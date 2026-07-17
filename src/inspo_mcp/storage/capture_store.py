"""Filesystem storage for sanitized capture artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from inspo_mcp.models.source import SemanticBlock


class LocalCaptureStore:
    """Save sanitized evidence under a deterministic per-run directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save_visible_text(self, run_id: str, source_url: str, text: str) -> Path:
        """Write sanitized visible page text and return its path."""

        path = self._artifact_path(run_id, source_url, suffix=".txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save_semantic_document(
        self,
        run_id: str,
        source_url: str,
        blocks: tuple[SemanticBlock, ...],
    ) -> Path:
        """Write semantic, text-only HTML evidence next to the visible-text file."""

        path = self._artifact_path(run_id, source_url, suffix=".semantic.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"version": 1, "blocks": [block.to_dict() for block in blocks]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        return path

    def screenshot_path(self, run_id: str, source_url: str) -> Path:
        """Return the reserved output path for a source screenshot."""

        path = self._artifact_path(run_id, source_url, suffix=".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_user_screenshot(
        self,
        run_id: str,
        source_url: str,
        supplied_path: str,
        *,
        max_bytes: int,
    ) -> Path:
        """Validate and copy a user-supplied image into the managed evidence store."""

        source = Path(supplied_path).expanduser()
        if not source.is_file():
            raise ValueError(f"User screenshot file does not exist: {supplied_path}")
        if source.stat().st_size == 0:
            raise ValueError("User screenshot file is empty.")
        if source.stat().st_size > max_bytes:
            raise ValueError(f"User screenshot exceeds the {max_bytes}-byte size limit.")

        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("User screenshot must be a PNG, JPEG, or WebP image.")
        with source.open("rb") as image:
            header = image.read(12)
        if not _is_supported_image(header):
            raise ValueError("User screenshot contents do not match its image format.")

        destination = self._artifact_path(run_id, source_url, suffix=suffix)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    def delete_run(self, run_id: str) -> None:
        """Delete one managed evidence directory without following user input outside root."""

        root = self.root.resolve()
        target = (self.root / run_id).resolve()
        if target.parent != root:
            raise ValueError("Refusing to delete a capture path outside the managed root.")
        if target.exists():
            shutil.rmtree(target)

    @staticmethod
    def has_complete_evidence(
        visible_text_path: str | None,
        screenshot_path: str | None,
        semantic_document_path: str | None,
    ) -> bool:
        """Return whether all M3/M4 artifacts for a captured source remain."""

        return bool(
            visible_text_path
            and screenshot_path
            and semantic_document_path
            and Path(visible_text_path).is_file()
            and Path(screenshot_path).is_file()
            and Path(semantic_document_path).is_file()
        )

    @staticmethod
    def has_screenshot(screenshot_path: str | None) -> bool:
        """Return whether a user-supplied fallback image remains available."""

        return bool(screenshot_path and Path(screenshot_path).is_file())

    def _artifact_path(self, run_id: str, source_url: str, *, suffix: str) -> Path:
        source_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
        return self.root / run_id / f"{source_id}{suffix}"


def _is_supported_image(header: bytes) -> bool:
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or (len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP")
    )
