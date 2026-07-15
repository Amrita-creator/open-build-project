"""Offline tests for M4 page-structure extraction and persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inspo_mcp.models.source import SourceRecord, SourceStatus, utc_now
from inspo_mcp.repositories.site_analyses import SiteAnalysisRepository
from inspo_mcp.services.extract import StructureExtractor
from inspo_mcp.storage.database import SqliteDatabase


class StructureExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.repository = SiteAnalysisRepository(SqliteDatabase(self.root / "extract.db"))
        self.extractor = StructureExtractor(self.repository)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_extracts_sections_ctas_cards_hierarchy_and_persists_result(self) -> None:
        text_path = self.root / "visible.txt"
        text_path.write_text(
            "\n".join(
                [
                    "Acme analytics",
                    "A unified analytics platform for product teams.",
                    "Get started",
                    "Features",
                    "Realtime dashboards",
                    "Monitor product metrics as they change.",
                    "Automated reports",
                    "Schedule concise reports for every stakeholder.",
                    "Pricing",
                    "Choose a plan that grows with your team.",
                ]
            ),
            encoding="utf-8",
        )
        source = _source(
            run_id="run_extract",
            visible_text_path=str(text_path),
            title="Acme analytics",
        )

        analysis = self.extractor.extract_and_store((source,))[0]

        self.assertEqual(analysis.status, "extracted")
        self.assertEqual([section.name for section in analysis.sections], ["Acme analytics", "Features", "Pricing"])
        self.assertEqual(analysis.calls_to_action[0].label, "Get started")
        self.assertEqual(analysis.calls_to_action[0].section, "Acme analytics")
        self.assertEqual(
            [card.title for card in analysis.cards],
            ["Realtime dashboards", "Automated reports"],
        )
        self.assertEqual(analysis.sections[1].card_titles, ["Realtime dashboards", "Automated reports"])
        self.assertEqual(analysis.hierarchy[0].level, 1)
        self.assertEqual(analysis.hierarchy[1].text, "Features")
        self.assertEqual(self.repository.list_for_run("run_extract"), (analysis,))

    def test_marks_screenshot_only_fallback_as_awaiting_vision(self) -> None:
        screenshot_path = self.root / "fallback.png"
        screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\nplaceholder")
        source = _source(
            run_id="run_screenshot_only",
            status=SourceStatus.USER_PROVIDED,
            screenshot_path=str(screenshot_path),
        )

        analysis = self.extractor.extract_and_store((source,))[0]

        self.assertEqual(analysis.status, "awaiting_vision")
        self.assertIn("M5 vision", analysis.extraction_message or "")
        self.assertEqual(self.repository.list_for_run("run_screenshot_only"), (analysis,))


def _source(
    *,
    run_id: str,
    status: SourceStatus = SourceStatus.CAPTURED,
    visible_text_path: str | None = None,
    screenshot_path: str | None = None,
    title: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        run_id=run_id,
        source_url="https://example.com/",
        final_url="https://example.com/",
        status=status,
        http_status=200,
        title=title,
        visible_text_path=visible_text_path,
        screenshot_path=screenshot_path,
        content_hash="a" * 64,
        redirect_chain=("https://example.com/",),
        captured_at=utc_now(),
    )


if __name__ == "__main__":
    unittest.main()
