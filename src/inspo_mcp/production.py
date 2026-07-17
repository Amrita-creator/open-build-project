"""ASGI production entry point: authenticated, observable HTTP MCP service."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from inspo_mcp.config import RuntimeSettings
from inspo_mcp.observability.logging import configure_logging
from inspo_mcp.observability.middleware import BearerTokenMiddleware, RequestTraceMiddleware
from inspo_mcp.observability.telemetry import configure_telemetry
from inspo_mcp.storage.database import SqliteDatabase


async def healthz(_: Any) -> JSONResponse:
    """Return liveness without revealing configuration or protected data."""

    return JSONResponse({"status": "ok"})


def readiness_handler(settings: RuntimeSettings):
    """Build a readiness endpoint that verifies the configured persistent database."""

    async def readyz(_: Any) -> JSONResponse:
        try:
            with SqliteDatabase(settings.database_path).connection() as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return JSONResponse({"status": "ready", "service": settings.service_name})

    return readyz


def create_production_app(
    settings: RuntimeSettings,
    mcp_instance: FastMCP | None = None,
) -> ASGIApp:
    """Create a stateless HTTP MCP app with probes, auth, CORS, and tracing."""

    if mcp_instance is None:
        from inspo_mcp.server import mcp as configured_mcp

        mcp_instance = configured_mcp
    mcp_app = mcp_instance.http_app(path=settings.mcp_path, stateless_http=True)
    base_app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readiness_handler(settings), methods=["GET"]),
            Mount("", app=mcp_app),
        ],
        lifespan=mcp_app.lifespan,
    )
    protected_app: ASGIApp = BearerTokenMiddleware(base_app, settings)
    if settings.cors_origins:
        protected_app = CORSMiddleware(
            protected_app,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "mcp-protocol-version",
                "mcp-session-id",
            ],
            expose_headers=["mcp-session-id", "x-request-id"],
        )
    return RequestTraceMiddleware(protected_app, settings)


settings = RuntimeSettings.from_environment()
configure_logging(settings)
configure_telemetry(settings)
app = create_production_app(settings)
