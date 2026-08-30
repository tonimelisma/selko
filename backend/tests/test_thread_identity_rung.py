"""Rung 3: a provider thread identifies an existing event, never a new one.

Mail carrying no invite has no UID, so no rung above this can reach it. Without
a hint the candidate set is the local day of the *new* start, which an event
rescheduled to another date is not in -- so a plain-text "moved to the 11th"
could not be matched to the event it reschedules. That is scenario S5, and S4
for a text update of an ICS-created event.
"""

from __future__ import annotations

from selko.services.events import (
    CandidateWindow,
    _identity_match,
    _thread_update_is_plausible,
)
from selko.services.event_identity import canonical_provider_thread


def _window() -> CandidateWindow:
    return CandidateWindow(
        window_start="2026-09-01T00:00:00+00:00",
        window_end="2026-09-02T00:00:00+00:00",
        fingerprint="fp",
        hint_keys=(),
        hint_fingerprint=None,
    )


def _thread_setup(existing_title: str, event_ids: list[str]):
    hint = canonical_provider_thread("outlook", "thread-1")
    key = f"{hint.kind}|{hint.value_hash}|{hint.recurrence_id}"
    rows = {key: [{"event_id": eid, "kind": hint.kind} for eid in event_ids]}
    events = {
        eid: {
            "id": eid,
            "title": existing_title,
            "start_datetime": "2026-09-04T17:00:00+00:00",
            "review_status": "active",
        }
        for eid in event_ids
    }
    return hint, rows, events


def test_a_thread_matches_its_event_across_a_date_change():
    """The reschedule case: new date, same thread, same event."""
    hint, rows, events = _thread_setup("Team Standup", ["event-1"])
    match = _identity_match(
        rows, events, [hint],
        {"title": "Team Standup", "start_datetime": "2026-09-11T17:00:00+00:00"},
        _window(),
    )
    assert match is not None
    assert match.match_id == "event-1"


def test_an_ambiguous_thread_decides_nothing():
    """Two events on one thread: the thread cannot say which was meant."""
    hint, rows, events = _thread_setup("Team Standup", ["event-1", "event-2"])
    match = _identity_match(
        rows, events, [hint],
        {"title": "Team Standup", "start_datetime": "2026-09-11T17:00:00+00:00"},
        _window(),
    )
    assert match is None


def test_a_shared_thread_does_not_merge_different_events():
    """A newsletter thread carries many happenings; they are not one event."""
    hint, rows, events = _thread_setup("Autumn Book Fair", ["event-1"])
    match = _identity_match(
        rows, events, [hint],
        {"title": "Winter Concert", "start_datetime": "2026-09-11T17:00:00+00:00"},
        _window(),
    )
    assert match is None


def test_a_cosmetic_title_edit_still_matches():
    assert _thread_update_is_plausible(
        {"title": "Team Standup (moved)"}, {"title": "Team Standup"}
    )
    assert _thread_update_is_plausible({"title": "Team Standup."}, {"title": "team standup"})


def test_an_empty_title_never_matches():
    """Absent evidence is not evidence of sameness."""
    assert not _thread_update_is_plausible({"title": ""}, {"title": "Team Standup"})
    assert not _thread_update_is_plausible({"title": "Team Standup"}, {"title": None})
