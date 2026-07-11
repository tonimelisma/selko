"""Unit tests for deterministic event field diffs and LLM changeset gating."""

from selko.services.event_diff import (
    EventChangeSet,
    FieldChange,
    apply_asserted_fields,
    baseline_from_gcal_event,
    compute_change_set,
    gate_change_set,
)


class TestComputeChangeSet:
    def test_noop_identical(self):
        baseline = {
            "title": "Team Sync",
            "start_datetime": "2026-07-17T15:00:00-04:00",
            "end_datetime": "2026-07-17T16:00:00-04:00",
            "all_day": False,
            "location": "Zoom",
            "description": "Weekly",
        }
        proposed = {
            "title": "Team Sync",
            "start_datetime": "2026-07-17T19:00:00Z",
            "end_datetime": "2026-07-17T20:00:00Z",
            "all_day": False,
            "location": "zoom",
            "description": "Weekly",
        }
        result = compute_change_set(baseline, proposed)
        assert result.kind == "noop"
        assert result.changes == []

    def test_missing_proposed_fields_not_clears(self):
        baseline = {
            "title": "Dentist",
            "start_datetime": "2026-08-01T14:00:00Z",
            "location": "123 Main St",
            "description": "Cleaning",
        }
        proposed = {
            "title": "Dentist",
            "start_datetime": "2026-08-01T14:00:00Z",
        }
        result = compute_change_set(baseline, proposed)
        assert result.kind == "noop"

    def test_time_change_is_material(self):
        baseline = {
            "title": "Dentist",
            "start_datetime": "2026-08-01T14:00:00Z",
            "end_datetime": "2026-08-01T15:00:00Z",
        }
        proposed = {
            "title": "Dentist",
            "start_datetime": "2026-08-01T15:00:00Z",
            "end_datetime": "2026-08-01T16:00:00Z",
        }
        result = compute_change_set(baseline, proposed)
        assert result.kind == "material_update"
        fields = {c.field for c in result.changes}
        assert "start_datetime" in fields
        assert "end_datetime" in fields

    def test_location_only_is_material(self):
        baseline = {
            "title": "Lunch",
            "start_datetime": "2026-08-01T12:00:00Z",
            "location": "Cafe A",
        }
        proposed = {
            "title": "Lunch",
            "start_datetime": "2026-08-01T12:00:00Z",
            "location": "Cafe B",
        }
        result = compute_change_set(baseline, proposed)
        assert result.kind == "material_update"
        assert result.changes[0].field == "location"

    def test_description_only_is_enrichment(self):
        baseline = {
            "title": "Lunch",
            "start_datetime": "2026-08-01T12:00:00Z",
            "description": "Old",
        }
        proposed = {
            "title": "Lunch",
            "start_datetime": "2026-08-01T12:00:00Z",
            "description": "Bring slides",
        }
        result = compute_change_set(baseline, proposed)
        assert result.kind == "enrichment"
        assert result.changes[0].field == "description"

    def test_cancellation_kind(self):
        baseline = {
            "title": "Team Meeting",
            "start_datetime": "2026-08-01T12:00:00Z",
            "status": "synced",
        }
        proposed = {
            "title": "Team Meeting",
            "start_datetime": "2026-08-01T12:00:00Z",
        }
        result = compute_change_set(baseline, proposed, source_type="cancellation")
        assert result.kind == "cancellation"
        assert any(c.field == "status" for c in result.changes)


class TestGateChangeSet:
    def test_drops_equivalent_datetime_hallucination(self):
        baseline = {"start_datetime": "2026-07-17T15:00:00-04:00", "title": "A"}
        raw = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="start_datetime",
                    before="2026-07-17T15:00:00-04:00",
                    after="2026-07-17T19:00:00Z",
                )
            ],
        )
        gated = gate_change_set(raw, baseline)
        assert gated.kind == "noop"
        assert gated.changes == []

    def test_keeps_real_time_change(self):
        baseline = {"start_datetime": "2026-07-17T15:00:00Z", "title": "A"}
        raw = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="start_datetime",
                    before="2026-07-17T15:00:00Z",
                    after="2026-07-17T16:00:00Z",
                    reason="Rescheduled",
                )
            ],
        )
        gated = gate_change_set(raw, baseline)
        assert gated.kind == "material_update"
        assert len(gated.changes) == 1


class TestBaselineHelpers:
    def test_baseline_from_gcal_event(self):
        gcal = {
            "summary": "Standup",
            "start": {"dateTime": "2026-07-17T15:00:00-04:00"},
            "end": {"dateTime": "2026-07-17T15:30:00-04:00"},
            "location": "Room 1",
            "description": "Daily",
        }
        baseline = baseline_from_gcal_event(gcal)
        assert baseline["title"] == "Standup"
        assert baseline["all_day"] is False
        assert baseline["location"] == "Room 1"

    def test_apply_asserted_fields(self):
        baseline = {
            "title": "A",
            "start_datetime": "2026-01-01T10:00:00Z",
            "location": "Keep me",
        }
        proposed = {"title": "B", "start_datetime": "2026-01-01T11:00:00Z"}
        merged = apply_asserted_fields(baseline, proposed)
        assert merged["title"] == "B"
        assert merged["location"] == "Keep me"
