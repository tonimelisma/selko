"""`selko.db.sender_rules` against a real SQLite database.

``ignore_sender_and_reject_pending`` has no Postgres test: in Postgres it raises
for any sender with a pending change (a 14-argument call to the 13-argument
``reject_event_change_proposal``). These are its first tests, including that
case. The sender-rule matching tests port integration/test_integration_events.py
``TestSenderRules``; the delete tests carry the ``reset_skipped_emails_for_sender_rule``
trigger's contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from selko.db import codec, errors, sender_rules
from selko.db import events as db_events
from selko.db.codec import new_id


def _rule(factory, user: str, action: str = "ignore", **extra) -> str:
    return factory._insert("sender_rules", {"id": new_id(), "user_id": user, "action": action, **extra})


def _new_lane_event(factory, user: str, from_email: str) -> tuple[str, str]:
    email = factory.email(user, from_email=from_email, processing_status="processed")
    event = factory.event(user, title=f"from {from_email}")
    factory.event_source(event, email)
    return event, email


def _pending_change(factory, user: str, from_email: str, snapshot: dict) -> tuple[str, str]:
    event = factory.event(user, review_status="active", title="Changed title", location="New room",
                          start_datetime="2026-12-02T09:00:00.000000Z", end_datetime="2026-12-02T10:00:00.000000Z",
                          description="changed")
    email = factory.email(user, from_email=from_email, processing_status="processed")
    source = factory.event_source(event, email, source_type="update")
    proposal = factory._insert("event_change_proposals", {
        "id": new_id(), "event_id": event, "user_id": user, "source_id": source, "kind": "material_update",
        "status": "pending", "change_set": {"kind": "material_update", "changes": [{"field": "title"}]},
        "event_snapshot_before": snapshot})
    return event, proposal


def _rules(db, user: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT sender_email, sender_domain, action FROM sender_rules WHERE user_id = ? ORDER BY created_at", (user,))]


# --- ignore_sender_and_reject_pending -----------------------------------------


# Validates: SEL-186
def test_ignore_rejects_new_and_discards_pending_changes(db, factory):
    """The case that raises in Postgres today: the sender has a pending change."""
    user = factory.user()
    new_event, _ = _new_lane_event(factory, user, "spam@shop.example")
    changed, proposal = _pending_change(factory, user, "spam@shop.example", {
        "title": "Original title", "start_datetime": "2026-12-01T17:00:00Z", "end_datetime": "",
        "all_day": "f", "location": None, "importance": "fyi", "review_status": "active"})
    kept, _ = _new_lane_event(factory, user, "friend@shop.example")

    result = sender_rules.ignore_sender_and_reject_pending(db, user, sender_email="spam@shop.example")

    assert result == {"rejected_new": 1, "discarded_changes": 1}
    assert _rules(db, user) == [{"sender_email": "spam@shop.example", "sender_domain": None, "action": "ignore"}]
    assert db_events.get(db, user, new_event)["review_status"] == "rejected"
    assert db_events.get(db, user, kept)["review_status"] == "pending_review"

    p = factory.row("event_change_proposals", proposal)
    assert (p["status"], p["resolution_reason"]) == ("rejected", "repair_operator")
    restored = db_events.get(db, user, changed)
    assert restored["review_status"] == "active", "discarding a change does not change the decision"
    assert restored["title"] == "Original title"
    assert restored["start_datetime"] == "2026-12-01T17:00:00.000000Z"
    assert restored["end_datetime"] == "2026-12-02T10:00:00.000000Z", "an empty snapshot value keeps the current one"
    assert restored["location"] is None, "a present snapshot key is restored, even null"
    assert restored["description"] == "changed", "an absent snapshot key keeps the current value"
    assert (restored["all_day"], restored["importance"]) == (False, "fyi")


# Validates: SEL-186
def test_ignore_by_domain_matches_suffix_case_sensitively(db, factory):
    user = factory.user()
    matching, _ = _new_lane_event(factory, user, "news@example.edu")
    other_case, _ = _new_lane_event(factory, user, "news@EXAMPLE.edu")
    lookalike, _ = _new_lane_event(factory, user, "news@notexample.edu")
    sub, _ = _new_lane_event(factory, user, "news@mail.example.edu")
    result = sender_rules.ignore_sender_and_reject_pending(db, user, sender_domain="example.edu")
    assert result == {"rejected_new": 1, "discarded_changes": 0}
    assert db_events.get(db, user, matching)["review_status"] == "rejected"
    for event in (other_case, lookalike, sub):
        assert db_events.get(db, user, event)["review_status"] == "pending_review"
    assert _rules(db, user) == [{"sender_email": None, "sender_domain": "example.edu", "action": "ignore"}]


def test_email_and_domain_together_record_the_email_rule_and_match_both(db, factory):
    user = factory.user()
    exact, _ = _new_lane_event(factory, user, "a@x.example")
    by_domain, _ = _new_lane_event(factory, user, "b@y.example")
    result = sender_rules.ignore_sender_and_reject_pending(db, user, "a@x.example", "y.example")
    assert result["rejected_new"] == 2
    assert {db_events.get(db, user, e)["review_status"] for e in (exact, by_domain)} == {"rejected"}
    assert _rules(db, user) == [{"sender_email": "a@x.example", "sender_domain": None, "action": "ignore"}]


def test_ignore_is_idempotent_and_turns_an_auto_approve_rule_into_ignore(db, factory):
    user = factory.user()
    _rule(factory, user, action="auto_approve", sender_email="s@x.example")
    _new_lane_event(factory, user, "s@x.example")
    assert sender_rules.ignore_sender_and_reject_pending(db, user, "s@x.example")["rejected_new"] == 1
    assert sender_rules.ignore_sender_and_reject_pending(db, user, "s@x.example") == {
        "rejected_new": 0, "discarded_changes": 0}
    assert _rules(db, user) == [{"sender_email": "s@x.example", "sender_domain": None, "action": "ignore"}]


# Validates: SEL-186
def test_ignore_never_touches_another_users_rows(db, factory):
    user, other = factory.user(), factory.user()
    theirs, _ = _new_lane_event(factory, other, "s@x.example")
    _, their_proposal = _pending_change(factory, other, "s@x.example", {"title": "t"})
    assert sender_rules.ignore_sender_and_reject_pending(db, user, "s@x.example") == {
        "rejected_new": 0, "discarded_changes": 0}
    assert db_events.get(db, other, theirs)["review_status"] == "pending_review"
    assert factory.row("event_change_proposals", their_proposal)["status"] == "pending"
    assert _rules(db, other) == []


def test_ignore_leaves_approved_events_and_resolved_proposals(db, factory):
    user = factory.user()
    email = factory.email(user, from_email="s@x.example")
    approved = factory.event(user, review_status="active")
    factory.event_source(approved, email)
    assert sender_rules.ignore_sender_and_reject_pending(db, user, "s@x.example")["rejected_new"] == 0
    assert db_events.get(db, user, approved)["review_status"] == "active"


def test_ignore_requires_a_sender_and_a_user(db, factory):
    user = factory.user()
    with pytest.raises(errors.InvalidArgument, match="sender_email or sender_domain required"):
        sender_rules.ignore_sender_and_reject_pending(db, user)
    with pytest.raises(errors.NotOwned, match="not authenticated"):
        sender_rules.ignore_sender_and_reject_pending(db, None, "s@x.example")
    assert _rules(db, user) == []


# Validates: SEL-186
def test_ignore_is_all_or_nothing(db, factory):
    """A failure discarding a change rolls back the rule and the New-lane rejections too."""
    user = factory.user()
    new_event, _ = _new_lane_event(factory, user, "s@x.example")
    # The snapshot's start time cannot be cast, as Postgres's ::timestamptz would refuse it.
    _pending_change(factory, user, "s@x.example", {"title": "t", "start_datetime": "not a time"})
    with pytest.raises(errors.InvalidArgument, match="timestamp"):
        sender_rules.ignore_sender_and_reject_pending(db, user, "s@x.example")
    assert _rules(db, user) == []
    assert db_events.get(db, user, new_event)["review_status"] == "pending_review"


# --- matching (services/events.py check_sender_rules) ---------------------------


def test_check_sender_rules_exact_email(db, factory):
    user = factory.user()
    _rule(factory, user, action="auto_approve", sender_email="school@example.edu")
    assert sender_rules.matching(db, user, "school@example.edu")["action"] == "auto_approve"


# Validates: SEL-183
def test_check_sender_rules_domain_match(db, factory):
    user = factory.user()
    _rule(factory, user, action="ignore", sender_domain="example.edu")
    assert sender_rules.matching(db, user, "newsletter@example.edu")["action"] == "ignore"


# Validates: SEL-183
def test_exact_email_wins_over_domain_and_matching_is_per_user(db, factory):
    user, other = factory.user(), factory.user()
    _rule(factory, user, action="ignore", sender_domain="example.edu")
    _rule(factory, user, action="auto_approve", sender_email="school@example.edu")
    assert sender_rules.matching(db, user, "school@example.edu")["action"] == "auto_approve"
    assert sender_rules.matching(db, other, "school@example.edu") is None
    assert sender_rules.matching(db, user, "school@EXAMPLE.edu") is None, "= is case-sensitive"


def test_check_sender_rules_no_match(db, factory):
    user = factory.user()
    assert sender_rules.matching(db, user, "unknown@random.com") is None
    assert sender_rules.matching(db, user, "no-at-sign") is None


# --- delete_rule (reset_skipped_emails_for_sender_rule) -------------------------


def _ago(days: float) -> str:
    return codec.to_timestamp(datetime.now(UTC) - timedelta(days=days))  # type: ignore[return-value]


# Validates: SEL-187
def test_deleting_ignore_rule_requeues_recent_skipped_mail(db, factory, monkeypatch):
    user = factory.user()
    rule = _rule(factory, user, sender_email="s@x.example")
    recent = factory.email(user, from_email="s@x.example", processing_status="skipped", date_sent=_ago(2),
                           attempts=3, processing_error="ignored")
    old = factory.email(user, from_email="s@x.example", processing_status="skipped", date_sent=_ago(31))
    undated = factory.email(user, from_email="s@x.example", processing_status="skipped")
    other_sender = factory.email(user, from_email="t@x.example", processing_status="skipped", date_sent=_ago(1))
    processed = factory.email(user, from_email="s@x.example", processing_status="processed", date_sent=_ago(1))
    signals: list[str] = []
    monkeypatch.setattr(db.signals, "signal", signals.append)

    assert sender_rules.delete_rule(db, user, rule) is True

    row = factory.row("emails", recent)
    assert (row["processing_status"], row["attempts"], row["processing_error"], row["locked_by"]) == (
        "pending", 0, None, None)
    for email, status in ((old, "skipped"), (undated, "skipped"), (other_sender, "skipped"), (processed, "processed")):
        assert factory.row("emails", email)["processing_status"] == status
    assert _rules(db, user) == []
    assert "email_pending" in signals, "the requeue wakes the email worker"


def test_deleting_a_domain_rule_requeues_by_case_sensitive_suffix(db, factory):
    user = factory.user()
    rule = _rule(factory, user, sender_domain="x.example")
    match = factory.email(user, from_email="a@x.example", processing_status="skipped", date_sent=_ago(1))
    upper = factory.email(user, from_email="a@X.EXAMPLE", processing_status="skipped", date_sent=_ago(1))
    sender_rules.delete_rule(db, user, rule)
    assert factory.row("emails", match)["processing_status"] == "pending"
    assert factory.row("emails", upper)["processing_status"] == "skipped"


# Validates: SEL-187
def test_deleting_an_auto_approve_rule_requeues_nothing(db, factory):
    user = factory.user()
    rule = _rule(factory, user, action="auto_approve", sender_email="s@x.example")
    skipped = factory.email(user, from_email="s@x.example", processing_status="skipped", date_sent=_ago(1))
    assert sender_rules.delete_rule(db, user, rule) is True
    assert factory.row("emails", skipped)["processing_status"] == "skipped"


def test_delete_rule_is_owner_only(db, factory):
    user, other = factory.user(), factory.user()
    rule = _rule(factory, user, sender_email="s@x.example")
    skipped = factory.email(user, from_email="s@x.example", processing_status="skipped", date_sent=_ago(1))
    assert sender_rules.delete_rule(db, other, rule) is False
    assert len(_rules(db, user)) == 1
    assert factory.row("emails", skipped)["processing_status"] == "skipped"
    assert sender_rules.delete_rule(db, user, new_id()) is False
