"""JSON logging that preserves request trace identifiers without request payloads."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from inspo_mcp.config import RuntimeSettings
from inspo_mcp.observability.context import current_trace_id


class JsonLogFormatter(logging.Formatter):
    """Emit compact structured logs suitable for a container log collector."""

    def __init__(self, settings: RuntimeSettings) -> None:
        super().__init__()
        self._settings = settings

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._settings.service_name,
            "environment": self._settings.environment,
            "trace_id": current_trace_id(),
        }
        for name in ("event", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(settings: RuntimeSettings) -> None:
    """Add one stderr JSON handler without disrupting an embedding host's handlers."""

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    if any(getattr(handler, "_inspo_mcp_handler", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler._inspo_mcp_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonLogFormatter(settings))
    root.addHandler(handler)
