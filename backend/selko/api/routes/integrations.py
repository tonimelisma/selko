"""OAuth integration endpoints.

These endpoints handle OAuth flows requiring server-side secrets.
For direct integration queries, use Supabase client from frontend.
"""

import logging
import os
import time
from collections import defaultdict
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from selko.api.deps import CurrentUser, get_config, get_current_user
from selko.api.schemas.common import ErrorCode, error_detail
from selko.config import Config
from selko.services.gmail import build_service, get_user_profile
from selko.services.outlook import (
    OutlookError,
    get_user_profile as get_outlook_user_profile,
)
from selko.services.integrations import (
    IntegrationError,
    OAuthStateError,
    complete_oauth_flow,
    initiate_oauth_flow,
    save_oauth_credentials,
    save_provider_tokens,
)

# Base allowlist for Google OAuth callback hosts (Google redirects here, not the SPA)
_STATIC_REDIRECT_HOSTS = {
    "localhost",
    "127.0.0.1",
    "api.selko.app",
    "selko-production.onrender.com",
    "selko.onrender.com",
}

ALLOWED_REDIRECT_PATHS = {
    "/integrations/google/callback",  # Unified for all Google providers
    "/integrations/microsoft/callback",
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


# --- IP-based rate limiter for OAuth callback ---

# Track request timestamps per IP: {ip: [timestamp, ...]}
_callback_request_log: dict[str, list[float]] = defaultdict(list)
_CALLBACK_RATE_LIMIT = 10  # max requests
_CALLBACK_RATE_WINDOW = 60  # per 60 seconds


def _allowed_redirect_hosts() -> set[str]:
    """Build redirect-host allowlist from static hosts + API_PUBLIC_URL."""
    hosts = set(_STATIC_REDIRECT_HOSTS)
    api_url = os.getenv("API_PUBLIC_URL", "").rstrip("/")
    if api_url:
        hostname = urlparse(api_url).hostname
        if hostname:
            hosts.add(hostname)
    return hosts


def _default_oauth_callback_uri(config: Config, provider: str = "gmail") -> str:
    """Default OAuth callback URI for the selected provider."""
    if provider == "outlook":
        return f"{config.api_public_url}/integrations/microsoft/callback"
    return f"{config.api_public_url}/integrations/google/callback"


def _check_callback_rate_limit(request: Request) -> None:
    """Check IP-based rate limit for OAuth callback endpoint.

    Args:
        request: FastAPI request object.

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()

    # Clean old entries outside the window
    timestamps = _callback_request_log[client_ip]
    _callback_request_log[client_ip] = [
        t for t in timestamps if now - t < _CALLBACK_RATE_WINDOW
    ]

    if len(_callback_request_log[client_ip]) >= _CALLBACK_RATE_LIMIT:
        logger.warning(f"OAuth callback rate limit exceeded for IP {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail(
                ErrorCode.QUOTA_EXCEEDED,
                "Too many OAuth callback requests. Please try again later.",
            ),
            headers={"Retry-After": str(_CALLBACK_RATE_WINDOW)},
        )

    _callback_request_log[client_ip].append(now)


def _validate_redirect_uri(redirect_uri: str) -> bool:
    """Validate redirect URI against allowlist to prevent open redirect attacks.

    Args:
        redirect_uri: The URI to validate.

    Returns:
        True if valid, False otherwise.
    """
    try:
        parsed = urlparse(redirect_uri)
        # Check scheme is http or https
        if parsed.scheme not in ("http", "https"):
            return False
        # Check host is in allowlist
        host = parsed.hostname
        if host not in _allowed_redirect_hosts():
            return False
        # Check path is a valid callback path
        if parsed.path not in ALLOWED_REDIRECT_PATHS:
            return False
        return True
    except Exception:
        return False


def _wants_json(accept: str | None) -> bool:
    """Return True when the client prefers a JSON auth_url response."""
    if not accept:
        return False
    return "application/json" in accept.lower()


def _oauth_initiate_response(
    *,
    config: Config,
    provider: str,
    user_id: str,
    redirect_uri: str | None,
    accept: str | None,
) -> RedirectResponse | JSONResponse:
    """Shared OAuth initiation for Gmail / Calendar / Photos."""
    resolved_uri = redirect_uri or _default_oauth_callback_uri(config, provider)

    if not _validate_redirect_uri(resolved_uri):
        logger.warning(f"Invalid redirect_uri attempted: {resolved_uri}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.INVALID_REQUEST, "Invalid redirect URI"),
        )

    try:
        result = initiate_oauth_flow(
            config=config,
            provider=provider,
            user_id=user_id,
            redirect_uri=resolved_uri,
        )
    except (IntegrationError, OutlookError) as e:
        logger.error(f"Failed to initiate OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.OAUTH_FAILED, "Failed to initiate OAuth flow"),
        ) from e

    auth_url = result["auth_url"]
    if _wants_json(accept):
        return JSONResponse({"auth_url": auth_url})
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


def _frontend_oauth_redirect(
    config: Config,
    *,
    status_value: str,
    provider: str | None = None,
    message: str | None = None,
) -> RedirectResponse:
    """Redirect the browser back to the SPA after OAuth completes."""
    params: dict[str, str] = {"oauth": status_value}
    if provider:
        params["provider"] = provider
    if message:
        params["message"] = message
    url = f"{config.frontend_url}/app?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/gmail/auth")
async def gmail_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[
        str | None, Query(description="OAuth callback URI")
    ] = None,
    accept: Annotated[str | None, Header()] = None,
) -> Any:
    """Initiate Gmail OAuth flow.

    With ``Accept: application/json``, returns ``{"auth_url": "..."}`` so
    authenticated SPA clients can fetch with a Bearer token then navigate.
    Otherwise redirects (302) to Google — useful for curl -L with auth header.
    """
    return _oauth_initiate_response(
        config=config,
        provider="gmail",
        user_id=user.id,
        redirect_uri=redirect_uri,
        accept=accept,
    )


@router.get("/outlook/auth")
async def outlook_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[
        str | None, Query(description="OAuth callback URI")
    ] = None,
    accept: Annotated[str | None, Header()] = None,
) -> Any:
    """Initiate Microsoft Graph OAuth for Outlook email access."""
    return _oauth_initiate_response(
        config=config,
        provider="outlook",
        user_id=user.id,
        redirect_uri=redirect_uri,
        accept=accept,
    )


@router.get("/google/callback")
async def google_oauth_callback(
    request: Request,
    code: Annotated[str, Query(description="Authorization code from Google")],
    state: Annotated[str, Query(description="State parameter for CSRF validation")],
    config: Config = Depends(get_config),
) -> RedirectResponse:
    """Handle Google OAuth callback (public endpoint).

    Unified callback for all Google integrations (Gmail, Calendar, etc.).
    The provider is determined from the state parameter.

    Exchanges authorization code for access and refresh tokens.
    Stores tokens in the integrations table, then redirects to the frontend.

    This endpoint is PUBLIC - no JWT authentication required.
    Security is provided by state parameter validation + IP rate limiting.
    """
    # Rate limit this endpoint to prevent abuse
    _check_callback_rate_limit(request)

    try:
        # Validate state and extract user_id FIRST
        credentials, user_id, provider = complete_oauth_flow(
            config=config,
            code=code,
            state=state,
        )

        # Create service role client (bypasses RLS for explicit user_id)
        from selko.services.auth import get_service_client
        client = get_service_client(config)

        # Get provider-specific profile info
        provider_email = None
        if provider == "gmail":
            try:
                service = build_service(credentials)
                profile = get_user_profile(service)
                provider_email = profile.get("emailAddress")
            except Exception as e:
                logger.warning(f"Could not get Gmail profile: {e}")
        # For google_calendar and google_photos, we don't fetch profile info
        # (those APIs don't have a user profile endpoint)

        # Save credentials with EXPLICIT user_id
        save_oauth_credentials(client, user_id, provider, credentials, provider_email)

        # Auto-detect timezone from Google Calendar settings
        if provider == "google_calendar":
            try:
                from googleapiclient.discovery import build as build_google_service
                cal_service = build_google_service("calendar", "v3", credentials=credentials)
                tz_setting = cal_service.settings().get(setting="timezone").execute()
                user_timezone = tz_setting.get("value")
                if user_timezone:
                    client.table("user_calendar_settings").upsert({
                        "user_id": str(user_id),
                        "timezone": user_timezone,
                    }).execute()
                    logger.info(f"Auto-detected timezone '{user_timezone}' for user {user_id}")
            except Exception as e:
                logger.warning(f"Could not auto-detect timezone for user {user_id}: {e}")

        logger.info(f"{provider} OAuth completed successfully for user {user_id}")

        return _frontend_oauth_redirect(
            config, status_value="success", provider=provider
        )

    except OAuthStateError as e:
        logger.warning(f"OAuth state validation failed: {e}")
        return _frontend_oauth_redirect(
            config,
            status_value="error",
            message="OAuth state invalid or expired. Please try again.",
        )
    except IntegrationError as e:
        logger.error(f"OAuth callback failed: {e}")
        return _frontend_oauth_redirect(
            config,
            status_value="error",
            message="OAuth callback failed",
        )


@router.get("/microsoft/callback")
async def microsoft_oauth_callback(
    request: Request,
    code: Annotated[str, Query(description="Authorization code from Microsoft")],
    state: Annotated[str, Query(description="State parameter for CSRF validation")],
    config: Config = Depends(get_config),
) -> RedirectResponse:
    """Exchange a Microsoft authorization code and store Outlook tokens."""
    _check_callback_rate_limit(request)

    try:
        token_result, user_id, provider = complete_oauth_flow(
            config=config,
            code=code,
            state=state,
        )
        if provider != "outlook" or not isinstance(token_result, dict):
            raise IntegrationError("Invalid Microsoft OAuth state")

        from selko.services.auth import get_service_client
        client = get_service_client(config)
        access_token = token_result.get("access_token")
        if not access_token:
            raise IntegrationError("Microsoft OAuth response did not include an access token")

        provider_email = None
        try:
            profile = get_outlook_user_profile(access_token)
            provider_email = profile.get("mail") or profile.get("userPrincipalName")
        except Exception as exc:
            logger.warning("Could not get Outlook profile: %s", exc)

        save_provider_tokens(
            client,
            user_id,
            provider,
            token_result,
            provider_email,
        )
        logger.info("Outlook OAuth completed successfully for user %s", user_id)
        return _frontend_oauth_redirect(
            config, status_value="success", provider=provider
        )

    except OAuthStateError as exc:
        logger.warning("Microsoft OAuth state validation failed: %s", exc)
        return _frontend_oauth_redirect(
            config,
            status_value="error",
            message="OAuth state invalid or expired. Please try again.",
        )
    except (IntegrationError, OutlookError) as exc:
        logger.error("Microsoft OAuth callback failed: %s", exc)
        return _frontend_oauth_redirect(
            config,
            status_value="error",
            message="OAuth callback failed",
        )


@router.get("/calendar/auth")
async def calendar_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[
        str | None, Query(description="OAuth callback URI")
    ] = None,
    accept: Annotated[str | None, Header()] = None,
) -> Any:
    """Initiate Google Calendar OAuth flow.

    With ``Accept: application/json``, returns ``{"auth_url": "..."}``.
    Otherwise redirects (302) to Google.
    """
    return _oauth_initiate_response(
        config=config,
        provider="google_calendar",
        user_id=user.id,
        redirect_uri=redirect_uri,
        accept=accept,
    )
