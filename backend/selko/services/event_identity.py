"""Content-free calendar identity canonicalization and matching inputs."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ref",
    "ref_src",
}


@dataclass(frozen=True)
class IdentityHint:
    """A normalized, content-free identity signal."""

    kind: str
    value_hash: str
    recurrence_id: str = ""
    strength: str = "supporting"
    sequence: int | None = None
    dtstamp: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "value_hash": self.value_hash,
            "recurrence_id": self.recurrence_id,
            "strength": self.strength,
        }
        if self.sequence is not None:
            payload["sequence"] = self.sequence
        if self.dtstamp:
            payload["dtstamp"] = self.dtstamp
        return payload


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _normalize_url(value: object, *, preserve_opaque_query: bool) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    port = parsed.port
    if port and not ((parsed.scheme.casefold() == "http" and port == 80) or (parsed.scheme.casefold() == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = parsed.query
    if not preserve_opaque_query:
        pairs = [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_QUERY_KEYS
            and not any(key.casefold().startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES)
        ]
        query = urlencode(sorted(pairs))
    return urlunsplit((parsed.scheme.casefold(), host, path, query, ""))


def canonical_ical_uid(uid: object, recurrence_id: object = "") -> IdentityHint | None:
    normalized = _normalized_text(uid)
    if not normalized:
        return None
    return IdentityHint(
        kind="ical_uid",
        value_hash=_hash(normalized),
        recurrence_id=_normalized_text(recurrence_id),
        strength="authoritative",
    )


def canonical_provider_thread(provider: object, thread_id: object) -> IdentityHint | None:
    provider_value = _normalized_text(provider)
    thread_value = _normalized_text(thread_id)
    if not provider_value or not thread_value:
        return None
    return IdentityHint(
        kind="provider_thread",
        value_hash=_hash(f"{provider_value}:{thread_value}"),
    )


def canonical_join_url(url: object) -> IdentityHint | None:
    normalized = _normalize_url(url, preserve_opaque_query=False)
    if not normalized:
        return None
    return IdentityHint(kind="join_url", value_hash=_hash(normalized))


def canonical_management_url(url: object) -> IdentityHint | None:
    normalized = _normalize_url(url, preserve_opaque_query=True)
    if not normalized:
        return None
    return IdentityHint(kind="management_url", value_hash=_hash(normalized))


def extract_urls(*values: object) -> list[str]:
    """Return URL-shaped tokens without logging or returning them to callers."""
    urls: list[str] = []
    for value in values:
        text = str(value or "")
        for token in text.replace("<", " ").replace(">", " ").split():
            candidate = token.strip("()[]{}\"'.,;:!?\n\r\t")
            if _normalize_url(candidate, preserve_opaque_query=True):
                urls.append(candidate)
    return urls


def build_hints(
    *,
    provider: object = "",
    thread_id: object = "",
    calendar_components: list[dict[str, object]] | None = None,
    event_values: list[object] | tuple[object, ...] = (),
) -> list[IdentityHint]:
    """Build deduplicated hints from provider metadata and event text."""
    hints: list[IdentityHint] = []
    provider_thread = canonical_provider_thread(provider, thread_id)
    if provider_thread:
        hints.append(provider_thread)
    for component in calendar_components or []:
        uid = canonical_ical_uid(component.get("uid"), component.get("recurrence_id"))
        if uid is None and component.get("uid_hash"):
            uid = IdentityHint(
                kind="ical_uid",
                value_hash=str(component["uid_hash"]),
                recurrence_id=_normalized_text(component.get("recurrence_id")),
                strength="authoritative",
                sequence=_component_sequence(component),
                dtstamp=_component_dtstamp(component),
            )
        if uid:
            hints.append(
                IdentityHint(
                    **{
                        **uid.__dict__,
                        "sequence": _component_sequence(component),
                        "dtstamp": _component_dtstamp(component),
                    }
                )
            )
    for url in extract_urls(*event_values):
        parsed = urlsplit(url)
        identity_text = f"{parsed.path}?{parsed.query}".casefold()
        factory = (
            canonical_management_url
            if any(token in identity_text for token in ("manage", "cancel", "edit", "portal", "registration"))
            else canonical_join_url
        )
        hint = factory(url)
        if hint:
            hints.append(hint)
    deduped: dict[tuple[str, str, str], IdentityHint] = {}
    for hint in hints:
        deduped[(hint.kind, hint.value_hash, hint.recurrence_id)] = hint
    result = list(deduped.values())
    for hint in result:
        logger.debug("Calendar identity hint kind=%s present=true", hint.kind)
    return result


def _component_sequence(component: dict[str, object]) -> int | None:
    try:
        return int(component["sequence"]) if component.get("sequence") is not None else None
    except (TypeError, ValueError):
        return None


def _component_dtstamp(component: dict[str, object]) -> str | None:
    value = component.get("dtstamp")
    return str(value) if value else None


def hints_from_calendar_event(gcal_event: dict[str, object]) -> list[IdentityHint]:
    """Identity hints for an event that lives in the user's Google Calendar.

    Hints were only ever derived from incoming email and stored against Selko's
    own events, so an event the user had already accepted from an invite -- and
    which therefore existed only in their calendar -- could not be matched by
    identity at all. It was compared by title, time and an LLM judgement, and
    when that declined it was proposed as New all over again.

    Google Calendar returns `iCalUID` on every event, and it is the same UID
    that was in the invite. Reading it turns "the user already has this" from a
    text guess into a deterministic match.
    """
    hints: list[IdentityHint] = []

    # A single occurrence of a recurring series is identified by its UID plus
    # the original start; `recurringEventId` alone would collapse the series.
    original_start = gcal_event.get("originalStartTime")
    recurrence_id = ""
    if isinstance(original_start, dict):
        recurrence_id = str(
            original_start.get("dateTime") or original_start.get("date") or ""
        )

    uid_hint = canonical_ical_uid(gcal_event.get("iCalUID"), recurrence_id)
    if uid_hint:
        hints.append(uid_hint)

    join_candidates: list[object] = [gcal_event.get("hangoutLink")]
    conference = gcal_event.get("conferenceData")
    if isinstance(conference, dict):
        entry_points = conference.get("entryPoints")
        if isinstance(entry_points, list):
            for entry in entry_points:
                if isinstance(entry, dict) and entry.get("entryPointType") == "video":
                    join_candidates.append(entry.get("uri"))

    for candidate in join_candidates:
        join_hint = canonical_join_url(candidate)
        if join_hint and not any(
            h.kind == join_hint.kind and h.value_hash == join_hint.value_hash
            for h in hints
        ):
            hints.append(join_hint)

    return hints


def match_by_identity(
    incoming: list[IdentityHint], existing: list[IdentityHint]
) -> IdentityHint | None:
    """Return the hint proving two events are the same, or None.

    An authoritative hint (an iCalendar UID, with its recurrence id) decides on
    its own. A supporting hint such as a join URL does not: several distinct
    sessions of one interview loop legitimately share a meeting room link, and
    merging them would be worse than the duplicate this is meant to prevent.
    """
    if not incoming or not existing:
        return None

    existing_by_key = {
        (hint.kind, hint.value_hash, hint.recurrence_id): hint for hint in existing
    }
    for hint in incoming:
        if hint.strength != "authoritative":
            continue
        found = existing_by_key.get((hint.kind, hint.value_hash, hint.recurrence_id))
        if found:
            return found
    return None
