"""Centralized configuration module for Selko.

Handles environment detection and .env file loading with support for
development/staging/production environments.
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Project root directory (parent of backend/)
PROJECT_ROOT = Path(__file__).parent.parent.parent
CLI_DIR = PROJECT_ROOT / "cli"

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
    supabase_anon_key: str
    supabase_service_role_key: Optional[str] = None
    supabase_jwt_secret: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None

    # Test user credentials for CLI authentication
    test_user_email: Optional[str] = None
    test_user_password: Optional[str] = None

    # Storage configuration
    storage_bucket_attachments: str = "attachments"
    max_attachment_size: int = 50 * 1024 * 1024  # 50 MB

    # Paths (derived, not from env)
    credentials_file: Path = CLI_DIR / "credentials.json"


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
    # Support both legacy anon key (JWT) and newer publishable key formats
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv(
        "SUPABASE_PUBLISHABLE_API_KEY"
    )

    # Validate required variables
    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not supabase_anon_key:
        missing.append("SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_API_KEY")

    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error(f"Check your {env_file} file.")
        sys.exit(1)

    return Config(
        environment=environment,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        test_user_email=os.getenv("TEST_USER_EMAIL"),
        test_user_password=os.getenv("TEST_USER_PASSWORD"),
    )


def add_env_argument(parser: argparse.ArgumentParser) -> None:
    """Add --env argument to an argparse parser.

    Args:
        parser: argparse.ArgumentParser instance.
    """
    parser.add_argument(
        "--env",
        choices=list(ENV_FILES.keys()),
        help="Override ENVIRONMENT variable (development, staging, production)",
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
