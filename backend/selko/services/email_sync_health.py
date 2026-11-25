"""Safe, deduplicated health incidents for durable email polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
import time
from datetime import datetime, timezone
from typing import Protocol

import requests

from selko.config import Config
from selko.db import email_sync, ops
from selko.db.connection import Database

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SafeIncident:
    incident_key: str
    provider: str
    incident_type: str
    severity: str
    safe_summary: str
    first_seen_at: str | None = None
    last_success_at: str | None = None
    user_id: str | None = None


class OperationalNotifier(Protocol):
    async def send_incident_opened(self, incident: SafeIncident) -> None: ...
    async def send_incident_resolved(self, incident: SafeIncident) -> None: ...


class ResendOperationalNotifier:
    """Minimal Resend transactional-email adapter with safe payloads only."""

    def __init__(self, config: Config):
        self.config = config

    @classmethod
    def is_configured(cls, config: Config) -> bool:
        """Whether every credential this adapter needs is present.

        Email delivery is optional: incidents are always recorded in
        `operational_incidents`. Callers should skip constructing a notifier
        rather than let every evaluation cycle fail and log a traceback.
        """
        return bool(
            config.operational_notification_api_key
            and config.operational_notification_sender
            and config.operational_notification_recipient
        )

    async def _send(self, incident: SafeIncident, *, resolved: bool) -> None:
        if not self.is_configured(self.config):
            raise RuntimeError("Operational notifier is not configured")
        state = "resolved" if resolved else "opened"
        body = (
            f"Environment: {self.config.environment}\n"
            f"Provider: {incident.provider}\n"
            f"Incident: {incident.incident_type}\n"
            f"Severity: {incident.severity}\n"
            f"Status: {state}\n"
            f"Summary: {incident.safe_summary}\n"
            "Remediation: verify provider connectivity or reconnect OAuth."
        )
        payload = {
            "from": self.config.operational_notification_sender,
            "to": [self.config.operational_notification_recipient],
            "subject": f"Selko email sync {incident.severity}: {incident.provider} {state}",
            "text": body,
        }
        response = await asyncio.to_thread(
            requests.post,
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {self.config.operational_notification_api_key}"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    async def send_incident_opened(self, incident: SafeIncident) -> None:
        await self._send(incident, resolved=False)

    async def send_incident_resolved(self, incident: SafeIncident) -> None:
        await self._send(incident, resolved=True)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class EmailSyncHealthEvaluator:
    def __init__(self, client: Database, config: Config, notifier: OperationalNotifier | None = None):
        self.client = client
        self.config = config
        self.notifier = notifier
        # Monotonic, so a clock adjustment cannot make the floor fire early or
        # never. None means "has not run since this process started".
        self._last_evaluated_monotonic: float | None = None

    def seconds_since_last_evaluation(self) -> float | None:
        """Seconds since evaluate_once last completed, or None if never."""
        if self._last_evaluated_monotonic is None:
            return None
        return time.monotonic() - self._last_evaluated_monotonic

    def _incident(self, state: dict, incident_type: str, severity: str, summary: str) -> SafeIncident:
        key = f"email-sync:{state['integration_id']}:{incident_type}"
        return SafeIncident(key, state.get("provider", "email"), incident_type, severity, summary,
                            state.get("last_started_at"), state.get("last_success_at"), state.get("user_id"))

    async def evaluate_once(self) -> int:
        states = email_sync.all_states(self.client)
        # Polling incidents apply only to integrations we are actually polling.
        #
        # An expired integration is intentionally not claimable, so its poll age
        # grows without bound and stale_poll fires forever. Production ran for
        # 18 days with a critical stale_poll incident raised against a Gmail
        # integration whose OAuth had expired: it pinned /health to 'degraded'
        # permanently while the only healthy signal -- reconnect the account --
        # was already carried by the integration's own status and the
        # ConnectionRecovery card.
        #
        # This is the same scope migration 20260827000001 applied to
        # integrations_due and oldest_next_poll_seconds, whose comment reads:
        # "Expired integrations are intentionally not claimable, so an old
        # next_poll_at on one must not make the whole service report degraded."
        # The incident evaluator never got that fix.
        #
        # Dead-letter incidents below are deliberately still evaluated for every
        # integration: data needing repair does not stop needing repair because
        # a token lapsed.
        active_integration_ids = {
            integration_id
            for integration_id, status in email_sync.integration_statuses(self.client).items()
            if status == "active"
        }
        now = datetime.now(timezone.utc)
        expected: dict[str, SafeIncident] = {}
        for state in states:
            if state.get("integration_id") not in active_integration_ids:
                continue
            last_success = _parse_datetime(state.get("last_success_at"))
            last_started = _parse_datetime(state.get("last_started_at"))
            # 7b: an integration whose first poll is still running (last_started set,
            # last_success still null) must not open a stale_poll incident immediately.
            # Hardcoding age = warning+1 did exactly that — every new connection
            # generated an opened+resolved pair once the notifier is configured.
            in_initial_grace = False
            if last_success is None and last_started is None:
                in_initial_grace = True
                continue  # initial grace: no coordinator claim yet
            if last_success is None:
                # First poll in flight: grace until last_started itself is stale
                age = (now - last_started).total_seconds() if last_started else 0
                if age < self.config.email_health_warning_seconds:
                    in_initial_grace = True
                    continue
            else:
                age = (now - last_success).total_seconds()
            if not in_initial_grace:
                if age >= self.config.email_health_critical_seconds:
                    incident = self._incident(state, "stale_poll", "critical", "Normal email polling has been stale for over one hour")
                    expected[incident.incident_key] = incident
                elif age >= self.config.email_health_warning_seconds:
                    incident = self._incident(state, "stale_poll", "warning", "Normal email polling has been stale for over thirty minutes")
                    expected[incident.incident_key] = incident
            # R7: inside initial grace, consecutive failures are not yet "repeated"
            if not in_initial_grace and (state.get("consecutive_failures") or 0) >= 3:
                incident = self._incident(state, "repeated_failures", "critical", "Three consecutive email polling runs failed")
                expected[incident.incident_key] = incident

        # Two grouped scans, not two counts *per state* per cycle: a fixed
        # number of queries regardless of how many integrations exist.
        dead_item_integrations = email_sync.dead_letter_item_integration_ids(self.client)
        dead_attachment_integrations = email_sync.dead_letter_attachment_integration_ids(self.client)

        for state in states:
            integration_id = state["integration_id"]
            if integration_id in dead_item_integrations:
                incident = self._incident(state, "acquisition_dead_letter", "warning", "One or more email acquisition items require repair")
                expected[incident.incident_key] = incident
            if integration_id in dead_attachment_integrations:
                incident = self._incident(state, "attachment_dead_letter", "warning", "One or more supported attachments require repair")
                expected[incident.incident_key] = incident

        for incident in expected.values():
            # Read-then-insert-or-reopen in one transaction.
            _, previous_status = ops.raise_incident(
                self.client,
                incident_key=incident.incident_key,
                integration_id=incident.incident_key.split(":")[1],
                user_id=incident.user_id,
                incident_type=incident.incident_type,
                severity=incident.severity,
                safe_summary=incident.safe_summary,
            )
            # Notify on a new incident, and again when a resolved one re-opens.
            if self.notifier and previous_status in (None, "resolved"):
                try:
                    await self.notifier.send_incident_opened(incident)
                    ops.update_incident(
                        self.client, incident.incident_key,
                        {"opened_notification_sent_at": now.isoformat()},
                    )
                except Exception:
                    logger.exception("Operational incident notification failed")

        # 6e: scope the resolution sweep to email-sync:* so the first non-email
        # subsystem to write to operational_incidents does not have its incidents
        # silently auto-resolved by this evaluator. The table name is generic;
        # an unscoped sweep would resolve any open row not in this evaluator's
        # `expected` set, including foreign subsystems'.
        open_rows = ops.open_incidents(self.client, "email-sync:")
        for row in open_rows:
            if row.get("incident_key") in expected:
                continue
            ops.update_incident_by_id(
                self.client, row["id"],
                {"status": "resolved", "resolved_at": now.isoformat(), "last_seen_at": now.isoformat()},
            )
            if self.notifier and not row.get("resolved_notification_sent_at"):
                incident = SafeIncident(row["incident_key"], "email", row.get("incident_type", "email_sync"), row.get("severity", "warning"), row.get("safe_summary", "Email polling recovered"))
                try:
                    await self.notifier.send_incident_resolved(incident)
                    ops.update_incident_by_id(
                        self.client, row["id"], {"resolved_notification_sent_at": now.isoformat()}
                    )
                except Exception:
                    logger.exception("Operational recovery notification failed")
        self._last_evaluated_monotonic = time.monotonic()
        return len(expected)

    async def run(self, stop_event: asyncio.Event) -> None:
        # ``evaluate_once`` issues many DB calls; a single transient failure
        # must not kill the health evaluator (it watches the ingestion loops
        # and would die from the same blip). Wrap each cycle so the evaluator
        # keeps ticking after a failed evaluation.
        while not stop_event.is_set():
            try:
                await self.evaluate_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Email sync health evaluation failed; continuing")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=max(self.config.email_health_interval_seconds, 1))
            except asyncio.TimeoutError:
                pass
