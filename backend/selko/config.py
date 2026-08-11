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

from dotenv import dotenv_values

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
    microsoft_client_id: Optional[str] = None
    microsoft_client_secret: Optional[str] = None

    # LLM provider configuration
    llm_provider: str = "gemini"  # gemini|qwen|anthropic|openai|zai|xai|…
    llm_model: Optional[str] = None  # None = PROVIDER_DEFAULT_MODEL[provider]
    llm_thinking: str = "minimal"

    # Fallback route (different provider). Provisional defaults until eval report.
    llm_fallback_provider: Optional[str] = None
    llm_fallback_model: Optional[str] = None
    llm_fallback_thinking: str = "low"
    llm_primary_max_attempts: int = 3
    llm_fallback_max_attempts: int = 2

    # API keys (one per provider)
    gemini_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    zai_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    alibaba_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None
    meta_api_key: Optional[str] = None
    tinker_api_key: Optional[str] = None

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
    worker_calendar_sync_concurrency: int = 2
    # LLM extraction parallelism — emails are independent, so this is the
    # primary knob for draining the 578-pending backlog. 1 = 29 min,
    # 2 = 15 min, 5 = 6 min, 10 = 3 min at ~3s avg. Paid gemini is 60-1000 RPM,
    # so 5 is safe; 10 will hit provider_rate_limited and defer via breaker.
    llm_extraction_concurrency: int = 8
    # How long a claimed LLM-path email is locked. Must outlast the executor
    # queue: a claim held while waiting for a semaphore slot must not expire
    # and get re-claimed (duplicate LLM spend). Default 15 min >> 300s.
    llm_claim_lease_seconds: int = 900
    worker_idle_sleep_seconds: float = 1.0
    # Ceiling for the pool's geometric idle backoff. The flat idle sleep above
    # is the *first* wait after work runs out; consecutive idle ticks back off
    # up to this value so an idle deployment stops polling at tick speed.
    # R3: _tick_seconds() floors at 5.0 so WORKER_IDLE_MAX_SECONDS=1 cannot
    # recreate a busy-wait; the clamp is logged once at DEBUG.
    worker_idle_max_seconds: float = 30.0
    egress_log_interval_seconds: float = 300.0
    worker_error_backoff_seconds: float = 5.0

    # Processing timeouts (seconds)
    email_processing_timeout: int = 120
    photo_processing_timeout: int = 120
    event_sync_timeout: int = 60

    # Whether this process performs background work at all. Off outside
    # production so local servers, tests and CI never poll providers or spend
    # LLM quota. It does not select an ingestion implementation — there is
    # only one.
    enable_background_processing: bool = False
    email_poll_interval_seconds: int = 300
    email_coordinator_tick_seconds: int = 60
    email_retry_base_seconds: int = 60
    email_retry_max_seconds: int = 1800
    email_reconcile_daily_days: int = 30
    email_reconcile_weekly_days: int = 90
    email_reconcile_max_identities: int = 2000
    email_health_warning_seconds: int = 1800
    email_health_critical_seconds: int = 3600
    email_lease_seconds: int = 900
    email_sync_max_run_seconds: int = 900
    # Executor width, NOT poller count. One claim loop per type drains the
    # queue; these bound how many items are processed concurrently. Raising
    # them does not increase database polling.
    email_acquisition_concurrency: int = 2
    email_attachment_concurrency: int = 2
    email_worker_idle_base_seconds: float = 1.0
    email_worker_idle_max_seconds: float = 30.0
    email_worker_error_backoff_seconds: float = 5.0
    email_runtime_watchdog_seconds: int = 30
    recovery_refresh_interval_seconds: float = 30.0
    email_health_interval_seconds: int = 300
    email_folder_refresh_seconds: int = 3600
    # Inc3: direct Postgres work transport (asyncpg session pooler)
    supabase_db_url: str | None = None
    pg_pool_min_size: int = 1
    pg_pool_max_size: int = 4
    pg_keepalive_seconds: int = 60
    pg_connect_timeout_seconds: int = 10
    pg_command_timeout_seconds: int = 30
    worker_safety_poll_seconds: int = 300
    pg_listener_heartbeat_seconds: int = 120
    operational_notification_sender: Optional[str] = None
    operational_notification_recipient: Optional[str] = None
    operational_notification_api_key: Optional[str] = None
    operational_notification_webhook_url: Optional[str] = None
    sentry_dsn: Optional[str] = None

    # Memory instrumentation (leak diagnosis; see services/memory_monitor.py)
    memory_log_interval_seconds: float = 60.0  # <= 0 disables periodic logging
    memory_tracemalloc: bool = False  # log allocation-site growth (expensive)

    # CORS configuration
    allowed_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ])

    # Public URLs for OAuth redirects (no trailing slash)
    api_public_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"


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


def _parse_allowed_origins(getenv=os.getenv) -> list[str]:
    """Parse ALLOWED_ORIGINS from env, fall back to localhost defaults."""
    defaults = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    origins_str = getenv("ALLOWED_ORIGINS", "")
    if origins_str:
        return [o.strip() for o in origins_str.split(",") if o.strip()]
    return defaults


# Primary→fallback pairs (eval-backed Jul 2026). Always a *different* provider
# so a provider-wide outage cannot defeat both.
# Text-only primaries (deepseek, zai glm-5.x) get a vision fallback so
# attachments are never silently dropped — see _ensure_vision_fallback.
_PROVISIONAL_FALLBACK: dict[str, tuple[str, str]] = {
    "gemini": ("qwen", "qwen3.7-flash"),
    "qwen": ("gemini", "gemini-3.5-flash-lite"),
    "anthropic": ("gemini", "gemini-3.5-flash-lite"),
    "openai": ("gemini", "gemini-3.5-flash-lite"),
    "deepseek": ("gemini", "gemini-3.5-flash-lite"),
    "zai": ("gemini", "gemini-3.5-flash-lite"),
    "meta": ("gemini", "gemini-3.5-flash-lite"),
    "moonshot": ("gemini", "gemini-3.5-flash-lite"),
    "minimax": ("gemini", "gemini-3.5-flash-lite"),
    "xai": ("gemini", "gemini-3.5-flash-lite"),
    "tinker": ("gemini", "gemini-3.5-flash-lite"),
}

_VISION_FALLBACK_PROVIDER = "gemini"
_VISION_FALLBACK_MODEL = "gemini-3.5-flash-lite"


def _is_vision_model(model_name: Optional[str]) -> bool:
    """Return True if model supports vision (images/PDFs)."""
    if not model_name:
        return False
    try:
        from selko.services.llm_provider import MODEL_SPECS

        spec = MODEL_SPECS.get(model_name)
        if spec is not None:
            return bool(spec.vision)
    except Exception:
        pass
    # Unknown models are assumed non-vision to be safe (forces fallback).
    return False


def _ensure_vision_fallback(
    primary_provider: str,
    primary_model: Optional[str],
    fallback_provider: Optional[str],
    fallback_model: Optional[str],
    getenv=os.getenv,
) -> tuple[Optional[str], Optional[str]]:
    """Ensure a vision-capable fallback when primary is text-only.

    If the resolved primary model is text-only (vision=False), a text-only
    or missing fallback would silently drop attachments (PDFs/images are
    returned as [] by prepare_content_for_provider). This forces a vision
    fallback (gemini-3.5-flash-lite) when the configured fallback cannot
    cover visuals and a key is available.
    """
    # Resolve primary model name (explicit or provider default).
    if not primary_model:
        try:
            from selko.services.llm_provider import PROVIDER_DEFAULT_MODEL

            primary_model = PROVIDER_DEFAULT_MODEL.get(primary_provider)
        except Exception:
            primary_model = None

    if not _is_vision_model(primary_model):
        # Primary is text-only — fallback must be vision.
        if not fallback_model or not _is_vision_model(fallback_model):
            # Don't override an explicitly configured text-only fallback that
            # the user intentionally set with a key — just warn.
            # Otherwise, auto-select vision fallback if key is present.
            if _fallback_key_present(_VISION_FALLBACK_PROVIDER, getenv):
                logger.warning(
                    "Primary model '%s' is text-only — forcing vision fallback "
                    "%s/%s to ensure attachments are not silently dropped. "
                    "Set LLM_FALLBACK_PROVIDER/MODEL explicitly to override.",
                    primary_model,
                    _VISION_FALLBACK_PROVIDER,
                    _VISION_FALLBACK_MODEL,
                )
                return _VISION_FALLBACK_PROVIDER, _VISION_FALLBACK_MODEL
            else:
                logger.warning(
                    "Primary model '%s' is text-only and no vision fallback key "
                    "(%s) is available — attachments will be dropped on this route. "
                    "Set %s API key or configure a vision fallback.",
                    primary_model,
                    _VISION_FALLBACK_PROVIDER,
                    _VISION_FALLBACK_PROVIDER,
                )
    return fallback_provider, fallback_model


def _resolve_provisional_fallback(
    primary_provider: str,
    fallback_provider: Optional[str],
    fallback_model: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Fill missing fallback provider/model with provisional defaults."""
    if fallback_provider and fallback_model:
        return fallback_provider, fallback_model
    provisional = _PROVISIONAL_FALLBACK.get(primary_provider)
    if not provisional:
        return fallback_provider, fallback_model
    prov_provider, prov_model = provisional
    return (
        fallback_provider or prov_provider,
        fallback_model or prov_model,
    )


def _fallback_key_present(provider_name: Optional[str], getenv=os.getenv) -> bool:
    """Return True when the env has an API key for the fallback provider."""
    if not provider_name:
        return False
    key_env = {
        "gemini": "GEMINI_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "zai": "ZAI_API_KEY",
        "qwen": "ALIBABA_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "xai": "XAI_API_KEY",
        "meta": "META_API_KEY",
        "tinker": "TINKER_API_KEY",
    }.get(provider_name)
    if not key_env:
        return False
    if provider_name == "meta":
        return bool(
            getenv("META_API_KEY")
            or getenv("META_MODEL_API_KEY")
            or getenv("MODEL_API_KEY")
        )
    if provider_name == "zai":
        return bool(getenv("ZAI_API_KEY") or getenv("ZHIPU_API_KEY"))
    return bool(getenv(key_env))


def _warn_if_fallback_unavailable(
    environment: str,
    fallback_provider: Optional[str],
    fallback_model: Optional[str],
    getenv=os.getenv,
) -> None:
    """Loud warning when fallback cannot be used outside test runs."""
    if "pytest" in sys.modules or getenv("PYTEST_CURRENT_TEST"):
        return
    # Treat explicit test-ish environments quietly; staging/prod/dev warn.
    missing_bits = []
    if not fallback_provider:
        missing_bits.append("LLM_FALLBACK_PROVIDER")
    if not fallback_model:
        missing_bits.append("LLM_FALLBACK_MODEL")
    if fallback_provider and not _fallback_key_present(fallback_provider, getenv):
        missing_bits.append(f"API key for fallback provider '{fallback_provider}'")
    if not missing_bits:
        return
    logger.warning(
        "⚠️  LLM FALLBACK UNAVAILABLE in %s environment: missing %s. "
        "Primary failures that need a different provider will not be recovered. "
        "Set LLM_FALLBACK_PROVIDER / LLM_FALLBACK_MODEL and the matching API key. "
        "Current pairing: gemini→qwen/qwen3.7-flash (primary gemini-3.5-flash-lite).",
        environment,
        ", ".join(missing_bits),
    )


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

    # Build an isolated view of the selected file plus the real process
    # environment. Platform variables stay authoritative without mutating
    # os.environ, so one explicit load cannot contaminate a later load.
    values = dict(os.environ)
    if env_path.exists():
        for key, value in dotenv_values(env_path).items():
            if value is not None:
                values.setdefault(key, value)
        logger.info(f"Loaded config from {env_file} ({environment})")
    elif values.get("SUPABASE_URL"):
        # Env vars already set (CI/CD mode)
        logger.info(f"Using environment variables ({environment})")
    else:
        logger.error(f"Environment file not found: {env_path}")
        logger.error(f"Copy .env.example to {env_file} and fill in values.")
        logger.error("Or set environment variables directly (for CI/CD).")
        sys.exit(1)
    getenv = values.get

    # Get required variables
    supabase_url = getenv("SUPABASE_URL")
    supabase_key = getenv("SUPABASE_PUBLISHABLE_KEY")

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

    llm_provider = getenv("LLM_PROVIDER", "gemini")
    llm_fallback_provider = getenv("LLM_FALLBACK_PROVIDER") or None
    llm_fallback_model = getenv("LLM_FALLBACK_MODEL") or None
    llm_fallback_provider, llm_fallback_model = _resolve_provisional_fallback(
        llm_provider, llm_fallback_provider, llm_fallback_model
    )
    # Ensure attachments are never silently dropped: text-only primary
    # must have a vision fallback. This is a safety net even if provisional
    # mapping misses a new text-only model.
    llm_fallback_provider, llm_fallback_model = _ensure_vision_fallback(
        llm_provider,
        getenv("LLM_MODEL") or None,
        llm_fallback_provider,
        llm_fallback_model,
        getenv,
    )
    _warn_if_fallback_unavailable(
        environment, llm_fallback_provider, llm_fallback_model, getenv
    )

    enable_background_processing = (
        getenv("ENABLE_BACKGROUND_PROCESSING", "").lower() == "true"
        if "ENABLE_BACKGROUND_PROCESSING" in values
        else environment == "production"
    )
    supabase_db_url = getenv("SUPABASE_DB_URL")
    if enable_background_processing and not supabase_db_url:
        # Local import: selko.services.pg is a leaf module, but selko.services'
        # package __init__ eagerly imports selko.services.auth, which imports
        # this module — importing pg at module scope here would be circular.
        from selko.services.pg import ConfigurationError

        raise ConfigurationError(
            f"SUPABASE_DB_URL is required in {environment} because "
            "ENABLE_BACKGROUND_PROCESSING is true. Set SUPABASE_DB_URL on the "
            f"{environment} Render service environment to the Supavisor "
            "session pooler URL (port 5432) — it is never committed to a "
            f".env file. See {env_file} for the marker comment."
        )

    return Config(
        environment=environment,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        supabase_service_role_key=getenv("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_jwt_secret=getenv("SUPABASE_JWT_SECRET"),
        google_client_id=getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=getenv("GOOGLE_CLIENT_SECRET"),
        microsoft_client_id=getenv("MICROSOFT_CLIENT_ID"),
        microsoft_client_secret=getenv("MICROSOFT_CLIENT_SECRET"),
        llm_provider=llm_provider,
        llm_model=getenv("LLM_MODEL") or None,
        llm_thinking=getenv("LLM_THINKING", "minimal") or "minimal",
        llm_fallback_provider=llm_fallback_provider,
        llm_fallback_model=llm_fallback_model,
        llm_fallback_thinking=getenv("LLM_FALLBACK_THINKING", "low") or "low",
        llm_primary_max_attempts=int(getenv("LLM_PRIMARY_MAX_ATTEMPTS", "3")),
        llm_fallback_max_attempts=int(getenv("LLM_FALLBACK_MAX_ATTEMPTS", "2")),
        gemini_api_key=getenv("GEMINI_API_KEY"),
        moonshot_api_key=getenv("MOONSHOT_API_KEY"),
        # Local .env may use Zhipu's ZHIPU_API_KEY; Z.AI console uses ZAI_API_KEY.
        zai_api_key=getenv("ZAI_API_KEY") or getenv("ZHIPU_API_KEY"),
        deepseek_api_key=getenv("DEEPSEEK_API_KEY"),
        alibaba_api_key=getenv("ALIBABA_API_KEY"),
        minimax_api_key=getenv("MINIMAX_API_KEY"),
        openai_api_key=getenv("OPENAI_API_KEY"),
        anthropic_api_key=getenv("ANTHROPIC_API_KEY"),
        xai_api_key=getenv("XAI_API_KEY"),
        # Meta docs use MODEL_API_KEY; local .env may use META_MODEL_API_KEY.
        meta_api_key=(
            getenv("META_API_KEY")
            or getenv("META_MODEL_API_KEY")
            or getenv("MODEL_API_KEY")
        ),
        tinker_api_key=getenv("TINKER_API_KEY"),
        test_user_email=getenv("TEST_USER_EMAIL"),
        test_user_password=getenv("TEST_USER_PASSWORD"),
        worker_calendar_sync_concurrency=int(getenv("WORKER_CALENDAR_SYNC_CONCURRENCY", "2")),
        llm_extraction_concurrency=int(getenv("LLM_EXTRACTION_CONCURRENCY", "8")),
        llm_claim_lease_seconds=int(getenv("LLM_CLAIM_LEASE_SECONDS", "900")),
        worker_idle_sleep_seconds=float(getenv("WORKER_IDLE_SLEEP_SECONDS", "1.0")),
        worker_idle_max_seconds=float(getenv("WORKER_IDLE_MAX_SECONDS", "30")),
        egress_log_interval_seconds=float(getenv("EGRESS_LOG_INTERVAL_SECONDS", "300")),
        worker_error_backoff_seconds=float(getenv("WORKER_ERROR_BACKOFF_SECONDS", "5.0")),
        email_processing_timeout=int(getenv("EMAIL_PROCESSING_TIMEOUT", "120")),
        photo_processing_timeout=int(getenv("PHOTO_PROCESSING_TIMEOUT", "120")),
        event_sync_timeout=int(getenv("EVENT_SYNC_TIMEOUT", "60")),
        enable_background_processing=enable_background_processing,
        email_poll_interval_seconds=int(getenv("EMAIL_POLL_INTERVAL_SECONDS", "300")),
        email_coordinator_tick_seconds=int(getenv("EMAIL_COORDINATOR_TICK_SECONDS", "60")),
        email_retry_base_seconds=int(getenv("EMAIL_RETRY_BASE_SECONDS", "60")),
        email_retry_max_seconds=int(getenv("EMAIL_RETRY_MAX_SECONDS", "1800")),
        email_reconcile_daily_days=int(getenv("EMAIL_RECONCILE_DAILY_DAYS", "30")),
        email_reconcile_weekly_days=int(getenv("EMAIL_RECONCILE_WEEKLY_DAYS", "90")),
        email_reconcile_max_identities=int(getenv("EMAIL_RECONCILE_MAX_IDENTITIES", "2000")),
        email_health_warning_seconds=int(getenv("EMAIL_HEALTH_WARNING_SECONDS", "1800")),
        email_health_critical_seconds=int(getenv("EMAIL_HEALTH_CRITICAL_SECONDS", "3600")),
        email_lease_seconds=int(getenv("EMAIL_LEASE_SECONDS", "900")),
        email_sync_max_run_seconds=int(getenv("EMAIL_SYNC_MAX_RUN_SECONDS", "900")),
        email_acquisition_concurrency=int(getenv("EMAIL_ACQUISITION_CONCURRENCY", "2")),
        email_attachment_concurrency=int(getenv("EMAIL_ATTACHMENT_CONCURRENCY", "2")),
        email_worker_idle_base_seconds=float(getenv("EMAIL_WORKER_IDLE_BASE_SECONDS", "1")),
        email_worker_idle_max_seconds=float(getenv("EMAIL_WORKER_IDLE_MAX_SECONDS", "30")),
        email_worker_error_backoff_seconds=float(getenv("EMAIL_WORKER_ERROR_BACKOFF_SECONDS", "5")),
        email_runtime_watchdog_seconds=int(getenv("EMAIL_RUNTIME_WATCHDOG_SECONDS", "30")),
        recovery_refresh_interval_seconds=float(getenv("RECOVERY_REFRESH_INTERVAL_SECONDS", "30")),
        email_health_interval_seconds=int(getenv("EMAIL_HEALTH_INTERVAL_SECONDS", "300")),
        email_folder_refresh_seconds=int(getenv("EMAIL_FOLDER_REFRESH_SECONDS", "3600")),
        supabase_db_url=supabase_db_url,
        pg_pool_min_size=int(getenv("PG_POOL_MIN_SIZE", "1")),
        pg_pool_max_size=int(getenv("PG_POOL_MAX_SIZE", "4")),
        pg_keepalive_seconds=int(getenv("PG_KEEPALIVE_SECONDS", "60")),
        pg_connect_timeout_seconds=int(getenv("PG_CONNECT_TIMEOUT_SECONDS", "10")),
        pg_command_timeout_seconds=int(getenv("PG_COMMAND_TIMEOUT_SECONDS", "30")),
        worker_safety_poll_seconds=max(60, int(getenv("WORKER_SAFETY_POLL_SECONDS", "300"))),
        pg_listener_heartbeat_seconds=int(getenv("PG_LISTENER_HEARTBEAT_SECONDS", "120")),
        operational_notification_sender=getenv("OPERATIONAL_NOTIFICATION_SENDER"),
        operational_notification_recipient=getenv("OPERATIONAL_NOTIFICATION_RECIPIENT"),
        operational_notification_api_key=getenv("OPERATIONAL_NOTIFICATION_API_KEY"),
        operational_notification_webhook_url=getenv("OPERATIONAL_NOTIFICATION_WEBHOOK_URL"),
        sentry_dsn=getenv("SENTRY_DSN"),
        memory_log_interval_seconds=float(getenv("MEMORY_LOG_INTERVAL_SECONDS", "60")),
        memory_tracemalloc=getenv("MEMORY_TRACEMALLOC", "").lower() == "true",
        allowed_origins=_parse_allowed_origins(getenv),
        api_public_url=getenv("API_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
        frontend_url=getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/"),
        max_pdf_pages_for_llm=int(getenv("MAX_PDF_PAGES_FOR_LLM", "10")),
        max_image_size_for_llm=int(getenv("MAX_IMAGE_SIZE_FOR_LLM", str(10 * 1024 * 1024))),
        max_other_size_for_llm=int(getenv("MAX_OTHER_SIZE_FOR_LLM", str(20 * 1024 * 1024))),
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
