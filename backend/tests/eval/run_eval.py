#!/usr/bin/env python3
"""
LLM Evaluation Runner — Multi-Model, Multi-Operation, Cost Tracking

Comprehensive eval framework for testing all 3 LLM operations (extract, compare, merge)
across 6 default models (one per provider) with idempotent caching and cost analysis.

Run with: uv run python -m backend.tests.eval.run_eval --help
"""

import argparse
import hashlib
import inspect
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .artifact_store import (
    ArtifactStore,
    PlannedCell,
    build_combined_result,
    format_plan_table,
    new_run_id,
)
from .eval_config import (
    ATTACHMENTS_DIR,
    AUTO_SCORE_THRESHOLDS,
    COMPARE_DIR,
    COST_TIERS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DIFFICULTY_LEVELS,
    EMAIL_CATEGORIES,
    EMAILS_DIR,
    EVAL_MODELS,
    EVENT_PROCESSING_PATH,
    MERGE_DIR,
    MERGE_SCORE_THRESHOLDS,
    RATING_SCALE,
    RESULTS_DIR,
    THREADS_DIR,
)
from .identity import (
    build_inference_identity,
    build_score_identity,
    code_provenance,
    compute_fixture_input_hash,
    compute_prompt_contract_hash,
    normalize_thinking,
)


# ---------------------------------------------------------------------------
# Hashing helpers (legacy wrappers + content-addressed identity)
# ---------------------------------------------------------------------------

def get_fixture_hash(fixture_path: Path) -> str:
    """SHA256 of the full fixture JSON file (legacy helper for unit tests).

    Cache invalidation for model calls uses ``compute_fixture_input_hash`` which
    hashes only the input portion plus attachment bytes.
    """
    return hashlib.sha256(fixture_path.read_bytes()).hexdigest()


def get_code_hash() -> str:
    """Short SHA256 hash of event_processing.py (provenance only; not cache key)."""
    code_path = EVENT_PROCESSING_PATH.resolve()
    if not code_path.exists():
        return "unknown"
    return hashlib.sha256(code_path.read_bytes()).hexdigest()[:12]


def get_prompt_hash(operation: str = "extract") -> str:
    """Short operation-specific prompt contract hash (first 12 chars).

    Prefer ``compute_prompt_contract_hash(operation)`` for full identity keys.
    The default operation is extract for backwards-compatible call sites.
    """
    full = compute_prompt_contract_hash(operation)
    if full == "unknown":
        return "unknown"
    return full[:12]


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def estimate_cost(
    model: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    """Calculate cost in USD using MODEL_REGISTRY pricing (per 1M tokens).

    Returns None (unknown) when token counts are missing or the model has no
    pricing entry. A registered $0/$0 model still returns 0.0.
    """
    from selko.services.llm_provider import MODEL_REGISTRY

    if prompt_tokens is None or completion_tokens is None:
        return None
    entry = MODEL_REGISTRY.get(model)
    if entry is None or "pricing" not in entry:
        return None
    pricing = entry["pricing"]
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Content-addressed cache helpers
# ---------------------------------------------------------------------------

_DEFAULT_STORE = ArtifactStore()


def get_result_path(
    operation: str,
    provider: str,
    model: str,
    fixture_name: str,
    prompt_hash: str,
    thinking: str = "low",
) -> Path:
    """Legacy path helper retained for unit tests and old result browsing.

    New evals write under results/inference/ and results/scores/.
    """
    safe_name = fixture_name.replace("/", "_")
    model_dir = f"{provider}_{model}_{thinking}"
    return RESULTS_DIR / operation / model_dir / safe_name / f"result_{prompt_hash}.json"


def get_latest_result(
    operation: str,
    provider: str,
    model: str,
    fixture_name: str,
    thinking: str = "low",
    fixture: dict | None = None,
    fixture_path: Path | None = None,
    store: ArtifactStore | None = None,
) -> dict | None:
    """Load a cached combined result via content-addressed identity when possible."""
    store = store or _DEFAULT_STORE
    if fixture is None and fixture_path is not None:
        fixture = load_fixture(fixture_path)
    if fixture is None:
        return None

    identity = build_inference_identity(
        operation=operation,
        provider=provider,
        model=model,
        thinking=thinking,
        fixture=fixture,
    )
    inference = store.load_inference(identity.inference_key)
    if inference is None:
        return None

    score_identity = build_score_identity(
        operation=operation,
        inference_key=identity.inference_key,
        fixture=fixture,
    )
    score = store.load_score(score_identity.score_key)
    if score is None:
        # Inference hit but expected/scorer changed — caller should rescore.
        return None

    inference = {**inference, "from_cache": True}
    return build_combined_result(
        inference=inference,
        score=score,
        fixture_name=fixture_name,
        operation=operation,
        provider=provider,
        model=model,
        thinking=thinking,
    )


def should_run(
    fixture_path: Path,
    operation: str,
    provider: str,
    model: str,
    fixture_name: str,
    thinking: str = "low",
    store: ArtifactStore | None = None,
) -> bool:
    """True when a model call is required (inference cache miss)."""
    store = store or _DEFAULT_STORE
    fixture = load_fixture(fixture_path)
    identity = build_inference_identity(
        operation=operation,
        provider=provider,
        model=model,
        thinking=thinking,
        fixture=fixture,
    )
    return not store.has_inference(identity.inference_key)


def save_result_new(
    result: dict,
    operation: str,
    provider: str,
    model: str,
    fixture_name: str,
    thinking: str = "low",
    *,
    fixture: dict | None = None,
    store: ArtifactStore | None = None,
    replicate: int | None = None,
) -> None:
    """Persist inference + score artifacts under content-addressed keys."""
    store = store or _DEFAULT_STORE
    if fixture is None:
        # Best-effort: reconstruct minimal fixture from the result payload.
        fixture = {
            "input": result.get("input_summary", {}),
            "expected": result.get("expected", {}),
            "category": result.get("category"),
            "difficulty": result.get("difficulty"),
            "tags": result.get("tags", []),
            "description": result.get("description", ""),
        }

    identity = build_inference_identity(
        operation=operation,
        provider=provider,
        model=model,
        thinking=thinking,
        fixture=fixture,
    )
    score_identity = build_score_identity(
        operation=operation,
        inference_key=identity.inference_key,
        fixture=fixture,
    )

    inference_artifact = {
        "fixture_name": fixture_name,
        "operation": operation,
        "provider": provider,
        "model": model,
        "thinking": normalize_thinking(thinking),
        "run_at": result.get("run_at"),
        "duration_ms": result.get("duration_ms"),
        "timing": result.get("timing"),
        "tokens": result.get("tokens"),
        "cost": result.get("cost"),
        "actual": result.get("actual"),
        "trace": result.get("trace"),
        "category": result.get("category"),
        "description": result.get("description"),
        "difficulty": result.get("difficulty"),
        "tags": result.get("tags", []),
        "input_summary": result.get("input_summary", {}),
        "fixture_input_hash": identity.fixture_input_hash,
        "code_provenance": code_provenance(),
        "raw_response": (result.get("trace") or {}).get("response_text"),
    }
    store.write_inference(identity, inference_artifact, replicate=replicate)

    score_artifact = {
        "fixture_name": fixture_name,
        "operation": operation,
        "expected": result.get("expected"),
        "auto_score": result.get("auto_score"),
    }
    store.write_score(score_identity, score_artifact)

    # Keep a compatibility copy under the legacy tree for older report browsers.
    prompt_hash = identity.prompt_contract_hash[:12]
    legacy_path = get_result_path(
        operation, provider, model, fixture_name, prompt_hash, thinking
        if isinstance(thinking, str)
        else str(thinking.get("value", "low"))
    )
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    compat = {
        **result,
        "inference_key": identity.inference_key,
        "score_key": score_identity.score_key,
        "prompt_hash": prompt_hash,
        "fixture_hash": identity.fixture_input_hash,
        "identity": identity.to_dict(),
    }
    with open(legacy_path, "w") as f:
        json.dump(compat, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Legacy flat-file helpers (for backwards compat with --report on old results)
# ---------------------------------------------------------------------------

def get_legacy_result_path(fixture_name: str) -> Path:
    safe_name = fixture_name.replace("/", "_")
    return RESULTS_DIR / f"{safe_name}.json"


def load_cached_result(fixture_name: str) -> dict[str, Any] | None:
    result_path = get_legacy_result_path(fixture_name)
    if result_path.exists():
        with open(result_path) as f:
            return json.load(f)
    return None


def save_result(fixture_name: str, result: dict[str, Any]) -> None:
    result_path = get_legacy_result_path(fixture_name)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

def load_fixture(fixture_path: Path) -> dict[str, Any]:
    """Load a fixture JSON file."""
    with open(fixture_path) as f:
        return json.load(f)


def load_attachment(attachment_name: str) -> tuple[str, bytes]:
    """Load attachment content from fixtures."""
    attachment_path = ATTACHMENTS_DIR / attachment_name
    if not attachment_path.exists():
        raise FileNotFoundError(f"Attachment not found: {attachment_path}")
    content = attachment_path.read_bytes()
    return attachment_name, content


def get_all_fixtures() -> list[tuple[str, Path]]:
    """Get all email fixtures organized by category."""
    fixtures = []
    for category in EMAIL_CATEGORIES:
        category_dir = EMAILS_DIR / category
        if category_dir.exists():
            for fixture_file in sorted(category_dir.glob("*.json")):
                fixture_name = f"{category}/{fixture_file.stem}"
                fixtures.append((fixture_name, fixture_file))
    return fixtures


def get_compare_fixtures() -> list[tuple[str, Path]]:
    """Get all compare/dedup fixtures."""
    fixtures = []
    if COMPARE_DIR.exists():
        for fixture_file in sorted(COMPARE_DIR.glob("*.json")):
            fixtures.append((fixture_file.stem, fixture_file))
    return fixtures


def get_merge_fixtures() -> list[tuple[str, Path]]:
    """Get all merge fixtures."""
    fixtures = []
    if MERGE_DIR.exists():
        for fixture_file in sorted(MERGE_DIR.glob("*.json")):
            fixtures.append((fixture_file.stem, fixture_file))
    return fixtures


def get_thread_scenarios() -> list[tuple[str, Path]]:
    """Get all thread scenario files."""
    scenarios = []
    if THREADS_DIR.exists():
        for scenario_file in sorted(THREADS_DIR.glob("*.json")):
            scenarios.append((scenario_file.stem, scenario_file))
    return scenarios


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def string_similarity(a: str | None, b: str | None) -> float:
    """Calculate string similarity ratio."""
    if a is None or b is None:
        return 0.0 if (a is None) != (b is None) else 1.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def time_difference_minutes(t1: str | None, t2: str | None) -> float | None:
    """Calculate time difference in minutes between two datetime strings."""
    if t1 is None or t2 is None:
        return None
    try:
        # Replace Z suffix with +00:00 for Python 3.10 compatibility
        dt1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
        dt2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
        # Make both naive or both aware for comparison
        if dt1.tzinfo is not None and dt2.tzinfo is None:
            dt2 = dt2.replace(tzinfo=dt1.tzinfo)
        elif dt2.tzinfo is not None and dt1.tzinfo is None:
            dt1 = dt1.replace(tzinfo=dt2.tzinfo)
        return abs((dt1 - dt2).total_seconds() / 60)
    except (ValueError, TypeError):
        return None


def _parse_date_only(dt_str: str) -> str | None:
    """Extract YYYY-MM-DD from a datetime string."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return dt_str[:10] if len(dt_str) >= 10 else None


def auto_score_event(expected: dict, actual: dict) -> dict[str, Any]:
    """Auto-score a single event extraction.

    Only core fields (start_datetime, end_datetime, all_day) gate overall_match.
    Title and location are NOT scored — algorithmic string similarity can't
    determine semantic equivalence (e.g. "SFO" vs "San Francisco International Airport").

    When expected all_day=true, compares only the DATE portion (ignoring time)
    and allows ±1 day tolerance on end dates (exclusive vs inclusive convention).
    """
    scores = {}
    expected_all_day = expected.get("all_day")

    # --- Start datetime ---
    if expected_all_day:
        # All-day: compare date portion only
        exp_date = _parse_date_only(expected.get("start_datetime", ""))
        act_date = _parse_date_only(actual.get("start_datetime", ""))
        scores["start_datetime"] = {
            "expected_date": exp_date,
            "actual_date": act_date,
            "match": exp_date is not None and exp_date == act_date,
            "allday_relaxed": True,
        }
    else:
        start_diff = time_difference_minutes(
            expected.get("start_datetime"), actual.get("start_datetime")
        )
        scores["start_datetime"] = {
            "difference_minutes": start_diff,
            "match": isinstance(start_diff, (int, float))
            and start_diff <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"],
        }

    # --- End datetime ---
    if expected_all_day:
        exp_end = expected.get("end_datetime")
        act_end = actual.get("end_datetime")
        if exp_end is None or act_end is None:
            # If either is None, match (end is optional for all-day)
            scores["end_datetime"] = {"match": True, "allday_relaxed": True}
        else:
            exp_date = _parse_date_only(exp_end)
            act_date = _parse_date_only(act_end)
            if exp_date and act_date:
                # Allow ±1 day tolerance (exclusive vs inclusive end convention)
                try:
                    from datetime import timedelta
                    exp_d = datetime.strptime(exp_date, "%Y-%m-%d")
                    act_d = datetime.strptime(act_date, "%Y-%m-%d")
                    day_diff = abs((exp_d - act_d).days)
                    scores["end_datetime"] = {
                        "expected_date": exp_date,
                        "actual_date": act_date,
                        "day_difference": day_diff,
                        "match": day_diff <= 1,
                        "allday_relaxed": True,
                    }
                except (ValueError, TypeError):
                    scores["end_datetime"] = {"match": False}
            else:
                scores["end_datetime"] = {"match": exp_date == act_date, "allday_relaxed": True}
    else:
        end_diff = time_difference_minutes(
            expected.get("end_datetime"), actual.get("end_datetime")
        )
        scores["end_datetime"] = {
            "difference_minutes": end_diff,
            "match": end_diff is None
            or (isinstance(end_diff, (int, float)) and end_diff <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"]),
        }

    # All day — don't fail on mismatch when expected is all_day
    # (model may say all_day=false with midnight time, which is equivalent)
    if expected_all_day is not None:
        actual_all_day = actual.get("all_day")
        if expected_all_day:
            # When expected is all_day, don't gate on mismatch
            scores["all_day"] = {
                "expected": expected_all_day,
                "actual": actual_all_day,
                "match": True,
                "allday_relaxed": expected_all_day != actual_all_day,
            }
        else:
            scores["all_day"] = {
                "expected": expected_all_day,
                "actual": actual_all_day,
                "match": expected_all_day == actual_all_day,
            }

    # Importance (reported but does not gate overall_match)
    expected_importance = expected.get("importance")
    actual_importance = actual.get("importance")
    if expected_importance is not None:
        scores["importance"] = {
            "expected": expected_importance,
            "actual": actual_importance,
            "match": expected_importance == actual_importance,
        }

    # Recurrence rule (reported but does not gate overall_match)
    expected_recurrence = expected.get("recurrence_rule")
    actual_recurrence = actual.get("recurrence_rule")
    if expected_recurrence is not None:
        scores["recurrence_rule"] = {
            "expected": expected_recurrence,
            "actual": actual_recurrence,
            "match": expected_recurrence == actual_recurrence,
        }

    # Recurring events: if EITHER expected or actual has recurrence_rule,
    # skip date comparison — only compare time-of-day (the date the model
    # picks is irrelevant for a recurring event).
    has_recurrence = expected_recurrence or actual_recurrence
    if has_recurrence:
        for dt_field in ("start_datetime", "end_datetime"):
            if not scores.get(dt_field, {}).get("match", True):
                try:
                    exp_dt = datetime.fromisoformat(expected.get(dt_field, "").replace("Z", "+00:00"))
                    act_dt = datetime.fromisoformat(actual.get(dt_field, "").replace("Z", "+00:00"))
                    time_diff_mins = abs(
                        (exp_dt.hour * 60 + exp_dt.minute) - (act_dt.hour * 60 + act_dt.minute)
                    )
                    if time_diff_mins <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"]:
                        scores[dt_field]["match"] = True
                        scores[dt_field]["recurring_relaxed"] = True
                except (ValueError, TypeError):
                    pass

    # Only core fields (times + all_day) gate overall_match.
    CORE_MATCH_FIELDS = {"start_datetime", "end_datetime", "all_day"}
    scores["overall_match"] = all(
        s.get("match", True)
        for key, s in scores.items()
        if isinstance(s, dict) and key in CORE_MATCH_FIELDS
    )

    return scores


def auto_score_result(expected: dict, actual: dict) -> dict[str, Any]:
    """Auto-score the full extraction result.

    Extra events (model finds more than expected) are reported but do NOT
    penalize the score — extracting additional sub-events is acceptable.

    Supports event_count_min: when present, actual count >= min passes even
    if fewer than event_count.
    """
    expected_count = expected.get("event_count", len(expected.get("events", [])))
    expected_count_min = expected.get("event_count_min")
    actual_count = len(actual.get("events", []))
    tolerance = max(1, round(expected_count * 0.2))

    # Count match: within tolerance of expected, OR >= event_count_min
    count_match = abs(actual_count - expected_count) <= tolerance
    if not count_match and expected_count_min is not None:
        count_match = actual_count >= expected_count_min

    scores = {
        "events_found_match": expected.get("events_found")
        == actual.get("events_found"),
        "event_count_match": count_match,
    }

    expected_events = expected.get("events", [])
    actual_events = actual.get("events", [])

    if expected_events and actual_events:
        # Build score matrix for greedy best-match (not positional)
        score_matrix = []
        for i, exp_event in enumerate(expected_events):
            for j, act_event in enumerate(actual_events):
                pair_score = auto_score_event(exp_event, act_event)
                # Quality metric: (overall_match, count of field matches)
                field_matches = sum(
                    1 for k, s in pair_score.items()
                    if isinstance(s, dict) and s.get("match", False) and k != "overall_match"
                )
                score_matrix.append((pair_score.get("overall_match", False), field_matches, i, j, pair_score))

        # Sort descending by quality: overall_match first, then field_matches
        score_matrix.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # Greedy assignment: best unmatched pairs first
        matched_expected = set()
        matched_actual = set()
        event_scores = [None] * len(expected_events)
        extra_scores = []

        for overall_match, field_matches, i, j, pair_score in score_matrix:
            if i not in matched_expected and j not in matched_actual:
                event_scores[i] = pair_score
                matched_expected.add(i)
                matched_actual.add(j)

        # Remaining unmatched expected → missing
        for i in range(len(expected_events)):
            if event_scores[i] is None:
                event_scores[i] = {"missing": True, "overall_match": False}

        # Remaining unmatched actual → extra (reported but NOT penalized)
        for j in range(len(actual_events)):
            if j not in matched_actual:
                extra_scores.append({"extra": True, "overall_match": False})

        scores["event_scores"] = event_scores
        scores["extra_events"] = extra_scores
        # all_events_match only considers matched expected events, NOT extras
        scores["all_events_match"] = all(
            es.get("overall_match", False) for es in event_scores
        )
    else:
        scores["all_events_match"] = not expected_events and not actual_events

    # Rating: extras don't penalize, event_count_match is informational
    if scores["events_found_match"] and scores.get("all_events_match"):
        scores["auto_rating"] = 5
    elif scores["events_found_match"]:
        # Check what fraction of expected events match
        event_scores_list = scores.get("event_scores", [])
        matched_count = sum(1 for es in event_scores_list if es.get("overall_match", False))
        total_count = len(event_scores_list) if event_scores_list else 1
        if matched_count / total_count >= 0.5:
            scores["auto_rating"] = 4
        else:
            scores["auto_rating"] = 3
    else:
        scores["auto_rating"] = 1

    return scores


def score_compare_result(expected: dict, actual_matched_id: str | None) -> dict[str, Any]:
    """Score a compare (dedup) result. Binary pass/fail."""
    expected_id = expected.get("matched_event_id")
    correct = (expected_id is None and actual_matched_id is None) or (
        expected_id is not None and actual_matched_id is not None and str(expected_id) == str(actual_matched_id)
    )
    return {"correct": correct, "expected": expected_id, "actual": actual_matched_id}


def score_merge_result(expected: dict, actual: dict) -> dict[str, Any]:
    """Score a merge result. Returns per-field scores and overall rating 1-5."""
    scores = {}
    fields_matched = 0
    total_fields = 0

    # Title
    total_fields += 1
    title_sim = string_similarity(expected.get("title"), actual.get("title"))
    title_match = title_sim >= MERGE_SCORE_THRESHOLDS["title_similarity"]
    scores["title"] = {"similarity": title_sim, "match": title_match}
    if title_match:
        fields_matched += 1

    # Check cancellation prefix
    if expected.get("title", "").startswith("CANCELLED:"):
        actual_title = actual.get("title", "")
        scores["cancellation_prefix"] = actual_title.upper().startswith("CANCELLED:")
        if not scores["cancellation_prefix"]:
            fields_matched = max(0, fields_matched - 1)

    # Start datetime
    total_fields += 1
    start_diff = time_difference_minutes(
        expected.get("start_datetime"), actual.get("start_datetime")
    )
    start_match = isinstance(start_diff, (int, float)) and start_diff <= MERGE_SCORE_THRESHOLDS["time_tolerance_minutes"]
    scores["start_datetime"] = {"difference_minutes": start_diff, "match": start_match}
    if start_match:
        fields_matched += 1

    # End datetime
    total_fields += 1
    end_diff = time_difference_minutes(
        expected.get("end_datetime"), actual.get("end_datetime")
    )
    end_match = end_diff is None or (isinstance(end_diff, (int, float)) and end_diff <= MERGE_SCORE_THRESHOLDS["time_tolerance_minutes"])
    scores["end_datetime"] = {"difference_minutes": end_diff, "match": end_match}
    if end_match:
        fields_matched += 1

    # All day
    if "all_day" in expected:
        total_fields += 1
        allday_match = expected["all_day"] == actual.get("all_day")
        scores["all_day"] = {"match": allday_match}
        if allday_match:
            fields_matched += 1

    # Location
    if expected.get("location") is not None:
        total_fields += 1
        loc_sim = string_similarity(expected.get("location"), actual.get("location"))
        loc_match = loc_sim >= MERGE_SCORE_THRESHOLDS["location_similarity"]
        scores["location"] = {"similarity": loc_sim, "match": loc_match}
        if loc_match:
            fields_matched += 1

    # Description contains
    desc_keywords = expected.get("description_contains", [])
    if desc_keywords:
        total_fields += 1
        actual_desc = (actual.get("description") or "").lower()
        found = [kw for kw in desc_keywords if kw.lower() in actual_desc]
        missing = [kw for kw in desc_keywords if kw.lower() not in actual_desc]
        desc_match = len(missing) == 0
        scores["description_contains"] = {
            "found": found,
            "missing": missing,
            "match": desc_match,
        }
        if desc_match:
            fields_matched += 1

    # Overall rating
    if total_fields == 0:
        rating = 1
    else:
        ratio = fields_matched / total_fields
        if ratio == 1.0:
            rating = 5
        elif ratio >= 0.8:
            rating = 4
        elif ratio >= 0.6:
            rating = 3
        elif ratio >= 0.4:
            rating = 2
        else:
            rating = 1

    scores["fields_matched"] = fields_matched
    scores["total_fields"] = total_fields
    scores["auto_rating"] = rating
    return scores


# ---------------------------------------------------------------------------
# Fixture schema validation
# ---------------------------------------------------------------------------

def validate_fixtures() -> list[str]:
    """Validate all fixture files for schema correctness. Returns list of warnings."""
    warnings = []

    # Validate extract fixtures
    for fixture_name, fixture_path in get_all_fixtures():
        try:
            fixture = load_fixture(fixture_path)
        except Exception as e:
            warnings.append(f"[extract] {fixture_name}: Failed to parse JSON: {e}")
            continue

        expected = fixture.get("expected", {})
        if "events_found" not in expected:
            warnings.append(f"[extract] {fixture_name}: Missing required field 'expected.events_found'")

        for i, event in enumerate(expected.get("events", [])):
            if "title" not in event:
                warnings.append(f"[extract] {fixture_name}: Event {i} missing 'title'")
            if "start_datetime" not in event:
                warnings.append(f"[extract] {fixture_name}: Event {i} missing 'start_datetime'")
            if "is_all_day" in event:
                warnings.append(f"[extract] {fixture_name}: Event {i} uses deprecated 'is_all_day' — rename to 'all_day'")

    # Validate compare fixtures
    for fixture_name, fixture_path in get_compare_fixtures():
        try:
            fixture = load_fixture(fixture_path)
        except Exception as e:
            warnings.append(f"[compare] {fixture_name}: Failed to parse JSON: {e}")
            continue

        expected = fixture.get("expected", {})
        if "matched_event_id" not in expected:
            warnings.append(f"[compare] {fixture_name}: Missing required field 'expected.matched_event_id'")

    # Validate merge fixtures
    for fixture_name, fixture_path in get_merge_fixtures():
        try:
            fixture = load_fixture(fixture_path)
        except Exception as e:
            warnings.append(f"[merge] {fixture_name}: Failed to parse JSON: {e}")
            continue

        input_data = fixture.get("input", {})
        if "existing_event" not in input_data:
            warnings.append(f"[merge] {fixture_name}: Missing 'input.existing_event'")
        if "new_extraction" not in input_data:
            warnings.append(f"[merge] {fixture_name}: Missing 'input.new_extraction'")
        if "source_type" not in input_data:
            warnings.append(f"[merge] {fixture_name}: Missing 'input.source_type'")

    return warnings


# ---------------------------------------------------------------------------
# MIME type helper
# ---------------------------------------------------------------------------

def _guess_mime_type(filename: str) -> str:
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    mime_map = {
        "txt": "text/plain",
        "ics": "text/calendar",
        "csv": "text/csv",
        "md": "text/markdown",
        "json": "application/json",
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "heic": "image/heic",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
    }
    return mime_map.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# Provider/gateway factory for evals
# ---------------------------------------------------------------------------

def _create_gateway(provider_name: str, model_name: str, thinking: str = "low"):
    """Create a provider + gateway for a specific model."""
    from selko.config import load_config
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import create_provider

    config = load_config()
    config.llm_provider = provider_name
    config.llm_model = model_name
    provider = create_provider(config, thinking=thinking)
    return LLMGateway(provider)


# ---------------------------------------------------------------------------
# Check if fixture requires vision
# ---------------------------------------------------------------------------

def fixture_requires_vision(fixture: dict) -> bool:
    """Check if an extraction fixture has visual attachments (images, PDFs, HEIC)."""
    for att in fixture.get("input", {}).get("attachments", []):
        if isinstance(att, str):
            ext = att.lower().split(".")[-1] if "." in att else ""
            if ext in ("png", "jpg", "jpeg", "gif", "webp", "pdf", "heic", "bmp", "tiff"):
                return True
    return False


def run_preflight(eval_models: list[tuple]) -> bool:
    """Run a cheap API call per model to validate credentials.

    Returns True if all models pass, False if any fail.
    """
    from selko.services.llm_provider import ContentPart

    print("Preflight: validating API credentials for each model...")
    all_ok = True
    seen = set()
    for model_tuple in eval_models:
        if len(model_tuple) == 3:
            provider_name, model_name, thinking = model_tuple
        else:
            provider_name, model_name = model_tuple
            thinking = "low"

        # Only test each provider+model once (skip duplicate thinking levels)
        key = (provider_name, model_name)
        if key in seen:
            continue
        seen.add(key)

        try:
            gateway = _create_gateway(provider_name, model_name, thinking=thinking)
            from selko.services.llm_logging import LLMOperationType
            response = gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["Say 'ok' in one word."],
                max_retries=1,
            )
            print(f"  OK  {provider_name}/{model_name} ({len(response.text)} chars)")
        except Exception as e:
            print(f"  FAIL {provider_name}/{model_name}: {e}")
            all_ok = False

    if all_ok:
        print("Preflight: all models OK")
    else:
        print("Preflight: some models FAILED — fix credentials before running evals")
    return all_ok


# ---------------------------------------------------------------------------
# Extract eval runner
# ---------------------------------------------------------------------------

def _rescore_cached_inference(
    operation: str,
    fixture_name: str,
    fixture: dict[str, Any],
    provider_name: str,
    model_name: str,
    thinking: str,
    *,
    store: ArtifactStore,
    score_fn,
) -> dict[str, Any] | None:
    """Rescore an existing inference when expected output or scorer changed."""
    identity = build_inference_identity(
        operation=operation,
        provider=provider_name,
        model=model_name,
        thinking=thinking,
        fixture=fixture,
    )
    inference = store.load_inference(identity.inference_key)
    if inference is None:
        return None

    expected = fixture.get("expected", {})
    actual = inference.get("actual", {})
    if operation == "compare":
        auto_score = score_fn(expected, actual.get("matched_event_id") if isinstance(actual, dict) else actual)
    else:
        auto_score = score_fn(expected, actual)

    score_identity = build_score_identity(
        operation=operation,
        inference_key=identity.inference_key,
        fixture=fixture,
    )
    store.write_score(
        score_identity,
        {
            "fixture_name": fixture_name,
            "operation": operation,
            "expected": expected,
            "auto_score": auto_score,
        },
    )
    score = store.load_score(score_identity.score_key)
    inference = {**inference, "from_cache": True}
    return build_combined_result(
        inference=inference,
        score=score,
        fixture_name=fixture_name,
        operation=operation,
        provider=provider_name,
        model=model_name,
        thinking=thinking,
    )


def run_extract_eval(
    fixture_name: str,
    fixture_path: Path,
    provider_name: str,
    model_name: str,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    thinking: str = "low",
    replicate: int | None = None,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Run extraction evaluation for a single fixture."""
    fixture = load_fixture(fixture_path)
    store = store or _DEFAULT_STORE

    # Cache check — complete inference+score hit
    if (
        use_cache
        and replicate is None
        and not dry_run
        and not should_run(
            fixture_path, "extract", provider_name, model_name, fixture_name, thinking, store=store
        )
    ):
        cached = get_latest_result(
            "extract",
            provider_name,
            model_name,
            fixture_name,
            thinking,
            fixture=fixture,
            store=store,
        )
        if cached:
            if verbose:
                print(f"  [cached] {fixture_name}")
            return cached
        # Inference exists but score identity changed — rescore without a model call.
        rescored = _rescore_cached_inference(
            "extract",
            fixture_name,
            fixture,
            provider_name,
            model_name,
            thinking,
            store=store,
            score_fn=lambda expected, actual: auto_score_result(expected, actual),
        )
        if rescored is not None:
            if verbose:
                print(f"  [rescore] {fixture_name}")
            return rescored

    # Phase 1: Fixture + attachment loading
    fixture_load_started_at = datetime.now(timezone.utc)
    input_data = fixture["input"]
    expected = fixture["expected"]

    attachments = []
    attachment_errors = []
    attachment_types: list[str] = []
    total_attachment_bytes = 0
    for att_ref in input_data.get("attachments", []):
        if isinstance(att_ref, str):
            try:
                name, content = load_attachment(att_ref)
                mime = _guess_mime_type(name)
                attachments.append({
                    "filename": name,
                    "data": content,
                    "mime_type": mime,
                })
                total_attachment_bytes += len(content)
                if mime.startswith("image/") or mime == "application/pdf":
                    attachment_types.append("image")
                else:
                    attachment_types.append("text")
            except FileNotFoundError as e:
                attachment_errors.append(str(e))
                if not dry_run:
                    print(f"  Warning: {e}")

    fixture_load_ms = int((datetime.now(timezone.utc) - fixture_load_started_at).total_seconds() * 1000)

    # Dry-run
    if dry_run:
        validation_errors = []
        if "input" not in fixture:
            validation_errors.append("Missing 'input' field")
        if "expected" not in fixture:
            validation_errors.append("Missing 'expected' field")
        if "body_text" not in input_data and "attachments" not in input_data:
            validation_errors.append("Input must have 'body_text' or 'attachments'")
        if "events_found" not in expected:
            validation_errors.append("Expected must have 'events_found' field")
        validation_errors.extend(attachment_errors)
        is_valid = len(validation_errors) == 0
        return {
            "fixture_name": fixture_name,
            "operation": "extract",
            "provider": provider_name,
            "model": model_name,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": True,
            "valid": is_valid,
            "errors": validation_errors,
        }

    # Real run
    from selko.services.event_processing import extract_calendar_events

    # Phase 2: Gateway creation
    gateway_create_started_at = datetime.now(timezone.utc)
    gateway = _create_gateway(provider_name, model_name, thinking=thinking)
    gateway.trace = {}  # Enable tracing
    gateway_create_ms = int((datetime.now(timezone.utc) - gateway_create_started_at).total_seconds() * 1000)

    # Use date_sent as current_date so evals produce consistent results
    # regardless of when they run — the LLM sees a date contemporary with the email
    date_sent = input_data.get("date_sent", "")
    email_metadata = {
        "subject": input_data.get("subject", ""),
        "from_name": input_data.get("from_name", ""),
        "from_email": input_data.get("from_email", ""),
        "date_sent": date_sent,
        "current_date_override": date_sent[:10] if date_sent else "",
    }

    # Phase 3: API call
    api_call_started_at = datetime.now(timezone.utc)
    try:
        extraction = extract_calendar_events(
            gateway=gateway,
            email_text=input_data.get("body_text", ""),
            email_metadata=email_metadata,
            attachments=attachments if attachments else None,
        )
        actual = {
            "events_found": extraction.events_found,
            "events": [
                {
                    "title": e.title,
                    "start_datetime": e.start_datetime.isoformat() if e.start_datetime else None,
                    "end_datetime": e.end_datetime.isoformat() if e.end_datetime else None,
                    "all_day": getattr(e, "all_day", False),
                    "location": e.location,
                    "description": e.description,
                    "importance": getattr(e, "importance", None),
                    "recurrence_rule": getattr(e, "recurrence_rule", None),
                }
                for e in extraction.events
            ],
        }
        error = None
    except Exception as e:
        actual = {"events_found": False, "events": [], "error": str(e)}
        error = str(e)
    api_call_ms = int((datetime.now(timezone.utc) - api_call_started_at).total_seconds() * 1000)

    # Phase 4: Scoring
    scoring_started_at = datetime.now(timezone.utc)
    prompt_tokens = getattr(gateway, '_last_prompt_tokens', None)
    completion_tokens = getattr(gateway, '_last_completion_tokens', None)
    auto_score = auto_score_result(expected, actual) if not error else {"error": error}
    scoring_ms = int((datetime.now(timezone.utc) - scoring_started_at).total_seconds() * 1000)

    result = {
        "fixture_name": fixture_name,
        "fixture_hash": compute_fixture_input_hash(fixture),
        "code_hash": get_code_hash(),
        "prompt_hash": get_prompt_hash("extract"),
        "operation": "extract",
        "provider": provider_name,
        "model": model_name,
        "thinking": thinking,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": fixture_load_ms + gateway_create_ms + api_call_ms + scoring_ms,
        "timing": {
            "fixture_load": {
                "started_at": fixture_load_started_at.isoformat(),
                "duration_ms": fixture_load_ms,
            },
            "gateway_create": {
                "started_at": gateway_create_started_at.isoformat(),
                "duration_ms": gateway_create_ms,
            },
            "api_call": {
                "started_at": api_call_started_at.isoformat(),
                "duration_ms": api_call_ms,
            },
            "scoring": {
                "started_at": scoring_started_at.isoformat(),
                "duration_ms": scoring_ms,
            },
        },
        "category": fixture.get("category", fixture_name.split("/")[0]),
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "input_summary": {
            "subject": input_data.get("subject", ""),
            "from": input_data.get("from_email", ""),
            "has_attachments": bool(attachments),
            "attachment_count": len(attachments),
            "attachment_types": attachment_types,
            "total_attachment_bytes": total_attachment_bytes,
        },
        "expected": expected,
        "actual": actual,
        "auto_score": auto_score,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0)
            if prompt_tokens is not None or completion_tokens is not None
            else None,
        },
        "cost": estimate_cost(model_name, prompt_tokens, completion_tokens),
        "trace": gateway.trace,
    }

    save_result_new(
        result,
        "extract",
        provider_name,
        model_name,
        fixture_name,
        thinking,
        fixture=fixture,
        store=store,
        replicate=replicate,
    )
    return result


# ---------------------------------------------------------------------------
# Compare eval runner
# ---------------------------------------------------------------------------

def run_compare_eval(
    fixture_name: str,
    fixture_path: Path,
    provider_name: str,
    model_name: str,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    thinking: str = "low",
    replicate: int | None = None,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Run compare (dedup) evaluation for a single fixture."""
    fixture = load_fixture(fixture_path)
    store = store or _DEFAULT_STORE

    if (
        use_cache
        and replicate is None
        and not dry_run
        and not should_run(
            fixture_path, "compare", provider_name, model_name, fixture_name, thinking, store=store
        )
    ):
        cached = get_latest_result(
            "compare",
            provider_name,
            model_name,
            fixture_name,
            thinking,
            fixture=fixture,
            store=store,
        )
        if cached:
            if verbose:
                print(f"  [cached] {fixture_name}")
            return cached
        rescored = _rescore_cached_inference(
            "compare",
            fixture_name,
            fixture,
            provider_name,
            model_name,
            thinking,
            store=store,
            score_fn=score_compare_result,
        )
        if rescored is not None:
            if verbose:
                print(f"  [rescore] {fixture_name}")
            return rescored

    input_data = fixture["input"]
    expected = fixture["expected"]

    if dry_run:
        validation_errors = []
        if "new_event" not in input_data:
            validation_errors.append("Missing 'input.new_event'")
        if "candidate_events" not in input_data:
            validation_errors.append("Missing 'input.candidate_events'")
        if "matched_event_id" not in expected:
            validation_errors.append("Missing 'expected.matched_event_id'")
        is_valid = len(validation_errors) == 0
        return {
            "fixture_name": fixture_name,
            "operation": "compare",
            "provider": provider_name,
            "model": model_name,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": True,
            "valid": is_valid,
            "errors": validation_errors,
        }

    from selko.services.event_processing import compare_events

    # Phase 1: Fixture loading (already done above)
    fixture_load_started_at = datetime.now(timezone.utc)
    new_event = input_data["new_event"]
    candidate_events = input_data["candidate_events"]
    fixture_load_ms = int((datetime.now(timezone.utc) - fixture_load_started_at).total_seconds() * 1000)

    # Phase 2: Gateway creation
    gateway_create_started_at = datetime.now(timezone.utc)
    gateway = _create_gateway(provider_name, model_name, thinking=thinking)
    gateway.trace = {}  # Enable tracing
    gateway_create_ms = int((datetime.now(timezone.utc) - gateway_create_started_at).total_seconds() * 1000)

    # Phase 3: API call
    api_call_started_at = datetime.now(timezone.utc)
    try:
        matched_id = compare_events(gateway, new_event, candidate_events)
        error = None
    except Exception as e:
        matched_id = None
        error = str(e)
    api_call_ms = int((datetime.now(timezone.utc) - api_call_started_at).total_seconds() * 1000)

    # Phase 4: Scoring
    scoring_started_at = datetime.now(timezone.utc)
    prompt_tokens = getattr(gateway, '_last_prompt_tokens', None)
    completion_tokens = getattr(gateway, '_last_completion_tokens', None)
    auto_score = score_compare_result(expected, matched_id) if not error else {"error": error}
    scoring_ms = int((datetime.now(timezone.utc) - scoring_started_at).total_seconds() * 1000)

    result = {
        "fixture_name": fixture_name,
        "fixture_hash": compute_fixture_input_hash(fixture),
        "code_hash": get_code_hash(),
        "prompt_hash": get_prompt_hash("compare"),
        "operation": "compare",
        "provider": provider_name,
        "model": model_name,
        "thinking": thinking,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": fixture_load_ms + gateway_create_ms + api_call_ms + scoring_ms,
        "timing": {
            "fixture_load": {
                "started_at": fixture_load_started_at.isoformat(),
                "duration_ms": fixture_load_ms,
            },
            "gateway_create": {
                "started_at": gateway_create_started_at.isoformat(),
                "duration_ms": gateway_create_ms,
            },
            "api_call": {
                "started_at": api_call_started_at.isoformat(),
                "duration_ms": api_call_ms,
            },
            "scoring": {
                "started_at": scoring_started_at.isoformat(),
                "duration_ms": scoring_ms,
            },
        },
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "expected": expected,
        "actual": {"matched_event_id": matched_id},
        "auto_score": auto_score,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0)
            if prompt_tokens is not None or completion_tokens is not None
            else None,
        },
        "cost": estimate_cost(model_name, prompt_tokens, completion_tokens),
        "trace": gateway.trace,
    }

    save_result_new(
        result,
        "compare",
        provider_name,
        model_name,
        fixture_name,
        thinking,
        fixture=fixture,
        store=store,
        replicate=replicate,
    )
    return result


# ---------------------------------------------------------------------------
# Merge eval runner
# ---------------------------------------------------------------------------

def run_merge_eval(
    fixture_name: str,
    fixture_path: Path,
    provider_name: str,
    model_name: str,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    thinking: str = "low",
    replicate: int | None = None,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Run merge evaluation for a single fixture."""
    fixture = load_fixture(fixture_path)
    store = store or _DEFAULT_STORE

    if (
        use_cache
        and replicate is None
        and not dry_run
        and not should_run(
            fixture_path, "merge", provider_name, model_name, fixture_name, thinking, store=store
        )
    ):
        cached = get_latest_result(
            "merge",
            provider_name,
            model_name,
            fixture_name,
            thinking,
            fixture=fixture,
            store=store,
        )
        if cached:
            if verbose:
                print(f"  [cached] {fixture_name}")
            return cached
        rescored = _rescore_cached_inference(
            "merge",
            fixture_name,
            fixture,
            provider_name,
            model_name,
            thinking,
            store=store,
            score_fn=score_merge_result,
        )
        if rescored is not None:
            if verbose:
                print(f"  [rescore] {fixture_name}")
            return rescored

    input_data = fixture["input"]
    expected = fixture["expected"]

    if dry_run:
        validation_errors = []
        if "existing_event" not in input_data:
            validation_errors.append("Missing 'input.existing_event'")
        if "new_extraction" not in input_data:
            validation_errors.append("Missing 'input.new_extraction'")
        if "source_type" not in input_data:
            validation_errors.append("Missing 'input.source_type'")
        is_valid = len(validation_errors) == 0
        return {
            "fixture_name": fixture_name,
            "operation": "merge",
            "provider": provider_name,
            "model": model_name,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": True,
            "valid": is_valid,
            "errors": validation_errors,
        }

    from selko.services.event_processing import merge_event_data

    # Phase 1: Fixture loading (already done above)
    fixture_load_started_at = datetime.now(timezone.utc)
    existing_event = input_data["existing_event"]
    new_extraction = input_data["new_extraction"]
    source_type = input_data["source_type"]
    fixture_load_ms = int((datetime.now(timezone.utc) - fixture_load_started_at).total_seconds() * 1000)

    # Phase 2: Gateway creation
    gateway_create_started_at = datetime.now(timezone.utc)
    gateway = _create_gateway(provider_name, model_name, thinking=thinking)
    gateway.trace = {}  # Enable tracing
    gateway_create_ms = int((datetime.now(timezone.utc) - gateway_create_started_at).total_seconds() * 1000)

    # Phase 3: API call
    api_call_started_at = datetime.now(timezone.utc)
    try:
        merged = merge_event_data(gateway, existing_event, new_extraction, source_type)
        error = None
    except Exception as e:
        merged = {}
        error = str(e)
    api_call_ms = int((datetime.now(timezone.utc) - api_call_started_at).total_seconds() * 1000)

    # Phase 4: Scoring
    scoring_started_at = datetime.now(timezone.utc)
    prompt_tokens = getattr(gateway, '_last_prompt_tokens', None)
    completion_tokens = getattr(gateway, '_last_completion_tokens', None)
    auto_score = score_merge_result(expected, merged) if not error else {"error": error}
    scoring_ms = int((datetime.now(timezone.utc) - scoring_started_at).total_seconds() * 1000)

    result = {
        "fixture_name": fixture_name,
        "fixture_hash": compute_fixture_input_hash(fixture),
        "code_hash": get_code_hash(),
        "prompt_hash": get_prompt_hash("merge"),
        "operation": "merge",
        "provider": provider_name,
        "model": model_name,
        "thinking": thinking,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": fixture_load_ms + gateway_create_ms + api_call_ms + scoring_ms,
        "timing": {
            "fixture_load": {
                "started_at": fixture_load_started_at.isoformat(),
                "duration_ms": fixture_load_ms,
            },
            "gateway_create": {
                "started_at": gateway_create_started_at.isoformat(),
                "duration_ms": gateway_create_ms,
            },
            "api_call": {
                "started_at": api_call_started_at.isoformat(),
                "duration_ms": api_call_ms,
            },
            "scoring": {
                "started_at": scoring_started_at.isoformat(),
                "duration_ms": scoring_ms,
            },
        },
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "expected": expected,
        "actual": merged,
        "auto_score": auto_score,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0)
            if prompt_tokens is not None or completion_tokens is not None
            else None,
        },
        "cost": estimate_cost(model_name, prompt_tokens, completion_tokens),
        "trace": gateway.trace,
    }

    save_result_new(
        result,
        "merge",
        provider_name,
        model_name,
        fixture_name,
        thinking,
        fixture=fixture,
        store=store,
        replicate=replicate,
    )
    return result


# ---------------------------------------------------------------------------
# Thread eval runner (legacy, unchanged)
# ---------------------------------------------------------------------------

def run_thread_eval(
    scenario_name: str,
    scenario_path: Path,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    provider_name: str | None = None,
    model_name: str | None = None,
    thinking: str = "low",
) -> dict[str, Any]:
    """Run evaluation for a thread scenario (multiple emails processed in sequence)."""
    provider_name = provider_name or DEFAULT_PROVIDER
    model_name = model_name or DEFAULT_MODEL
    start_time = time.time()

    with open(scenario_path) as f:
        scenario = json.load(f)

    thread_emails = scenario.get("thread_emails", [])
    expected_final = scenario.get("expected_final_state", {})

    if dry_run:
        validation_errors = []
        if not thread_emails:
            validation_errors.append("No 'thread_emails' defined in scenario")
        if not expected_final:
            validation_errors.append("No 'expected_final_state' defined")
        for i, email in enumerate(thread_emails):
            if "body_text" not in email:
                validation_errors.append(f"Email {i+1} missing 'body_text'")
            if "date_sent" not in email:
                validation_errors.append(f"Email {i+1} missing 'date_sent'")
        is_valid = len(validation_errors) == 0
        return {
            "scenario_name": scenario_name,
            "scenario_path": str(scenario_path),
            "description": scenario.get("description", ""),
            "difficulty": scenario.get("difficulty", "medium"),
            "tags": scenario.get("tags", []),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "model": model_name,
            "duration_ms": 0,
            "email_count": len(thread_emails),
            "expected_final_state": expected_final,
            "actual": {"dry_run": True, "valid": is_valid, "errors": validation_errors},
            "auto_score": {"dry_run": True, "valid": is_valid},
            "email_results": [],
        }

    from selko.services.event_processing import extract_calendar_events

    gateway = _create_gateway(provider_name, model_name, thinking=thinking)

    email_results = []
    all_events = []

    for i, email_data in enumerate(thread_emails):
        email_metadata = {
            "subject": email_data.get("subject", ""),
            "from_name": email_data.get("from_name", ""),
            "from_email": email_data.get("from_email", ""),
            "date_sent": email_data.get("date_sent", ""),
        }
        try:
            extraction = extract_calendar_events(
                gateway=gateway,
                email_text=email_data.get("body_text", ""),
                email_metadata=email_metadata,
                attachments=None,
            )
            email_result = {
                "email_index": i + 1,
                "provider_message_id": email_data.get("provider_message_id", f"email-{i+1}"),
                "subject": email_data.get("subject", ""),
                "events_found": extraction.events_found,
                "events": [
                    {
                        "title": e.title,
                        "start_datetime": e.start_datetime.isoformat() if e.start_datetime else None,
                        "end_datetime": e.end_datetime.isoformat() if e.end_datetime else None,
                        "location": e.location,
                    }
                    for e in extraction.events
                ],
            }
            if extraction.events:
                all_events = email_result["events"]
            email_results.append(email_result)
        except Exception as e:
            email_results.append({
                "email_index": i + 1,
                "provider_message_id": email_data.get("provider_message_id", f"email-{i+1}"),
                "error": str(e),
            })

    duration_ms = int((time.time() - start_time) * 1000)

    final_event_count = len(all_events)
    expected_count = expected_final.get("event_count", 0)
    count_match = final_event_count == expected_count

    final_event_score = None
    if expected_final.get("final_event") and all_events:
        final_event_score = auto_score_event(expected_final["final_event"], all_events[0])

    auto_score = {
        "event_count_match": count_match,
        "final_event_score": final_event_score,
        "all_match": count_match and (
            final_event_score is None or final_event_score.get("overall_match", False)
        ),
    }

    return {
        "scenario_name": scenario_name,
        "scenario_path": str(scenario_path),
        "description": scenario.get("description", ""),
        "difficulty": scenario.get("difficulty", "medium"),
        "tags": scenario.get("tags", []),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider_name,
        "model": model_name,
        "thinking": thinking,
        "duration_ms": duration_ms,
        "email_count": len(thread_emails),
        "expected_final_state": expected_final,
        "actual_final_state": {
            "event_count": final_event_count,
            "events": all_events,
        },
        "auto_score": auto_score,
        "email_results": email_results,
    }


# ---------------------------------------------------------------------------
# Legacy single-provider extract eval (for backwards compat with old CLI args)
# ---------------------------------------------------------------------------

def run_single_eval(
    fixture_name: str,
    fixture_path: Path,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run evaluation for a single fixture using DEFAULT_PROVIDER/DEFAULT_MODEL."""
    return run_extract_eval(
        fixture_name, fixture_path, DEFAULT_PROVIDER, DEFAULT_MODEL,
        use_cache=use_cache, verbose=verbose, dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Parallel execution helpers
# ---------------------------------------------------------------------------

class ProgressTracker:
    """Thread-safe progress tracker for parallel fixture execution."""

    def __init__(self, total: int, operation: str):
        self._lock = threading.Lock()
        self._completed = 0
        self._total = total
        self._operation = operation
        self._results: list[dict] = []

    def record(self, result: dict) -> None:
        with self._lock:
            self._completed += 1
            self._results.append(result)
            progress = f"[{self._completed}/{self._total}] "
            print_result_summary(result, progress=progress)
            if self._completed % 10 == 0 or self._completed == self._total:
                _print_progress_totals(self._results, self._operation)

    def record_error(self, name: str, error: str) -> None:
        with self._lock:
            self._completed += 1
            print(
                f"  [{self._completed}/{self._total}] [{self._operation:7}] "
                f"{name:40} [ERROR ] {error}",
                flush=True,
            )

    @property
    def results(self) -> list[dict]:
        with self._lock:
            return list(self._results)


def _run_fixtures_parallel(fixtures, operation, run_fn, concurrency=10):
    """Run fixtures with ThreadPoolExecutor. Sequential if concurrency <= 1."""
    tracker = ProgressTracker(len(fixtures), operation)

    if concurrency <= 1:
        for name, path in fixtures:
            try:
                tracker.record(run_fn(name, path))
            except Exception as e:
                tracker.record_error(name, str(e))
        return tracker.results

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {}
        for name, path in fixtures:
            future = executor.submit(run_fn, name, path)
            futures[future] = name
            time.sleep(0.2)  # Stagger submissions to avoid rate-limit bursts
        for future in as_completed(futures):
            name = futures[future]
            try:
                tracker.record(future.result())
            except Exception as e:
                tracker.record_error(name, str(e))

    return tracker.results


def _print_model_summary(model_name: str, thinking: str, results: list[dict]) -> None:
    """Print a one-line summary after all fixtures for a model/operation complete."""
    if not results:
        return
    op = results[0].get("operation", "?")
    non_dry = [r for r in results if not r.get("dry_run")]
    if not non_dry:
        return
    pass_count = sum(1 for r in non_dry if _get_result_status(r) == "PASS")
    partial_count = sum(1 for r in non_dry if _get_result_status(r) == "PARTIAL")
    fail_count = sum(1 for r in non_dry if _get_result_status(r) in ("FAIL", "ERROR"))
    total_cost = sum(r.get("cost", 0) for r in non_dry)
    # Prefer api_call timing when available
    api_durations = []
    for r in non_dry:
        timing = r.get("timing")
        if timing and timing.get("api_call", {}).get("duration_ms") is not None:
            api_durations.append(timing["api_call"]["duration_ms"])
        else:
            api_durations.append(r.get("duration_ms", 0))
    avg_api = sum(api_durations) // len(api_durations) if api_durations else 0
    total_tok = sum(r.get("tokens", {}).get("total_tokens", 0) or 0 for r in non_dry)
    tok_str = f"{total_tok:,}" if total_tok else "0"
    print(
        f"  >>> {model_name} ({thinking}) {op}: "
        f"{pass_count} pass, {partial_count} partial, {fail_count} fail | "
        f"${total_cost:.4f} | {avg_api}ms avg API | {tok_str} tok",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _get_result_status(result: dict[str, Any]) -> str:
    """Extract PASS/PARTIAL/FAIL status from a result."""
    op = result.get("operation", "extract")
    auto_score = result.get("auto_score", {})
    if op == "extract":
        rating = auto_score.get("auto_rating", 0)
        if rating == 5:
            return "PASS"
        elif rating >= 3:
            return "PARTIAL"
        return "FAIL"
    elif op == "compare":
        return "PASS" if auto_score.get("correct", False) else "FAIL"
    elif op == "merge":
        rating = auto_score.get("auto_rating", "?")
        if isinstance(rating, (int, float)):
            return "PASS" if rating == 5 else ("PARTIAL" if rating >= 3 else "FAIL")
        return "ERROR"
    return "?"


def _print_progress_totals(results: list[dict], operation: str) -> None:
    """Print running totals after each fixture."""
    op_results = [r for r in results if r.get("operation") == operation and not r.get("dry_run")]
    if not op_results:
        return
    pass_count = sum(1 for r in op_results if _get_result_status(r) == "PASS")
    partial_count = sum(1 for r in op_results if _get_result_status(r) == "PARTIAL")
    fail_count = sum(1 for r in op_results if _get_result_status(r) in ("FAIL", "ERROR"))
    total_cost = sum(r.get("cost", 0) for r in op_results)
    total_duration = sum(r.get("duration_ms", 0) for r in op_results)
    avg_duration = total_duration // len(op_results) if op_results else 0
    print(
        f"         Running: {pass_count} pass, {partial_count} partial, "
        f"{fail_count} fail | ${total_cost:.4f} total | {avg_duration}ms avg",
        flush=True,
    )


def _format_timing_detail(result: dict[str, Any]) -> str:
    """Format timing breakdown from result's timing block, falling back to duration_ms."""
    timing = result.get("timing")
    if timing:
        parts = []
        api_ms = timing.get("api_call", {}).get("duration_ms")
        gw_ms = timing.get("gateway_create", {}).get("duration_ms")
        load_ms = timing.get("fixture_load", {}).get("duration_ms")
        if api_ms is not None:
            parts.append(f"{api_ms}ms api")
        if gw_ms is not None and gw_ms > 0:
            parts.append(f"{gw_ms}ms gw")
        if load_ms is not None and load_ms > 0:
            parts.append(f"{load_ms}ms load")
        if parts:
            return ", ".join(parts)
    return f"{result.get('duration_ms', 0)}ms"


def _format_token_detail(result: dict[str, Any]) -> str:
    """Format token counts from result."""
    tokens = result.get("tokens", {})
    prompt = tokens.get("prompt_tokens")
    completion = tokens.get("completion_tokens")
    if prompt is not None and completion is not None:
        return f"{prompt}+{completion}tok"
    return ""


def _format_attachment_detail(result: dict[str, Any]) -> str:
    """Format attachment info from input_summary."""
    summary = result.get("input_summary", {})
    count = summary.get("attachment_count", 0)
    if count == 0:
        return ""
    types = summary.get("attachment_types", [])
    total_bytes = summary.get("total_attachment_bytes", 0)
    img_count = sum(1 for t in types if t == "image")
    text_count = sum(1 for t in types if t == "text")
    if total_bytes >= 1024 * 1024:
        size_str = f"{total_bytes / (1024 * 1024):.1f}MB"
    elif total_bytes >= 1024:
        size_str = f"{total_bytes // 1024}KB"
    else:
        size_str = f"{total_bytes}B"
    parts = []
    if img_count:
        parts.append(f"{img_count} img")
    if text_count:
        parts.append(f"{text_count} txt")
    return f"[{', '.join(parts)}, {size_str}]" if parts else ""


def print_result_summary(result: dict[str, Any], progress: str = "") -> None:
    """Print a one-line summary of a result with timing breakdown, tokens, and attachments.

    Args:
        result: The eval result dict.
        progress: Optional progress prefix like "[3/25] ".
    """
    if result.get("dry_run"):
        valid = result.get("valid", False)
        errors = result.get("errors", [])
        op = result.get("operation", "extract")
        status = "VALID" if valid else "INVALID"
        print(f"  {progress}[{op:7}] {result.get('fixture_name', '?'):40} [{status:7}] (dry-run)", flush=True)
        for err in errors:
            print(f"           - {err}", flush=True)
        return

    op = result.get("operation", "extract")
    auto_score = result.get("auto_score", {})
    cost_str = _format_cost(result.get("cost"))
    status = _get_result_status(result)
    timing_str = _format_timing_detail(result)
    token_str = _format_token_detail(result)
    error_str = ""

    if status in ("FAIL", "ERROR"):
        err = result.get("actual", {}).get("error", "")
        if err:
            error_str = f" | {err[:80]}"

    if op == "extract":
        rating = auto_score.get("auto_rating", "?")
        attach_str = _format_attachment_detail(result)
        extra = " ".join(filter(None, [token_str, attach_str]))
        print(
            f"  {progress}[{op:7}] {result.get('fixture_name', '?'):40} "
            f"[{status:7}] Rating:{rating}/5 "
            f"{cost_str} ({timing_str}) {extra}{error_str}",
            flush=True,
        )
    elif op == "compare":
        extra = token_str
        print(
            f"  {progress}[{op:7}] {result.get('fixture_name', '?'):40} "
            f"[{status:7}] "
            f"{cost_str} ({timing_str}) {extra}{error_str}",
            flush=True,
        )
    elif op == "merge":
        rating = auto_score.get("auto_rating", "?")
        matched = auto_score.get("fields_matched", 0)
        total = auto_score.get("total_fields", 0)
        extra = token_str
        print(
            f"  {progress}[{op:7}] {result.get('fixture_name', '?'):40} "
            f"[{status:7}] Rating:{rating}/5 ({matched}/{total}) "
            f"{cost_str} ({timing_str}) {extra}{error_str}",
            flush=True,
        )


def print_thread_result_summary(result: dict[str, Any]) -> None:
    auto_score = result.get("auto_score", {})
    is_dry_run = auto_score.get("dry_run", False)
    if is_dry_run:
        status = "VALID" if auto_score.get("valid", False) else "INVALID"
    else:
        status = "PASS" if auto_score.get("all_match") else "FAIL"
    email_count = result.get("email_count", 0)
    duration = result.get("duration_ms", 0)
    print(f"  {result['scenario_name']:40} [{status:7}] Emails:{email_count} ({duration}ms)")


def print_detailed_result(result: dict[str, Any]) -> None:
    """Print detailed result for a fixture."""
    print(f"\n{'='*60}")
    print(f"Fixture: {result.get('fixture_name', 'N/A')}")
    print(f"Operation: {result.get('operation', 'extract')}")
    print(f"Provider: {result.get('provider', 'N/A')} / Model: {result.get('model', 'N/A')}")
    print(f"Description: {result.get('description', 'N/A')}")
    print(f"Run at: {result.get('run_at', 'N/A')}")
    print(f"Duration: {result.get('duration_ms', 0)}ms")
    print(f"Cost: {_format_cost(result.get('cost'))}")
    tokens = result.get("tokens", {})
    print(f"Tokens: {tokens.get('prompt_tokens', '?')} prompt + {tokens.get('completion_tokens', '?')} completion")
    print(f"\n--- Expected ---")
    print(json.dumps(result.get("expected", {}), indent=2, default=str))
    print(f"\n--- Actual ---")
    print(json.dumps(result.get("actual", {}), indent=2, default=str))
    print(f"\n--- Auto Score ---")
    print(json.dumps(result.get("auto_score", {}), indent=2, default=str))
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Console report (legacy)
# ---------------------------------------------------------------------------

def generate_report(results: list[dict[str, Any]]) -> None:
    """Generate summary report to console."""
    print("\n" + "=" * 60)
    print("LLM EVALUATION REPORT")
    print("=" * 60)

    total = len(results)
    if total == 0:
        print("No results found.")
        return

    # Group by operation
    by_op: dict[str, list] = {}
    for r in results:
        op = r.get("operation", "extract")
        by_op.setdefault(op, []).append(r)

    for op, op_results in sorted(by_op.items()):
        print(f"\n--- {op.upper()} ({len(op_results)} fixtures) ---")
        if op == "extract":
            pass_count = sum(1 for r in op_results if r.get("auto_score", {}).get("all_events_match"))
            partial = sum(1 for r in op_results if r.get("auto_score", {}).get("events_found_match") and not r.get("auto_score", {}).get("all_events_match"))
            fail = len(op_results) - pass_count - partial
            print(f"  PASS: {pass_count}  PARTIAL: {partial}  FAIL: {fail}")
        elif op == "compare":
            correct = sum(1 for r in op_results if r.get("auto_score", {}).get("correct"))
            print(f"  Correct: {correct}/{len(op_results)} ({100*correct/len(op_results):.1f}%)")
        elif op == "merge":
            avg_rating = sum(r.get("auto_score", {}).get("auto_rating", 0) for r in op_results) / len(op_results)
            print(f"  Avg rating: {avg_rating:.1f}/5")

    known_costs = [r.get("cost") for r in results if isinstance(r.get("cost"), (int, float))]
    total_cost = sum(known_costs) if known_costs else None
    avg_dur = sum(r.get("duration_ms", 0) or 0 for r in results) / total
    print(f"\nTotal cost: {_format_cost(total_cost)}")
    unknown = sum(1 for r in results if r.get("cost") is None)
    if unknown:
        print(f"Unknown-cost cells: {unknown}")
    print(f"Average duration: {avg_dur:.0f}ms")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------

def _format_cost(cost: float | None) -> str:
    if cost is None:
        return "unknown"
    return f"${cost:.4f}"


def plan_eval_cells(
    *,
    operations: list[str],
    models: list[tuple],
    fixtures_by_op: dict[str, list[tuple[str, Path]]],
    store: ArtifactStore | None = None,
) -> list[PlannedCell]:
    """Build HIT/MISS plan cells without calling any provider."""
    store = store or _DEFAULT_STORE
    cells: list[PlannedCell] = []

    for model_tuple in models:
        if len(model_tuple) == 3:
            provider, model, thinking = model_tuple
        else:
            provider, model = model_tuple
            thinking = "low"

        for operation in operations:
            for fixture_name, fixture_path in fixtures_by_op.get(operation, []):
                fixture = load_fixture(fixture_path)
                identity = build_inference_identity(
                    operation=operation,
                    provider=provider,
                    model=model,
                    thinking=thinking,
                    fixture=fixture,
                )
                score_identity = build_score_identity(
                    operation=operation,
                    inference_key=identity.inference_key,
                    fixture=fixture,
                )
                if store.has_inference(identity.inference_key):
                    if store.has_score(score_identity.score_key):
                        state = "HIT"
                        reason = "complete inference+score artifacts"
                    else:
                        state = "HIT"
                        reason = "inference HIT; score MISS (rescore only, zero model calls)"
                else:
                    state = "MISS"
                    reason = "no inference artifact"
                cells.append(
                    PlannedCell(
                        operation=operation,
                        provider=provider,
                        model=model,
                        thinking=normalize_thinking(thinking),
                        fixture_name=fixture_name,
                        inference_key=identity.inference_key,
                        score_key=score_identity.score_key,
                        state=state,
                        reason=reason,
                    )
                )
    return cells


def collect_fixtures_for_operations(
    operations: list[str],
    *,
    all_extract: bool = False,
    category: str | None = None,
    fixture: str | None = None,
    difficulty: str | None = None,
) -> dict[str, list[tuple[str, Path]]]:
    """Resolve fixture lists for the requested operations."""
    by_op: dict[str, list[tuple[str, Path]]] = {}
    if "extract" in operations:
        fixtures = []
        if all_extract or fixture or category:
            fixtures = get_all_fixtures()
            if category:
                fixtures = [(n, p) for n, p in fixtures if n.startswith(category + "/")]
            if fixture:
                fixtures = [(n, p) for n, p in fixtures if n == fixture]
        else:
            fixtures = get_all_fixtures()
        if difficulty:
            fixtures = [
                (n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty
            ]
        by_op["extract"] = fixtures
    if "compare" in operations:
        fixtures = get_compare_fixtures()
        if difficulty:
            fixtures = [
                (n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty
            ]
        by_op["compare"] = fixtures
    if "merge" in operations:
        fixtures = get_merge_fixtures()
        if difficulty:
            fixtures = [
                (n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty
            ]
        by_op["merge"] = fixtures
    return by_op


def write_run_manifest(
    *,
    cells: list[PlannedCell],
    operations: list[str],
    models: list[tuple],
    store: ArtifactStore | None = None,
    run_id: str | None = None,
) -> str:
    store = store or _DEFAULT_STORE
    run_id = run_id or new_run_id()
    manifest = {
        "run_id": run_id,
        "operations": operations,
        "matrix": [
            {
                "provider": m[0],
                "model": m[1],
                "thinking": m[2] if len(m) == 3 else "low",
            }
            for m in models
        ],
        "provenance": code_provenance(),
        "cells": [
            {
                "operation": c.operation,
                "provider": c.provider,
                "model": c.model,
                "thinking": c.thinking,
                "fixture_name": c.fixture_name,
                "inference_key": c.inference_key,
                "score_key": c.score_key,
                "state": c.state,
                "reason": c.reason,
            }
            for c in cells
        ],
    }
    store.write_manifest(run_id, manifest)
    return run_id


def generate_markdown_report(output_path: str, manifest_run_id: str | None = None) -> None:
    """Generate comprehensive markdown report from a run manifest (preferred).

    Without a manifest id, only identity-bearing artifacts under
    results/inference + results/scores are included. Legacy mtime fallback is gone.
    """
    lines = []

    def line(s=""):
        lines.append(s)

    line("# Selko LLM Eval Report")
    line(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    line()

    store = _DEFAULT_STORE
    all_results: list[dict] = []

    if manifest_run_id:
        manifest = store.load_manifest(manifest_run_id)
        if not manifest:
            line(f"*Manifest not found: {manifest_run_id}*")
            Path(output_path).write_text("\n".join(lines))
            return
        line(f"Manifest: `{manifest_run_id}`")
        line()
        for cell in manifest.get("cells", []):
            inference = store.load_inference(cell["inference_key"])
            score = store.load_score(cell["score_key"])
            if inference is None:
                all_results.append(
                    {
                        "fixture_name": cell["fixture_name"],
                        "operation": cell["operation"],
                        "provider": cell["provider"],
                        "model": cell["model"],
                        "thinking": cell.get("thinking", {}).get("value", "low")
                        if isinstance(cell.get("thinking"), dict)
                        else cell.get("thinking", "low"),
                        "auto_score": {"error": f"MISSING ({cell.get('state')})"},
                        "cost": None,
                        "tokens": {},
                        "duration_ms": 0,
                        "missing": True,
                    }
                )
                continue
            combined = build_combined_result(
                inference={**inference, "from_cache": True},
                score=score,
                fixture_name=cell["fixture_name"],
                operation=cell["operation"],
                provider=cell["provider"],
                model=cell["model"],
                thinking=cell.get("thinking", "low"),
            )
            if score is None:
                combined["auto_score"] = {"error": "score missing"}
                combined["missing_score"] = True
            all_results.append(combined)
    else:
        # Scan content-addressed inference artifacts only (no mtime fallback).
        if store.inference_root.exists():
            for path in sorted(store.inference_root.glob("*/*.json")):
                if ".replica-" in path.name or path.name.startswith("."):
                    continue
                try:
                    inference = json.loads(path.read_text())
                except Exception:
                    continue
                identity = inference.get("identity") or {}
                if not identity:
                    continue
                score_key = None
                # Best-effort: find a score for this inference_key
                for score_path in store.scores_root.glob("*/*.json") if store.scores_root.exists() else []:
                    try:
                        score_doc = json.loads(score_path.read_text())
                    except Exception:
                        continue
                    if score_doc.get("identity", {}).get("inference_key") == inference.get(
                        "inference_key"
                    ):
                        score_key = score_doc
                        break
                thinking = identity.get("thinking", {"value": "low"})
                all_results.append(
                    build_combined_result(
                        inference={**inference, "from_cache": True},
                        score=score_key,
                        fixture_name=inference.get("fixture_name", path.stem),
                        operation=identity.get("operation", inference.get("operation", "extract")),
                        provider=identity.get("provider", inference.get("provider", "unknown")),
                        model=identity.get("model", inference.get("model", "unknown")),
                        thinking=thinking,
                    )
                )

    if not all_results:
        line("*No identity-bearing results found. Run evals first.*")
        Path(output_path).write_text("\n".join(lines))
        return

    # Group by model+thinking and operation
    models_seen = set()
    by_model_op: dict[str, dict[str, list]] = {}
    for r in all_results:
        thinking = r.get("thinking", "low")
        model_key = f"{r.get('model', 'unknown')} ({thinking})"
        op = r.get("operation", "extract")
        models_seen.add(model_key)
        by_model_op.setdefault(model_key, {}).setdefault(op, []).append(r)

    models_sorted = sorted(models_seen)

    known_costs = [r.get("cost") for r in all_results if isinstance(r.get("cost"), (int, float))]
    unknown_cost_count = sum(1 for r in all_results if r.get("cost") is None)
    grand_total_cost = sum(known_costs) if known_costs else None
    grand_total_tokens = sum(
        (r.get("tokens") or {}).get("total_tokens", 0) or 0 for r in all_results
    )
    total_evals = len(all_results)
    total_extract = sum(1 for r in all_results if r.get("operation") == "extract")
    total_compare = sum(1 for r in all_results if r.get("operation") == "compare")
    total_merge = sum(1 for r in all_results if r.get("operation") == "merge")
    total_duration_s = sum(r.get("duration_ms", 0) or 0 for r in all_results) / 1000
    code_hashes = set(r.get("code_hash", "") for r in all_results if r.get("code_hash"))
    missing_count = sum(1 for r in all_results if r.get("missing") or r.get("missing_score"))

    line("## Eval Run Overview")
    line()
    line(f"| Metric | Value |")
    line(f"|--------|-------|")
    line(f"| **Total Eval Cost** | **{_format_cost(grand_total_cost)}** |")
    if unknown_cost_count:
        line(f"| Unknown-cost cells | {unknown_cost_count} |")
    if missing_count:
        line(f"| Missing/error cells | {missing_count} |")
    line(f"| Total Evals | {total_evals} ({total_extract} extract, {total_compare} compare, {total_merge} merge) |")
    line(f"| Models Tested | {len(models_sorted)} |")
    line(f"| Total Tokens | {grand_total_tokens:,} |")
    line(f"| Total API Time | {total_duration_s:.0f}s |")
    line(f"| Code Hash | {', '.join(sorted(code_hashes)) if code_hashes else 'N/A'} |")
    line()

    # ---- Model Comparison Table ----
    line("## Model Comparison")
    line()
    line("| Model | Extract | Compare | Merge | Cost | Avg Latency |")
    line("|-------|---------|---------|-------|------|-------------|")

    for model in models_sorted:
        ops = by_model_op.get(model, {})

        extract_results = ops.get("extract", [])
        if extract_results:
            eligible = [r for r in extract_results if not r.get("missing")]
            ext_pass = sum(
                1 for r in eligible if r.get("auto_score", {}).get("all_events_match")
            )
            ext_total = len(eligible)
            ext_str = (
                f"{ext_pass}/{ext_total} ({100 * ext_pass / ext_total:.1f}%)"
                if ext_total
                else "0/0"
            )
        else:
            ext_str = "-"

        compare_results = ops.get("compare", [])
        if compare_results:
            eligible = [r for r in compare_results if not r.get("missing")]
            cmp_correct = sum(1 for r in eligible if r.get("auto_score", {}).get("correct"))
            cmp_total = len(eligible)
            cmp_str = (
                f"{cmp_correct}/{cmp_total} ({100 * cmp_correct / cmp_total:.1f}%)"
                if cmp_total
                else "0/0"
            )
        else:
            cmp_str = "-"

        merge_results = ops.get("merge", [])
        if merge_results:
            eligible = [r for r in merge_results if not r.get("missing")]
            mrg_pass = sum(
                1 for r in eligible if r.get("auto_score", {}).get("auto_rating", 0) == 5
            )
            mrg_total = len(eligible)
            mrg_avg = (
                sum(r.get("auto_score", {}).get("auto_rating", 0) for r in eligible) / mrg_total
                if mrg_total
                else 0
            )
            mrg_str = f"{mrg_pass}/{mrg_total} ({mrg_avg:.1f} avg)"
        else:
            mrg_str = "-"

        all_model = extract_results + compare_results + merge_results
        model_costs = [r.get("cost") for r in all_model if isinstance(r.get("cost"), (int, float))]
        total_cost = sum(model_costs) if model_costs else None
        avg_latency = (
            sum(r.get("duration_ms", 0) or 0 for r in all_model) / len(all_model)
            if all_model
            else 0
        )

        line(
            f"| {model} | {ext_str} | {cmp_str} | {mrg_str} | {_format_cost(total_cost)} | {avg_latency:.0f}ms |"
        )

    line(f"| **TOTAL** | | | | **{_format_cost(grand_total_cost)}** | |")
    line()

    # Keep the remainder of the detailed sections from the previous report body by
    # delegating to the legacy detailed formatter for identity-bearing results.
    _append_detailed_report_sections(line, models_sorted, by_model_op)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines))
    print(f"Report written to {output_path}")


def _append_detailed_report_sections(line, models_sorted, by_model_op) -> None:
    """Append extraction/compare/merge detail tables to a markdown report."""
    line("## Extraction Results")
    line()
    line("### All Fixtures")
    line()
    line("| Model | Pass | Partial | Fail | Avg Rating | Cost |")
    line("|-------|------|---------|------|------------|------|")

    for model in models_sorted:
        results = [
            r for r in by_model_op.get(model, {}).get("extract", []) if not r.get("missing")
        ]
        if not results:
            continue
        pass_count = sum(1 for r in results if r.get("auto_score", {}).get("all_events_match"))
        fail = sum(
            1
            for r in results
            if r.get("auto_score", {}).get("error")
            or (
                not r.get("auto_score", {}).get("events_found_match", True)
                if "events_found_match" in (r.get("auto_score") or {})
                else False
            )
        )
        partial = max(0, len(results) - pass_count - fail)
        ratings = [
            r.get("auto_score", {}).get("auto_rating", 0)
            for r in results
            if r.get("auto_score", {}).get("auto_rating") is not None
        ]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        costs = [r.get("cost") for r in results if isinstance(r.get("cost"), (int, float))]
        cost = sum(costs) if costs else None
        line(
            f"| {model} | {pass_count} | {partial} | {fail} | {avg_rating:.1f}/5 | {_format_cost(cost)} |"
        )
    line()

    line("## Compare Results")
    line()
    line("| Model | Correct | Wrong | Accuracy | Cost |")
    line("|-------|---------|-------|----------|------|")
    for model in models_sorted:
        results = [
            r for r in by_model_op.get(model, {}).get("compare", []) if not r.get("missing")
        ]
        if not results:
            continue
        correct = sum(1 for r in results if r.get("auto_score", {}).get("correct"))
        wrong = len(results) - correct
        accuracy = 100 * correct / len(results) if results else 0
        costs = [r.get("cost") for r in results if isinstance(r.get("cost"), (int, float))]
        cost = sum(costs) if costs else None
        line(
            f"| {model} | {correct} | {wrong} | {accuracy:.1f}% | {_format_cost(cost)} |"
        )
    line()

    line("## Merge Results")
    line()
    line("| Model | Avg Rating | Perfect | Cost |")
    line("|-------|------------|---------|------|")
    for model in models_sorted:
        results = [
            r for r in by_model_op.get(model, {}).get("merge", []) if not r.get("missing")
        ]
        if not results:
            continue
        perfect = sum(1 for r in results if r.get("auto_score", {}).get("auto_rating", 0) == 5)
        avg_rating = (
            sum(r.get("auto_score", {}).get("auto_rating", 0) for r in results) / len(results)
        )
        costs = [r.get("cost") for r in results if isinstance(r.get("cost"), (int, float))]
        cost = sum(costs) if costs else None
        line(
            f"| {model} | {avg_rating:.1f}/5 | {perfect}/{len(results)} | {_format_cost(cost)} |"
        )
    line()


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------

def compare_baseline(hash_a: str | None = None, hash_b: str | None = None) -> None:
    """Compare auto_ratings between two code versions.

    Args:
        hash_a: Previous code hash (optional — auto-selects 2nd most recent).
        hash_b: Current code hash (optional — auto-selects most recent).
    """
    results_base = RESULTS_DIR
    if not results_base.exists():
        print("No results directory found.")
        return

    # Collect all results grouped by code_hash
    by_hash: dict[str, list[dict]] = {}
    for op_dir in sorted(results_base.iterdir()):
        if not op_dir.is_dir() or op_dir.name.startswith("."):
            continue
        for model_dir in sorted(op_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            for fixture_dir in sorted(model_dir.iterdir()):
                if not fixture_dir.is_dir():
                    continue
                for result_file in fixture_dir.glob("result_*.json"):
                    try:
                        with open(result_file) as f:
                            r = json.load(f)
                            code_hash = r.get("code_hash", "")
                            if code_hash:
                                by_hash.setdefault(code_hash, []).append(r)
                    except Exception:
                        pass

    if hash_a and hash_b:
        # Explicit hashes provided
        if hash_a not in by_hash:
            print(f"Code hash not found: {hash_a}")
            print(f"Available hashes: {', '.join(sorted(by_hash.keys()))}")
            return
        if hash_b not in by_hash:
            print(f"Code hash not found: {hash_b}")
            print(f"Available hashes: {', '.join(sorted(by_hash.keys()))}")
            return
        previous_hash = hash_a
        current_hash = hash_b
    else:
        if len(by_hash) < 2:
            print(f"Need at least 2 code versions to compare. Found {len(by_hash)}.")
            if by_hash:
                print(f"Available hashes: {', '.join(sorted(by_hash.keys()))}")
            return

        # Find two most recent versions by newest result timestamp
        version_times = []
        for ch, results in by_hash.items():
            newest = max(r.get("run_at", "") for r in results)
            version_times.append((newest, ch))
        version_times.sort(reverse=True)

        current_hash = version_times[0][1]
        previous_hash = version_times[1][1]

    print(f"Comparing code versions:")
    print(f"  Previous: {previous_hash} ({len(by_hash[previous_hash])} results)")
    print(f"  Current:  {current_hash} ({len(by_hash[current_hash])} results)")

    # prompt_hash comparison
    def get_prompt_hashes_for_version(results: list[dict]) -> set[str]:
        return {r["prompt_hash"] for r in results if r.get("prompt_hash")}

    prev_ph = get_prompt_hashes_for_version(by_hash[previous_hash])
    curr_ph = get_prompt_hashes_for_version(by_hash[current_hash])
    prev_ph_str = ", ".join(sorted(prev_ph)) if prev_ph else "N/A (pre-prompt_hash tracking)"
    curr_ph_str = ", ".join(sorted(curr_ph)) if curr_ph else "N/A (pre-prompt_hash tracking)"
    print(f"  prompt_hash previous: {prev_ph_str}")
    print(f"  prompt_hash current:  {curr_ph_str}")
    if prev_ph and curr_ph and prev_ph == curr_ph:
        print("  => UNCHANGED — scaffolding-only change; score differences are LLM non-determinism")
    elif prev_ph and curr_ph:
        print("  => prompt changed — score differences may reflect prompt improvements or regressions")
    else:
        print("  => prompt_hash not available for one or both versions (pre-tracking results)")
    print()

    # Build lookup: (fixture_name, model, operation) → auto_rating for each version
    def build_lookup(results: list[dict]) -> dict[tuple, int]:
        lookup = {}
        for r in results:
            key = (r.get("fixture_name", ""), r.get("model", ""), r.get("operation", ""))
            op = r.get("operation", "extract")
            if op == "compare":
                rating = 5 if r.get("auto_score", {}).get("correct") else 1
            else:
                rating = r.get("auto_score", {}).get("auto_rating", 0)
            lookup[key] = rating
        return lookup

    previous_lookup = build_lookup(by_hash[previous_hash])
    current_lookup = build_lookup(by_hash[current_hash])

    # Compare and build table
    all_keys = set(current_lookup.keys()) | set(previous_lookup.keys())
    improved = []
    regressed = []
    unchanged = 0
    rows = []

    for key in sorted(all_keys):
        fixture, model, op = key
        curr = current_lookup.get(key)
        prev = previous_lookup.get(key)
        if curr is not None and prev is not None:
            delta = curr - prev
            if delta > 0:
                improved.append((key, prev, curr))
                delta_str = f"+{delta}"
            elif delta < 0:
                regressed.append((key, prev, curr))
                delta_str = str(delta)
            else:
                unchanged += 1
                continue  # Skip unchanged from table
            rows.append((fixture, model, op, prev, curr, delta_str))

    # Print markdown table
    print(f"| {'Fixture':<40} | {'Model':<35} | {'Op':<8} | {'Prev':>4} | {'Curr':>4} | {'Delta':>5} |")
    print(f"|{'-'*42}|{'-'*37}|{'-'*10}|{'-'*6}|{'-'*6}|{'-'*7}|")
    for fixture, model, op, prev, curr, delta_str in rows:
        print(f"| {fixture:<40} | {model:<35} | {op:<8} | {prev:>4} | {curr:>4} | {delta_str:>5} |")
    print()

    print(f"Summary: {len(improved)} improved, {len(regressed)} regressed, {unchanged} unchanged")


# ---------------------------------------------------------------------------
# Legacy display helpers
# ---------------------------------------------------------------------------

def rate_fixture(fixture_name: str) -> None:
    result = load_cached_result(fixture_name)
    if not result:
        print(f"No cached result for {fixture_name}. Run evaluation first.")
        return
    print_detailed_result(result)
    print("Rating scale:")
    for rating, description in RATING_SCALE.items():
        print(f"  {rating}: {description}")
    while True:
        try:
            rating_input = input("\nEnter rating (1-5) or 'skip': ").strip()
            if rating_input.lower() == "skip":
                return
            rating = int(rating_input)
            if 1 <= rating <= 5:
                break
            print("Rating must be between 1 and 5")
        except ValueError:
            print("Invalid input. Enter a number 1-5 or 'skip'")
    notes = input("Notes (optional): ").strip() or None
    result["manual_rating"] = rating
    result["manual_notes"] = notes
    result["rated_at"] = datetime.now(timezone.utc).isoformat()
    save_result(fixture_name, result)
    print(f"Rating saved: {rating}/5")


def clear_cache() -> None:
    """Clear all cached results (both legacy and new structure)."""
    import shutil
    count = 0
    # Legacy flat files
    for result_file in RESULTS_DIR.glob("*.json"):
        result_file.unlink()
        count += 1
    # New directory structure
    for op_dir in RESULTS_DIR.iterdir():
        if op_dir.is_dir() and op_dir.name != ".gitignore":
            shutil.rmtree(op_dir)
            count += 1
    print(f"Cleared {count} cached results/directories")


def export_results(output_path: str) -> None:
    """Export all results to CSV."""
    import csv

    results = []
    for result_file in RESULTS_DIR.glob("*.json"):
        with open(result_file) as f:
            results.append(json.load(f))

    if not results:
        print("No results to export")
        return

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "fixture_name", "category", "difficulty",
            "events_found_expected", "events_found_actual",
            "event_count_expected", "event_count_actual",
            "auto_rating", "manual_rating", "duration_ms", "run_at",
        ])
        for r in sorted(results, key=lambda x: x.get("fixture_name", "")):
            expected = r.get("expected", {})
            actual = r.get("actual", {})
            auto_score = r.get("auto_score", {})
            writer.writerow([
                r.get("fixture_name", ""),
                r.get("category", ""),
                r.get("difficulty", ""),
                expected.get("events_found", ""),
                actual.get("events_found", ""),
                expected.get("event_count", len(expected.get("events", []))),
                len(actual.get("events", [])),
                auto_score.get("auto_rating", ""),
                r.get("manual_rating", ""),
                r.get("duration_ms", ""),
                r.get("run_at", ""),
            ])

    print(f"Exported {len(results)} results to {output_path}")


# ---------------------------------------------------------------------------
# Multi-model orchestrator
# ---------------------------------------------------------------------------

def run_all_models(
    operations: list[str],
    difficulty: str | None = None,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    models: list[tuple] | None = None,
    concurrency: int = 10,
) -> list[dict]:
    """Run evals across multiple models and operations."""
    from selko.services.llm_provider import MODEL_REGISTRY

    eval_models = models or EVAL_MODELS
    all_results = []

    for model_tuple in eval_models:
        # Support both 2-tuples (provider, model) and 3-tuples (provider, model, thinking)
        if len(model_tuple) == 3:
            provider_name, model_name, thinking = model_tuple
        else:
            provider_name, model_name = model_tuple
            thinking = "low"

        model_info = MODEL_REGISTRY.get(model_name, {})
        supports_vision = model_info.get("vision", False)

        print(f"\n{'='*60}")
        print(f"Model: {model_name} (provider: {provider_name}, thinking: {thinking}, vision: {supports_vision})")
        print(f"{'='*60}")

        if "extract" in operations:
            fixtures = get_all_fixtures()
            if difficulty:
                fixtures = [(n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty]

            # Skip image fixtures for text-only models
            if not supports_vision:
                filtered = []
                for name, path in fixtures:
                    fixture = load_fixture(path)
                    if not fixture_requires_vision(fixture):
                        filtered.append((name, path))
                    elif verbose:
                        print(f"  [skip] {name} (requires vision)")
                skipped = len(fixtures) - len(filtered)
                fixtures = filtered
                if skipped:
                    print(f"  Skipping {skipped} image fixtures (text-only model)")

            total = len(fixtures)
            print(f"\n  Extract: {total} fixtures (concurrency: {concurrency})")
            print(f"  {'-'*50}")

            def _run_extract(name, path):
                return run_extract_eval(
                    name, path, provider_name, model_name,
                    use_cache=use_cache, verbose=verbose, dry_run=dry_run,
                    thinking=thinking,
                )

            model_extract_results = _run_fixtures_parallel(fixtures, "extract", _run_extract, concurrency)
            all_results.extend(model_extract_results)
            if not dry_run:
                _print_model_summary(model_name, thinking, model_extract_results)

        if "compare" in operations:
            fixtures = get_compare_fixtures()
            if difficulty:
                fixtures = [(n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty]
            total = len(fixtures)
            print(f"\n  Compare: {total} fixtures (concurrency: {concurrency})")
            print(f"  {'-'*50}")

            def _run_compare(name, path):
                return run_compare_eval(
                    name, path, provider_name, model_name,
                    use_cache=use_cache, verbose=verbose, dry_run=dry_run,
                    thinking=thinking,
                )

            model_compare_results = _run_fixtures_parallel(fixtures, "compare", _run_compare, concurrency)
            all_results.extend(model_compare_results)
            if not dry_run:
                _print_model_summary(model_name, thinking, model_compare_results)

        if "merge" in operations:
            fixtures = get_merge_fixtures()
            if difficulty:
                fixtures = [(n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty]
            total = len(fixtures)
            print(f"\n  Merge: {total} fixtures (concurrency: {concurrency})")
            print(f"  {'-'*50}")

            def _run_merge(name, path):
                return run_merge_eval(
                    name, path, provider_name, model_name,
                    use_cache=use_cache, verbose=verbose, dry_run=dry_run,
                    thinking=thinking,
                )

            model_merge_results = _run_fixtures_parallel(fixtures, "merge", _run_merge, concurrency)
            all_results.extend(model_merge_results)
            if not dry_run:
                _print_model_summary(model_name, thinking, model_merge_results)

    return all_results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _handle_show_trace(args) -> None:
    """Load and pretty-print the trace from a cached result."""
    fixture_name = args.show_trace
    provider = args.provider or DEFAULT_PROVIDER
    model = args.model or DEFAULT_MODEL
    thinking = args.thinking

    # Try all 3 operations and show whichever exists
    found = False
    for operation in ("extract", "compare", "merge"):
        result = get_latest_result(operation, provider, model, fixture_name, thinking)
        if result:
            found = True
            trace = result.get("trace")
            print(f"\n{'='*60}")
            print(f"Trace: {fixture_name}")
            print(f"Operation: {operation} | Provider: {provider} | Model: {model} | Thinking: {thinking}")
            print(f"Run at: {result.get('run_at', 'N/A')}")
            print(f"{'='*60}")
            if trace:
                print(json.dumps(trace, indent=2, default=str))
            else:
                print("(no trace data — result was cached before tracing was enabled)")
            print(f"{'='*60}\n")

    if not found:
        print(f"No result found for fixture '{fixture_name}' with {provider}/{model} (thinking={thinking})")
        print("Check fixture name and ensure you've run the eval for this model.")


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LLM Evaluation Runner — Multi-Model, Multi-Operation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run all extractions (default model):
    uv run python -m backend.tests.eval.run_eval --all

  Run all operations, all models:
    uv run python -m backend.tests.eval.run_eval --all --all-operations --all-models

  Run with concurrency (default 10):
    uv run python -m backend.tests.eval.run_eval --all --concurrency 10

  Run sequentially:
    uv run python -m backend.tests.eval.run_eval --all --concurrency 1

  Dry-run all operations:
    uv run python -m backend.tests.eval.run_eval --all --all-operations --dry-run

  Generate markdown report:
    uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/REPORT.md

  Run compare only:
    uv run python -m backend.tests.eval.run_eval --compare

  Run merge only:
    uv run python -m backend.tests.eval.run_eval --merge

  Use a specific model:
    uv run python -m backend.tests.eval.run_eval --all --provider moonshot --model kimi-k2.5

  Show trace (schema, response, traceback) for a fixture:
    uv run python -m backend.tests.eval.run_eval --show-trace invitations/baby_shower_04 --provider gemini --model gemini-3-flash-preview --thinking none

  Plan cache hits/misses without API calls:
    uv run python -m backend.tests.eval.run_eval --all --all-operations --plan

  Intentional nondeterminism study (does not overwrite canonical cache):
    uv run python -m backend.tests.eval.run_eval --fixture invitations/birthday_party_01 --replicate 1

  Generate markdown report from a run manifest:
    uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/reports/out.md --manifest <run_id>
        """,
    )

    # Run options
    parser.add_argument("--all", action="store_true", help="Run all extraction fixtures")
    parser.add_argument("--category", type=str, help="Run extraction fixtures in category")
    parser.add_argument("--fixture", type=str, help="Run single extraction fixture (category/name)")
    parser.add_argument("--threads", action="store_true", help="Run thread scenarios")
    parser.add_argument("--compare", action="store_true", help="Run compare (dedup) fixtures")
    parser.add_argument("--merge", action="store_true", help="Run merge fixtures")
    parser.add_argument("--all-operations", action="store_true", help="Run extract + compare + merge")
    parser.add_argument("--all-models", action="store_true", help="Run evals for all 6 default models")
    parser.add_argument(
        "--difficulty", type=str, choices=DIFFICULTY_LEVELS, help="Filter by difficulty"
    )

    # Cache options — cache is always on for canonical keys; no overwrite path.
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print HIT/MISS plan for the requested matrix without provider calls",
    )
    parser.add_argument(
        "--replicate",
        type=int,
        metavar="N",
        help="Write a side replica artifact for nondeterminism studies (never overwrites canonical)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=argparse.SUPPRESS,  # deprecated; kept so old scripts fail loudly below
    )
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached results")

    # View options
    parser.add_argument("--report", action="store_true", help="Show console summary report")
    parser.add_argument("--report-md", type=str, help="Generate markdown report to file")
    parser.add_argument(
        "--manifest",
        type=str,
        help="Run manifest id for --report-md (preferred; avoids mixed populations)",
    )
    parser.add_argument("--show", type=str, help="Show detailed result for fixture")
    parser.add_argument("--show-trace", type=str, metavar="FIXTURE_NAME",
                        help="Show full trace (schema, response, traceback) for a fixture result. Requires --provider/--model/--thinking.")
    parser.add_argument("--export", type=str, help="Export results to CSV file")
    parser.add_argument("--list", action="store_true", help="List all available fixtures")

    # Rating options
    parser.add_argument("--rate", nargs="?", const="all", help="Rate results interactively")

    # Provider options
    parser.add_argument("--provider", type=str, help="LLM provider override")
    parser.add_argument("--model", type=str, help="LLM model ID override")
    parser.add_argument(
        "--thinking", type=str, default="low",
        choices=["none", "low", "medium"],
        help="Thinking/reasoning level (default: low)",
    )

    # Concurrency options
    parser.add_argument(
        "--concurrency", type=int, default=10,
        help="Max concurrent fixture runs per model (default: 10, use 1 for sequential)",
    )

    # Model filtering
    parser.add_argument(
        "--skip-models", type=str, default="",
        help="Comma-separated list of provider names to skip (e.g., moonshot,zai)",
    )

    # Preflight
    parser.add_argument(
        "--preflight", action="store_true",
        help="Run one cheap API call per model to validate credentials before full eval",
    )
    parser.add_argument(
        "--no-preflight", action="store_true",
        help="Skip automatic preflight check",
    )

    # Validation and baseline
    parser.add_argument("--validate", action="store_true", help="Validate all fixture schemas")
    parser.add_argument("--compare-baseline", action="store_true", help="Compare latest vs previous code version results")
    parser.add_argument("--compare-hash", nargs=2, metavar=("PREV", "CURR"),
                        help="Compare specific code hashes (e.g., --compare-hash abc123 def456)")

    # Output options
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Validate fixtures without calling LLM")

    args = parser.parse_args()

    if args.no_cache:
        print(
            "ERROR: --no-cache is removed. Canonical inference artifacts are immutable.\n"
            "Use --replicate N for intentional nondeterminism studies, or --plan to inspect cache state.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Apply provider/model overrides
    import backend.tests.eval.eval_config as eval_cfg
    if args.provider:
        eval_cfg.DEFAULT_PROVIDER = args.provider
    if args.model:
        eval_cfg.DEFAULT_MODEL = args.model

    # Handle validate
    if args.validate:
        print("Validating all fixtures...")
        warnings = validate_fixtures()
        if warnings:
            print(f"\n{len(warnings)} warning(s):")
            for w in warnings:
                print(f"  - {w}")
            sys.exit(1)
        else:
            print("All fixtures valid.")
        return

    # Handle compare-baseline / compare-hash
    if args.compare_hash:
        compare_baseline(hash_a=args.compare_hash[0], hash_b=args.compare_hash[1])
        return
    if args.compare_baseline:
        compare_baseline()
        return

    # Handle list
    if args.list:
        fixtures = get_all_fixtures()
        print(f"\nExtraction fixtures ({len(fixtures)} total):\n")
        for name, path in fixtures:
            fixture = load_fixture(path)
            diff = fixture.get("difficulty", "?")
            desc = fixture.get("description", "")[:50]
            print(f"  {name:40} [{diff:6}] {desc}")

        compare = get_compare_fixtures()
        print(f"\nCompare fixtures ({len(compare)}):")
        for name, path in compare:
            fixture = load_fixture(path)
            desc = fixture.get("description", "")[:60]
            print(f"  {name:40} {desc}")

        merge = get_merge_fixtures()
        print(f"\nMerge fixtures ({len(merge)}):")
        for name, path in merge:
            fixture = load_fixture(path)
            desc = fixture.get("description", "")[:60]
            print(f"  {name:40} {desc}")

        threads = get_thread_scenarios()
        if threads:
            print(f"\nThread scenarios ({len(threads)}):")
            for name, path in threads:
                print(f"  {name}")
        return

    # Handle clear cache
    if args.clear_cache:
        clear_cache()
        return

    # Handle report
    if args.report:
        results = []
        for result_file in RESULTS_DIR.glob("*.json"):
            with open(result_file) as f:
                results.append(json.load(f))
        generate_report(results)
        return

    # Handle markdown report
    if args.report_md:
        generate_markdown_report(args.report_md, manifest_run_id=args.manifest)
        return

    # Determine operations early (shared by --plan and runners)
    operations = []
    if args.all_operations:
        operations = ["extract", "compare", "merge"]
    else:
        if args.all or args.category or args.fixture:
            operations.append("extract")
        if args.compare:
            operations.append("compare")
        if args.merge:
            operations.append("merge")

    # Handle --plan (zero provider calls)
    if args.plan:
        if not operations:
            operations = ["extract"]
        if args.all_models:
            models = list(EVAL_MODELS)
            if args.skip_models:
                skip_set = {s.strip().lower() for s in args.skip_models.split(",")}
                models = [m for m in models if m[0].lower() not in skip_set]
        else:
            models = [(eval_cfg.DEFAULT_PROVIDER, eval_cfg.DEFAULT_MODEL, args.thinking)]
        fixtures_by_op = collect_fixtures_for_operations(
            operations,
            all_extract=bool(args.all or args.all_operations or args.fixture or args.category),
            category=args.category,
            fixture=args.fixture,
            difficulty=args.difficulty,
        )
        # --all without category/fixture still means all extract fixtures
        if "extract" in operations and not fixtures_by_op.get("extract") and (
            args.all or args.all_operations
        ):
            fixtures_by_op["extract"] = get_all_fixtures()
        cells = plan_eval_cells(
            operations=operations,
            models=models,
            fixtures_by_op=fixtures_by_op,
        )
        run_id = write_run_manifest(cells=cells, operations=operations, models=models)
        print(format_plan_table(cells))
        print(f"\nManifest written: {run_id}")
        print("Provider calls: 0")
        return

    # Handle show
    if args.show:
        result = load_cached_result(args.show)
        if result:
            print_detailed_result(result)
        else:
            print(f"No cached result for {args.show}")
        return

    # Handle show-trace
    if args.show_trace:
        _handle_show_trace(args)
        return

    # Handle export
    if args.export:
        export_results(args.export)
        return

    # Handle rate
    if args.rate:
        if args.rate == "all":
            for result_file in sorted(RESULTS_DIR.glob("*.json")):
                with open(result_file) as f:
                    result = json.load(f)
                if result.get("manual_rating") is None:
                    rate_fixture(result["fixture_name"])
                    continue_rating = input("\nContinue rating? (y/n): ").strip().lower()
                    if continue_rating != "y":
                        break
        else:
            rate_fixture(args.rate)
        return

    # Determine operations to run
    operations = []
    if args.all_operations:
        operations = ["extract", "compare", "merge"]
    else:
        if args.all or args.category or args.fixture:
            operations.append("extract")
        if args.compare:
            operations.append("compare")
        if args.merge:
            operations.append("merge")

    # Handle preflight-only mode
    if args.preflight and not args.all_models and not args.all:
        filtered_models = list(EVAL_MODELS)
        if args.skip_models:
            skip_set = {s.strip().lower() for s in args.skip_models.split(",")}
            filtered_models = [m for m in filtered_models if m[0].lower() not in skip_set]
        run_preflight(filtered_models)
        return

    # Multi-model mode
    if args.all_models:
        if not operations:
            operations = ["extract", "compare", "merge"]

        # Apply --skip-models filter
        filtered_models = list(EVAL_MODELS)
        if args.skip_models:
            skip_set = {s.strip().lower() for s in args.skip_models.split(",")}
            before = len(filtered_models)
            filtered_models = [m for m in filtered_models if m[0].lower() not in skip_set]
            skipped = before - len(filtered_models)
            if skipped:
                print(f"Skipping {skipped} model configs (providers: {args.skip_models})")

        # Run preflight unless --no-preflight
        if not args.no_preflight and not args.dry_run:
            if not run_preflight(filtered_models):
                print("Aborting due to preflight failures. Use --no-preflight to skip.")
                sys.exit(1)

        use_cache = True
        results = run_all_models(
            operations=operations,
            difficulty=args.difficulty,
            use_cache=use_cache,
            verbose=args.verbose,
            dry_run=args.dry_run,
            models=filtered_models,
            concurrency=args.concurrency,
        )
        if not args.dry_run:
            generate_report(results)
        return

    # Single-model mode with specific provider/model
    provider = eval_cfg.DEFAULT_PROVIDER
    model = eval_cfg.DEFAULT_MODEL

    # Handle threads (legacy)
    if args.threads:
        threads = get_thread_scenarios()
        if not threads:
            print("No thread scenarios found")
            sys.exit(0)
        use_cache = True
        dry_run = args.dry_run
        print(f"\nRunning {len(threads)} thread scenarios...")
        if dry_run:
            print("(dry-run mode)")
        print("-" * 60)
        thread_results = []
        for name, path in threads:
            try:
                result = run_thread_eval(
                    name, path, use_cache=use_cache, verbose=args.verbose, dry_run=dry_run,
                    provider_name=provider, model_name=model, thinking=args.thinking,
                )
                thread_results.append(result)
                print_thread_result_summary(result)
            except Exception as e:
                print(f"  {name:40} [ERROR] {e}")
        print("-" * 60)
        passed = sum(1 for r in thread_results if r.get("auto_score", {}).get("all_match") or r.get("auto_score", {}).get("valid"))
        print(f"Thread scenarios: {passed}/{len(thread_results)} passed")
        sys.exit(0)

    # Run operations
    use_cache = True
    all_results = []

    if "extract" in operations:
        fixtures_to_run = []
        if args.all or args.all_operations:
            fixtures_to_run = get_all_fixtures()
        elif args.category:
            all_fixtures = get_all_fixtures()
            fixtures_to_run = [(n, p) for n, p in all_fixtures if n.startswith(args.category + "/")]
        elif args.fixture:
            all_fixtures = get_all_fixtures()
            for name, path in all_fixtures:
                if name == args.fixture:
                    fixtures_to_run = [(name, path)]
                    break
            if not fixtures_to_run:
                print(f"Fixture not found: {args.fixture}")
                sys.exit(1)

        if args.difficulty:
            fixtures_to_run = [(n, p) for n, p in fixtures_to_run if load_fixture(p).get("difficulty") == args.difficulty]

        if fixtures_to_run:
            total = len(fixtures_to_run)
            print(f"\nRunning {total} extraction fixtures ({provider}/{model}, concurrency: {args.concurrency})...")
            if args.dry_run:
                print("(dry-run mode)")
            print("-" * 60)

            def _run_extract_single(name, path):
                return run_extract_eval(
                    name, path, provider, model,
                    use_cache=use_cache, verbose=args.verbose, dry_run=args.dry_run,
                    thinking=args.thinking, replicate=args.replicate,
                )

            extract_results = _run_fixtures_parallel(fixtures_to_run, "extract", _run_extract_single, args.concurrency)
            all_results.extend(extract_results)

    if "compare" in operations:
        fixtures_to_run = get_compare_fixtures()
        if args.difficulty:
            fixtures_to_run = [(n, p) for n, p in fixtures_to_run if load_fixture(p).get("difficulty") == args.difficulty]
        if fixtures_to_run:
            total = len(fixtures_to_run)
            print(f"\nRunning {total} compare fixtures ({provider}/{model}, concurrency: {args.concurrency})...")
            if args.dry_run:
                print("(dry-run mode)")
            print("-" * 60)

            def _run_compare_single(name, path):
                return run_compare_eval(
                    name, path, provider, model,
                    use_cache=use_cache, verbose=args.verbose, dry_run=args.dry_run,
                    thinking=args.thinking, replicate=args.replicate,
                )

            compare_results = _run_fixtures_parallel(fixtures_to_run, "compare", _run_compare_single, args.concurrency)
            all_results.extend(compare_results)

    if "merge" in operations:
        fixtures_to_run = get_merge_fixtures()
        if args.difficulty:
            fixtures_to_run = [(n, p) for n, p in fixtures_to_run if load_fixture(p).get("difficulty") == args.difficulty]
        if fixtures_to_run:
            total = len(fixtures_to_run)
            print(f"\nRunning {total} merge fixtures ({provider}/{model}, concurrency: {args.concurrency})...")
            if args.dry_run:
                print("(dry-run mode)")
            print("-" * 60)

            def _run_merge_single(name, path):
                return run_merge_eval(
                    name, path, provider, model,
                    use_cache=use_cache, verbose=args.verbose, dry_run=args.dry_run,
                    thinking=args.thinking, replicate=args.replicate,
                )

            merge_results = _run_fixtures_parallel(fixtures_to_run, "merge", _run_merge_single, args.concurrency)
            all_results.extend(merge_results)

    if not operations and not args.threads:
        parser.print_help()
        sys.exit(0)

    # Summary
    if all_results and not args.dry_run:
        generate_report(all_results)
    elif args.dry_run and all_results:
        print("-" * 60)
        valid = sum(1 for r in all_results if r.get("valid", False))
        invalid = len(all_results) - valid
        print(f"Dry-run complete: {valid} valid, {invalid} invalid fixtures")
        # Also run fixture schema validation during dry-run
        schema_warnings = validate_fixtures()
        if schema_warnings:
            print(f"\nFixture schema warnings ({len(schema_warnings)}):")
            for w in schema_warnings:
                print(f"  - {w}")


if __name__ == "__main__":
    main()
