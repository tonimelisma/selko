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
from selko.services.llm_gateway import LLMGateway
from selko.services.retry_utils import calculate_retry_delay

logger = logging.getLogger(__name__)


class EventsError(Exception):
    """Raised when event operations fail."""

    pass


@dataclass
class EventMatch:
    """A dedup match against a local Selko event or Google Calendar event."""

    match_id: str
    baseline: dict[str, Any]
    gcal_raw: Optional[dict[str, Any]] = None

    @property
    def is_gcal(self) -> bool:
        return self.match_id.startswith("gcal:")

    @property
    def gcal_id(self) -> Optional[str]:
        if self.is_gcal:
            return self.match_id[5:]
        return None


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

    for event in extraction.events:
        source_event_data = normalize_event_data(
            event, user_timezone=user_timezone, treat_as_civil=treat_as_civil
        )
        # Materialized form drives dedup + events row; source stays in extracted_data.
        event_data = materialize_all_day_event(
            source_event_data, all_day_policy, user_timezone
        )

        if not event_data.get("start_datetime"):
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
                if start_dt < cutoff:
                    logger.info(f"Skipping past event: {event_data.get('title')} ({start_str})")
                    continue
            except (ValueError, TypeError):
                pass

        match = find_matching_event(
            supabase_client, gateway, user_id, event_data,
            user_timezone=user_timezone,
        )

        if match is None:
            create_event(
                supabase_client,
                user_id,
                event_data,
                email_id,
                initial_status=initial_status,
                source_event_data=source_event_data,
            )
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

        # extracted_data keeps LLM source truth; change_set carries materialized deltas
        source_proposal = source_event_data

        if auto_apply:
            if match.is_gcal:
                event_id = create_pending_change_from_gcal(
                    supabase_client,
                    user_id,
                    source_proposal,
                    email_id,
                    match.gcal_id or "",
                    match.baseline,
                    change_set,
                    source_type=source_type,
                )
                apply_pending_change(supabase_client, event_id)
            else:
                propose_local_change(
                    supabase_client,
                    match.match_id,
                    source_proposal,
                    email_id,
                    change_set,
                    source_type=source_type,
                )
                apply_pending_change(supabase_client, match.match_id)
            num_updated += 1
            continue

        if match.is_gcal:
            create_pending_change_from_gcal(
                supabase_client,
                user_id,
                source_proposal,
                email_id,
                match.gcal_id or "",
                match.baseline,
                change_set,
                source_type=source_type,
            )
            num_updated += 1
        else:
            propose_local_change(
                supabase_client,
                match.match_id,
                source_proposal,
                email_id,
                change_set,
                source_type=source_type,
            )
            num_updated += 1

    return num_new, num_updated


def process_email_for_events(
    supabase_client: Client,
    gateway: LLMGateway,
    email_id: str,
    user_id: str,
    config: Optional[Config] = None,
) -> dict[str, Any]:
    """Main pipeline function to extract events from an email.

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

    try:
        mark_email_status(supabase_client, email_id, "processing")

        email_metadata, email_text, attachments = event_processing.fetch_email_with_attachments(
            supabase_client, email_id
        )

        # Inject user timezone for timezone-aware current_date in prompt
        email_metadata["user_timezone"] = get_user_timezone(supabase_client, user_id)

        sender_email = email_metadata.get("from_email", "")

        # Check sender rules: ignore, auto_approve, or no rule
        sender_rule = check_sender_rules(supabase_client, user_id, sender_email)
        rule_action = sender_rule.get("action") if sender_rule else None

        if rule_action == "ignore":
            logger.info(f"Sender {sender_email} is ignored, skipping event extraction")
            mark_email_status(supabase_client, email_id, "skipped")
            return {"num_events": 0, "num_new": 0, "num_updated": 0, "skipped": True}

        # Determine initial status based on sender rule
        if rule_action == "auto_approve":
            initial_status = "approved"
            logger.info(f"Sender {sender_email} is auto-approved, events will be created as approved")
        else:
            initial_status = "pending_review"

        # Calendar invitation emails (meeting requests, updates, RSVPs, cancellations)
        # are already handled by the user's email client and calendar. Skip entirely.
        invite_method = ics_parser.detect_invite_method(attachments)
        if email_metadata.get("is_calendar_invite") or invite_method in ics_parser.INVITE_METHODS:
            result = {"num_events": 0, "num_new": 0, "num_updated": 0, "skipped": True}
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
            logger.info(f"Parsed {len(extraction.events)} events from .ics (skipped LLM)")
        else:
            extraction = event_processing.extract_calendar_events(
                gateway, email_text, email_metadata, attachments, config=config,
            )

        if not extraction.events_found or not extraction.events:
            logger.info("No events found in email")
            result = {"num_events": 0, "num_new": 0, "num_updated": 0}
            mark_email_status(
                supabase_client,
                email_id,
                "processed",
                outcome="no_event",
                result=result,
            )
            return result

        num_new, num_updated = save_extracted_events(
            supabase_client, gateway, user_id, email_id, extraction,
            initial_status=initial_status,
            treat_as_civil=not from_ics,
            email_date_sent=email_metadata.get("date_sent"),
        )

        if num_new and num_updated:
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


def find_matching_event(
    supabase_client: Client,
    gateway: LLMGateway,
    user_id: str,
    event_data: dict[str, Any],
    user_timezone: Optional[str] = None,
) -> Optional[EventMatch]:
    """Find if event matches any existing events (date-based + LLM).

    Checks both local Selko events and the user's Google Calendar.
    Returns an EventMatch with baseline fields for change detection.
    """
    if user_timezone is None:
        user_timezone = get_user_timezone(supabase_client, user_id)

    start_dt = event_data.get("start_datetime")
    if not start_dt:
        return None

    start_aware = ensure_aware(start_dt, user_timezone)
    if start_aware is None:
        return None
    local_day = start_aware.astimezone(resolve_zone(user_timezone)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    time_min = local_day.astimezone(timezone.utc).isoformat()
    time_max = (local_day + timedelta(days=1)).astimezone(timezone.utc).isoformat()

    result = supabase_client.table("events").select("*").eq(
        "user_id", user_id
    ).gte(
        "start_datetime", time_min
    ).lt(
        "start_datetime", time_max
    ).execute()

    candidates: list[dict[str, Any]] = list(result.data) if result.data else []
    candidate_by_id: dict[str, dict[str, Any]] = {
        c["id"]: c for c in candidates if c.get("id")
    }

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
        return None

    try:
        matched_id = event_processing.compare_events(
            gateway,
            event_data,
            candidates
        )
    except Exception as e:
        logger.warning(f"LLM comparison failed, no match: {e}")
        return None

    if not matched_id:
        return None

    candidate = candidate_by_id.get(matched_id)
    if not candidate:
        # compare_events may return an id string that still matches a candidate
        for c in candidates:
            if c.get("id") == matched_id:
                candidate = c
                break
    if not candidate:
        logger.warning(f"Matched id {matched_id} not found in candidates")
        return None

    if matched_id.startswith("gcal:"):
        gcal_id = candidate.get("_gcal_id") or matched_id[5:]
        existing = supabase_client.table("events").select("*").eq(
            "user_id", user_id
        ).eq("google_calendar_event_id", gcal_id).not_.in_(
            "status", ["rejected", "cancelled"]
        ).order("created_at").limit(1).execute()
        if existing.data:
            row = existing.data[0]
            return EventMatch(
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
            )

        baseline = candidate.get("_baseline") or {
            "title": candidate.get("title"),
            "start_datetime": candidate.get("start_datetime"),
            "end_datetime": candidate.get("end_datetime"),
            "location": candidate.get("location"),
            "description": candidate.get("description"),
            "all_day": False,
            "status": "synced",
        }
        return EventMatch(
            match_id=matched_id,
            baseline=baseline,
            gcal_raw=candidate.get("_gcal_raw"),
        )

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
    return EventMatch(match_id=matched_id, baseline=baseline)


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

    event_result = supabase_client.table("events").insert(insert_data).execute()

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
    event_result = supabase_client.table("events").insert({
        "user_id": user_id,
        "title": event_data.get("title"),
        "start_datetime": event_data.get("start_datetime"),
        "end_datetime": event_data.get("end_datetime"),
        "all_day": event_data.get("all_day", False),
        "location": event_data.get("location"),
        "description": event_data.get("description"),
        "importance": event_data.get("importance", "action_required"),
        "status": initial_status,
        "google_calendar_event_id": gcal_event_id,
    }).execute()

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
    event_result = supabase_client.table("events").insert({
        "user_id": user_id,
        "title": baseline.get("title"),
        "start_datetime": baseline.get("start_datetime"),
        "end_datetime": baseline.get("end_datetime"),
        "all_day": baseline.get("all_day", False),
        "location": baseline.get("location"),
        "description": baseline.get("description"),
        "importance": baseline.get("importance", "action_required"),
        "status": "pending_change",
        "google_calendar_event_id": gcal_event_id,
    }).execute()

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


def _latest_pending_change_source(
    supabase_client: Client, event_id: str
) -> Optional[dict[str, Any]]:
    result = supabase_client.table("event_sources").select("*").eq(
        "event_id", event_id
    ).in_("source_type", ["update", "cancellation"]).eq(
        "is_undone", False
    ).order("created_at", desc=True).limit(1).execute()
    if result.data:
        return result.data[0]
    return None


def apply_pending_change(supabase_client: Client, event_id: str) -> dict[str, Any]:
    """Apply the latest pending change proposal and mark event approved.

    Prefers ``change_set`` after-values so source-truth ``extracted_data``
    (which may still say ``all_day=true``) cannot undo all-day materialization.
    Falls back to ``extracted_data`` only when no change_set is present (legacy).
    """
    event_result = supabase_client.table("events").select("*").eq(
        "id", event_id
    ).single().execute()
    event = event_result.data

    source = _latest_pending_change_source(supabase_client, event_id)
    if not source:
        raise EventsError(f"No pending change proposal for event {event_id}")

    # Prefer the email source sibling when the latest row is GCal metadata-only
    if source.get("source_origin") == "google_calendar" and not source.get("change_set"):
        email_sources = supabase_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_origin", "email").eq("is_undone", False).order(
            "created_at", desc=True
        ).limit(1).execute()
        if email_sources.data:
            source = email_sources.data[0]

    proposed_fields: dict[str, Any] = {}
    change_set_raw = source.get("change_set")
    if change_set_raw:
        change_set = EventChangeSet.model_validate(change_set_raw)
        proposed_fields = proposed_fields_from_change_set(event, change_set)
    else:
        proposed = source.get("extracted_data") or {}
        proposed_fields = {
            k: v for k, v in proposed.items()
            if k in {
                "title", "start_datetime", "end_datetime", "all_day",
                "location", "description", "importance", "status", "recurrence_rule",
            }
        }
        if not proposed_fields and source.get("source_origin") == "google_calendar":
            email_sources = supabase_client.table("event_sources").select("*").eq(
                "event_id", event_id
            ).eq("source_origin", "email").eq("is_undone", False).order(
                "created_at", desc=True
            ).limit(1).execute()
            if email_sources.data:
                source = email_sources.data[0]
                proposed = source.get("extracted_data") or {}
                proposed_fields = {
                    k: v for k, v in proposed.items()
                    if k in {
                        "title", "start_datetime", "end_datetime", "all_day",
                        "location", "description", "importance", "status",
                        "recurrence_rule",
                    }
                }

    merged = apply_asserted_fields(event, proposed_fields)
    if source.get("source_type") == "cancellation":
        merged["title"] = merged.get("title") or event.get("title")
        if merged.get("title") and not str(merged["title"]).startswith("CANCELLED:"):
            merged["title"] = f"CANCELLED: {merged['title']}"

    update_fields = {
        "title": merged.get("title"),
        "start_datetime": merged.get("start_datetime"),
        "end_datetime": merged.get("end_datetime"),
        "all_day": merged.get("all_day", False),
        "location": merged.get("location"),
        "description": merged.get("description"),
        "importance": merged.get("importance", event.get("importance", "action_required")),
        "status": "approved",
        "sync_attempts": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase_client.table("events").update(update_fields).eq("id", event_id).execute()
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

    source = _latest_pending_change_source(supabase_client, event_id)
    snapshot = (source or {}).get("event_snapshot_before") if source else None

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
        supabase_client.table("events").delete().eq("id", event_id).execute()
        logger.info(f"Deleted GCal pending_change event {event_id} on reject")
        return "deleted"

    if source:
        supabase_client.table("event_sources").update({
            "is_undone": True
        }).eq("id", source["id"]).execute()

    restore_status = "synced" if event.get("google_calendar_event_id") else "approved"
    if snapshot and snapshot.get("status") in {
        "pending_review", "approved", "synced", "sync_failed", "rejected", "cancelled"
    }:
        restore_status = snapshot["status"]

    restore_fields: dict[str, Any] = {
        "status": restore_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if snapshot:
        for key in (
            "title", "start_datetime", "end_datetime", "all_day",
            "location", "description", "importance",
        ):
            if key in snapshot:
                restore_fields[key] = snapshot[key]

    supabase_client.table("events").update(restore_fields).eq("id", event_id).execute()
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
      snapshot, PATCH Google Calendar back to that state when synced, set
      ``pending_change``.
    - New event approval/rejection → DELETE Google Calendar event when
      synced, clear sync fields, set ``pending_review``.

    If the live Google Calendar event diverged from Selko's last write and
    ``force`` is False, raises ``calendars.CalendarDivergedError``.

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

    sources = supabase_client.table("event_sources").select("*").eq(
        "event_id", event_id
    ).eq("is_undone", False).order("created_at", desc=True).execute()

    change_source = None
    for src in sources.data or []:
        if src.get("source_type") in ("update", "cancellation") and src.get(
            "event_snapshot_before"
        ):
            change_source = src
            break

    google_event_id = event.get("google_calendar_event_id")
    if google_event_id:
        if not user_id:
            raise EventsError(
                "user_id is required to undo a calendar-synced event"
            )
        # Drift check (skipped when force=True; 404 is not divergence)
        calendars.assert_calendar_not_diverged(
            supabase_client,
            user_id,
            event_id,
            google_event_id,
            force=force,
        )

    if change_source:
        snapshot = change_source["event_snapshot_before"]
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

        if google_event_id and user_id:
            live = calendars.get_calendar_event(
                supabase_client, user_id, google_event_id
            )
            if live is None:
                restore_fields["google_calendar_event_id"] = None
                restore_fields["synced_at"] = None
            else:
                calendars.restore_calendar_event_from_selko_fields(
                    supabase_client,
                    user_id,
                    event_id,
                    {k: v for k, v in restore_fields.items() if k != "status"},
                )

        supabase_client.table("events").update(restore_fields).eq(
            "id", event_id
        ).execute()
        logger.info(f"Undid applied change on event {event_id} → pending_change")
        return "pending_change"

    # New approval / rejection undo
    if google_event_id and user_id:
        calendars.delete_calendar_event_only(
            supabase_client, user_id, event_id
        )

    supabase_client.table("events").update({
        "status": "pending_review",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", event_id).execute()
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


def claim_approved_event_for_sync(
    client: Client,
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next approved event for calendar sync.

    Uses PostgreSQL FOR UPDATE SKIP LOCKED to safely claim events without
    conflicts between multiple workers.

    Args:
        client: Authenticated Supabase client (should use service role).
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Event dict if claimed, None if no approved events available.

    Raises:
        EventsError: If claim operation fails.
    """
    try:
        result = client.rpc('claim_approved_event', {
            'p_worker_id': worker_id,
            'p_lock_duration_seconds': lock_duration_seconds,
        }).execute()

        if result.data and len(result.data) > 0:
            event = result.data[0]
            title = event.get("title", "(no title)")[:50]
            logger.info(
                f"Worker {worker_id} claimed event {event['id']}: {title} "
                f"(attempt {event['sync_attempts']}/{event['max_sync_attempts']})"
            )
            return event

        return None

    except Exception as e:
        raise EventsError(f"Failed to claim approved event: {e}") from e


def complete_event_sync(client: Client, event_id: str, google_event_id: str) -> None:
    """Mark event as synced successfully and clear the lock.

    Args:
        client: Authenticated Supabase client (should use service role).
        event_id: UUID of event to mark as synced.
        google_event_id: ID of the created Google Calendar event.

    Raises:
        EventsError: If update fails.
    """
    try:
        client.table("events").update({
            "status": "synced",
            "google_calendar_event_id": google_event_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "sync_error": None,
            "locked_by": None,
            "locked_until": None,
        }).eq("id", event_id).execute()

        logger.info(f"Completed sync for event {event_id} -> {google_event_id}")

    except Exception as e:
        raise EventsError(f"Failed to complete event sync: {e}") from e


def fail_event_sync(
    client: Client,
    event_id: str,
    error: str,
) -> None:
    """Mark event sync as failed.

    If sync_attempts < max_sync_attempts, sets status back to 'approved' for retry.
    Otherwise, sets status to 'sync_failed' permanently.

    Args:
        client: Authenticated Supabase client (should use service role).
        event_id: UUID of event that failed syncing.
        error: Error message to store.

    Raises:
        EventsError: If update fails.
    """
    try:
        # Fetch current event to check retry eligibility
        result = client.table("events").select(
            "sync_attempts, max_sync_attempts"
        ).eq("id", event_id).single().execute()

        event = result.data
        sync_attempts = event["sync_attempts"]
        max_sync_attempts = event["max_sync_attempts"]
        should_retry = sync_attempts < max_sync_attempts

        update_data = {
            "status": "approved" if should_retry else "sync_failed",
            "sync_error": error,
            "locked_by": None,
            "locked_until": None,
        }

        if should_retry:
            delay, next_retry_at = calculate_retry_delay(sync_attempts)
            update_data["next_retry_at"] = next_retry_at
        else:
            # Dead letter: permanently failed
            update_data["dead_letter_reason"] = error
            update_data["dead_letter_at"] = datetime.now(timezone.utc).isoformat()

        client.table("events").update(update_data).eq("id", event_id).execute()

        if should_retry:
            logger.warning(
                f"Event {event_id} sync failed "
                f"(attempt {sync_attempts}/{max_sync_attempts}): {error}. "
                f"Will retry in {delay}s."
            )
        else:
            logger.error(
                f"Event {event_id} sync failed permanently "
                f"after {sync_attempts} attempts: {error}. "
                f"Moved to dead letter."
            )

    except Exception as e:
        raise EventsError(f"Failed to mark event sync as failed: {e}") from e


def unlock_expired_event_locks(client: Client) -> int:
    """Reset expired event sync locks back to approved.

    Handles the case where a worker crashes mid-sync and the lock expires.

    Args:
        client: Authenticated Supabase client (should use service role).

    Returns:
        Number of events unlocked.

    Raises:
        EventsError: If unlock fails.
    """
    try:
        result = client.rpc('unlock_expired_event_locks').execute()
        count = result.data if result.data else 0

        if count > 0:
            logger.warning(f"Unlocked {count} expired event sync locks")

        return count

    except Exception as e:
        raise EventsError(f"Failed to unlock expired event locks: {e}") from e
