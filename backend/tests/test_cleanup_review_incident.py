"""Unit tests for the pure decision helpers in the WS2 production cleanup script.

The script lives in scripts/ (a one-off tool, not part of the selko package),
so it's imported directly from its file path rather than via `selko.*`.
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "cleanup_review_incident_20260713.py"
)
_spec = importlib.util.spec_from_file_location("cleanup_review_incident_20260713", SCRIPT_PATH)
cleanup_script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cleanup_script
_spec.loader.exec_module(cleanup_script)

find_orphaned_outlook_email_ids = cleanup_script.find_orphaned_outlook_email_ids
fetch_all_rows = cleanup_script.fetch_all_rows
group_duplicate_pending_events = cleanup_script.group_duplicate_pending_events
pending_change_has_orphaned_email_source = (
    cleanup_script.pending_change_has_orphaned_email_source
)


class TestFetchAllRows:
    def test_reads_past_postgrest_row_cap_in_stable_ranges(self):
        rows = [{"id": str(index)} for index in range(5)]
        requested_ranges = []

        class Query:
            def order(self, column):
                assert column == "id"
                return self

            def range(self, start, end):
                requested_ranges.append((start, end))
                self.start = start
                self.end = end
                return self

            def execute(self):
                return SimpleNamespace(data=rows[self.start : self.end + 1])

        assert fetch_all_rows(Query, page_size=2) == rows
        assert requested_ranges == [(0, 1), (2, 3), (4, 5)]


class TestPendingChangeOrphanDetection:
    def test_uses_email_sibling_when_latest_source_is_google_calendar(self):
        sources = [
            {"id": "email", "source_type": "update", "email_id": "orphan"},
            {"id": "gcal", "source_type": "update", "email_id": None},
        ]

        assert pending_change_has_orphaned_email_source(sources, {"orphan"})

    def test_ignores_non_proposal_or_non_orphaned_email_sources(self):
        sources = [
            {"source_type": "new_invitation", "email_id": "orphan"},
            {"source_type": "update", "email_id": "kept"},
        ]

        assert not pending_change_has_orphaned_email_source(sources, {"orphan"})


class TestFindOrphanedOutlookEmailIds:
    def test_email_with_all_folders_missing_is_orphaned(self):
        emails = [{"id": "e1", "provider_folder_ids": ["deleted-folder"]}]
        known_folder_ids = {"inbox-folder"}
        assert find_orphaned_outlook_email_ids(emails, known_folder_ids) == ["e1"]

    def test_email_with_a_known_folder_is_not_orphaned(self):
        emails = [{"id": "e1", "provider_folder_ids": ["inbox-folder"]}]
        known_folder_ids = {"inbox-folder"}
        assert find_orphaned_outlook_email_ids(emails, known_folder_ids) == []

    def test_email_with_one_known_and_one_deleted_folder_is_not_orphaned(self):
        """Only orphaned when EVERY folder entry is missing."""
        emails = [{"id": "e1", "provider_folder_ids": ["inbox-folder", "deleted-folder"]}]
        known_folder_ids = {"inbox-folder"}
        assert find_orphaned_outlook_email_ids(emails, known_folder_ids) == []

    def test_email_with_no_folder_ids_is_not_orphaned(self):
        emails = [{"id": "e1", "provider_folder_ids": []}]
        assert find_orphaned_outlook_email_ids(emails, set()) == []

    def test_email_with_missing_folder_ids_key_is_not_orphaned(self):
        emails = [{"id": "e1"}]
        assert find_orphaned_outlook_email_ids(emails, set()) == []

    def test_multiple_emails_mixed(self):
        emails = [
            {"id": "orphan-1", "provider_folder_ids": ["deleted-1"]},
            {"id": "kept-1", "provider_folder_ids": ["inbox"]},
            {"id": "orphan-2", "provider_folder_ids": ["deleted-2"]},
        ]
        known_folder_ids = {"inbox"}
        assert find_orphaned_outlook_email_ids(emails, known_folder_ids) == [
            "orphan-1",
            "orphan-2",
        ]


class TestGroupDuplicatePendingEvents:
    def test_single_event_is_not_a_duplicate(self):
        events = [
            {
                "id": "e1",
                "title": "Deadline",
                "start_datetime": "2026-08-01T20:00:00Z",
                "created_at": "2026-07-01T00:00:00Z",
            }
        ]
        assert group_duplicate_pending_events(events) == []

    def test_duplicate_pair_keeps_oldest_created_at(self):
        events = [
            {
                "id": "newer",
                "title": "Application Deadline",
                "start_datetime": "2026-08-01T20:00:00Z",
                "created_at": "2026-07-13T01:15:00Z",
            },
            {
                "id": "older",
                "title": "Application Deadline",
                "start_datetime": "2026-08-01T20:00:00Z",
                "created_at": "2026-07-13T01:14:00Z",
            },
        ]
        result = group_duplicate_pending_events(events)
        assert len(result) == 1
        keep_id, reject_ids = result[0]
        assert keep_id == "older"
        assert reject_ids == ["newer"]

    def test_different_titles_are_not_grouped(self):
        events = [
            {"id": "a", "title": "Deadline A", "start_datetime": "2026-08-01T20:00:00Z", "created_at": "2026-07-01T00:00:00Z"},
            {"id": "b", "title": "Deadline B", "start_datetime": "2026-08-01T20:00:00Z", "created_at": "2026-07-01T00:00:00Z"},
        ]
        assert group_duplicate_pending_events(events) == []

    def test_different_start_datetimes_are_not_grouped(self):
        events = [
            {"id": "a", "title": "Deadline", "start_datetime": "2026-08-01T20:00:00Z", "created_at": "2026-07-01T00:00:00Z"},
            {"id": "b", "title": "Deadline", "start_datetime": "2026-08-02T20:00:00Z", "created_at": "2026-07-01T00:00:00Z"},
        ]
        assert group_duplicate_pending_events(events) == []

    def test_triplicate_keeps_only_oldest(self):
        events = [
            {"id": "c", "title": "X", "start_datetime": "T", "created_at": "2026-07-03T00:00:00Z"},
            {"id": "a", "title": "X", "start_datetime": "T", "created_at": "2026-07-01T00:00:00Z"},
            {"id": "b", "title": "X", "start_datetime": "T", "created_at": "2026-07-02T00:00:00Z"},
        ]
        result = group_duplicate_pending_events(events)
        assert len(result) == 1
        keep_id, reject_ids = result[0]
        assert keep_id == "a"
        assert sorted(reject_ids) == ["b", "c"]
