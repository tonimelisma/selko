"""API route modules.

Server-side endpoints that require secrets (OAuth, Gmail API, LLM, Calendar API, Photos API).
For direct database queries, frontends should use Supabase client directly.
"""

from selko.api.routes.calendars import router as calendars_router
from selko.api.routes.emails import router as emails_router
from selko.api.routes.events import router as events_router
from selko.api.routes.health import router as health_router
from selko.api.routes.integrations import router as integrations_router
from selko.api.routes.photos import router as photos_router

__all__ = [
    "health_router",
    "emails_router",
    "integrations_router",
    "events_router",
    "calendars_router",
    "photos_router",
]
