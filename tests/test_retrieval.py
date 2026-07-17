"""M7 tests for durable kit retrieval, progress, and restart-safe partial work."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inspo_mcp.models.run import RunRecord, RunStatus, utc_now
from inspo_mcp.models.source import SourceRecord, SourceStatus
from inspo_mcp.repositories.kits import KitRepository
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.site_analyses import SiteAnalysisRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas import InspirationRequest, ScreenshotVisionAnalysis
from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis
from inspo_mcp.services.mock_artifacts import create_mock_kit
from inspo_mcp.services.run_manager import RunManager
from inspo_mcp.services.vision import VisionAnalysisService
from inspo_mcp.storage.database import SqliteDatabase
from inspo_mcp.tools.get_kit import build_kit_lookup
from inspo_mcp.tools.get_status import build_run_status


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = SqliteDatabase(Path(self._temporary_directory.name) / "m7.db")
        self.runs = RunRepository(self.database)
        self.sources = SourceRepository(self.database)
        self.structures = SiteAnalysisRepository(self.database)
        self.vision = VisionAnalysisRepository(self.database)
        self.kits = KitRepository(self.database)
        self.run = self.runs.create(
            RunRecord(
                run_id="run_m7",
                status=RunStatus.GENERATING,
                inspiration_urls=("user-screenshot://one", "user-screenshot://two"),
                project_goal="Build a durable design-starter-kit workflow.",
                framework="nextjs-tailwind",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_status_reports_partial_vision_results_and_actionable_warnings(self) -> None:
        first, second = self._persist_sources()
        self.structures.upsert(
            SiteStructureAnalysis(
                run_id=self.run.run_id,
                source_url=first.source_url,
                status="awaiting_vision",
                extracted_at=utc_now(),
            )
        )
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=first.source_url,
                status="pending",
                message="M5 vision analysis is queued and running in the background.",
                analyzed_at=utc_now(),
            )
        )
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=second.source_url,
                status="not_configured",
                message="Local Ollama is not running.",
                analyzed_at=utc_now(),
            )
        )

        report = self._report()
        lookup = build_kit_lookup(report, self.kits.get_optional(self.run.run_id))

        self.assertEqual(report.progress, 75)
        self.assertFalse(report.is_terminal)
        self.assertFalse(report.kit_ready)
        self.assertEqual([source.status for source in report.sources], ["pending", "not_configured"])
        self.assertTrue(any("Ollama" in warning.message for warning in report.warnings))
        self.assertEqual(lookup.state, "not_ready")
        self.assertIn("get_status", lookup.message)

    def test_status_requires_retry_when_any_requested_visual_analysis_failed(self) -> None:
        first, second = self._persist_sources()
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=first.source_url,
                status="completed",
                summary="Completed visual evidence.",
                analyzed_at=utc_now(),
            )
        )
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=second.source_url,
                status="failed",
                message="Local Ollama vision analysis timed out.",
                analyzed_at=utc_now(),
            )
        )

        report = self._report()

        self.assertEqual(report.stage, "M5 visual evidence needs retry")
        self.assertFalse(report.is_terminal)
        self.assertIn("retry_vision_analysis", report.next_action)

    def test_stored_kit_is_retrievable_after_recreating_the_repository(self) -> None:
        self._persist_sources()
        request = InspirationRequest(
            project_goal=self.run.project_goal,
            inspiration_screenshots=[
                {"image_path": "C:/references/one.png"},
                {"image_path": "C:/references/two.png"},
            ],
        )
        kit = create_mock_kit(request, run_id=self.run.run_id).model_copy(
            update={"is_mock": False}
        )
        self.kits.upsert(kit)

        reloaded_kits = KitRepository(self.database)
        report = self._report(kit_ready=True)
        lookup = build_kit_lookup(report, reloaded_kits.get_optional(self.run.run_id))

        self.assertEqual(lookup.state, "ready")
        self.assertIsNotNone(lookup.kit)
        self.assertFalse(lookup.kit.is_mock if lookup.kit else True)
        self.assertEqual(report.progress, 100)
        self.assertTrue(report.kit_ready)

    async def test_pending_vision_can_resume_from_sqlite_after_restart(self) -> None:
        source, _ = self._persist_sources()
        self.structures.upsert(
            SiteStructureAnalysis(
                run_id=self.run.run_id,
                source_url=source.source_url,
                status="awaiting_vision",
                extracted_at=utc_now(),
            )
        )
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=source.source_url,
                status="pending",
                analyzed_at=utc_now(),
            )
        )
        manager = RunManager(
            self.runs,
            vision_service=VisionAnalysisService(self.vision, _VisionSpy()),
            source_repository=self.sources,
            site_analysis_repository=self.structures,
            vision_repository=self.vision,
        )

        self.assertTrue(manager.has_resumable_vision(self.run.run_id))
        analyses = await manager.analyze_deferred_vision(self.run.run_id)

        self.assertEqual([analysis.status for analysis in analyses], ["completed"])
        self.assertEqual(self.runs.get(self.run.run_id).status, RunStatus.COMPLETED)
        self.assertEqual(self.vision.list_for_run(self.run.run_id)[0].status, "completed")

    async def test_retry_queues_only_incomplete_vision_sources(self) -> None:
        first, second = self._persist_sources()
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=first.source_url,
                status="failed",
                message="Timed out.",
                analyzed_at=utc_now(),
            )
        )
        self.vision.upsert(
            ScreenshotVisionAnalysis(
                run_id=self.run.run_id,
                source_url=second.source_url,
                status="completed",
                summary="Already complete.",
                analyzed_at=utc_now(),
            )
        )
        manager = RunManager(
            self.runs,
            vision_service=VisionAnalysisService(self.vision, _VisionSpy()),
            source_repository=self.sources,
            site_analysis_repository=self.structures,
            vision_repository=self.vision,
        )

        queued = manager.retry_vision_analysis(self.run.run_id)
        analyses = await manager.analyze_deferred_vision(self.run.run_id)

        self.assertEqual([analysis.source_url for analysis in queued], [first.source_url])
        self.assertEqual([analysis.status for analysis in analyses], ["completed"])
        by_source = {analysis.source_url: analysis.status for analysis in self.vision.list_for_run(self.run.run_id)}
        self.assertEqual(by_source, {first.source_url: "completed", second.source_url: "completed"})

    def _persist_sources(self) -> tuple[SourceRecord, SourceRecord]:
        now = utc_now()
        first = self.sources.upsert(
            SourceRecord(
                run_id=self.run.run_id,
                source_url="user-screenshot://one",
                final_url=None,
                status=SourceStatus.USER_PROVIDED,
                http_status=None,
                title="One",
                visible_text_path=None,
                screenshot_path="one.png",
                content_hash="a" * 64,
                redirect_chain=("user-screenshot://one",),
                captured_at=now,
                capture_note="User-provided screenshot accepted as primary visual evidence.",
            )
        )
        second = self.sources.upsert(
            SourceRecord(
                run_id=self.run.run_id,
                source_url="user-screenshot://two",
                final_url=None,
                status=SourceStatus.CAPTURED,
                http_status=200,
                title="Two",
                visible_text_path="two.txt",
                screenshot_path="two.png",
                content_hash="b" * 64,
                redirect_chain=("user-screenshot://two",),
                captured_at=now,
            )
        )
        return first, second

    def _report(self, *, kit_ready: bool = False):
        return build_run_status(
            self.runs.get(self.run.run_id),
            self.sources.list_for_run(self.run.run_id),
            self.structures.list_for_run(self.run.run_id),
            self.vision.list_for_run(self.run.run_id),
            kit_ready=kit_ready,
        )


class _VisionSpy:
    async def analyze(
        self,
        source: SourceRecord,
        text_analysis: SiteStructureAnalysis | None,
    ) -> ScreenshotVisionAnalysis:
        return ScreenshotVisionAnalysis(
            run_id=source.run_id,
            source_url=source.source_url,
            source_content_hash=source.content_hash,
            status="completed",
            summary="Resumed analysis from persisted screenshot evidence.",
            analyzed_at=utc_now(),
        )


if __name__ == "__main__":
    unittest.main()
