"""The SQLite foundation: schema, migration runner, single writer, codec.

Each test states a property the Postgres version had (or the plan requires)
and fails if the SQLite version loses it.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from selko.db import Database, MigrationError, migrate
from selko.db import codec
from selko.db.errors import CheckViolation, ForeignKeyViolation, InvariantViolation
from selko.db.migrate import MIGRATIONS_DIR, available, current_version

POSTGRES_TABLES = {
    "action_history", "attachments", "calendar_entries", "calendar_mirror_state",
    "calendar_sync_log", "calendar_work_items", "email_calendar_components",
    "email_folders", "email_ingestion_items", "email_sync_runs", "email_sync_state",
    "emails", "event_change_proposals", "event_identity_hints", "event_repair_audit",
    "event_sources", "events", "global_limits", "graph_api_failures",
    "integration_recoveries", "integrations", "llm_call_log", "oauth_states",
    "operational_incidents", "photos", "scheduled_tasks", "sender_rules",
    "usage_quotas", "user_calendar_settings", "users",
}


@pytest.fixture
def db(tmp_path: Path) -> Database:
    path = tmp_path / "selko.db"
    migrate(path)
    database = Database(path)
    yield database
    database.close()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# --- schema -----------------------------------------------------------------


def test_initial_schema_creates_every_table(tmp_path):
    path = tmp_path / "selko.db"
    assert migrate(path) == ["0001_initial.sql"]
    conn = sqlite3.connect(path)
    tables = _tables(conn)
    assert POSTGRES_TABLES <= tables, POSTGRES_TABLES - tables
    assert {"accounts", "auth_sessions", "auth_refresh_tokens", "schema_migrations"} <= tables
    assert current_version(conn) == 1


def test_every_table_is_strict(tmp_path):
    path = tmp_path / "selko.db"
    migrate(path)
    conn = sqlite3.connect(path)
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
        assert sql.rstrip().endswith("STRICT"), name


def test_check_domains_hold(db):
    """The Postgres CHECK domains survive: an unknown processing_status is refused."""
    with pytest.raises(CheckViolation, match="emails_processing_status_check"):
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO accounts (id, email, password_hash, created_at, updated_at) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'a@b.c', 'x', '2026', '2026')"
            )
            tx.execute(
                "INSERT INTO users (id, email) VALUES ('00000000-0000-0000-0000-000000000001', 'a@b.c')"
            )
            tx.execute(
                "INSERT INTO emails (id, user_id, provider_message_id, processing_status) "
                "VALUES ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-000000000001', 'm1', 'bogus')"
            )


def test_foreign_keys_are_enforced(db):
    with pytest.raises(ForeignKeyViolation):
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO emails (id, user_id, provider_message_id) "
                "VALUES ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-00000000dead', 'm1')"
            )


# --- migration runner -------------------------------------------------------


def _write(dir_: Path, name: str, sql: str) -> None:
    (dir_ / name).write_text(sql, encoding="utf-8")


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "selko.db"
    migrate(path)
    assert migrate(path) == []


def test_pending_migration_is_applied_after_a_backup(tmp_path):
    mdir = tmp_path / "m"
    mdir.mkdir()
    _write(mdir, "0001_a.sql", "CREATE TABLE t (x INTEGER) STRICT;")
    path = tmp_path / "data" / "selko.db"
    path.parent.mkdir()
    migrate(path, mdir)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO t VALUES (7)")
    conn.commit()
    conn.close()
    _write(mdir, "0002_b.sql", "ALTER TABLE t ADD COLUMN y INTEGER;")
    assert migrate(path, mdir) == ["0002_b.sql"]
    backup = path.parent / "backups" / "pre-0002.db"
    assert backup.exists()
    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT x FROM t").fetchall() == [(7,)]
    assert [r[1] for r in copy.execute("PRAGMA table_info(t)")] == ["x"]


def test_failing_migration_rolls_back_whole(tmp_path):
    mdir = tmp_path / "m"
    mdir.mkdir()
    _write(mdir, "0001_a.sql", "CREATE TABLE t (x INTEGER) STRICT;")
    path = tmp_path / "selko.db"
    migrate(path, mdir)
    _write(mdir, "0002_b.sql", "CREATE TABLE u (x INTEGER) STRICT;\nINSERT INTO nowhere VALUES (1);")
    with pytest.raises(MigrationError, match="rolled back"):
        migrate(path, mdir)
    conn = sqlite3.connect(path)
    assert "u" not in _tables(conn)
    assert current_version(conn) == 1


def test_foreign_key_violation_is_never_committed(tmp_path):
    mdir = tmp_path / "m"
    mdir.mkdir()
    _write(mdir, "0001_a.sql", "CREATE TABLE p (id INTEGER PRIMARY KEY) STRICT;")
    path = tmp_path / "selko.db"
    migrate(path, mdir)
    _write(
        mdir,
        "0002_b.sql",
        "CREATE TABLE c (p INTEGER REFERENCES p(id)) STRICT;\nPRAGMA foreign_keys=OFF;\nINSERT INTO c VALUES (99);",
    )
    with pytest.raises(MigrationError, match="(?i)foreign key"):
        migrate(path, mdir)
    assert "c" not in _tables(sqlite3.connect(path))


def test_changed_applied_migration_is_refused(tmp_path):
    mdir = tmp_path / "m"
    mdir.mkdir()
    _write(mdir, "0001_a.sql", "CREATE TABLE t (x INTEGER) STRICT;")
    path = tmp_path / "selko.db"
    migrate(path, mdir)
    _write(mdir, "0001_a.sql", "CREATE TABLE t (x INTEGER, y INTEGER) STRICT;")
    with pytest.raises(MigrationError, match="changed"):
        migrate(path, mdir)


def test_database_newer_than_the_build_is_refused(tmp_path):
    mdir = tmp_path / "m"
    mdir.mkdir()
    _write(mdir, "0001_a.sql", "CREATE TABLE t (x INTEGER) STRICT;")
    _write(mdir, "0002_b.sql", "CREATE TABLE u (x INTEGER) STRICT;")
    path = tmp_path / "selko.db"
    migrate(path, mdir)
    (mdir / "0002_b.sql").unlink()
    with pytest.raises(MigrationError, match="does not know"):
        migrate(path, mdir)


def test_shipped_migrations_are_numbered_without_gaps():
    assert [m.version for m in available(MIGRATIONS_DIR)] == list(range(1, len(available()) + 1))


# --- single writer ----------------------------------------------------------


def test_writes_never_interleave(db):
    """Concurrent claimers each get a different row: what SKIP LOCKED gave Postgres."""
    with db.transaction() as tx:
        tx.execute("CREATE TABLE q (id INTEGER PRIMARY KEY, owner TEXT) STRICT")
        tx.execute("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < 200) "
                   "INSERT INTO q (id) SELECT i FROM n")

    claimed: list[int] = []
    lock = threading.Lock()

    def claim(worker: str) -> None:
        while True:
            with db.transaction() as tx:
                row = tx.execute(
                    "UPDATE q SET owner = ? WHERE id = (SELECT id FROM q WHERE owner IS NULL LIMIT 1) RETURNING id",
                    (worker,),
                ).fetchone()
            if row is None:
                return
            with lock:
                claimed.append(row[0])

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == list(range(1, 201))


def test_after_commit_runs_only_on_commit(db):
    fired: list[str] = []
    with db.transaction() as tx:
        tx.after_commit(lambda: fired.append("committed"))
    with pytest.raises(RuntimeError):
        with db.transaction() as tx:
            tx.after_commit(lambda: fired.append("rolled back"))
            raise RuntimeError("boom")
    assert fired == ["committed"]


def test_rollback_discards_writes(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO accounts (id, email, password_hash, created_at, updated_at) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'a@b.c', 'x', '2026', '2026')"
            )
            raise RuntimeError("boom")
    assert db.reader().execute("SELECT count(*) FROM accounts").fetchone()[0] == 0


def test_readers_cannot_write(db):
    with pytest.raises(sqlite3.OperationalError):
        db.reader().execute("DELETE FROM accounts")


def test_run_moves_work_off_the_event_loop(db):
    async def go():
        return await db.run(lambda: threading.current_thread() is threading.main_thread())

    assert asyncio.run(go()) is False


# --- codec ------------------------------------------------------------------


def test_timestamp_text_orders_like_time():
    base = datetime(2026, 11, 25, 7, 0, tzinfo=timezone.utc)
    moments = [base + timedelta(microseconds=n) for n in (0, 1, 999_999)] + [
        base.astimezone(timezone(timedelta(hours=-8))) + timedelta(hours=1)
    ]
    texts = [codec.to_timestamp(m) for m in moments]
    assert sorted(texts) == [codec.to_timestamp(m) for m in sorted(moments)]
    assert all(len(t) == 27 and t.endswith("Z") for t in texts)


def test_timestamp_round_trips_and_refuses_naive():
    moment = datetime(2026, 3, 8, 10, 30, 1, 123456, tzinfo=timezone(timedelta(hours=-7)))
    assert codec.parse_timestamp(codec.to_timestamp(moment)) == moment
    with pytest.raises(ValueError):
        codec.to_timestamp(datetime(2026, 1, 1))


def test_json_is_canonical():
    assert codec.to_json({"b": 1, "a": [1, "ä"]}) == codec.to_json({"a": [1, "ä"], "b": 1}) == '{"a":[1,"ä"],"b":1}'


def test_schema_decodes_booleans_and_json(db):
    assert "is_spam" in db.schema.bool_columns["emails"]
    assert "processing_result" in db.schema.json_columns["emails"]
    row = {"is_spam": 1, "processing_result": '{"a":1}', "subject": "x"}
    assert db.schema.decode("emails", row) == {"is_spam": True, "processing_result": {"a": 1}, "subject": "x"}
    assert db.schema.encode("emails", {"is_spam": False, "processing_result": {"a": 1}}) == {
        "is_spam": 0,
        "processing_result": '{"a":1}',
    }


# --- event bus --------------------------------------------------------------


def test_bus_delivers_after_commit_from_a_worker_thread(db):
    from selko.db.bus import Bus

    bus = Bus()

    async def go():
        sub = bus.subscribe("user:u1")

        def write():
            with db.transaction() as tx:
                tx.after_commit(lambda: bus.publish("user:u1", {"resource": "events"}))

        await db.run(write)
        return await sub.get(timeout=2)

    assert asyncio.run(go()) == {"resource": "events"}


def test_bus_drops_oldest_for_a_slow_subscriber_and_marks_it_lagged():
    from selko.db.bus import Bus

    bus = Bus(queue_size=2)

    async def go():
        sub = bus.subscribe("t")
        for n in range(5):
            bus.publish("t", n)
        await asyncio.sleep(0)
        return [sub.queue.get_nowait() for _ in range(sub.queue.qsize())], sub.lagged

    assert asyncio.run(go()) == ([3, 4], True)


def test_bus_unsubscribe_stops_delivery():
    from selko.db.bus import Bus

    bus = Bus()

    async def go():
        sub = bus.subscribe("t")
        bus.unsubscribe(sub)
        return bus.publish("t", 1), bus.subscriber_count("t")

    assert asyncio.run(go()) == (0, 0)


# --- the transaction and the triggers ---------------------------------------

USER = "00000000-0000-0000-0000-0000000000a1"
OTHER = "00000000-0000-0000-0000-0000000000b2"


def _user(tx, user_id=USER):
    tx.execute(
        "INSERT INTO accounts (id, email, password_hash, created_at, updated_at) VALUES (?, ?, 'x', ?, ?)",
        (user_id, f"{user_id[-4:]}@example.test", tx.now_text, tx.now_text),
    )
    tx.execute("INSERT INTO users (id, email) VALUES (?, ?)", (user_id, f"{user_id[-4:]}@example.test"))


def _event(tx, event_id, user_id=USER, review_status="active"):
    tx.execute(
        "INSERT INTO events (id, user_id, title, start_datetime, review_status) VALUES (?, ?, 'T', ?, ?)",
        (event_id, user_id, tx.now_text, review_status),
    )


def _columns(db, table):
    return {r[1]: r for r in db.reader().execute(f"PRAGMA table_info({table})")}


def test_now_is_strictly_increasing(db):
    stamps = []
    for _ in range(50):
        with db.write() as tx:
            stamps.append(tx.now)
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)


def test_trigger_functions_exist_only_inside_a_write(db, tmp_path):
    """A connection without the data layer's functions cannot write a triggered table."""
    with db.write() as tx:
        _user(tx)
    other = sqlite3.connect(db.path)
    with pytest.raises(sqlite3.OperationalError, match="no such function"):
        other.execute("UPDATE users SET email = 'x@example.test' WHERE id = ?", (USER,))


def test_updated_at_is_the_transaction_time(db):
    with db.write() as tx:
        _user(tx)
    with db.write() as tx:
        tx.execute("UPDATE users SET display_name = 'Sam' WHERE id = ?", (USER,))
        expected = tx.now_text
    assert db.query_one("SELECT updated_at FROM users WHERE id = ?", (USER,))[0] == expected


def test_live_hints_are_deduplicated_and_sent_after_commit(db):
    from selko.db.bus import Bus

    bus = Bus()
    db.bus = bus

    async def go():
        sub = bus.subscribe(f"user:{USER}")

        def write():
            with db.write() as tx:
                _user(tx)
                for n in range(3):
                    _event(tx, f"00000000-0000-0000-0000-00000000e00{n}")

        await db.run(write)
        await asyncio.sleep(0.05)
        return [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]

    messages = asyncio.run(go())
    assert [(m["resource"], m["operation"]) for m in messages] == [("events", "INSERT")]


def test_rolled_back_write_sends_nothing(db):
    from selko.db.bus import WorkSignals

    signals = WorkSignals()
    db.signals = signals

    async def go():
        await signals.start()

        def write():
            with db.write() as tx:
                _user(tx)
                tx.execute(
                    "INSERT INTO emails (id, user_id, provider_message_id) VALUES (?, ?, 'm1')",
                    ("00000000-0000-0000-0000-0000000000e1", USER),
                )
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await db.run(write)
        await asyncio.sleep(0.05)
        return signals.event_for("email_pending").is_set()

    assert asyncio.run(go()) is False


def test_pending_email_wakes_the_email_worker(db):
    from selko.db.bus import WorkSignals

    signals = WorkSignals()
    db.signals = signals

    async def go():
        await signals.start()

        def write():
            with db.write() as tx:
                _user(tx)
                tx.execute(
                    "INSERT INTO emails (id, user_id, provider_message_id) VALUES (?, ?, 'm1')",
                    ("00000000-0000-0000-0000-0000000000e1", USER),
                )

        await db.run(write)
        await asyncio.wait_for(signals.event_for("email_pending").wait(), 2)
        return signals.status()["signals_sent"]

    assert asyncio.run(go()) == 1


def test_gmail_labels_set_the_flags(db):
    with db.write() as tx:
        _user(tx)
        tx.execute(
            "INSERT INTO emails (id, user_id, provider_message_id, provider_labels) VALUES (?, ?, 'm1', ?)",
            ("00000000-0000-0000-0000-0000000000e1", USER, '["SPAM","UNREAD"]'),
        )
    row = db.query_one("SELECT is_spam, is_unread, is_starred FROM emails")
    assert tuple(row) == (1, 1, 0)
    with db.write() as tx:
        tx.execute("UPDATE emails SET provider_labels = '[\"STARRED\"]'")
    row = db.query_one("SELECT is_spam, is_unread, is_starred FROM emails")
    assert tuple(row) == (0, 0, 1)


def test_calendar_work_item_must_belong_to_the_event_owner(db):
    with db.write() as tx:
        _user(tx)
        _user(tx, OTHER)
        _event(tx, "00000000-0000-0000-0000-00000000e001")
    with pytest.raises(InvariantViolation, match="owner does not match"):
        with db.write() as tx:
            tx.execute(
                "INSERT INTO calendar_work_items (id, user_id, event_id, action) VALUES (?, ?, ?, 'upsert')",
                ("00000000-0000-0000-0000-0000000000c1", OTHER, "00000000-0000-0000-0000-00000000e001"),
            )


def test_active_integration_gets_a_sync_state(db):
    with db.write() as tx:
        _user(tx)
        tx.execute(
            "INSERT INTO integrations (id, user_id, provider, status, access_token) VALUES (?, ?, 'gmail', 'active', 't')",
            ("00000000-0000-0000-0000-0000000000f1", USER),
        )
        now = tx.now_text
    row = db.query_one("SELECT next_poll_at, initial_watermark_at FROM email_sync_state")
    assert row[0] == now and row[1] < now


def test_pending_proposal_requires_an_active_event(db):
    """The deferred invariant: checked at commit, so the order of writes inside does not matter."""
    event = "00000000-0000-0000-0000-00000000e001"
    with db.write() as tx:
        _user(tx)
        _event(tx, event, review_status="pending_review")
        tx.execute(
            "INSERT INTO event_sources (id, event_id, source_origin, google_calendar_source_event_id, extracted_data) "
            "VALUES (?, ?, 'google_calendar', 'g1', '{}')",
            ("00000000-0000-0000-0000-0000000000s1", event),
        )
    proposal = (
        "INSERT INTO event_change_proposals (id, user_id, event_id, source_id, kind, status, change_set, event_snapshot_before) "
        "VALUES ('00000000-0000-0000-0000-0000000000p1', ?, ?, '00000000-0000-0000-0000-0000000000s1', 'material_update', 'pending', '{\"title\":\"X\"}', '{\"title\":\"T\"}')"
    )
    with pytest.raises(InvariantViolation, match="must have active review status"):
        with db.write() as tx:
            tx.execute(proposal, (USER, event))
    # Pending before active in the same transaction is fine, as Postgres deferral allowed.
    with db.write() as tx:
        tx.execute(proposal, (USER, event))
        tx.execute("UPDATE events SET review_status = 'active' WHERE id = ?", (event,))


def test_every_timestamp_default_writes_the_codec_format(db):
    """Text-compared leases misorder silently if any writer uses another format (risk E-2)."""
    import re

    pattern = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z")
    checked = 0
    for (table,) in db.reader().execute("SELECT name FROM sqlite_master WHERE type='table'"):
        for _cid, name, _type, _notnull, default, _pk in db.reader().execute(f"PRAGMA table_info({table})"):
            if default and "strftime" in default:
                value = db.reader().execute(f"SELECT {default}").fetchone()[0]
                assert pattern.fullmatch(value), (table, name, value)
                checked += 1
    assert checked >= 40
