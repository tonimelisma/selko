"""Configuration for LLM evaluation suite."""

import os
from pathlib import Path

# Paths
EVAL_DIR = Path(__file__).parent
FIXTURES_DIR = EVAL_DIR / "fixtures"
EMAILS_DIR = FIXTURES_DIR / "emails"
ATTACHMENTS_DIR = FIXTURES_DIR / "attachments"
THREADS_DIR = FIXTURES_DIR / "threads"
COMPARE_DIR = FIXTURES_DIR / "compare"
MERGE_DIR = FIXTURES_DIR / "merge"
RESULTS_DIR = EVAL_DIR / "results"

# Production code path for hashing (detects prompt/schema changes)
EVENT_PROCESSING_PATH = Path(__file__).parent / "../../../selko/services/event_processing.py"

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

# Auto-scoring thresholds (extraction)
AUTO_SCORE_THRESHOLDS = {
    "title_similarity": 0.8,  # Minimum string similarity for title match
    "time_tolerance_minutes": 30,  # Allow 30 min difference in times
    "location_similarity": 0.7,  # Minimum string similarity for location
    "confidence_min": 0.5,  # Minimum acceptable confidence
}

# Merge scoring thresholds
MERGE_SCORE_THRESHOLDS = {
    "title_similarity": 0.9,
    "time_tolerance_minutes": 0,  # Must be exact
    "location_similarity": 0.8,
}

# Provider and model configuration (env overrides)
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", os.environ.get("SELKO_EVAL_PROVIDER", "gemini"))
DEFAULT_MODEL = os.environ.get("LLM_MODEL", os.environ.get("SELKO_EVAL_MODEL", "gemini-3-flash-preview"))

# 6 default models for multi-model evals (one per provider)
EVAL_MODELS = [
    ("gemini", "gemini-3-flash-preview"),
    ("moonshot", "kimi-k2.5"),
    ("zai", "glm-4.6v-flash"),
    ("qwen", "qwen3-vl-flash"),
    ("deepseek", "deepseek-chat"),
    ("minimax", "MiniMax-M2.5"),
]

# Monthly cost projection tiers
COST_TIERS = {
    "Tier 1 (50 emails)": {
        "emails_per_month": 50,
        "image_rate": 0.10,
        "avg_images": 2,
        "dedup_rate": 0.40,
        "merge_rate": 0.20,
    },
    "Tier 2 (150 emails)": {
        "emails_per_month": 150,
        "image_rate": 0.15,
        "avg_images": 3,
        "dedup_rate": 0.50,
        "merge_rate": 0.25,
    },
    "Tier 3 (500 emails)": {
        "emails_per_month": 500,
        "image_rate": 0.20,
        "avg_images": 5,
        "dedup_rate": 0.60,
        "merge_rate": 0.30,
    },
}
