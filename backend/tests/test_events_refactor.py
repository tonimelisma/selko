"""Unit tests for the event pipeline helpers, on a real database.

Covers mark_email_status, should_skip_email, normalize_event_data,
save_extracted_events and the process_email_for_events orchestrator. The
database, the matching reads and the fenced commit are real (`db`/`factory`);
the LLM (`extract_calendar_events`, `compare_events`, `propose_event_update`)
and the calendar provider's live read are mocked.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from zoneinfo import ZoneInfo

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.db import events as db_events
from selko.services.event_diff import EventChangeSet, FieldChange
from selko.services.events import (
    EventsError,
    ResolutionConflictExhausted,
    _fetch_baseline_info_date,
    mark_email_status,
    normalize_event_data,
    process_email_for_events,
    save_extracted_events,
    should_skip_email,
)
from tests.event_pipeline import (
    claimed_email,
    email_row,
    event_at,
    gateway,
    lease,
    providers_offline,
    spy_commit,  # noqa: F401  (fixture)
    stored_attachment,
)

TEST_TIMEZONE = "America/New_York"
TEST_ZONE = ZoneInfo(TEST_TIMEZONE)
FIXED_NOW = datetime(2026, 4, 9, 12, 0, tzinfo=TEST_ZONE)


# --- Helpers ---


def _future(days: int = 30, hour: int = 14) -> datetime:
    future = datetime.now() + timedelta(days=days)
    return future.replace(hour=hour, minute=0, second=0, microsecond=0)


def _make_calendar_event(**overrides):
    """A CalendarEvent with future-dated defaults (the past-event filter keeps it)."""
    start = _future()
    defaults = {
        "title": "Team Meeting",
        "start_datetime": start,
        "end_datetime": start + timedelta(hours=1),
        "location": "Room A",
        "description": "Weekly sync",
    }
    defaults.update(overrides)
    return CalendarEvent(**defaults)


def _make_extraction(events=None, events_found=True):
    return CalendarEventExtraction(
        email_message_id="msg-123",
        email_date=datetime(2026, 4, 9, 10, 0),
        sender_email="sender@example.com",
        events_found=events_found,
        events=events or [],
    )


@pytest.fixture
def user(factory):
    return factory.user()


@pytest.fixture
def email(factory, user):
    return claimed_email(factory, user, from_email="sender@example.com", date_sent="2026-04-09T10:00:00.000000Z")


def _save(db, user, email, extraction, **kwargs):
    kwargs.setdefault("current_time", FIXED_NOW)
    with providers_offline(kwargs.pop("live", None)):
        return save_extracted_events(db, gateway(), user, email, extraction, **lease(db, email), **kwargs)


def _events(db, user):
    return [db.schema.decode("events", r) for r in db.query(
        "SELECT * FROM events WHERE user_id = ? ORDER BY title", (user,))]


def _statuses(db, email):
    row = email_row(db, email)
    return row["processing_status"], row["processing_outcome"]


class TestMarkEmailStatus:
    """mark_email_status writes the status fields and nothing else."""

    def test_sets_processing_with_timestamp(self, db, factory, user):
        email = factory.email(user, processing_status="processing", processing_outcome="no_event",
                              processing_error="old", locked_by="w",
                              locked_until="2099-01-01T00:00:00.000000Z")
        mark_email_status(db, email, "processing")

        row = factory.row("emails", email)
        assert row["processing_status"] == "processing"
        assert row["processed_at"] is not None
        assert (row["processing_error"], row["processing_outcome"]) == (None, None)

    def test_sets_processed_without_timestamp(self, db, factory, user):
        email = factory.email(user, processing_status="processing", processing_error="old")
        mark_email_status(db, email, "processed")

        row = factory.row("emails", email)
        assert row["processing_status"] == "processed"
        assert row["processed_at"] is None
        assert row["processing_error"] is None

    def test_sets_skipped(self, db, factory, user):
        email = factory.email(user, processing_status="processing", processing_error="kept")
        mark_email_status(db, email, "skipped")

        row = factory.row("emails", email)
        assert row["processing_status"] == "skipped"
        assert row["processing_error"] == "kept", "skipped does not touch the error"

    def test_sets_failed_with_error(self, db, factory, user):
        email = factory.email(user, processing_status="processing")
        mark_email_status(db, email, "failed", error="LLM timeout")

        row = factory.row("emails", email)
        assert (row["processing_status"], row["processing_error"]) == ("failed", "LLM timeout")

    def test_outcome_explanation_and_result_are_stored(self, db, factory, user):
        email = factory.email(user, processing_status="processing")
        mark_email_status(db, email, "processed", outcome="no_event", explanation="why",
                          result={"num_events": 0})

        row = factory.row("emails", email)
        assert (row["processing_outcome"], row["processing_explanation"]) == ("no_event", "why")
        assert row["processing_result"] == {"num_events": 0}


class TestShouldSkipEmail:
    """should_skip_email reads the user's real sender rules."""

    def _rule(self, factory, user, **values):
        from selko.db.codec import new_id

        factory._insert("sender_rules", {"id": new_id(), "user_id": user, **values})

    def test_returns_true_for_ignored_sender(self, db, factory, user):
        self._rule(factory, user, sender_email="spam@example.com", action="ignore")
        assert should_skip_email(db, user, "spam@example.com") is True

    def test_returns_true_for_ignored_domain(self, db, factory, user):
        self._rule(factory, user, sender_domain="spam.example", action="ignore")
        assert should_skip_email(db, user, "anyone@spam.example") is True

    def test_returns_false_for_auto_approve_sender(self, db, factory, user):
        self._rule(factory, user, sender_email="school@example.com", action="auto_approve")
        assert should_skip_email(db, user, "school@example.com") is False

    def test_returns_false_when_no_rule(self, db, factory, user):
        assert should_skip_email(db, user, "unknown@example.com") is False

    def test_another_users_rule_does_not_apply(self, db, factory, user):
        self._rule(factory, factory.user(), sender_email="spam@example.com", action="ignore")
        assert should_skip_email(db, user, "spam@example.com") is False


class TestNormalizeEventData:
    """Tests for normalize_event_data helper."""

    def test_converts_all_fields(self):
        # Explicit fixed dates so the exact-ISO assertions below are stable.
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 14, 0),
            end_datetime=datetime(2026, 3, 15, 15, 0),
        )
        result = normalize_event_data(event)

        assert result["title"] == "Team Meeting"
        # Naive datetimes are localized to America/New_York (default); March 15 = EDT (-04:00)
        assert result["start_datetime"] == "2026-03-15T14:00:00-04:00"
        assert result["end_datetime"] == "2026-03-15T15:00:00-04:00"
        assert result["all_day"] is False
        assert result["location"] == "Room A"
        assert result["description"] == "Weekly sync"
        assert result["source_quote"] == ""

    def test_handles_none_datetimes(self):
        event = _make_calendar_event(start_datetime=None, end_datetime=None)
        result = normalize_event_data(event)

        assert result["start_datetime"] is None
        assert result["end_datetime"] is None

    def test_handles_missing_optional_fields(self):
        event = _make_calendar_event(location=None, description="")
        result = normalize_event_data(event)

        assert result["location"] is None
        assert result["description"] == ""

    def test_zero_length_event_gets_one_hour_duration(self):
        """Regression: end == start (e.g. an extracted deadline) must not sync
        as a zero-length sliver."""
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 20, 0),
            end_datetime=datetime(2026, 3, 15, 20, 0),
        )
        result = normalize_event_data(event)

        assert result["start_datetime"] == "2026-03-15T20:00:00-04:00"
        assert result["end_datetime"] == "2026-03-15T21:00:00-04:00"

    def test_missing_end_gets_one_hour_duration(self):
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 20, 0), end_datetime=None
        )
        result = normalize_event_data(event)

        assert result["end_datetime"] == "2026-03-15T21:00:00-04:00"

    def test_end_before_start_gets_one_hour_duration(self):
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 20, 0),
            end_datetime=datetime(2026, 3, 15, 19, 0),
        )
        result = normalize_event_data(event)

        assert result["end_datetime"] == "2026-03-15T21:00:00-04:00"

    def test_valid_duration_is_untouched(self):
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 20, 0),
            end_datetime=datetime(2026, 3, 15, 21, 30),
        )
        result = normalize_event_data(event)

        assert result["end_datetime"] == "2026-03-15T21:30:00-04:00"

    def test_all_day_zero_length_is_untouched(self):
        """all_day events must never get the timed-event duration guard."""
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 0, 0),
            end_datetime=datetime(2026, 3, 15, 0, 0),
            all_day=True,
        )
        result = normalize_event_data(event)

        assert result["end_datetime"] == "2026-03-15T00:00:00-04:00"



class TestSaveExtractedEvents:
    """save_extracted_events builds decisions and the real commit writes them."""

    def test_creates_new_event_when_no_match(self, db, user, email, spy_commit):
        num_new, num_updated = _save(db, user, email, _make_extraction(events=[_make_calendar_event()]))

        assert (num_new, num_updated) == (1, 0)
        assert spy_commit.decisions[0]["action"] == "create"
        (event,) = _events(db, user)
        assert (event["title"], event["review_status"]) == ("Team Meeting", "pending_review")
        sources = db.query("SELECT email_id FROM event_sources WHERE event_id = ?", (event["id"],))
        assert [s["email_id"] for s in sources] == [email]
        assert _statuses(db, email)[0] == "processed"

    def test_retries_resolution_after_candidate_conflict(self, db, factory, user, email, monkeypatch):
        """Every attempt meets a band that moved after it was read, until the budget runs out."""
        start = _future()
        rival = event_at(factory, user, start + timedelta(hours=3), title="Rival")
        real = db_events.commit_email_extraction
        calls = []

        def band_moves_first(database, *args):
            calls.append(args)
            with database.write() as tx:  # another writer touches the band
                tx.execute("UPDATE events SET updated_at = ? WHERE id = ?", (tx.now_text, rival))
            return real(database, *args)

        monkeypatch.setattr("selko.services.events.db_events.commit_email_extraction", band_moves_first)
        with patch("selko.services.events.event_processing.compare_events", return_value=None), \
             pytest.raises(ResolutionConflictExhausted):
            _save(db, user, email, _make_extraction(events=[_make_calendar_event(start_datetime=start)]))

        assert len(calls) == 3
        assert [e["title"] for e in _events(db, user)] == ["Rival"], "a conflict writes nothing"
        assert _statuses(db, email)[0] == "processing", "the email stays claimed for a retry"

    def test_skips_event_with_null_start_datetime(self, db, user, email, spy_commit):
        """Regression: events with no start_datetime must not be created or matched."""
        extraction = _make_extraction(events=[_make_calendar_event(start_datetime=None, end_datetime=None)])

        with patch("selko.services.events.find_matching_event") as match:
            assert _save(db, user, email, extraction) == (0, 0)

        match.assert_not_called()
        assert spy_commit.decisions == []
        assert _events(db, user) == []

    def test_skips_noop_match(self, db, factory, user, email, spy_commit):
        event = event_at(factory, user, _future(), review_status="active")

        with patch("selko.services.events.event_processing.compare_events", return_value=event), \
             patch("selko.services.events.event_processing.propose_event_update",
                   return_value=EventChangeSet(kind="noop", changes=[])):
            assert _save(db, user, email, _make_extraction(events=[_make_calendar_event()])) == (0, 0)

        assert spy_commit.decisions == [] or all(d["action"] == "noop" for d in spy_commit.decisions)
        assert len(_events(db, user)) == 1
        assert db.query("SELECT 1 FROM event_change_proposals") == []

    def test_proposed_zero_length_change_gets_one_hour_duration(self, db, factory, user, email, spy_commit):
        """Regression: a proposal with matching start/end (e.g. a re-extracted
        deadline) must not persist a zero-length change."""
        start = _future()
        event = event_at(factory, user, start, title="Application Deadline", review_status="active")
        factory.event_source(event)  # from the user's calendar: the change waits in review
        later = (start + timedelta(days=5)).isoformat()
        stored = factory.row("events", event)
        change_set = EventChangeSet(kind="material_update", changes=[
            FieldChange(field="start_datetime", before=stored["start_datetime"], after=later),
            FieldChange(field="end_datetime", before=stored["end_datetime"], after=later),
        ])

        with patch("selko.services.events.event_processing.compare_events", return_value=event), \
             patch("selko.services.events.event_processing.propose_event_update", return_value=change_set):
            _save(db, user, email, _make_extraction(events=[_make_calendar_event(title="Application Deadline")]))

        decision = spy_commit.decisions[0]
        assert decision["source"]["extracted_data"]["all_day"] is False  # extraction default is timed
        applied = EventChangeSet.model_validate(decision["source"]["change_set"])
        start_after = next(c.after for c in applied.changes if c.field == "start_datetime")
        end_after = next(c.after for c in applied.changes if c.field == "end_datetime")
        assert datetime.fromisoformat(end_after) == datetime.fromisoformat(start_after) + timedelta(hours=1)
        (proposal,) = db.query("SELECT change_set FROM event_change_proposals WHERE event_id = ?", (event,))
        assert "end_datetime" in proposal["change_set"]

    def test_adopts_a_calendar_event_when_the_change_is_material(self, db, user, email, spy_commit):
        start = _future()
        live = [{
            "id": "abc-123", "summary": "Team Meeting", "location": "Room A",
            "start": {"dateTime": start.replace(tzinfo=TEST_ZONE).isoformat()},
            "end": {"dateTime": (start + timedelta(hours=1)).replace(tzinfo=TEST_ZONE).isoformat()},
        }]
        change_set = EventChangeSet(kind="material_update", changes=[
            FieldChange(field="location", before="Room A", after="Room B"),
        ])

        with patch("selko.services.events.event_processing.compare_events", return_value="gcal:abc-123"), \
             patch("selko.services.events.event_processing.propose_event_update", return_value=change_set):
            num_new, num_updated = _save(
                db, user, email, _make_extraction(events=[_make_calendar_event(location="Room B")]), live=live,
            )

        assert (num_new, num_updated) == (0, 1)
        decision = spy_commit.decisions[0]
        assert decision["action"] == "create"
        assert decision["fields"]["google_calendar_event_id"] == "abc-123"
        (event,) = _events(db, user)
        assert event["google_calendar_event_id"] == "abc-123"
        (proposal,) = db.query("SELECT status FROM event_change_proposals WHERE event_id = ?", (event["id"],))
        assert proposal["status"] == "pending", "a calendar event's change waits for the user"

    def test_proposes_local_change_when_material(self, db, factory, user, email, spy_commit):
        event = event_at(factory, user, _future(), review_status="active")
        factory.event_source(event)
        change_set = EventChangeSet(kind="material_update", changes=[
            FieldChange(field="location", before="Room A", after="Room B"),
        ])

        with patch("selko.services.events.event_processing.compare_events", return_value=event), \
             patch("selko.services.events.event_processing.propose_event_update", return_value=change_set):
            assert _save(db, user, email, _make_extraction(events=[_make_calendar_event()])) == (0, 1)

        assert spy_commit.decisions[0]["action"] == "update"
        assert factory.row("events", event)["location"] == "Room A"
        (proposal,) = db.query("SELECT status FROM event_change_proposals WHERE event_id = ?", (event,))
        assert proposal["status"] == "pending"

    def test_passes_recency_context_to_propose_event_update(self, db, factory, user, email):
        """Regression: the email's date_sent and the matched event's newest
        source date must reach propose_event_update for the recency rules."""
        event = event_at(factory, user, _future(), review_status="active")
        for sent in ("2026-03-10T09:00:00.000000Z", "2026-03-08T09:00:00.000000Z"):
            factory.event_source(event, factory.email(user, date_sent=sent))

        with patch("selko.services.events.event_processing.compare_events", return_value=event), \
             patch("selko.services.events.event_processing.propose_event_update",
                   return_value=EventChangeSet(kind="noop", changes=[])) as propose:
            _save(db, user, email, _make_extraction(events=[_make_calendar_event()]),
                  email_date_sent="2026-03-14T12:00:00Z")

        propose.assert_called_once()
        assert propose.call_args.kwargs["email_date_sent"] == "2026-03-14T12:00:00Z"
        assert propose.call_args.kwargs["baseline_info_date"] == "2026-03-10T09:00:00.000000Z"

    def test_gcal_match_passes_none_baseline_info_date(self, db, user, email):
        """GCal-baseline matches have no local event_sources history to query."""
        start = _future()
        live = [{"id": "abc-123", "summary": "Team Meeting",
                 "start": {"dateTime": start.replace(tzinfo=TEST_ZONE).isoformat()},
                 "end": {"dateTime": (start + timedelta(hours=1)).replace(tzinfo=TEST_ZONE).isoformat()}}]

        with patch("selko.services.events.event_processing.compare_events", return_value="gcal:abc-123"), \
             patch("selko.services.events._fetch_baseline_info_date") as fetch_date, \
             patch("selko.services.events.event_processing.propose_event_update",
                   return_value=EventChangeSet(kind="noop", changes=[])) as propose:
            _save(db, user, email, _make_extraction(events=[_make_calendar_event()]), live=live)

        fetch_date.assert_not_called()
        assert propose.call_args.kwargs["baseline_info_date"] is None

    def test_handles_multiple_events(self, db, factory, user, email, spy_commit):
        start = _future()
        existing = event_at(factory, user, start + timedelta(days=1), title="Event 2", review_status="active")
        extraction = _make_extraction(events=[
            _make_calendar_event(title="Event 1", start_datetime=start),
            _make_calendar_event(title="Event 2", start_datetime=start + timedelta(days=1)),
            _make_calendar_event(title="Event 3", start_datetime=start + timedelta(days=2)),
        ])
        change_set = EventChangeSet(kind="enrichment", changes=[
            FieldChange(field="description", before="Weekly sync", after="Weekly sync, bring notes"),
        ])

        with patch("selko.services.events.event_processing.compare_events",
                   side_effect=lambda gw, event, candidates, **kw: existing
                   if any(c["id"] == existing for c in candidates) else None), \
             patch("selko.services.events.event_processing.propose_event_update", return_value=change_set):
            assert _save(db, user, email, extraction) == (2, 1)

        assert [e["title"] for e in _events(db, user)] == ["Event 1", "Event 2", "Event 3"]
        assert len(spy_commit.calls) == 1, "one email, one atomic commit"

    def test_returns_zero_for_empty_extraction(self, db, user, email, spy_commit):
        assert _save(db, user, email, _make_extraction(events=[], events_found=False)) == (0, 0)
        assert spy_commit.decisions == []
        assert _statuses(db, email)[0] == "processed"

    def test_skips_events_older_than_24_hours(self, db, user, email):
        old_event = _make_calendar_event(
            title="Old Event",
            start_datetime=(FIXED_NOW - timedelta(hours=24, minutes=1)).replace(tzinfo=None),
            end_datetime=(FIXED_NOW - timedelta(hours=23, minutes=1)).replace(tzinfo=None),
        )

        with patch("selko.services.events.find_matching_event") as match:
            assert _save(db, user, email, _make_extraction(events=[old_event])) == (0, 0)

        match.assert_not_called()
        assert _events(db, user) == []

    def test_keeps_events_exactly_at_24_hour_cutoff(self, db, user, email, spy_commit):
        boundary_event = _make_calendar_event(
            title="Boundary Event",
            start_datetime=(FIXED_NOW - timedelta(hours=24)).replace(tzinfo=None),
            end_datetime=(FIXED_NOW - timedelta(hours=23)).replace(tzinfo=None),
        )

        assert _save(db, user, email, _make_extraction(events=[boundary_event])) == (1, 0)
        assert spy_commit.decisions[0]["action"] == "create"
        assert [e["title"] for e in _events(db, user)] == ["Boundary Event"]

    def test_keeps_timezone_aware_events_inside_cutoff_window(self, db, user, email, spy_commit):
        aware_start = (FIXED_NOW - timedelta(hours=23)).astimezone(timezone.utc)
        extraction = _make_extraction(events=[_make_calendar_event(
            title="Aware Event", start_datetime=aware_start, end_datetime=aware_start + timedelta(hours=1),
        )])

        assert _save(db, user, email, extraction) == (1, 0)
        assert spy_commit.decisions[0]["action"] == "create"

    def test_filters_past_events_against_the_real_clock(self, db, user, email, spy_commit):
        """Events >24h in the past are skipped, recent and future ones saved."""
        now = datetime.now(timezone.utc)
        extraction = _make_extraction(events=[
            _make_calendar_event(title="Past Event", start_datetime=now - timedelta(hours=48),
                                 end_datetime=now - timedelta(hours=47)),
            _make_calendar_event(title="Just Happened", start_datetime=now - timedelta(hours=12),
                                 end_datetime=now - timedelta(hours=11)),
            _make_calendar_event(title="Future Event", start_datetime=now + timedelta(days=7),
                                 end_datetime=now + timedelta(days=7, hours=1)),
        ])

        assert _save(db, user, email, extraction, current_time=None) == (2, 0)
        assert [e["title"] for e in _events(db, user)] == ["Future Event", "Just Happened"]

    def test_a_stale_lease_writes_nothing(self, db, factory, user, spy_commit):
        """The worker lost the email while extracting: its decisions never land."""
        email = claimed_email(factory, user, worker="new-owner", generation=2)
        with providers_offline():
            save_extracted_events(
                db, gateway(), user, email, _make_extraction(events=[_make_calendar_event()]),
                current_time=FIXED_NOW, locked_by="old-owner", lock_generation=1,
            )

        assert spy_commit.results == [{"fenced": True, "applied": 0}]
        assert _events(db, user) == []


class TestProcessEmailPipeline:
    """process_email_for_events end to end, from the claimed email row."""

    def _process(self, db, user, email, **patches):
        extraction = patches.pop("extraction", None)
        with providers_offline(), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction) as extract, \
             patch("selko.services.events.event_processing.compare_events", return_value=None):
            result = process_email_for_events(db, gateway(), email, user, email_row=email_row(db, email))
        return result, extract

    def test_happy_path_end_to_end(self, db, user, email):
        result, extract = self._process(
            db, user, email, extraction=_make_extraction(events=[_make_calendar_event()]),
        )

        assert (result["num_events"], result["num_new"], result["num_updated"]) == (1, 1, 0)
        extract.assert_called_once()
        assert _statuses(db, email) == ("processed", "event_created")
        row = email_row(db, email)
        assert row["processing_result"] == {"num_events": 1, "num_new": 1, "num_updated": 0}
        assert row["locked_by"] is None, "the commit released the lease"
        assert [e["review_status"] for e in _events(db, user)] == ["pending_review"]

    def test_sender_ignored_short_circuits(self, db, factory, user, email):
        from selko.db.codec import new_id

        factory._insert("sender_rules", {"id": new_id(), "user_id": user,
                                         "sender_email": "sender@example.com", "action": "ignore"})
        result, extract = self._process(db, user, email)

        assert result["skipped"] is True
        assert result["num_events"] == 0
        extract.assert_not_called()
        assert _statuses(db, email)[0] == "skipped"
        assert _events(db, user) == []

    def test_calendar_invite_already_on_the_calendar_short_circuits(self, db, factory, user):
        """An invitation the calendar already holds must not reach extraction.

        This used to be unconditional -- every invitation was skipped as
        "already handled by your email client and calendar", which is an
        assumption about a system Selko could not see. It was wrong for five
        interview invitations that were skipped while their calendar entries
        never existed, so the only record became a plain-text confirmation whose
        events carried no UID. The skip now requires the mirror to confirm it.
        """
        from selko.db.codec import new_id

        email = claimed_email(factory, user, from_email="organizer@example.com", is_calendar_invite=True)
        factory._insert("email_calendar_components", {
            "id": new_id(), "email_id": email, "user_id": user, "component_index": 0,
            "method": "REQUEST", "uid_hash": "uid-on-calendar"})
        integration = factory.integration(user)
        entry = factory._insert("calendar_entries", {
            "id": new_id(), "user_id": user, "integration_id": integration, "calendar_id": "primary",
            "provider_event_id": "g-1", "title": "Interview"})
        factory._insert("event_identity_hints", {
            "id": new_id(), "user_id": user, "calendar_entry_id": entry, "kind": "ical_uid",
            "value_hash": "uid-on-calendar", "strength": "authoritative"})

        result, extract = self._process(db, user, email)

        assert result["num_events"] == 0
        extract.assert_not_called()
        # Regression: the backstop marks the email skipped, matching the
        # ingest-time marking, so it never shows up as a false "processed" row.
        assert _statuses(db, email) == ("skipped", "calendar_invite")

    def test_an_invite_the_calendar_does_not_hold_is_processed(self, db, factory, user):
        """The case the old rule got wrong, stated as a test.

        An invitation the user never accepted is not on their calendar, so
        skipping it means the commitment is never surfaced anywhere. Showing an
        event they already have is a duplicate they can reject; dropping one
        they do not have is a meeting they never learn about, so this fails
        toward processing.
        """
        from selko.db.codec import new_id

        email = claimed_email(factory, user, from_email="organizer@example.com", is_calendar_invite=True)
        factory._insert("email_calendar_components", {
            "id": new_id(), "email_id": email, "user_id": user, "component_index": 0,
            "method": "REQUEST", "uid_hash": "uid-nowhere"})

        _, extract = self._process(db, user, email, extraction=_make_extraction(events=[], events_found=False))

        extract.assert_called_once()
        assert _statuses(db, email) == ("processed", "no_event")

    def test_ics_invite_method_short_circuits(self, db, factory, user):
        """Regression: a Gmail METHOD:REQUEST .ics attachment must never reach LLM extraction."""
        from selko.db.codec import new_id

        email = claimed_email(factory, user, from_email="organizer@example.com")
        stored_attachment(db, factory, user, email, (
            b"BEGIN:VCALENDAR\nVERSION:2.0\nMETHOD:REQUEST\n"
            b"BEGIN:VEVENT\nSUMMARY:Meeting\nDTSTART:20260315T140000Z\n"
            b"END:VEVENT\nEND:VCALENDAR"
        ), filename="invite.ics", mime_type="text/calendar")
        factory._insert("email_calendar_components", {
            "id": new_id(), "email_id": email, "user_id": user, "component_index": 0,
            "method": "REQUEST", "uid_hash": "uid-req"})
        integration = factory.integration(user)
        entry = factory._insert("calendar_entries", {
            "id": new_id(), "user_id": user, "integration_id": integration, "calendar_id": "primary",
            "provider_event_id": "g-2"})
        factory._insert("event_identity_hints", {
            "id": new_id(), "user_id": user, "calendar_entry_id": entry, "kind": "ical_uid",
            "value_hash": "uid-req", "strength": "authoritative"})

        result, extract = self._process(db, user, email)

        assert result["num_events"] == 0
        extract.assert_not_called()
        assert _statuses(db, email)[1] == "calendar_invite"

    def test_publish_ics_still_extracts_events(self, db, factory, user):
        """A plain 'add to calendar' .ics (METHOD:PUBLISH or no METHOD) is not an invite."""
        email = claimed_email(factory, user, from_email="organizer@example.com")
        start = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y%m%dT140000Z")
        stored_attachment(db, factory, user, email, (
            b"BEGIN:VCALENDAR\nVERSION:2.0\nMETHOD:PUBLISH\n"
            b"BEGIN:VEVENT\nSUMMARY:Community Fest\nDTSTART:" + start.encode() + b"\n"
            b"END:VEVENT\nEND:VCALENDAR"
        ), filename="event.ics", mime_type="text/calendar")

        result, extract = self._process(db, user, email)

        assert result["num_events"] == 1
        extract.assert_not_called()  # .ics parses directly, skipping the LLM
        assert _statuses(db, email) == ("processed", "event_created")
        assert [e["title"] for e in _events(db, user)] == ["Community Fest"]

    def test_no_events_short_circuits(self, db, user, email, spy_commit):
        result, _ = self._process(db, user, email, extraction=_make_extraction(events=[], events_found=False))

        assert result["num_events"] == 0
        assert spy_commit.decisions == []
        assert _statuses(db, email) == ("processed", "no_event")

    def test_matched_event_has_distinct_processing_outcome(self, db, factory, user, email):
        start = _future()
        existing = event_at(factory, user, start, review_status="active")
        with providers_offline(), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=_make_extraction(events=[_make_calendar_event(start_datetime=start)])), \
             patch("selko.services.events.event_processing.compare_events", return_value=existing), \
             patch("selko.services.events.event_processing.propose_event_update",
                   return_value=EventChangeSet(kind="noop", changes=[])):
            process_email_for_events(db, gateway(), email, user, email_row=email_row(db, email))

        assert _statuses(db, email) == ("processed", "event_matched")

    def test_exception_marks_failed(self, db, user, email):
        with providers_offline(), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   side_effect=RuntimeError("model unavailable")):
            with pytest.raises(EventsError, match="Failed to process email"):
                process_email_for_events(db, gateway(), email, user, email_row=email_row(db, email))

        row = email_row(db, email)
        assert (row["processing_status"], row["processing_error"]) == ("failed", "model unavailable")

    def test_ics_attachment_skips_llm(self, db, factory, user, email):
        """When email has .ics attachment, LLM extraction is skipped."""
        start = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y%m%dT14%M00Z")
        stored_attachment(db, factory, user, email, (
            b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nSUMMARY:ICS Event\n"
            b"DTSTART:" + start.encode() + b"\nDESCRIPTION:From .ics\nEND:VEVENT\nEND:VCALENDAR"
        ), filename="invite.ics", mime_type="text/calendar")

        result, extract = self._process(db, user, email)

        extract.assert_not_called()
        assert (result["num_events"], result["num_new"]) == (1, 1)

    def test_ics_parse_failure_falls_back_to_llm(self, db, factory, user, email):
        """When .ics parsing fails, falls back to LLM extraction."""
        stored_attachment(db, factory, user, email, b"not valid ics", filename="bad.ics",
                          mime_type="text/calendar")

        result, extract = self._process(db, user, email, extraction=_make_extraction(events=[_make_calendar_event()]))

        extract.assert_called_once()
        assert result["num_events"] == 1

    def test_attachment_bytes_reach_the_extraction(self, db, factory, user, email):
        """The stored file is what the model is shown."""
        stored_attachment(db, factory, user, email, b"\x89PNG-bytes", filename="flyer.png", mime_type="image/png")

        _, extract = self._process(db, user, email, extraction=_make_extraction(events=[], events_found=False))

        attachments = extract.call_args.args[3]
        assert attachments == [{"data": b"\x89PNG-bytes", "mime_type": "image/png", "filename": "flyer.png"}]


class TestAutoApproveSenderRule:
    """The auto_approve sender rule decides the review status of new events."""

    def _rule(self, factory, user, action):
        from selko.db.codec import new_id

        factory._insert("sender_rules", {"id": new_id(), "user_id": user,
                                         "sender_email": "sender@example.com", "action": action})

    def _process(self, db, user, email):
        with providers_offline(), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=_make_extraction(events=[_make_calendar_event()])):
            return process_email_for_events(db, gateway(), email, user, email_row=email_row(db, email))

    def test_process_email_auto_approve_creates_approved_events(self, db, factory, user, email):
        self._rule(factory, user, "auto_approve")
        result = self._process(db, user, email)

        assert result["auto_approved"] is True
        assert (result["num_events"], result["num_new"]) == (1, 1)
        (event,) = _events(db, user)
        assert event["review_status"] == "active"
        work = db.query("SELECT action FROM calendar_work_items WHERE event_id = ?", (event["id"],))
        assert [w["action"] for w in work] == ["upsert"], "an approved event is queued for the calendar"

    def test_process_email_no_rule_creates_pending_events(self, db, user, email):
        result = self._process(db, user, email)

        assert "auto_approved" not in result
        (event,) = _events(db, user)
        assert event["review_status"] == "pending_review"
        assert db.query("SELECT 1 FROM calendar_work_items") == []


class TestFetchBaselineInfoDate:
    """The update-proposal recency helper (WS4)."""

    def test_returns_newest_date_sent_across_sources(self, db, factory, user):
        event = factory.event(user)
        for sent in ("2026-03-10T09:00:00.000000Z", "2026-03-14T12:00:00.000000Z"):
            factory.event_source(event, factory.email(user, date_sent=sent))
        factory.event_source(event)  # a calendar source has no email date

        assert _fetch_baseline_info_date(db, event) == "2026-03-14T12:00:00.000000Z"

    def test_returns_none_when_no_sources(self, db, factory, user):
        assert _fetch_baseline_info_date(db, factory.event(user)) is None

    def test_returns_none_on_query_error(self, tmp_path):
        from selko.db.connection import Database

        broken = Database(tmp_path / "unmigrated.db")
        try:
            assert _fetch_baseline_info_date(broken, "00000000-0000-0000-0000-000000000001") is None
        finally:
            broken.close()
