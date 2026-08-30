"""Contracts for the ICS backfill (I5 of event-identity-reach)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from backfill_calendar_components import find_candidates  # noqa: E402


def _client(attachments: list[dict], existing_component_emails: list[str]) -> MagicMock:
    client = MagicMock()

    def table(name):
        handle = MagicMock()
        if name == "attachments":
            handle.select.return_value.execute.return_value.data = attachments
        elif name == "email_calendar_components":
            handle.select.return_value.in_.return_value.execute.return_value.data = [
                {"email_id": email_id} for email_id in existing_component_emails
            ]
        return handle

    client.table.side_effect = table
    return client


def test_finds_ics_attachments_with_no_component():
    client = _client(
        [{"id": "a1", "email_id": "e1", "filename": "invite.ics", "mime_type": "application/octet-stream"}],
        [],
    )
    assert [row["id"] for row in find_candidates(client)] == ["a1"]


def test_detects_ics_by_mime_type_as_well_as_extension():
    """Providers send invites with a generic filename and a calendar MIME, and
    with an .ics filename and a generic MIME. Either is an invite."""
    client = _client(
        [
            {"id": "a1", "email_id": "e1", "filename": "attachment", "mime_type": "text/calendar"},
            {"id": "a2", "email_id": "e2", "filename": "meeting.ICS", "mime_type": "application/octet-stream"},
        ],
        [],
    )
    assert {row["id"] for row in find_candidates(client)} == {"a1", "a2"}


def test_skips_emails_that_already_have_a_component():
    """The backfill only ever adds; it must not touch a parsed email."""
    client = _client(
        [
            {"id": "a1", "email_id": "e1", "filename": "invite.ics", "mime_type": ""},
            {"id": "a2", "email_id": "e2", "filename": "invite.ics", "mime_type": ""},
        ],
        ["e1"],
    )
    assert [row["id"] for row in find_candidates(client)] == ["a2"]


def test_ignores_non_calendar_attachments():
    client = _client(
        [{"id": "a1", "email_id": "e1", "filename": "agenda.pdf", "mime_type": "application/pdf"}],
        [],
    )
    assert find_candidates(client) == []


def test_no_attachments_is_not_an_error():
    assert find_candidates(_client([], [])) == []


def test_apply_requires_an_explicit_environment():
    """Production must never be reachable by default."""
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts" / "backfill_calendar_components.py"
    result = subprocess.run(
        [sys.executable, str(script), "--apply"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "--environment" in result.stderr
