"""The Postgres -> SQLite importer (04-data-cutover.md §B) against a real Postgres.

The source is a throwaway Postgres container started for this module and
loaded from selko_import/fixture (the frozen pre-move schema plus synthetic
rows) -- the same source the image lane imports. SELKO_IMPORT_TEST_POSTGRES_URL
(an admin URL) uses an existing server instead. Without Docker or that URL the
tests fail: they are the only proof the cutover tool works, so they never skip.
Besides the happy path, each check is shown to fail when it should.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "selko_import" / "fixture"
POSTGRES_IMAGE = os.environ.get("SELKO_FIXTURE_POSTGRES_IMAGE", "public.ecr.aws/docker/library/postgres:17")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def postgres_admin_url():
    """An admin URL on a Postgres server this module may create databases on."""
    url = os.environ.get("SELKO_IMPORT_TEST_POSTGRES_URL")
    if url:
        yield url
        return
    import asyncio

    import asyncpg

    name = f"selko-import-test-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=fixture",
         "-p", f"127.0.0.1:{port}:5432", POSTGRES_IMAGE],
        check=True, capture_output=True,
    )
    try:
        url = f"postgresql://postgres:fixture@127.0.0.1:{port}/postgres"

        async def ready() -> bool:
            try:
                conn = await asyncpg.connect(url, timeout=2)
            except Exception:
                return False
            await conn.close()
            return True

        deadline = time.monotonic() + 90
        while not asyncio.run(ready()):
            if time.monotonic() > deadline:
                raise RuntimeError("the fixture Postgres did not accept connections within 90 s")
            time.sleep(1)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def importer():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from selko_import import core

    return core


def test_import_carries_every_table_and_verifies(importer, fixture_source, tmp_path):
    target = tmp_path / "selko.db"
    report = importer.import_sync(fixture_source, target, progress=lambda _: None)
    assert report.ok and target.exists()
    carried = {t.table for t in report.tables}
    assert carried == set(importer.COLUMNS) - importer.SKIPPED
    conn = sqlite3.connect(target)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # Triggers are back after the load, and the database migrates as a no-op.
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()[0] >= 37
    from selko.db import migrate

    assert migrate(target) == []


def test_a_corrupted_cell_fails_verification_and_replaces_nothing(importer, fixture_source, tmp_path, monkeypatch):
    original = importer._typed
    hit = {"done": False}

    def corrupt(row, kinds):
        out = list(original(row, kinds))
        if not hit["done"] and "X" in kinds:
            i = kinds.index("X")
            if out[i] is not None:
                out[i] = out[i] + "!"
                hit["done"] = True
        return tuple(out)

    monkeypatch.setattr(importer, "_typed", corrupt)
    target = tmp_path / "selko.db"
    with pytest.raises(importer.ImportError_) as exc:
        importer.import_sync(fixture_source, target, progress=lambda _: None)
    assert hit["done"], "the fixture database has no text cell to corrupt"
    assert exc.value.exit_code == 5
    assert not target.exists()


def test_schema_drift_is_refused(importer, fixture_source, tmp_path, monkeypatch):
    drifted = {t: list(c) for t, c in importer.COLUMNS.items()}
    drifted["events"] = drifted["events"] + [["column_the_source_lacks", "X"]]
    monkeypatch.setattr(importer, "COLUMNS", drifted)
    with pytest.raises(importer.ImportError_) as exc:
        importer.import_sync(fixture_source, tmp_path / "selko.db", progress=lambda _: None)
    assert exc.value.exit_code == 3


def test_both_sides_hash_identically(importer, postgres_admin_url):
    """The Python row hash equals Postgres's for the same cells (the formula in 04 §A.2)."""
    import asyncio

    import asyncpg

    async def pg():
        conn = await asyncpg.connect(postgres_admin_url)
        try:
            row = await conn.fetchrow(
                "SELECT ('x'||substr(encode(sha256(convert_to('S3:abc'||'N'||'S2:ä1','UTF8')),'hex'),1,15))::bit(60)::bigint"
            )
            return int(row[0])
        finally:
            await conn.close()

    assert asyncio.run(pg()) == importer.row_hash(["abc", None, "ä1"])


@pytest.fixture
def fixture_source(postgres_admin_url):
    """A fresh database holding selko_import/fixture; dropped afterwards."""
    import asyncio

    import asyncpg

    name = f"fixture_{uuid.uuid4().hex[:12]}"
    sql = (FIXTURE_DIR / "schema.sql").read_text() + (FIXTURE_DIR / "data.sql").read_text()
    url = postgres_admin_url.rsplit("/", 1)[0] + "/" + name

    async def setup():
        admin = await asyncpg.connect(postgres_admin_url)
        await admin.execute(f"CREATE DATABASE {name}")
        await admin.close()
        conn = await asyncpg.connect(url)
        await conn.execute(sql)
        await conn.close()

    async def teardown():
        admin = await asyncpg.connect(postgres_admin_url)
        await admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        await admin.close()

    asyncio.run(setup())
    try:
        yield url
    finally:
        asyncio.run(teardown())


def _run(url, sql):
    import asyncio

    import asyncpg

    async def go():
        conn = await asyncpg.connect(url)
        await conn.execute(sql)
        await conn.close()

    asyncio.run(go())


def test_the_fixture_imports_and_its_account_signs_in(importer, fixture_source, tmp_path):
    from selko.db import Database
    from selko.services import accounts

    target = tmp_path / "selko.db"
    report = importer.import_sync(fixture_source, target, progress=lambda _: None)
    assert report.ok and report.accounts == 1  # the deleted auth user is not carried
    db = Database(target)
    try:
        assert db.query_one("SELECT count(*) FROM global_limits")[0] == 3  # the source's, not seed + source
        keys = accounts.TokenKeys(current="k" * 64)
        signed = accounts.sign_in(db, keys, "FIXTURE@example.test", "fixture-password")
        assert signed.user["email"] == "fixture@example.test"
        with pytest.raises(accounts.AuthError):
            accounts.sign_in(db, keys, "gone@example.test", "fixture-password")
        statuses = sorted(r[0] for r in db.query("SELECT review_status FROM events"))
        assert statuses == ["active", "pending_review"]
    finally:
        db.close()


def test_a_row_the_target_refuses_is_exit_5_and_leaves_nothing(importer, fixture_source, tmp_path):
    _run(fixture_source, "UPDATE public.events SET importance = 'urgent'")
    target = tmp_path / "selko.db"
    with pytest.raises(importer.ImportError_) as exc:
        importer.import_sync(fixture_source, target, progress=lambda _: None)
    assert exc.value.exit_code == 5 and "events" in str(exc.value)
    assert list(tmp_path.iterdir()) == []


# --- the removed Google Photos ingestion: its data is refused, never dropped ---

FIXTURE_USER = "11111111-1111-4111-8111-111111111111"
FIXTURE_INTEGRATION = "33333333-3333-4333-8333-333333333333"


@pytest.mark.parametrize(
    ("what", "sql"),
    [
        ("photos rows", f"INSERT INTO public.photos (user_id, google_photo_id) VALUES ('{FIXTURE_USER}', 'g-1')"),
        ("scheduled_tasks rows",
         f"INSERT INTO public.scheduled_tasks (user_id, task_type) VALUES ('{FIXTURE_USER}', 'photo_fetch')"),
        ("google_photos integrations",
         f"INSERT INTO public.integrations (user_id, provider, access_token) VALUES ('{FIXTURE_USER}', 'google_photos', 't')"),
        ("integrations with last_photo_sync_at",
         f"UPDATE public.integrations SET last_photo_sync_at = now() WHERE id = '{FIXTURE_INTEGRATION}'"),
        ("google_photos event sources",
         "UPDATE public.event_sources SET source_origin = 'google_photos' "
         "WHERE id = '77777777-7777-4777-8777-777777777771'"),
    ],
)
def test_data_of_the_removed_photo_ingestion_is_refused_not_dropped(importer, fixture_source, tmp_path, what, sql):
    _run(fixture_source, sql)
    target = tmp_path / "selko.db"
    with pytest.raises(importer.ImportError_) as exc:
        importer.import_sync(fixture_source, target, progress=lambda _: None)
    assert exc.value.exit_code == 3
    assert what in str(exc.value)
    assert list(tmp_path.iterdir()) == []


def test_the_removed_photo_tables_and_column_are_not_carried(importer, fixture_source, tmp_path):
    target = tmp_path / "selko.db"
    report = importer.import_sync(fixture_source, target, progress=lambda _: None)
    assert report.ok
    conn = sqlite3.connect(target)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not {"photos", "scheduled_tasks"} & tables
    columns = {r[1] for r in conn.execute("PRAGMA table_info(integrations)")}
    assert "last_photo_sync_at" not in columns
    assert conn.execute("SELECT count(*) FROM integrations").fetchone()[0] == 1
