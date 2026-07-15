"""SQLite persistence for M4 page-structure extraction results."""

from __future__ import annotations

from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis
from inspo_mcp.storage.database import SqliteDatabase


class SiteAnalysisRepository:
    """Store one current structure analysis for every run/source pair."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS site_analyses (
                    run_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    extracted_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, source_url)
                )
                """
            )

    def upsert(self, analysis: SiteStructureAnalysis) -> SiteStructureAnalysis:
        """Persist the latest extraction result for a captured source."""

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO site_analyses (
                    run_id, source_url, status, analysis_json, extracted_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_url) DO UPDATE SET
                    status = excluded.status,
                    analysis_json = excluded.analysis_json,
                    extracted_at = excluded.extracted_at
                """,
                (
                    analysis.run_id,
                    analysis.source_url,
                    analysis.status,
                    analysis.model_dump_json(),
                    analysis.extracted_at,
                ),
            )
        return analysis

    def list_for_run(self, run_id: str) -> tuple[SiteStructureAnalysis, ...]:
        """Return every persisted M4 result in deterministic source order."""

        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT analysis_json FROM site_analyses WHERE run_id = ? ORDER BY source_url",
                (run_id,),
            ).fetchall()
        return tuple(SiteStructureAnalysis.model_validate_json(row["analysis_json"]) for row in rows)
