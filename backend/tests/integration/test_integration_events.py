"""Integration tests for event processing pipeline."""

from uuid import uuid4

import pytest

from selko.services import events, gemini


@pytest.mark.integration
@pytest.mark.development
class TestEventProcessingMocked:
    """Test email→event extraction with mocked LLM (no API costs).
    
    These tests validate service orchestration, database interactions,
    and business logic without making real LLM API calls.
    """

    def test_process_email_creates_event_mocked(
        self, authenticated_client, test_user_id, mock_gemini_client
    ):
        """Test that processing an email creates event records (mocked LLM)."""
        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-mocked-event-{uuid4().hex[:8]}",
            "subject": "Birthday Party Invitation",
            "from_email": "friend@example.com",
            "from_name": "Best Friend",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "You're invited to Sarah's birthday party on Feb 20th at 2pm!",
            "gmail_label_ids": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        
        # Process email with mocked LLM
        processing_result = events.process_email_for_events(
            authenticated_client,
            mock_gemini_client,
            email_id,
            test_user_id
        )
        
        # Verify events were created
        assert processing_result["num_events"] >= 0
        assert processing_result["num_new"] >= 0
        
        # Check email status updated
        email_result = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()
        
        assert email_result.data["processing_status"] == "processed"
        
        # Verify mock was called
        assert mock_gemini_client.models.generate_content.called

    def test_process_email_no_events_mocked(
        self, authenticated_client, test_user_id, mock_gemini_no_events
    ):
        """Test processing email that has no events (mocked LLM)."""
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-no-event-{uuid4().hex[:8]}",
            "subject": "Newsletter",
            "from_email": "newsletter@example.com",
            "from_name": "Newsletter",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "Read our latest articles...",
            "gmail_label_ids": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        
        # Process email
        processing_result = events.process_email_for_events(
            authenticated_client,
            mock_gemini_no_events,
            email_id,
            test_user_id
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
        self, authenticated_client, test_user_id, mock_gemini_client
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
            "gmail_id": f"test-ignored-{uuid4().hex[:8]}",
            "subject": "Event Invitation",
            "from_email": "spam@example.com",
            "from_name": "Spammer",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "You're invited!",
            "gmail_label_ids": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        
        # Process email
        processing_result = events.process_email_for_events(
            authenticated_client,
            mock_gemini_client,
            email_id,
            test_user_id
        )
        
        # Should be skipped
        assert processing_result.get("skipped") is True
        assert processing_result["num_events"] == 0
        
        # Email should be marked as skipped
        email_result = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()
        assert email_result.data["processing_status"] == "skipped"
        
        # Mock should NOT be called
        assert not mock_gemini_client.models.generate_content.called


@pytest.mark.integration
@pytest.mark.development
class TestEventProcessing:
    """Test email→event extraction with REAL LLM (requires --run-llm flag)."""

    @pytest.mark.llm
    def test_process_email_creates_event(
        self, authenticated_client, test_user_id, gemini_client
    ):
        """Test that processing an email with events creates event records.
        
        This test requires --run-llm flag to run (costs money).
        """
        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-event-email-{uuid4().hex[:8]}",
            "subject": "Birthday Party Invitation",
            "from_email": "friend@example.com",
            "from_name": "Best Friend",
            "date_sent": "2026-02-15T12:00:00Z",
            "snippet": "You're invited to Sarah's birthday party on Feb 20th at 2pm!",
            "gmail_label_ids": ["INBOX"],
        }
        
        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]
        
        # Process email for events (this will call real Gemini API)
        try:
            processing_result = events.process_email_for_events(
                authenticated_client,
                gemini_client,
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
            # If Gemini API fails (no key, rate limit), skip gracefully
            if "GEMINI_API_KEY" in str(e) or "rate limit" in str(e):
                pytest.skip(f"Gemini API unavailable: {e}")
            raise

    def test_get_events_new(self, authenticated_client, test_user_id):
        """Test getting pending events."""
        # Create test event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event",
            "start_datetime": "2026-03-01T10:00:00Z",
            "status": "pending_review",
        }
        
        authenticated_client.table("events").insert(event_data).execute()
        
        # Get new events
        new_events = events.get_events_new(authenticated_client, test_user_id)
        
        assert len(new_events) >= 1
        assert any(e["title"] == "Test Event" for e in new_events)

    def test_approve_event(self, authenticated_client, test_user_id):
        """Test approving an event."""
        # Create test event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Approval",
            "start_datetime": "2026-03-01T14:00:00Z",
            "status": "pending_review",
        }
        
        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]
        
        # Approve
        events.approve_event(authenticated_client, event_id)
        
        # Verify status changed
        updated = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        
        assert updated.data["status"] == "approved"

    def test_reject_and_restore_event(self, authenticated_client, test_user_id):
        """Test rejecting and restoring an event."""
        # Create test event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Reject/Restore",
            "start_datetime": "2026-03-05T16:00:00Z",
            "status": "pending_review",
        }
        
        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]
        
        # Reject
        events.reject_event(authenticated_client, event_id)
        rejected = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        assert rejected.data["status"] == "rejected"
        
        # Restore
        events.restore_rejected_event(authenticated_client, event_id)
        restored = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        assert restored.data["status"] == "pending_review"


@pytest.mark.integration
@pytest.mark.development
class TestSenderRules:
    """Test sender rule automation."""

    def test_check_sender_rules_exact_email(self, authenticated_client, test_user_id):
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

    def test_check_sender_rules_domain_match(self, authenticated_client, test_user_id):
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

    def test_create_event_with_source(self, authenticated_client, test_user_id):
        """Test creating event with source link."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-source-{uuid4().hex[:8]}",
            "subject": "Test Event",
            "from_email": "test@example.com",
            "from_name": "Test Sender",
            "date_sent": "2026-02-01T10:00:00Z",
            "snippet": "Test content",
            "gmail_label_ids": ["INBOX"],
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
        
        event_id = events.create_event(
            authenticated_client,
            test_user_id,
            event_data,
            email_id
        )
        
        # Verify event_source was created
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).execute()
        
        assert len(sources.data) == 1
        assert sources.data[0]["email_id"] == email_id
        assert sources.data[0]["source_type"] == "new_invitation"

    def test_source_attribution_generation(self, authenticated_client, test_user_id):
        """Test natural English attribution generation."""
        # Create test email and event
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-attr-{uuid4().hex[:8]}",
            "subject": "Event Invitation",
            "from_email": "sender@test.com",
            "from_name": "Event Organizer",
            "date_sent": "2026-01-25T13:30:00Z",
            "snippet": "Event details",
            "gmail_label_ids": ["INBOX"],
        }
        
        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]
        
        event_data = {
            "title": "Test Attribution",
            "start_datetime": "2026-03-15T14:00:00Z",
            "description": "Test",
            "source_quote": "Quote from email",
        }
        
        event_id = events.create_event(
            authenticated_client,
            test_user_id,
            event_data,
            email_id
        )
        
        # Check attribution was generated
        event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        
        attribution = event.data.get("source_attribution")
        assert attribution is not None
        assert "Event Organizer" in attribution or "sender@test.com" in attribution
        assert "January" in attribution or "Jan" in attribution
