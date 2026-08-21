"""Shared, redacted Microsoft Graph transport and failure ledger helpers."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import requests
from supabase import Client

from selko.config import Config
from selko.services.egress import GRAPH, record_egress

_TOKEN_QUERY_RE = re.compile(r"([?&](?:token|%24skiptoken|deltatoken)=[^&]+)", re.I)


class GraphRequestError(Exception):
    """A redacted Graph failure with correlation metadata."""

    def __init__(self, status_code: int | None, message: str, **metadata: Any):
        super().__init__(message)
        self.status_code = status_code
        for key, value in metadata.items():
            setattr(self, key, value)


@dataclass(frozen=True)
class GraphCallContext:
    """Durable ownership context for a Graph request and its failure ledger."""

    client: Client
    config: Config
    integration_id: str
    run_id: str | None = None


def safe_url_template(url: str) -> str:
    """Normalize an endpoint without retaining item IDs or opaque cursors."""
    value = _TOKEN_QUERY_RE.sub("", url)
    value = re.sub(r"/messages/[^/?]+", "/messages/{message-id}", value)
    value = re.sub(r"/mailFolders/[^/?]+", "/mailFolders/{folder-id}", value)
    return value.split("?", 1)[0]


def request_headers(access_token: str, prefer: str | None = None) -> tuple[dict[str, str], str]:
    client_request_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "client-request-id": client_request_id,
        "return-client-request-id": "true",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers, client_request_id


def _retry_after(response: requests.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return None


def record_graph_failure(
    client: Client | None,
    config: Config | None,
    *,
    integration_id: str | None,
    operation: str,
    url: str,
    error: BaseException,
    run_id: str | None = None,
    attempt: int = 1,
    will_retry: bool = False,
) -> None:
    """Best-effort persistence of a structured, redacted Graph failure."""
    if client is None:
        return
    payload = {
        "environment": (config.environment if config else "unknown"),
        "integration_id": integration_id,
        "graph_surface": "outlook_mail",
        "operation": operation,
        "http_method": "GET",
        "safe_url_template": safe_url_template(url),
        "http_status": getattr(error, "status_code", None),
        "graph_error_code": getattr(error, "graph_error_code", None),
        "request_id": getattr(error, "request_id", None),
        "client_request_id": getattr(error, "client_request_id", None),
        "retry_after_seconds": getattr(error, "retry_after_seconds", None),
        "failure_class": getattr(error, "failure_class", "transport"),
        "response_summary": " ".join(str(error).split())[:500],
        "run_id": run_id,
        "attempt": attempt,
        "will_retry": will_retry,
    }
    try:
        client.table("graph_api_failures").insert(payload).execute()
    except Exception:
        # Ledger writes must never block provider ingestion.
        return


def request_json(
    access_token: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    prefer: str | None = None,
    timeout: float = 30.0,
    max_attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    client: Client | None = None,
    config: Config | None = None,
    integration_id: str | None = None,
    run_id: str | None = None,
    operation: str,
) -> dict[str, Any]:
    """GET JSON, honoring Graph throttling and recording safe failures."""
    request_params = params
    for attempt in range(1, max_attempts + 1):
        headers, generated_request_id = request_headers(access_token, prefer)
        try:
            response = requests.get(url, headers=headers, params=request_params, timeout=timeout)
        except requests.RequestException as exc:
            error = GraphRequestError(None, "Microsoft Graph transport failure", failure_class="transport", client_request_id=generated_request_id, safe_url_template=safe_url_template(url))
            record_graph_failure(client, config, integration_id=integration_id, operation=operation, url=url, error=error, run_id=run_id, attempt=attempt, will_retry=attempt < max_attempts)
            if attempt < max_attempts:
                sleep(min(30.0, 2 ** (attempt - 1)))
                continue
            raise error from exc

        # Count every Graph round trip, including failures — a retry storm is
        # exactly the kind of traffic a bandwidth alert surfaces and a success
        # counter would hide. `operation` is already a bounded template.
        record_egress(
            GRAPH,
            operation,
            request_bytes=len(url),
            response_bytes=len(response.content or b""),
        )

        if response.status_code < 400:
            try:
                return response.json()
            except ValueError as exc:
                error = GraphRequestError(response.status_code, "Microsoft Graph returned invalid JSON", failure_class="server", client_request_id=generated_request_id, safe_url_template=safe_url_template(url))
                record_graph_failure(client, config, integration_id=integration_id, operation=operation, url=url, error=error, run_id=run_id, attempt=attempt)
                raise error from exc

        try:
            body = response.json()
            graph_error = body.get("error", {}) if isinstance(body, dict) else {}
            code = graph_error.get("code")
            detail = graph_error.get("message")
        except (TypeError, ValueError):
            code = None
            detail = None
        retry_after = _retry_after(response)
        failure_class = "throttle" if response.status_code == 429 else "auth" if response.status_code in (401, 403) else "cursor_reset" if response.status_code == 410 else "server" if response.status_code >= 500 else "client"
        error = GraphRequestError(
            response.status_code,
            f"Microsoft Graph returned HTTP {response.status_code}: {detail or 'request failed'}",
            graph_error_code=code,
            request_id=response.headers.get("request-id"),
            client_request_id=response.headers.get("client-request-id") or generated_request_id,
            retry_after_seconds=retry_after,
            failure_class=failure_class,
            safe_url_template=safe_url_template(url),
        )
        should_retry = response.status_code == 429 or response.status_code >= 500
        record_graph_failure(client, config, integration_id=integration_id, operation=operation, url=url, error=error, run_id=run_id, attempt=attempt, will_retry=should_retry and attempt < max_attempts)
        if should_retry and attempt < max_attempts:
            sleep(float(retry_after if retry_after is not None else min(30, 2 ** (attempt - 1))))
            continue
        raise error
    raise GraphRequestError(None, "Microsoft Graph request exhausted retries", failure_class="transport")
