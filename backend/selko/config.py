"""Centralized configuration module for Selko.

Loads environment-specific settings from .env files (local development) or
environment variables (CI/CD). Supports development, staging, and production.
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Project root directory (parent of backend/)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Environment file mapping
ENV_FILES = {
    "development": ".env",
    "staging": ".env.test",
    "production": ".env.production",
}


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    environment: str
    supabase_url: str
    supabase_key: str  # Publishable key for client operations
    supabase_service_role_key: Optional[str] = None
    supabase_jwt_secret: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None

    # LLM provider configuration
    llm_provider: str = "qwen"  # gemini|moonshot|zai|qwen|deepseek|minimax|openai|anthropic
    llm_model: Optional[str] = None  # specific model ID (None = provider default)

    # API keys (one per provider)
    gemini_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    zai_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    alibaba_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Test user credentials for CLI authentication
    test_user_email: Optional[str] = None
    test_user_password: Optional[str] = None

    # Storage configuration
    storage_bucket_attachments: str = "attachments"
    max_attachment_size: int = 50 * 1024 * 1024  # 50 MB

    # Per-type attachment size limits for LLM processing
    max_pdf_pages_for_llm: int = 10                    # max pages to render
    max_image_size_for_llm: int = 10 * 1024 * 1024    # 10 MB
    max_other_size_for_llm: int = 20 * 1024 * 1024    # 20 MB

    # Worker pool configuration
    worker_pool_size: int = 3
    worker_idle_sleep_seconds: float = 1.0
    worker_error_backoff_seconds: float = 5.0

    # Processing timeouts (seconds)
    email_processing_timeout: int = 120
    photo_processing_timeout: int = 120
    event_sync_timeout: int = 60

    # Background processing (workers + scheduler)
    enable_background_processing: bool = False

    # CORS configuration
    allowed_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ])


def get_environment(override: Optional[str] = None) -> str:
    """Get the current environment name.

    Args:
        override: Optional environment name to use instead of env variable.

    Returns:
        Environment name: 'development', 'staging', or 'production'.

    Raises:
        ValueError: If the environment name is invalid.
    """
    env = override if override else os.getenv("ENVIRONMENT", "development")
    if env not in ENV_FILES:
        raise ValueError(
            f"Invalid environment '{env}'. "
            f"Valid environments: {', '.join(ENV_FILES.keys())}"
        )
    return env


def _parse_allowed_origins() -> list[str]:
    """Parse ALLOWED_ORIGINS from env, fall back to localhost defaults."""
    defaults = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    origins_str = os.getenv("ALLOWED_ORIGINS", "")
    if origins_str:
        return [o.strip() for o in origins_str.split(",") if o.strip()]
    return defaults


def load_config(env_override: Optional[str] = None) -> Config:
    """Load configuration from environment variables or .env file.

    For CI/CD: Set environment variables directly (no .env file needed).
    For local dev: Uses .env, .env.test, or .env.production files.

    Args:
        env_override: Optional environment name to override ENVIRONMENT variable.

    Returns:
        Config object with all configuration values.

    Raises:
        SystemExit: If required environment variables are missing.
    """
    try:
        environment = get_environment(env_override)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Determine which .env file to load
    env_file = ENV_FILES.get(environment)
    env_path = PROJECT_ROOT / env_file

    # Load from .env file if it exists (local development)
    # Skip if running in CI/CD where env vars are set directly
    if env_path.exists():
        load_dotenv(env_path, override=True)
        logger.info(f"Loaded config from {env_file} ({environment})")
    elif os.getenv("SUPABASE_URL"):
        # Env vars already set (CI/CD mode)
        logger.info(f"Using environment variables ({environment})")
    else:
        logger.error(f"Environment file not found: {env_path}")
        logger.error(f"Copy .env.example to {env_file} and fill in values.")
        logger.error("Or set environment variables directly (for CI/CD).")
        sys.exit(1)

    # Get required variables
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")

    # Validate required variables
    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not supabase_key:
        missing.append("SUPABASE_PUBLISHABLE_KEY")

    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error(f"Check your {env_file} file.")
        sys.exit(1)

    return Config(
        environment=environment,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        llm_provider=os.getenv("LLM_PROVIDER", "qwen"),
        llm_model=os.getenv("LLM_MODEL") or None,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        moonshot_api_key=os.getenv("MOONSHOT_API_KEY"),
        zai_api_key=os.getenv("ZAI_API_KEY"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        alibaba_api_key=os.getenv("ALIBABA_API_KEY"),
        minimax_api_key=os.getenv("MINIMAX_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        test_user_email=os.getenv("TEST_USER_EMAIL"),
        test_user_password=os.getenv("TEST_USER_PASSWORD"),
        worker_pool_size=int(os.getenv("WORKER_POOL_SIZE", "3")),
        worker_idle_sleep_seconds=float(os.getenv("WORKER_IDLE_SLEEP_SECONDS", "1.0")),
        worker_error_backoff_seconds=float(os.getenv("WORKER_ERROR_BACKOFF_SECONDS", "5.0")),
        email_processing_timeout=int(os.getenv("EMAIL_PROCESSING_TIMEOUT", "120")),
        photo_processing_timeout=int(os.getenv("PHOTO_PROCESSING_TIMEOUT", "120")),
        event_sync_timeout=int(os.getenv("EVENT_SYNC_TIMEOUT", "60")),
        enable_background_processing=os.getenv("ENABLE_BACKGROUND_PROCESSING", "").lower() == "true",
        allowed_origins=_parse_allowed_origins(),
        max_pdf_pages_for_llm=int(os.getenv("MAX_PDF_PAGES_FOR_LLM", "10")),
        max_image_size_for_llm=int(os.getenv("MAX_IMAGE_SIZE_FOR_LLM", str(10 * 1024 * 1024))),
        max_other_size_for_llm=int(os.getenv("MAX_OTHER_SIZE_FOR_LLM", str(20 * 1024 * 1024))),
    )


def add_logging_arguments(parser: argparse.ArgumentParser) -> None:
    """Add --verbose and --quiet flags to argument parser.

    Args:
        parser: argparse.ArgumentParser instance.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only show warnings and errors",
    )
