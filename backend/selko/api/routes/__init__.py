"""API route modules."""

from selko.api.routes.calendars import router as calendars_router
from selko.api.routes.emails import router as emails_router
from selko.api.routes.events import router as events_router
from selko.api.routes.health import router as health_router
from selko.api.routes.integrations import router as integrations_router
from selko.api.routes.jobs import router as jobs_router
from selko.api.routes.sender_rules import router as sender_rules_router

__all__ = [
    "health_router",
    "emails_router",
    "integrations_router",
    "events_router",
    "calendars_router",
    "sender_rules_router",
    "jobs_router",
]
