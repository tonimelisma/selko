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
INFERENCE_RESULTS_DIR = RESULTS_DIR / "inference"
SCORE_RESULTS_DIR = RESULTS_DIR / "scores"
MANIFESTS_DIR = RESULTS_DIR / "manifests"
REPORTS_DIR = RESULTS_DIR / "reports"

# Production code path for hashing (detects prompt/schema changes)
EVENT_PROCESSING_PATH = Path(__file__).parent / "../../selko/services/event_processing.py"

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
    5: "Perfect - events_found + count + ALL events match",
    4: "Good - events_found + count match + >= 50% events match",
    3: "Partial - events_found + count match + < 50% events match",
    2: "Poor - events_found match only (count wrong)",
    1: "Failed - events_found mismatch",
}

# Auto-scoring thresholds (extraction)
AUTO_SCORE_THRESHOLDS = {
    "time_tolerance_minutes": 60,  # Allow 60 min difference in times
}

# Merge scoring thresholds
MERGE_SCORE_THRESHOLDS = {
    "title_similarity": 0.9,
    "time_tolerance_minutes": 0,  # Must be exact
    "location_similarity": 0.8,
}

# Provider and model configuration (env overrides)
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", os.environ.get("SELKO_EVAL_PROVIDER", "qwen"))
DEFAULT_MODEL = os.environ.get("LLM_MODEL", os.environ.get("SELKO_EVAL_MODEL", "qwen3.6-flash"))

# Default models for multi-model evals: ONE preferred low/minimal thinking per model.
# Gemini 3.x uses thinking_level (minimal is lowest). OpenAI/xAI use reasoning_effort=low.
# Qwen uses enable_thinking + thinking_budget for "low". Anthropic uses adaptive effort=low.
EVAL_MODELS = [
    ("gemini", "gemini-3.5-flash-lite", "minimal"),
    ("gemini", "gemini-3.6-flash", "minimal"),
    ("openai", "gpt-5.6-luna", "low"),
    ("openai", "gpt-5.6-terra", "low"),
    ("anthropic", "claude-sonnet-5", "low"),
    ("qwen", "qwen3.6-flash", "low"),
    ("qwen", "qwen3.7-plus", "low"),
    ("zai", "glm-5.2", "low"),
    ("xai", "grok-4.5", "low"),
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
