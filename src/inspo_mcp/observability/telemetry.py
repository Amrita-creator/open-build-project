"""OpenTelemetry setup and safe tracing helpers for the HTTP MCP service."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from inspo_mcp.config import RuntimeSettings


logger = logging.getLogger(__name__)
_configured = False
P = ParamSpec("P")
T = TypeVar("T")


def configure_telemetry(settings: RuntimeSettings) -> bool:
    """Configure OTLP tracing when an endpoint is supplied.

    Missing configuration leaves tracing as a no-op. Export happens in a batch
    worker, so a collector outage cannot block a user request.
    """

    global _configured
    if settings.otlp_traces_endpoint is None:
        return False
    if _configured:
        return True

    resource = Resource.create(
        {
            SERVICE_NAME: settings.service_name,
            "deployment.environment.name": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_traces_endpoint))
    )
    trace.set_tracer_provider(provider)
    _configured = True
    logger.info("otel_tracing_configured", extra={"event": "otel_tracing_configured"})
    return True


def get_trace_id() -> str | None:
    """Return the active OpenTelemetry trace ID, if sampling created one."""

    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"{context.trace_id:032x}"


def traced_tool(name: str) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Add a payload-free child span around one MCP tool call."""

    def decorate(operation: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(operation)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            tracer = trace.get_tracer("inspo_mcp.mcp")
            with tracer.start_as_current_span(f"mcp.tool {name}") as span:
                span.set_attribute("rpc.system", "mcp")
                span.set_attribute("mcp.tool.name", name)
                try:
                    return await operation(*args, **kwargs)
                except Exception as error:
                    span.record_exception(error)
                    span.set_status(Status(StatusCode.ERROR, str(error)))
                    raise

        return wrapped

    return decorate
