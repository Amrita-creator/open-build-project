"""Offline tests for the safe M3 source-capture pipeline."""

from __future__ import annotations

import hashlib
import socket
import tempfile
import unittest
from pathlib import Path

from pydantic import HttpUrl

from inspo_mcp.models.source import SourceStatus
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.services.capture import CaptureService, FetchedResponse
from inspo_mcp.services.url_safety import SafeUrl, validate_public_urls
from inspo_mcp.storage.capture_store import LocalCaptureStore
from inspo_mcp.storage.database import SqliteDatabase


def public_resolver(host: str, port: int | None, *, type: int) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def safe_url(url: str) -> SafeUrl:
    return validate_public_urls([HttpUrl(url)], resolver=public_resolver)[0]


class FakeFetcher:
    def __init__(self, pages: dict[str, FetchedResponse]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def get(self, url: str) -> FetchedResponse:
        self.calls.append(url)
        return self.pages[url]


class FakeScreenshotter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def capture(self, url: str, output_path: Path) -> None:
        self.calls.append(url)
        output_path.write_bytes(b"fake-png-evidence")


class CaptureServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self._temporary_directory.name)
        self.repository = SourceRepository(SqliteDatabase(root / "capture.db"))
        self.store = LocalCaptureStore(root / "captures")

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    async def test_captures_sanitized_text_screenshot_metadata_and_cache(self) -> None:
        initial = safe_url("https://example.com")
        final = safe_url("https://example.com/final")
        body = b"""
            <html><head><title>Example title</title><script>secret()</script></head>
            <body><h1>Welcome</h1><p>Build faster.</p>
            <div hidden>Not visible</div><div style='display: none'>Also hidden</div>
            </body></html>
        """
        fetcher = FakeFetcher(
            {
                initial.url: FetchedResponse(
                    url=initial.url,
                    status_code=302,
                    headers={"Location": "/final"},
                    body=b"",
                ),
                final.url: FetchedResponse(
                    url=final.url,
                    status_code=200,
                    headers={"Content-Type": "text/html; charset=utf-8"},
                    body=body,
                ),
            }
        )
        screenshotter = FakeScreenshotter()
        service = CaptureService(
            self.repository,
            self.store,
            fetcher=fetcher,
            screenshotter=screenshotter,
            resolver=public_resolver,
        )

        records = await service.capture_sources("run_capture_test", (initial,))
        record = records[0]

        self.assertEqual(record.status, SourceStatus.CAPTURED)
        self.assertEqual(record.final_url, final.url)
        self.assertEqual(record.http_status, 200)
        self.assertEqual(record.title, "Example title")
        self.assertEqual(record.redirect_chain, (initial.url, final.url))
        self.assertEqual(record.content_hash, hashlib.sha256(body).hexdigest())
        self.assertTrue(Path(record.screenshot_path or "").is_file())
        text = Path(record.visible_text_path or "").read_text(encoding="utf-8")
        self.assertIn("Welcome", text)
        self.assertIn("Build faster.", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("Not visible", text)
        self.assertNotIn("Also hidden", text)
        self.assertEqual(self.repository.list_for_run("run_capture_test"), records)

        cached_records = await service.capture_sources("run_capture_test", (initial,))
        self.assertEqual(cached_records, records)
        self.assertEqual(fetcher.calls, [initial.url, final.url])
        self.assertEqual(screenshotter.calls, [final.url])

    async def test_blocks_private_redirect_and_persists_failure(self) -> None:
        initial = safe_url("https://example.com")
        fetcher = FakeFetcher(
            {
                initial.url: FetchedResponse(
                    url=initial.url,
                    status_code=302,
                    headers={"Location": "http://127.0.0.1/internal"},
                    body=b"",
                )
            }
        )
        screenshotter = FakeScreenshotter()
        service = CaptureService(
            self.repository,
            self.store,
            fetcher=fetcher,
            screenshotter=screenshotter,
            resolver=public_resolver,
        )

        record = (await service.capture_sources("run_blocked_redirect", (initial,)))[0]

        self.assertEqual(record.status, SourceStatus.FAILED)
        self.assertEqual(record.http_status, 302)
        self.assertEqual(record.redirect_chain, (initial.url,))
        self.assertIn("Unsafe redirect target blocked", record.error_message or "")
        self.assertEqual(fetcher.calls, [initial.url])
        self.assertEqual(screenshotter.calls, [])
        self.assertEqual(self.repository.list_for_run("run_blocked_redirect"), (record,))

    async def test_fallback_screenshot_used_on_automatic_capture_failure(self) -> None:
        initial = safe_url("https://example.com")
        # Fetcher returns 500 Internal Server Error, causing automatic capture to fail
        fetcher = FakeFetcher(
            {
                initial.url: FetchedResponse(
                    url=initial.url,
                    status_code=500,
                    headers={},
                    body=b"Internal server error",
                )
            }
        )
        screenshotter = FakeScreenshotter()
        service = CaptureService(
            self.repository,
            self.store,
            fetcher=fetcher,
            screenshotter=screenshotter,
            resolver=public_resolver,
        )

        # Create a valid user fallback screenshot file
        user_screenshot_path = Path(self._temporary_directory.name) / "user_provided.png"
        user_screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00some-image-data")

        records = await service.capture_sources(
            "run_fallback_test",
            (initial,),
            fallback_screenshots={initial.url: str(user_screenshot_path)},
        )
        record = records[0]

        self.assertEqual(record.status, SourceStatus.USER_PROVIDED)
        self.assertEqual(record.http_status, 500)
        self.assertEqual(record.redirect_chain, (initial.url,))
        self.assertTrue(Path(record.screenshot_path or "").is_file())
        self.assertIn("Automatic capture was unavailable", record.capture_note or "")
        self.assertEqual(self.repository.list_for_run("run_fallback_test"), records)


if __name__ == "__main__":
    unittest.main()
