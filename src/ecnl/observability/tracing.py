"""OpenTelemetry SDK bootstrap for the ECNL MCP server.

Mirrors the auth-server / login-ui pattern from identity-platform-go.
``setup_tracing`` is the single entry point — called once at startup
from :mod:`ecnl.server` before any tool dispatch — and is intentionally
a no-op when ``MCP_TRACING_ENABLED`` is unset or false. That keeps the
SDK out of the import graph for the stdio transport's tight-loop tests
and lets a single env-var flip turn observability on at deploy time
without code changes.

Two instrumentations are wired automatically on bootstrap:

* ``HTTPXClientInstrumentor`` — every ``httpx.AsyncClient`` emits a
  client span per request and injects the W3C ``traceparent`` header.
  The AthleteOne and discovery outbound adapters all use httpx, so this
  closes the outbound half of the trace chain in one call.
* ``StarletteInstrumentor`` — the ``streamable-http`` MCP transport
  uses Starlette under the hood. Wiring it here means every inbound
  tool call becomes a server span and the W3C ``traceparent`` from
  the upstream caller (Claude → MCP gateway → here) is honoured.

The stdio transport does not run an HTTP server, so the Starlette
instrumentation is a no-op there. The httpx instrumentation still
applies to outbound calls.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    """Read an env var as a boolean.

    Accepts ``1``, ``true``, ``yes``, ``on`` (case-insensitive) as true.
    Empty / unset / any other value is false. Mirrors the convention the
    Go services use so operators don't have to remember a second one.
    """
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _resolve_endpoint() -> str:
    """Return the OTLP exporter endpoint.

    Prefers ``MCP_TRACING_EXPORTER_ENDPOINT`` so the service can be
    pointed at a non-default collector without touching the standard
    ``OTEL_*`` chain; otherwise defers to ``OTEL_EXPORTER_OTLP_ENDPOINT``.
    Returns the empty string when nothing is configured — the caller
    then falls back to the stdout exporter so spans are still visible
    during local development.
    """
    return os.environ.get("MCP_TRACING_EXPORTER_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")


def setup_tracing(service_name: str) -> Callable[[], None]:
    """Bootstrap the global ``TracerProvider``.

    Idempotent and safe to call from any process; the SDK's own
    ``set_tracer_provider`` rejects a second registration so a duplicate
    call is logged and ignored.

    Args:
        service_name: Recorded as the ``service.name`` resource
            attribute on every emitted span. Conventionally the MCP
            server's package name (``jk-mcp-nwsl``).

    Returns:
        A no-arg callable that flushes buffered spans and shuts the
        SDK down. Wire it into the process's graceful-shutdown path so
        spans aren't dropped on SIGTERM.
    """
    if not _env_flag("MCP_TRACING_ENABLED"):
        logger.debug("MCP_TRACING_ENABLED unset — tracing remains disabled")
        return _noop_shutdown

    # Imports are local so a deployment that never enables tracing does
    # not pay the import cost. The opentelemetry-* packages pull in a
    # non-trivial dependency graph and slow cold-start measurably when
    # imported unconditionally.
    from opentelemetry import trace
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(_resource_attrs(service_name))
    provider = TracerProvider(resource=resource, sampler=_sampler())
    provider.add_span_processor(BatchSpanProcessor(_build_exporter()))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    _instrument_starlette_if_available()

    logger.info(
        "opentelemetry tracing enabled",
        extra={
            "service_name": service_name,
            "exporter_endpoint": _resolve_endpoint() or "stdout",
        },
    )
    return provider.shutdown


def _build_exporter():
    """Construct the configured OTLP exporter or fall back to stdout.

    Endpoint resolution mirrors the Go ``go-platform/otel`` package: an
    operator-set ``MCP_TRACING_EXPORTER_ENDPOINT`` wins, then the
    standard ``OTEL_EXPORTER_OTLP_ENDPOINT``, then stdout. The protocol
    is gRPC by default — set ``MCP_TRACING_EXPORTER_PROTOCOL=http`` to
    use the HTTP exporter instead, mirroring the Go side's switch.
    """
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    endpoint = _resolve_endpoint()
    if not endpoint:
        return ConsoleSpanExporter()

    protocol = os.environ.get("MCP_TRACING_EXPORTER_PROTOCOL", "grpc").lower()
    if protocol == "http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=endpoint)
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    insecure = _env_flag("MCP_TRACING_EXPORTER_INSECURE")
    return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)


def _resource_attrs(service_name: str) -> dict[str, str]:
    """Build the resource attribute set.

    ``service.name`` is always set; ``service.version`` and
    ``deployment.environment.name`` come in from env when present.
    Empty values are dropped so the SDK does not emit blank attrs.
    """
    attrs: dict[str, str] = {"service.name": service_name}
    version = os.environ.get("MCP_TRACING_SERVICE_VERSION") or os.environ.get("OTEL_SERVICE_VERSION", "")
    if version:
        attrs["service.version"] = version
    environment = os.environ.get("MCP_TRACING_ENVIRONMENT") or os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT_NAME", "")
    if environment:
        attrs["deployment.environment.name"] = environment
    return attrs


def _sampler():
    """Return the head-based parent-based + ratio sampler.

    ``MCP_TRACING_SAMPLER_RATIO`` accepts a float in [0, 1]. Zero or
    unset defaults to 1.0 — sampling everything is the right default
    for a deployment that has tracing explicitly turned on; an
    operator who needs fewer spans can dial it down without touching
    code.
    """
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    raw = os.environ.get("MCP_TRACING_SAMPLER_RATIO", "").strip()
    try:
        ratio = float(raw) if raw else 1.0
    except ValueError:
        logger.warning("MCP_TRACING_SAMPLER_RATIO=%r is not a number; falling back to 1.0", raw)
        ratio = 1.0
    return ParentBased(root=TraceIdRatioBased(min(max(ratio, 0.0), 1.0)))


def _instrument_starlette_if_available() -> None:
    """Wire Starlette instrumentation if the package is installed.

    FastMCP's ``streamable-http`` transport runs on Starlette, so this
    is the inbound-span source for the HTTP path. ``stdio`` deployments
    don't need it and shouldn't pay the import cost when the package
    isn't installed — the import is wrapped in a try/except so a
    minimal deployment that never serves HTTP can omit the
    ``starlette`` extra without breaking startup.
    """
    try:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
    except ImportError:
        logger.debug("opentelemetry-instrumentation-starlette not installed; skipping inbound instrumentation")
        return
    # StarletteInstrumentor patches the Starlette class itself, so any
    # Starlette app constructed after this call — including FastMCP's
    # internal one — gets instrumented automatically.
    StarletteInstrumentor().instrument()


def _noop_shutdown() -> None:
    """No-op shutdown for the disabled-tracing path."""
    return None
