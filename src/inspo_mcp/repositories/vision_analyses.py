"""SQLite persistence for M5 screenshot-vision analysis."""

from __future__ import annotations

from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis
from inspo_mcp.storage.database import SqliteDatabase


class VisionAnalysisRepository:
    """Store the latest M5 result for each source in an inspiration run."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_analyses (
                    run_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, source_url)
                )
                """
            )

    def upsert(self, analysis: ScreenshotVisionAnalysis) -> ScreenshotVisionAnalysis:
        """Save one vision result without exposing raw image bytes in SQLite."""

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO vision_analyses (
                    run_id, source_url, status, analysis_json, analyzed_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_url) DO UPDATE SET
                    status = excluded.status,
                    analysis_json = excluded.analysis_json,
                    analyzed_at = excluded.analyzed_at
                """,
                (
                    analysis.run_id,
                    analysis.source_url,
                    analysis.status,
                    analysis.model_dump_json(),
                    analysis.analyzed_at,
                ),
            )
        return analysis

    def list_for_run(self, run_id: str) -> tuple[ScreenshotVisionAnalysis, ...]:
        """Return M5 results in a stable source order."""

        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT analysis_json FROM vision_analyses WHERE run_id = ? ORDER BY source_url",
                (run_id,),
            ).fetchall()
        return tuple(ScreenshotVisionAnalysis.model_validate_json(row["analysis_json"]) for row in rows)
