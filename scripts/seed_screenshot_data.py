#!/usr/bin/env python3
"""Seed and clean up fake data for screenshot captures.

Creates a realistic-looking user with integrations, emails, events,
and event sources suitable for taking product screenshots.

Usage:
    uv run python scripts/seed_screenshot_data.py seed
    uv run python scripts/seed_screenshot_data.py cleanup
    uv run python scripts/seed_screenshot_data.py seed --cleanup-first
"""

import argparse
import hashlib

import sys
from datetime import datetime, timedelta, timezone

from selko.config import load_config
from selko.services.users import (
    UserManagementError,
    create_user,
    delete_user,
    get_admin_client,
    list_users,
)
from selko.services.resolution_fingerprint import candidate_fingerprint

# Screenshot test user credentials
SCREENSHOT_EMAIL = "screenshots@selko.local"
SCREENSHOT_PASSWORD = "screenshotpass123"
SCREENSHOT_DISPLAY_NAME = "Sarah Johnson"


def find_screenshot_user(config):
    """Find the screenshot user by email, returns user dict or None."""
    users = list_users(config)
    for user in users:
        if user["email"] == SCREENSHOT_EMAIL:
            return user
    return None


def do_cleanup(config):
    """Remove the screenshot user and all associated data (via CASCADE)."""
    print("Cleaning up screenshot data...")

    user = find_screenshot_user(config)
    if not user:
        print("  No screenshot user found. Nothing to clean up.")
        return

    user_id = user["id"]
    print(f"  Found screenshot user: {user_id}")

    try:
        delete_user(config, user_id)
        print(f"  Deleted user {user_id} and all associated data (CASCADE).")
    except UserManagementError as e:
        print(f"  Error deleting user: {e}")
        sys.exit(1)

    print("Cleanup complete.")


def do_seed(config):
    """Create the screenshot user and seed all associated data."""
    admin = get_admin_client(config)
    now = datetime.now(timezone.utc)

    # Check if user already exists
    existing = find_screenshot_user(config)
    if existing:
        print(f"Error: Screenshot user already exists (id={existing['id']}).")
        print("Run with --cleanup-first or 'cleanup' command first.")
        sys.exit(1)

    # Step 1: Create auth user
    print("Creating user...")
    try:
        user = create_user(
            config,
            email=SCREENSHOT_EMAIL,
            password=SCREENSHOT_PASSWORD,
            auto_confirm=True,
        )
    except UserManagementError as e:
        print(f"  Error creating user: {e}")
        sys.exit(1)

    user_id = user["id"]
    print(f"  Created user: {user_id} ({user['email']})")

    seed_worker = "screenshot-fixture-seed"

    def call_rpc(name, params):
        response = admin.rpc(name, params).execute()
        data = response.data
        if isinstance(data, list) and len(data) == 1:
            return data[0]
        return data

    def lock_email(email_id):
        admin.table("emails").update({
            "processing_status": "processing",
            "locked_by": seed_worker,
            "locked_until": (now + timedelta(minutes=10)).isoformat(),
            "lock_generation": 1,
        }).eq("id", email_id).execute()

    def commit_decision(email_id, decision):
        lock_email(email_id)
        result = call_rpc("commit_email_extraction", {
            "p_email_id": email_id,
            "p_worker_id": seed_worker,
            "p_generation": 1,
            "p_decisions": [decision],
            "p_terminal": "processed",
        })
        if not isinstance(result, dict) or result.get("fenced") or result.get("conflict"):
            raise RuntimeError(f"fixture extraction commit failed: {result!r}")
        return result

    def day_window(start_datetime):
        start = datetime.fromisoformat(start_datetime.replace("Z", "+00:00"))
        day_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start.isoformat(), (day_start + timedelta(days=1)).isoformat()

    def decision_envelope(action, fields, source, *, intent, event_id=None,
                          expected_fingerprint=None, window=None):
        window = window or day_window(fields["start_datetime"])
        return {
            "action": action,
            "event_id": event_id,
            "intent": intent,
            "fields": fields,
            "window_start": window[0],
            "window_end": window[1],
            "expected_fingerprint": expected_fingerprint or candidate_fingerprint([]),
            "hints": [],
            "source": source,
        }

    # Step 2: Update display name
    print("Setting display name...")
    admin.table("users").update({"display_name": SCREENSHOT_DISPLAY_NAME}).eq(
        "id", user_id
    ).execute()
    print(f"  Display name set to '{SCREENSHOT_DISPLAY_NAME}'")

    # Step 3: Insert integrations
    print("Inserting integrations...")
    token_expiry = (now + timedelta(days=30)).isoformat()

    integrations = [
        {
            "user_id": user_id,
            "provider": "gmail",
            "status": "active",
            "access_token": "fake-gmail-token",
            "refresh_token": "fake-gmail-refresh",
            "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            "provider_email": "sarah.johnson@gmail.com",
            "token_expiry": token_expiry,
        },
        {
            "user_id": user_id,
            "provider": "google_calendar",
            "status": "active",
            "access_token": "fake-gcal-token",
            "refresh_token": "fake-gcal-refresh",
            "scopes": ["https://www.googleapis.com/auth/calendar"],
            "provider_email": "sarah.johnson@gmail.com",
            "token_expiry": token_expiry,
        },
    ]

    result = admin.table("integrations").insert(integrations).execute()
    print(f"  Inserted {len(result.data)} integrations")

    # Folder preferences make the Included/Excluded control visible in Settings captures.
    gmail_integration_id = next(
        row["id"] for row in result.data if row["provider"] == "gmail"
    )
    folders = [
        {
            "user_id": user_id,
            "integration_id": gmail_integration_id,
            "provider": "gmail",
            "provider_folder_id": "all-mail",
            "name": "All Mail",
            "full_path": "[Gmail]/All Mail",
            "folder_kind": "label",
            "classification_decision": "include",
            "is_included": True,
        },
        {
            "user_id": user_id,
            "integration_id": gmail_integration_id,
            "provider": "gmail",
            "provider_folder_id": "promotions",
            "name": "Promotions",
            "full_path": "Promotions",
            "folder_kind": "label",
            "classification_decision": "exclude",
            "classification_reason": "This folder is dedicated to promotional and marketing emails.",
            "is_included": False,
        },
    ]
    admin.table("email_folders").insert(folders).execute()
    print(f"  Inserted {len(folders)} email folders")

    # Step 4: Insert emails
    print("Inserting emails...")

    def content_hash(subject):
        return hashlib.sha256(subject.encode()).hexdigest()

    emails_data = [
        {
            "user_id": user_id,
            "from_name": "Lincoln Elementary School",
            "from_email": "office@lincoln-elementary.edu",
            "subject": "Parent-Teacher Conference Reminder",
            "provider_message_id": "msg_screenshot_1",
            "thread_id": "thread_1",
            "to_emails": ["sarah.johnson@gmail.com"],
            "date_sent": (now - timedelta(days=2)).isoformat(),
            "processing_status": "processed",
            "content_hash": content_hash("Parent-Teacher Conference Reminder"),
        },
        {
            "user_id": user_id,
            "from_name": "Lincoln Elementary School",
            "from_email": "office@lincoln-elementary.edu",
            "subject": "Spring Concert Information",
            "provider_message_id": "msg_screenshot_2",
            "thread_id": "thread_2",
            "to_emails": ["sarah.johnson@gmail.com"],
            "date_sent": (now - timedelta(days=3)).isoformat(),
            "processing_status": "processed",
            "content_hash": content_hash("Spring Concert Information"),
        },
        {
            "user_id": user_id,
            "from_name": "Downtown Dental",
            "from_email": "appointments@downtowndental.com",
            "subject": "Appointment Confirmation: Dr. Martinez",
            "provider_message_id": "msg_screenshot_3",
            "thread_id": "thread_3",
            "to_emails": ["sarah.johnson@gmail.com"],
            "date_sent": (now - timedelta(days=1)).isoformat(),
            "processing_status": "processed",
            "content_hash": content_hash("Appointment Confirmation: Dr. Martinez"),
        },
        {
            "user_id": user_id,
            "from_name": "Alex Chen",
            "from_email": "alex.chen@techcorp.com",
            "subject": "Q2 Planning Offsite Details",
            "provider_message_id": "msg_screenshot_4",
            "thread_id": "thread_4",
            "to_emails": ["sarah.johnson@gmail.com"],
            "date_sent": (now - timedelta(days=4)).isoformat(),
            "processing_status": "processed",
            "content_hash": content_hash("Q2 Planning Offsite Details"),
        },
    ]

    result = admin.table("emails").insert(emails_data).execute()
    email_ids = {row["provider_message_id"]: row["id"] for row in result.data}
    print(f"  Inserted {len(result.data)} emails")

    # Step 5: Create events and sources through the fenced application RPC.
    print("Committing events through application RPCs...")

    def make_dt(days_offset, hour, minute=0):
        dt = now + timedelta(days=days_offset)
        return dt.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    event_specs = [
        ("Parent-Teacher Conference", "msg_screenshot_1", 3, 15, 16, False,
         "Lincoln Elementary School, Room 204", "Meet with Ms. Thompson to discuss Emma's progress in 3rd grade.", "pending_review", "action_required"),
        ("Spring Concert", "msg_screenshot_2", 10, 18, 20, False,
         "Lincoln Elementary Auditorium", "Annual spring concert featuring performances by grades K-5.", "pending_review", "fyi"),
        ("Q2 Planning Offsite", "msg_screenshot_4", 7, 9, 17, True,
         "TechCorp HQ, Building 5, Conference Room A", "Full-day offsite to plan Q2 roadmap. Lunch will be provided.", "synced", "action_required"),
        ("Dentist - Dr. Martinez", "msg_screenshot_3", 5, 10, 11, False,
         "Downtown Dental, 456 Oak Ave", "Regular checkup and cleaning.", "approved", "action_required"),
        ("Team Standup", "msg_screenshot_1", 1, 9, 9, False,
         "", "Daily team sync.", "approved", "action_required"),
        ("Marketing Webinar", "msg_screenshot_2", 2, 14, 15, False,
         "Zoom", "Q1 marketing results review.", "rejected", "fyi"),
        ("Yoga Class", "msg_screenshot_3", 4, 18, 19, False,
         "Downtown Fitness Center", "Weekly yoga class.", "approved", "action_required"),
    ]
    event_ids = {}
    for title, provider_message_id, day, start_hour, end_hour, all_day, location, description, status, importance in event_specs:
        start_datetime = make_dt(day, start_hour)
        end_datetime = make_dt(day, end_hour)
        # The spec's `status` is the *delivery* state step 6 produces through
        # the work queue. events.status itself was deleted by 20260829000001, and
        # the commit RPC no longer infers a review lane from anything -- so the
        # lane this implies is stated outright.
        review_status = (
            status if status in ("pending_review", "rejected", "cancelled") else "active"
        )
        fields = {
            "title": title,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
            "all_day": all_day,
            "location": location,
            "description": description,
            "review_status": review_status,
            "importance": importance,
        }
        source = {
            "email_id": email_ids[provider_message_id],
            "source_type": "new_invitation",
            "extracted_data": {**fields, "source_quote": f"Fixture source for {title}."},
        }
        result = commit_decision(
            email_ids[provider_message_id],
            decision_envelope("create", fields, source, intent="no_change"),
        )
        event_ids[title] = result["event_ids"][0]
    print(f"  Committed {len(event_ids)} events and their sources")

    # Q2's second email is an update: the RPC owns proposal creation and
    # review-state transitions from the same source payload.
    q2_update_email = admin.table("emails").insert({
        "user_id": user_id,
        "from_name": "Alex Chen",
        "from_email": "alex.chen@techcorp.com",
        "subject": "Q2 Planning Offsite Room Change",
        "provider_message_id": "msg_screenshot_5",
        "thread_id": "thread_4",
        "to_emails": ["sarah.johnson@gmail.com"],
        "date_sent": (now - timedelta(days=1)).isoformat(),
        "processing_status": "processing",
        "content_hash": content_hash("Q2 Planning Offsite Room Change"),
    }).execute().data[0]["id"]
    q2 = admin.table("events").select("*").eq("id", event_ids["Q2 Planning Offsite"]).single().execute().data
    q2_window = day_window(q2["start_datetime"])
    q2_source = {
        "email_id": q2_update_email,
        "source_type": "update",
        "extracted_data": {
            "title": "Q2 Planning Offsite",
            "location": "TechCorp HQ, Building 3, Conference Room B",
            "start_datetime": q2["start_datetime"],
            "source_quote": "Room moved to Building 3.",
        },
        "event_snapshot_before": q2,
        "change_set": {
            "kind": "material_update",
            "changes": [{
                "field": "location",
                "before": q2["location"],
                "after": "TechCorp HQ, Building 3, Conference Room B",
                "reason": "Room moved to Building 3",
            }],
            "reasoning": "Email updates the offsite location",
        },
    }
    commit_decision(
        q2_update_email,
        decision_envelope(
            "update",
            # The Changes lane: a pending proposal on an active event. This used
            # to require sending review_status='pending_review' -- a value the
            # fixture knew to be wrong -- because the commit RPC derived
            # auto-apply from that field and defaulted it to 'active'. It now
            # takes an explicit intent, so the fixture can state what it means.
            {"review_status": "active"},
            q2_source,
            intent="review",
            event_id=event_ids["Q2 Planning Offsite"],
            expected_fingerprint=candidate_fingerprint([q2]),
            window=q2_window,
        ),
    )
    print("  Created the Q2 pending proposal through commit_email_extraction")

    # Step 6: Drive calendar delivery through the public enqueue/claim/complete
    # and fail RPCs, never by inserting queue rows directly.
    print("Seeding calendar work through worker RPCs...")

    def desired_event(title):
        row = admin.table("events").select(
            "title,start_datetime,end_datetime,all_day,location,description,importance"
        ).eq("id", event_ids[title]).single().execute().data
        return row

    def enqueue(title):
        data = call_rpc("enqueue_calendar_work", {
            "p_event_id": event_ids[title],
            "p_user_id": user_id,
            "p_action": "upsert",
            "p_desired_event": desired_event(title),
            "p_expected_provider_revision": None,
            "p_force_overwrite": False,
        })
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"calendar work enqueue failed: {data!r}")
        return data

    def claim_next():
        rows = call_rpc("claim_calendar_work_item", {
            "p_worker_id": seed_worker,
            "p_lease_seconds": 600,
        })
        row = rows[0] if isinstance(rows, list) else rows
        if not row:
            raise RuntimeError(f"calendar work claim failed: {rows!r}")
        return row

    def complete(item, provider_event_id=None):
        ok = call_rpc("complete_calendar_work", {
            "p_item_id": item["id"],
            "p_worker_id": seed_worker,
            "p_generation": item["generation"],
            "p_provider_event_id": provider_event_id,
            "p_provider_revision": None,
        })
        if ok is not True:
            raise RuntimeError(f"calendar work completion failed: {ok!r}")

    def fail(item):
        result = call_rpc("fail_calendar_work", {
            "p_item_id": item["id"],
            "p_worker_id": seed_worker,
            "p_generation": item["generation"],
            "p_error_code": "provider_transient",
            "p_error_detail": "Fixture provider failure",
            "p_retryable": False,
        })
        if not isinstance(result, dict) or result.get("status") != "blocked":
            raise RuntimeError(f"calendar work failure transition failed: {result!r}")

    enqueue("Q2 Planning Offsite")
    completed_targets = set()
    for _ in range(8):
        if {"q2", "dentist", "yoga"} <= completed_targets:
            break
        claimed = claim_next()
        event_id = claimed["event_id"]
        if event_id == event_ids["Q2 Planning Offsite"]:
            complete(claimed)
            completed_targets.add("q2")
        elif event_id == event_ids["Dentist - Dr. Martinez"]:
            complete(claimed, "fake_gcal_id_1")
            completed_targets.add("dentist")
        elif event_id == event_ids["Yoga Class"]:
            fail(claimed)
            completed_targets.add("yoga")
        elif event_id == event_ids["Team Standup"]:
            # The fixture deliberately leaves this item pending. A retryable
            # failure is the public worker transition that releases the claim.
            released = call_rpc("fail_calendar_work", {
                "p_item_id": claimed["id"],
                "p_worker_id": seed_worker,
                "p_generation": claimed["generation"],
                "p_error_code": "provider_transient",
                "p_error_detail": "Fixture pending work release",
                "p_retryable": True,
            })
            if not isinstance(released, dict) or released.get("status") != "pending":
                raise RuntimeError(f"calendar work release failed: {released!r}")
        else:
            raise RuntimeError(f"unexpected screenshot work item: {claimed!r}")
    print("  Seeded succeeded, pending, and blocked worker-owned calendar work")

    # Step 7: Insert user_calendar_settings
    print("Inserting calendar settings...")

    calendar_settings = {
        "user_id": user_id,
        "target_calendar_id": "primary",
    }

    result = admin.table("user_calendar_settings").insert(calendar_settings).execute()
    print(f"  Inserted calendar settings")

    print()
    print("Seed complete!")
    print(f"  Email: {SCREENSHOT_EMAIL}")
    print(f"  Password: {SCREENSHOT_PASSWORD}")
    print(f"  User ID: {user_id}")


def main():
    parser = argparse.ArgumentParser(
        description="Seed and clean up screenshot test data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run python scripts/seed_screenshot_data.py seed
    uv run python scripts/seed_screenshot_data.py cleanup
    uv run python scripts/seed_screenshot_data.py seed --cleanup-first
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # seed command
    seed_parser = subparsers.add_parser("seed", help="Create screenshot user and data")
    seed_parser.add_argument(
        "--cleanup-first",
        action="store_true",
        help="Remove existing screenshot data before seeding",
    )

    # cleanup command
    subparsers.add_parser("cleanup", help="Remove screenshot user and all data")

    args = parser.parse_args()
    config = load_config()

    if args.command == "seed":
        if args.cleanup_first:
            do_cleanup(config)
            print()
        do_seed(config)
    elif args.command == "cleanup":
        do_cleanup(config)


if __name__ == "__main__":
    main()
