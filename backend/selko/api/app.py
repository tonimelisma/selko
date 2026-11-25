"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from selko.api.routes import (
    calendars_router,
    emails_router,
    events_router,
    health_router,
    integrations_router,
    photos_router,
)
from selko.api.routes.auth import router as auth_router
from selko.api.routes.client import router as client_router
from selko.api.routes.live import router as live_router
from selko.services.auth import AuthenticationError
from selko.services.calendars import CalendarsError
from selko.services.emails import EmailError
from selko.services.events import EventsError
from selko.services.request_metrics import request_metrics
from selko.services.integrations import IntegrationError, OAuthStateError
from selko.services.photos import PhotosError
from selko.services.quotas import QuotaExceededError
from selko.config import load_config
from selko.services.memory_monitor import start_memory_monitor
from selko.workers.pool import WorkerPool

logger = logging.getLogger(__name__)

# Global worker pool instance
worker_pool: WorkerPool = None

# Global email ingestion runtime (async monolith mode)
ingestion_runtime = None


from selko.api.limits import get_user_id_or_ip, limiter  # noqa: E402,F401  (re-exported)


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

    # The database comes first: migrations run before anything is served, and
    # a failed migration stops the process (the previous image keeps running).
    from selko.db.runtime import open_database
    from selko.db.startup import reset_leases_at_startup
    from selko.services.accounts import TokenKeys

    db = open_database(config.data_dir)
    app.state.db = db
    app.state.bus = db.bus
    app.state.environment = config.environment
    app.state.allowed_origins = config.allowed_origins
    app.state.token_keys = TokenKeys(config.jwt_secret, config.jwt_secret_previous) if config.jwt_secret else None
    await db.signals.start()

    memory_monitor_task = start_memory_monitor(
        config.memory_log_interval_seconds,
        config.memory_tracemalloc,
    )

    if config.enable_background_processing:
        from selko.workers.ingestion_runtime import IngestionRuntime

        logger.info("Starting background processing (worker pool + email ingestion)")
        # One process owns every lease, so any lease present now belongs to a
        # dead run. Release them before a single worker starts.
        released = await db.run(reset_leases_at_startup, db)
        if any(released.values()):
            logger.info("Released stale leases on startup: %s", {k: v for k, v in released.items() if v})

        worker_pool = WorkerPool(
            idle_sleep_seconds=config.worker_idle_sleep_seconds,
            error_backoff_seconds=config.worker_error_backoff_seconds,
            pg_pool=db,
            work_listener=db.signals,
        )
        await worker_pool.start()

        ingestion_runtime = IngestionRuntime(db, config, pg_pool=db, work_listener=db.signals)
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
        logger.info("Background workers shutdown complete")

    await db.signals.stop()
    from selko.db.runtime import close_database

    close_database()


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

    @app.middleware("http")
    async def record_response_outcome(request: Request, call_next):
        """Count what we actually answer, so a 500 storm is visible in /health.

        Health measured internal state only -- workers, queues, listener -- so
        production answered 500 to every /apply-change for eight days with every
        invariant green. This is the missing signal.
        """
        response = await call_next(request)
        route = request.scope.get("route")
        request_metrics.record(
            status_code=response.status_code,
            # The route template, never the concrete path: no identifiers.
            route=getattr(route, "path", "unmatched"),
        )
        return response

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

    # Include routers; routes/client.py is the web app's data API.
    app.include_router(health_router)
    app.include_router(emails_router)
    app.include_router(integrations_router)
    app.include_router(events_router)
    app.include_router(calendars_router)
    app.include_router(photos_router)
    app.include_router(auth_router)
    app.include_router(client_router)
    app.include_router(live_router)

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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Return unexpected failures as a normal response, not a bare crash.

        Without this, an unhandled exception is turned into a 500 by Starlette's
        ServerErrorMiddleware, which sits *outside* CORSMiddleware -- so the
        response carries no Access-Control-Allow-Origin header and the browser
        refuses to read it. The client sees a network-level failure
        ("Load failed" in Safari) rather than the actual error.

        That masked a real outage: /events/{id}/apply-change raised KeyError on
        every call for eight days, and the web app could only report that the
        request had failed to load, which reads like a connectivity problem and
        is not one. Handling the exception here routes the response back through
        CORSMiddleware, so a 500 arrives as a readable 500.

        The body stays deliberately content-free; details go to the logs.
        """
        logger.exception("Unhandled error serving %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": "Internal server error"},
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

    mount_web_app(app)
    return app


# Paths the web app owns; everything else is the API's. The SPA routes itself,
# so any of these answers index.html unless it names a built file.
WEB_PATH_PREFIXES = ("/app", "/login", "/register", "/privacy", "/_app/")
WEB_PATHS = {"/", "/favicon.png", "/favicon.svg", "/robots.txt", "/manifest.webmanifest"}


def mount_web_app(app: FastAPI) -> None:
    """Serve the built web app from SELKO_WEB_DIR (the image sets it to /app/web).

    Unset or missing: the API alone (development uses the Vite dev server).
    """
    import os
    from pathlib import Path

    from fastapi.responses import FileResponse

    web_dir = os.environ.get("SELKO_WEB_DIR")
    if not web_dir or not (Path(web_dir) / "index.html").is_file():
        return
    root = Path(web_dir).resolve()
    index = root / "index.html"

    async def web(request: Request) -> FileResponse:
        relative = request.url.path.lstrip("/")
        target = (root / relative).resolve() if relative else index
        if target != index and root in target.parents and target.is_file():
            # Built assets are content-hashed: cache them for good.
            immutable = request.url.path.startswith("/_app/immutable/")
            return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"} if immutable else {})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    for prefix in WEB_PATH_PREFIXES:
        app.add_api_route(prefix.rstrip("/") or "/", web, methods=["GET"], include_in_schema=False)
        app.add_api_route(prefix.rstrip("/") + "/{path:path}", web, methods=["GET"], include_in_schema=False)
    for exact in WEB_PATHS:
        app.add_api_route(exact, web, methods=["GET"], include_in_schema=False)


# Create the app instance
app = create_app()
