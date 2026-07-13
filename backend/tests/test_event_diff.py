"""Unit tests for deterministic event field diffs and LLM changeset gating."""

from selko.services.event_diff import (
    EventChangeSet,
    FieldChange,
    apply_asserted_fields,
    baseline_from_gcal_event,
    compute_change_set,
    gate_change_set,
    resolve_description_append,
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

    def test_drops_llm_utc_stamp_matching_local_wall_time(self):
        """Bike Family Fest regression: 10:00+00:00 civil == 10:00-07:00 baseline."""
        baseline = {"start_datetime": "2026-09-13T10:00:00-07:00", "title": "Fest"}
        raw = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="start_datetime",
                    before="2026-09-13T10:00:00-07:00",
                    after="2026-09-13T10:00:00+00:00",
                    reason="UTC vs local",
                )
            ],
        )
        gated = gate_change_set(raw, baseline, user_timezone="America/Los_Angeles")
        assert gated.kind == "noop"
        assert gated.changes == []

    def test_drops_cosmetic_title_recruiter_case(self):
        """The real-world case behind rule 11: rewording + subtitle qualifier."""
        baseline = {"title": "Interview with Acme - Screening Call with Jane Doe"}
        raw = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="title",
                    before="Interview with Acme - Screening Call with Jane Doe",
                    after="Acme Screening Call with Jane Doe (Recruiter)",
                )
            ],
        )
        gated = gate_change_set(raw, baseline)
        assert gated.kind == "noop"
        assert gated.changes == []

    def test_drops_cosmetic_title_participation_role(self):
        baseline = {"title": "Community Bike Fest 2026"}
        raw = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="title",
                    before="Community Bike Fest 2026",
                    after="Community Bike Fest 2026 - Advocacy Table",
                )
            ],
        )
        gated = gate_change_set(raw, baseline)
        assert gated.kind == "noop"
        assert gated.changes == []

    def test_keeps_genuine_title_rename(self):
        baseline = {"title": "Spring Gala"}
        raw = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="title",
                    before="Spring Gala",
                    after="Emergency Board Meeting",
                )
            ],
        )
        gated = gate_change_set(raw, baseline)
        assert gated.kind == "material_update"
        assert len(gated.changes) == 1

    def test_preserves_mode_on_gated_change(self):
        baseline = {"description": "Existing description"}
        raw = EventChangeSet(
            kind="enrichment",
            changes=[
                FieldChange(
                    field="description",
                    before="Existing description",
                    after="New info",
                    mode="append",
                )
            ],
        )
        gated = gate_change_set(raw, baseline)
        assert len(gated.changes) == 1
        assert gated.changes[0].mode == "append"


class TestResolveDescriptionAppend:
    def test_appends_to_non_empty_baseline(self):
        baseline = {"description": "Original description."}
        change_set = EventChangeSet(
            kind="enrichment",
            changes=[
                FieldChange(
                    field="description",
                    before="Original description.",
                    after="New detail from the follow-up email.",
                    mode="append",
                )
            ],
        )
        result = resolve_description_append(change_set, baseline)
        assert result.changes[0].after == (
            "Original description.\n\nNew detail from the follow-up email."
        )
        assert result.changes[0].mode is None

    def test_appends_to_empty_baseline(self):
        baseline = {"description": ""}
        change_set = EventChangeSet(
            kind="enrichment",
            changes=[
                FieldChange(field="description", after="Only new info.", mode="append")
            ],
        )
        result = resolve_description_append(change_set, baseline)
        assert result.changes[0].after == "Only new info."

    def test_dedupes_already_present_addition(self):
        baseline = {"description": "Bring your own snacks. Original description."}
        change_set = EventChangeSet(
            kind="enrichment",
            changes=[
                FieldChange(
                    field="description",
                    after="Bring your own snacks.",
                    mode="append",
                )
            ],
        )
        result = resolve_description_append(change_set, baseline)
        assert result.changes[0].after == "Bring your own snacks. Original description."

    def test_replace_mode_is_untouched(self):
        baseline = {"description": "Old"}
        change_set = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(field="description", after="Corrected text", mode="replace")
            ],
        )
        result = resolve_description_append(change_set, baseline)
        assert result.changes[0].after == "Corrected text"
        assert result.changes[0].mode == "replace"

    def test_non_description_fields_are_untouched(self):
        baseline = {"title": "A"}
        change_set = EventChangeSet(
            kind="material_update",
            changes=[FieldChange(field="title", after="B")],
        )
        result = resolve_description_append(change_set, baseline)
        assert result.changes[0].after == "B"


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
