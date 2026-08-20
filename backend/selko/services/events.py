"""Events service for event extraction, deduplication, and management."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from supabase import Client

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.config import Config
from selko.services import calendars, event_processing, ics_parser
from selko.services.event_diff import (
    EventChangeSet,
    apply_asserted_fields,
    baseline_from_gcal_event,
    compute_change_set,
    gate_stale_email_material_changes,
    proposed_fields_from_change_set,
    resolve_description_append,
)
from selko.services.calendar_policy import materialize_all_day_event
from selko.services.civil_time import ensure_aware, resolve_zone
from selko.services.event_identity import IdentityHint, build_hints
from selko.services.llm_gateway import LLMGateway
from selko.services.retry_utils import calculate_retry_delay
from selko.services.resolution_fingerprint import candidate_fingerprint
from selko.services.resolution_metrics import resolution_metrics

logger = logging.getLogger(__name__)


class EventsError(Exception):
    """Raised when event operations fail."""

    pass


class ResolutionConflictExhausted(EventsError):
    """Raised after repeated candidate-band conflicts."""


MAX_RESOLUTION_ATTEMPTS = 3


@dataclass(frozen=True)
class CandidateWindow:
    """The exact local-day candidate band seen by a resolver."""

    window_start: str
    window_end: str
    fingerprint: str
    hint_keys: tuple[str, ...] = ()
    hint_fingerprint: Optional[str] = None


@dataclass
class EventMatch:
    """A dedup match against a local Selko event or Google Calendar event."""

    match_id: str
    baseline: dict[str, Any]
    gcal_raw: Optional[dict[str, Any]] = None
    candidate_window: Optional[CandidateWindow] = None
    stale_authoritative: bool = False
    ambiguous: bool = False

    @property
    def is_gcal(self) -> bool:
        return self.match_id.startswith("gcal:")

    @property
    def gcal_id(self) -> Optional[str]:
        if self.is_gcal:
            return self.match_id[5:]
        return None


def _commit_email_extraction(
    supabase_client: Client,
    email_id: str,
    locked_by: str,
    lock_generation: int,
    decisions: list[dict[str, Any]],
    terminal: str = "processed",
) -> dict[str, Any]:
    """Commit one extraction envelope through the lease-fenced RPC."""
    response = supabase_client.rpc(
        "commit_email_extraction",
        {
            "p_email_id": email_id,
            "p_worker_id": locked_by,
            "p_generation": lock_generation,
            "p_decisions": decisions,
            "p_terminal": terminal,
        },
    ).execute()
    result = response.data
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        raise EventsError("commit_email_extraction returned an invalid result")
    if result.get("fenced"):
        resolution_metrics.record_fenced_write()
        logger.warning(
            "Extraction commit fenced for email %s (worker=%s generation=%s)",
            email_id,
            locked_by,
            lock_generation,
        )
    return result


def _window_fields(window: Optional[CandidateWindow]) -> dict[str, Any]:
    if window is None:
        return {}
    fields: dict[str, Any] = {
        "window_start": window.window_start,
        "window_end": window.window_end,
        "expected_fingerprint": window.fingerprint,
    }
    if window.hint_keys:
        fields["hint_keys"] = list(window.hint_keys)
        fields["expected_hint_fingerprint"] = window.hint_fingerprint or ""
    return fields


def mark_email_status(
    supabase_client: Client,
    email_id: str,
    status: str,
    error: Optional[str] = None,
    *,
    outcome: Optional[str] = None,
    explanation: Optional[str] = None,
    result: Optional[dict[str, Any]] = None,
) -> None:
    """Update email processing status.

    Args:
        supabase_client: Authenticated Supabase client.
        email_id: UUID of email to update.
        status: New processing status (processing, processed, skipped, failed).
        error: Optional error message (only used for failed status).
    """
    update_data: dict[str, Any] = {"processing_status": status}
    if status == "processing":
        update_data["processed_at"] = datetime.now(timezone.utc).isoformat()
        update_data["processing_error"] = None
        update_data["processing_outcome"] = None
        update_data["processing_explanation"] = None
        update_data["processing_result"] = None
    elif status == "failed":
        update_data["processing_error"] = error
    elif status == "processed":
        update_data["processing_error"] = None
    if outcome is not None:
        update_data["processing_outcome"] = outcome
    if explanation is not None:
        update_data["processing_explanation"] = explanation
    if result is not None:
        update_data["processing_result"] = result
    supabase_client.table("emails").update(update_data).eq("id", email_id).execute()


def should_skip_email(
    supabase_client: Client, user_id: str, sender_email: str
) -> bool:
    """Check if sender is ignored and email should be skipped.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        sender_email: Email address of sender.

    Returns:
        True if sender has an "ignore" rule.
    """
    sender_rule = check_sender_rules(supabase_client, user_id, sender_email)
    return bool(sender_rule and sender_rule.get("action") == "ignore")


def get_user_timezone(supabase_client: Client, user_id: str) -> str:
    """Get user's IANA timezone from calendar settings.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.

    Returns:
        IANA timezone string (e.g., "America/New_York"). Defaults to
        "America/New_York" if not set.
    """
    try:
        result = supabase_client.table("user_calendar_settings").select(
            "timezone"
        ).eq("user_id", user_id).execute()

        if result.data:
            return result.data[0].get("timezone") or "America/New_York"
    except Exception as e:
        logger.warning(f"Failed to fetch user timezone: {e}")

    return "America/New_York"


def normalize_event_data(
    event: CalendarEvent,
    user_timezone: str = "America/New_York",
    *,
    treat_as_civil: bool = True,
) -> dict[str, Any]:
    """Convert a CalendarEvent to a DB-ready dict.

    LLM extractions (``treat_as_civil=True``, default): datetimes are local
    wall-clock times. Any offset the model invents (e.g. ``+00:00``) is
    stripped and the clock face is attached to ``user_timezone``.

    Trusted sources such as ICS (``treat_as_civil=False``): already-aware
    datetimes keep their absolute instant; naive ones use ``user_timezone``.

    Args:
        event: Extracted CalendarEvent.
        user_timezone: IANA timezone for civil localization.
        treat_as_civil: Whether to interpret datetimes as wall-clock local.

    Returns:
        Dict with isoformat datetimes suitable for DB insertion.
    """
    from selko.services.civil_time import to_storage_iso

    all_day = getattr(event, "all_day", False)
    start_iso = to_storage_iso(
        event.start_datetime, user_timezone, treat_as_civil=treat_as_civil
    )
    end_iso = to_storage_iso(
        event.end_datetime, user_timezone, treat_as_civil=treat_as_civil
    )
    if not all_day and start_iso:
        end_iso = ensure_min_duration(start_iso, end_iso)

    return {
        "title": event.title,
        "start_datetime": start_iso,
        "end_datetime": end_iso,
        "all_day": all_day,
        "location": event.location,
        "description": event.description,
        "source_quote": getattr(event, "source_quote", ""),
        "importance": getattr(event, "importance", "action_required"),
        "recurrence_rule": getattr(event, "recurrence_rule", None),
    }


def ensure_min_duration(start_iso: str, end_iso: Optional[str]) -> str:
    """Give zero-length or missing-end timed events a 1-hour default duration."""
    start_dt = datetime.fromisoformat(start_iso)
    if end_iso:
        end_dt = datetime.fromisoformat(end_iso)
        if end_dt > start_dt:
            return end_iso
    return (start_dt + timedelta(hours=1)).isoformat()


def _fetch_baseline_info_date(
    supabase_client: Client, event_id: str
) -> Optional[str]:
    """Newest ``emails.date_sent`` across a local event's non-undone sources.

    Used as the "current information" recency baseline for propose_event_update.
    """
    try:
        result = (
            supabase_client.table("event_sources")
            .select("emails(date_sent)")
            .eq("event_id", event_id)
            .eq("is_undone", False)
            .execute()
        )
    except Exception as e:
        logger.debug("Could not fetch baseline info date for %s: %s", event_id, e)
        return None
    dates = [
        (row.get("emails") or {}).get("date_sent")
        for row in (result.data or [])
    ]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _load_identity_context(
    supabase_client: Client,
    email_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load only metadata needed to derive content-free identity hints."""
    email: dict[str, Any] = {}
    components: list[dict[str, Any]] = []
    try:
        result = supabase_client.table("emails").select(
            "email_provider,thread_id,subject,body_text,body_html"
        ).eq("id", email_id).limit(1).execute()
        if isinstance(result.data, list) and result.data:
            email = result.data[0] or {}
        elif isinstance(result.data, dict):
            email = result.data
    except Exception as exc:
        logger.debug("Could not load email identity metadata (%s)", type(exc).__name__)
    try:
        result = supabase_client.table("email_calendar_components").select(
            "component_index,uid_hash,recurrence_id,sequence,dtstamp"
        ).eq("email_id", email_id).order("component_index").execute()
        if isinstance(result.data, list):
            components = [row for row in result.data if isinstance(row, dict)]
    except Exception as exc:
        logger.debug("Could not load calendar identity components (%s)", type(exc).__name__)
    return email, components


def _identity_hints_for_event(
    email: dict[str, Any],
    components: list[dict[str, Any]],
    event_index: int,
    event_data: dict[str, Any],
) -> list[IdentityHint]:
    component = components[event_index] if event_index < len(components) else None
    return build_hints(
        provider=email.get("email_provider"),
        thread_id=email.get("thread_id"),
        calendar_components=[component] if component else [],
        event_values=(
            event_data.get("location"),
            event_data.get("description"),
            email.get("subject"),
            email.get("body_text"),
            email.get("body_html"),
        ),
    )


def save_extracted_events(
    supabase_client: Client,
    gateway: LLMGateway,
    user_id: str,
    email_id: str,
    extraction: CalendarEventExtraction,
    initial_status: str = "pending_review",
    current_time: Optional[datetime] = None,
    *,
    treat_as_civil: bool = True,
    email_date_sent: Optional[str] = None,
    locked_by: str = "",
    lock_generation: int = 0,
    commit_result: Optional[dict[str, Any]] = None,
    cancellation_mode: bool = False,
    _attempt: int = 0,
) -> tuple[int, int]:
    """Deduplicate and persist extracted events into New or Changes lanes.

    Routing:
    - No match → New lane (``pending_review``), or auto-approved when requested.
    - Match + noop changeset → silent skip.
    - Match + real change → Changes lane (``pending_change``), or apply immediately
      when ``initial_status == "approved"`` (sender auto_approve).
    Args:
        supabase_client: Authenticated Supabase client.
        gateway: LLMGateway instance for LLM operations.
        user_id: UUID of user.
        email_id: UUID of source email.
        extraction: LLM extraction result containing events.
        initial_status: Status for newly created events (default: pending_review).
        current_time: Optional current time override for deterministic testing.
        treat_as_civil: Interpret datetimes as local wall times (LLM). False for ICS.
        email_date_sent: When this email was sent, for update-proposal recency rules.

    Returns:
        Tuple of (num_new, num_updated) event counts. Skips are not counted.
    """
    num_new = 0
    num_updated = 0
    cancellation_outcomes: list[str] = []
    decisions: list[dict[str, Any]] = []
    identity_email, identity_components = _load_identity_context(
        supabase_client, email_id
    )
    # Load timezone + all-day policy once per email (lean; no GCal list).
    all_day_policy, user_timezone = calendars.get_all_day_policy_and_timezone(
        supabase_client, user_id
    )
    auto_apply = initial_status == "approved"

    try:
        user_tz = ZoneInfo(user_timezone)
    except (KeyError, ValueError):
        user_tz = ZoneInfo("America/New_York")
    if current_time is None:
        now = datetime.now(user_tz)
    elif current_time.tzinfo is None:
        now = current_time.replace(tzinfo=user_tz)
    else:
        now = current_time.astimezone(user_tz)
    cutoff = now - timedelta(hours=24)

    for event_index, event in enumerate(extraction.events):
        source_event_data = normalize_event_data(
            event, user_timezone=user_timezone, treat_as_civil=treat_as_civil
        )
        # Materialized form drives dedup + events row; source stays in extracted_data.
        event_data = materialize_all_day_event(
            source_event_data, all_day_policy, user_timezone
        )

        if not event_data.get("start_datetime") and not cancellation_mode:
            logger.info(
                "Skipping event with no start_datetime: %s", event_data.get("title")
            )
            continue

        start_str = event_data.get("start_datetime")
        if start_str:
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=user_tz)
                if start_dt < cutoff and not cancellation_mode:
                    logger.info(f"Skipping past event: {event_data.get('title')} ({start_str})")
                    continue
            except (ValueError, TypeError):
                pass

        identity_hints = _identity_hints_for_event(
            identity_email, identity_components, event_index, event_data
        )
        resolution = find_matching_event(
            supabase_client, gateway, user_id, event_data,
            user_timezone=user_timezone,
            with_window=True,
            identity_hints=identity_hints,
            strict_identity=cancellation_mode,
        )
        if isinstance(resolution, tuple):
            match, candidate_window = resolution
        else:
            match = resolution
            candidate_window = getattr(match, "candidate_window", None)

        if cancellation_mode and match is not None and match.ambiguous:
            cancellation_outcomes.append("cancellation_ambiguous")
            continue

        if match is not None and match.stale_authoritative:
            logger.info(
                "Stale authoritative calendar identity is an audited no-op for event %s",
                event_data.get("title"),
            )
            if cancellation_mode:
                cancellation_outcomes.append("cancellation_unmatched")
            continue

        hint_payload = [hint.as_payload() for hint in identity_hints]

        if cancellation_mode:
            # A provider-only event has no Selko queue row or fenced owner. It
            # is safe to audit as unmatched, but never create a local shadow
            # row merely to gain permission to delete someone else's event.
            if match is not None and match.is_gcal:
                cancellation_outcomes.append("cancellation_unmatched")
                continue
            if match is None:
                cancellation_outcomes.append("cancellation_unmatched")
                continue

            status = str(match.baseline.get("status") or "")
            if status == "rejected":
                next_status = "rejected"
                next_action = match.baseline.get("calendar_sync_action", "upsert")
            elif status in {"synced", "syncing", "sync_failed", "approved", "cancel_queued"}:
                next_status = "cancel_queued"
                next_action = "cancel"
            else:
                next_status = "cancelled"
                next_action = match.baseline.get("calendar_sync_action", "upsert")

            decisions.append({
                "action": "update",
                "event_id": match.match_id,
                "fields": {
                    "status": next_status,
                    "calendar_sync_action": next_action,
                },
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": {
                    "email_id": email_id,
                    "extracted_data": source_event_data,
                    "source_type": "cancellation",
                    "event_snapshot_before": match.baseline,
                    "change_set": {
                        "kind": "cancellation",
                        "changes": [{
                            "field": "status",
                            "before": status,
                            "after": next_status,
                            "reason": "organizer cancellation",
                        }],
                        "reasoning": "Structured or strong cancellation matched an existing event.",
                    },
                    "replace_pending_proposal": True,
                },
            })
            num_updated += 1
            cancellation_outcomes.append("event_cancelled")
            continue

        if match is None:
            decisions.append({
                "action": "create",
                "event_id": None,
                "fields": {**event_data, "status": initial_status},
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": {
                    "email_id": email_id,
                    "extracted_data": source_event_data,
                    "source_type": "new_invitation",
                },
            })
            num_new += 1
            continue

        # LLM proposes what to update; code gate drops no-ops
        baseline_info_date = (
            None if match.is_gcal
            else _fetch_baseline_info_date(supabase_client, match.match_id)
        )
        try:
            change_set = event_processing.propose_event_update(
                gateway,
                match.baseline,
                event_data,
                user_timezone=user_timezone,
                email_date_sent=email_date_sent,
                baseline_info_date=baseline_info_date,
            )
        except Exception as e:
            logger.warning(
                "propose_event_update failed for match %s, falling back to deterministic diff: %s",
                match.match_id,
                e,
            )
            change_set = compute_change_set(
                match.baseline, event_data, user_timezone=user_timezone
            )

        change_set = gate_stale_email_material_changes(
            change_set, email_date_sent, baseline_info_date
        )
        change_set = resolve_description_append(change_set, match.baseline)

        if change_set.kind == "noop":
            logger.info(
                "Skipping noop rediscovery for match %s (%s)",
                match.match_id,
                event_data.get("title"),
            )
            continue

        source_type = (
            "cancellation" if change_set.kind == "cancellation" else "update"
        )
        # Persist only the fields the gated changeset says to change.
        # Localize propose after-values onto the change_set so apply_pending_change
        # writes storage-ready datetimes (extracted_data keeps source truth).
        from selko.services.civil_time import to_storage_iso

        for change in change_set.changes:
            if change.field in ("start_datetime", "end_datetime") and change.after is not None:
                change.after = to_storage_iso(
                    change.after, user_timezone, treat_as_civil=True
                )

        proposed_fields = proposed_fields_from_change_set(match.baseline, change_set)
        if (
            "start_datetime" in proposed_fields
            and "end_datetime" in proposed_fields
            and proposed_fields["start_datetime"]
            and not proposed_fields.get("all_day", match.baseline.get("all_day", False))
        ):
            fixed_end = ensure_min_duration(
                proposed_fields["start_datetime"], proposed_fields["end_datetime"]
            )
            for change in change_set.changes:
                if change.field == "end_datetime":
                    change.after = fixed_end

        # extracted_data keeps LLM source truth; change_set carries materialized deltas.
        source = {
            "email_id": email_id,
            "extracted_data": source_event_data,
            "source_type": source_type,
            "event_snapshot_before": match.baseline,
            "change_set": change_set.model_dump_jsonable(),
        }

        if auto_apply and match.is_gcal:
            applied = apply_asserted_fields(match.baseline, proposed_fields)
            decisions.append({
                "action": "create",
                "event_id": None,
                "fields": {
                    **applied,
                    "status": "approved",
                    "google_calendar_event_id": match.gcal_id,
                },
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": {
                    **source,
                    "extra_sources": [{
                        "source_origin": "google_calendar",
                        "google_calendar_source_event_id": match.gcal_id,
                        "source_type": source_type,
                        "extracted_data": {"google_calendar_event_id": match.gcal_id},
                        "change_set": change_set.model_dump_jsonable(),
                    }],
                },
            })
        elif match.is_gcal:
            decisions.append({
                "action": "create",
                "event_id": None,
                    "fields": {
                    **match.baseline,
                    "status": "pending_change",
                    "google_calendar_event_id": match.gcal_id,
                },
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": {
                    **source,
                    "extra_sources": [{
                        "source_origin": "google_calendar",
                        "google_calendar_source_event_id": match.gcal_id,
                        "source_type": source_type,
                        "extracted_data": {"google_calendar_event_id": match.gcal_id},
                        "change_set": change_set.model_dump_jsonable(),
                    }],
                },
            })
        elif match.baseline.get("status") == "pending_review":
            decisions.append({
                "action": "update",
                "event_id": match.match_id,
                "fields": proposed_fields,
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": source,
            })
        elif auto_apply:
            applied = apply_asserted_fields(match.baseline, proposed_fields)
            decisions.append({
                "action": "update",
                "event_id": match.match_id,
                "fields": {**applied, "status": "approved"},
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": {**source, "replace_pending_proposal": True},
            })
        else:
            decisions.append({
                "action": "update",
                "event_id": match.match_id,
                "fields": {"status": "pending_change"},
                **_window_fields(candidate_window),
                "hints": hint_payload,
                "source": {**source, "replace_pending_proposal": True},
            })
        num_updated += 1

    outcome = _commit_email_extraction(
        supabase_client,
        email_id,
        locked_by,
        lock_generation,
        decisions,
    )
    if outcome.get("conflict"):
        resolution_metrics.record_conflict()
        if _attempt + 1 >= MAX_RESOLUTION_ATTEMPTS:
            resolution_metrics.record_retries_per_email(MAX_RESOLUTION_ATTEMPTS)
            resolution_metrics.record_conflict_exhaustion()
            raise ResolutionConflictExhausted(
                f"Resolution conflicts exhausted for email {email_id}"
            )
        logger.info(
            "Resolution conflict for email %s; recomputing (attempt %s/%s)",
            email_id,
            _attempt + 1,
            MAX_RESOLUTION_ATTEMPTS,
        )
        if commit_result is not None:
            commit_result.clear()
        return save_extracted_events(
            supabase_client,
            gateway,
            user_id,
            email_id,
            extraction,
            initial_status=initial_status,
            current_time=current_time,
            treat_as_civil=treat_as_civil,
            email_date_sent=email_date_sent,
            locked_by=locked_by,
            lock_generation=lock_generation,
            commit_result=commit_result,
            cancellation_mode=cancellation_mode,
            _attempt=_attempt + 1,
        )
    if commit_result is not None:
        commit_result.update(outcome)
        if cancellation_outcomes:
            commit_result["cancellation_outcomes"] = cancellation_outcomes
    if _attempt:
        resolution_metrics.record_retries_per_email(_attempt)
    return num_new, num_updated


def process_email_for_events(
    supabase_client: Client,
    gateway: LLMGateway,
    email_id: str,
    user_id: str,
    config: Optional[Config] = None,
    email_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Main pipeline function to extract events from an email.

    If email_row is supplied, the extra SELECT in fetch_email_with_attachments
    is skipped — Inc1 payload fix; workers already have the claimed row.

    Orchestrates sender checking, LLM extraction, dedup, and persistence.

    Args:
        supabase_client: Authenticated Supabase client.
        gateway: LLMGateway instance for LLM operations.
        email_id: UUID of email to process.
        user_id: UUID of user who owns the email.
        config: Optional Config for per-type attachment limits.

    Returns:
        Dict with processing results (num_events, num_new, num_updated).

    Raises:
        EventsError: If processing fails.
    """
    gateway.for_user(user_id).for_email(email_id)
    locked_by = str((email_row or {}).get("locked_by") or "")
    lock_generation = int((email_row or {}).get("lock_generation") or 0)

    try:
        mark_email_status(supabase_client, email_id, "processing")

        email_metadata, email_text, attachments = event_processing.fetch_email_with_attachments(
            supabase_client, email_id, email_row=email_row
        )

        # Inject user timezone for timezone-aware current_date in prompt
        email_metadata["user_timezone"] = get_user_timezone(supabase_client, user_id)

        sender_email = email_metadata.get("from_email", "")

        # Check sender rules: ignore, auto_approve, or no rule
        sender_rule = check_sender_rules(supabase_client, user_id, sender_email)
        rule_action = sender_rule.get("action") if sender_rule else None

        if rule_action == "ignore":
            logger.info(f"Sender {sender_email} is ignored, skipping event extraction")
            commit = _commit_email_extraction(
                supabase_client, email_id, locked_by, lock_generation, [], "skipped"
            )
            if commit.get("fenced"):
                return {"num_events": 0, "num_new": 0, "num_updated": 0, "skipped": True, "fenced": True}
            mark_email_status(supabase_client, email_id, "skipped")
            return {"num_events": 0, "num_new": 0, "num_updated": 0, "skipped": True}

        # Determine initial status based on sender rule
        if rule_action == "auto_approve":
            initial_status = "approved"
            logger.info(f"Sender {sender_email} is auto-approved, events will be created as approved")
        else:
            initial_status = "pending_review"

        # Calendar invitation emails (meeting requests, updates, RSVPs) are
        # already handled by the user's email client and calendar. Organizer
        # cancellations are the exception: they enter the cancellation state
        # machine so a known event is terminalized or queued for the worker.
        invite_method = ics_parser.detect_invite_method(attachments)
        structured_cancellation = invite_method == "CANCEL"
        if not structured_cancellation and email_metadata.get("is_calendar_invite"):
            try:
                component_result = supabase_client.table("email_calendar_components").select(
                    "method"
                ).eq("email_id", email_id).eq("method", "CANCEL").limit(1).execute()
                structured_cancellation = isinstance(component_result.data, list) and bool(
                    component_result.data
                )
            except Exception:
                logger.debug("Could not inspect structured cancellation components for %s", email_id)
        if (
            not structured_cancellation
            and (email_metadata.get("is_calendar_invite") or invite_method in ics_parser.INVITE_METHODS)
        ):
            result = {"num_events": 0, "num_new": 0, "num_updated": 0, "skipped": True}
            commit = _commit_email_extraction(
                supabase_client, email_id, locked_by, lock_generation, [], "skipped"
            )
            if commit.get("fenced"):
                result["fenced"] = True
                return result
            mark_email_status(
                supabase_client, email_id, "skipped",
                outcome="calendar_invite",
                explanation="Calendar invitation — already handled by your email client and calendar.",
                result=result,
            )
            return result

        # Try .ics direct parsing first (skips LLM)
        ics_extraction = ics_parser.parse_ics_attachments(attachments, email_metadata)
        from_ics = bool(ics_extraction and ics_extraction.events)
        if from_ics:
            extraction = ics_extraction
            if structured_cancellation:
                extraction = extraction.model_copy(update={"cancellation_detected": True})
            logger.info(f"Parsed {len(extraction.events)} events from .ics (skipped LLM)")
        else:
            extraction = event_processing.extract_calendar_events(
                gateway, email_text, email_metadata, attachments, config=config,
            )

        cancellation_mode = structured_cancellation or extraction.cancellation_detected
        if not extraction.events_found or not extraction.events:
            logger.info("No events found in email")
            result = {"num_events": 0, "num_new": 0, "num_updated": 0}
            commit = _commit_email_extraction(
                supabase_client, email_id, locked_by, lock_generation, [], "processed"
            )
            if commit.get("fenced"):
                result["fenced"] = True
                return result
            mark_email_status(
                supabase_client,
                email_id,
                "processed",
                outcome="cancellation_unmatched" if cancellation_mode else "no_event",
                explanation=(
                    "Cancellation did not contain enough identity to match an event."
                    if cancellation_mode else None
                ),
                result=result,
            )
            return result

        commit_result: dict[str, Any] = {}
        num_new, num_updated = save_extracted_events(
            supabase_client, gateway, user_id, email_id, extraction,
            initial_status=initial_status,
            treat_as_civil=not from_ics,
            email_date_sent=email_metadata.get("date_sent"),
            locked_by=locked_by,
            lock_generation=lock_generation,
            commit_result=commit_result,
            cancellation_mode=cancellation_mode,
        )
        if commit_result.get("fenced"):
            return {
                "num_events": len(extraction.events),
                "num_new": 0,
                "num_updated": 0,
                "fenced": True,
            }

        cancellation_outcomes = commit_result.get("cancellation_outcomes", [])
        if "event_cancelled" in cancellation_outcomes:
            outcome = "event_cancelled"
        elif "cancellation_ambiguous" in cancellation_outcomes:
            outcome = "cancellation_ambiguous"
        elif "cancellation_unmatched" in cancellation_outcomes:
            outcome = "cancellation_unmatched"
        elif num_new and num_updated:
            outcome = "event_created_and_updated"
        elif num_new:
            outcome = "event_created"
        elif num_updated:
            outcome = "event_updated"
        else:
            # Extraction found an event, but it matched an existing event and
            # produced no material change. This is distinct from no_event,
            # where extraction found nothing at all.
            outcome = "event_matched"
        result = {
            "num_events": len(extraction.events),
            "num_new": num_new,
            "num_updated": num_updated,
        }
        try:
            source_result = supabase_client.table("event_sources").select(
                "source_type"
            ).eq("email_id", email_id).eq("is_undone", False).execute()
            if any(row.get("source_type") == "cancellation" for row in (source_result.data or [])):
                outcome = "event_cancelled"
        except Exception:
            logger.debug("Could not determine cancellation outcome for %s", email_id)
        mark_email_status(
            supabase_client,
            email_id,
            "processed",
            outcome=outcome,
            result=result,
        )
        logger.info(f"Processed email {email_id}: {num_new} new, {num_updated} updated events")

        if rule_action == "auto_approve":
            result["auto_approved"] = True

        return result

    except Exception as e:
        mark_email_status(supabase_client, email_id, "failed", error=str(e))
        raise EventsError(f"Failed to process email for events: {e}") from e


def _identity_key(hint: IdentityHint) -> str:
    return f"{hint.kind}|{hint.value_hash}|{hint.recurrence_id}"


def _event_baseline(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": row.get("title"),
        "start_datetime": row.get("start_datetime"),
        "end_datetime": row.get("end_datetime"),
        "all_day": row.get("all_day", False),
        "location": row.get("location"),
        "description": row.get("description"),
        "importance": row.get("importance"),
        "status": row.get("status"),
        "calendar_sync_action": row.get("calendar_sync_action", "upsert"),
        "calendar_work_generation": row.get("calendar_work_generation", 0),
        "google_calendar_event_id": row.get("google_calendar_event_id"),
    }


def _load_identity_candidates(
    supabase_client: Client,
    user_id: str,
    hints: list[IdentityHint],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], str, tuple[str, ...]]:
    """Load hint rows and their events, returning a CAS fingerprint."""
    rows_by_key: dict[str, list[dict[str, Any]]] = {}
    keys = tuple(sorted({_identity_key(hint) for hint in hints}))
    for hint in hints:
        key = _identity_key(hint)
        try:
            result = supabase_client.table("event_identity_hints").select(
                "event_id,kind,value_hash,recurrence_id,strength,sequence,dtstamp"
            ).eq("user_id", user_id).eq("kind", hint.kind).eq(
                "value_hash", hint.value_hash
            ).eq("recurrence_id", hint.recurrence_id).execute()
            rows = result.data if isinstance(result.data, list) else []
            rows_by_key[key] = [row for row in rows if isinstance(row, dict)]
        except Exception as exc:
            logger.debug("Could not load identity candidates (%s)", type(exc).__name__)
            rows_by_key[key] = []

    event_ids = sorted({row.get("event_id") for rows in rows_by_key.values() for row in rows if row.get("event_id")})
    events_by_id: dict[str, dict[str, Any]] = {}
    if event_ids:
        try:
            result = supabase_client.table("events").select("*").eq(
                "user_id", user_id
            ).in_("id", event_ids).execute()
            events_by_id = {
                str(row["id"]): row
                for row in (result.data or [])
                if isinstance(row, dict) and row.get("id")
            }
        except Exception as exc:
            logger.debug("Could not load identity event candidates (%s)", type(exc).__name__)
    fingerprint = candidate_fingerprint(list(events_by_id.values()))
    return rows_by_key, events_by_id, fingerprint, keys


def _times_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    try:
        return (
            datetime.fromisoformat(str(left.get("start_datetime")).replace("Z", "+00:00"))
            == datetime.fromisoformat(str(right.get("start_datetime")).replace("Z", "+00:00"))
            and datetime.fromisoformat(str(left.get("end_datetime")).replace("Z", "+00:00"))
            == datetime.fromisoformat(str(right.get("end_datetime")).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return False


def _identity_match(
    rows_by_key: dict[str, list[dict[str, Any]]],
    events_by_id: dict[str, dict[str, Any]],
    hints: list[IdentityHint],
    event_data: dict[str, Any],
    candidate_window: CandidateWindow,
    strict_identity: bool = False,
) -> EventMatch | None:
    """Apply authoritative, exact-supporting, then two-signal matching."""
    authoritative = [hint for hint in hints if hint.kind == "ical_uid"]
    for hint in authoritative:
        rows = rows_by_key.get(_identity_key(hint), [])
        event_ids = {str(row.get("event_id")) for row in rows if row.get("event_id") in events_by_id}
        if strict_identity and len(event_ids) > 1:
            return EventMatch(
                match_id="",
                baseline={},
                candidate_window=candidate_window,
                ambiguous=True,
            )
        if len(event_ids) != 1:
            continue
        event_id = next(iter(event_ids))
        row = next(row for row in rows if str(row.get("event_id")) == event_id)
        current_sequence = int(row.get("sequence") or 0)
        incoming_sequence = int(hint.sequence or 0)
        current_dtstamp = str(row.get("dtstamp") or "")
        incoming_dtstamp = str(hint.dtstamp or "")
        stale = incoming_sequence < current_sequence or (
            incoming_sequence == current_sequence
            and bool(current_dtstamp)
            and bool(incoming_dtstamp)
            and incoming_dtstamp <= current_dtstamp
        )
        return EventMatch(
            match_id=event_id,
            baseline=_event_baseline(events_by_id[event_id]),
            candidate_window=candidate_window,
            stale_authoritative=stale,
        )

    supporting_by_event: dict[str, set[str]] = {}
    for hint in hints:
        if hint.kind == "ical_uid":
            continue
        for row in rows_by_key.get(_identity_key(hint), []):
            event_id = str(row.get("event_id"))
            if event_id in events_by_id:
                supporting_by_event.setdefault(event_id, set()).add(hint.kind)

    join_hints = [hint for hint in hints if hint.kind == "join_url"]
    for hint in join_hints:
        for row in rows_by_key.get(_identity_key(hint), []):
            event_id = str(row.get("event_id"))
            candidate = events_by_id.get(event_id)
            if candidate and _times_match(event_data, candidate):
                return EventMatch(
                    match_id=event_id,
                    baseline=_event_baseline(candidate),
                    candidate_window=candidate_window,
                )

    # Two supporting signals are a bounded LLM candidate set, not an automatic
    # merge.  The caller passes only signal labels, never hashes or raw values.
    return None


def _strong_identity_candidates(
    rows_by_key: dict[str, list[dict[str, Any]]],
    events_by_id: dict[str, dict[str, Any]],
    hints: list[IdentityHint],
) -> list[dict[str, Any]]:
    supporting_by_event: dict[str, set[str]] = {}
    for hint in hints:
        if hint.kind == "ical_uid":
            continue
        for row in rows_by_key.get(_identity_key(hint), []):
            event_id = str(row.get("event_id"))
            if event_id in events_by_id:
                supporting_by_event.setdefault(event_id, set()).add(hint.kind)
    return [
        {
            **_event_baseline(events_by_id[event_id]),
            "id": event_id,
            "_identity_signals": sorted(kinds),
        }
        for event_id, kinds in supporting_by_event.items()
        if len(kinds) >= 2
    ]


def find_matching_event(
    supabase_client: Client,
    gateway: LLMGateway,
    user_id: str,
    event_data: dict[str, Any],
    user_timezone: Optional[str] = None,
    *,
    with_window: bool = False,
    identity_hints: Optional[list[IdentityHint]] = None,
    strict_identity: bool = False,
) -> Optional[EventMatch] | tuple[Optional[EventMatch], CandidateWindow | None]:
    """Find if event matches any existing events (date-based + LLM).

    Checks both local Selko events and the user's Google Calendar.
    Returns an EventMatch with baseline fields for change detection.
    """
    if user_timezone is None:
        user_timezone = get_user_timezone(supabase_client, user_id)

    identity_hints = identity_hints or []
    start_dt = event_data.get("start_datetime")
    if start_dt:
        start_aware = ensure_aware(start_dt, user_timezone)
        if start_aware is None:
            return (None, None) if with_window else None
        local_day = start_aware.astimezone(resolve_zone(user_timezone)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        time_min = local_day.astimezone(timezone.utc).isoformat()
        time_max = (local_day + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    elif identity_hints:
        # Structured cancellations can contain only an authoritative UID. Use
        # an explicit bounded identity-only read set so the same RPC fence
        # still covers the lookup instead of silently falling back to a create.
        time_min = "1970-01-01T00:00:00+00:00"
        time_max = "2100-01-01T00:00:00+00:00"
    else:
        return (None, None) if with_window else None

    result = supabase_client.table("events").select("*").eq(
        "user_id", user_id
    ).gte(
        "start_datetime", time_min
    ).lt(
        "start_datetime", time_max
    ).execute()

    candidates: list[dict[str, Any]] = list(result.data) if result.data else []
    identity_rows, identity_events, hint_fingerprint, hint_keys = _load_identity_candidates(
        supabase_client, user_id, identity_hints
    )
    candidate_window = CandidateWindow(
        window_start=time_min,
        window_end=time_max,
        fingerprint=candidate_fingerprint(candidates),
        hint_keys=hint_keys,
        hint_fingerprint=hint_fingerprint if hint_keys else None,
    )

    def resolved(match: Optional[EventMatch]):
        return (match, candidate_window) if with_window else match

    candidate_by_id: dict[str, dict[str, Any]] = {
        c["id"]: c for c in candidates if c.get("id")
    }

    identity_match = _identity_match(
        identity_rows,
        identity_events,
        identity_hints,
        event_data,
        candidate_window,
        strict_identity=strict_identity,
    )
    if identity_match is not None:
        return resolved(identity_match)

    strong_candidates = _strong_identity_candidates(
        identity_rows, identity_events, identity_hints
    )
    if strict_identity and len(strong_candidates) > 1:
        return resolved(EventMatch(
            match_id="",
            baseline={},
            candidate_window=candidate_window,
            ambiguous=True,
        ))
    if len(strong_candidates) == 1:
        try:
            matched_id = event_processing.compare_events(
                gateway, event_data, strong_candidates
            )
        except Exception as exc:
            logger.warning("Strong identity comparison failed (%s)", type(exc).__name__)
            matched_id = None
        if matched_id == strong_candidates[0]["id"]:
            candidate = strong_candidates[0]
            return resolved(EventMatch(
                match_id=matched_id,
                baseline=_event_baseline(candidate),
                candidate_window=candidate_window,
            ))

    if strict_identity:
        return resolved(None)

    try:
        gcal_events = calendars.fetch_calendar_events_for_date_range(
            supabase_client, user_id, time_min, time_max,
            user_timezone=user_timezone,
        )
        for gcal_event in gcal_events:
            ext_props = gcal_event.get("extendedProperties", {})
            private_props = ext_props.get("private", {})
            if private_props.get("selko_event_id"):
                continue
            gcal_id = gcal_event.get("id")
            if not gcal_id:
                continue
            baseline = baseline_from_gcal_event(
                gcal_event, user_timezone=user_timezone
            )
            match_id = f"gcal:{gcal_id}"
            candidate = {
                "id": match_id,
                "title": baseline.get("title", ""),
                "start_datetime": baseline.get("start_datetime"),
                "end_datetime": baseline.get("end_datetime"),
                "location": baseline.get("location", ""),
                "description": baseline.get("description", ""),
                "_source": "google_calendar",
                "_gcal_id": gcal_id,
                "_baseline": baseline,
                "_gcal_raw": gcal_event,
            }
            candidates.append(candidate)
            candidate_by_id[match_id] = candidate
    except Exception as e:
        logger.warning(f"GCal read-back failed during dedup, continuing with local only: {e}")

    if not candidates:
        return resolved(None)

    try:
        matched_id = event_processing.compare_events(
            gateway,
            event_data,
            candidates
        )
    except Exception as e:
        logger.warning(f"LLM comparison failed, no match: {e}")
        return resolved(None)

    if not matched_id:
        return resolved(None)

    candidate = candidate_by_id.get(matched_id)
    if not candidate:
        # compare_events may return an id string that still matches a candidate
        for c in candidates:
            if c.get("id") == matched_id:
                candidate = c
                break
    if not candidate:
        logger.warning(f"Matched id {matched_id} not found in candidates")
        return resolved(None)

    if matched_id.startswith("gcal:"):
        gcal_id = candidate.get("_gcal_id") or matched_id[5:]
        existing = supabase_client.table("events").select("*").eq(
            "user_id", user_id
        ).eq("google_calendar_event_id", gcal_id).not_.in_(
            "status", ["rejected", "cancelled"]
        ).order("created_at").limit(1).execute()
        if existing.data:
            row = existing.data[0]
            return resolved(EventMatch(
                match_id=row["id"],
                baseline={
                    "title": row.get("title"),
                    "start_datetime": row.get("start_datetime"),
                    "end_datetime": row.get("end_datetime"),
                    "all_day": row.get("all_day", False),
                    "location": row.get("location"),
                    "description": row.get("description"),
                    "importance": row.get("importance"),
                    "status": row.get("status"),
                },
                candidate_window=candidate_window,
            ))

        baseline = candidate.get("_baseline") or {
            "title": candidate.get("title"),
            "start_datetime": candidate.get("start_datetime"),
            "end_datetime": candidate.get("end_datetime"),
            "location": candidate.get("location"),
            "description": candidate.get("description"),
            "all_day": False,
            "status": "synced",
        }
        return resolved(EventMatch(
            match_id=matched_id,
            baseline=baseline,
            gcal_raw=candidate.get("_gcal_raw"),
            candidate_window=candidate_window,
        ))

    baseline = {
        "title": candidate.get("title"),
        "start_datetime": candidate.get("start_datetime"),
        "end_datetime": candidate.get("end_datetime"),
        "all_day": candidate.get("all_day", False),
        "location": candidate.get("location"),
        "description": candidate.get("description"),
        "importance": candidate.get("importance"),
        "status": candidate.get("status"),
    }
    return resolved(EventMatch(
        match_id=matched_id,
        baseline=baseline,
        candidate_window=candidate_window,
    ))


def ensure_email_event_source(
    supabase_client: Client,
    *,
    event_id: str,
    email_id: str,
    extracted_data: dict[str, Any],
    source_type: str = "new_invitation",
    event_snapshot_before: Any = None,
) -> str:
    """Insert an email ``event_sources`` row, or reuse an existing link.

    Idempotent for ``(event_id, email_id)`` email-origin rows to avoid
    ``event_sources_event_email_unique`` failures on reprocessing.
    """
    existing = (
        supabase_client.table("event_sources")
        .select("id")
        .eq("event_id", event_id)
        .eq("email_id", email_id)
        .eq("source_origin", "email")
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    result = supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": source_type,
        "extracted_data": extracted_data,
        "event_snapshot_before": event_snapshot_before,
    }).execute()
    return result.data[0]["id"]


def create_event(
    supabase_client: Client,
    user_id: str,
    event_data: dict[str, Any],
    email_id: str,
    initial_status: str = "pending_review",
    *,
    source_event_data: Optional[dict[str, Any]] = None,
) -> str:
    """Create new event and link to email source.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        event_data: Materialized event data written to the ``events`` row
            (and used for review/sync). After all-day policy, this may differ
            from the LLM source extraction.
        email_id: UUID of source email.
        initial_status: Status for the new event (default: pending_review).
        source_event_data: Optional LLM source-truth payload stored on
            ``event_sources.extracted_data``. Defaults to ``event_data``.

    Returns:
        UUID of created event.
    """
    extracted = source_event_data if source_event_data is not None else event_data

    # Create event record from materialized fields
    insert_data = {
        "user_id": user_id,
        "title": event_data.get("title"),
        "start_datetime": event_data.get("start_datetime"),
        "end_datetime": event_data.get("end_datetime"),
        "all_day": event_data.get("all_day", False),
        "location": event_data.get("location"),
        "description": event_data.get("description"),
        "importance": event_data.get("importance", "action_required"),
        "status": initial_status,
    }
    recurrence_rule = event_data.get("recurrence_rule")
    if recurrence_rule:
        insert_data["recurrence_rule"] = recurrence_rule

    raise EventsError("create_event was removed; use commit_email_extraction")

    event_id = event_result.data[0]["id"]

    # Create event_source link — retain LLM source truth in extracted_data
    ensure_email_event_source(
        supabase_client,
        event_id=event_id,
        email_id=email_id,
        extracted_data=extracted,
        source_type="new_invitation",
        event_snapshot_before=None,
    )

    # Generate source attribution
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Created new event {event_id}")
    return event_id


def create_event_from_gcal_match(
    supabase_client: Client,
    user_id: str,
    event_data: dict[str, Any],
    email_id: str,
    gcal_event_id: str,
    initial_status: str = "pending_review",
) -> str:
    """Create a Selko event linked to an existing Google Calendar event.

    Prefer ``create_pending_change_from_gcal`` for the Changes-lane pipeline.
    This helper remains for tests and callers that need a direct adopt insert.
    """
    raise EventsError("create_event_from_gcal_match was removed; use commit_email_extraction")
    event_result = None

    event_id = event_result.data[0]["id"]

    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "source_origin": "google_calendar",
        "google_calendar_source_event_id": gcal_event_id,
        "source_type": "new_invitation",
        "extracted_data": {"google_calendar_event_id": gcal_event_id},
        "event_snapshot_before": None,
    }).execute()

    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": "new_invitation",
        "extracted_data": event_data,
        "event_snapshot_before": None,
    }).execute()

    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()

    logger.info(f"Created event {event_id} adopting GCal event {gcal_event_id}")
    return event_id


def create_pending_change_from_gcal(
    supabase_client: Client,
    user_id: str,
    event_data: dict[str, Any],
    email_id: str,
    gcal_event_id: str,
    baseline: dict[str, Any],
    change_set: EventChangeSet,
    source_type: str = "update",
) -> str:
    """Create a Selko event for a GCal match that has real field changes.

    Canonical fields are the calendar baseline. Proposed deltas live on
    event_sources.change_set / extracted_data until apply_pending_change.
    """
    raise EventsError("create_pending_change_from_gcal was removed; use commit_email_extraction")
    event_result = None

    event_id = event_result.data[0]["id"]

    snapshot = {
        "title": baseline.get("title"),
        "start_datetime": baseline.get("start_datetime"),
        "end_datetime": baseline.get("end_datetime"),
        "all_day": baseline.get("all_day", False),
        "location": baseline.get("location"),
        "description": baseline.get("description"),
        "importance": baseline.get("importance", "action_required"),
        "status": baseline.get("status") or "synced",
    }

    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "source_origin": "google_calendar",
        "google_calendar_source_event_id": gcal_event_id,
        "source_type": source_type,
        "extracted_data": {"google_calendar_event_id": gcal_event_id},
        "event_snapshot_before": None,
        "change_set": change_set.model_dump_jsonable(),
    }).execute()

    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": source_type,
        "extracted_data": event_data,
        "event_snapshot_before": snapshot,
        "change_set": change_set.model_dump_jsonable(),
    }).execute()

    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()

    logger.info(
        "Created pending_change event %s for GCal %s (%s)",
        event_id,
        gcal_event_id,
        change_set.kind,
    )
    return event_id


def propose_local_change(
    supabase_client: Client,
    event_id: str,
    event_data: dict[str, Any],
    email_id: str,
    change_set: EventChangeSet,
    source_type: str = "update",
) -> None:
    """Attach a pending change proposal to an existing Selko event.

    Leaves canonical event fields unchanged until apply_pending_change.
    Replaces any prior non-undone update/cancellation proposal.
    """
    result = supabase_client.table("events").select("*").eq(
        "id", event_id
    ).single().execute()
    existing = result.data

    # Mark prior pending proposals undone (one active proposal at a time)
    prior = supabase_client.table("event_sources").select("id").eq(
        "event_id", event_id
    ).in_("source_type", ["update", "cancellation"]).eq(
        "is_undone", False
    ).execute()
    for row in prior.data or []:
        supabase_client.table("event_sources").update({
            "is_undone": True
        }).eq("id", row["id"]).execute()

    snapshot = {
        "title": existing.get("title"),
        "start_datetime": existing.get("start_datetime"),
        "end_datetime": existing.get("end_datetime"),
        "all_day": existing.get("all_day"),
        "location": existing.get("location"),
        "description": existing.get("description"),
        "importance": existing.get("importance"),
        "status": existing.get("status"),
    }

    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": source_type,
        "extracted_data": event_data,
        "event_snapshot_before": snapshot,
        "change_set": change_set.model_dump_jsonable(),
    }).execute()

    supabase_client.table("events").update({
        "status": "pending_change",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", event_id).execute()

    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()

    logger.info(
        "Proposed %s change on event %s from email %s",
        change_set.kind,
        event_id,
        email_id,
    )


def _latest_pending_change_proposal(
    supabase_client: Client, event_id: str
) -> Optional[dict[str, Any]]:
    """Return the owned proposal and its source enrichment.

    ``event_change_proposals`` is authoritative.  The source row is fetched
    only by the proposal's foreign key to display the compatibility email
    metadata; no source query is allowed to select a proposal.
    """
    result = supabase_client.table("event_change_proposals").select("*").eq(
        "event_id", event_id
    ).eq("status", "pending").maybe_single().execute()
    proposal = result.data if result is not None and isinstance(result.data, dict) else None
    if not proposal:
        return None
    source_result = supabase_client.table("event_sources").select("*").eq(
        "id", proposal["source_id"]
    ).maybe_single().execute()
    source = source_result.data if source_result is not None and isinstance(source_result.data, dict) else None
    if not source:
        raise EventsError(
            f"Proposal {proposal['id']} is missing its compatibility source"
        )
    proposal["source"] = source
    return proposal


def apply_pending_change(supabase_client: Client, event_id: str) -> dict[str, Any]:
    """Apply the latest pending change proposal without provider I/O.

    Prefers ``change_set`` after-values so source-truth ``extracted_data``
    (which may still say ``all_day=true``) cannot undo all-day materialization.
    Falls back to ``extracted_data`` only when no change_set is present (legacy).
    """
    event_result = supabase_client.table("events").select("*").eq(
        "id", event_id
    ).single().execute()
    event = event_result.data

    proposal = _latest_pending_change_proposal(supabase_client, event_id)
    if not proposal:
        raise EventsError(f"No pending change proposal for event {event_id}")
    source = proposal["source"]

    proposed_fields: dict[str, Any] = {}
    change_set = EventChangeSet.model_validate(proposal["change_set"])
    proposed_fields = proposed_fields_from_change_set(event, change_set)

    merged = apply_asserted_fields(event, proposed_fields)
    is_cancellation = proposal.get("kind") == "cancellation"
    if is_cancellation:
        # Cancellation is a state transition, not a title rewrite.  A
        # provider delete is performed later by the calendar worker.
        merged["title"] = event.get("title")

    if is_cancellation:
        has_provider_event = bool(event.get("google_calendar_event_id"))
        next_status = "cancel_queued" if has_provider_event else "cancelled"
        next_action = "cancel"
    else:
        next_status = "approved"
        next_action = event.get("calendar_sync_action", "upsert")

    update_fields = {
        "title": merged.get("title"),
        "start_datetime": merged.get("start_datetime"),
        "end_datetime": merged.get("end_datetime"),
        "all_day": merged.get("all_day", False),
        "location": merged.get("location"),
        "description": merged.get("description"),
        "importance": merged.get("importance", event.get("importance", "action_required")),
        "status": next_status,
        "calendar_sync_action": next_action,
        "sync_attempts": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase_client.rpc("apply_event_change_proposal", {
        "p_event_id": event_id,
        "p_user_id": event["user_id"],
        "p_proposal_id": proposal["id"],
        "p_expected_hash": None,
        "p_title": update_fields["title"],
        "p_start_datetime": update_fields["start_datetime"],
        "p_end_datetime": update_fields["end_datetime"],
        "p_all_day": update_fields["all_day"],
        "p_location": update_fields["location"],
        "p_description": update_fields["description"],
        "p_importance": update_fields["importance"],
        "p_next_status": update_fields["status"],
        "p_calendar_sync_action": update_fields["calendar_sync_action"],
    }).execute()
    logger.info(f"Applied pending change on event {event_id}")
    return update_fields


def reject_pending_change(supabase_client: Client, event_id: str) -> str:
    """Discard the pending change proposal.

    Returns the resulting status (or \"deleted\" if the Selko row is removed).
    """
    event_result = supabase_client.table("events").select("*").eq(
        "id", event_id
    ).single().execute()
    event = event_result.data

    proposal = _latest_pending_change_proposal(supabase_client, event_id)
    if not proposal:
        raise EventsError(f"No pending change proposal for event {event_id}")
    source = proposal["source"]
    snapshot = proposal.get("event_snapshot_before")

    # GCal-only adopt that never left pending_change: delete the row
    created_as_change_only = (
        event.get("status") == "pending_change"
        and event.get("google_calendar_event_id")
        and not event.get("synced_at")
        and (snapshot or {}).get("status") == "synced"
    )
    # Heuristic: if snapshot status is synced and event never synced via Selko,
    # and the only meaningful history is this proposal, delete.
    sources = supabase_client.table("event_sources").select(
        "id, source_type, source_origin"
    ).eq("event_id", event_id).execute()
    source_types = {s.get("source_type") for s in (sources.data or [])}
    gcal_only_proposal = (
        event.get("status") == "pending_change"
        and event.get("google_calendar_event_id")
        and "new_invitation" not in source_types
        and not event.get("synced_at")
    )

    if gcal_only_proposal or created_as_change_only:
        supabase_client.rpc("reject_event_change_proposal", {
            "p_event_id": event_id,
            "p_user_id": event["user_id"],
            "p_proposal_id": proposal["id"],
            "p_expected_hash": None,
            "p_resolution_reason": "user_rejected",
            "p_delete_event": True,
            "p_restore_status": "approved",
            "p_title": event.get("title"),
            "p_start_datetime": event.get("start_datetime"),
            "p_end_datetime": event.get("end_datetime"),
            "p_all_day": event.get("all_day", False),
            "p_location": event.get("location"),
            "p_description": event.get("description"),
            "p_importance": event.get("importance", "action_required"),
        }).execute()
        logger.info(f"Deleted GCal pending_change event {event_id} on reject")
        return "deleted"

    restore_status = "synced" if event.get("google_calendar_event_id") else "approved"
    if snapshot and snapshot.get("status") in {
        "pending_review", "approved", "synced", "sync_failed", "rejected", "cancelled"
    }:
        restore_status = snapshot["status"]

    restored_event = {
        "title": event.get("title"),
        "start_datetime": event.get("start_datetime"),
        "end_datetime": event.get("end_datetime"),
        "all_day": event.get("all_day", False),
        "location": event.get("location"),
        "description": event.get("description"),
        "importance": event.get("importance", "action_required"),
    }
    if snapshot:
        for key in (
            "title", "start_datetime", "end_datetime", "all_day",
            "location", "description", "importance",
        ):
            if key in snapshot:
                restored_event[key] = snapshot[key]

    supabase_client.rpc("reject_event_change_proposal", {
        "p_event_id": event_id,
        "p_user_id": event["user_id"],
        "p_proposal_id": proposal["id"],
        "p_expected_hash": None,
        "p_resolution_reason": "user_rejected",
        "p_delete_event": False,
        "p_restore_status": restore_status,
        "p_title": restored_event["title"],
        "p_start_datetime": restored_event["start_datetime"],
        "p_end_datetime": restored_event["end_datetime"],
        "p_all_day": restored_event["all_day"],
        "p_location": restored_event["location"],
        "p_description": restored_event["description"],
        "p_importance": restored_event["importance"],
    }).execute()
    logger.info(f"Rejected pending change on event {event_id} → {restore_status}")
    return restore_status


def undo_history_event(
    supabase_client: Client,
    event_id: str,
    user_id: str | None = None,
    *,
    force: bool = False,
) -> str:
    """Undo a History action: return New or Changes to the review queue.

    - Applied change (update/cancellation source with snapshot) → restore
      snapshot and queue a worker-owned compensation when synced, set
      ``pending_change``.
    - New event approval/rejection → queue worker-owned removal when synced,
      clear sync fields on completion, and set ``pending_review``.

    If the live Google Calendar event diverged from Selko's last write and
    ``force`` is False, raises ``calendars.CalendarDivergedError``. Provider
    mutation is never performed here; the calendar worker owns the queued
    compensation.

    Args:
        supabase_client: Authenticated Supabase client.
        event_id: Event UUID.
        user_id: Owner user id (required when the event is calendar-synced).
        force: When True, overwrite diverged GCal edits with the pre-Selko state.

    Returns:
        The new status (``pending_review`` or ``pending_change``).
    """
    event_result = supabase_client.table("events").select("*").eq(
        "id", event_id
    ).single().execute()
    event = event_result.data
    owner_id = user_id or event.get("user_id")

    proposal_result = supabase_client.table("event_change_proposals").select(
        "*"
    ).eq("event_id", event_id).eq("status", "applied").order(
        "resolved_at", desc=True
    ).limit(1).maybe_single().execute()
    change_proposal = (
        proposal_result.data
        if proposal_result is not None and isinstance(proposal_result.data, dict)
        else None
    )

    google_event_id = event.get("google_calendar_event_id")
    provider_exists = bool(google_event_id)
    expected_provider_revision: str | None = None
    if google_event_id:
        if not user_id:
            raise EventsError(
                "user_id is required to undo a calendar-synced event"
            )
        # Read the provider state outside the database transaction. The worker
        # will revalidate this revision immediately before writing.
        live = calendars.get_calendar_event(supabase_client, user_id, google_event_id)
        if live is not None:
            expected_provider_revision = live.get("etag") or live.get("updated")
            if not force:
                calendars.assert_calendar_not_diverged(
                    supabase_client, user_id, event_id, google_event_id, force=False
                )
        else:
            provider_exists = False

    if change_proposal:
        snapshot = change_proposal["event_snapshot_before"]
        restore_fields: dict[str, Any] = {
            "status": "pending_change",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for key in (
            "title", "start_datetime", "end_datetime", "all_day",
            "location", "description", "importance",
        ):
            if key in snapshot:
                restore_fields[key] = snapshot[key]
        if google_event_id and not provider_exists:
            restore_fields["google_calendar_event_id"] = None
            restore_fields["synced_at"] = None

        desired_event = {
            key: value for key, value in restore_fields.items() if key != "status"
        }
        result = supabase_client.rpc("reopen_event_change_proposal", {
            "p_event_id": event_id,
            "p_user_id": owner_id,
            "p_proposal_id": change_proposal["id"],
            "p_expected_hash": None,
            "p_action": "upsert" if provider_exists else None,
            "p_desired_event": desired_event if provider_exists else None,
            "p_expected_provider_revision": expected_provider_revision,
            "p_force_overwrite": force,
        }).execute()
        if not result.data:
            raise EventsError(f"Undo enqueue returned no result for event {event_id}")
        logger.info(f"Undid applied change on event {event_id} → pending_change")
        return "pending_change"

    # New approval / rejection undo
    result = supabase_client.rpc("undo_event_and_enqueue_calendar_work", {
        "p_event_id": event_id,
        "p_user_id": owner_id,
        "p_change_source_id": None,
        "p_restore_fields": {},
        "p_action": "cancel" if provider_exists else None,
        "p_desired_event": None,
        "p_expected_provider_revision": expected_provider_revision,
        "p_force_overwrite": force,
    }).execute()
    if not result.data:
        raise EventsError(f"Undo enqueue returned no result for event {event_id}")
    logger.info(f"Undid history event {event_id} → pending_review")
    return "pending_review"


def update_event(
    supabase_client: Client,
    gateway: LLMGateway,
    event_id: str,
    new_data: dict[str, Any],
    email_id: str,
    source_type: str,
) -> None:
    """Auto-merge new data into existing event.

    If the event was previously synced (status='synced'), re-queues it for
    sync so updated data reaches Google Calendar.

    Args:
        supabase_client: Authenticated Supabase client.
        gateway: LLMGateway instance for LLM operations.
        event_id: UUID of event to update.
        new_data: New event data from email.
        email_id: UUID of source email.
        source_type: Type of source (update, cancellation, etc).
    """
    raise EventsError("update_event was removed; use commit_email_extraction")

    # Fetch current event
    result = supabase_client.table("events").select("*").eq("id", event_id).single().execute()
    existing_event = result.data

    # Store snapshot before merge
    snapshot = {
        "title": existing_event.get("title"),
        "start_datetime": existing_event.get("start_datetime"),
        "end_datetime": existing_event.get("end_datetime"),
        "all_day": existing_event.get("all_day"),
        "location": existing_event.get("location"),
        "description": existing_event.get("description"),
    }

    # Use LLM to merge
    merged_data = event_processing.merge_event_data(
        gateway,
        existing_event,
        new_data,
        source_type
    )

    # Build update fields
    update_fields = {
        "title": merged_data.get("title"),
        "start_datetime": merged_data.get("start_datetime"),
        "end_datetime": merged_data.get("end_datetime"),
        "all_day": merged_data.get("all_day", False),
        "location": merged_data.get("location"),
        "description": merged_data.get("description"),
        "importance": merged_data.get("importance", "action_required"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Re-queue synced events for re-sync so updated data reaches Google Calendar
    if existing_event.get("status") == "synced":
        update_fields["status"] = "approved"
        update_fields["sync_attempts"] = 0

    # Update event
    supabase_client.table("events").update(update_fields).eq("id", event_id).execute()

    # Create event_source link
    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_type": source_type,
        "extracted_data": new_data,
        "event_snapshot_before": snapshot,
    }).execute()

    # Update source attribution
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()

    logger.info(f"Updated event {event_id} from email {email_id}")


def get_events_new(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get New-lane events pending approval, grouped by sender."""
    result = supabase_client.table("events").select(
        "*, event_sources(*, emails(*))"
    ).eq("user_id", user_id).eq("status", "pending_review").order(
        "start_datetime"
    ).execute()

    return result.data


def get_events_pending_change(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get Changes-lane events awaiting approve/reject."""
    result = supabase_client.table("events").select(
        "*, event_sources(*, emails(*))"
    ).eq("user_id", user_id).eq("status", "pending_change").order(
        "start_datetime"
    ).execute()

    return result.data


def get_events_approved(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get approved/synced events."""
    result = supabase_client.table("events").select("*").eq(
        "user_id", user_id
    ).in_("status", ["approved", "synced"]).order("start_datetime").execute()
    
    return result.data


def get_events_updates(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get change log (updates, cancellations, rejections)."""
    result = supabase_client.table("event_sources").select(
        "*, events(*), emails(*)"
    ).in_(
        "source_type", ["update", "cancellation"]
    ).order("created_at", desc=True).execute()
    
    # Filter by user_id
    updates = [
        source for source in result.data
        if source.get("events", {}).get("user_id") == user_id
    ]
    
    return updates


def get_event_with_sources(
    supabase_client: Client, event_id: str
) -> dict[str, Any]:
    """Fetch event with all source emails."""
    result = supabase_client.table("events").select(
        "*, event_sources(*, emails(*))"
    ).eq("id", event_id).single().execute()
    
    return result.data


def approve_event(supabase_client: Client, event_id: str) -> None:
    """Approve event for calendar sync.

    For ``pending_change``, applies the proposal first.
    """
    event_result = supabase_client.table("events").select("status").eq(
        "id", event_id
    ).single().execute()
    status = event_result.data.get("status")
    if status == "pending_change":
        apply_pending_change(supabase_client, event_id)
        return

    supabase_client.table("events").update({
        "status": "approved"
    }).eq("id", event_id).execute()

    logger.info(f"Approved event {event_id}")


def reject_event(supabase_client: Client, event_id: str) -> None:
    """Reject event (or discard a pending change proposal)."""
    event_result = supabase_client.table("events").select("status").eq(
        "id", event_id
    ).single().execute()
    status = event_result.data.get("status")
    if status == "pending_change":
        reject_pending_change(supabase_client, event_id)
        return

    supabase_client.table("events").update({
        "status": "rejected"
    }).eq("id", event_id).execute()

    logger.info(f"Rejected event {event_id}")


def restore_rejected_event(supabase_client: Client, event_id: str) -> None:
    """Restore rejected event to New."""
    supabase_client.table("events").update({
        "status": "pending_review"
    }).eq("id", event_id).execute()
    
    logger.info(f"Restored event {event_id}")


def undo_email_contribution(
    supabase_client: Client, event_source_id: str
) -> None:
    """Rollback specific email's changes using snapshot.
    
    Args:
        supabase_client: Authenticated Supabase client.
        event_source_id: UUID of event_source to undo.
    """
    # Fetch event_source
    result = supabase_client.table("event_sources").select("*").eq(
        "id", event_source_id
    ).single().execute()
    
    source = result.data
    event_id = source.get("event_id")
    snapshot = source.get("event_snapshot_before")
    
    if not snapshot:
        raise EventsError("No snapshot available for undo")
    
    # Restore snapshot
    supabase_client.table("events").update(snapshot).eq("id", event_id).execute()
    
    # Mark source as undone
    supabase_client.table("event_sources").update({
        "is_undone": True
    }).eq("id", event_source_id).execute()
    
    # Regenerate source attribution (excluding undone sources)
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Undid event_source {event_source_id}")


def redo_email_contribution(
    supabase_client: Client, event_source_id: str
) -> None:
    """Re-apply undone contribution."""
    supabase_client.table("event_sources").update({
        "is_undone": False
    }).eq("id", event_source_id).execute()
    
    # Regenerate source attribution
    result = supabase_client.table("event_sources").select("event_id").eq(
        "id", event_source_id
    ).single().execute()
    event_id = result.data["event_id"]
    
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Redid event_source {event_source_id}")


def check_sender_rules(
    supabase_client: Client, user_id: str, sender_email: str
) -> Optional[dict[str, Any]]:
    """Check if auto-approve/ignore applies to sender.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        sender_email: Email address of sender.
        
    Returns:
        Sender rule dict if found, None otherwise.
    """
    # Check exact email match first
    result = supabase_client.table("sender_rules").select("*").eq(
        "user_id", user_id
    ).eq("sender_email", sender_email).execute()
    
    if result.data:
        return result.data[0]
    
    # Check domain match
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    if domain:
        result = supabase_client.table("sender_rules").select("*").eq(
            "user_id", user_id
        ).eq("sender_domain", domain).execute()
        
        if result.data:
            return result.data[0]
    
    return None


def generate_source_attribution(
    supabase_client: Client, event_id: str
) -> str:
    """Generate natural English attribution for event.
    
    Args:
        supabase_client: Authenticated Supabase client.
        event_id: UUID of event.
        
    Returns:
        Natural English attribution string.
    """
    # Fetch all non-undone sources
    result = supabase_client.table("event_sources").select(
        "*, emails(*)"
    ).eq("event_id", event_id).eq("is_undone", False).order("created_at").execute()
    
    sources = result.data
    if not sources:
        return ""
    
    # Build attribution using helper function
    sources_with_email_data = []
    for source in sources:
        source_origin = source.get("source_origin", "email")
        email = source.get("emails") or {}

        if source_origin == "google_calendar":
            # Calendar-sourced entry — no email join
            sources_with_email_data.append({
                "source_type": source.get("source_type"),
                "email_sender": "your Google Calendar",
                "email_sender_name": "your Google Calendar",
                "email_date": source.get("created_at"),
                "created_at": source.get("created_at"),
                "is_undone": source.get("is_undone", False),
            })
        else:
            sources_with_email_data.append({
                "source_type": source.get("source_type"),
                "email_sender": email.get("from_email"),
                "email_sender_name": email.get("from_name"),
                "email_date": email.get("date_sent"),
                "created_at": source.get("created_at"),
                "is_undone": source.get("is_undone", False),
            })

    return event_processing.generate_source_attribution(sources_with_email_data)


# --- Status-based worker claiming functions for calendar sync ---


async def claim_approved_event_for_sync(
    pool,
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Claim one authoritative calendar work item and return its event view."""
    try:
        item_row = await pool.fetchrow(
            "SELECT * FROM public.claim_calendar_work_item($1, $2)",
            worker_id,
            lock_duration_seconds,
        )
        if item_row:
            from selko.services.pg import _normalize_pg_row

            item = _normalize_pg_row(dict(item_row))
            event_row = await pool.fetchrow(
                "SELECT * FROM public.events WHERE id = $1", item["event_id"]
            )
            if event_row is None:
                raise EventsError(f"Calendar work item {item['id']} has no event")
            event = _normalize_pg_row(dict(event_row))
            event["calendar_work_item_id"] = str(item["id"])
            event["calendar_work_generation"] = int(item["generation"])
            event["calendar_sync_action"] = item["action"]
            event["sync_attempts"] = item["attempts"]
            event["max_sync_attempts"] = item["max_attempts"]
            event["expected_provider_revision"] = item.get("expected_provider_revision")
            event["force_overwrite"] = bool(item.get("force_overwrite"))
            event["calendar_work_desired_event"] = item.get("desired_event")
            title = event.get("title", "(no title)")[:50]
            logger.info(
                "Worker %s claimed event %s: %s (attempt %s/%s)",
                worker_id,
                event["id"],
                title,
                event.get("sync_attempts", 0),
                event.get("max_sync_attempts", 0),
            )
            return event
        return None
    except Exception as e:
        raise EventsError(f"Failed to claim approved event: {e}") from e


async def _resolve_calendar_work_item(
    pool,
    identifier: str,
    worker_id: str | None,
    generation: int | None,
) -> dict[str, Any] | None:
    """Resolve an item id, or a legacy event id, to the current work item."""
    if worker_id is None or generation is None:
        row = await pool.fetchrow(
            "SELECT * FROM public.calendar_work_items "
            "WHERE (id = $1 OR event_id = $1) AND status = 'processing' "
            "ORDER BY generation DESC LIMIT 1",
            identifier,
        )
    else:
        row = await pool.fetchrow(
            "SELECT * FROM public.calendar_work_items "
            "WHERE (id = $1 OR event_id = $1) AND status = 'processing' "
            "AND locked_by = $2 AND generation = $3 "
            "ORDER BY generation DESC LIMIT 1",
            identifier,
            worker_id,
            generation,
        )
    return dict(row) if row else None


async def complete_event_sync(
    pool,
    event_id: str,
    google_event_id: str,
    worker_id: str | None = None,
    generation: int | None = None,
) -> bool:
    """Complete an upsert through the calendar work-item RPC."""
    try:
        item = await _resolve_calendar_work_item(pool, event_id, worker_id, generation)
        if item is None:
            logger.warning("Ignoring stale upsert completion for event %s", event_id)
            return False
        result = await pool.fetchval(
            "SELECT public.complete_calendar_work($1, $2, $3, $4, $5)",
            item["id"],
            worker_id or item.get("locked_by"),
            generation if generation is not None else int(item["generation"]),
            google_event_id,
            None,
        )
        return bool(result)

    except Exception as e:
        raise EventsError(f"Failed to complete event sync: {e}") from e


async def complete_event_cancellation(
    pool,
    event_id: str,
    worker_id: str,
    generation: int,
) -> bool:
    """Complete a cancellation through the calendar work-item RPC."""
    try:
        item = await _resolve_calendar_work_item(pool, event_id, worker_id, generation)
        if item is None:
            logger.warning("Ignoring stale cancellation completion for event %s", event_id)
            return False
        result = await pool.fetchval(
            "SELECT public.complete_calendar_work($1, $2, $3, $4, $5)",
            item["id"],
            worker_id,
            generation,
            item.get("provider_event_id"),
            None,
        )
        return bool(result)
    except Exception as e:
        raise EventsError(f"Failed to complete event cancellation: {e}") from e


async def defer_event_sync_for_quota(
    pool,
    event_id: str,
    sync_attempts: int,
    next_retry_at: str,
    worker_id: str | None = None,
    generation: int | None = None,
) -> None:
    """Release a claimed event until the daily calendar quota resets.

    Quota checks happen after the worker's atomic claim. A quota deferral is
    not a Google sync attempt, so restore the attempt budget while releasing
    the lock and schedule the next claim for the quota reset.
    """
    try:
        item = await _resolve_calendar_work_item(pool, event_id, worker_id, generation)
        if item is None:
            return
        await pool.fetchval(
            "SELECT public.defer_calendar_work($1, $2, $3, $4, $5)",
            item["id"],
            worker_id or item.get("locked_by"),
            generation if generation is not None else int(item["generation"]),
            next_retry_at,
            "Daily calendar sync quota exceeded",
        )
        logger.warning(
            "Deferred event %s until calendar quota resets at %s",
            event_id,
            next_retry_at,
        )
    except Exception as e:
        raise EventsError(f"Failed to defer event sync for quota: {e}") from e


async def park_event_for_oauth_reauth(
    pool,
    event_id: str,
    sync_attempts: int,
    sync_failure_code: str,
    user_message: str,
    worker_id: str | None = None,
    generation: int | None = None,
) -> None:
    """Return a claimed event to approved after an OAuth-blocked sync.

    Mirrors ``defer_event_sync_for_quota``: the worker's atomic claim already
    incremented ``sync_attempts``, but a sync blocked on expired or
    insufficient OAuth authorization isn't a real attempt against the user's
    calendar. Clear retry/backoff and dead-letter fields too, so the event is
    a clean `approved` row that resumes automatically (via
    ``claim_approved_event``'s active-integration check, and later the
    reconnect recovery flow) once the user reauthorizes.
    """
    try:
        item = await _resolve_calendar_work_item(pool, event_id, worker_id, generation)
        if item is None:
            return
        await pool.fetchval(
            "SELECT public.fail_calendar_work($1, $2, $3, $4, $5, $6)",
            item["id"],
            worker_id or item.get("locked_by"),
            generation if generation is not None else int(item["generation"]),
            sync_failure_code,
            user_message,
            False,
        )
        logger.warning(
            "Parked event %s for %s reauthorization", event_id, sync_failure_code
        )
    except Exception as e:
        raise EventsError(f"Failed to park event for oauth reauth: {e}") from e


async def fail_event_sync(
    pool,
    event_id: str,
    error: str,
    worker_id: str | None = None,
    generation: int | None = None,
) -> None:
    """Mark event sync as failed.

    If sync_attempts < max_sync_attempts, sets status back to 'approved' for retry.
    Otherwise, sets status to 'sync_failed' permanently.

    Args:
        pool: asyncpg session-pooler pool.
        event_id: UUID of event that failed syncing.
        error: Error message to store.

    Raises:
        EventsError: If update fails.
    """
    try:
        item = await _resolve_calendar_work_item(pool, event_id, worker_id, generation)
        if item is None:
            logger.warning("Ignoring stale calendar failure for %s", event_id)
            return
        result = await pool.fetchval(
            "SELECT public.fail_calendar_work($1, $2, $3, $4, $5, $6)",
            item["id"],
            worker_id or item.get("locked_by"),
            generation if generation is not None else int(item["generation"]),
            "calendar_sync_failed",
            error,
            True,
        )
        logger.warning("Calendar work failure for %s: %s", event_id, result)

    except EventsError:
        raise
    except Exception as e:
        raise EventsError(f"Failed to mark event sync as failed: {e}") from e


async def unlock_expired_event_locks(pool) -> int:
    """Reset expired event sync locks back to approved.

    Handles the case where a worker crashes mid-sync and the lock expires.

    Args:
        pool: asyncpg session-pooler pool.

    Returns:
        Number of events unlocked.

    Raises:
        EventsError: If unlock fails.
    """
    try:
        # Claim-time recovery owns mutation. The next claim_calendar_work_item
        # call reclaims expired work atomically without a periodic sweeper.
        count = await pool.fetchval(
            "SELECT count(*) FROM public.calendar_work_items "
            "WHERE status = 'processing' AND locked_until < now()"
        )

        if count:
            logger.warning(f"Unlocked {count} expired event sync locks")

        return count or 0

    except Exception as e:
        raise EventsError(f"Failed to unlock expired event locks: {e}") from e
