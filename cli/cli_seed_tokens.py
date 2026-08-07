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

# Token staleness threshold — if expiry is within this window, treat as stale
# and copy from the other env rather than failing. Google refresh tokens
# typically expire in 1h, but we use 5m buffer.
_STALE_BUFFER_SECONDS = 300

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
    # An unordered limit(1) silently picks an arbitrary row, and environments
    # routinely hold several accounts per provider — seeding an expired one
    # looks like a successful copy but leaves the target unusable. Take an
    # active integration, and only fall back to a non-active row if that is
    # genuinely all there is.
    result = (
        admin_client.table("integrations")
        .select("*")
        .eq("provider", provider)
        .order("updated_at", desc=True)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None

    active = [row for row in rows if row.get("status") == "active"]
    if not active:
        logger.warning(
            "No active %s integration in source; seeding a %s one",
            provider,
            rows[0].get("status"),
        )
    return (active or rows)[0]


def is_integration_stale(integration: dict | None) -> bool:
    """Return True if integration is missing, non-active, or expiry is past.

    This is the predicate for dev↔staging auto-sync: if either env is stale
    and the other is fresh, copy fresh → stale. Both stale → need reauth.
    Production is never considered here.
    """
    if not integration:
        return True
    if integration.get("status") != "active":
        return True
    # No expiry at all is treated as stale — cannot verify
    expiry_raw = integration.get("token_expiry")
    if not expiry_raw:
        return True
    try:
        # token_expiry may be "2026-02-12T...Z" or with microseconds
        expiry = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
        # naive datetimes in DB are assumed UTC
        if expiry.tzinfo is None:
            from datetime import timezone as _tz
            expiry = expiry.replace(tzinfo=_tz.utc)
        from datetime import timezone
        now = datetime.now(timezone.utc)
        # if expiry is within buffer or past, stale
        if (expiry - now).total_seconds() < _STALE_BUFFER_SECONDS:
            return True
    except Exception:
        # Unparseable expiry -> stale
        return True
    # Also stale if refresh_token missing (cannot refresh)
    if not integration.get("refresh_token"):
        return True
    return False


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
    # Enforced here as well as in argparse: seed_tokens is importable and is
    # called directly by CI, so the guarantee cannot live in the CLI surface
    # alone. Production credentials belong to real users and must never reach a
    # lower-trust environment, nor be overwritten by burner tokens.
    for label, env in (("source", source_env), ("target", target_env)):
        if env == "production":
            raise TokenSeedError(
                f"Refusing to use production as the {label} environment. "
                "Reconnect production through the normal OAuth flow instead."
            )

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


def sync_dev_staging(provider: str) -> str:
    """Check both dev and staging; copy working → stale if one is stale.

    Returns the direction taken ("development->staging", "staging->development",
    or "already in sync"). Raises TokenSeedError if both are stale or both missing.
    Production is never touched.
    """
    # Load both envs via prefixed or .env files; validate service keys present
    dev_config = load_config_with_prefix("development", "SOURCE")
    staging_config = load_config_with_prefix("staging", "TARGET")
    # Re-load staging as SOURCE for symmetry when checking staging→dev
    # (load_config_with_prefix handles both .env and prefixed CI vars)
    # For staleness check we just need the integrations, so load both clients
    dev_admin = create_client(dev_config.supabase_url, dev_config.supabase_service_role_key)
    staging_admin = create_client(staging_config.supabase_url, staging_config.supabase_service_role_key)

    dev_integration = get_integration_by_provider(dev_admin, provider)
    staging_integration = get_integration_by_provider(staging_admin, provider)

    dev_stale = is_integration_stale(dev_integration)
    staging_stale = is_integration_stale(staging_integration)

    logger.info(
        f"Dev↔Staging sync check for {provider}: dev stale={dev_stale} (status={dev_integration.get('status') if dev_integration else 'missing'}), "
        f"staging stale={staging_stale} (status={staging_integration.get('status') if staging_integration else 'missing'})"
    )

    if not dev_stale and not staging_stale:
        logger.info("Both dev and staging tokens are fresh — nothing to do")
        return "already in sync"

    if dev_stale and staging_stale:
        raise TokenSeedError(
            f"Both dev and staging {provider} tokens are stale/missing — need fresh OAuth. "
            f"Run: uv run python -m cli.cli_auth_gmail (for dev) or ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail"
        )

    if dev_stale and not staging_stale:
        logger.info(f"Dev stale, staging fresh — copying staging → development for {provider}")
        seed_tokens("staging", "development", provider)
        return "staging->development"

    # staging stale, dev fresh
    logger.info(f"Staging stale, dev fresh — copying development → staging for {provider}")
    seed_tokens("development", "staging", provider)
    return "development->staging"


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

  # Auto-sync dev↔staging: check both, copy working → stale
  uv run python -m cli.cli_seed_tokens --sync --provider gmail
  uv run python -m cli.cli_seed_tokens --sync --provider gmail --provider outlook

Prerequisites:
  1. OAuth tokens must exist in source environment (for explicit --from/--to):
     ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail

  2. For --sync, at least one of dev/staging must have a fresh token; the
     stale side is overwritten with the fresh side. If both are stale, re-auth
     one side then re-run --sync.

  3. Test user must exist in target environment:
     uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm

  4. Both environments must have SUPABASE_SERVICE_ROLE_KEY configured

Note:
  Production is never a source or target for seeding — it holds real users'
  OAuth credentials. Dev and staging are kept in sync via --sync; if either is
  stale the working side is copied to the stale side automatically.
        """,
    )
    add_logging_arguments(parser)

    # Production is deliberately not selectable at either end. This is a
    # developer convenience for seeding burner test tokens; production holds
    # real users' OAuth credentials, which must never be copied down into a
    # lower-trust environment, and real integrations must never be overwritten
    # with burner tokens. Reconnect production through the normal OAuth flow.
    parser.add_argument(
        "--from",
        dest="source_env",
        required=False,
        default=None,
        choices=["development", "staging"],
        help="Source environment to copy tokens from (never production)",
    )
    parser.add_argument(
        "--to",
        dest="target_env",
        required=False,
        default=None,
        choices=["development", "staging"],
        help="Target environment to copy tokens to (never production)",
    )
    parser.add_argument(
        "--provider",
        required=False,
        default=None,
        choices=["gmail", "outlook", "google_calendar", "google_photos"],
        help="Integration provider to copy (or all with --sync)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Check both dev and staging; copy working → stale (or do nothing if both fresh). Production never touched.",
    )
    parser.add_argument(
        "--all-providers",
        action="store_true",
        help="With --sync, sync all providers (gmail, outlook, google_calendar)",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    # --sync mode: check both dev/staging, copy working → stale
    if args.sync:
        providers = []
        if args.all_providers:
            providers = ["gmail", "outlook", "google_calendar"]
        elif args.provider:
            providers = [args.provider]
        else:
            # Default: sync gmail (most common) — explicit is better for safety
            logger.error("--sync requires --provider <name> or --all-providers")
            sys.exit(1)
        failed = []
        for prov in providers:
            try:
                direction = sync_dev_staging(prov)
                logger.info(f"Sync {prov}: {direction}")
            except TokenSeedError as e:
                logger.error(f"Sync {prov} failed: {e}")
                failed.append(prov)
        if failed:
            sys.exit(1)
        return

    # Explicit --from/--to mode (legacy)
    if not args.source_env or not args.target_env or not args.provider:
        parser.error("--from/--to/--provider are required unless --sync is used")
    # Validate not copying to same environment
    if args.source_env == args.target_env:
        logger.error("Source and target environments must be different")
        sys.exit(1)

    try:
        seed_tokens(args.source_env, args.target_env, args.provider)
    except TokenSeedError as e:
        logger.error(f"Token seeding failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
