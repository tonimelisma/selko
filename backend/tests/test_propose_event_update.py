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


def test_prompt_includes_both_date_lines_when_provided():
    gateway = MagicMock()
    gateway.call.return_value = MagicMock(
        text=json.dumps({"kind": "noop", "changes": [], "reasoning": ""})
    )
    baseline = {"title": "Sync"}
    extracted = {"title": "Sync"}

    propose_event_update(
        gateway,
        baseline,
        extracted,
        email_date_sent="2026-07-09T10:00:00Z",
        baseline_info_date="2026-07-12T08:00:00Z",
    )

    prompt = gateway.call.call_args.kwargs["contents"][0]
    assert "**This email was sent:** 2026-07-09T10:00:00Z" in prompt
    assert (
        "**The event's current information is from an email sent:** 2026-07-12T08:00:00Z"
        in prompt
    )


def test_prompt_omits_date_lines_when_not_provided():
    gateway = MagicMock()
    gateway.call.return_value = MagicMock(
        text=json.dumps({"kind": "noop", "changes": [], "reasoning": ""})
    )
    baseline = {"title": "Sync"}
    extracted = {"title": "Sync"}

    propose_event_update(gateway, baseline, extracted)

    prompt = gateway.call.call_args.kwargs["contents"][0]
    assert "This email was sent" not in prompt
    assert "current information is from an email sent" not in prompt


def test_prompt_rejects_digest_generated_enrichment():
    gateway = MagicMock()
    gateway.call.return_value = MagicMock(
        text=json.dumps({"kind": "noop", "changes": [], "reasoning": ""})
    )

    propose_event_update(
        gateway,
        {"title": "Evening Cleanup", "description": None},
        {
            "title": "Evening Cleanup",
            "description": "1 person. Associated contact: Family Member.",
        },
        email_subject="Daily Brief",
    )

    prompt = gateway.call.call_args.kwargs["contents"][0]
    assert "Digest-generated metadata" in prompt
    assert "participant counts" in prompt
    assert "kind=noop, changes=[]" in prompt
