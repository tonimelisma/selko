"""The C2 hint writer and the hint read-set fence, on a real SQLite database."""

from hashlib import md5

from selko.db import events as db_events

EMPTY = md5(b"").hexdigest()


def _claimed(factory, user, **extra):
    return factory.email(user, processing_status="processing", locked_by="identity-worker",
                         locked_until="2099-01-01T00:00:00.000000Z", lock_generation=1, **extra)


def test_commit_writes_identity_hints_in_same_transaction(db, factory):
    user = factory.user()
    email_id = _claimed(factory, user, email_provider="gmail", thread_id="thread-c2",
                        date_sent="2035-01-01T09:00:00.000000Z")
    value_hash = "a" * 64
    decision = {
        "action": "create",
        "event_id": None,
        "intent": "no_change",
        "window_start": "2035-01-02T00:00:00Z",
        "window_end": "2035-01-03T00:00:00Z",
        "expected_fingerprint": EMPTY,
        "hint_keys": [f"ical_uid|{value_hash}|"],
        "expected_hint_fingerprint": EMPTY,
        "hints": [{
            "kind": "ical_uid", "value_hash": value_hash, "recurrence_id": "",
            "strength": "authoritative", "sequence": 1, "dtstamp": "2035-01-01T12:00:00Z",
        }],
        "fields": {
            "title": "C2 identity event",
            "start_datetime": "2035-01-02T10:00:00Z",
            "end_datetime": "2035-01-02T11:00:00Z",
            "review_status": "pending_review",
        },
        "source": {"email_id": email_id, "extracted_data": {}},
    }

    result = db_events.commit_email_extraction(db, email_id, "identity-worker", 1, [decision], "processed")

    assert result["applied"] == 1
    event_id = result["event_ids"][0]
    hint = db.query_one(
        "SELECT event_id, source_email_id, kind, value_hash, sequence, dtstamp "
        "FROM event_identity_hints WHERE event_id = ?", (event_id,))
    assert hint["event_id"] == event_id
    assert hint["source_email_id"] == email_id
    assert (hint["kind"], hint["value_hash"], hint["sequence"]) == ("ical_uid", value_hash, 1)
    assert hint["dtstamp"].startswith("2035-01-01T12:00:00")


def test_hint_lookup_is_part_of_the_commit_fence(db, factory):
    """A hint naming an event outside the band still fences the decision."""
    user = factory.user()
    existing_email = factory.email(user, processing_status="processed")
    email_id = _claimed(factory, user)
    existing_event = factory.event(user, title="outside local day",
                                   start_datetime="2036-02-02T10:00:00.000000Z",
                                   end_datetime="2036-02-02T11:00:00.000000Z")
    value_hash = "b" * 64
    factory._insert("event_identity_hints", {
        "id": "00000000-0000-4000-8000-000000000001", "user_id": user, "event_id": existing_event,
        "source_email_id": existing_email, "kind": "join_url", "value_hash": value_hash,
        "strength": "supporting",
    })
    decision = {
        "action": "create",
        "event_id": None,
        "intent": "no_change",
        "window_start": "2036-02-03T00:00:00Z",
        "window_end": "2036-02-04T00:00:00Z",
        "expected_fingerprint": EMPTY,
        "hint_keys": [f"join_url|{value_hash}|"],
        # Computed as if the hint named nothing: stale.
        "expected_hint_fingerprint": EMPTY,
        "hints": [{"kind": "join_url", "value_hash": value_hash, "strength": "supporting"}],
        "fields": {
            "title": "must be fenced",
            "start_datetime": "2036-02-03T10:00:00Z",
            "end_datetime": "2036-02-03T11:00:00Z",
            "review_status": "pending_review",
        },
        "source": {"email_id": email_id, "extracted_data": {}},
    }

    result = db_events.commit_email_extraction(db, email_id, "identity-worker", 1, [decision], "processed")

    assert result["conflict"] is True
    assert db.query_one("SELECT count(*) FROM events WHERE title = 'must be fenced'")[0] == 0
    # With the producer's real value the same decision commits.
    decision["expected_hint_fingerprint"] = db_events.hint_fingerprint(db, user, decision["hint_keys"])
    assert db_events.commit_email_extraction(
        db, email_id, "identity-worker", 1, [decision], "processed")["applied"] == 1
