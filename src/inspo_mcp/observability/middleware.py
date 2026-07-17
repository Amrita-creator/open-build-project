"""ASGI authentication and trace middleware for remote MCP traffic."""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from opentelemetry import propagate, trace
from opentelemetry.trace import Status, StatusCode
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from inspo_mcp.config import RuntimeSettings
from inspo_mcp.observability.context import bind_trace_id
from inspo_mcp.observability.telemetry import get_trace_id


logger = logging.getLogger(__name__)
_SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})


class BearerTokenMiddleware:
    """Protect MCP routes with a configured bearer token while keeping probes public."""

    def __init__(self, app: ASGIApp, settings: RuntimeSettings) -> None:
        self.app = app
        self._token = settings.auth_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._token is None or scope["path"] in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        header_value = dict(scope.get("headers", [])).get(b"authorization", b"").decode(
            "latin-1"
        )
        if _valid_bearer_token(header_value, self._token):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "A valid bearer token is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


class RequestTraceMiddleware:
    """Create safe HTTP spans and correlate them with structured logs."""

    def __init__(self, app: ASGIApp, settings: RuntimeSettings) -> None:
        self.app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        supplied_request_id = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = (
            supplied_request_id if _SAFE_TRACE_ID.fullmatch(supplied_request_id) else uuid4().hex
        )
        started = time.perf_counter()
        status_code = 500

        async def send_with_trace(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers_out = list(message.get("headers", []))
                headers_out.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers_out}
            await send(message)

        carrier = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in headers.items()
            if key.lower() == b"traceparent"
        }
        parent_context = propagate.extract(carrier)
        tracer = trace.get_tracer("inspo_mcp.http")
        with tracer.start_as_current_span("http.server.request", context=parent_context) as span:
            span.set_attribute("http.request.method", scope["method"])
            span.set_attribute("url.path", scope["path"])
            span.set_attribute("inspo_mcp.request_id", request_id)
            trace_id = get_trace_id() or request_id
            with bind_trace_id(trace_id):
                logger.info(
                    "http_request_started",
                    extra={
                        "event": "http_request_started",
                        "method": scope["method"],
                        "path": scope["path"],
                    },
                )
                try:
                    await self.app(scope, receive, send_with_trace)
                except Exception as error:
                    span.record_exception(error)
                    span.set_status(Status(StatusCode.ERROR, str(error)))
                    logger.exception(
                        "http_request_failed",
                        extra={
                            "event": "http_request_failed",
                            "method": scope["method"],
                            "path": scope["path"],
                        },
                    )
                    raise
                finally:
                    duration_ms = round((time.perf_counter() - started) * 1000, 2)
                    span.set_attribute("http.response.status_code", status_code)
                    span.set_attribute("http.server.request.duration_ms", duration_ms)
                    if status_code >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                    logger.info(
                        "http_request_completed",
                        extra={
                            "event": "http_request_completed",
                            "method": scope["method"],
                            "path": scope["path"],
                            "status_code": status_code,
                            "duration_ms": duration_ms,
                        },
                    )


def _valid_bearer_token(header_value: str, expected_token: str) -> bool:
    """Compare the configured token without logging or timing-leaking its content."""

    scheme, separator, token = header_value.partition(" ")
    return bool(separator) and scheme.lower() == "bearer" and secrets.compare_digest(token, expected_token)
