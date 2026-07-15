"""Persistent state for one inspiration-kit request."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from inspo_mcp.schemas import Framework, InspirationRequest


class RunStatus(str, Enum):
    """The lifecycle of a kit-generation run."""

    RECEIVED = "received"
    VALIDATING = "validating"
    CAPTURING = "capturing"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


def utc_now() -> str:
    """Return a timezone-aware timestamp that SQLite can store as text."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunRecord:
    """The durable request and lifecycle metadata for one MCP tool call."""

    run_id: str
    status: RunStatus
    inspiration_urls: tuple[str, ...]
    project_goal: str
    framework: Framework
    created_at: str
    updated_at: str
    error_message: str | None = None

    @classmethod
    def new(cls, request: InspirationRequest) -> "RunRecord":
        """Create the initial record for the current mock-backed implementation."""

        now = utc_now()
        return cls(
            run_id=f"mock_{uuid4().hex[:12]}",
            status=RunStatus.RECEIVED,
            inspiration_urls=tuple(str(url) for url in request.inspiration_urls),
            project_goal=request.project_goal,
            framework=request.framework,
            created_at=now,
            updated_at=now,
        )

    def with_status(
        self,
        status: RunStatus,
        *,
        error_message: str | None = None,
    ) -> "RunRecord":
        """Return an updated immutable record for the next pipeline stage."""

        return replace(
            self,
            status=status,
            updated_at=utc_now(),
            error_message=error_message,
        )
