"""Configuration for LLM evaluation suite."""

import os
from pathlib import Path

# Paths
EVAL_DIR = Path(__file__).parent
FIXTURES_DIR = EVAL_DIR / "fixtures"
EMAILS_DIR = FIXTURES_DIR / "emails"
ATTACHMENTS_DIR = FIXTURES_DIR / "attachments"
THREADS_DIR = FIXTURES_DIR / "threads"
RESULTS_DIR = EVAL_DIR / "results"

# Categories
EMAIL_CATEGORIES = [
    "invitations",
    "appointments",
    "meetings",
    "travel",
    "conferences",
    "school",
    "recurring",
    "no_events",
]

# Difficulty levels
DIFFICULTY_LEVELS = ["easy", "medium", "hard"]

# Rating scale
RATING_SCALE = {
    5: "Perfect - Exact match on all fields",
    4: "Excellent - Minor differences (e.g., slight description variation)",
    3: "Good - Correct event detection, some field issues",
    2: "Partial - Missed events or significant extraction errors",
    1: "Failed - Wrong extraction or false positive/negative",
}

# Auto-scoring thresholds
AUTO_SCORE_THRESHOLDS = {
    "title_similarity": 0.8,  # Minimum string similarity for title match
    "time_tolerance_minutes": 30,  # Allow 30 min difference in times
    "location_similarity": 0.7,  # Minimum string similarity for location
    "confidence_min": 0.5,  # Minimum acceptable confidence
}

# Model configuration
DEFAULT_MODEL = os.environ.get("SELKO_EVAL_MODEL", "gemini-3-flash-preview")
