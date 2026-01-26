"""FastAPI application factory."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from selko.api.routes import (
    calendars_router,
    emails_router,
    events_router,
    health_router,
    integrations_router,
    sender_rules_router,
)
from selko.services.auth import AuthenticationError
from selko.services.calendars import CalendarsError
from selko.services.emails import EmailError
from selko.services.events import EventsError
from selko.services.integrations import IntegrationError

logger = logging.getLogger(__name__)


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

    return app


# Create the app instance
app = create_app()
