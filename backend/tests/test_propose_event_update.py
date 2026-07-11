"""Unit tests for propose_event_update LLM + gate."""

import json
from unittest.mock import MagicMock

from selko.services.event_processing import propose_event_update


def test_propose_event_update_gates_noop_datetime():
    gateway = MagicMock()
    gateway.call.return_value = MagicMock(
        text=json.dumps(
            {
                "kind": "material_update",
                "changes": [
                    {
                        "field": "start_datetime",
                        "before": "2026-07-17T15:00:00-04:00",
                        "after": "2026-07-17T19:00:00Z",
                        "reason": "same instant",
                    }
                ],
                "reasoning": "timezone format only",
            }
        )
    )
    baseline = {
        "title": "Sync",
        "start_datetime": "2026-07-17T15:00:00-04:00",
    }
    extracted = {
        "title": "Sync",
        "start_datetime": "2026-07-17T19:00:00Z",
    }
    result = propose_event_update(gateway, baseline, extracted)
    assert result.kind == "noop"
    assert result.changes == []


def test_propose_event_update_keeps_real_change():
    gateway = MagicMock()
    gateway.call.return_value = MagicMock(
        text=json.dumps(
            {
                "kind": "material_update",
                "changes": [
                    {
                        "field": "location",
                        "before": "Room A",
                        "after": "Room B",
                        "reason": "Moved rooms",
                    }
                ],
                "reasoning": "location changed",
            }
        )
    )
    baseline = {"title": "Sync", "location": "Room A"}
    extracted = {"title": "Sync", "location": "Room B"}
    result = propose_event_update(gateway, baseline, extracted)
    assert result.kind == "material_update"
    assert len(result.changes) == 1
    assert result.changes[0].field == "location"
