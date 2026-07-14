from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def read_migration(name: str) -> str:
    return (MIGRATIONS / name).read_text()


def test_sender_rule_dedupe_installs_guard_before_deleting_duplicates():
    sql = read_migration("20260713000001_ignore_sender_retroactive.sql")

    assert "DISABLE TRIGGER sender_rule_before_delete" not in sql
    assert "CREATE OR REPLACE FUNCTION reset_skipped_emails_for_sender_rule()" in sql
    assert sql.index("CREATE OR REPLACE FUNCTION reset_skipped_emails_for_sender_rule()") < sql.index(
        "-- De-duplicate any pre-existing rows"
    )
    assert "action = 'ignore'" in sql


def test_ignored_domain_repair_respects_exact_non_ignore_rules():
    sql = read_migration("20260714000001_repair_requeued_ignored_sender_emails.sql")

    assert "exact_rule.sender_email = em.from_email" in sql
    assert "exact_rule.action <> 'ignore'" in sql


def test_auto_approved_sender_repair_preserves_calendar_invites():
    sql = read_migration("20260714000002_repair_auto_approved_sender_emails.sql")

    assert "processing_outcome IS DISTINCT FROM 'calendar_invite'" in sql
    assert "exact_rule.action = 'auto_approve'" in sql
    assert "domain_rule.action = 'auto_approve'" in sql
