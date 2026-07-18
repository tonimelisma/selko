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

    # Step 5: Insert events
    print("Inserting events...")

    def make_dt(days_offset, hour, minute=0):
        """Create a datetime offset from now at a specific hour."""
        dt = now + timedelta(days=days_offset)
        return dt.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    events_data = [
        # Pending review events (for Review Queue)
        {
            "user_id": user_id,
            "title": "Parent-Teacher Conference",
            "start_datetime": make_dt(3, 15),
            "end_datetime": make_dt(3, 16),
            "all_day": False,
            "location": "Lincoln Elementary School, Room 204",
            "description": "Meet with Ms. Thompson to discuss Emma's progress in 3rd grade.",
            "status": "pending_review",
            "importance": "action_required",
            "updated_at": (now - timedelta(minutes=30)).isoformat(),
            "source_attribution": "From email: Parent-Teacher Conference Reminder",
        },
        {
            "user_id": user_id,
            "title": "Spring Concert",
            "start_datetime": make_dt(10, 18),
            "end_datetime": make_dt(10, 20),
            "all_day": False,
            "location": "Lincoln Elementary Auditorium",
            "description": "Annual spring concert featuring performances by grades K-5.",
            "status": "pending_review",
            "importance": "fyi",
            "updated_at": (now - timedelta(minutes=45)).isoformat(),
            "source_attribution": "From email: Spring Concert Information",
        },
        {
            "user_id": user_id,
            "title": "Q2 Planning Offsite",
            "start_datetime": make_dt(7, 9),
            "end_datetime": make_dt(7, 17),
            "all_day": True,
            "location": "TechCorp HQ, Building 5, Conference Room A",
            "description": "Full-day offsite to plan Q2 roadmap. Lunch will be provided.",
            "status": "pending_change",
            "importance": "action_required",
            "updated_at": (now - timedelta(minutes=60)).isoformat(),
            "source_attribution": "From email: Q2 Planning Offsite Details",
        },
        # Other status events (for History)
        {
            "user_id": user_id,
            "title": "Dentist - Dr. Martinez",
            "start_datetime": make_dt(5, 10),
            "end_datetime": make_dt(5, 11),
            "all_day": False,
            "location": "Downtown Dental, 456 Oak Ave",
            "description": "Regular checkup and cleaning.",
            "status": "synced",
            "importance": "action_required",
            "google_calendar_event_id": "fake_gcal_id_1",
            "synced_at": (now - timedelta(hours=1)).isoformat(),
            "updated_at": (now - timedelta(hours=8)).isoformat(),
            "source_attribution": "From email: Appointment Confirmation",
        },
        {
            "user_id": user_id,
            "title": "Team Standup",
            "start_datetime": make_dt(1, 9),
            "end_datetime": make_dt(1, 9, 15),
            "all_day": False,
            "location": "",
            "description": "Daily team sync.",
            "status": "approved",
            "importance": "action_required",
            "updated_at": (now - timedelta(hours=2)).isoformat(),
            "source_attribution": "",
        },
        {
            "user_id": user_id,
            "title": "Marketing Webinar",
            "start_datetime": make_dt(2, 14),
            "end_datetime": make_dt(2, 15),
            "all_day": False,
            "location": "Zoom",
            "description": "Q1 marketing results review.",
            "status": "rejected",
            "importance": "fyi",
            "updated_at": (now - timedelta(hours=4)).isoformat(),
            "source_attribution": "",
        },
        {
            "user_id": user_id,
            "title": "Yoga Class",
            "start_datetime": make_dt(4, 18),
            "end_datetime": make_dt(4, 19),
            "all_day": False,
            "location": "Downtown Fitness Center",
            "description": "Weekly yoga class.",
            "status": "sync_failed",
            "importance": "action_required",
            "sync_error": "Failed to connect to Google Calendar API",
            "updated_at": (now - timedelta(hours=6)).isoformat(),
            "source_attribution": "",
        },
    ]

    result = admin.table("events").insert(events_data).execute()
    # Map event titles to IDs for linking
    event_ids = {row["title"]: row["id"] for row in result.data}
    print(f"  Inserted {len(result.data)} events")

    # Step 6: Insert event_sources
    print("Inserting event sources...")

    event_sources_data = [
        {
            "event_id": event_ids["Parent-Teacher Conference"],
            "email_id": email_ids["msg_screenshot_1"],
            "source_type": "new_invitation",
            "extracted_data": {
                "source_quote": (
                    "Dear Parents, This is a reminder about the upcoming "
                    "parent-teacher conferences scheduled for next week. Your "
                    "child's conference is scheduled with Ms. Thompson."
                ),
                "title": "Parent-Teacher Conference",
                "start_datetime": make_dt(3, 15),
            },
        },
        {
            "event_id": event_ids["Spring Concert"],
            "email_id": email_ids["msg_screenshot_2"],
            "source_type": "new_invitation",
            "extracted_data": {
                "source_quote": (
                    "We are excited to announce the annual Spring Concert! "
                    "Students from grades K-5 will be performing musical "
                    "selections they have been practicing."
                ),
                "title": "Spring Concert",
                "start_datetime": make_dt(10, 18),
            },
        },
        {
            "event_id": event_ids["Q2 Planning Offsite"],
            "email_id": email_ids["msg_screenshot_4"],
            "source_type": "update",
            "extracted_data": {
                "source_quote": (
                    "Hi team, Location update: we'll meet in Building 3 instead of Building 5."
                ),
                "title": "Q2 Planning Offsite",
                "location": "TechCorp HQ, Building 3, Conference Room B",
                "start_datetime": make_dt(7, 9),
            },
            "event_snapshot_before": {
                "title": "Q2 Planning Offsite",
                "location": "TechCorp HQ, Building 5, Conference Room A",
                "start_datetime": make_dt(7, 9),
                "status": "synced",
            },
            "change_set": {
                "kind": "material_update",
                "changes": [
                    {
                        "field": "location",
                        "before": "TechCorp HQ, Building 5, Conference Room A",
                        "after": "TechCorp HQ, Building 3, Conference Room B",
                        "reason": "Room moved to Building 3",
                    }
                ],
                "reasoning": "Email updates the offsite location",
            },
        },
        {
            "event_id": event_ids["Dentist - Dr. Martinez"],
            "email_id": email_ids["msg_screenshot_3"],
            "source_type": "new_invitation",
            "extracted_data": {
                "source_quote": (
                    "This is a confirmation of your appointment with Dr. Martinez "
                    "on the scheduled date. Please arrive 15 minutes early."
                ),
                "title": "Dentist - Dr. Martinez",
                "start_datetime": make_dt(5, 10),
            },
        },
    ]

    result = admin.table("event_sources").insert(event_sources_data).execute()
    print(f"  Inserted {len(result.data)} event sources")

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
