"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
from selko.workers.email_fetch import schedule_email_fetches
from selko.workers.photo_fetch import schedule_photo_fetches
from selko.workers.pool import WorkerPool

logger = logging.getLogger(__name__)

# Global scheduler instance (for cron jobs only)
scheduler = AsyncIOScheduler()

# Global worker pool instance
worker_pool: WorkerPool = None


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

    This implements the Async Monolith pattern where the API server,
    background workers, and cron jobs all run in the same process.

    Background processing (workers + scheduler) is OFF by default and requires
    ENABLE_BACKGROUND_PROCESSING=true to enable. This allows running the API
    without background workers for development, testing, or lightweight deployments.

    - Worker pool: Continuously processes pending emails and events from data tables
    - APScheduler: Runs periodic tasks (e.g., email fetch scheduling)
    """
    global worker_pool

    # Startup
    logger.info("Starting Selko API")

    # Load configuration
    config = load_config()

    if config.enable_background_processing:
        # Start worker pool for job processing
        logger.info("Starting worker pool for background job processing")
        worker_pool = WorkerPool(
            num_workers=config.worker_pool_size,
            idle_sleep_seconds=config.worker_idle_sleep_seconds,
            error_backoff_seconds=config.worker_error_backoff_seconds,
        )
        await worker_pool.start()

        # Recover any stale jobs from previous instance crash
        from selko.services.auth import get_service_client
        from selko.services.emails import unlock_expired_email_locks
        from selko.services.events import unlock_expired_event_locks
        from selko.services.photos import unlock_expired_photo_locks
        from selko.services.scheduled_tasks import unlock_expired_scheduled_tasks

        service_client = get_service_client(config)
        emails_unlocked = unlock_expired_email_locks(service_client)
        events_unlocked = unlock_expired_event_locks(service_client)
        photos_unlocked = unlock_expired_photo_locks(service_client)
        tasks_unlocked = unlock_expired_scheduled_tasks(service_client)

        if emails_unlocked or events_unlocked or photos_unlocked or tasks_unlocked:
            logger.info(
                f"Recovered stale jobs on startup: "
                f"{emails_unlocked} emails, {events_unlocked} events, "
                f"{photos_unlocked} photos, {tasks_unlocked} tasks"
            )

        # Start APScheduler for cron-like periodic tasks
        logger.info("Starting APScheduler for periodic tasks")

        # Email fetch scheduler - run immediately on start, then every 15 minutes
        scheduler.add_job(
            schedule_email_fetches,
            "interval",
            minutes=15,
            id="email_fetch_scheduler",
            name="Email Fetch Scheduler",
            max_instances=1,
            next_run_time=datetime.now(timezone.utc),
        )

        # Photo fetch scheduler - run immediately on start, then every 30 minutes
        scheduler.add_job(
            schedule_photo_fetches,
            "interval",
            minutes=30,
            id="photo_fetch_scheduler",
            name="Photo Fetch Scheduler",
            max_instances=1,
            next_run_time=datetime.now(timezone.utc),
        )

        scheduler.start()
        logger.info("Background workers started successfully")
    else:
        logger.info(
            "Background processing disabled "
            "(set ENABLE_BACKGROUND_PROCESSING=true to enable)"
        )

    yield

    # Shutdown
    logger.info("Shutting down Selko API")

    # Only stop background workers if they were started
    if config.enable_background_processing:
        # Stop worker pool first (workers complete current work)
        if worker_pool:
            await worker_pool.stop()

        # Then stop scheduler
        scheduler.shutdown(wait=True)

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
        allowed_origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]

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
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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
