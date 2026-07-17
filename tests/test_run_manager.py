"""Integration tests for the durable run lifecycle."""

import tempfile
import unittest
from pathlib import Path

from inspo_mcp.models.run import RunStatus
from inspo_mcp.models.source import SourceRecord, SourceStatus, utc_now
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas import InspirationRequest, ScreenshotVisionAnalysis
from inspo_mcp.services.run_manager import RunManager
from inspo_mcp.services.url_safety import SafeUrl
from inspo_mcp.services.vision import VisionAnalysisService
from inspo_mcp.storage.database import SqliteDatabase


class RunManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self._temporary_directory.name) / "runs.db"
        self.database = SqliteDatabase(database_path)
        self.repository = RunRepository(self.database)
        self.manager = RunManager(self.repository)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_mock_run_is_persisted_as_completed(self) -> None:
        from inspo_mcp.schemas import ScreenshotFallback
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
            fallback_screenshots=[
                ScreenshotFallback(source_url="https://example.com", image_path="/path/1.png"),
                ScreenshotFallback(source_url="https://example.org", image_path="/path/2.png"),
            ]
        )

        kit = self.manager.create_mock_kit(request)
        run = self.manager.get_run(kit.run_id)

        self.assertTrue(kit.is_mock)
        self.assertEqual(run.run_id, kit.run_id)
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.project_goal, request.project_goal)
        self.assertEqual(run.inspiration_urls, tuple(str(url) for url in request.inspiration_urls))

    async def test_capture_stage_persists_run_and_exposes_source_failures(self) -> None:
        from inspo_mcp.schemas import ScreenshotFallback
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
            fallback_screenshots=[
                ScreenshotFallback(source_url="https://example.com", image_path="/path/1.png"),
                ScreenshotFallback(source_url="https://example.org", image_path="/path/2.png"),
            ]
        )
        safe_urls = (
            SafeUrl(
                url="https://example.com/",
                host="example.com",
                resolved_ips=("93.184.216.34",),
            ),
            SafeUrl(
                url="https://example.org/",
                host="example.org",
                resolved_ips=("93.184.216.34",),
            ),
        )
        capture_service = _CaptureSpy()

        kit = await self.manager.create_captured_mock_kit(
            request,
            safe_urls,
            capture_service,  # type: ignore[arg-type]
        )
        run = self.manager.get_run(kit.run_id)

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(capture_service.run_id, kit.run_id)
        self.assertEqual(capture_service.safe_urls, safe_urls)
        self.assertEqual(len(kit.warnings), 1)
        self.assertEqual(kit.warnings[0].url, safe_urls[1].url)

    async def test_capture_stage_forwards_fallback_screenshots(self) -> None:
        from inspo_mcp.schemas import ScreenshotFallback
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
            fallback_screenshots=[
                ScreenshotFallback(
                    source_url="https://example.com",
                    image_path="/path/to/screenshot.png",
                ),
                ScreenshotFallback(
                    source_url="https://example.org",
                    image_path="/path/to/screenshot2.png",
                )
            ]
        )
        safe_urls = (
            SafeUrl(
                url="https://example.com/",
                host="example.com",
                resolved_ips=("93.184.216.34",),
            ),
            SafeUrl(
                url="https://example.org/",
                host="example.org",
                resolved_ips=("93.184.216.34",),
            ),
        )
        capture_service = _CaptureSpy()

        await self.manager.create_captured_mock_kit(
            request,
            safe_urls,
            capture_service,  # type: ignore[arg-type]
        )

        self.assertEqual(
            capture_service.fallback_screenshots,
            {
                "https://example.com/": "/path/to/screenshot.png",
                "https://example.org/": "/path/to/screenshot2.png",
            },
        )

    async def test_capture_stage_warns_when_user_screenshot_is_used(self) -> None:
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
        )
        safe_urls = (
            SafeUrl(
                url="https://example.com/",
                host="example.com",
                resolved_ips=("93.184.216.34",),
            ),
            SafeUrl(
                url="https://example.org/",
                host="example.org",
                resolved_ips=("93.184.216.34",),
            ),
        )

        kit = await self.manager.create_captured_mock_kit(
            request,
            safe_urls,
            _CaptureSpy(use_user_screenshot=True),  # type: ignore[arg-type]
        )

        self.assertEqual(len(kit.warnings), 1)
        self.assertIn("user-provided screenshot", kit.warnings[0].message.lower())

    async def test_screenshot_only_run_skips_automatic_url_capture(self) -> None:
        from inspo_mcp.schemas import InspirationScreenshot

        request = InspirationRequest(
            project_goal="Build a developer tool landing page.",
            inspiration_screenshots=[
                InspirationScreenshot(image_path="C:/screenshots/one.png", label="One"),
                InspirationScreenshot(image_path="C:/screenshots/two.png", label="Two"),
            ],
        )
        capture_service = _CaptureSpy()

        kit = await self.manager.create_captured_mock_kit(
            request,
            (),
            capture_service,  # type: ignore[arg-type]
        )
        run = self.manager.get_run(kit.run_id)

        self.assertEqual(capture_service.safe_urls, ())
        self.assertEqual(len(capture_service.primary_screenshots or ()), 2)
        self.assertEqual(run.inspiration_urls, request.source_identifiers)
        self.assertTrue(all("primary visual evidence" in warning.message for warning in kit.warnings))

    async def test_defers_m5_and_completes_it_later(self) -> None:
        from inspo_mcp.schemas import InspirationScreenshot

        request = InspirationRequest(
            project_goal="Build a developer tool landing page.",
            inspiration_screenshots=[
                InspirationScreenshot(image_path="C:/screenshots/one.png"),
                InspirationScreenshot(image_path="C:/screenshots/two.png"),
            ],
        )
        vision_repository = VisionAnalysisRepository(self.database)
        manager = RunManager(
            self.repository,
            vision_service=VisionAnalysisService(vision_repository, _M5Spy()),
        )

        kit = await manager.create_captured_mock_kit(
            request,
            (),
            _CaptureSpy(),  # type: ignore[arg-type]
            defer_vision=True,
        )

        self.assertEqual(self.repository.get(kit.run_id).status, RunStatus.GENERATING)
        self.assertEqual(
            [analysis.status for analysis in vision_repository.list_for_run(kit.run_id)],
            ["pending", "pending"],
        )
        self.assertTrue(any("running in the background" in warning.message for warning in kit.warnings))

        analyses = await manager.analyze_deferred_vision(kit.run_id)

        self.assertEqual([analysis.status for analysis in analyses], ["completed", "completed"])
        self.assertEqual(self.repository.get(kit.run_id).status, RunStatus.COMPLETED)


class _CaptureSpy:
    """Small in-memory capture boundary used to verify the run orchestration."""

    def __init__(self, *, use_user_screenshot: bool = False) -> None:
        self.run_id: str | None = None
        self.safe_urls: tuple[SafeUrl, ...] | None = None
        self.fallback_screenshots: dict[str, str] | None = None
        self.primary_screenshots: tuple[object, ...] | None = None
        self.use_user_screenshot = use_user_screenshot

    async def capture_sources(
        self,
        run_id: str,
        safe_urls: tuple[SafeUrl, ...],
        *,
        fallback_screenshots: dict[str, str] | None = None,
    ) -> tuple[SourceRecord, ...]:
        self.run_id = run_id
        self.safe_urls = safe_urls
        self.fallback_screenshots = fallback_screenshots
        if not safe_urls:
            return ()
        now = utc_now()
        return (
            SourceRecord(
                run_id=run_id,
                source_url=safe_urls[0].url,
                final_url=safe_urls[0].url,
                status=SourceStatus.CAPTURED,
                http_status=200,
                title="Example",
                visible_text_path="capture.txt",
                screenshot_path="capture.png",
                content_hash="a" * 64,
                redirect_chain=(safe_urls[0].url,),
                captured_at=now,
            ),
            self._second_source(run_id, safe_urls[1], now),
        )

    async def capture_primary_screenshots(
        self,
        run_id: str,
        screenshots: tuple[object, ...] | list[object],
    ) -> tuple[SourceRecord, ...]:
        self.primary_screenshots = tuple(screenshots)
        now = utc_now()
        return tuple(
            SourceRecord(
                run_id=run_id,
                source_url=screenshot.source_identifier,  # type: ignore[attr-defined]
                final_url=None,
                status=SourceStatus.USER_PROVIDED,
                http_status=None,
                title=screenshot.label,  # type: ignore[attr-defined]
                visible_text_path=None,
                screenshot_path=f"{index}.png",
                content_hash=f"{index:064x}",
                redirect_chain=(screenshot.source_identifier,),  # type: ignore[attr-defined]
                captured_at=now,
                capture_note="User-provided screenshot accepted as primary visual evidence.",
            )
            for index, screenshot in enumerate(screenshots, start=1)
        )

    async def enrich_primary_screenshots(
        self,
        run_id: str,
        safe_urls: tuple[SafeUrl, ...],
    ) -> tuple[SourceRecord, ...]:
        return ()

    def _second_source(
        self,
        run_id: str,
        source: SafeUrl,
        captured_at: str,
    ) -> SourceRecord:
        if self.use_user_screenshot:
            return SourceRecord(
                run_id=run_id,
                source_url=source.url,
                final_url=source.url,
                status=SourceStatus.USER_PROVIDED,
                http_status=403,
                title=None,
                visible_text_path=None,
                screenshot_path="user-supplied.png",
                content_hash="b" * 64,
                redirect_chain=(source.url,),
                captured_at=captured_at,
                capture_note="Automatic capture was unavailable; user-provided screenshot used.",
            )
        return SourceRecord(
            run_id=run_id,
            source_url=source.url,
            final_url=None,
            status=SourceStatus.FAILED,
            http_status=502,
            title=None,
            visible_text_path=None,
            screenshot_path=None,
            content_hash=None,
            redirect_chain=(source.url,),
            captured_at=captured_at,
            error_message="Capture returned HTTP 502.",
        )


class _M5Spy:
    async def analyze(
        self,
        source: SourceRecord,
        text_analysis: object | None,
    ) -> ScreenshotVisionAnalysis:
        return ScreenshotVisionAnalysis(
            run_id=source.run_id,
            source_url=source.source_url,
            source_content_hash=source.content_hash,
            status="completed",
            summary="Background visual analysis.",
            analyzed_at=utc_now(),
        )


if __name__ == "__main__":
    unittest.main()
