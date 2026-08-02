"""Safe, deduplicated health incidents for durable email polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import requests
from supabase import Client

from selko.config import Config

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

    async def _send(self, incident: SafeIncident, *, resolved: bool) -> None:
        if not (
            self.config.operational_notification_api_key
            and self.config.operational_notification_sender
            and self.config.operational_notification_recipient
        ):
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
    def __init__(self, client: Client, config: Config, notifier: OperationalNotifier | None = None):
        self.client = client
        self.config = config
        self.notifier = notifier

    def _incident(self, state: dict, incident_type: str, severity: str, summary: str) -> SafeIncident:
        key = f"email-sync:{state['integration_id']}:{incident_type}"
        return SafeIncident(key, state.get("provider", "email"), incident_type, severity, summary,
                            state.get("last_started_at"), state.get("last_success_at"), state.get("user_id"))

    async def evaluate_once(self) -> int:
        states = self.client.table("email_sync_state").select("*").execute().data or []
        now = datetime.now(timezone.utc)
        expected: dict[str, SafeIncident] = {}
        for state in states:
            last_success = _parse_datetime(state.get("last_success_at"))
            last_started = _parse_datetime(state.get("last_started_at"))
            age = (now - last_success).total_seconds() if last_success else self.config.email_health_warning_seconds + 1
            if last_success is None and last_started is None:
                continue  # initial grace period before the first coordinator claim
            if age >= self.config.email_health_critical_seconds:
                incident = self._incident(state, "stale_poll", "critical", "Normal email polling has been stale for over one hour")
                expected[incident.incident_key] = incident
            elif age >= self.config.email_health_warning_seconds:
                incident = self._incident(state, "stale_poll", "warning", "Normal email polling has been stale for over thirty minutes")
                expected[incident.incident_key] = incident
            if (state.get("consecutive_failures") or 0) >= 3:
                incident = self._incident(state, "repeated_failures", "critical", "Three consecutive email polling runs failed")
                expected[incident.incident_key] = incident

        for state in states:
            dead_items = self.client.table("email_ingestion_items").select("id", count="exact").eq("integration_id", state["integration_id"]).eq("acquisition_status", "dead_letter").execute()
            if getattr(dead_items, "count", 0):
                incident = self._incident(state, "acquisition_dead_letter", "warning", "One or more email acquisition items require repair")
                expected[incident.incident_key] = incident
            # Scope to this integration's own mail. An unscoped count would
            # raise the same incident on every integration in the deployment.
            dead_attachments = (
                self.client.table("attachments")
                .select("id, emails!inner(integration_id)", count="exact")
                .eq("emails.integration_id", state["integration_id"])
                .eq("ingestion_status", "dead_letter")
                .execute()
            )
            if getattr(dead_attachments, "count", 0):
                incident = self._incident(state, "attachment_dead_letter", "warning", "One or more supported attachments require repair")
                expected[incident.incident_key] = incident

        for incident in expected.values():
            existing = self.client.table("operational_incidents").select("*").eq("incident_key", incident.incident_key).maybe_single().execute().data
            if not existing:
                self.client.table("operational_incidents").insert({
                    "incident_key": incident.incident_key,
                    "integration_id": incident.incident_key.split(":")[1],
                    "user_id": incident.user_id,
                    "incident_type": incident.incident_type,
                    "severity": incident.severity,
                    "status": "open",
                    "safe_summary": incident.safe_summary,
                }).execute()
                if self.notifier:
                    try:
                        await self.notifier.send_incident_opened(incident)
                        self.client.table("operational_incidents").update({"opened_notification_sent_at": now.isoformat()}).eq("incident_key", incident.incident_key).execute()
                    except Exception:
                        logger.exception("Operational incident notification failed")
            else:
                self.client.table("operational_incidents").update({
                    "status": "open", "severity": incident.severity, "safe_summary": incident.safe_summary,
                    "last_seen_at": now.isoformat(), "resolved_at": None,
                    "opened_notification_sent_at": None if existing.get("status") == "resolved" else existing.get("opened_notification_sent_at"),
                    # A re-opened incident must be able to send a second
                    # recovery notification when it resolves again.
                    "resolved_notification_sent_at": None if existing.get("status") == "resolved" else existing.get("resolved_notification_sent_at"),
                }).eq("incident_key", incident.incident_key).execute()
                if self.notifier and existing.get("status") == "resolved":
                    try:
                        await self.notifier.send_incident_opened(incident)
                        self.client.table("operational_incidents").update({"opened_notification_sent_at": now.isoformat()}).eq("incident_key", incident.incident_key).execute()
                    except Exception:
                        logger.exception("Operational incident re-open notification failed")

        open_rows = self.client.table("operational_incidents").select("*").eq("status", "open").execute().data or []
        for row in open_rows:
            if row.get("incident_key") in expected:
                continue
            self.client.table("operational_incidents").update({"status": "resolved", "resolved_at": now.isoformat(), "last_seen_at": now.isoformat()}).eq("id", row["id"]).execute()
            if self.notifier and not row.get("resolved_notification_sent_at"):
                incident = SafeIncident(row["incident_key"], "email", row.get("incident_type", "email_sync"), row.get("severity", "warning"), row.get("safe_summary", "Email polling recovered"))
                try:
                    await self.notifier.send_incident_resolved(incident)
                    self.client.table("operational_incidents").update({"resolved_notification_sent_at": now.isoformat()}).eq("id", row["id"]).execute()
                except Exception:
                    logger.exception("Operational recovery notification failed")
        return len(expected)

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await self.evaluate_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=max(self.config.email_health_interval_seconds, 1))
            except asyncio.TimeoutError:
                pass
