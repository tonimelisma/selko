"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from selko.api.routes import (
    calendars_router,
    emails_router,
    events_router,
    health_router,
    integrations_router,
    photos_router,
)
from selko.services.auth import AuthenticationError
from selko.services.calendars import CalendarsError
from selko.services.emails import EmailError
from selko.services.events import EventsError
from selko.services.integrations import IntegrationError, OAuthStateError
from selko.services.photos import PhotosError
from selko.services.quotas import QuotaExceededError
from selko.config import load_config
from selko.services.memory_monitor import start_memory_monitor
from selko.services.pg import create_pool
from selko.workers.pool import WorkerPool

logger = logging.getLogger(__name__)

# Global worker pool instance
worker_pool: WorkerPool = None

# Global email ingestion runtime (async monolith mode)
ingestion_runtime = None


def get_user_id_or_ip(request: Request) -> str:
    """Rate limit key function: by user_id if authenticated, else by IP.

    Args:
        request: FastAPI request object.

    Returns:
        Rate limit key string (user:{id} or ip:{address}).
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        # Extract actual user ID from JWT for consistent rate limiting
        try:
            from jose import jwt
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub", token[:32])
            return f"user:{user_id}"
        except Exception:
            # Fall back to token prefix if JWT decode fails
            return f"user:{token[:32]}"
    return f"ip:{get_remote_address(request)}"


# Create limiter with user/IP key function
limiter = Limiter(key_func=get_user_id_or_ip, default_limits=["60/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events.

    This implements the Async Monolith pattern where the API server and
    background workers run in the same process.

    `ENABLE_BACKGROUND_PROCESSING` decides whether this process does background
    work at all — off outside production so local servers, tests and CI never
    poll providers or spend LLM quota. It does not select an implementation:
    email ingestion is the durable polling runtime and nothing else. There is
    no APScheduler; the ingestion coordinator owns its own polling cadence.
    """
    global worker_pool, ingestion_runtime

    # Startup
    logger.info("Starting Selko API")

    # Load configuration
    config = load_config()

    pg_pool = None

    memory_monitor_task = start_memory_monitor(
        config.memory_log_interval_seconds,
        config.memory_tracemalloc,
    )

    if config.enable_background_processing:
        from selko.services.auth import get_service_client
        from selko.services.emails import unlock_expired_email_locks
        from selko.services.events import unlock_expired_event_locks
        from selko.services.integrations import unlock_expired_integration_recoveries
        from selko.services.photos import unlock_expired_photo_locks
        from selko.services.scheduled_tasks import unlock_expired_scheduled_tasks
        from selko.workers.ingestion_runtime import IngestionRuntime

        logger.info("Starting background processing (worker pool + email ingestion)")
        # The direct-pg transport is the only transport for worker coordination.
        # A missing URL or a failed pool is a configuration error. There is
        # nothing to fall back to, and pretending otherwise is how this shipped
        # broken the first time.
        pg_pool = await create_pool(config)
        app.state.pg_pool = pg_pool
        logger.info("Supavisor session pooler connected")
        service_client = get_service_client(config)

        worker_pool = WorkerPool(
            num_workers=config.worker_pool_size,
            idle_sleep_seconds=config.worker_idle_sleep_seconds,
            error_backoff_seconds=config.worker_error_backoff_seconds,
            pg_pool=pg_pool,
        )
        await worker_pool.start()

        # Recover any stale jobs from a previous instance crash. Email sync
        # leases need no equivalent step: claims reclaim expired leases.
        emails_unlocked = await unlock_expired_email_locks(pg_pool)
        events_unlocked = await unlock_expired_event_locks(pg_pool)
        photos_unlocked = await unlock_expired_photo_locks(pg_pool)
        tasks_unlocked = await unlock_expired_scheduled_tasks(pg_pool)
        recoveries_unlocked = await unlock_expired_integration_recoveries(pg_pool)

        if (
            emails_unlocked or events_unlocked or photos_unlocked
            or tasks_unlocked or recoveries_unlocked
        ):
            logger.info(
                f"Recovered stale jobs on startup: "
                f"{emails_unlocked} emails, {events_unlocked} events, "
                f"{photos_unlocked} photos, {tasks_unlocked} tasks, "
                f"{recoveries_unlocked} integration recoveries"
            )

        ingestion_runtime = IngestionRuntime(service_client, config, pg_pool=pg_pool)
        await ingestion_runtime.start()

        logger.info("Background workers started successfully")
    else:
        logger.info(
            "Background processing disabled "
            "(set ENABLE_BACKGROUND_PROCESSING=true to enable)"
        )

    yield

    # Shutdown
    logger.info("Shutting down Selko API")

    if memory_monitor_task:
        memory_monitor_task.cancel()

    # Only stop what was actually started. Ingestion stops first so no new
    # provider work is claimed while the pool drains; unfinished leases expire
    # and are reclaimed by whichever instance comes up next.
    if config.enable_background_processing:
        if ingestion_runtime:
            await ingestion_runtime.stop()
        if worker_pool:
            await worker_pool.stop()
        if pg_pool:
            await pg_pool.close()
            logger.info("Pg pool closed")

        logger.info("Background workers shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    # Try to load config for CORS, fall back to defaults if not available
    # This allows app creation during test collection when env vars aren't set
    try:
        config = load_config()
        allowed_origins = config.allowed_origins
    except SystemExit:
        # Config not available (e.g., during test collection without env vars)
        # Use default localhost origins for CORS
        config = None
        allowed_origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]

    # Initialize Sentry when a DSN is configured. Unset => no-op, so local
    # servers, tests and CI are unaffected. This is the only APM path; until
    # someone is available to watch a metrics backend, structured log lines
    # (increment 5c) plus Sentry is the right amount for a single-operator
    # deployment.
    if config is not None and getattr(config, "sentry_dsn", None):
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastapiIntegration

            sentry_sdk.init(
                dsn=config.sentry_dsn,
                environment=config.environment,
                traces_sample_rate=0.0,
                send_default_pii=False,
                integrations=[FastapiIntegration()],
            )
            logger.info("Sentry initialized (environment=%s)", config.environment)
        except Exception:
            logger.exception("Sentry initialization failed; continuing without APM")

    app = FastAPI(
        title="Selko API",
        description="AI-powered personal organization assistant",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Store limiter in app state for access in routes
    app.state.limiter = limiter

    # Add SlowAPI rate limiting middleware
    app.add_middleware(SlowAPIMiddleware)

    # Configure CORS from environment
    # Note: Specific methods/headers instead of wildcards for security
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # Include routers (server-side endpoints only)
    # For direct database queries, frontends use Supabase client
    app.include_router(health_router)
    app.include_router(emails_router)
    app.include_router(integrations_router)
    app.include_router(events_router)
    app.include_router(calendars_router)
    app.include_router(photos_router)

    # Exception handlers for service errors
    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError):
        logger.warning(f"Authentication error: {exc}")
        return JSONResponse(
            status_code=401,
            content={"error": "authentication_error", "detail": "Authentication failed"},
        )

    @app.exception_handler(EmailError)
    async def email_error_handler(request: Request, exc: EmailError):
        logger.error(f"Email service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "email_error", "detail": "Email operation failed"},
        )

    @app.exception_handler(OAuthStateError)
    async def oauth_state_error_handler(request: Request, exc: OAuthStateError):
        logger.warning(f"OAuth state error: {exc}")
        return JSONResponse(
            status_code=400,
            content={"error": "oauth_state_error", "detail": "OAuth state invalid or expired"},
        )

    @app.exception_handler(IntegrationError)
    async def integration_error_handler(request: Request, exc: IntegrationError):
        logger.error(f"Integration service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "integration_error", "detail": "Integration operation failed"},
        )

    @app.exception_handler(EventsError)
    async def events_error_handler(request: Request, exc: EventsError):
        logger.error(f"Events service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "events_error", "detail": "Event operation failed"},
        )

    @app.exception_handler(CalendarsError)
    async def calendars_error_handler(request: Request, exc: CalendarsError):
        logger.error(f"Calendars service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "calendars_error", "detail": "Calendar operation failed"},
        )

    @app.exception_handler(PhotosError)
    async def photos_error_handler(request: Request, exc: PhotosError):
        logger.error(f"Photos service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "photos_error", "detail": "Photos operation failed"},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        logger.warning(f"Rate limit exceeded: {exc.detail}")
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "detail": "Too many requests. Please try again later.",
            },
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(QuotaExceededError)
    async def quota_exceeded_handler(request: Request, exc: QuotaExceededError):
        logger.warning(f"Quota exceeded: {exc.quota_type} for user")
        return JSONResponse(
            status_code=429,
            content={
                "error": "quota_exceeded",
                "detail": f"Daily {exc.quota_type} quota exceeded",
                "quota_type": exc.quota_type,
                "limit": exc.limit,
                "resets_at": "midnight UTC",
            },
        )

    return app


# Create the app instance
app = create_app()
