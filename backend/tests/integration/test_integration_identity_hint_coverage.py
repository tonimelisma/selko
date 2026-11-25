"""Identity hints must actually be written for ordinary email (I4 groundwork).

`_load_identity_context` once selected a `body_html` column that no longer
existed. PostgREST rejected the whole select for the unknown column, the
failure was swallowed by a debug-level `except`, and the email metadata came
back empty -- so `provider` and `thread_id` were empty for every email and no
`provider_thread` hint was ever written. Production carried 14 identity hints
across 364 events, every one `join_url`.

A mocked read could not see this: the query only fails against a real schema.
These run on a real SQLite database.
"""

from __future__ import annotations

from selko.services.events import _identity_hints_for_event, _load_identity_context


def test_email_identity_metadata_actually_loads(db, factory):
    """The read must succeed against the real schema, not fail into {}."""
    user = factory.user()
    email = factory.email(user, subject="Probe", from_email="sender@example.com",
                          date_sent="2026-03-30T09:00:00.000000Z", snippet="probe",
                          thread_id="thread-probe-1", email_provider="gmail")

    loaded, _components = _load_identity_context(db, email)

    assert loaded, (
        "identity metadata came back empty -- the select failed and the "
        "exception was swallowed, which is how provider_thread hints "
        "silently stopped being written"
    )
    assert loaded.get("email_provider") == "gmail"
    assert loaded.get("thread_id") == "thread-probe-1"


def test_ordinary_email_yields_a_provider_thread_hint(db, factory):
    """Every email has a thread, so every extracted event can carry this hint.

    It is the only identity signal available to mail that carries no invite,
    and therefore the only thing that can match a plain-text reschedule to the
    event it reschedules.
    """
    user = factory.user()
    email = factory.email(user, subject="Moved to the 11th", from_email="organiser@example.com",
                          date_sent="2026-03-30T09:00:00.000000Z", snippet="moved",
                          thread_id="thread-probe-2", email_provider="outlook")

    loaded, components = _load_identity_context(db, email)
    hints = _identity_hints_for_event(loaded, components, 0, {"title": "Standup"})

    kinds = {hint.kind for hint in hints}
    assert "provider_thread" in kinds, f"plain-text mail produced no thread hint; kinds={kinds}"
