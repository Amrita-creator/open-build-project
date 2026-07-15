"""Integration tests for the durable run lifecycle."""

import tempfile
import unittest
from pathlib import Path

from inspo_mcp.models.run import RunStatus
from inspo_mcp.models.source import SourceRecord, SourceStatus, utc_now
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.schemas import InspirationRequest
from inspo_mcp.services.run_manager import RunManager
from inspo_mcp.services.url_safety import SafeUrl
from inspo_mcp.storage.database import SqliteDatabase


class RunManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self._temporary_directory.name) / "runs.db"
        repository = RunRepository(SqliteDatabase(database_path))
        self.manager = RunManager(repository)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_mock_run_is_persisted_as_completed(self) -> None:
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
        )

        kit = self.manager.create_mock_kit(request)
        run = self.manager.get_run(kit.run_id)

        self.assertTrue(kit.is_mock)
        self.assertEqual(run.run_id, kit.run_id)
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.project_goal, request.project_goal)
        self.assertEqual(run.inspiration_urls, tuple(str(url) for url in request.inspiration_urls))

    async def test_capture_stage_persists_run_and_exposes_source_failures(self) -> None:
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
            {"https://example.com/": "/path/to/screenshot.png"}
        )


class _CaptureSpy:
    """Small in-memory capture boundary used to verify the run orchestration."""

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.safe_urls: tuple[SafeUrl, ...] | None = None
        self.fallback_screenshots: dict[str, str] | None = None

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
            SourceRecord(
                run_id=run_id,
                source_url=safe_urls[1].url,
                final_url=None,
                status=SourceStatus.FAILED,
                http_status=502,
                title=None,
                visible_text_path=None,
                screenshot_path=None,
                content_hash=None,
                redirect_chain=(safe_urls[1].url,),
                captured_at=now,
                error_message="Capture returned HTTP 502.",
            ),
        )


if __name__ == "__main__":
    unittest.main()
