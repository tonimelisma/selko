"""python -m selko.admin: migrate, delete-account, seed-demo."""

from __future__ import annotations

import json
import sqlite3

import pytest

from selko import admin
from selko.db import runtime
from selko.services import accounts


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SELKO_DATA_DIR", str(tmp_path))
    runtime.close_database()
    yield tmp_path
    runtime.close_database()


def test_migrate_creates_the_database(data_dir):
    assert admin.main(["migrate"]) == 0
    assert (data_dir / "selko.db").exists()


def test_seed_demo_is_refused_without_the_flag(data_dir, monkeypatch, capsys):
    monkeypatch.delenv("SELKO_ALLOW_DEMO_SEED", raising=False)
    assert admin.main(["seed-demo", "ops@example.test"]) == 2


def test_seed_demo_then_delete_account(data_dir, monkeypatch, capsys):
    monkeypatch.setenv("SELKO_ALLOW_DEMO_SEED", "1")
    admin.main(["migrate"])
    account = accounts.sign_up(runtime.get_database(), "ops@example.test", "secret-pw")
    capsys.readouterr()
    assert admin.main(["seed-demo", "ops@example.test"]) == 0
    seeded = json.loads(capsys.readouterr().out)
    stored = list((data_dir / "attachments" / account["id"]).rglob("ticket.pdf"))
    assert len(stored) == 1 and stored[0].read_bytes().startswith(b"%PDF")
    # Never into an account that has events.
    with pytest.raises(Exception, match="already has events"):
        admin.main(["seed-demo", "ops@example.test"])
    assert admin.main(["delete-account", account["id"]]) == 0
    conn = sqlite3.connect(data_dir / "selko.db")
    assert conn.execute("SELECT count(*) FROM events WHERE id = ?", (seeded["event_id"],)).fetchone()[0] == 0
    assert not (data_dir / "attachments" / account["id"]).exists()
    assert admin.main(["delete-account", account["id"]]) == 1
    assert admin.main(["delete-account", "not-a-uuid"]) == 2
