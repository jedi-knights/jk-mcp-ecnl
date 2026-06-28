"""Inbound adapter — exposes the application service as MCP tools.

Composition root for the MCP layer:
- Creates the FastMCP server instance
- Registers liveness/readiness/health endpoints
- Delegates per-domain tool registration to the modules in ``tools/``

FastMCP generates tool schemas from Python type hints and docstrings, so the
docstrings on each registered tool are the LLM's primary guide.

Logging note (STDIO transport): NEVER use print() here. It writes to stdout
and corrupts the JSON-RPC stream.
"""

import logging

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from ...application.service import ECNLService
from ...ports.inbound import Authorizer
from .authorization import PassThroughAuthorizer
from .tools._base import _safe_call as _safe_call_internal
from .tools.analytics import register_analytics_tools
from .tools.events import register_event_tools
from .tools.matches import register_match_tools
from .tools.schedule import register_schedule_tools
from .tools.standings import register_standings_tools
from .tools.teams import register_team_tools

logger = logging.getLogger(__name__)

# Re-exported for tests that import `_safe_call` from this module.
_safe_call = _safe_call_internal


async def _handle_livez(request: Request) -> JSONResponse:
    """Liveness probe — returns 200 OK if the HTTP server is up."""
    return JSONResponse({"status": "ok"})


async def _handle_readyz(request: Request) -> JSONResponse:
    """Readiness probe — returns 200 when the server is ready to serve traffic."""
    return JSONResponse({"status": "ok"})


async def _handle_health(request: Request) -> JSONResponse:
    """Aggregate health endpoint for monitoring systems."""
    return JSONResponse({"status": "ok", "checks": {"liveness": "ok", "readiness": "ok"}})


def create_mcp_server(
    service: ECNLService,
    host: str = "0.0.0.0",
    port: int = 8000,
    path: str = "/mcp",
    auth_settings=None,
    token_verifier=None,
    authorizer: Authorizer | None = None,
) -> FastMCP:
    """Wire the application service into a FastMCP instance and register tools.

    Args:
        service: The ECNLService to expose as MCP tools.
        host: Bind address for HTTP transport (ignored for stdio). Defaults to 0.0.0.0.
        port: TCP port for HTTP transport (ignored for stdio). Defaults to 8000.
        path: URL path the streamable-http transport is served at (ignored for
            stdio). Each MCP server uses a distinct path (e.g. ``/mcp/ecnl``).
        auth_settings: Optional ``mcp.server.auth.settings.AuthSettings`` that
            enables bearer-token enforcement on the streamable-http transport.
        token_verifier: Optional ``TokenVerifier`` consulted on every request.
    """
    mcp = FastMCP(
        "ecnl",
        host=host,
        port=port,
        stateless_http=True,
        streamable_http_path=path,
        auth=auth_settings,
        token_verifier=token_verifier,
    )

    mcp.custom_route("/livez", methods=["GET"])(_handle_livez)
    mcp.custom_route("/readyz", methods=["GET"])(_handle_readyz)
    mcp.custom_route("/health", methods=["GET"])(_handle_health)

    authz = authorizer or PassThroughAuthorizer()
    register_event_tools(mcp, service, authz)
    register_standings_tools(mcp, service, authz)
    register_schedule_tools(mcp, service, authz)
    register_team_tools(mcp, service, authz)
    register_match_tools(mcp, service, authz)
    register_analytics_tools(mcp, service, authz)

    return mcp
