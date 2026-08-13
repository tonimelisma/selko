from pathlib import Path

from selko.services.event_identity import (
    build_hints,
    canonical_ical_uid,
    canonical_join_url,
    canonical_management_url,
    canonical_provider_thread,
)
from selko.services.events import CandidateWindow, _identity_key, _identity_match


def test_ical_uid_is_authoritative_and_content_free():
    hint = canonical_ical_uid("  Meeting-42@Example.COM ", "2026-09-13T10:00:00Z")
    assert hint is not None
    assert hint.kind == "ical_uid"
    assert hint.strength == "authoritative"
    assert len(hint.value_hash) == 64
    assert "Meeting-42" not in str(hint.as_payload())


def test_provider_thread_is_namespaced_by_provider():
    assert canonical_provider_thread("gmail", "thread-1") != canonical_provider_thread(
        "outlook", "thread-1"
    )


def test_join_url_removes_tracking_and_fragment_but_preserves_identity():
    first = canonical_join_url("HTTPS://Meet.Example/room/?utm_source=x&room=abc#details")
    second = canonical_join_url("https://meet.example/room?room=abc")
    assert first == second


def test_management_url_preserves_opaque_query_identity():
    first = canonical_management_url("https://portal.example/manage?token=a")
    second = canonical_management_url("https://portal.example/manage?token=b")
    assert first != second


def test_single_supporting_signal_is_not_promoted_to_authoritative():
    hints = build_hints(
        provider="gmail",
        thread_id="thread-1",
        event_values=("https://meet.example/room",),
    )
    assert {hint.kind for hint in hints} == {"provider_thread", "join_url"}
    assert all(hint.strength == "supporting" for hint in hints)


def test_c2_migration_has_rls_and_only_commit_hint_writer():
    migration = Path("supabase/migrations/20260820000001_identity_hints_and_fence.sql").read_text()
    assert "ALTER TABLE public.event_identity_hints ENABLE ROW LEVEL SECURITY" in migration
    assert "GRANT ALL ON TABLE public.event_identity_hints TO service_role" in migration
    assert migration.count("INSERT INTO public.event_identity_hints") == 1
    assert "v_decision->'hints'" in migration


def test_permanent_room_supporting_hint_cannot_merge_distinct_slots():
    hint = canonical_join_url("https://meet.example/permanent-room")
    assert hint is not None
    candidate = {
        "id": "event-a",
        "updated_at": "2026-08-12T10:00:00+00:00",
        "title": "Earlier meeting",
        "start_datetime": "2026-09-13T10:00:00+00:00",
        "end_datetime": "2026-09-13T11:00:00+00:00",
    }
    window = CandidateWindow("2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z", "empty")
    result = _identity_match(
        {_identity_key(hint): [{"event_id": "event-a"}]},
        {"event-a": candidate},
        [hint],
        {
            "start_datetime": "2026-09-14T10:00:00+00:00",
            "end_datetime": "2026-09-14T11:00:00+00:00",
        },
        window,
    )
    assert result is None


def test_authoritative_stale_sequence_is_audited_noop():
    hint = canonical_ical_uid("uid@example", "2026-09-13T10:00:00Z")
    assert hint is not None
    hint = type(hint)(**{**hint.__dict__, "sequence": 1, "dtstamp": "2026-09-12T10:00:00Z"})
    event = {
        "id": "event-a",
        "updated_at": "2026-08-12T10:00:00+00:00",
        "title": "Current meeting",
        "start_datetime": "2026-09-13T10:00:00+00:00",
        "end_datetime": "2026-09-13T11:00:00+00:00",
    }
    result = _identity_match(
        {_identity_key(hint): [{"event_id": "event-a", "sequence": 2, "dtstamp": "2026-09-12T10:00:00Z"}]},
        {"event-a": event},
        [hint],
        event,
        CandidateWindow("2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z", "empty"),
    )
    assert result is not None
    assert result.stale_authoritative is True
