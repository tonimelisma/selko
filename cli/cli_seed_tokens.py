#!/usr/bin/env python3
"""CLI for copying OAuth tokens between environments.

Copies OAuth tokens from one environment (e.g., staging) to another (e.g., development)
with automatic user ID remapping. This enables running real Gmail integration tests
against local Supabase without re-authenticating.

The script uses service role keys to bypass RLS and directly access the integrations table.
"""

import argparse
import logging
import sys
from datetime import datetime

from supabase import create_client

from selko.config import Config, add_logging_arguments, load_config
from selko.logging import setup_logging

logger = logging.getLogger(__name__)


class TokenSeedError(Exception):
    """Raised when token seeding fails."""

    pass


def get_integration_by_provider(admin_client, provider: str) -> dict | None:
    """Get integration record by provider (bypasses RLS via service role).

    Args:
        admin_client: Supabase client with service role key.
        provider: Integration provider name (e.g., 'gmail').

    Returns:
        Integration record dict or None if not found.
    """
    result = (
        admin_client.table("integrations")
        .select("*")
        .eq("provider", provider)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    return result.data[0]


def get_user_by_email(admin_client, email: str) -> dict | None:
    """Get user by email using admin API.

    Args:
        admin_client: Supabase client with service role key.
        email: User email to find.

    Returns:
        User dict or None if not found.
    """
    # Use the admin API to list users and find by email
    # The gotrue-py client exposes this via auth.admin
    try:
        users_response = admin_client.auth.admin.list_users()
        for user in users_response:
            if user.email == email:
                return {"id": user.id, "email": user.email}
    except Exception as e:
        logger.warning(f"Could not list users via admin API: {e}")

    # Fallback: query the users table directly
    result = (
        admin_client.table("users").select("id, email").eq("email", email).execute()
    )

    if result.data:
        return result.data[0]

    return None


def load_config_with_prefix(env_name: str, prefix: str) -> Config:
    """Load config, checking for prefixed env vars first (CI mode).

    In CI, env vars like SOURCE_SUPABASE_URL are set instead of .env files.
    This function checks for prefixed vars first, then falls back to load_config.

    Args:
        env_name: Environment name ('development', 'staging', 'production').
        prefix: Prefix for environment variables (e.g., 'SOURCE', 'TARGET').

    Returns:
        Config object with configuration values.

    Raises:
        TokenSeedError: If configuration cannot be loaded.
    """
    import os

    url_var = f"{prefix}_SUPABASE_URL"
    key_var = f"{prefix}_SUPABASE_SERVICE_ROLE_KEY"

    # CI mode: prefixed env vars are set
    if os.getenv(url_var):
        logger.info(f"Using {prefix}_* environment variables for {env_name} config")
        return Config(
            environment=env_name,
            supabase_url=os.getenv(url_var),
            supabase_key=os.getenv(f"{prefix}_SUPABASE_PUBLISHABLE_KEY", ""),
            supabase_service_role_key=os.getenv(key_var),
            test_user_email=os.getenv("TEST_USER_EMAIL"),
            test_user_password=os.getenv("TEST_USER_PASSWORD"),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            microsoft_client_id=os.getenv("MICROSOFT_CLIENT_ID"),
            microsoft_client_secret=os.getenv("MICROSOFT_CLIENT_SECRET"),
        )

    # Local dev mode: use .env files
    try:
        return load_config(env_override=env_name)
    except SystemExit:
        raise TokenSeedError(
            f"Could not load {env_name} config. "
            f"Check that the env file exists and has required variables, "
            f"or set {prefix}_SUPABASE_URL and {prefix}_SUPABASE_SERVICE_ROLE_KEY for CI."
        )


def seed_tokens(
    source_env: str,
    target_env: str,
    provider: str,
) -> None:
    """Copy OAuth tokens from source to target environment with user ID remapping.

    Supports environment variable overrides for CI:
    - SOURCE_SUPABASE_URL / SOURCE_SUPABASE_SERVICE_ROLE_KEY for source config
    - TARGET_SUPABASE_URL / TARGET_SUPABASE_SERVICE_ROLE_KEY for target config

    Args:
        source_env: Source environment ('staging', 'production', 'development').
        target_env: Target environment ('development', 'staging').
        provider: Integration provider to copy (e.g., 'gmail').

    Raises:
        TokenSeedError: If seeding fails.
    """
    logger.info(f"Seeding {provider} tokens from {source_env} to {target_env}")

    # Load configs for both environments
    # Checks for prefixed env vars first (CI mode), then falls back to .env files
    source_config = load_config_with_prefix(source_env, "SOURCE")
    target_config = load_config_with_prefix(target_env, "TARGET")

    # Validate service role keys exist
    if not source_config.supabase_service_role_key:
        raise TokenSeedError(
            f"Missing SUPABASE_SERVICE_ROLE_KEY in {source_env} config"
        )
    if not target_config.supabase_service_role_key:
        raise TokenSeedError(
            f"Missing SUPABASE_SERVICE_ROLE_KEY in {target_env} config"
        )

    # Create admin clients (bypass RLS)
    source_admin = create_client(
        source_config.supabase_url, source_config.supabase_service_role_key
    )
    target_admin = create_client(
        target_config.supabase_url, target_config.supabase_service_role_key
    )

    # Get integration from source
    logger.info(f"Fetching {provider} integration from {source_env}...")
    source_integration = get_integration_by_provider(source_admin, provider)

    if not source_integration:
        raise TokenSeedError(
            f"No {provider} integration found in {source_env}. "
            f"Run: ENVIRONMENT={source_env} uv run python -m cli.cli_auth_gmail"
        )

    logger.debug(f"Found integration for provider_email: {source_integration.get('provider_email')}")

    # Find target user by TEST_USER_EMAIL
    if not target_config.test_user_email:
        raise TokenSeedError(
            f"Missing TEST_USER_EMAIL in {target_env} config"
        )

    logger.info(f"Finding target user {target_config.test_user_email} in {target_env}...")
    target_user = get_user_by_email(target_admin, target_config.test_user_email)

    if not target_user:
        raise TokenSeedError(
            f"User {target_config.test_user_email} not found in {target_env}. "
            f"Create user first: ENVIRONMENT={target_env} uv run python -m cli.cli_user create "
            f"--email {target_config.test_user_email} --password <password> --auto-confirm"
        )

    logger.debug(f"Found target user: {target_user['id']}")

    # Prepare integration data with remapped user_id
    integration_data = {
        "user_id": target_user["id"],  # Remap to target user's UUID
        "provider": source_integration["provider"],
        "status": source_integration["status"],
        "access_token": source_integration["access_token"],
        "refresh_token": source_integration.get("refresh_token"),
        "token_expiry": source_integration.get("token_expiry"),
        "scopes": source_integration.get("scopes", []),
        "provider_email": source_integration.get("provider_email"),
        "sync_cursor": source_integration.get("sync_cursor"),
        "updated_at": datetime.utcnow().isoformat(),
    }

    # Upsert integration in target
    logger.info(f"Upserting {provider} integration in {target_env}...")
    try:
        target_admin.table("integrations").upsert(
            integration_data, on_conflict="user_id,provider"
        ).execute()
    except Exception as e:
        raise TokenSeedError(f"Failed to upsert integration: {e}")

    logger.info(
        f"Successfully seeded {provider} tokens from {source_env} to {target_env}!"
    )
    logger.info(f"  Source user: {source_integration.get('user_id')}")
    logger.info(f"  Target user: {target_user['id']} ({target_user['email']})")
    logger.info(f"  Provider email: {source_integration.get('provider_email')}")


def main():
    parser = argparse.ArgumentParser(
        description="Copy OAuth tokens between environments with user ID remapping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Copy Gmail tokens from staging to local development
  uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail

  # Copy with verbose logging
  uv run python -m cli.cli_seed_tokens -v --from staging --to development --provider gmail

Prerequisites:
  1. OAuth tokens must exist in source environment:
     ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail

  2. Test user must exist in target environment:
     uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm

  3. Both environments must have SUPABASE_SERVICE_ROLE_KEY configured

Note:
  This copies the tokens with user ID remapping - the source and target users
  can have different UUIDs, the script handles the mapping automatically.
        """,
    )
    add_logging_arguments(parser)

    parser.add_argument(
        "--from",
        dest="source_env",
        required=True,
        choices=["development", "staging", "production"],
        help="Source environment to copy tokens from",
    )
    parser.add_argument(
        "--to",
        dest="target_env",
        required=True,
        choices=["development", "staging", "production"],
        help="Target environment to copy tokens to",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=["gmail", "outlook", "google_calendar", "google_photos"],
        help="Integration provider to copy",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    # Validate not copying to same environment
    if args.source_env == args.target_env:
        logger.error("Source and target environments must be different")
        sys.exit(1)

    # Warn about production
    if args.target_env == "production":
        logger.warning("WARNING: You are about to modify production data!")
        response = input("Are you sure you want to continue? [y/N] ")
        if response.lower() != "y":
            logger.info("Aborted")
            sys.exit(0)

    try:
        seed_tokens(args.source_env, args.target_env, args.provider)
    except TokenSeedError as e:
        logger.error(f"Token seeding failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
