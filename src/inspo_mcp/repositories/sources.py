"""SQLite persistence for captured inspiration-source metadata."""

from __future__ import annotations

import json
import sqlite3

from inspo_mcp.models.source import SourceRecord, SourceStatus
from inspo_mcp.storage.database import SqliteDatabase


class SourceRepository:
    """Persist source evidence without coupling capture logic to SQLite."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    run_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    final_url TEXT,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    title TEXT,
                    visible_text_path TEXT,
                    screenshot_path TEXT,
                    content_hash TEXT,
                    redirect_chain TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    error_message TEXT,
                    capture_note TEXT,
                    PRIMARY KEY (run_id, source_url)
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(sources)").fetchall()
            }
            if "capture_note" not in columns:
                connection.execute("ALTER TABLE sources ADD COLUMN capture_note TEXT")

    def upsert(self, source: SourceRecord) -> SourceRecord:
        """Save the latest capture outcome for a source in one run."""

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                    run_id, source_url, final_url, status, http_status, title,
                    visible_text_path, screenshot_path, content_hash,
                    redirect_chain, captured_at, error_message, capture_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_url) DO UPDATE SET
                    final_url = excluded.final_url,
                    status = excluded.status,
                    http_status = excluded.http_status,
                    title = excluded.title,
                    visible_text_path = excluded.visible_text_path,
                    screenshot_path = excluded.screenshot_path,
                    content_hash = excluded.content_hash,
                    redirect_chain = excluded.redirect_chain,
                    captured_at = excluded.captured_at,
                    error_message = excluded.error_message,
                    capture_note = excluded.capture_note
                """,
                (
                    source.run_id,
                    source.source_url,
                    source.final_url,
                    source.status.value,
                    source.http_status,
                    source.title,
                    source.visible_text_path,
                    source.screenshot_path,
                    source.content_hash,
                    json.dumps(source.redirect_chain),
                    source.captured_at,
                    source.error_message,
                    source.capture_note,
                ),
            )
        return source

    def list_for_run(self, run_id: str) -> tuple[SourceRecord, ...]:
        """Return all captured/failed sources for one kit-generation run."""

        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sources WHERE run_id = ? ORDER BY source_url", (run_id,)
            ).fetchall()
        return tuple(self._to_record(row) for row in rows)

    @staticmethod
    def _to_record(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            run_id=row["run_id"],
            source_url=row["source_url"],
            final_url=row["final_url"],
            status=SourceStatus(row["status"]),
            http_status=row["http_status"],
            title=row["title"],
            visible_text_path=row["visible_text_path"],
            screenshot_path=row["screenshot_path"],
            content_hash=row["content_hash"],
            redirect_chain=tuple(json.loads(row["redirect_chain"])),
            captured_at=row["captured_at"],
            error_message=row["error_message"],
            capture_note=row["capture_note"],
        )
