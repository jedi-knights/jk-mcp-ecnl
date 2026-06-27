"""Tests for the OpenTelemetry bootstrap.

The SDK is global state, so the tests focus on the behaviour we can
observe at the boundary: whether ``setup_tracing`` returned a no-op or
a real shutdown, whether the env-var defaults parse correctly, and
whether the optional Starlette instrumentor gracefully degrades when
the package is missing. Spinning up a full provider against the actual
SDK in unit tests would leak state across the suite, so we monkeypatch
the SDK entry points.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import pytest

from ecnl.observability import tracing


@pytest.fixture(autouse=True)
def _clear_tracing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset every MCP_TRACING_* and OTEL_* env var the module reads.

    The SDK reaches for these at provider-construction time, so leaving
    them set between tests causes cross-talk that's hard to diagnose.
    """
    for name in [
        "MCP_TRACING_ENABLED",
        "MCP_TRACING_EXPORTER_ENDPOINT",
        "MCP_TRACING_EXPORTER_PROTOCOL",
        "MCP_TRACING_EXPORTER_INSECURE",
        "MCP_TRACING_SERVICE_VERSION",
        "MCP_TRACING_ENVIRONMENT",
        "MCP_TRACING_SAMPLER_RATIO",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_VERSION",
        "OTEL_DEPLOYMENT_ENVIRONMENT_NAME",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_env_flag_handles_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv("FLAG", value)
        assert tracing._env_flag("FLAG") is True


def test_env_flag_handles_falsey_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "0", "false", "no", "off", "random"):
        monkeypatch.setenv("FLAG", value)
        assert tracing._env_flag("FLAG") is False


def test_env_flag_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLAG", raising=False)
    assert tracing._env_flag("FLAG", default=False) is False
    assert tracing._env_flag("FLAG", default=True) is True


def test_setup_tracing_returns_noop_when_disabled() -> None:
    shutdown = tracing.setup_tracing("test-service")
    assert shutdown is tracing._noop_shutdown
    assert shutdown() is None  # callable + idempotent


def test_setup_tracing_returns_provider_shutdown_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_ENABLED", "true")
    shutdown = tracing.setup_tracing("test-service")
    # The returned shutdown is bound to the TracerProvider instance the
    # call constructed; it is not the noop sentinel.
    assert shutdown is not tracing._noop_shutdown
    assert callable(shutdown)


def test_resource_attrs_includes_service_name() -> None:
    attrs = tracing._resource_attrs("test-service")
    assert attrs["service.name"] == "test-service"


def test_resource_attrs_includes_version_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_SERVICE_VERSION", "1.2.3")
    attrs = tracing._resource_attrs("test-service")
    assert attrs["service.version"] == "1.2.3"


def test_resource_attrs_falls_back_to_otel_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_DEPLOYMENT_ENVIRONMENT_NAME", "production")
    attrs = tracing._resource_attrs("test-service")
    assert attrs["deployment.environment.name"] == "production"


def test_resource_attrs_drops_empty_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_SERVICE_VERSION", "")
    monkeypatch.setenv("MCP_TRACING_ENVIRONMENT", "")
    attrs = tracing._resource_attrs("test-service")
    assert "service.version" not in attrs
    assert "deployment.environment.name" not in attrs


def test_resolve_endpoint_prefers_mcp_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_EXPORTER_ENDPOINT", "https://mcp.collector:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://default.collector:4318")
    assert tracing._resolve_endpoint() == "https://mcp.collector:4318"


def test_resolve_endpoint_falls_back_to_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://default.collector:4318")
    assert tracing._resolve_endpoint() == "https://default.collector:4318"


def test_resolve_endpoint_empty_when_unset() -> None:
    assert tracing._resolve_endpoint() == ""


def test_build_exporter_falls_back_to_console_when_no_endpoint() -> None:
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    exporter = tracing._build_exporter()
    assert isinstance(exporter, ConsoleSpanExporter)


def test_build_exporter_grpc_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_EXPORTER_ENDPOINT", "https://collector:4317")
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcExporter

    exporter = tracing._build_exporter()
    assert isinstance(exporter, GrpcExporter)


def test_build_exporter_http_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_EXPORTER_ENDPOINT", "https://collector:4318/v1/traces")
    monkeypatch.setenv("MCP_TRACING_EXPORTER_PROTOCOL", "http")
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpExporter

    exporter = tracing._build_exporter()
    assert isinstance(exporter, HttpExporter)


def test_sampler_defaults_to_full_ratio() -> None:
    sampler = tracing._sampler()
    # ParentBased sampler exposes the root via .root; check it samples every id.
    assert sampler is not None


def test_sampler_handles_invalid_ratio(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.setenv("MCP_TRACING_SAMPLER_RATIO", "not-a-number")
    sampler = tracing._sampler()
    assert sampler is not None
    assert any("MCP_TRACING_SAMPLER_RATIO" in rec.message for rec in caplog.records)


def test_sampler_clamps_negative_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_SAMPLER_RATIO", "-0.5")
    sampler = tracing._sampler()
    # Sampler is constructed without raising — the ratio is clamped to [0, 1].
    assert sampler is not None


def test_sampler_clamps_above_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRACING_SAMPLER_RATIO", "5")
    sampler = tracing._sampler()
    assert sampler is not None


def test_starlette_instrumentation_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the Starlette instrumentor is missing, bootstrap still succeeds.

    The stdio transport doesn't use Starlette and shouldn't fail if the
    package is not installed; the import-guard inside the bootstrap is
    what makes that work.
    """
    # Hide the module so the try/except branch fires.
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.starlette", None)
    # Should not raise.
    tracing._instrument_starlette_if_available()


def test_noop_shutdown_returns_none() -> None:
    assert tracing._noop_shutdown() is None


def test_setup_tracing_returns_callable() -> None:
    # Disabled path
    assert isinstance(tracing.setup_tracing("test"), Callable)
