#!/usr/bin/env python3
"""
LLM Evaluation Runner — Multi-Model, Multi-Operation, Cost Tracking

Comprehensive eval framework for testing all 3 LLM operations (extract, compare, merge)
across 6 default models (one per provider) with idempotent caching and cost analysis.

Run with: uv run python -m backend.tests.eval.run_eval --help
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def get_fixture_hash(fixture_path: Path) -> str:
    """SHA256 hash of a fixture file's content."""
    return hashlib.sha256(fixture_path.read_bytes()).hexdigest()


def get_code_hash() -> str:
    """Short SHA256 hash of event_processing.py (production prompts/schemas)."""
    code_path = EVENT_PROCESSING_PATH.resolve()
    if not code_path.exists():
        return "unknown"
    return hashlib.sha256(code_path.read_bytes()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def estimate_cost(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float:
    """Calculate cost in USD using MODEL_REGISTRY pricing (per 1M tokens)."""
    from selko.services.llm_provider import MODEL_REGISTRY

    if prompt_tokens is None or completion_tokens is None:
        return 0.0
    entry = MODEL_REGISTRY.get(model, {})
    pricing = entry.get("pricing", {"input": 0, "output": 0})
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Per-model result path helpers
# ---------------------------------------------------------------------------

def get_result_path(operation: str, provider: str, model: str, fixture_name: str, code_hash: str) -> Path:
    """Get path for a result file: results/{op}/{provider}_{model}/{fixture}/result_{code_hash}.json"""
    safe_name = fixture_name.replace("/", "_")
    model_dir = f"{provider}_{model}"
    return RESULTS_DIR / operation / model_dir / safe_name / f"result_{code_hash}.json"


def get_latest_result(operation: str, provider: str, model: str, fixture_name: str) -> dict | None:
    """Get the most recent result file for a fixture (by mtime)."""
    safe_name = fixture_name.replace("/", "_")
    model_dir = f"{provider}_{model}"
    result_dir = RESULTS_DIR / operation / model_dir / safe_name
    if not result_dir.exists():
        return None
    results = sorted(result_dir.glob("result_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not results:
        return None
    with open(results[0]) as f:
        return json.load(f)


def should_run(fixture_path: Path, operation: str, provider: str, model: str, fixture_name: str) -> bool:
    """Check if eval needs to run (cache miss or hash mismatch)."""
    code_hash = get_code_hash()
    result_path = get_result_path(operation, provider, model, fixture_name, code_hash)
    if not result_path.exists():
        return True
    try:
        cached = json.loads(result_path.read_text())
        return cached.get("fixture_hash") != get_fixture_hash(fixture_path)
    except Exception:
        return True


def save_result_new(result: dict, operation: str, provider: str, model: str, fixture_name: str) -> None:
    """Save result to the new per-model directory structure."""
    code_hash = result.get("code_hash", get_code_hash())
    result_path = get_result_path(operation, provider, model, fixture_name, code_hash)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)


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
        for fmt in [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
        ]:
            try:
                dt1 = datetime.strptime(t1.replace("Z", ""), fmt.replace("Z", "").replace("%z", ""))
                dt2 = datetime.strptime(t2.replace("Z", ""), fmt.replace("Z", "").replace("%z", ""))
                return abs((dt1 - dt2).total_seconds() / 60)
            except ValueError:
                continue
        return None
    except Exception:
        return None


def auto_score_event(expected: dict, actual: dict) -> dict[str, Any]:
    """Auto-score a single event extraction."""
    scores = {}

    title_sim = string_similarity(expected.get("title"), actual.get("title"))
    scores["title"] = {
        "similarity": title_sim,
        "match": title_sim >= AUTO_SCORE_THRESHOLDS["title_similarity"],
    }

    start_diff = time_difference_minutes(
        expected.get("start_datetime"), actual.get("start_datetime")
    )
    scores["start_datetime"] = {
        "difference_minutes": start_diff,
        "match": start_diff is not None
        and start_diff <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"],
    }

    end_diff = time_difference_minutes(
        expected.get("end_datetime"), actual.get("end_datetime")
    )
    scores["end_datetime"] = {
        "difference_minutes": end_diff,
        "match": end_diff is None
        or end_diff <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"],
    }

    loc_sim = string_similarity(expected.get("location"), actual.get("location"))
    scores["location"] = {
        "similarity": loc_sim,
        "match": loc_sim >= AUTO_SCORE_THRESHOLDS["location_similarity"],
    }

    actual_confidence = actual.get("confidence", 0)
    min_confidence = expected.get("confidence_min", AUTO_SCORE_THRESHOLDS["confidence_min"])
    scores["confidence"] = {
        "actual": actual_confidence,
        "required_min": min_confidence,
        "match": actual_confidence >= min_confidence,
    }

    # Importance (soft match — tracked for reporting but doesn't affect overall_match)
    expected_importance = expected.get("importance")
    actual_importance = actual.get("importance")
    if expected_importance is not None:
        scores["importance"] = {
            "expected": expected_importance,
            "actual": actual_importance,
            "match": expected_importance == actual_importance,
        }

    scores["overall_match"] = all(
        s.get("match", True)
        for key, s in scores.items()
        if isinstance(s, dict) and key != "importance"  # importance is soft
    )

    return scores


def auto_score_result(expected: dict, actual: dict) -> dict[str, Any]:
    """Auto-score the full extraction result."""
    scores = {
        "events_found_match": expected.get("events_found")
        == actual.get("events_found"),
        "event_count_match": expected.get("event_count", len(expected.get("events", [])))
        == len(actual.get("events", [])),
    }

    expected_events = expected.get("events", [])
    actual_events = actual.get("events", [])

    if expected_events and actual_events:
        event_scores = []
        for i, exp_event in enumerate(expected_events):
            if i < len(actual_events):
                event_scores.append(auto_score_event(exp_event, actual_events[i]))
            else:
                event_scores.append({"missing": True, "overall_match": False})
        for i in range(len(expected_events), len(actual_events)):
            event_scores.append({"extra": True, "overall_match": False})
        scores["event_scores"] = event_scores
        scores["all_events_match"] = all(
            es.get("overall_match", False) for es in event_scores
        )
    else:
        scores["all_events_match"] = not expected_events and not actual_events

    if scores["events_found_match"] and scores["event_count_match"] and scores.get("all_events_match"):
        scores["auto_rating"] = 5
    elif scores["events_found_match"] and scores["event_count_match"]:
        scores["auto_rating"] = 4
    elif scores["events_found_match"]:
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
    start_match = start_diff is not None and start_diff <= MERGE_SCORE_THRESHOLDS["time_tolerance_minutes"]
    scores["start_datetime"] = {"difference_minutes": start_diff, "match": start_match}
    if start_match:
        fields_matched += 1

    # End datetime
    total_fields += 1
    end_diff = time_difference_minutes(
        expected.get("end_datetime"), actual.get("end_datetime")
    )
    end_match = end_diff is None or end_diff <= MERGE_SCORE_THRESHOLDS["time_tolerance_minutes"]
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

def _create_gateway(provider_name: str, model_name: str):
    """Create a provider + gateway for a specific model."""
    from selko.config import load_config
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import create_provider

    config = load_config()
    config.llm_provider = provider_name
    config.llm_model = model_name
    provider = create_provider(config)
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


# ---------------------------------------------------------------------------
# Extract eval runner
# ---------------------------------------------------------------------------

def run_extract_eval(
    fixture_name: str,
    fixture_path: Path,
    provider_name: str,
    model_name: str,
    use_cache: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run extraction evaluation for a single fixture."""
    fixture = load_fixture(fixture_path)

    # Cache check
    if use_cache and not dry_run and not should_run(fixture_path, "extract", provider_name, model_name, fixture_name):
        cached = get_latest_result("extract", provider_name, model_name, fixture_name)
        if cached:
            if verbose:
                print(f"  [cached] {fixture_name}")
            return cached

    input_data = fixture["input"]
    expected = fixture["expected"]

    # Load attachments
    attachments = []
    attachment_errors = []
    for att_ref in input_data.get("attachments", []):
        if isinstance(att_ref, str):
            try:
                name, content = load_attachment(att_ref)
                attachments.append({
                    "filename": name,
                    "data": content,
                    "mime_type": _guess_mime_type(name),
                })
            except FileNotFoundError as e:
                attachment_errors.append(str(e))
                if not dry_run:
                    print(f"  Warning: {e}")

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

    gateway = _create_gateway(provider_name, model_name)

    email_metadata = {
        "subject": input_data.get("subject", ""),
        "from_name": input_data.get("from_name", ""),
        "from_email": input_data.get("from_email", ""),
        "date_sent": input_data.get("date_sent", ""),
    }

    start_time = time.time()
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
                    "location": e.location,
                    "description": e.description,
                    "confidence": e.confidence,
                    "importance": getattr(e, "importance", None),
                }
                for e in extraction.events
            ],
        }
        error = None
    except Exception as e:
        actual = {"events_found": False, "events": [], "error": str(e)}
        error = str(e)

    duration_ms = int((time.time() - start_time) * 1000)

    # Get token info from gateway's last response
    prompt_tokens = getattr(gateway, '_last_prompt_tokens', None)
    completion_tokens = getattr(gateway, '_last_completion_tokens', None)

    auto_score = auto_score_result(expected, actual) if not error else {"error": error}

    result = {
        "fixture_name": fixture_name,
        "fixture_hash": get_fixture_hash(fixture_path),
        "code_hash": get_code_hash(),
        "operation": "extract",
        "provider": provider_name,
        "model": model_name,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "category": fixture.get("category", fixture_name.split("/")[0]),
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "input_summary": {
            "subject": input_data.get("subject", ""),
            "from": input_data.get("from_email", ""),
            "has_attachments": bool(attachments),
            "attachment_count": len(attachments),
        },
        "expected": expected,
        "actual": actual,
        "auto_score": auto_score,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0),
        },
        "cost": estimate_cost(model_name, prompt_tokens, completion_tokens),
    }

    save_result_new(result, "extract", provider_name, model_name, fixture_name)
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
) -> dict[str, Any]:
    """Run compare (dedup) evaluation for a single fixture."""
    fixture = load_fixture(fixture_path)

    if use_cache and not dry_run and not should_run(fixture_path, "compare", provider_name, model_name, fixture_name):
        cached = get_latest_result("compare", provider_name, model_name, fixture_name)
        if cached:
            if verbose:
                print(f"  [cached] {fixture_name}")
            return cached

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

    gateway = _create_gateway(provider_name, model_name)

    new_event = input_data["new_event"]
    candidate_events = input_data["candidate_events"]

    start_time = time.time()
    try:
        matched_id = compare_events(gateway, new_event, candidate_events)
        error = None
    except Exception as e:
        matched_id = None
        error = str(e)

    duration_ms = int((time.time() - start_time) * 1000)

    prompt_tokens = getattr(gateway, '_last_prompt_tokens', None)
    completion_tokens = getattr(gateway, '_last_completion_tokens', None)

    auto_score = score_compare_result(expected, matched_id) if not error else {"error": error}

    result = {
        "fixture_name": fixture_name,
        "fixture_hash": get_fixture_hash(fixture_path),
        "code_hash": get_code_hash(),
        "operation": "compare",
        "provider": provider_name,
        "model": model_name,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "expected": expected,
        "actual": {"matched_event_id": matched_id},
        "auto_score": auto_score,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0),
        },
        "cost": estimate_cost(model_name, prompt_tokens, completion_tokens),
    }

    save_result_new(result, "compare", provider_name, model_name, fixture_name)
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
) -> dict[str, Any]:
    """Run merge evaluation for a single fixture."""
    fixture = load_fixture(fixture_path)

    if use_cache and not dry_run and not should_run(fixture_path, "merge", provider_name, model_name, fixture_name):
        cached = get_latest_result("merge", provider_name, model_name, fixture_name)
        if cached:
            if verbose:
                print(f"  [cached] {fixture_name}")
            return cached

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

    gateway = _create_gateway(provider_name, model_name)

    existing_event = input_data["existing_event"]
    new_extraction = input_data["new_extraction"]
    source_type = input_data["source_type"]

    start_time = time.time()
    try:
        merged = merge_event_data(gateway, existing_event, new_extraction, source_type)
        error = None
    except Exception as e:
        merged = {}
        error = str(e)

    duration_ms = int((time.time() - start_time) * 1000)

    prompt_tokens = getattr(gateway, '_last_prompt_tokens', None)
    completion_tokens = getattr(gateway, '_last_completion_tokens', None)

    auto_score = score_merge_result(expected, merged) if not error else {"error": error}

    result = {
        "fixture_name": fixture_name,
        "fixture_hash": get_fixture_hash(fixture_path),
        "code_hash": get_code_hash(),
        "operation": "merge",
        "provider": provider_name,
        "model": model_name,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "expected": expected,
        "actual": merged,
        "auto_score": auto_score,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0),
        },
        "cost": estimate_cost(model_name, prompt_tokens, completion_tokens),
    }

    save_result_new(result, "merge", provider_name, model_name, fixture_name)
    return result


# ---------------------------------------------------------------------------
# Thread eval runner (legacy, unchanged)
# ---------------------------------------------------------------------------

def run_thread_eval(
    scenario_name: str,
    scenario_path: Path,
    use_cache: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run evaluation for a thread scenario (multiple emails processed in sequence)."""
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
            "model": DEFAULT_MODEL,
            "duration_ms": 0,
            "email_count": len(thread_emails),
            "expected_final_state": expected_final,
            "actual": {"dry_run": True, "valid": is_valid, "errors": validation_errors},
            "auto_score": {"dry_run": True, "valid": is_valid},
            "email_results": [],
        }

    from selko.services.event_processing import extract_calendar_events

    gateway = _create_gateway(DEFAULT_PROVIDER, DEFAULT_MODEL)

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
                "gmail_id": email_data.get("gmail_id", f"email-{i+1}"),
                "subject": email_data.get("subject", ""),
                "events_found": extraction.events_found,
                "events": [
                    {
                        "title": e.title,
                        "start_datetime": e.start_datetime.isoformat() if e.start_datetime else None,
                        "end_datetime": e.end_datetime.isoformat() if e.end_datetime else None,
                        "location": e.location,
                        "confidence": e.confidence,
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
                "gmail_id": email_data.get("gmail_id", f"email-{i+1}"),
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
        "model": DEFAULT_MODEL,
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
    use_cache: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run evaluation for a single fixture using DEFAULT_PROVIDER/DEFAULT_MODEL."""
    return run_extract_eval(
        fixture_name, fixture_path, DEFAULT_PROVIDER, DEFAULT_MODEL,
        use_cache=use_cache, verbose=verbose, dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_result_summary(result: dict[str, Any]) -> None:
    """Print a one-line summary of a result."""
    if result.get("dry_run"):
        valid = result.get("valid", False)
        errors = result.get("errors", [])
        op = result.get("operation", "extract")
        status = "VALID" if valid else "INVALID"
        print(f"  [{op:7}] {result.get('fixture_name', '?'):40} [{status:7}] (dry-run)")
        for err in errors:
            print(f"           - {err}")
        return

    op = result.get("operation", "extract")
    auto_score = result.get("auto_score", {})
    cost = result.get("cost", 0)
    duration = result.get("duration_ms", 0)

    if op == "extract":
        if auto_score.get("all_events_match"):
            status = "PASS"
        elif auto_score.get("events_found_match"):
            status = "PARTIAL"
        else:
            status = "FAIL"
        rating = auto_score.get("auto_rating", "?")
        print(
            f"  [{op:7}] {result.get('fixture_name', '?'):40} "
            f"[{status:7}] Rating:{rating}/5 "
            f"${cost:.4f} ({duration}ms)"
        )
    elif op == "compare":
        correct = auto_score.get("correct", False)
        status = "PASS" if correct else "FAIL"
        print(
            f"  [{op:7}] {result.get('fixture_name', '?'):40} "
            f"[{status:7}] "
            f"${cost:.4f} ({duration}ms)"
        )
    elif op == "merge":
        rating = auto_score.get("auto_rating", "?")
        matched = auto_score.get("fields_matched", 0)
        total = auto_score.get("total_fields", 0)
        status = "PASS" if rating == 5 else ("PARTIAL" if rating >= 3 else "FAIL")
        print(
            f"  [{op:7}] {result.get('fixture_name', '?'):40} "
            f"[{status:7}] Rating:{rating}/5 ({matched}/{total}) "
            f"${cost:.4f} ({duration}ms)"
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
    print(f"Cost: ${result.get('cost', 0):.6f}")
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

    total_cost = sum(r.get("cost", 0) for r in results)
    avg_dur = sum(r.get("duration_ms", 0) for r in results) / total
    print(f"\nTotal cost: ${total_cost:.4f}")
    print(f"Average duration: {avg_dur:.0f}ms")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------

def generate_markdown_report(output_path: str) -> None:
    """Generate comprehensive markdown report from all cached results."""
    lines = []

    def line(s=""):
        lines.append(s)

    line("# Selko LLM Eval Report")
    line(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    line()

    # Collect all results from new directory structure
    all_results: list[dict] = []
    results_base = RESULTS_DIR
    for op_dir in sorted(results_base.iterdir()) if results_base.exists() else []:
        if not op_dir.is_dir() or op_dir.name.startswith("."):
            continue
        operation = op_dir.name
        for model_dir in sorted(op_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            for fixture_dir in sorted(model_dir.iterdir()):
                if not fixture_dir.is_dir():
                    continue
                # Get latest result
                result_files = sorted(fixture_dir.glob("result_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if result_files:
                    try:
                        with open(result_files[0]) as f:
                            r = json.load(f)
                            r.setdefault("operation", operation)
                            all_results.append(r)
                    except Exception:
                        pass

    if not all_results:
        line("*No results found. Run evals first.*")
        Path(output_path).write_text("\n".join(lines))
        return

    # Group by model and operation
    models_seen = set()
    by_model_op: dict[str, dict[str, list]] = {}
    for r in all_results:
        model = r.get("model", "unknown")
        op = r.get("operation", "extract")
        models_seen.add(model)
        by_model_op.setdefault(model, {}).setdefault(op, []).append(r)

    models_sorted = sorted(models_seen)

    # ---- Summary Table ----
    line("## Summary")
    line()
    line("| Model | Extract | Compare | Merge | Total Cost | Avg Latency |")
    line("|-------|---------|---------|-------|------------|-------------|")

    for model in models_sorted:
        ops = by_model_op.get(model, {})

        # Extract stats
        extract_results = ops.get("extract", [])
        if extract_results:
            ext_pass = sum(1 for r in extract_results if r.get("auto_score", {}).get("all_events_match"))
            ext_total = len(extract_results)
            ext_str = f"{ext_pass}/{ext_total} ({100*ext_pass/ext_total:.1f}%)"
        else:
            ext_str = "-"

        # Compare stats
        compare_results = ops.get("compare", [])
        if compare_results:
            cmp_correct = sum(1 for r in compare_results if r.get("auto_score", {}).get("correct"))
            cmp_total = len(compare_results)
            cmp_str = f"{cmp_correct}/{cmp_total} ({100*cmp_correct/cmp_total:.1f}%)"
        else:
            cmp_str = "-"

        # Merge stats
        merge_results = ops.get("merge", [])
        if merge_results:
            mrg_pass = sum(1 for r in merge_results if r.get("auto_score", {}).get("auto_rating", 0) == 5)
            mrg_total = len(merge_results)
            mrg_avg = sum(r.get("auto_score", {}).get("auto_rating", 0) for r in merge_results) / mrg_total
            mrg_str = f"{mrg_pass}/{mrg_total} ({mrg_avg:.1f} avg)"
        else:
            mrg_str = "-"

        all_model = extract_results + compare_results + merge_results
        total_cost = sum(r.get("cost", 0) for r in all_model)
        avg_latency = sum(r.get("duration_ms", 0) for r in all_model) / len(all_model) if all_model else 0

        line(f"| {model} | {ext_str} | {cmp_str} | {mrg_str} | ${total_cost:.4f} | {avg_latency:.0f}ms |")

    line()

    # ---- Extraction Results ----
    line("## Extraction Results")
    line()

    # All fixtures table
    line("### All Fixtures")
    line()
    line("| Model | Pass | Partial | Fail | Avg Rating | Cost |")
    line("|-------|------|---------|------|------------|------|")

    for model in models_sorted:
        results = by_model_op.get(model, {}).get("extract", [])
        if not results:
            continue
        pass_count = sum(1 for r in results if r.get("auto_score", {}).get("all_events_match"))
        partial = sum(1 for r in results if r.get("auto_score", {}).get("events_found_match") and not r.get("auto_score", {}).get("all_events_match"))
        fail = len(results) - pass_count - partial
        avg_rating = sum(r.get("auto_score", {}).get("auto_rating", 0) for r in results) / len(results)
        cost = sum(r.get("cost", 0) for r in results)
        line(f"| {model} | {pass_count} | {partial} | {fail} | {avg_rating:.1f}/5 | ${cost:.4f} |")

    line()

    # Real-life fixtures
    line("### Real-Life Fixtures Only")
    line()
    line("| Model | Pass | Partial | Fail | Avg Rating | Cost |")
    line("|-------|------|---------|------|------------|------|")

    for model in models_sorted:
        results = by_model_op.get(model, {}).get("extract", [])
        real_life = [r for r in results if "real-world" in r.get("tags", [])]
        if not real_life:
            continue
        pass_count = sum(1 for r in real_life if r.get("auto_score", {}).get("all_events_match"))
        partial = sum(1 for r in real_life if r.get("auto_score", {}).get("events_found_match") and not r.get("auto_score", {}).get("all_events_match"))
        fail = len(real_life) - pass_count - partial
        avg_rating = sum(r.get("auto_score", {}).get("auto_rating", 0) for r in real_life) / len(real_life)
        cost = sum(r.get("cost", 0) for r in real_life)
        line(f"| {model} | {pass_count} | {partial} | {fail} | {avg_rating:.1f}/5 | ${cost:.4f} |")

    line()

    # By category
    line("### By Category")
    line()
    for category in EMAIL_CATEGORIES:
        has_data = False
        cat_lines = []
        cat_lines.append(f"**{category}**")
        cat_lines.append("")
        cat_lines.append("| Model | Pass | Fail | Avg Rating |")
        cat_lines.append("|-------|------|------|------------|")
        for model in models_sorted:
            results = by_model_op.get(model, {}).get("extract", [])
            cat_results = [r for r in results if r.get("category") == category]
            if not cat_results:
                continue
            has_data = True
            pass_count = sum(1 for r in cat_results if r.get("auto_score", {}).get("all_events_match"))
            fail = len(cat_results) - pass_count
            avg_rating = sum(r.get("auto_score", {}).get("auto_rating", 0) for r in cat_results) / len(cat_results)
            cat_lines.append(f"| {model} | {pass_count} | {fail} | {avg_rating:.1f}/5 |")
        if has_data:
            for cl in cat_lines:
                line(cl)
            line()

    # ---- Compare Results ----
    line("## Compare (Dedup) Results")
    line()
    line("| Model | Correct | Wrong | Accuracy | Cost |")
    line("|-------|---------|-------|----------|------|")
    for model in models_sorted:
        results = by_model_op.get(model, {}).get("compare", [])
        if not results:
            continue
        correct = sum(1 for r in results if r.get("auto_score", {}).get("correct"))
        wrong = len(results) - correct
        accuracy = 100 * correct / len(results) if results else 0
        cost = sum(r.get("cost", 0) for r in results)
        line(f"| {model} | {correct} | {wrong} | {accuracy:.1f}% | ${cost:.4f} |")
    line()

    # ---- Merge Results ----
    line("## Merge Results")
    line()
    line("| Model | Avg Rating | Pass (5/5) | Cost |")
    line("|-------|------------|------------|------|")
    for model in models_sorted:
        results = by_model_op.get(model, {}).get("merge", [])
        if not results:
            continue
        avg_rating = sum(r.get("auto_score", {}).get("auto_rating", 0) for r in results) / len(results)
        perfect = sum(1 for r in results if r.get("auto_score", {}).get("auto_rating", 0) == 5)
        cost = sum(r.get("cost", 0) for r in results)
        line(f"| {model} | {avg_rating:.1f}/5 | {perfect}/{len(results)} | ${cost:.4f} |")
    line()

    # ---- Cost Analysis ----
    line("## Cost Analysis")
    line()

    line("### Per-Eval Cost")
    line()
    line("| Model | Extract Avg | Compare Avg | Merge Avg | Total |")
    line("|-------|-------------|-------------|-----------|-------|")
    for model in models_sorted:
        ops = by_model_op.get(model, {})
        ext = ops.get("extract", [])
        cmp = ops.get("compare", [])
        mrg = ops.get("merge", [])
        ext_avg = sum(r.get("cost", 0) for r in ext) / len(ext) if ext else 0
        cmp_avg = sum(r.get("cost", 0) for r in cmp) / len(cmp) if cmp else 0
        mrg_avg = sum(r.get("cost", 0) for r in mrg) / len(mrg) if mrg else 0
        total = sum(r.get("cost", 0) for r in ext + cmp + mrg)
        line(f"| {model} | ${ext_avg:.6f} | ${cmp_avg:.6f} | ${mrg_avg:.6f} | ${total:.4f} |")
    line()

    # Monthly projections
    line("### Monthly Cost Projection")
    line()
    line("Assumptions per tier:")
    for tier_name, tier in COST_TIERS.items():
        line(f"- **{tier_name}**: {tier['emails_per_month']} emails/month, "
             f"{int(tier['image_rate']*100)}% with images, "
             f"{int(tier['dedup_rate']*100)}% trigger dedup, "
             f"{int(tier['merge_rate']*100)}% trigger merge")
    line()

    tier_names = list(COST_TIERS.keys())
    header = "| Model | " + " | ".join(tier_names) + " |"
    sep = "|-------" + "|--------------------" * len(tier_names) + "|"
    line(header)
    line(sep)

    for model in models_sorted:
        ops = by_model_op.get(model, {})
        ext = ops.get("extract", [])
        cmp = ops.get("compare", [])
        mrg = ops.get("merge", [])
        ext_avg = sum(r.get("cost", 0) for r in ext) / len(ext) if ext else 0
        cmp_avg = sum(r.get("cost", 0) for r in cmp) / len(cmp) if cmp else 0
        mrg_avg = sum(r.get("cost", 0) for r in mrg) / len(mrg) if mrg else 0

        cells = []
        for tier in COST_TIERS.values():
            emails = tier["emails_per_month"]
            ext_cost = emails * ext_avg
            cmp_cost = emails * tier["dedup_rate"] * cmp_avg
            mrg_cost = emails * tier["merge_rate"] * mrg_avg
            total = ext_cost + cmp_cost + mrg_cost
            cells.append(f"${total:.2f}")
        line(f"| {model} | " + " | ".join(cells) + " |")
    line()

    # ---- Token Usage ----
    line("## Token Usage")
    line()
    line("| Model | Avg Prompt Tokens | Avg Completion Tokens | Total Tokens |")
    line("|-------|-------------------|----------------------|--------------|")
    for model in models_sorted:
        all_model = []
        for op_results in by_model_op.get(model, {}).values():
            all_model.extend(op_results)
        if not all_model:
            continue
        avg_prompt = sum(r.get("tokens", {}).get("prompt_tokens", 0) or 0 for r in all_model) / len(all_model)
        avg_comp = sum(r.get("tokens", {}).get("completion_tokens", 0) or 0 for r in all_model) / len(all_model)
        total_tok = sum(r.get("tokens", {}).get("total_tokens", 0) or 0 for r in all_model)
        line(f"| {model} | {avg_prompt:.0f} | {avg_comp:.0f} | {total_tok} |")
    line()

    # ---- Regression Analysis ----
    # Check if there are multiple code versions for any model
    code_versions: dict[str, set] = {}
    for r in all_results:
        model = r.get("model", "unknown")
        ch = r.get("code_hash", "")
        if ch:
            code_versions.setdefault(model, set()).add(ch)

    has_regression = any(len(versions) > 1 for versions in code_versions.values())
    if has_regression:
        line("## Regression Analysis")
        line()
        line("Multiple code versions detected — showing latest vs previous where applicable.")
        line()
        # This is a simplified version; full comparison would require iterating
        # through result files and comparing across code_hash versions
        for model in models_sorted:
            versions = code_versions.get(model, set())
            if len(versions) > 1:
                line(f"- **{model}**: {len(versions)} code versions: {', '.join(sorted(versions))}")
        line()

    # Write file
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n")
    print(f"Markdown report written to {output_path}")


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
    models: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Run evals across multiple models and operations."""
    from selko.services.llm_provider import MODEL_REGISTRY

    eval_models = models or EVAL_MODELS
    all_results = []

    for provider_name, model_name in eval_models:
        model_info = MODEL_REGISTRY.get(model_name, {})
        supports_vision = model_info.get("vision", False)

        print(f"\n{'='*60}")
        print(f"Model: {model_name} (provider: {provider_name}, vision: {supports_vision})")
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

            print(f"\n  Extract: {len(fixtures)} fixtures")
            print(f"  {'-'*50}")
            for name, path in fixtures:
                try:
                    result = run_extract_eval(
                        name, path, provider_name, model_name,
                        use_cache=use_cache, verbose=verbose, dry_run=dry_run,
                    )
                    all_results.append(result)
                    print_result_summary(result)
                except Exception as e:
                    print(f"  [extract] {name:40} [ERROR] {e}")

        if "compare" in operations:
            fixtures = get_compare_fixtures()
            if difficulty:
                fixtures = [(n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty]
            print(f"\n  Compare: {len(fixtures)} fixtures")
            print(f"  {'-'*50}")
            for name, path in fixtures:
                try:
                    result = run_compare_eval(
                        name, path, provider_name, model_name,
                        use_cache=use_cache, verbose=verbose, dry_run=dry_run,
                    )
                    all_results.append(result)
                    print_result_summary(result)
                except Exception as e:
                    print(f"  [compare] {name:40} [ERROR] {e}")

        if "merge" in operations:
            fixtures = get_merge_fixtures()
            if difficulty:
                fixtures = [(n, p) for n, p in fixtures if load_fixture(p).get("difficulty") == difficulty]
            print(f"\n  Merge: {len(fixtures)} fixtures")
            print(f"  {'-'*50}")
            for name, path in fixtures:
                try:
                    result = run_merge_eval(
                        name, path, provider_name, model_name,
                        use_cache=use_cache, verbose=verbose, dry_run=dry_run,
                    )
                    all_results.append(result)
                    print_result_summary(result)
                except Exception as e:
                    print(f"  [merge] {name:40} [ERROR] {e}")

    return all_results


# ---------------------------------------------------------------------------
# CLI
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

    # Cache options
    parser.add_argument("--use-cache", action="store_true", help="Use cached results if available")
    parser.add_argument("--no-cache", action="store_true", help="Force re-run, ignore cache")
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached results")

    # View options
    parser.add_argument("--report", action="store_true", help="Show console summary report")
    parser.add_argument("--report-md", type=str, help="Generate markdown report to file")
    parser.add_argument("--show", type=str, help="Show detailed result for fixture")
    parser.add_argument("--export", type=str, help="Export results to CSV file")
    parser.add_argument("--list", action="store_true", help="List all available fixtures")

    # Rating options
    parser.add_argument("--rate", nargs="?", const="all", help="Rate results interactively")

    # Provider options
    parser.add_argument("--provider", type=str, help="LLM provider override")
    parser.add_argument("--model", type=str, help="LLM model ID override")

    # Output options
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Validate fixtures without calling LLM")

    args = parser.parse_args()

    # Apply provider/model overrides
    import backend.tests.eval.eval_config as eval_cfg
    if args.provider:
        eval_cfg.DEFAULT_PROVIDER = args.provider
    if args.model:
        eval_cfg.DEFAULT_MODEL = args.model

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
        generate_markdown_report(args.report_md)
        return

    # Handle show
    if args.show:
        result = load_cached_result(args.show)
        if result:
            print_detailed_result(result)
        else:
            print(f"No cached result for {args.show}")
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

    # Multi-model mode
    if args.all_models:
        if not operations:
            operations = ["extract", "compare", "merge"]

        use_cache = args.use_cache and not args.no_cache
        results = run_all_models(
            operations=operations,
            difficulty=args.difficulty,
            use_cache=use_cache,
            verbose=args.verbose,
            dry_run=args.dry_run,
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
        use_cache = args.use_cache and not args.no_cache
        dry_run = args.dry_run
        print(f"\nRunning {len(threads)} thread scenarios...")
        if dry_run:
            print("(dry-run mode)")
        print("-" * 60)
        thread_results = []
        for name, path in threads:
            try:
                result = run_thread_eval(name, path, use_cache=use_cache, verbose=args.verbose, dry_run=dry_run)
                thread_results.append(result)
                print_thread_result_summary(result)
            except Exception as e:
                print(f"  {name:40} [ERROR] {e}")
        print("-" * 60)
        passed = sum(1 for r in thread_results if r.get("auto_score", {}).get("all_match") or r.get("auto_score", {}).get("valid"))
        print(f"Thread scenarios: {passed}/{len(thread_results)} passed")
        sys.exit(0)

    # Run operations
    use_cache = args.use_cache and not args.no_cache
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
            print(f"\nRunning {len(fixtures_to_run)} extraction fixtures ({provider}/{model})...")
            if args.dry_run:
                print("(dry-run mode)")
            print("-" * 60)
            for name, path in fixtures_to_run:
                try:
                    result = run_extract_eval(
                        name, path, provider, model,
                        use_cache=use_cache, verbose=args.verbose, dry_run=args.dry_run,
                    )
                    all_results.append(result)
                    print_result_summary(result)
                except Exception as e:
                    print(f"  [extract] {name:40} [ERROR] {e}")

    if "compare" in operations:
        fixtures_to_run = get_compare_fixtures()
        if args.difficulty:
            fixtures_to_run = [(n, p) for n, p in fixtures_to_run if load_fixture(p).get("difficulty") == args.difficulty]
        if fixtures_to_run:
            print(f"\nRunning {len(fixtures_to_run)} compare fixtures ({provider}/{model})...")
            if args.dry_run:
                print("(dry-run mode)")
            print("-" * 60)
            for name, path in fixtures_to_run:
                try:
                    result = run_compare_eval(
                        name, path, provider, model,
                        use_cache=use_cache, verbose=args.verbose, dry_run=args.dry_run,
                    )
                    all_results.append(result)
                    print_result_summary(result)
                except Exception as e:
                    print(f"  [compare] {name:40} [ERROR] {e}")

    if "merge" in operations:
        fixtures_to_run = get_merge_fixtures()
        if args.difficulty:
            fixtures_to_run = [(n, p) for n, p in fixtures_to_run if load_fixture(p).get("difficulty") == args.difficulty]
        if fixtures_to_run:
            print(f"\nRunning {len(fixtures_to_run)} merge fixtures ({provider}/{model})...")
            if args.dry_run:
                print("(dry-run mode)")
            print("-" * 60)
            for name, path in fixtures_to_run:
                try:
                    result = run_merge_eval(
                        name, path, provider, model,
                        use_cache=use_cache, verbose=args.verbose, dry_run=args.dry_run,
                    )
                    all_results.append(result)
                    print_result_summary(result)
                except Exception as e:
                    print(f"  [merge] {name:40} [ERROR] {e}")

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


if __name__ == "__main__":
    main()
