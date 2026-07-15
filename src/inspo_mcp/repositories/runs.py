"""SQLite persistence for inspiration-kit run records."""

from __future__ import annotations

import json
import sqlite3

from inspo_mcp.models.run import RunRecord, RunStatus
from inspo_mcp.storage.database import SqliteDatabase


class RunNotFoundError(LookupError):
    """Raised when a requested run ID does not exist."""


class RunRepository:
    """Persist and retrieve the lifecycle state for MCP tool calls."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    inspiration_urls TEXT NOT NULL,
                    project_goal TEXT NOT NULL,
                    framework TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT
                )
                """
            )

    def create(self, run: RunRecord) -> RunRecord:
        """Save a newly received run."""

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, status, inspiration_urls, project_goal, framework,
                    created_at, updated_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.status.value,
                    json.dumps(run.inspiration_urls),
                    run.project_goal,
                    run.framework,
                    run.created_at,
                    run.updated_at,
                    run.error_message,
                ),
            )
        return run

    def get(self, run_id: str) -> RunRecord:
        """Load one run or raise a domain-specific not-found error."""

        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()

        if row is None:
            raise RunNotFoundError(f"Run not found: {run_id}")
        return self._to_record(row)

    def update(self, run: RunRecord) -> RunRecord:
        """Persist a lifecycle transition for an existing run."""

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = ?, updated_at = ?, error_message = ?
                WHERE run_id = ?
                """,
                (
                    run.status.value,
                    run.updated_at,
                    run.error_message,
                    run.run_id,
                ),
            )

        if cursor.rowcount != 1:
            raise RunNotFoundError(f"Run not found: {run.run_id}")
        return run

    @staticmethod
    def _to_record(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            status=RunStatus(row["status"]),
            inspiration_urls=tuple(json.loads(row["inspiration_urls"])),
            project_goal=row["project_goal"],
            framework=row["framework"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error_message=row["error_message"],
        )

