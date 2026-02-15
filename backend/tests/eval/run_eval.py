#!/usr/bin/env python3
"""
LLM Evaluation Runner

Manual evaluation framework for testing LLM email processing quality.
Run with: uv run python -m backend.tests.eval.run_eval --help
"""

import argparse
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
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DIFFICULTY_LEVELS,
    EMAIL_CATEGORIES,
    EMAILS_DIR,
    RATING_SCALE,
    RESULTS_DIR,
    THREADS_DIR,
)


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


def get_thread_scenarios() -> list[tuple[str, Path]]:
    """Get all thread scenario files."""
    scenarios = []
    if THREADS_DIR.exists():
        for scenario_file in sorted(THREADS_DIR.glob("*.json")):
            scenarios.append((scenario_file.stem, scenario_file))
    return scenarios


def get_result_path(fixture_name: str) -> Path:
    """Get the cache path for a fixture result."""
    safe_name = fixture_name.replace("/", "_")
    return RESULTS_DIR / f"{safe_name}.json"


def load_cached_result(fixture_name: str) -> dict[str, Any] | None:
    """Load cached result if exists."""
    result_path = get_result_path(fixture_name)
    if result_path.exists():
        with open(result_path) as f:
            return json.load(f)
    return None


def save_result(fixture_name: str, result: dict[str, Any]) -> None:
    """Save result to cache."""
    result_path = get_result_path(fixture_name)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)


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
        # Handle various datetime formats
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

    # Title similarity
    title_sim = string_similarity(expected.get("title"), actual.get("title"))
    scores["title"] = {
        "similarity": title_sim,
        "match": title_sim >= AUTO_SCORE_THRESHOLDS["title_similarity"],
    }

    # Start time
    start_diff = time_difference_minutes(
        expected.get("start_datetime"), actual.get("start_datetime")
    )
    scores["start_datetime"] = {
        "difference_minutes": start_diff,
        "match": start_diff is not None
        and start_diff <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"],
    }

    # End time
    end_diff = time_difference_minutes(
        expected.get("end_datetime"), actual.get("end_datetime")
    )
    scores["end_datetime"] = {
        "difference_minutes": end_diff,
        "match": end_diff is None
        or end_diff <= AUTO_SCORE_THRESHOLDS["time_tolerance_minutes"],
    }

    # Location similarity
    loc_sim = string_similarity(expected.get("location"), actual.get("location"))
    scores["location"] = {
        "similarity": loc_sim,
        "match": loc_sim >= AUTO_SCORE_THRESHOLDS["location_similarity"],
    }

    # Confidence check
    actual_confidence = actual.get("confidence", 0)
    min_confidence = expected.get("confidence_min", AUTO_SCORE_THRESHOLDS["confidence_min"])
    scores["confidence"] = {
        "actual": actual_confidence,
        "required_min": min_confidence,
        "match": actual_confidence >= min_confidence,
    }

    # Overall match
    scores["overall_match"] = all(
        s.get("match", True)
        for s in scores.values()
        if isinstance(s, dict)
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

    # Score individual events if both have events
    expected_events = expected.get("events", [])
    actual_events = actual.get("events", [])

    if expected_events and actual_events:
        # Simple matching: pair events by order
        event_scores = []
        for i, exp_event in enumerate(expected_events):
            if i < len(actual_events):
                event_scores.append(auto_score_event(exp_event, actual_events[i]))
            else:
                event_scores.append({"missing": True, "overall_match": False})

        # Extra events in actual
        for i in range(len(expected_events), len(actual_events)):
            event_scores.append({"extra": True, "overall_match": False})

        scores["event_scores"] = event_scores
        scores["all_events_match"] = all(
            es.get("overall_match", False) for es in event_scores
        )
    else:
        scores["all_events_match"] = not expected_events and not actual_events

    # Overall auto-score (1-5 scale approximation)
    if scores["events_found_match"] and scores["event_count_match"] and scores.get("all_events_match"):
        scores["auto_rating"] = 5
    elif scores["events_found_match"] and scores["event_count_match"]:
        scores["auto_rating"] = 4
    elif scores["events_found_match"]:
        scores["auto_rating"] = 3
    else:
        scores["auto_rating"] = 1

    return scores


def run_single_eval(
    fixture_name: str,
    fixture_path: Path,
    use_cache: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run evaluation for a single fixture."""
    # Check cache first
    if use_cache:
        cached = load_cached_result(fixture_name)
        if cached:
            if verbose:
                print(f"  Using cached result for {fixture_name}")
            return cached

    # Load fixture
    fixture = load_fixture(fixture_path)
    input_data = fixture["input"]
    expected = fixture["expected"]

    # Load attachments if specified
    attachments = []
    attachment_errors = []
    for att_ref in input_data.get("attachments", []):
        if isinstance(att_ref, str):
            try:
                name, content = load_attachment(att_ref)
                attachments.append({
                    "filename": name,
                    "content": content,
                    "mime_type": _guess_mime_type(name),
                })
            except FileNotFoundError as e:
                attachment_errors.append(str(e))
                if not dry_run:
                    print(f"  Warning: {e}")

    # Dry-run mode: validate fixture without calling LLM
    if dry_run:
        validation_errors = []

        # Check required fields
        if "input" not in fixture:
            validation_errors.append("Missing 'input' field")
        if "expected" not in fixture:
            validation_errors.append("Missing 'expected' field")

        # Check input structure
        if "body_text" not in input_data and "attachments" not in input_data:
            validation_errors.append("Input must have 'body_text' or 'attachments'")

        # Check expected structure
        if "events_found" not in expected:
            validation_errors.append("Expected must have 'events_found' field")

        # Include attachment errors
        validation_errors.extend(attachment_errors)

        is_valid = len(validation_errors) == 0

        result = {
            "fixture_name": fixture_name,
            "fixture_path": str(fixture_path),
            "category": fixture.get("category", fixture_name.split("/")[0]),
            "description": fixture.get("description", ""),
            "difficulty": fixture.get("difficulty", "medium"),
            "tags": fixture.get("tags", []),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "model": DEFAULT_MODEL,
            "duration_ms": 0,
            "input_summary": {
                "subject": input_data.get("subject", ""),
                "from": input_data.get("from_email", ""),
                "has_attachments": bool(input_data.get("attachments", [])),
                "attachment_count": len(input_data.get("attachments", [])),
            },
            "expected": expected,
            "actual": {"dry_run": True, "valid": is_valid, "errors": validation_errors},
            "auto_score": {"dry_run": True, "valid": is_valid},
            "manual_rating": None,
            "manual_notes": None,
        }
        return result

    # Import here to avoid circular imports and allow running without deps
    try:
        from selko.config import load_config
        from selko.services.gemini import extract_calendar_events
        from selko.services.llm_gateway import LLMGateway
        from selko.services.llm_provider import create_provider
    except ImportError as e:
        print(f"Error: Could not import required modules: {e}")
        print("Make sure you're running from the project root with uv run")
        sys.exit(1)

    # Initialize provider and gateway
    config = load_config()
    # Allow env overrides for evals
    config.llm_provider = DEFAULT_PROVIDER
    config.llm_model = DEFAULT_MODEL
    provider = create_provider(config)
    gateway = LLMGateway(provider)

    # Prepare email metadata
    email_metadata = {
        "subject": input_data.get("subject", ""),
        "from_name": input_data.get("from_name", ""),
        "from_email": input_data.get("from_email", ""),
        "date_sent": input_data.get("date_sent", ""),
    }

    # Run extraction
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
                }
                for e in extraction.events
            ],
        }
        error = None
    except Exception as e:
        actual = {"events_found": False, "events": [], "error": str(e)}
        error = str(e)

    duration_ms = int((time.time() - start_time) * 1000)

    # Auto-score
    auto_score = auto_score_result(expected, actual) if not error else {"error": error}

    # Build result
    result = {
        "fixture_name": fixture_name,
        "fixture_path": str(fixture_path),
        "category": fixture.get("category", fixture_name.split("/")[0]),
        "description": fixture.get("description", ""),
        "difficulty": fixture.get("difficulty", "medium"),
        "tags": fixture.get("tags", []),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
        "duration_ms": duration_ms,
        "input_summary": {
            "subject": input_data.get("subject", ""),
            "from": input_data.get("from_email", ""),
            "has_attachments": bool(attachments),
            "attachment_count": len(attachments),
        },
        "expected": expected,
        "actual": actual,
        "auto_score": auto_score,
        "manual_rating": None,
        "manual_notes": None,
    }

    # Save to cache
    save_result(fixture_name, result)

    return result


def _guess_mime_type(filename: str) -> str:
    """Guess MIME type from filename extension."""
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
    }
    return mime_map.get(ext, "application/octet-stream")


def run_thread_eval(
    scenario_name: str,
    scenario_path: Path,
    use_cache: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run evaluation for a thread scenario (multiple emails processed in sequence)."""
    start_time = time.time()

    # Load scenario
    with open(scenario_path) as f:
        scenario = json.load(f)

    thread_emails = scenario.get("thread_emails", [])
    expected_final = scenario.get("expected_final_state", {})

    # Dry-run mode: validate scenario without calling LLM
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

        result = {
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
        return result

    # Import here to avoid circular imports
    try:
        from selko.config import load_config
        from selko.services.gemini import extract_calendar_events
        from selko.services.llm_gateway import LLMGateway
        from selko.services.llm_provider import create_provider
    except ImportError as e:
        print(f"Error: Could not import required modules: {e}")
        sys.exit(1)

    # Initialize provider and gateway
    config = load_config()
    config.llm_provider = DEFAULT_PROVIDER
    config.llm_model = DEFAULT_MODEL
    provider = create_provider(config)
    gateway = LLMGateway(provider)

    # Process each email in sequence, tracking extracted events
    email_results = []
    all_events = []  # Track events across the thread

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

            # Track events - in a real scenario, we'd merge/update based on thread context
            # For now, we just collect the latest extraction
            if extraction.events:
                all_events = email_result["events"]  # Latest events override

            email_results.append(email_result)

        except Exception as e:
            email_results.append({
                "email_index": i + 1,
                "gmail_id": email_data.get("gmail_id", f"email-{i+1}"),
                "error": str(e),
            })

    duration_ms = int((time.time() - start_time) * 1000)

    # Compare final state with expected
    final_event_count = len(all_events)
    expected_count = expected_final.get("event_count", 0)
    count_match = final_event_count == expected_count

    # Score final event if expected
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

    result = {
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

    return result


def print_thread_result_summary(result: dict[str, Any]) -> None:
    """Print a summary of a thread evaluation result."""
    auto_score = result.get("auto_score", {})
    is_dry_run = auto_score.get("dry_run", False)

    if is_dry_run:
        valid = auto_score.get("valid", False)
        status = "VALID" if valid else "INVALID"
    else:
        status = "PASS" if auto_score.get("all_match") else "FAIL"

    email_count = result.get("email_count", 0)
    duration = result.get("duration_ms", 0)

    print(
        f"  {result['scenario_name']:40} "
        f"[{status:7}] "
        f"Emails:{email_count} "
        f"({duration}ms)"
    )


def print_result_summary(result: dict[str, Any]) -> None:
    """Print a summary of a single result."""
    auto_score = result.get("auto_score", {})

    # Handle dry-run results
    if auto_score.get("dry_run"):
        valid = result.get("actual", {}).get("valid", False)
        errors = result.get("actual", {}).get("errors", [])
        status = "VALID" if valid else "INVALID"
        print(
            f"  {result['fixture_name']:40} "
            f"[{status:7}] "
            f"(dry-run)"
        )
        if errors:
            for err in errors:
                print(f"      - {err}")
        return

    auto_rating = auto_score.get("auto_rating", "?")
    manual_rating = result.get("manual_rating", "-")

    status = ""
    if auto_score.get("events_found_match") and auto_score.get("event_count_match"):
        if auto_score.get("all_events_match"):
            status = "PASS"
        else:
            status = "PARTIAL"
    else:
        status = "FAIL"

    print(
        f"  {result['fixture_name']:40} "
        f"[{status:7}] "
        f"Auto:{auto_rating}/5 "
        f"Manual:{manual_rating}/5 "
        f"({result['duration_ms']}ms)"
    )


def print_detailed_result(result: dict[str, Any]) -> None:
    """Print detailed result for a fixture."""
    print(f"\n{'='*60}")
    print(f"Fixture: {result['fixture_name']}")
    print(f"Description: {result.get('description', 'N/A')}")
    print(f"Category: {result.get('category', 'N/A')}")
    print(f"Difficulty: {result.get('difficulty', 'N/A')}")
    print(f"Tags: {', '.join(result.get('tags', []))}")
    print(f"Run at: {result.get('run_at', 'N/A')}")
    print(f"Duration: {result.get('duration_ms', 0)}ms")
    print(f"Model: {result.get('model', 'N/A')}")

    print(f"\n--- Input Summary ---")
    inp = result.get("input_summary", {})
    print(f"Subject: {inp.get('subject', 'N/A')}")
    print(f"From: {inp.get('from', 'N/A')}")
    print(f"Attachments: {inp.get('attachment_count', 0)}")

    print(f"\n--- Expected ---")
    expected = result.get("expected", {})
    print(f"Events found: {expected.get('events_found', 'N/A')}")
    print(f"Event count: {expected.get('event_count', len(expected.get('events', [])))}")
    for i, event in enumerate(expected.get("events", [])):
        print(f"  Event {i+1}:")
        print(f"    Title: {event.get('title', 'N/A')}")
        print(f"    Start: {event.get('start_datetime', 'N/A')}")
        print(f"    End: {event.get('end_datetime', 'N/A')}")
        print(f"    Location: {event.get('location', 'N/A')}")

    print(f"\n--- Actual ---")
    actual = result.get("actual", {})
    if actual.get("error"):
        print(f"ERROR: {actual['error']}")
    else:
        print(f"Events found: {actual.get('events_found', 'N/A')}")
        print(f"Event count: {len(actual.get('events', []))}")
        for i, event in enumerate(actual.get("events", [])):
            print(f"  Event {i+1}:")
            print(f"    Title: {event.get('title', 'N/A')}")
            print(f"    Start: {event.get('start_datetime', 'N/A')}")
            print(f"    End: {event.get('end_datetime', 'N/A')}")
            print(f"    Location: {event.get('location', 'N/A')}")
            print(f"    Confidence: {event.get('confidence', 'N/A')}")

    print(f"\n--- Auto Score ---")
    auto_score = result.get("auto_score", {})
    print(f"Events found match: {auto_score.get('events_found_match', 'N/A')}")
    print(f"Event count match: {auto_score.get('event_count_match', 'N/A')}")
    print(f"All events match: {auto_score.get('all_events_match', 'N/A')}")
    print(f"Auto rating: {auto_score.get('auto_rating', 'N/A')}/5")

    print(f"\n--- Manual Rating ---")
    print(f"Rating: {result.get('manual_rating', 'Not rated')}/5")
    print(f"Notes: {result.get('manual_notes', 'None')}")
    print(f"{'='*60}\n")


def generate_report(results: list[dict[str, Any]]) -> None:
    """Generate summary report from results."""
    print("\n" + "=" * 60)
    print("LLM EVALUATION REPORT")
    print("=" * 60)

    total = len(results)
    if total == 0:
        print("No results found. Run evaluations first.")
        return

    # Count by auto-rating
    rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in results:
        rating = r.get("auto_score", {}).get("auto_rating", 0)
        if rating in rating_counts:
            rating_counts[rating] += 1

    # Count by category
    category_stats: dict[str, dict[str, int]] = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "pass": 0, "partial": 0, "fail": 0}
        category_stats[cat]["total"] += 1
        auto_score = r.get("auto_score", {})
        if auto_score.get("all_events_match"):
            category_stats[cat]["pass"] += 1
        elif auto_score.get("events_found_match"):
            category_stats[cat]["partial"] += 1
        else:
            category_stats[cat]["fail"] += 1

    # Summary
    pass_count = sum(
        1
        for r in results
        if r.get("auto_score", {}).get("all_events_match")
    )
    partial_count = sum(
        1
        for r in results
        if r.get("auto_score", {}).get("events_found_match")
        and not r.get("auto_score", {}).get("all_events_match")
    )
    fail_count = total - pass_count - partial_count

    print(f"\nTotal fixtures: {total}")
    print(f"  PASS:    {pass_count:3} ({100*pass_count/total:.1f}%)")
    print(f"  PARTIAL: {partial_count:3} ({100*partial_count/total:.1f}%)")
    print(f"  FAIL:    {fail_count:3} ({100*fail_count/total:.1f}%)")

    print(f"\nAuto-rating distribution:")
    for rating in [5, 4, 3, 2, 1]:
        count = rating_counts[rating]
        bar = "" * count
        print(f"  {rating}/5: {count:3} {bar}")

    print(f"\nBy category:")
    for cat, stats in sorted(category_stats.items()):
        total_cat = stats["total"]
        pass_pct = 100 * stats["pass"] / total_cat if total_cat > 0 else 0
        print(
            f"  {cat:15} "
            f"Pass:{stats['pass']:2}/{total_cat:2} ({pass_pct:5.1f}%) "
            f"Partial:{stats['partial']:2} Fail:{stats['fail']:2}"
        )

    # Average duration
    avg_duration = sum(r.get("duration_ms", 0) for r in results) / total
    print(f"\nAverage duration: {avg_duration:.0f}ms")

    # Manual ratings if any
    rated = [r for r in results if r.get("manual_rating") is not None]
    if rated:
        avg_manual = sum(r["manual_rating"] for r in rated) / len(rated)
        print(f"Manual ratings: {len(rated)}/{total} rated, avg: {avg_manual:.1f}/5")

    print("=" * 60 + "\n")


def rate_fixture(fixture_name: str) -> None:
    """Interactive rating for a fixture."""
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
    """Clear all cached results."""
    count = 0
    for result_file in RESULTS_DIR.glob("*.json"):
        result_file.unlink()
        count += 1
    print(f"Cleared {count} cached results")


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
            "fixture_name",
            "category",
            "difficulty",
            "events_found_expected",
            "events_found_actual",
            "event_count_expected",
            "event_count_actual",
            "auto_rating",
            "manual_rating",
            "duration_ms",
            "run_at",
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


def main():
    parser = argparse.ArgumentParser(
        description="LLM Evaluation Runner for Selko email processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run all evaluations:
    uv run python -m backend.tests.eval.run_eval --all

  Run specific category:
    uv run python -m backend.tests.eval.run_eval --category invitations

  Run single fixture:
    uv run python -m backend.tests.eval.run_eval --fixture invitations/birthday_party_01

  Use cached results:
    uv run python -m backend.tests.eval.run_eval --all --use-cache

  Show report:
    uv run python -m backend.tests.eval.run_eval --report

  Rate results interactively:
    uv run python -m backend.tests.eval.run_eval --rate
        """,
    )

    # Run options
    parser.add_argument("--all", action="store_true", help="Run all fixtures")
    parser.add_argument("--category", type=str, help="Run fixtures in category")
    parser.add_argument("--fixture", type=str, help="Run single fixture (category/name)")
    parser.add_argument("--threads", action="store_true", help="Run thread scenarios")
    parser.add_argument(
        "--difficulty", type=str, choices=DIFFICULTY_LEVELS, help="Filter by difficulty"
    )

    # Cache options
    parser.add_argument(
        "--use-cache", action="store_true", help="Use cached results if available"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Force re-run, ignore cache"
    )
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached results")

    # View options
    parser.add_argument("--report", action="store_true", help="Show summary report")
    parser.add_argument("--show", type=str, help="Show detailed result for fixture")
    parser.add_argument("--export", type=str, help="Export results to CSV file")
    parser.add_argument("--list", action="store_true", help="List all available fixtures")

    # Rating options
    parser.add_argument(
        "--rate", nargs="?", const="all", help="Rate results interactively"
    )

    # Provider options
    parser.add_argument(
        "--provider",
        type=str,
        help="LLM provider (gemini, moonshot, zai, qwen, deepseek, minimax)",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="LLM model ID (e.g., gemini-3-flash-preview, kimi-k2.5)",
    )

    # Output options
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate fixtures without calling LLM",
    )

    args = parser.parse_args()

    # Apply provider/model overrides to eval_config globals
    import backend.tests.eval.eval_config as eval_cfg
    if args.provider:
        eval_cfg.DEFAULT_PROVIDER = args.provider
    if args.model:
        eval_cfg.DEFAULT_MODEL = args.model

    # Handle list
    if args.list:
        fixtures = get_all_fixtures()
        print(f"\nAvailable fixtures ({len(fixtures)} total):\n")
        for name, path in fixtures:
            fixture = load_fixture(path)
            diff = fixture.get("difficulty", "?")
            desc = fixture.get("description", "")[:50]
            print(f"  {name:40} [{diff:6}] {desc}")
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
            # Rate unrated fixtures
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

    # Determine which fixtures to run
    fixtures_to_run = []

    if args.all:
        fixtures_to_run = get_all_fixtures()
    elif args.category:
        all_fixtures = get_all_fixtures()
        fixtures_to_run = [
            (name, path)
            for name, path in all_fixtures
            if name.startswith(args.category + "/")
        ]
    elif args.fixture:
        all_fixtures = get_all_fixtures()
        for name, path in all_fixtures:
            if name == args.fixture:
                fixtures_to_run = [(name, path)]
                break
        if not fixtures_to_run:
            print(f"Fixture not found: {args.fixture}")
            sys.exit(1)
    elif args.threads:
        # Run thread scenario evaluations
        threads = get_thread_scenarios()
        if not threads:
            print("No thread scenarios found")
            sys.exit(0)

        use_cache = args.use_cache and not args.no_cache
        dry_run = args.dry_run

        print(f"\nRunning {len(threads)} thread scenarios...")
        if dry_run:
            print("(dry-run mode - validating fixtures only)")
        print("-" * 60)

        thread_results = []
        for name, path in threads:
            if args.verbose:
                print(f"\nProcessing thread: {name}")
            try:
                result = run_thread_eval(
                    name, path, use_cache=use_cache, verbose=args.verbose, dry_run=dry_run
                )
                thread_results.append(result)
                print_thread_result_summary(result)
            except Exception as e:
                print(f"  {name:40} [ERROR] {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()

        # Summary
        print("-" * 60)
        passed = sum(1 for r in thread_results if r.get("auto_score", {}).get("all_match") or r.get("auto_score", {}).get("valid"))
        print(f"Thread scenarios: {passed}/{len(thread_results)} passed")
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(0)

    # Filter by difficulty if specified
    if args.difficulty:
        filtered = []
        for name, path in fixtures_to_run:
            fixture = load_fixture(path)
            if fixture.get("difficulty") == args.difficulty:
                filtered.append((name, path))
        fixtures_to_run = filtered

    if not fixtures_to_run:
        print("No fixtures to run")
        sys.exit(0)

    # Run evaluations
    dry_run = args.dry_run
    print(f"\nRunning {len(fixtures_to_run)} fixtures...")
    if dry_run:
        print("(dry-run mode - validating fixtures only)")
    print("-" * 60)

    use_cache = args.use_cache and not args.no_cache
    results = []

    for name, path in fixtures_to_run:
        if args.verbose:
            print(f"\nProcessing: {name}")
        try:
            result = run_single_eval(
                name, path, use_cache=use_cache, verbose=args.verbose, dry_run=dry_run
            )
            results.append(result)
            print_result_summary(result)
        except Exception as e:
            print(f"  {name:40} [ERROR] {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Show summary (skip for dry-run as results are not saved)
    if not dry_run:
        generate_report(results)
    else:
        print("-" * 60)
        valid = sum(1 for r in results if r.get("actual", {}).get("valid", False))
        invalid = len(results) - valid
        print(f"Dry-run complete: {valid} valid, {invalid} invalid fixtures")


if __name__ == "__main__":
    main()
