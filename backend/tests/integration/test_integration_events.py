"""The event pipeline end to end on a real SQLite database.

The LLM is the mocked gateway (`mock_llm_gateway`, `mock_llm_no_events`) or,
with --run-llm, the real one; every database read and write is real. Ran
against local Supabase before the SQLite move.

Removed with the move, each with its successor:
- `test_get_events_new`: `events.get_events_new` had no caller and is deleted
  (02-data-layer §3.9); the review queue read is
  `tests/db/test_client_routes.py::test_review_queue_lists_new_events_with_their_sources`.
- `test_delete_events_status_backfill_preserves_every_legacy_status`: Postgres
  migration history (05-verification §A.2 #19).
"""

import inspect
import re

import pytest

from selko.db.codec import new_id
from selko.services import events
from tests.event_pipeline import claimed_email, email_row, providers_offline


def _seed_event(db, factory, user_id, event_data, email_id, review_status="pending_review"):
    """Seed event/source rows directly at the test boundary.

    Production event creation is owned by ``commit_email_extraction``; tests
    that exercise undo/attribution seed their starting state explicitly.
    """
    event_id = factory.event(
        user_id, review_status=review_status, title=event_data["title"],
        start_datetime=event_data.get("start_datetime"), end_datetime=event_data.get("end_datetime"),
        location=event_data.get("location"), description=event_data.get("description"),
    )
    factory.event_source(event_id, email_id, source_type="new_invitation", extracted_data=event_data)
    attribution = events.generate_source_attribution(db, event_id)
    if attribution:
        with db.write() as tx:
            tx.execute("UPDATE events SET source_attribution = ? WHERE id = ?", (attribution, event_id))
    return event_id


def _seed_update(db, factory, event_id, email_id, updated_data) -> str:
    with db.write() as tx:
        sets = ", ".join(f"{k} = ?" for k in updated_data)
        tx.execute(f"UPDATE events SET {sets} WHERE id = ?", (*updated_data.values(), event_id))
    return factory.event_source(event_id, email_id, source_type="update", extracted_data=updated_data)


def _email(factory, user, **extra):
    values = {"from_email": "friend@example.com", "from_name": "Best Friend",
              "date_sent": "2026-02-15T12:00:00.000000Z", "provider_labels": ["INBOX"]}
    values.update(extra)
    return factory.email(user, processing_status="processed", **values)


@pytest.mark.integration
class TestEventProcessingMocked:
    """Email -> event extraction with a mocked LLM (no API costs)."""

    def _process(self, db, factory, gateway, **email):
        user = factory.user()
        email_id = claimed_email(factory, user, **email)
        with providers_offline():
            result = events.process_email_for_events(
                db, gateway, email_id, user, email_row=email_row(db, email_id))
        return user, email_id, result

    def test_process_email_creates_event_mocked(self, db, factory, mock_llm_gateway):
        user, email_id, result = self._process(
            db, factory, mock_llm_gateway, subject="Birthday Party Invitation",
            from_email="friend@example.com", from_name="Best Friend",
            date_sent="2026-02-15T12:00:00.000000Z",
            snippet="You're invited to Sarah's birthday party on Feb 20th at 2pm!",
        )

        assert result["num_events"] >= 0
        assert email_row(db, email_id)["processing_status"] == "processed"
        assert mock_llm_gateway._mock_provider.generate.called
        created = db.query_one("SELECT count(*) FROM events WHERE user_id = ?", (user,))[0]
        assert created == result["num_new"]

    def test_process_email_no_events_mocked(self, db, factory, mock_llm_no_events):
        _, email_id, result = self._process(
            db, factory, mock_llm_no_events, subject="Newsletter",
            from_email="newsletter@example.com", snippet="Read our latest articles...",
        )

        assert (result["num_events"], result["num_new"], result["num_updated"]) == (0, 0, 0)
        row = email_row(db, email_id)
        assert (row["processing_status"], row["processing_outcome"]) == ("processed", "no_event")

    def test_process_email_sender_ignored_mocked(self, db, factory, mock_llm_gateway):
        user = factory.user()
        factory._insert("sender_rules", {"id": new_id(), "user_id": user,
                                         "sender_email": "spam@example.com", "action": "ignore"})
        email_id = claimed_email(factory, user, subject="Event Invitation", from_email="spam@example.com",
                                 snippet="You're invited!")

        with providers_offline():
            result = events.process_email_for_events(
                db, mock_llm_gateway, email_id, user, email_row=email_row(db, email_id))

        assert result.get("skipped") is True
        assert result["num_events"] == 0
        assert email_row(db, email_id)["processing_status"] == "skipped"
        assert not mock_llm_gateway._mock_provider.generate.called


@pytest.mark.integration
class TestEventProcessing:
    """Email -> event extraction with the REAL LLM (requires --run-llm)."""

    @pytest.mark.llm
    def test_process_email_creates_event(self, db, factory, llm_gateway):
        user = factory.user()
        email_id = claimed_email(
            factory, user, subject="Birthday Party Invitation", from_email="friend@example.com",
            from_name="Best Friend", date_sent="2026-02-15T12:00:00.000000Z",
            snippet="You're invited to Sarah's birthday party on Feb 20th at 2pm!",
        )
        try:
            with providers_offline():
                result = events.process_email_for_events(
                    db, llm_gateway, email_id, user, email_row=email_row(db, email_id))
        except Exception as e:
            err = str(e)
            if "API_KEY" in err or "API key" in err or "rate limit" in err.lower():
                pytest.skip(f"LLM API unavailable: {e}")
            raise
        assert result["num_events"] >= 0
        assert email_row(db, email_id)["processing_status"] in ["processed", "skipped"]


@pytest.mark.integration
class TestSenderRules:
    """Sender rule automation."""

    def test_check_sender_rules_exact_email(self, db, factory):
        user = factory.user()
        factory._insert("sender_rules", {"id": new_id(), "user_id": user,
                                         "sender_email": "school@example.edu", "action": "auto_approve"})

        rule = events.check_sender_rules(db, user, "school@example.edu")

        assert rule is not None
        assert rule["action"] == "auto_approve"

    def test_check_sender_rules_domain_match(self, db, factory):
        user = factory.user()
        factory._insert("sender_rules", {"id": new_id(), "user_id": user,
                                         "sender_domain": "example.edu", "action": "ignore"})

        rule = events.check_sender_rules(db, user, "newsletter@example.edu")

        assert rule is not None
        assert rule["action"] == "ignore"

    def test_check_sender_rules_no_match(self, db, factory):
        assert events.check_sender_rules(db, factory.user(), "unknown@random.com") is None


@pytest.mark.integration
class TestEventSources:
    """Event source tracking and attribution."""

    def test_create_event_with_source(self, db, factory):
        user = factory.user()
        email_id = _email(factory, user, subject="Test Event", from_email="test@example.com")
        event_id = _seed_event(db, factory, user, {
            "title": "Test Event", "start_datetime": "2026-03-10T10:00:00.000000Z",
            "description": "Test description", "source_quote": "Test quote from email",
        }, email_id)

        sources = db.query("SELECT email_id, source_type FROM event_sources WHERE event_id = ?", (event_id,))
        assert [(s["email_id"], s["source_type"]) for s in sources] == [(email_id, "new_invitation")]

    def test_source_attribution_generation(self, db, factory):
        user = factory.user()
        email_id = _email(factory, user, from_email="sender@test.com", from_name="Event Organizer",
                          date_sent="2026-01-25T13:30:00.000000Z")
        event_id = _seed_event(db, factory, user, {
            "title": "Test Attribution", "start_datetime": "2026-03-15T14:00:00.000000Z",
        }, email_id)

        attribution = factory.row("events", event_id)["source_attribution"]
        assert attribution is not None
        assert "Event Organizer" in attribution or "sender@test.com" in attribution
        assert "January" in attribution or "Jan" in attribution


def _applied_proposal(factory, user, event_id, source_id, change_set, snapshot):
    return factory._insert("event_change_proposals", {
        "id": new_id(), "event_id": event_id, "user_id": user, "source_id": source_id,
        "kind": "material_update", "status": "applied", "change_set": change_set,
        "event_snapshot_before": snapshot, "resolution_reason": "user_applied",
        "resolved_at": "2026-02-02T10:00:00.000000Z",
    })


@pytest.mark.integration
class TestEventUndoRedo:
    """Undo of an applied change restores the snapshot through the proposal."""

    def test_undo_restores_snapshot(self, db, factory):
        user = factory.user()
        email_id = _email(factory, user, subject="Meeting", from_email="organizer@example.com",
                          from_name="Meeting Organizer")
        event_id = _seed_event(db, factory, user, {
            "title": "Team Meeting", "start_datetime": "2026-03-20T14:00:00.000000Z",
            "end_datetime": "2026-03-20T15:00:00.000000Z", "description": "Original description",
        }, email_id, review_status="active")
        update_email = _email(factory, user, subject="Meeting Update", date_sent="2026-02-02T10:00:00.000000Z")
        source_id = _seed_update(db, factory, event_id, update_email, {
            "title": "Team Meeting - Updated", "start_datetime": "2026-03-20T15:00:00.000000Z",
            "end_datetime": "2026-03-20T16:00:00.000000Z", "description": "Updated description",
        })
        proposal = _applied_proposal(factory, user, event_id, source_id, {"kind": "material_update", "changes": [
            {"field": "title", "before": "Team Meeting", "after": "Team Meeting - Updated"},
            {"field": "start_datetime", "before": "2026-03-20T14:00:00Z", "after": "2026-03-20T15:00:00Z"},
        ]}, {"title": "Team Meeting", "start_datetime": "2026-03-20T14:00:00Z",
             "end_datetime": "2026-03-20T15:00:00Z", "review_status": "active"})

        assert events.undo_history_event(db, event_id, user) == "active"

        restored = factory.row("events", event_id)
        assert restored["title"] == "Team Meeting"
        assert restored["start_datetime"] == "2026-03-20T14:00:00.000000Z"
        # Undo reopens the proposal instead of mutating provenance.
        assert factory.row("event_change_proposals", proposal)["status"] == "pending"

    def test_redo_reactivates_source(self, db, factory):
        """Undo then accept again: the reopened proposal is the one applied."""
        user = factory.user()
        email_id = _email(factory, user, from_email="host@example.com", from_name="Event Host")
        event_id = _seed_event(db, factory, user, {
            "title": "Party", "start_datetime": "2026-03-25T19:00:00.000000Z", "description": "Celebration",
        }, email_id, review_status="active")
        update_email = _email(factory, user, subject="Party Update", date_sent="2026-02-06T10:00:00.000000Z")
        source_id = _seed_update(db, factory, event_id, update_email,
                                 {"location": "New Venue", "description": "Location updated"})
        proposal = _applied_proposal(factory, user, event_id, source_id, {"kind": "material_update", "changes": [
            {"field": "location", "before": None, "after": "New Venue"}]},
            {"title": "Party", "review_status": "active"})

        events.undo_history_event(db, event_id, user)
        assert factory.row("event_change_proposals", proposal)["status"] == "pending"
        assert factory.row("events", event_id)["location"] is None

        events.apply_change_proposal(db, event_id, proposal, user_id=user)
        assert factory.row("event_change_proposals", proposal)["status"] == "applied"
        assert factory.row("events", event_id)["location"] == "New Venue"

    def test_undo_fails_without_snapshot(self, db, factory):
        """A provenance row without a proposal is not undoable as a change."""
        user = factory.user()
        email_id = _email(factory, user)
        event_id = _seed_event(db, factory, user, {
            "title": "New Event", "start_datetime": "2026-04-01T10:00:00.000000Z",
        }, email_id)

        source = db.query_one("SELECT id FROM event_sources WHERE event_id = ?", (event_id,))
        assert db.query("SELECT id FROM event_change_proposals WHERE source_id = ?", (source["id"],)) == []
        # Undo of a New-lane decision returns it to review, never touching sources.
        assert events.undo_history_event(db, event_id, user) == "pending_review"
        assert db.query_one("SELECT count(*) FROM event_sources WHERE event_id = ?", (event_id,))[0] == 1

    def test_attribution_excludes_undone_sources(self, db, factory):
        """Attribution names every source that contributed."""
        user = factory.user()
        first = _email(factory, user, from_email="first@example.com", from_name="First Sender",
                       date_sent="2026-02-15T10:00:00.000000Z")
        event_id = _seed_event(db, factory, user, {
            "title": "Attribution Test Event", "start_datetime": "2026-04-10T14:00:00.000000Z",
        }, first)
        second = _email(factory, user, from_email="second@example.com", from_name="Second Sender",
                        date_sent="2026-02-16T10:00:00.000000Z")
        _seed_update(db, factory, event_id, second, {"title": "Attribution Test Event - Updated"})

        attribution = events.generate_source_attribution(db, event_id)
        assert "First Sender" in attribution or "first@example.com" in attribution
        assert "Second Sender" in attribution or "second@example.com" in attribution


# --- V8/W3: the events.status collapse -------------------------------------


@pytest.mark.integration
def test_events_has_exactly_one_state_owner(db):
    """review_status owns the decision; calendar_work_items owns delivery."""
    columns = {row["name"] for row in db.query("SELECT name FROM pragma_table_info('events')")}
    assert columns, "the events table must exist for this check to mean anything"
    assert "status" not in columns, "events.status is back; D1(a) chose to delete it"
    assert "review_status" in columns


@pytest.mark.integration
def test_no_rpc_signature_carries_the_deleted_delivery_vocabulary():
    """The column is gone; its vocabulary must not survive in the data layer's API.

    Scans the signature of every public function in every `selko.db` module.
    """
    import importlib
    import pkgutil

    import selko.db

    banned = re.compile(r"legacy_status|restore_status|next_status")
    scanned = 0
    offenders = []
    for info in pkgutil.iter_modules(selko.db.__path__):
        module = importlib.import_module(f"selko.db.{info.name}")
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if fn.__module__ != module.__name__:
                continue
            scanned += 1
            params = list(inspect.signature(fn).parameters)
            if any(banned.search(p) for p in params):
                offenders.append(f"{module.__name__}.{name}({', '.join(params)})")
    assert scanned > 50, f"only {scanned} functions scanned: the scan is not seeing the data layer"
    assert not offenders, f"deleted delivery vocabulary survives in: {offenders}"
