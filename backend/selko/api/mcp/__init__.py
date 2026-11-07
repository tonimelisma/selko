"""MCP endpoint at ``/mcp``: Selko for Claude and other MCP clients.

Mounted into the FastAPI app (no new service). Streamable HTTP, stateless and
JSON-only, so a request carries everything it needs and nothing is held in
process memory between calls. See ``docs/mcp.md`` for connecting Claude.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from selko.api.mcp.server import create_mcp_server, mcp_issuer_url, mcp_resource_url
from selko.config import Config

__all__ = ["create_mcp_server", "mount_mcp", "mcp_issuer_url", "mcp_resource_url"]


def _transport_security(config: Config) -> TransportSecuritySettings:
    """DNS-rebinding protection: only the public host and local hosts."""
    public_host = urlparse(config.api_public_url).netloc
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, "localhost:*", "127.0.0.1:*", "[::1]:*"],
        allowed_origins=list(config.allowed_origins),
    )


def mount_mcp(app: FastAPI, config: Config, server: MCPServer | None = None) -> MCPServer:
    """Mount the MCP app and its OAuth protected-resource metadata.

    The mounted Starlette app owns ``/mcp`` and
    ``/.well-known/oauth-protected-resource/mcp``. It is mounted at the root
    *after* every FastAPI router, so it only sees paths no route claimed.
    Its session manager must be run by the FastAPI lifespan (mounted apps'
    own lifespans never run): see ``app.state.mcp_server`` in ``app.py``.
    """
    server = server or create_mcp_server(config)
    starlette_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(config),
    )
    app.state.mcp_server = server
    app.mount("/", starlette_app)
    return server
