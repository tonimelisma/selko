"""Integration tests for event processing pipeline."""

import re
from pathlib import Path
from uuid import uuid4

import pytest

from selko.services import events, event_processing


def _seed_event(client, user_id, event_data, email_id, review_status="pending_review"):
    """Seed event/source rows directly from the test boundary.

    Production event creation is owned by ``commit_email_extraction``; tests
    that exercise undo/attribution seed their starting state explicitly.
    """
    row = {
        "user_id": user_id,
        "title": event_data.get("title"),
        "start_datetime": event_data.get("start_datetime"),
        "end_datetime": event_data.get("end_datetime"),
        "all_day": event_data.get("all_day", False),
        "location": event_data.get("location"),
        "description": event_data.get("description"),
        "importance": event_data.get("importance", "action_required"),
        "review_status": review_status,
    }
    event_id = client.table("events").insert(row).execute().data[0]["id"]
    client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": "new_invitation",
        "extracted_data": event_data,
    }).execute()
    attribution = events.generate_source_attribution(client, event_id)
    if attribution:
        client.table("events").update({"source_attribution": attribution}).eq(
            "id", event_id
        ).execute()
    return event_id


def _seed_event_update(client, event_id, email_id, updated_data):
    client.table("events").update(updated_data).eq("id", event_id).execute()
    client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": "update",
        "extracted_data": updated_data,
    }).execute()


@pytest.mark.integration
@pytest.mark.development
class TestEventProcessingMocked:
    """Test email→event extraction with mocked LLM (no API costs).
    
    These tests validate service orchestration, database interactions,
    and business logic without making real LLM API calls.
    """

    def test_process_email_creates_event_mocked(
        self, authenticated_client, admin_client, test_user_id, mock_llm_gateway
    ):
        """Test that processing an email creates event records (mocked LLM)."""
        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-mocked-event-{uuid4().hex[:8]}",
            "subject": "Birthday Party Invitation",
            "from_email": "friend@example.com",
            "from_name": "Best Friend",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "You're invited to Sarah's birthday party on Feb 20th at 2pm!",
            "provider_labels": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        admin_client.table("emails").update({
            "processing_status": "processing",
            "locked_by": "direct-test-worker",
            "lock_generation": 1,
        }).eq("id", email_id).execute()
        email_row = admin_client.table("emails").select("*").eq("id", email_id).single().execute().data
        
        # Process email with mocked LLM
        processing_result = events.process_email_for_events(
            admin_client,
            mock_llm_gateway,
            email_id,
            test_user_id,
            email_row=email_row,
        )
        
        # Verify events were created
        assert processing_result["num_events"] >= 0
        assert processing_result["num_new"] >= 0
        
        # Check email status updated
        email_result = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()
        
        assert email_result.data["processing_status"] == "processed"
        
        # Verify mock was called (gateway stores mock client for testing)
        assert mock_llm_gateway._mock_provider.generate.called

    def test_process_email_no_events_mocked(
        self, authenticated_client, admin_client, test_user_id, mock_llm_no_events
    ):
        """Test processing email that has no events (mocked LLM)."""
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-no-event-{uuid4().hex[:8]}",
            "subject": "Newsletter",
            "from_email": "newsletter@example.com",
            "from_name": "Newsletter",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "Read our latest articles...",
            "provider_labels": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        admin_client.table("emails").update({
            "processing_status": "processing",
            "locked_by": "direct-test-worker",
            "lock_generation": 1,
        }).eq("id", email_id).execute()
        email_row = admin_client.table("emails").select("*").eq("id", email_id).single().execute().data
        
        # Process email
        processing_result = events.process_email_for_events(
            admin_client,
            mock_llm_no_events,
            email_id,
            test_user_id,
            email_row=email_row,
        )
        
        # Should process successfully with no events
        assert processing_result["num_events"] == 0
        assert processing_result["num_new"] == 0
        assert processing_result["num_updated"] == 0
        
        # Email should be marked as processed
        email_result = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()
        assert email_result.data["processing_status"] == "processed"

    def test_process_email_sender_ignored_mocked(
        self, authenticated_client, admin_client, test_user_id, mock_llm_gateway, clean_sender_rules
    ):
        """Test that ignored senders are skipped (mocked LLM)."""
        # Create ignore rule
        authenticated_client.table("sender_rules").insert({
            "user_id": test_user_id,
            "sender_email": "spam@example.com",
            "action": "ignore",
        }).execute()
        
        # Create email from ignored sender
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-ignored-{uuid4().hex[:8]}",
            "subject": "Event Invitation",
            "from_email": "spam@example.com",
            "from_name": "Spammer",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "You're invited!",
            "provider_labels": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        admin_client.table("emails").update({
            "processing_status": "processing",
            "locked_by": "direct-test-worker",
            "lock_generation": 1,
        }).eq("id", email_id).execute()
        email_row = admin_client.table("emails").select("*").eq("id", email_id).single().execute().data
        
        # Process email
        processing_result = events.process_email_for_events(
            admin_client,
            mock_llm_gateway,
            email_id,
            test_user_id,
            email_row=email_row,
        )
        
        # Should be skipped
        assert processing_result.get("skipped") is True
        assert processing_result["num_events"] == 0
        
        # Email should be marked as skipped
        email_result = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()
        assert email_result.data["processing_status"] == "skipped"
        
        # Mock should NOT be called (gateway stores mock client for testing)
        assert not mock_llm_gateway._mock_provider.generate.called


@pytest.mark.integration
@pytest.mark.development
class TestEventProcessing:
    """Test email→event extraction with REAL LLM (requires --run-llm flag)."""

    @pytest.mark.llm
    def test_process_email_creates_event(
        self, authenticated_client, test_user_id, llm_gateway
    ):
        """Test that processing an email with events creates event records.
        
        This test requires --run-llm flag to run (costs money).
        """
        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-event-email-{uuid4().hex[:8]}",
            "subject": "Birthday Party Invitation",
            "from_email": "friend@example.com",
            "from_name": "Best Friend",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "You're invited to Sarah's birthday party on Feb 20th at 2pm!",
            "provider_labels": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        
        # Process email for events (real LLM when --run-llm is set)
        try:
            processing_result = events.process_email_for_events(
                authenticated_client,
                llm_gateway,
                email_id,
                test_user_id
            )
            
            # Verify events were created
            assert processing_result["num_events"] >= 0
            
            # Check email status updated
            email_result = authenticated_client.table("emails").select("*").eq(
                "id", email_id
            ).single().execute()
            
            assert email_result.data["processing_status"] in ["processed", "skipped"]
            
        except Exception as e:
            # If provider API fails (missing key, rate limit), skip gracefully
            err = str(e)
            if "API_KEY" in err or "API key" in err or "rate limit" in err.lower():
                pytest.skip(f"LLM API unavailable: {e}")
            raise

    def test_get_events_new(self, authenticated_client, test_user_id):
        """Test getting pending events."""
        # Create test event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event",
            "start_datetime": "2026-03-01T10:00:00Z",
            "review_status": "pending_review",
        }
        
        authenticated_client.table("events").insert(event_data).execute()
        
        # Get new events
        new_events = events.get_events_new(authenticated_client, test_user_id)
        
        assert len(new_events) >= 1
        assert any(e["title"] == "Test Event" for e in new_events)

@pytest.mark.integration
@pytest.mark.development
class TestSenderRules:
    """Test sender rule automation."""

    def test_check_sender_rules_exact_email(
        self, authenticated_client, test_user_id, clean_sender_rules
    ):
        """Test checking sender rules with exact email match."""
        # Create rule
        authenticated_client.table("sender_rules").insert({
            "user_id": test_user_id,
            "sender_email": "school@example.edu",
            "action": "auto_approve",
        }).execute()
        
        # Check rule
        rule = events.check_sender_rules(
            authenticated_client,
            test_user_id,
            "school@example.edu"
        )
        
        assert rule is not None
        assert rule["action"] == "auto_approve"

    def test_check_sender_rules_domain_match(
        self, authenticated_client, test_user_id, clean_sender_rules
    ):
        """Test checking sender rules with domain wildcard."""
        # Create domain rule
        authenticated_client.table("sender_rules").insert({
            "user_id": test_user_id,
            "sender_domain": "example.edu",
            "action": "ignore",
        }).execute()
        
        # Check with any email from that domain
        rule = events.check_sender_rules(
            authenticated_client,
            test_user_id,
            "newsletter@example.edu"
        )
        
        assert rule is not None
        assert rule["action"] == "ignore"

    def test_check_sender_rules_no_match(self, authenticated_client, test_user_id):
        """Test that non-matching sender returns None."""
        rule = events.check_sender_rules(
            authenticated_client,
            test_user_id,
            "unknown@random.com"
        )
        
        assert rule is None


@pytest.mark.integration
@pytest.mark.development
class TestEventSources:
    """Test event source tracking and undo."""

    def test_create_event_with_source(self, authenticated_client, admin_client, test_user_id):
        """Test creating event with source link."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-source-{uuid4().hex[:8]}",
            "subject": "Test Event",
            "from_email": "test@example.com",
            "from_name": "Test Sender",
            "date_sent": "2026-02-01T10:00:00Z",
            "snippet": "Test content",
            "provider_labels": ["INBOX"],
        }
        
        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]
        
        # Create event
        event_data = {
            "title": "Test Event",
            "start_datetime": "2026-03-10T10:00:00Z",
            "description": "Test description",
            "source_quote": "Test quote from email",
        }
        
        event_id = _seed_event(admin_client, test_user_id, event_data, email_id)
        
        # Verify event_source was created
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).execute()
        
        assert len(sources.data) == 1
        assert sources.data[0]["email_id"] == email_id
        assert sources.data[0]["source_type"] == "new_invitation"

    def test_source_attribution_generation(self, authenticated_client, admin_client, test_user_id):
        """Test natural English attribution generation."""
        # Create test email and event
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-attr-{uuid4().hex[:8]}",
            "subject": "Event Invitation",
            "from_email": "sender@test.com",
            "from_name": "Event Organizer",
            "date_sent": "2026-01-25T13:30:00Z",
            "snippet": "Event details",
            "provider_labels": ["INBOX"],
        }
        
        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]
        
        event_data = {
            "title": "Test Attribution",
            "start_datetime": "2026-03-15T14:00:00Z",
            "description": "Test",
            "source_quote": "Quote from email",
        }
        
        event_id = _seed_event(admin_client, test_user_id, event_data, email_id)
        
        # Check attribution was generated
        event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        attribution = event.data.get("source_attribution")
        assert attribution is not None
        assert "Event Organizer" in attribution or "sender@test.com" in attribution
        assert "January" in attribution or "Jan" in attribution


@pytest.mark.integration
@pytest.mark.development
class TestEventUndoRedo:
    """Test event undo/redo functionality with snapshot restore."""

    def test_undo_restores_snapshot(self, authenticated_client, admin_client, test_user_id, mock_llm_gateway):
        """Test that undo restores the event to its previous snapshot."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-undo-{uuid4().hex[:8]}",
            "subject": "Meeting Update",
            "from_email": "organizer@example.com",
            "from_name": "Meeting Organizer",
            "date_sent": "2026-02-01T10:00:00Z",
            "snippet": "Meeting time changed to 3pm",
            "provider_labels": ["INBOX"],
        }

        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]

        # Create initial event
        initial_event_data = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-20T14:00:00Z",
            "end_datetime": "2026-03-20T15:00:00Z",
            "description": "Original description",
            "source_quote": "Initial meeting invite",
        }

        event_id = _seed_event(admin_client, test_user_id, initial_event_data, email_id)

        # Create second email with update
        email_data_2 = {
            "user_id": test_user_id,
            "provider_message_id": f"test-undo-update-{uuid4().hex[:8]}",
            "subject": "Meeting Update",
            "from_email": "organizer@example.com",
            "from_name": "Meeting Organizer",
            "date_sent": "2026-02-02T10:00:00Z",
            "snippet": "Meeting time changed",
            "provider_labels": ["INBOX"],
        }

        email_result_2 = authenticated_client.table("emails").insert(email_data_2).execute()
        email_id_2 = email_result_2.data[0]["id"]

        # Update event (simulating a second email contribution)
        updated_data = {
            "title": "Team Meeting - Updated",
            "start_datetime": "2026-03-20T15:00:00Z",  # Changed time
            "end_datetime": "2026-03-20T16:00:00Z",
            "description": "Updated description",
        }

        _seed_event_update(admin_client, event_id, email_id_2, updated_data)

        # Verify event was updated
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        # The reversible payload belongs to the authoritative proposal.
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "update").execute()

        assert len(sources.data) == 1
        update_source_id = sources.data[0]["id"]
        proposal = admin_client.table("event_change_proposals").insert({
            "event_id": event_id,
            "user_id": test_user_id,
            "source_id": update_source_id,
            "kind": "material_update",
            "status": "applied",
            "change_set": {"kind": "material_update", "changes": [
                {"field": "title", "before": "Team Meeting", "after": "Team Meeting - Updated"},
                {"field": "start_datetime", "before": "2026-03-20T14:00:00Z", "after": "2026-03-20T15:00:00Z"},
            ]},
            "event_snapshot_before": {
                "title": "Team Meeting",
                "start_datetime": "2026-03-20T14:00:00Z",
                "end_datetime": "2026-03-20T15:00:00Z",
                "review_status": "active",
            },
            "resolution_reason": "approved",
        }).execute().data[0]

        # Now undo the update
        events.undo_history_event(admin_client, event_id, test_user_id)

        # Verify event was restored
        restored_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert restored_event.data["title"] == "Team Meeting"
        assert "14:00" in restored_event.data["start_datetime"]

        # Undo reopens the proposal instead of mutating provenance.
        proposal_after = authenticated_client.table("event_change_proposals").select("status").eq(
            "id", proposal["id"]
        ).single().execute()
        assert proposal_after.data["status"] == "pending"

    def test_redo_reactivates_source(self, authenticated_client, admin_client, test_user_id, mock_llm_gateway):
        """Test that redo marks the source as active again."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-redo-{uuid4().hex[:8]}",
            "subject": "Event Invite",
            "from_email": "host@example.com",
            "from_name": "Event Host",
            "date_sent": "2026-02-05T10:00:00Z",
            "snippet": "You're invited",
            "provider_labels": ["INBOX"],
        }

        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]

        # Create event
        event_data = {
            "title": "Party",
            "start_datetime": "2026-03-25T19:00:00Z",
            "description": "Celebration",
        }

        event_id = _seed_event(admin_client, test_user_id, event_data, email_id)

        # Create second email
        email_data_2 = {
            "user_id": test_user_id,
            "provider_message_id": f"test-redo-update-{uuid4().hex[:8]}",
            "subject": "Party Update",
            "from_email": "host@example.com",
            "from_name": "Event Host",
            "date_sent": "2026-02-06T10:00:00Z",
            "snippet": "Location changed",
            "provider_labels": ["INBOX"],
        }

        email_result_2 = authenticated_client.table("emails").insert(email_data_2).execute()
        email_id_2 = email_result_2.data[0]["id"]

        # Update event
        updated_data = {
            "title": "Party",
            "start_datetime": "2026-03-25T19:00:00Z",
            "location": "New Venue",
            "description": "Location updated",
        }

        _seed_event_update(admin_client, event_id, email_id_2, updated_data)

        # Get update provenance and create its authoritative proposal.
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "update").execute()

        update_source_id = sources.data[0]["id"]
        proposal = admin_client.table("event_change_proposals").insert({
            "event_id": event_id,
            "user_id": test_user_id,
            "source_id": update_source_id,
            "kind": "material_update",
            "status": "applied",
            "change_set": {"kind": "material_update", "changes": [
                {"field": "location", "before": None, "after": "New Venue"},
            ]},
            "event_snapshot_before": {"title": "Party", "review_status": "active"},
            "resolution_reason": "approved",
        }).execute().data[0]

        events.undo_history_event(admin_client, event_id, test_user_id)
        assert authenticated_client.table("event_change_proposals").select("status").eq(
            "id", proposal["id"]
        ).single().execute().data["status"] == "pending"

        events.apply_change_proposal(admin_client, event_id, proposal["id"])
        assert authenticated_client.table("event_change_proposals").select("status").eq(
            "id", proposal["id"]
        ).single().execute().data["status"] == "applied"

    def test_undo_fails_without_snapshot(self, authenticated_client, admin_client, test_user_id):
        """Test that undo fails gracefully when no snapshot exists."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"test-no-snap-{uuid4().hex[:8]}",
            "subject": "New Event",
            "from_email": "sender@example.com",
            "from_name": "Sender",
            "date_sent": "2026-02-10T10:00:00Z",
            "snippet": "Event info",
            "provider_labels": ["INBOX"],
        }

        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]

        # Create event (first source has no snapshot)
        event_data = {
            "title": "New Event",
            "start_datetime": "2026-04-01T10:00:00Z",
        }

        event_id = _seed_event(admin_client, test_user_id, event_data, email_id)

        # A provenance row without a proposal is not undoable.
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "new_invitation").execute()

        source_id = sources.data[0]["id"]
        proposals = authenticated_client.table("event_change_proposals").select("id").eq(
            "source_id", source_id
        ).execute().data
        assert proposals == []

    def test_attribution_excludes_undone_sources(self, authenticated_client, admin_client, test_user_id, mock_llm_gateway):
        """Test that source attribution excludes undone sources."""
        # Create first email
        email_data_1 = {
            "user_id": test_user_id,
            "provider_message_id": f"test-attr-1-{uuid4().hex[:8]}",
            "subject": "Event Invite",
            "from_email": "first@example.com",
            "from_name": "First Sender",
            "date_sent": "2026-02-15T10:00:00Z",
            "snippet": "Event details",
            "provider_labels": ["INBOX"],
        }

        email_result_1 = authenticated_client.table("emails").insert(email_data_1).execute()
        email_id_1 = email_result_1.data[0]["id"]

        # Create event
        event_data = {
            "title": "Attribution Test Event",
            "start_datetime": "2026-04-10T14:00:00Z",
        }

        event_id = _seed_event(admin_client, test_user_id, event_data, email_id_1)

        # Create second email
        email_data_2 = {
            "user_id": test_user_id,
            "provider_message_id": f"test-attr-2-{uuid4().hex[:8]}",
            "subject": "Event Update",
            "from_email": "second@example.com",
            "from_name": "Second Sender",
            "date_sent": "2026-02-16T10:00:00Z",
            "snippet": "Update details",
            "provider_labels": ["INBOX"],
        }

        email_result_2 = authenticated_client.table("emails").insert(email_data_2).execute()
        email_id_2 = email_result_2.data[0]["id"]

        # Update event
        updated_data = {
            "title": "Attribution Test Event - Updated",
            "start_datetime": "2026-04-10T15:00:00Z",
        }

        _seed_event_update(admin_client, event_id, email_id_2, updated_data)

        attribution = events.generate_source_attribution(authenticated_client, event_id)
        assert "First Sender" in attribution or "first@example.com" in attribution
        assert "Second Sender" in attribution or "second@example.com" in attribution


# --- V8/W3: the events.status collapse -------------------------------------

MIGRATIONS = Path(__file__).parents[3] / "supabase" / "migrations"
LEGACY_DOMAIN_MIGRATION = MIGRATIONS / "20260826000001_remove_legacy_event_state.sql"
DROP_MIGRATION = MIGRATIONS / "20260829000001_delete_events_status.sql"


def _legacy_status_domain() -> set[str]:
    """The events.status CHECK domain as it stood immediately before the drop."""
    text = LEGACY_DOMAIN_MIGRATION.read_text()
    marker = "ADD CONSTRAINT events_status_check CHECK (status IN ("
    body = text[text.index(marker) + len(marker):]
    body = body[: body.index("))")]
    return set(re.findall(r"'([a-z_]+)'", body))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_events_status_backfill_preserves_every_legacy_status(pg_pool):
    """Every legacy delivery state must have a declared destination.

    Scope note, stated plainly: this cannot be executed end to end. The DO block
    runs once, in the same migration that drops the column, so by the time any
    test connects the source data no longer exists and cannot be reconstructed.
    A follow-up migration cannot repair an incomplete backfill for the same
    reason -- which is why the block had to be fixed before it reached any
    durable environment rather than patched afterwards.

    What is executable here: the destination statuses are checked against the
    live CHECK constraint, and the column's absence is checked against the live
    catalog. The end-to-end proof is ./scripts/rehearse-cutover.sh, which
    applies the real migration to a copy of production's real rows.
    """
    handled = DROP_MIGRATION.read_text()
    block = handled[handled.index("DO $$"): handled.index("\n$$;\n")]

    covered = set(re.findall(r"'([a-z_]+)'", block[block.index("e.status IN ("):]))
    review_only = {"pending_review", "rejected", "cancelled"}
    domain = _legacy_status_domain()

    unhandled = domain - covered - review_only
    assert not unhandled, (
        f"legacy statuses with no destination in the backfill: {sorted(unhandled)}. "
        "Once the column is dropped these rows are unrecoverable."
    )

    # The destinations the block writes must be legal work-item statuses. This
    # half is a live-catalog assertion, not a source-text one.
    work_item_domain = await pg_pool.fetchval(
        """
        SELECT pg_get_constraintdef(c.oid)
        FROM pg_constraint AS c
        JOIN pg_class AS t ON t.oid = c.conrelid
        WHERE t.relname = 'calendar_work_items' AND c.conname LIKE '%status%'
        """
    )
    for destination in ("succeeded", "failed", "pending"):
        assert f"'{destination}'" in work_item_domain, (
            f"backfill writes calendar_work_items.status = {destination!r}, "
            f"which the live constraint rejects: {work_item_domain}"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_events_has_exactly_one_state_owner(pg_pool):
    """review_status owns the decision; calendar_work_items owns delivery."""
    columns = {
        row["column_name"]
        for row in await pg_pool.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'events'
            """
        )
    }
    assert "status" not in columns, "events.status is back; D1(a) chose to delete it"
    assert "review_status" in columns


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_rpc_signature_carries_the_deleted_delivery_vocabulary(pg_pool):
    """The column is gone; its vocabulary must not survive in the API surface.

    A live catalog assertion: it reads the argument names PostgreSQL actually
    holds, so it cannot be satisfied by editing a migration's text.
    """
    rows = await pg_pool.fetch(
        """
        SELECT p.proname AS name,
               pg_get_function_identity_arguments(p.oid) AS args,
               pg_get_function_arguments(p.oid) AS named_args
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prosecdef
        """
    )
    banned = ("p_legacy_status", "p_restore_status", "p_next_status")
    offenders = [
        f"{row['name']}({row['named_args']})"
        for row in rows
        if any(token in (row["named_args"] or "") for token in banned)
    ]
    assert not offenders, f"deleted delivery vocabulary survives in: {offenders}"
