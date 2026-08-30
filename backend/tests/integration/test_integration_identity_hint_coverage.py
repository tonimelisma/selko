"""Identity hints must actually be written for ordinary email (I4 groundwork).

`_load_identity_context` selected a `body_html` column that no longer
exists. PostgREST rejects the whole select for an unknown column, the failure
was swallowed by a debug-level `except`, and the email metadata came back empty
-- so `provider` and `thread_id` were empty for every email and no
`provider_thread` hint has ever been written. Production carries 14 identity
hints across 364 events, every one of them `join_url`, which are derived from
the event's own text rather than from that query.

A unit test could not see this: the query only fails against a real schema.
"""

from __future__ import annotations

import pytest

from selko.services.events import _load_identity_context


pytestmark = [pytest.mark.integration, pytest.mark.development]


def test_email_identity_metadata_actually_loads(admin_client, test_user_id):
    """The select must succeed against the real schema, not fail into {}."""
    email = admin_client.table("emails").insert({
        "user_id": test_user_id,
        "provider_message_id": "identity-metadata-probe",
        "subject": "Probe",
        "from_email": "sender@example.com",
        "date_sent": "2026-03-30T09:00:00Z",
        "snippet": "probe",
        "thread_id": "thread-probe-1",
        "email_provider": "gmail",
    }).execute().data[0]

    try:
        loaded, _components = _load_identity_context(admin_client, email["id"])
        assert loaded, (
            "identity metadata came back empty -- the select failed and the "
            "exception was swallowed, which is how provider_thread hints "
            "silently stopped being written"
        )
        assert loaded.get("email_provider") == "gmail"
        assert loaded.get("thread_id") == "thread-probe-1"
    finally:
        admin_client.table("emails").delete().eq("id", email["id"]).execute()


def test_ordinary_email_yields_a_provider_thread_hint(admin_client, test_user_id):
    """Every email has a thread, so every extracted event can carry this hint.

    It is the only identity signal available to mail that carries no invite,
    and therefore the only thing that can match a plain-text reschedule to the
    event it reschedules.
    """
    from selko.services.events import _identity_hints_for_event

    email = admin_client.table("emails").insert({
        "user_id": test_user_id,
        "provider_message_id": "identity-hint-probe",
        "subject": "Moved to the 11th",
        "from_email": "organiser@example.com",
        "date_sent": "2026-03-30T09:00:00Z",
        "snippet": "moved",
        "thread_id": "thread-probe-2",
        "email_provider": "outlook",
    }).execute().data[0]

    try:
        loaded, components = _load_identity_context(admin_client, email["id"])
        hints = _identity_hints_for_event(loaded, components, 0, {"title": "Standup"})
        kinds = {hint.kind for hint in hints}
        assert "provider_thread" in kinds, (
            f"plain-text mail produced no thread hint; kinds={kinds}"
        )
    finally:
        admin_client.table("emails").delete().eq("id", email["id"]).execute()
