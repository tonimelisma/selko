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
DEFAULT_MODEL = os.environ.get("LLM_MODEL", os.environ.get("SELKO_EVAL_MODEL", "qwen3.5-flash"))

# Default models for multi-model evals: (provider, model, thinking_level)
# Thinking levels: "none", "low", "medium" — providers without thinking support ignore the level
# Gemini supports none/low/medium; OpenAI GPT-5 supports low/medium; Anthropic Sonnet 4.6 supports none/low/medium
# Qwen3-VL/3.5 supports none/low/medium (enable_thinking + thinking_budget)
EVAL_MODELS = [
    # Gemini — test at none, low, medium
    ("gemini", "gemini-3-flash-preview", "none"),
    ("gemini", "gemini-3-flash-preview", "low"),
    ("gemini", "gemini-3-flash-preview", "medium"),
    # OpenAI GPT-5 — test at low, medium (reasoning models, can't disable reasoning)
    ("openai", "gpt-5-nano", "low"),
    ("openai", "gpt-5-nano", "medium"),
    ("openai", "gpt-5-mini", "low"),
    ("openai", "gpt-5-mini", "medium"),
    ("openai", "gpt-5.2", "low"),
    ("openai", "gpt-5.2", "medium"),
    # Anthropic Haiku — single mode (no adaptive thinking)
    # Note: Sonnet removed from defaults (too expensive for routine evals — $3/$15 per MTok).
    # Still accessible via: --provider anthropic --model claude-sonnet-4-6
    ("anthropic", "claude-haiku-4-5-20251001", "none"),
    # Qwen — thinking mode tested but dropped from defaults:
    # - qwen3.5-plus thinking: marginal quality gain (+2 pass at low), 3-5x cost/latency
    # - qwen3.5-flash thinking: quality *degrades* (3→5→6 fails), not worth the cost
    # - qwen3-vl-plus thinking: catastrophically broken (returns bare floats, not JSON)
    # Still accessible via: --provider qwen --model <model> --thinking low/medium
    ("qwen", "qwen3.5-plus", "none"),
    ("qwen", "qwen3.5-flash", "none"),
    ("qwen", "qwen3-vl-flash", "none"),
    ("qwen", "qwen3-vl-plus", "none"),
    ("qwen", "qwen-vl-max", "none"),
    # Other providers — single mode (no thinking support)
    ("moonshot", "kimi-k2.5", "none"),
    ("zai", "glm-4.6v-flash", "none"),
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
