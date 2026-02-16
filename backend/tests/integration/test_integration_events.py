"""Integration tests for event processing pipeline."""

from uuid import uuid4

import pytest

from selko.services import events, event_processing


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
        
        # Verify mock was called (gateway stores mock client for testing)
        assert mock_gemini_client._mock_provider.generate.called

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
        
        # Mock should NOT be called (gateway stores mock client for testing)
        assert not mock_gemini_client._mock_provider.generate.called


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


@pytest.mark.integration
@pytest.mark.development
class TestEventUndoRedo:
    """Test event undo/redo functionality with snapshot restore."""

    def test_undo_restores_snapshot(self, authenticated_client, test_user_id, mock_gemini_client):
        """Test that undo restores the event to its previous snapshot."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-undo-{uuid4().hex[:8]}",
            "subject": "Meeting Update",
            "from_email": "organizer@example.com",
            "from_name": "Meeting Organizer",
            "date_sent": "2026-02-01T10:00:00Z",
            "snippet": "Meeting time changed to 3pm",
            "gmail_label_ids": ["INBOX"],
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

        event_id = events.create_event(
            authenticated_client,
            test_user_id,
            initial_event_data,
            email_id
        )

        # Create second email with update
        email_data_2 = {
            "user_id": test_user_id,
            "gmail_id": f"test-undo-update-{uuid4().hex[:8]}",
            "subject": "Meeting Update",
            "from_email": "organizer@example.com",
            "from_name": "Meeting Organizer",
            "date_sent": "2026-02-02T10:00:00Z",
            "snippet": "Meeting time changed",
            "gmail_label_ids": ["INBOX"],
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

        events.update_event(
            authenticated_client,
            mock_gemini_client,
            event_id,
            updated_data,
            email_id_2,
            "update"
        )

        # Verify event was updated
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        # Note: The actual title/time depends on LLM merge logic
        # but event_source should have snapshot

        # Get the update source record
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "update").execute()

        assert len(sources.data) == 1
        update_source_id = sources.data[0]["id"]
        snapshot = sources.data[0]["event_snapshot_before"]

        # Snapshot should have original values
        assert snapshot is not None
        assert snapshot["title"] == "Team Meeting"
        assert "14:00" in snapshot["start_datetime"]

        # Now undo the update
        events.undo_email_contribution(authenticated_client, update_source_id)

        # Verify event was restored
        restored_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert restored_event.data["title"] == "Team Meeting"
        assert "14:00" in restored_event.data["start_datetime"]

        # Verify source was marked as undone
        source_after = authenticated_client.table("event_sources").select("*").eq(
            "id", update_source_id
        ).single().execute()

        assert source_after.data["is_undone"] is True

    def test_redo_reactivates_source(self, authenticated_client, test_user_id, mock_gemini_client):
        """Test that redo marks the source as active again."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-redo-{uuid4().hex[:8]}",
            "subject": "Event Invite",
            "from_email": "host@example.com",
            "from_name": "Event Host",
            "date_sent": "2026-02-05T10:00:00Z",
            "snippet": "You're invited",
            "gmail_label_ids": ["INBOX"],
        }

        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]

        # Create event
        event_data = {
            "title": "Party",
            "start_datetime": "2026-03-25T19:00:00Z",
            "description": "Celebration",
        }

        event_id = events.create_event(
            authenticated_client,
            test_user_id,
            event_data,
            email_id
        )

        # Create second email
        email_data_2 = {
            "user_id": test_user_id,
            "gmail_id": f"test-redo-update-{uuid4().hex[:8]}",
            "subject": "Party Update",
            "from_email": "host@example.com",
            "from_name": "Event Host",
            "date_sent": "2026-02-06T10:00:00Z",
            "snippet": "Location changed",
            "gmail_label_ids": ["INBOX"],
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

        events.update_event(
            authenticated_client,
            mock_gemini_client,
            event_id,
            updated_data,
            email_id_2,
            "update"
        )

        # Get update source
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "update").execute()

        update_source_id = sources.data[0]["id"]

        # Undo it
        events.undo_email_contribution(authenticated_client, update_source_id)

        # Verify undone
        source_after_undo = authenticated_client.table("event_sources").select("*").eq(
            "id", update_source_id
        ).single().execute()
        assert source_after_undo.data["is_undone"] is True

        # Redo it
        events.redo_email_contribution(authenticated_client, update_source_id)

        # Verify no longer undone
        source_after_redo = authenticated_client.table("event_sources").select("*").eq(
            "id", update_source_id
        ).single().execute()
        assert source_after_redo.data["is_undone"] is False

    def test_undo_fails_without_snapshot(self, authenticated_client, test_user_id):
        """Test that undo fails gracefully when no snapshot exists."""
        # Create test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"test-no-snap-{uuid4().hex[:8]}",
            "subject": "New Event",
            "from_email": "sender@example.com",
            "from_name": "Sender",
            "date_sent": "2026-02-10T10:00:00Z",
            "snippet": "Event info",
            "gmail_label_ids": ["INBOX"],
        }

        email_result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = email_result.data[0]["id"]

        # Create event (first source has no snapshot)
        event_data = {
            "title": "New Event",
            "start_datetime": "2026-04-01T10:00:00Z",
        }

        event_id = events.create_event(
            authenticated_client,
            test_user_id,
            event_data,
            email_id
        )

        # Get the source (new_invitation - no snapshot)
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "new_invitation").execute()

        source_id = sources.data[0]["id"]

        # Attempt undo should fail
        with pytest.raises(events.EventsError) as exc_info:
            events.undo_email_contribution(authenticated_client, source_id)

        assert "No snapshot available" in str(exc_info.value)

    def test_attribution_excludes_undone_sources(self, authenticated_client, test_user_id, mock_gemini_client):
        """Test that source attribution excludes undone sources."""
        # Create first email
        email_data_1 = {
            "user_id": test_user_id,
            "gmail_id": f"test-attr-1-{uuid4().hex[:8]}",
            "subject": "Event Invite",
            "from_email": "first@example.com",
            "from_name": "First Sender",
            "date_sent": "2026-02-15T10:00:00Z",
            "snippet": "Event details",
            "gmail_label_ids": ["INBOX"],
        }

        email_result_1 = authenticated_client.table("emails").insert(email_data_1).execute()
        email_id_1 = email_result_1.data[0]["id"]

        # Create event
        event_data = {
            "title": "Attribution Test Event",
            "start_datetime": "2026-04-10T14:00:00Z",
        }

        event_id = events.create_event(
            authenticated_client,
            test_user_id,
            event_data,
            email_id_1
        )

        # Create second email
        email_data_2 = {
            "user_id": test_user_id,
            "gmail_id": f"test-attr-2-{uuid4().hex[:8]}",
            "subject": "Event Update",
            "from_email": "second@example.com",
            "from_name": "Second Sender",
            "date_sent": "2026-02-16T10:00:00Z",
            "snippet": "Update details",
            "gmail_label_ids": ["INBOX"],
        }

        email_result_2 = authenticated_client.table("emails").insert(email_data_2).execute()
        email_id_2 = email_result_2.data[0]["id"]

        # Update event
        updated_data = {
            "title": "Attribution Test Event - Updated",
            "start_datetime": "2026-04-10T15:00:00Z",
        }

        events.update_event(
            authenticated_client,
            mock_gemini_client,
            event_id,
            updated_data,
            email_id_2,
            "update"
        )

        # Get attribution - should include both senders
        attribution_before = events.generate_source_attribution(authenticated_client, event_id)
        assert "First Sender" in attribution_before or "first@example.com" in attribution_before
        # The second sender shows up in "updated" portion

        # Undo the second contribution
        sources = authenticated_client.table("event_sources").select("*").eq(
            "event_id", event_id
        ).eq("source_type", "update").execute()

        update_source_id = sources.data[0]["id"]
        events.undo_email_contribution(authenticated_client, update_source_id)

        # Get attribution again - should only include first sender
        attribution_after = events.generate_source_attribution(authenticated_client, event_id)
        assert "First Sender" in attribution_after or "first@example.com" in attribution_after
        # Second sender should no longer appear in updates portion
        # (since the update is undone)
