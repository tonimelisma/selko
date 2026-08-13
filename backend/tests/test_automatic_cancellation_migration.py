from pathlib import Path


def test_automatic_cancellation_preserves_legacy_event_statuses() -> None:
    sql = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/20260813000004_automatic_cancellation.sql"
    ).read_text(encoding="utf-8")
    for status in ("syncing", "synced", "sync_failed"):
        assert f"'{status}'" in sql
