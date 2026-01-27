"""FastAPI application factory."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from selko.api.routes import (
    attachments_router,
    calendars_router,
    emails_router,
    events_router,
    health_router,
    integrations_router,
    jobs_router,
    sender_rules_router,
)
from selko.services.auth import AuthenticationError
from selko.services.calendars import CalendarsError
from selko.services.emails import EmailError
from selko.services.events import EventsError
from selko.services.integrations import IntegrationError
from selko.config import load_config
from selko.services.jobs import JobsError
from selko.workers.email_fetch import schedule_email_fetches
from selko.workers.pool import WorkerPool

logger = logging.getLogger(__name__)

# Global scheduler instance (for cron jobs only)
scheduler = AsyncIOScheduler()

# Global worker pool instance
worker_pool: WorkerPool = None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Selko API",
        description="AI-powered personal organization assistant",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # React dev server
            "http://localhost:5173",  # Vite dev server
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(emails_router)
    app.include_router(integrations_router)
    app.include_router(events_router)
    app.include_router(calendars_router)
    app.include_router(sender_rules_router)
    app.include_router(jobs_router)
    app.include_router(attachments_router)

    # Exception handlers for service errors
    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError):
        logger.warning(f"Authentication error: {exc}")
        return JSONResponse(
            status_code=401,
            content={"error": "authentication_error", "detail": str(exc)},
        )

    @app.exception_handler(EmailError)
    async def email_error_handler(request: Request, exc: EmailError):
        logger.error(f"Email service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "email_error", "detail": str(exc)},
        )

    @app.exception_handler(IntegrationError)
    async def integration_error_handler(request: Request, exc: IntegrationError):
        logger.error(f"Integration service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "integration_error", "detail": str(exc)},
        )

    @app.exception_handler(EventsError)
    async def events_error_handler(request: Request, exc: EventsError):
        logger.error(f"Events service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "events_error", "detail": str(exc)},
        )

    @app.exception_handler(CalendarsError)
    async def calendars_error_handler(request: Request, exc: CalendarsError):
        logger.error(f"Calendars service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "calendars_error", "detail": str(exc)},
        )

    @app.exception_handler(JobsError)
    async def jobs_error_handler(request: Request, exc: JobsError):
        logger.error(f"Jobs service error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "jobs_error", "detail": str(exc)},
        )

    # Startup event: Initialize worker pool and scheduler
    @app.on_event("startup")
    async def start_background_workers():
        """Start worker pool and APScheduler for background processing.

        This implements the Async Monolith pattern where the API server,
        background workers, and cron jobs all run in the same process.
        
        - Worker pool: Continuously processes jobs from the queue
        - APScheduler: Runs periodic tasks (e.g., email fetch scheduling)
        """
        global worker_pool

        # Load configuration
        config = load_config()

        # Start worker pool for job processing
        logger.info("Starting worker pool for background job processing")
        worker_pool = WorkerPool(
            num_workers=config.worker_pool_size,
            idle_sleep_seconds=config.worker_idle_sleep_seconds,
            error_backoff_seconds=config.worker_error_backoff_seconds,
        )
        await worker_pool.start()

        # Start APScheduler for cron-like periodic tasks
        logger.info("Starting APScheduler for periodic tasks")

        # Email fetch scheduler - creates email_fetch jobs every 5 minutes
        scheduler.add_job(
            schedule_email_fetches,
            "interval",
            minutes=5,
            id="email_fetch_scheduler",
            name="Email Fetch Scheduler",
            max_instances=1,
        )

        scheduler.start()
        logger.info("Background workers started successfully")

    # Shutdown event: Clean shutdown of worker pool and scheduler
    @app.on_event("shutdown")
    async def shutdown_background_workers():
        """Gracefully shutdown worker pool and scheduler."""
        global worker_pool

        logger.info("Shutting down background workers")

        # Stop worker pool first (workers complete current jobs)
        if worker_pool:
            await worker_pool.stop()

        # Then stop scheduler
        scheduler.shutdown(wait=True)

        logger.info("Background workers shutdown complete")

    return app


# Create the app instance
app = create_app()
