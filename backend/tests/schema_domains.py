"""Every enumerated CHECK domain in Selko's schema, pinned.

Moved from integration/test_schema_contract.py (05-verification §A.7 item a).
Adding a value is a one-line edit; removing one requires checking every writer
first (CLAUDE.md: never narrow a CHECK constraint without checking its writers).
Asserted against the applied SQLite chain by
test_sqlite_schema.py::test_check_constraint_domains_are_pinned.
"""

from __future__ import annotations

EXPECTED_CHECK_DOMAINS: dict[tuple[str, str], set[str]] = {
    ("action_history", "action_type"): {"create", "update", "delete"},
    ("action_history", "entity_type"): {"event", "sender_rule"},
    ("attachments", "ingestion_status"): {
        "pending", "processing", "stored", "unsupported", "retry", "dead_letter",
    },
    # I2: distinguishes entries Selko wrote (they carry our private
    # extendedProperty) from ones the user created or accepted elsewhere.
    ("calendar_entries", "origin"): {"selko_created", "external"},
    ("calendar_work_items", "action"): {"upsert", "cancel"},
    ("calendar_work_items", "status"): {
        "pending", "processing", "succeeded", "failed", "blocked", "superseded",
    },
    ("calendar_sync_log", "action"): {"created", "updated", "deleted", "cancelled"},
    ("email_folders", "classification_decision"): {"include", "exclude", "uncertain"},
    ("email_folders", "folder_kind"): {"label", "folder"},
    ("email_folders", "provider"): {"gmail", "outlook"},
    ("email_ingestion_items", "acquisition_status"): {
        "pending", "processing", "completed", "retry", "dead_letter", "removed",
    },
    ("email_ingestion_items", "change_kind"): {"upsert", "membership_change", "removed"},
    ("email_ingestion_items", "provider"): {"gmail", "outlook"},
    ("email_sync_runs", "provider"): {"gmail", "outlook"},
    ("email_sync_runs", "run_kind"): {
        "initial", "incremental", "daily_reconcile", "weekly_reconcile", "manual_repair",
    },
    ("email_sync_runs", "status"): {"running", "completed", "failed", "abandoned"},
    ("email_sync_state", "provider"): {"gmail", "outlook"},
    ("emails", "processing_outcome"): {
        "no_event", "event_matched", "event_created", "event_updated",
        "event_created_and_updated", "event_cancelled", "calendar_invite",
        "cancellation_unmatched", "cancellation_ambiguous",
    },
    ("emails", "processing_status"): {"pending", "processing", "processed", "failed", "skipped"},
    ("event_sources", "source_origin"): {"email", "google_calendar"},
    ("event_sources", "source_type"): {"new_invitation", "update", "cancellation", "reminder", "unknown"},
    ("event_change_proposals", "kind"): {"material_update", "cancellation"},
    ("event_change_proposals", "status"): {"pending", "applied", "rejected", "superseded", "closed_legacy"},
    ("event_identity_hints", "kind"): {"ical_uid", "provider_thread", "join_url", "management_url"},
    ("event_identity_hints", "strength"): {"authoritative", "supporting"},
    ("event_repair_audit", "action"): {"merge_duplicate_group", "merge_source", "cancel_event", "resolve_proposal"},
    ("events", "review_status"): {"pending_review", "active", "rejected", "cancelled"},
    ("events", "importance"): {"action_required", "fyi"},
    ("graph_api_failures", "graph_surface"): {"outlook_mail", "outlook_calendar", "onedrive"},
    ("calendar_work_items", "provider"): {"google_calendar", "outlook"},
    ("integration_recoveries", "reason"): {"initial_connection", "reauthorization"},
    ("integration_recoveries", "status"): {
        "pending", "processing", "waiting", "completed", "completed_with_errors",
        "failed", "superseded",
    },
    ("operational_incidents", "severity"): {"warning", "critical"},
    ("operational_incidents", "status"): {"open", "resolved"},
    ("sender_rules", "action"): {"auto_approve", "ignore"},
    # Postgres enums until the SQLite schema (0001_initial.sql), now CHECK domains.
    ("integrations", "provider"): {"gmail", "google_calendar", "outlook"},
    ("integrations", "status"): {"active", "error", "expired", "revoked"},
    ("integration_recoveries", "provider"): {"gmail", "google_calendar", "outlook"},
    ("llm_call_log", "operation_type"): {
        "classify_email_folder", "compare_events", "extract_events", "merge_events",
        "propose_event_update",
    },
    # Selko's own sessions (03-api-auth-web §B).
    ("auth_sessions", "revoked_reason"): {
        "account_deleted", "expired", "logout", "logout_global", "password_changed", "reuse_detected",
    },
    ("user_calendar_settings", "all_day_display_mode"): {
        "all_day", "day_9_to_5", "morning_8_to_9", "custom",
    },
}
