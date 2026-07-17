"""Validated runtime configuration for local and production deployments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


Environment = Literal["development", "test", "production"]


class ConfigurationError(ValueError):
    """Raised when an unsafe or incomplete runtime configuration is supplied."""


@dataclass(frozen=True)
class RuntimeSettings:
    """The deployment settings that must be known before serving remote MCP."""

    environment: Environment
    service_name: str
    host: str
    port: int
    mcp_path: str
    database_path: Path
    capture_root: Path
    auth_token: str | None
    log_level: str
    cors_origins: tuple[str, ...]
    otlp_traces_endpoint: str | None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "RuntimeSettings":
        """Load settings without ever logging secret values."""

        values = os.environ if environment is None else environment
        raw_environment = values.get("INSPO_MCP_ENVIRONMENT", "development").strip().lower()
        if raw_environment not in {"development", "test", "production"}:
            raise ConfigurationError(
                "INSPO_MCP_ENVIRONMENT must be development, test, or production."
            )
        runtime_environment: Environment = raw_environment  # type: ignore[assignment]
        database_value = values.get("INSPO_MCP_DATABASE_PATH")
        capture_value = values.get("INSPO_MCP_CAPTURE_ROOT")
        auth_token = _optional(values.get("INSPO_MCP_AUTH_TOKEN"))
        if runtime_environment == "production":
            if auth_token is None:
                raise ConfigurationError(
                    "INSPO_MCP_AUTH_TOKEN is required when INSPO_MCP_ENVIRONMENT=production."
                )
            if database_value is None or capture_value is None:
                raise ConfigurationError(
                    "INSPO_MCP_DATABASE_PATH and INSPO_MCP_CAPTURE_ROOT must point to persistent storage in production."
                )
        return cls(
            environment=runtime_environment,
            service_name=_optional(values.get("INSPO_MCP_SERVICE_NAME")) or "inspo-mcp",
            host=_optional(values.get("INSPO_MCP_HOST")) or "0.0.0.0",
            port=_port(values.get("PORT") or values.get("INSPO_MCP_PORT") or "8080"),
            mcp_path=_mcp_path(values.get("INSPO_MCP_HTTP_PATH", "/mcp")),
            database_path=Path(database_value or "data/inspo_mcp.db"),
            capture_root=Path(capture_value or "data/captures"),
            auth_token=auth_token,
            log_level=_log_level(values.get("INSPO_MCP_LOG_LEVEL", "INFO")),
            cors_origins=_origins(values.get("INSPO_MCP_CORS_ORIGINS", "")),
            otlp_traces_endpoint=_otlp_endpoint(
                values.get("INSPO_MCP_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
            ),
        )


def _optional(value: str | None) -> str | None:
    normalized = value.strip() if value is not None else ""
    return normalized or None


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ConfigurationError("INSPO_MCP_PORT must be an integer between 1 and 65535.") from error
    if not 1 <= port <= 65535:
        raise ConfigurationError("INSPO_MCP_PORT must be an integer between 1 and 65535.")
    return port


def _mcp_path(value: str) -> str:
    path = value.strip()
    if not path.startswith("/") or path in {"/", "/healthz", "/readyz"}:
        raise ConfigurationError("INSPO_MCP_HTTP_PATH must be a non-root path such as /mcp.")
    return path.rstrip("/")


def _log_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigurationError("INSPO_MCP_LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR.")
    return normalized


def _origins(value: str) -> tuple[str, ...]:
    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    if "*" in origins:
        raise ConfigurationError("INSPO_MCP_CORS_ORIGINS must list explicit origins; wildcards are unsafe.")
    return origins


def _otlp_endpoint(value: str) -> str | None:
    """Accept an explicit HTTP(S) OTLP traces endpoint, or disable export."""

    endpoint = _optional(value)
    if endpoint is None:
        return None
    if not endpoint.startswith(("http://", "https://")):
        raise ConfigurationError(
            "INSPO_MCP_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT must be an HTTP(S) URL."
        )
    return endpoint
