"""The screenshot fixture must be created through real application write paths.

Runs the seed against a fresh SQLite data directory and reads what it wrote
(docs/specs/sqlite-single-process/05-verification.md §A.2 row 36).
"""

import importlib.util
from collections import Counter
from pathlib import Path

import pytest

from selko.db import runtime
from selko.db import accounts as account_rows

SCREENSHOT_EMAIL = "screenshots@selko.local"
SEED_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed_screenshot_data.py"


def _seed_module():
    spec = importlib.util.spec_from_file_location("seed_screenshot_data", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_screenshot_seed_has_complete_lane_and_work_state(db):
    runtime.use_database(db)
    try:
        _seed_module().do_seed(db)

        user = account_rows.get_account_by_email(db, SCREENSHOT_EMAIL)
        assert user is not None, "the seed must create the screenshot user"
        user_id = user["id"]

        def rows(table):
            return [db.schema.decode(table, dict(r)) for r in db.query(
                f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)
            )]

        assert len(rows("integrations")) == 2
        assert len(rows("email_folders")) == 2
        assert len(rows("emails")) == 5
        event_rows = rows("events")
        event_ids = [item["id"] for item in event_rows]
        assert len(event_rows) == 7
        marks = ", ".join("?" for _ in event_ids)
        sources = db.query(f"SELECT id FROM event_sources WHERE event_id IN ({marks})", event_ids)
        assert len(sources) == 8
        assert len(rows("event_change_proposals")) == 1
        work_items = rows("calendar_work_items")

        # Two owners, asserted separately: review_status owns the user's
        # decision, calendar_work_items owns delivery.
        assert Counter(item["review_status"] for item in event_rows) == Counter({
            "active": 4,        # 2 delivered, 1 queued, 1 failed
            "pending_review": 2,
            "rejected": 1,
        })
        assert Counter(item["status"] for item in work_items) == Counter({
            "succeeded": 2,
            "pending": 1,
            "blocked": 1,
            "superseded": 1,
        })

        # An event has at most one work item that is not superseded, so a
        # delivery state derived from "latest non-superseded item" is never
        # ambiguous.
        live_by_event = Counter(
            item["event_id"] for item in work_items if item["status"] != "superseded"
        )
        assert live_by_event and max(live_by_event.values()) == 1, live_by_event
        assert len(live_by_event) == 4

        proposal = rows("event_change_proposals")[0]
        assert proposal["status"] == "pending"
        assert proposal["kind"] == "material_update"
        q2 = db.query_one("SELECT review_status FROM events WHERE id = ?", (proposal["event_id"],))
        assert q2["review_status"] == "active"
    finally:
        runtime.use_database(None)
