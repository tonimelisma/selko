"""Unit tests for the events service, on a real database.

The reads (events, mirrored calendar entries, sender rules, sources) run
against a migrated SQLite file (`db`/`factory`). Only the LLM comparison and
the calendar provider's live read are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from selko.db.codec import new_id
from selko.services.events import (
    check_sender_rules,
    derive_delivery_status,
    find_matching_event,
    generate_source_attribution,
)
from tests.event_pipeline import providers_offline


def _rule(factory, user, **values):
    return factory._insert("sender_rules", {"id": new_id(), "user_id": user, **values})


def _entry(factory, user, provider_event_id, *, title="", start, end=None, calendar_id="primary",
           integration=None, **extra):
    """A mirrored calendar entry (calendar_entries row)."""
    integration = integration or factory.integration(user)
    return factory._insert("calendar_entries", {
        "id": new_id(), "user_id": user, "integration_id": integration, "calendar_id": calendar_id,
        "provider_event_id": provider_event_id, "title": title, "start_at": start, "end_at": end,
        **extra,
    })


def _match(db, user, event_data, *, live=None, matched_id=None, compare_error=None, **kwargs):
    with providers_offline(live) as read, \
         patch("selko.services.events.event_processing.compare_events",
               return_value=matched_id, side_effect=compare_error) as compare:
        result = find_matching_event(db, MagicMock(), user, event_data, **kwargs)
    return result, compare, read


class TestDeliveryStatus:
    def test_review_lane_owns_pending_and_terminal_review_states(self):
        assert derive_delivery_status({"review_status": "pending_review"}) == "pending_review"
        assert derive_delivery_status({"review_status": "rejected"}) == "rejected"
        assert derive_delivery_status({"review_status": "cancelled"}) == "cancelled"

    @pytest.mark.parametrize(
        ("work_item", "expected"),
        [
            ({"action": "upsert", "status": "pending", "generation": 1}, "approved"),
            ({"action": "upsert", "status": "processing", "generation": 1}, "syncing"),
            ({"action": "upsert", "status": "succeeded", "generation": 1}, "synced"),
            ({"action": "upsert", "status": "failed", "generation": 1}, "sync_failed"),
            ({"action": "upsert", "status": "blocked", "failure_code": "oauth_required", "generation": 1}, "approved"),
            ({"action": "cancel", "status": "pending", "generation": 1}, "cancel_queued"),
            ({"action": "cancel", "status": "succeeded", "generation": 1}, "cancelled"),
        ],
    )
    def test_delivery_is_derived_from_latest_non_superseded_work_item(self, work_item, expected):
        event = {"review_status": "active", "calendar_work_items": [work_item]}
        assert derive_delivery_status(event) == expected

    def test_superseded_work_does_not_mask_latest_delivery(self):
        event = {
            "review_status": "active",
            "calendar_work_items": [
                {"action": "upsert", "status": "failed", "generation": 1},
                {"action": "upsert", "status": "superseded", "generation": 2},
            ],
        }
        assert derive_delivery_status(event) == "sync_failed"




class TestCheckSenderRules:
    """Sender rule matching reads the user's own rules."""

    def test_exact_email_match(self, db, factory):
        user = factory.user()
        _rule(factory, user, sender_email="school@example.edu", action="auto_approve")

        rule = check_sender_rules(db, user, "school@example.edu")

        assert rule is not None
        assert rule["action"] == "auto_approve"
        assert rule["sender_email"] == "school@example.edu"

    def test_domain_match_when_no_exact(self, db, factory):
        user = factory.user()
        _rule(factory, user, sender_domain="example.edu", action="ignore")

        rule = check_sender_rules(db, user, "newsletter@example.edu")

        assert rule is not None
        assert rule["action"] == "ignore"

    def test_exact_email_wins_over_domain(self, db, factory):
        user = factory.user()
        _rule(factory, user, sender_domain="example.edu", action="ignore")
        _rule(factory, user, sender_email="school@example.edu", action="auto_approve")

        assert check_sender_rules(db, user, "school@example.edu")["action"] == "auto_approve"

    def test_no_match_returns_none(self, db, factory):
        user = factory.user()
        _rule(factory, factory.user(), sender_email="unknown@random.com", action="ignore")

        assert check_sender_rules(db, user, "unknown@random.com") is None

    def test_email_without_domain(self, db, factory):
        """A malformed address without @ matches no domain rule."""
        user = factory.user()
        _rule(factory, user, sender_domain="malformed-email", action="ignore")

        assert check_sender_rules(db, user, "malformed-email") is None


class TestFindMatchingEvent:
    """Event deduplication matching against stored events."""

    def test_returns_none_when_no_start_datetime(self, db, factory):
        user = factory.user()
        result, compare, _ = _match(db, user, {"title": "Some event", "location": "Somewhere"})

        assert result is None
        compare.assert_not_called()

    def test_returns_none_when_no_candidates(self, db, factory):
        user = factory.user()
        factory.event(user, start_datetime="2026-03-16T14:00:00.000000Z")  # another day

        result, compare, _ = _match(
            db, user, {"title": "Birthday Party", "start_datetime": "2026-03-15T14:00:00Z"},
        )

        assert result is None
        compare.assert_not_called()

    def test_calls_compare_when_candidates_exist(self, db, factory):
        user = factory.user()
        event = factory.event(user, title="Birthday Party", start_datetime="2026-03-15T14:00:00.000000Z")

        result, compare, _ = _match(
            db, user, {"title": "Jake's Birthday Party", "start_datetime": "2026-03-15T14:00:00Z"},
            matched_id=event,
        )

        compare.assert_called_once()
        assert [c["id"] for c in compare.call_args.args[2]] == [event]
        assert result is not None
        assert result.match_id == event
        assert result.baseline["title"] == "Birthday Party"

    def test_another_users_event_is_never_a_candidate(self, db, factory):
        user = factory.user()
        factory.event(factory.user(), title="Birthday Party", start_datetime="2026-03-15T14:00:00.000000Z")

        result, compare, _ = _match(
            db, user, {"title": "Birthday Party", "start_datetime": "2026-03-15T14:00:00Z"},
        )

        assert result is None
        compare.assert_not_called()

    def test_handles_llm_comparison_failure(self, db, factory):
        user = factory.user()
        factory.event(user, title="Some Event", start_datetime="2026-03-15T14:00:00.000000Z")

        result, _, _ = _match(
            db, user, {"title": "Some Event", "start_datetime": "2026-03-15T14:00:00Z"},
            compare_error=Exception("LLM error"),
        )

        assert result is None  # a failure is no match, not an error

    @pytest.mark.parametrize("start", ["2026-03-15T14:00:00+00:00", "2026-03-15T14:00:00Z"])
    def test_parses_offset_and_z_suffix(self, db, factory, start):
        user = factory.user()
        event = factory.event(user, start_datetime="2026-03-15T09:00:00.000000Z")

        result, compare, _ = _match(db, user, {"title": "Test Event", "start_datetime": start},
                                    matched_id=None, user_timezone="UTC")

        assert result is None
        assert [c["id"] for c in compare.call_args.args[2]] == [event], "same UTC day, so a candidate"

    def test_the_band_fingerprint_is_the_commits(self, db, factory):
        """The producer fingerprints exactly the band the commit re-checks."""
        from selko.db import events as db_events

        user = factory.user()
        factory.event(user, start_datetime="2026-03-15T14:00:00.000000Z")
        factory.event(user, start_datetime="2026-03-16T14:00:00.000000Z")

        (_, window), _, _ = _match(
            db, user, {"title": "x", "start_datetime": "2026-03-15T14:00:00Z"},
            user_timezone="UTC", with_window=True,
        )

        assert window.fingerprint == db_events.band_fingerprint(
            db, user, window.window_start, window.window_end
        )


class TestGenerateSourceAttribution:
    """Source attribution reads the event's sources and their emails."""

    def test_empty_sources_returns_empty_string(self, db, factory):
        assert generate_source_attribution(db, factory.event(factory.user())) == ""

    def test_single_invitation_source(self, db, factory):
        user = factory.user()
        event = factory.event(user)
        email = factory.email(user, from_email="organizer@example.com", from_name="Event Organizer",
                              date_sent="2026-01-25T13:30:00.000000Z")
        factory.event_source(event, email, source_type="new_invitation")

        attribution = generate_source_attribution(db, event)

        assert "Event Organizer" in attribution
        assert "January" in attribution or "Jan" in attribution
        assert "automatically created" in attribution

    def test_handles_calendar_source(self, db, factory):
        """A calendar-sourced entry has no email."""
        event = factory.event(factory.user())
        factory.event_source(event, source_type="new_invitation")

        attribution = generate_source_attribution(db, event)

        assert "your Google Calendar" in attribution
        assert "automatically created" in attribution


class TestDedupCandidateIntegrity:
    """Regressions from four copies of one school parade on 2026-10-30.

    Three emails described the same 8am parade. Each was compared against a
    candidate list in which every synced Selko event appeared twice (itself and
    its mirrored provider entry) and a shared-calendar recurring event three
    times; none matched. The fourth email did match -- a spouse's copy on a
    shared calendar -- and adopting it created a new event anyway.
    """

    NEW_EVENT = {
        "title": "Morning Halloween Parade",
        "start_datetime": "2026-10-30T08:00:00-07:00",
        "end_datetime": "2026-10-30T09:00:00-07:00",
    }

    def _parade(self, factory, user):
        return factory.event(
            user, review_status="active", title="Halloween Parade",
            start_datetime="2026-10-30T15:00:00.000000Z", end_datetime="2026-10-30T16:00:00.000000Z",
            google_calendar_event_id="own-parade",
        )

    def _mirror(self, factory, user, provider_id, title, **kwargs):
        return _entry(factory, user, provider_id, title=title, start="2026-10-30T15:30:00.000000Z",
                      end="2026-10-30T16:30:00.000000Z", **kwargs)

    def _match(self, db, user, live, matched_id):
        return _match(db, user, dict(self.NEW_EVENT), live=live, matched_id=matched_id,
                      user_timezone="America/Los_Angeles")

    def test_a_synced_events_own_mirror_entry_is_not_a_second_candidate(self, db, factory):
        user = factory.user()
        parade = self._parade(factory, user)
        self._mirror(factory, user, "own-parade", "Halloween Parade")

        _, compare, _ = self._match(db, user, [], None)

        assert [c["id"] for c in compare.call_args.args[2]] == [parade]

    def test_one_provider_event_on_two_calendars_is_one_candidate(self, db, factory):
        user = factory.user()
        integration = factory.integration(user)
        for calendar in ("family", "me@example.com"):
            self._mirror(factory, user, "shared-recurring", "Evening chores",
                         calendar_id=calendar, integration=integration)
        live_copy = {
            "id": "shared-recurring",
            "summary": "Evening chores",
            "start": {"dateTime": "2026-10-30T19:00:00-07:00"},
            "end": {"dateTime": "2026-10-30T19:15:00-07:00"},
        }

        _, compare, _ = self._match(db, user, [live_copy], None)

        candidates = compare.call_args.args[2]
        assert [c["id"] for c in candidates] == ["gcal:shared-recurring"]
        # The live copy wins: it is the one proven to be on the write calendar.
        assert candidates[0]["_source"] == "google_calendar"

    def test_the_comparison_is_told_the_users_timezone(self, db, factory):
        user = factory.user()
        self._parade(factory, user)

        _, compare, _ = self._match(db, user, [], None)

        assert compare.call_args.kwargs["user_timezone"] == "America/Los_Angeles"

    def test_a_match_on_another_calendar_is_not_adopted(self, db, factory):
        user = factory.user()
        self._mirror(factory, user, "spouse-parade", "Costume Parade and Class Party")

        result, _, _ = self._match(db, user, [], "gcal:spouse-parade")

        assert result is not None
        assert result.on_other_calendar is True

    def test_a_match_on_the_write_calendar_is_still_adopted(self, db, factory):
        user = factory.user()
        self._mirror(factory, user, "own-external", "Costume Parade")
        live = {
            "id": "own-external",
            "summary": "Costume Parade",
            "start": {"dateTime": "2026-10-30T08:30:00-07:00"},
            "end": {"dateTime": "2026-10-30T09:00:00-07:00"},
        }

        result, _, _ = self._match(db, user, [live], "gcal:own-external")

        assert result.on_other_calendar is False
        assert result.gcal_raw == live

    def test_saving_a_match_on_another_calendar_creates_nothing(self, db, factory):
        from selko.api.schemas.calendar import CalendarEventExtraction
        from selko.services.events import save_extracted_events
        from tests.event_pipeline import claimed_email, gateway, lease

        user = factory.user()
        factory._insert("user_calendar_settings", {"user_id": user, "timezone": "America/Los_Angeles"})
        _entry(factory, user, "spouse-parade", title="Costume Parade and Class Party",
               start="2099-10-30T15:30:00.000000Z", end="2099-10-30T16:30:00.000000Z")
        email = claimed_email(factory, user)
        extraction = CalendarEventExtraction.model_validate({
            "email_message_id": "msg-1",
            "sender_email": "teacher@example.com",
            "events_found": True,
            "events": [{
                "title": "Costume Parade and Class Party",
                "start_datetime": "2099-10-30T08:30:00",
                "end_datetime": "2099-10-30T09:30:00",
                "description": "Parade on the blacktop, then the class party.",
            }],
        })

        with providers_offline(), \
             patch("selko.services.events.event_processing.compare_events",
                   return_value="gcal:spouse-parade"):
            created, updated = save_extracted_events(
                db, gateway(), user, email, extraction, **lease(db, email),
            )

        assert (created, updated) == (0, 0)
        assert db.query("SELECT 1 FROM events") == []


class TestFindMatchingEventGCal:
    """GCal read-back during deduplication."""

    LIVE = [{
        "id": "gcal-abc",
        "summary": "Team Meeting",
        "start": {"dateTime": "2026-03-15T14:00:00Z"},
        "end": {"dateTime": "2026-03-15T15:00:00Z"},
        "location": "Room A",
        "description": "Weekly sync",
    }]
    EVENT = {"title": "Team Meeting", "start_datetime": "2026-03-15T14:00:00Z"}

    def test_includes_gcal_candidates(self, db, factory):
        user = factory.user()

        result, compare, _ = _match(db, user, dict(self.EVENT), live=self.LIVE, matched_id="gcal:gcal-abc")

        compare.assert_called_once()
        candidates = compare.call_args.args[2]
        assert len(candidates) == 1
        assert candidates[0]["id"] == "gcal:gcal-abc"
        assert candidates[0]["_source"] == "google_calendar"
        assert result is not None
        assert result.match_id == "gcal:gcal-abc"
        assert result.is_gcal is True

    def test_skips_selko_managed_gcal_events(self, db, factory):
        user = factory.user()
        managed = [{**self.LIVE[0], "extendedProperties": {"private": {"selko_event_id": "event-123"}}}]

        result, compare, _ = _match(db, user, dict(self.EVENT), live=managed)

        assert result is None
        compare.assert_not_called()

    def test_graceful_gcal_failure(self, db, factory):
        user = factory.user()
        event = factory.event(user, title="Team Meeting", start_datetime="2026-03-15T14:00:00.000000Z")

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range",
                   side_effect=Exception("API error")), \
             patch("selko.services.events.event_processing.compare_events", return_value=event):
            result = find_matching_event(db, MagicMock(), user, dict(self.EVENT))

        assert result is not None
        assert result.match_id == event

    def test_evening_event_queries_local_day_not_utc_day(self, db, factory):
        """Regression: an evening local event must not query the next UTC day.

        2026-07-27T20:00:00-07:00 (8pm Pacific) is 2026-07-28T03:00:00Z — the
        old code queried the UTC calendar day (07-27T00:00Z-07-27T23:59Z) and
        never saw same-evening duplicates stored as 07-28T03:00:00Z.
        """
        user = factory.user()
        evening = factory.event(user, title="Application Deadline", start_datetime="2026-07-28T03:00:00.000000Z")
        mirrored = _entry(factory, user, "deadline-entry", title="Deadline",
                          start="2026-07-28T03:30:00.000000Z")
        factory.event(user, title="Next local day", start_datetime="2026-07-28T07:00:00.000000Z")

        (_, window), compare, read = _match(
            db, user, {"title": "Application Deadline", "start_datetime": "2026-07-27T20:00:00-07:00"},
            user_timezone="America/Los_Angeles", with_window=True,
        )

        # Stored events and mirrored entries share the one band the fence covers.
        assert (window.window_start, window.window_end) == (
            "2026-07-27T07:00:00+00:00", "2026-07-28T07:00:00+00:00",
        )
        ids = {c["id"] for c in compare.call_args.args[2]}
        assert ids == {evening, "gcal:deadline-entry"}
        assert mirrored
        assert read.call_args.args[2] == "2026-07-27T07:00:00+00:00"
        assert read.call_args.args[3] == "2026-07-28T07:00:00+00:00"

    def test_reuses_existing_row_linked_to_matched_gcal_event(self, db, factory):
        """Regression: a second email matching the same GCal event must reuse
        the Selko row already tracking it, not stack a second change card."""
        user = factory.user()
        existing = factory.event(
            user, review_status="active", title="Team Meeting",
            start_datetime="2026-03-14T14:00:00.000000Z", google_calendar_event_id="gcal-abc",
        )

        result, _, _ = _match(db, user, dict(self.EVENT), live=self.LIVE, matched_id="gcal:gcal-abc")

        assert result is not None
        assert result.match_id == existing
        assert result.is_gcal is False
        assert result.baseline["title"] == "Team Meeting"


class TestMirroredEntriesAreCandidates:
    """A mirrored calendar entry is a match candidate, not only a hint target.

    This is the defect that produced four "new" Snowflake interviews while
    identical entries sat on an imported Google calendar at the same minute:
    mirrored entries reached the candidate set only when an identity hint
    named them, and an LLM-extracted event from plain email text has no hint
    to name one with.
    """

    WINDOW = ("2026-09-09T07:00:00+00:00", "2026-09-10T07:00:00+00:00")

    def test_a_mirrored_entry_is_offered_to_matching(self, db, factory):
        from selko.services.events import _mirror_candidates_in_window

        user = factory.user()
        _entry(factory, user, "abc123", title="Snowflake Behavioral Interview",
               start="2026-09-09T17:00:00.000000Z", end="2026-09-09T18:00:00.000000Z", location="")

        candidates = _mirror_candidates_in_window(db, user, *self.WINDOW)

        assert candidates == [{
            "id": "gcal:abc123",
            "title": "Snowflake Behavioral Interview",
            "start_datetime": "2026-09-09T17:00:00.000000Z",
            "end_datetime": "2026-09-09T18:00:00.000000Z",
            "location": "",
            "_source": "calendar_mirror",
        }]

    def test_deleted_and_out_of_band_entries_are_not_candidates(self, db, factory):
        from selko.services.events import _mirror_candidates_in_window

        user = factory.user()
        integration = factory.integration(user)
        _entry(factory, user, "gone", start="2026-09-09T17:00:00.000000Z", integration=integration,
               deleted_at="2026-09-01T00:00:00.000000Z")
        _entry(factory, user, "tomorrow", start="2026-09-10T07:00:00.000000Z", integration=integration)
        _entry(factory, factory.user(), "someone-else", start="2026-09-09T17:00:00.000000Z")

        assert _mirror_candidates_in_window(db, user, *self.WINDOW) == []

    def test_a_failed_mirror_read_does_not_lose_the_extraction(self, tmp_path):
        """Fail toward a duplicate the user can reject, never toward silence."""
        from selko.db.connection import Database
        from selko.services.events import _mirror_candidates_in_window

        broken = Database(tmp_path / "unmigrated.db")
        try:
            assert _mirror_candidates_in_window(
                broken, "00000000-0000-0000-0000-000000000001", *self.WINDOW
            ) == []
        finally:
            broken.close()
