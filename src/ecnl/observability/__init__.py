"""Observability bootstrap for the ECNL MCP server.

The package provides a single entry point — :func:`tracing.setup_tracing`
— that wires the OpenTelemetry SDK from environment variables. Calling
it from :mod:`ecnl.server` is the only required integration; the
exporter, sampler, and resource attributes are all driven by config
rather than hardcoded so a deploy can repoint the trace destination
without code changes.
"""

from .tracing import setup_tracing

__all__ = ["setup_tracing"]
