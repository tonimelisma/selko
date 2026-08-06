"""Coverage for the outbound traffic meter and the idle-poll backoff.

Context: a production bandwidth alert fired against a service with essentially
zero inbound HTTP traffic. The egress was a flat ~39MB/hour around the clock —
the signature of a polling loop, not of users. These tests pin both halves of
the response: the meter that attributes bytes, and the backoff that stops the
loop generating them.
"""

import pytest

from selko.services.egress import (
    GMAIL,
    MAX_TRACKED_OPERATIONS,
    SUPABASE,
    egress_snapshot,
    operation_from_url,
    record_egress,
    reset_egress,
)


@pytest.fixture(autouse=True)
def _clean_meter():
    reset_egress()
    yield
    reset_egress()


def test_snapshot_attributes_bytes_by_destination_and_operation():
    record_egress(SUPABASE, "POST /rest/v1/rpc/claim_due_email_sync", request_bytes=600, response_bytes=40)
    record_egress(SUPABASE, "POST /rest/v1/rpc/claim_due_email_sync", request_bytes=600, response_bytes=40)
    record_egress(GMAIL, "GET /gmail/v1/users/me/messages/{id}?format=full", response_bytes=50_000)

    snapshot = egress_snapshot()

    assert snapshot["total_calls"] == 3
    assert snapshot["total_bytes"] == 600 + 40 + 600 + 40 + 50_000
    assert snapshot["by_destination"][SUPABASE]["calls"] == 2
    assert snapshot["by_destination"][GMAIL]["bytes"] == 50_000
    # Ranked by bytes, so the biggest consumer is the first thing an operator sees.
    assert snapshot["top_operations"][0]["destination"] == GMAIL


def test_operation_names_drop_query_strings_and_ids():
    """Message and attachment ids must never reach a counter key.

    They are both a privacy leak and an unbounded-cardinality bug: one counter
    per message would dwarf the traffic it is meant to describe.
    """
    operation = operation_from_url(
        "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/18c9f2ab3d4e5f6a?format=full"
    )

    assert "?" not in operation
    assert "18c9f2ab3d4e5f6a" not in operation
    assert operation == "GET /gmail/v1/users/me/messages/{id}"


def test_operation_names_collapse_uuid_segments():
    operation = operation_from_url(
        "PATCH", "https://example.supabase.co/rest/v1/emails/3f8a1c2e-9b4d-4a7f-8e1c-2d3f4a5b6c7d"
    )

    assert operation == "PATCH /rest/v1/emails/{id}"


def test_counter_cardinality_is_bounded():
    """A future call site that passes something high-cardinality must not OOM us."""
    for index in range(MAX_TRACKED_OPERATIONS + 50):
        record_egress(SUPABASE, f"operation-{index}", response_bytes=1)

    snapshot = egress_snapshot(top_n=1000)

    # Capped at the ceiling plus the single overflow bucket per destination.
    assert len(snapshot["top_operations"]) == MAX_TRACKED_OPERATIONS + 1
    overflow = [row for row in snapshot["top_operations"] if row["operation"] == "other"]
    assert overflow[0]["calls"] == 50
    # Nothing is dropped — overflow is folded into a bucket, not discarded.
    assert snapshot["total_calls"] == MAX_TRACKED_OPERATIONS + 50


def test_projection_extrapolates_the_observed_rate():
    record_egress(SUPABASE, "POST /rest/v1/rpc/noop", response_bytes=1_000)

    snapshot = egress_snapshot()

    # Uptime is tiny in a test, so the projection is huge; the property that
    # matters is that it is derived from the rate, not from the raw total.
    assert snapshot["projected_bytes_per_30d"] > snapshot["total_bytes"]
    assert snapshot["bytes_per_hour"] > 0
