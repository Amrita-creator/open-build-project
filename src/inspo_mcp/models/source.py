"""Persistent metadata for a captured inspiration source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SourceStatus(str, Enum):
    """Capture outcome for one user-supplied source URL."""

    CAPTURED = "captured"
    USER_PROVIDED = "user_provided"
    FAILED = "failed"


def utc_now() -> str:
    """Return a timezone-aware timestamp that SQLite can store as text."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceRecord:
    """Captured page evidence and metadata associated with one run."""

    run_id: str
    source_url: str
    final_url: str | None
    status: SourceStatus
    http_status: int | None
    title: str | None
    visible_text_path: str | None
    screenshot_path: str | None
    content_hash: str | None
    redirect_chain: tuple[str, ...]
    captured_at: str
    error_message: str | None = None
    capture_note: str | None = None
