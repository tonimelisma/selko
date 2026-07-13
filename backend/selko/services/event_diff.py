"""Deterministic field-level event change gating.

The LLM proposes what changed; this module normalizes and drops no-op /
hallucinated diffs so routing (New / Changes / skip) stays reliable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


MATERIAL_FIELDS = frozenset(
    {"start_datetime", "end_datetime", "all_day", "location", "title"}
)
ENRICHMENT_FIELDS = frozenset({"description", "importance"})
COMPARABLE_FIELDS = MATERIAL_FIELDS | ENRICHMENT_FIELDS | frozenset({"status"})

ALLOWED_FIELDS = frozenset(
    {
        "start_datetime",
        "end_datetime",
        "all_day",
        "location",
        "title",
        "description",
        "status",
        "importance",
    }
)


class FieldChange(BaseModel):
    """A single field that differs between baseline and proposal."""

    field: Literal[
        "start_datetime",
        "end_datetime",
        "all_day",
        "location",
        "title",
        "description",
        "status",
        "importance",
    ]
    before: Any = None
    after: Any = None
    reason: Optional[str] = None
    mode: Optional[Literal["append", "replace"]] = None


class EventChangeSet(BaseModel):
    """Structured diff used to route New vs Changes vs silent skip."""

    kind: Literal["noop", "enrichment", "material_update", "cancellation"]
    changes: list[FieldChange] = Field(default_factory=list)
    reasoning: Optional[str] = None

    def model_dump_jsonable(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _parse_datetime_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return datetime(
                int(text[0:4]), int(text[5:7]), int(text[8:10]), tzinfo=timezone.utc
            )
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_datetime(value: Any, user_timezone: Optional[str] = None) -> Optional[str]:
    dt = _parse_datetime_utc(value)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_location(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.casefold()


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _normalize_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(value)


def normalized_value(
    field: str, value: Any, user_timezone: Optional[str] = None
) -> Any:
    if field in ("start_datetime", "end_datetime"):
        return _normalize_datetime(value, user_timezone)
    if field == "location":
        return _normalize_location(value)
    if field == "all_day":
        return _normalize_bool(value)
    if field in ("title", "description", "status", "importance"):
        return _normalize_text(value)
    return value


def values_equal(
    field: str,
    before: Any,
    after: Any,
    user_timezone: Optional[str] = None,
) -> bool:
    if field in ("start_datetime", "end_datetime"):
        from selko.services.civil_time import datetimes_equal

        return datetimes_equal(before, after, user_timezone)
    return normalized_value(field, before, user_timezone) == normalized_value(
        field, after, user_timezone
    )


def derive_kind(changes: list[FieldChange]) -> Literal[
    "noop", "enrichment", "material_update", "cancellation"
]:
    if not changes:
        return "noop"
    names = {c.field for c in changes}
    if "status" in names and any(
        normalized_value("status", c.after) == "cancelled"
        for c in changes
        if c.field == "status"
    ):
        return "cancellation"
    if names & MATERIAL_FIELDS:
        return "material_update"
    return "enrichment"


def _title_tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(value or "").casefold()) if t}


def _titles_cosmetically_equal(before: Any, after: Any) -> bool:
    a, b = _title_tokens(before), _title_tokens(after)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.5


def gate_change_set(
    proposed: EventChangeSet,
    baseline: Optional[dict[str, Any]] = None,
    user_timezone: Optional[str] = None,
) -> EventChangeSet:
    """Drop hallucinated / no-op field changes; re-derive kind from survivors.

    If ``baseline`` is provided, ``before`` is taken from baseline when the LLM
    omitted it, and changes where normalized before==after are removed.
    """
    gated: list[FieldChange] = []
    for change in proposed.changes:
        field = change.field
        if field not in ALLOWED_FIELDS:
            continue
        before = change.before
        after = change.after
        if baseline is not None and before is None and field in baseline:
            before = baseline.get(field)
        if field == "title" and _titles_cosmetically_equal(before, after):
            continue
        if values_equal(field, before, after, user_timezone):
            continue
        gated.append(
            FieldChange(
                field=field,  # type: ignore[arg-type]
                before=before,
                after=after,
                reason=change.reason,
                mode=change.mode,
            )
        )

    kind = derive_kind(gated)
    if proposed.kind == "cancellation" and gated:
        kind = "cancellation"
    if proposed.kind == "noop" and not gated:
        kind = "noop"

    return EventChangeSet(
        kind=kind,
        changes=gated,
        reasoning=proposed.reasoning,
    )


def compute_change_set(
    baseline: dict[str, Any],
    proposed: dict[str, Any],
    *,
    source_type: str = "update",
    user_timezone: Optional[str] = None,
) -> EventChangeSet:
    """Deterministic fallback diff (tests / when LLM propose is unavailable).

    Only fields present in ``proposed`` are compared.
    """
    changes: list[FieldChange] = []

    if source_type == "cancellation" or proposed.get("status") == "cancelled":
        before_status = baseline.get("status")
        after_status = "cancelled"
        if not values_equal("status", before_status, after_status, user_timezone):
            changes.append(
                FieldChange(field="status", before=before_status, after=after_status)
            )
        return gate_change_set(
            EventChangeSet(kind="cancellation", changes=changes),
            baseline,
            user_timezone=user_timezone,
        )

    for field in sorted(COMPARABLE_FIELDS):
        if field not in proposed:
            continue
        before = baseline.get(field)
        after = proposed.get(field)
        if values_equal(field, before, after, user_timezone):
            continue
        changes.append(
            FieldChange(
                field=field,  # type: ignore[arg-type]
                before=before,
                after=after,
            )
        )

    return gate_change_set(
        EventChangeSet(kind=derive_kind(changes), changes=changes),
        baseline,
        user_timezone=user_timezone,
    )


def baseline_from_gcal_event(
    gcal_event: dict[str, Any],
    user_timezone: Optional[str] = None,
) -> dict[str, Any]:
    """Map a Google Calendar API event dict to Selko-like baseline fields."""
    from selko.services.civil_time import to_storage_iso

    start = gcal_event.get("start") or {}
    end = gcal_event.get("end") or {}
    all_day = "date" in start and "dateTime" not in start
    start_raw = start.get("dateTime") or start.get("date")
    end_raw = end.get("dateTime") or end.get("date")
    if all_day:
        start_dt = start_raw
        end_dt = end_raw
    else:
        start_dt = to_storage_iso(start_raw, user_timezone, treat_as_civil=False)
        end_dt = to_storage_iso(end_raw, user_timezone, treat_as_civil=False)
    return {
        "title": gcal_event.get("summary") or "",
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "all_day": all_day,
        "location": gcal_event.get("location") or None,
        "description": gcal_event.get("description") or None,
        "status": "synced",
    }


def resolve_description_append(
    change_set: EventChangeSet, baseline: dict[str, Any]
) -> EventChangeSet:
    """Materialize mode=append description changes into full after-values."""
    for change in change_set.changes:
        if change.field == "description" and change.mode == "append":
            base = (baseline.get("description") or "").strip()
            addition = (str(change.after or "")).strip()
            if addition and addition not in base:
                change.after = f"{base}\n\n{addition}" if base else addition
            else:
                change.after = base or change.after
            change.mode = None
    return change_set


def apply_asserted_fields(
    baseline: dict[str, Any],
    proposed: dict[str, Any],
) -> dict[str, Any]:
    """Return baseline with only asserted proposed fields overlaid."""
    merged = dict(baseline)
    for field in COMPARABLE_FIELDS:
        if field in proposed:
            merged[field] = proposed[field]
    return merged


def proposed_fields_from_change_set(
    baseline: dict[str, Any],
    change_set: EventChangeSet,
) -> dict[str, Any]:
    """Build a proposed field dict from gated changes (after values only)."""
    proposed: dict[str, Any] = {}
    for change in change_set.changes:
        proposed[change.field] = change.after
    if change_set.kind == "cancellation" and "status" not in proposed:
        proposed["status"] = "cancelled"
    return proposed
