"""Sign-up, sign-in, token refresh, sign-out (03-api-auth-web.md §B.9, E20-E23).

The access token travels as a Bearer header; the refresh token only in the
``selko_refresh`` cookie (HttpOnly, SameSite=Strict, Path=/auth), so data
endpoints never see a cookie and need no CSRF protection. The endpoints that
read or set the cookie require an allowed ``Origin`` and a JSON body.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from selko.api.limits import TOKEN_ROUTE_LIMIT, client_ip, limiter, password_attempts
from selko.services import accounts
from selko.services.accounts import AuthError, Identity

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "selko_refresh"
REFRESH_COOKIE_MAX_AGE = 30 * 86400


def get_db(request: Request):
    return request.app.state.db


def get_token_keys(request: Request) -> accounts.TokenKeys:
    return request.app.state.token_keys


def require_identity(request: Request, keys=Depends(get_token_keys)) -> Identity:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        return accounts.verify_access_token(keys, header[7:])
    except AuthError as exc:
        raise HTTPException(exc.status, exc.message, headers={"WWW-Authenticate": "Bearer"}) from exc


def _require_same_origin(request: Request) -> None:
    """Cookie endpoints: an allowed Origin and a JSON body (forces a CORS preflight)."""
    allowed = getattr(request.app.state, "allowed_origins", []) or []
    if request.headers.get("origin") not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Expected application/json")


def _secure_cookies(request: Request) -> bool:
    return getattr(request.app.state, "environment", "production") != "development"


def _set_refresh_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=REFRESH_COOKIE_MAX_AGE, path="/auth",
        httponly=True, samesite="strict", secure=_secure_cookies(request),
    )


def _clear_refresh_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/auth", httponly=True, samesite="strict", secure=_secure_cookies(request))


def _error(exc: AuthError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


def _token_body(signed: accounts.SignedIn) -> dict[str, Any]:
    return {"access_token": signed.access_token, "token_type": "bearer",
            "expires_in": accounts.ACCESS_TOKEN_SECONDS, "expires_at": signed.expires_at, "user": signed.user}


class SignUpBody(BaseModel):
    email: str
    password: str


class TokenBody(BaseModel):
    grant_type: Literal["password", "refresh_token"]
    email: str | None = None
    password: str | None = None


class LogoutBody(BaseModel):
    scope: Literal["local", "global"] = "global"


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour", key_func=client_ip)
async def sign_up(request: Request, body: SignUpBody, db=Depends(get_db)) -> dict[str, Any]:
    _require_same_origin(request)
    try:
        user = await db.run(accounts.sign_up, db, body.email, body.password)
    except AuthError as exc:
        raise _error(exc) from exc
    return {"user": user, "confirmation_required": False}


@router.post("/token")
@limiter.limit(TOKEN_ROUTE_LIMIT, key_func=client_ip)
async def token(request: Request, response: Response, body: TokenBody, db=Depends(get_db), keys=Depends(get_token_keys)) -> dict[str, Any]:
    _require_same_origin(request)
    try:
        if body.grant_type == "password":
            if not password_attempts.hit(client_ip(request)):
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                    {"code": "RATE_LIMITED", "message": "Too many sign-in attempts. Try again in a minute."})
            signed = await db.run(
                accounts.sign_in, db, keys, body.email or "", body.password or "",
                request.headers.get("user-agent"),
            )
        else:
            signed = await db.run(accounts.refresh, db, keys, request.cookies.get(REFRESH_COOKIE))
    except AuthError as exc:
        if body.grant_type == "refresh_token":
            error = _error(exc)
            # Clear the dead cookie along with the refusal.
            cleared = Response()
            _clear_refresh_cookie(request, cleared)
            error.headers = {"set-cookie": cleared.headers["set-cookie"]}
            raise error from exc
        raise _error(exc) from exc
    if signed.refresh_token is not None:
        _set_refresh_cookie(request, response, signed.refresh_token)
    return _token_body(signed)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, body: LogoutBody | None = None, db=Depends(get_db), keys=Depends(get_token_keys)) -> Response:
    _require_same_origin(request)
    scope = (body or LogoutBody()).scope
    account_id = session_id = None
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        try:
            identity = accounts.verify_access_token(keys, header[7:])
            account_id, session_id = identity.user_id, identity.session_id
        except AuthError:
            pass
    if account_id is None and (cookie := request.cookies.get(REFRESH_COOKIE)):
        from selko.db import accounts as account_rows

        session = await db.run(account_rows.session_for_refresh_token, db, accounts.hash_refresh_token(cookie))
        if session is not None:
            account_id, session_id = session["user_id"], session["id"]
    if account_id is not None:
        await db.run(accounts.sign_out, db, account_id, session_id, scope)
        bus = getattr(request.app.state, "bus", None)
        if bus is not None:
            bus.publish(f"user:{account_id}", {"resource": "session", "operation": "REVOKED",
                                              "session_id": session_id if scope == "local" else None})
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(request, response)
    return response


@router.get("/user")
async def current_user(identity: Identity = Depends(require_identity), db=Depends(get_db)) -> dict[str, Any]:
    from selko.db import accounts as account_rows

    account = await db.run(account_rows.get_account, db, identity.user_id)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return {"id": account["id"], "email": account["email"], "created_at": account["created_at"],
            "last_sign_in_at": account["last_sign_in_at"]}
