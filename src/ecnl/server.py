"""Entry point for the ECNL MCP server.

Wires together the outbound adapter (AthleteOne HTTP), discovery, the
application service, and the inbound MCP adapter. The dependency graph flows
inward — adapters depend on ports, ports depend on domain models.

Transport: controlled by the MCP_TRANSPORT environment variable.
- "stdio" (default): JSON-RPC over stdin/stdout — client spawns the server as a
  subprocess. Never write to stdout in this mode; it corrupts the message stream.
- "streamable-http": HTTP server on HOST:PORT.

AthleteOne API host: controlled by API_HOST (default: https://api.athleteone.com).

Structured logging: all records are emitted as JSON to stderr (captured as
container logs). Level via LOG_LEVEL (default: INFO).
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .adapters.inbound.mcp_adapter import create_mcp_server
from .adapters.outbound.athleteone_adapter import AthleteOneAdapter
from .adapters.outbound.caching_adapter import CachingAdapter
from .adapters.outbound.discovery import DiscoveryAdapter
from .adapters.outbound.retry_adapter import RetryingAdapter
from .application.service import ECNLService


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _configure_logging() -> None:
    """Configure the root logger to emit JSON records to stderr (LOG_LEVEL, default INFO)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logging.root.setLevel(level)
    logging.root.addHandler(handler)


load_dotenv()
_configure_logging()

logger = logging.getLogger(__name__)

_VALID_TRANSPORTS = ("stdio", "streamable-http")


def build_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    api_host: str = "https://api.athleteone.com",
    path: str = "/mcp",
) -> FastMCP:
    """Wire AthleteOneAdapter → retry → cache → ECNLService → FastMCP.

    Discovery shares the cached adapter, so org/event lookups are cached and
    retried just like direct data calls.

    Args:
        host: Bind address for HTTP transport (ignored for stdio).
        port: TCP port for HTTP transport (ignored for stdio).
        api_host: Base URL of the upstream AthleteOne API.
        path: URL path for the streamable-http transport (ignored for stdio).
    """
    adapter = AthleteOneAdapter(base_url=api_host)
    # Compose cross-cutting adapters: HTTP → retry on transient errors → cache results.
    repo = CachingAdapter(RetryingAdapter(adapter))
    discovery = DiscoveryAdapter(repo)

    service = ECNLService(repo=repo, discovery=discovery)
    return create_mcp_server(service, host=host, port=port, path=path)


def main() -> None:
    """Start the ECNL MCP server.

    Reads configuration from the environment:
      API_HOST       — base URL of the AthleteOne API (default: https://api.athleteone.com)
      MCP_TRANSPORT  — "stdio" (default) or "streamable-http"
      HOST           — bind address for HTTP transport (default: 0.0.0.0)
      PORT           — TCP port for HTTP transport (default: 8000)
      MCP_PATH       — URL path for streamable-http transport (default: /mcp/ecnl)
    """
    api_host = os.environ.get("API_HOST", "https://api.athleteone.com")
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    path = os.environ.get("MCP_PATH", "/mcp/ecnl")

    if transport not in _VALID_TRANSPORTS:
        raise ValueError(f"Invalid MCP_TRANSPORT={transport!r}. Must be one of: {', '.join(_VALID_TRANSPORTS)}")

    if transport == "streamable-http":
        logger.info("Starting ECNL MCP server (streamable-http transport, %s:%s, path=%s)", host, port, path)
        build_server(host=host, port=port, api_host=api_host, path=path).run(transport="streamable-http")
    else:
        logger.info("Starting ECNL MCP server (stdio transport)")
        build_server(api_host=api_host).run(transport="stdio")


if __name__ == "__main__":
    main()
