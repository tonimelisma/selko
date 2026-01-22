#!/usr/bin/env python3
"""Centralized configuration module for Selko POC.

Handles environment detection and .env file loading with support for
development/staging/production environments.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

# Project root directory (parent of poc/)
PROJECT_ROOT = Path(__file__).parent.parent
POC_DIR = Path(__file__).parent

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
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None

    # Paths (derived, not from env)
    credentials_file: Path = POC_DIR / "credentials.json"
    token_file: Path = POC_DIR / "token.json"
    emails_dir: Path = POC_DIR / "emails"


def get_environment(override: Optional[str] = None) -> str:
    """Get the current environment name.

    Args:
        override: Optional environment name to use instead of env variable.

    Returns:
        Environment name: 'development', 'staging', or 'production'.
    """
    if override:
        return override
    return os.getenv("ENVIRONMENT", "development")


def load_config(env_override: Optional[str] = None) -> Config:
    """Load configuration from the appropriate .env file.

    Args:
        env_override: Optional environment name to override ENVIRONMENT variable.

    Returns:
        Config object with all configuration values.

    Raises:
        SystemExit: If required environment variables are missing.
    """
    environment = get_environment(env_override)

    # Determine which .env file to load
    env_file = ENV_FILES.get(environment)
    if not env_file:
        print(f"Error: Unknown environment '{environment}'")
        print(f"Valid environments: {', '.join(ENV_FILES.keys())}")
        sys.exit(1)

    env_path = PROJECT_ROOT / env_file

    if not env_path.exists():
        print(f"Error: Environment file not found: {env_path}")
        print(f"Copy .env.example to {env_file} and fill in values.")
        sys.exit(1)

    # Load environment variables from file
    load_dotenv(env_path, override=True)
    print(f"Loaded config from {env_file} ({environment})")

    # Get required variables
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")

    # Validate required variables
    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not supabase_anon_key:
        missing.append("SUPABASE_ANON_KEY")

    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print(f"Check your {env_file} file.")
        sys.exit(1)

    return Config(
        environment=environment,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    )


def get_supabase_client(config: Config, use_service_role: bool = False) -> Client:
    """Initialize and return a Supabase client.

    Args:
        config: Configuration object with Supabase credentials.
        use_service_role: If True, use service role key (bypasses RLS).
                         Default is False (uses anon key).

    Returns:
        Initialized Supabase client.

    Raises:
        SystemExit: If service role key is requested but not configured.
    """
    key = config.supabase_anon_key

    if use_service_role:
        if not config.supabase_service_role_key:
            print("Error: SUPABASE_SERVICE_ROLE_KEY not configured")
            sys.exit(1)
        key = config.supabase_service_role_key

    return create_client(config.supabase_url, key)


def add_env_argument(parser) -> None:
    """Add --env argument to an argparse parser.

    Args:
        parser: argparse.ArgumentParser instance.
    """
    parser.add_argument(
        "--env",
        choices=list(ENV_FILES.keys()),
        help="Override ENVIRONMENT variable (development, staging, production)",
    )
