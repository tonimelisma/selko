"""API route modules."""

from selko.api.routes.emails import router as emails_router
from selko.api.routes.health import router as health_router
from selko.api.routes.integrations import router as integrations_router

__all__ = ["health_router", "emails_router", "integrations_router"]
