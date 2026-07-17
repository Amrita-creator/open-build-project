"""Persistent metadata for a captured inspiration source."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SourceStatus(str, Enum):
    """Capture outcome for one user-supplied source URL."""

    CAPTURED = "captured"
    USER_PROVIDED = "user_provided"
    FAILED = "failed"


@dataclass(frozen=True)
class SemanticBlock:
    """A bounded, text-only record of a meaningful HTML element.

    The block deliberately stores no attributes, links, or executable HTML.  Its
    tag/ancestry information lets later extraction distinguish page content from
    navigation and footer chrome.
    """

    kind: str
    tag: str
    text: str
    ancestry: tuple[str, ...]
    heading_level: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation for the capture sidecar file."""

        return {
            "kind": self.kind,
            "tag": self.tag,
            "text": self.text,
            "ancestry": list(self.ancestry),
            "heading_level": self.heading_level,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SemanticBlock":
        """Parse one untrusted sidecar entry without retaining arbitrary fields."""

        if not isinstance(value, dict):
            raise ValueError("Semantic block must be an object.")
        ancestry = value.get("ancestry", [])
        if not isinstance(ancestry, list) or not all(isinstance(tag, str) for tag in ancestry):
            raise ValueError("Semantic block ancestry must be a list of tags.")
        heading_level = value.get("heading_level")
        if heading_level is not None and (
            not isinstance(heading_level, int) or not 1 <= heading_level <= 6
        ):
            raise ValueError("Semantic block heading level must be between 1 and 6.")
        kind = value.get("kind")
        tag = value.get("tag")
        text = value.get("text")
        if not all(isinstance(item, str) for item in (kind, tag, text)):
            raise ValueError("Semantic block kind, tag, and text must be strings.")
        return cls(
            kind=kind,
            tag=tag,
            text=text,
            ancestry=tuple(ancestry),
            heading_level=heading_level,
        )


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
    semantic_document_path: str | None = None
    redaction_counts: dict[str, int] = field(default_factory=dict)
