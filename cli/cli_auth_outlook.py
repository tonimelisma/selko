#!/usr/bin/env python3
"""Authenticate a test user with Microsoft Graph and save Outlook tokens."""

import argparse
import logging
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from selko.config import add_logging_arguments, load_config
from selko.logging import setup_logging
from selko.services.auth import (
    AuthenticationError,
    get_authenticated_client,
    get_current_user_id,
)
from selko.services.integrations import (
    IntegrationError,
    complete_oauth_flow,
    initiate_oauth_flow,
    save_provider_tokens,
)
from selko.services.outlook import OutlookError, get_user_profile

logger = logging.getLogger(__name__)

REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8080
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}"


class _OAuthHandler(BaseHTTPRequestHandler):
    """Capture one authorization callback without logging credentials."""

    callback: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlparse(self.path).query)
        for key in ("code", "state", "error", "error_description"):
            if query.get(key):
                self.callback[key] = query[key][0]
        body = b"Microsoft sign-in complete. You can close this window."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def _capture_callback(auth_url: str) -> dict[str, str]:
    _OAuthHandler.callback = {}
    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _OAuthHandler)
    try:
        logger.info("Opening browser for Microsoft sign-in...")
        if not webbrowser.open(auth_url):
            logger.info("Open this URL in a browser:\n%s", auth_url)
        server.handle_request()
        return dict(_OAuthHandler.callback)
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Authenticate with Outlook and store Microsoft Graph tokens",
        epilog=(
            "Requires TEST_USER_EMAIL/TEST_USER_PASSWORD and "
            "MICROSOFT_CLIENT_ID/MICROSOFT_CLIENT_SECRET in the selected environment."
        ),
    )
    add_logging_arguments(parser)
    args = parser.parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    config = load_config()

    try:
        client = get_authenticated_client(config)
        user_id = get_current_user_id(client)
        oauth = initiate_oauth_flow(
            config=config,
            provider="outlook",
            user_id=user_id,
            redirect_uri=REDIRECT_URI,
        )
        callback = _capture_callback(oauth["auth_url"])
        if callback.get("error"):
            raise OutlookError(callback.get("error_description") or callback["error"])
        if not callback.get("code") or callback.get("state") != oauth["state"]:
            raise OutlookError("Microsoft OAuth callback did not contain the expected code/state")

        token_result, callback_user_id, provider = complete_oauth_flow(
            config=config,
            code=callback["code"],
            state=callback["state"],
        )
        if provider != "outlook" or not isinstance(token_result, dict):
            raise OutlookError("Unexpected provider returned from Microsoft OAuth")

        profile = get_user_profile(token_result["access_token"])
        provider_email = profile.get("mail") or profile.get("userPrincipalName")
        save_provider_tokens(
            client,
            callback_user_id,
            provider,
            token_result,
            provider_email,
        )
        logger.info("Outlook integration saved successfully")
        if provider_email:
            logger.info("Connected account: %s", provider_email)
    except (AuthenticationError, IntegrationError, OutlookError) as exc:
        logger.error("Outlook OAuth failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
