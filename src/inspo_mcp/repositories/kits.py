"""SQLite persistence for completed reusable inspiration kits."""

from __future__ import annotations

from inspo_mcp.schemas import InspirationKit
from inspo_mcp.storage.database import SqliteDatabase


class KitNotFoundError(LookupError):
    """Raised when M6 has not yet stored a kit for a run."""


class KitRepository:
    """Store the latest durable M6 result for each inspiration run."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kits (
                    run_id TEXT PRIMARY KEY,
                    kit_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL
                )
                """
            )

    def upsert(self, kit: InspirationKit) -> InspirationKit:
        """Persist an M6 kit without duplicating its individual artifact fields."""

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO kits (run_id, kit_json, generated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    kit_json = excluded.kit_json,
                    generated_at = excluded.generated_at
                """,
                (kit.run_id, kit.model_dump_json(), _now()),
            )
        return kit

    def get(self, run_id: str) -> InspirationKit:
        """Load the durable M6 result or report that synthesis has not happened."""

        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT kit_json FROM kits WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KitNotFoundError(f"Reusable kit not found for run: {run_id}")
        return InspirationKit.model_validate_json(row["kit_json"])

    def get_optional(self, run_id: str) -> InspirationKit | None:
        """Return a stored kit when it exists, otherwise ``None``."""

        try:
            return self.get(run_id)
        except KitNotFoundError:
            return None


def _now() -> str:
    """Reuse the run timestamp format without introducing a database dependency."""

    from inspo_mcp.models.run import utc_now

    return utc_now()
