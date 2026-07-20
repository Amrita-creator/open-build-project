"""Offline tests for M5 screenshot-first analysis orchestration."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from inspo_mcp.models.source import SourceRecord, SourceStatus, utc_now
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis
from inspo_mcp.services.vision import (
    OllamaVisionAnalyzer,
    VisionAnalysisService,
    extract_screenshot_palette,
    _parse_model_output,
    _vision_prompt,
)
from inspo_mcp.storage.database import SqliteDatabase


class VisionAnalysisServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._root = Path(self._temporary_directory.name)
        self.repository = VisionAnalysisRepository(SqliteDatabase(self._root / "vision.db"))

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    async def test_persists_a_completed_visual_analysis_with_m4_context(self) -> None:
        source = _source("run_vision", self._write_screenshot("persisted-analysis.png"))
        text_analysis = SiteStructureAnalysis(
            run_id=source.run_id,
            source_url=source.source_url,
            status="extracted",
            extracted_at=utc_now(),
        )
        analyzer = _VisionSpy()
        service = VisionAnalysisService(self.repository, analyzer)

        analyses = await service.analyze_and_store((source,), (text_analysis,))

        self.assertEqual(analyses[0].status, "completed")
        self.assertEqual(analyzer.received_source, source)
        self.assertEqual(analyzer.received_text_analysis, text_analysis)
        self.assertEqual(self.repository.list_for_run(source.run_id), analyses)

    async def test_marks_background_work_as_pending(self) -> None:
        source = _source("run_pending", self._write_screenshot("pending.png"))
        service = VisionAnalysisService(self.repository, _VisionSpy())

        analyses = service.mark_pending((source,))

        self.assertEqual(analyses[0].status, "pending")
        self.assertEqual(self.repository.list_for_run(source.run_id)[0].status, "pending")

    async def test_analyzes_multiple_sources_concurrently(self) -> None:
        first = _source("run_parallel", self._write_screenshot("first.png"))
        second = replace(
            first,
            source_url="user-screenshot://reference-two",
            screenshot_path=str(self._write_screenshot("second.png")),
            content_hash="b" * 64,
        )
        analyzer = _ConcurrentVisionSpy()
        service = VisionAnalysisService(self.repository, analyzer, max_concurrency=2)

        task = asyncio.create_task(service.analyze_and_store((first, second), ()))
        await asyncio.wait_for(analyzer.both_started.wait(), timeout=0.5)
        analyzer.release.set()
        analyses = await task

        self.assertEqual(len(analyses), 2)
        self.assertEqual(analyzer.started, 2)

    async def test_ollama_analyzer_sends_screenshot_to_local_api_only(self) -> None:
        screenshot_path = self._write_screenshot("reference.png")
        source = _source("run_local_ollama", screenshot_path)
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "summary": "A calm SaaS layout direction.",
                            "visual_style": ["restrained contrast"],
                            "layout_patterns": ["hero then cards"],
                            "component_patterns": ["feature cards"],
                            "color_direction": ["dark neutral base"],
                            "text_alignment": "aligned",
                            "text_mismatches": [],
                        }
                    )
                },
            )

        analyzer = OllamaVisionAnalyzer(
            model="test-vision",
            transport=httpx.MockTransport(handler),
        )
        analysis = await analyzer.analyze(source, None)

        self.assertEqual(analysis.status, "completed")
        self.assertEqual(analysis.summary, "A calm SaaS layout direction.")
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/api/generate")
        body = captured["body"]
        self.assertIsInstance(body, dict)
        self.assertEqual(body["model"], "test-vision")  # type: ignore[index]
        self.assertTrue(body["images"][0])  # type: ignore[index]
        self.assertEqual(body["format"], "json")  # type: ignore[index]
        self.assertFalse(body["stream"])  # type: ignore[index]

    async def test_ollama_analyzer_retries_malformed_json_with_compact_prompt(self) -> None:
        screenshot_path = self._write_screenshot("retry-reference.png")
        source = _source("run_json_retry", screenshot_path)
        requests: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content.decode("utf-8")))
            if len(requests) == 1:
                return httpx.Response(200, json={"response": '{"summary":"unterminated'})
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "summary": "A compact, valid retry result.",
                            "visual_style": ["clear hierarchy"],
                            "layout_patterns": ["hero then cards"],
                            "component_patterns": ["feature card"],
                            "color_direction": ["dark neutral base"],
                            "text_alignment": "aligned",
                            "text_mismatches": [],
                        }
                    )
                },
            )

        analyzer = OllamaVisionAnalyzer(
            model="test-vision",
            transport=httpx.MockTransport(handler),
        )
        analysis = await analyzer.analyze(source, None)

        self.assertEqual(analysis.status, "completed")
        self.assertEqual(analysis.summary, "A compact, valid retry result.")
        self.assertEqual(len(requests), 2)
        self.assertIn("previous response could not be parsed", requests[1]["prompt"])  # type: ignore[index]

    def test_parser_ignores_non_json_text_around_a_valid_object(self) -> None:
        source = _source("run_wrapped_json", self._write_screenshot("wrapped-json.png"))

        analysis = _parse_model_output(
            source,
            "Here is the analysis:\n"
            + json.dumps(
                {
                    "summary": "A valid wrapped object.",
                    "visual_style": ["focused"],
                    "layout_patterns": [],
                    "component_patterns": [],
                    "color_direction": [],
                    "text_alignment": "not_available",
                    "text_mismatches": [],
                }
            )
            + "\nEnd of response.",
        )

        self.assertEqual(analysis.status, "completed")
        self.assertEqual(analysis.summary, "A valid wrapped object.")

    async def test_missing_local_model_returns_a_setup_message(self) -> None:
        screenshot_path = self._write_screenshot("missing-model.png")
        source = _source("run_missing_model", screenshot_path)

        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        analyzer = OllamaVisionAnalyzer(
            model="missing-model",
            transport=httpx.MockTransport(handler),
        )
        analysis = await analyzer.analyze(source, None)

        self.assertEqual(analysis.status, "not_configured")
        self.assertIn("ollama pull missing-model", analysis.message or "")

    def test_rejects_a_remote_ollama_base_url(self) -> None:
        with self.assertRaises(ValueError):
            OllamaVisionAnalyzer(base_url="https://example.com")

    def test_malformed_alignment_value_is_safely_normalized(self) -> None:
        source = _source("run_malformed_alignment", self._write_screenshot("malformed.png"))

        analysis = _parse_model_output(
            source,
            json.dumps(
                {
                    "summary": "A visual direction.",
                    "visual_style": ["clean hierarchy"],
                    "layout_patterns": [],
                    "component_patterns": [],
                    "color_direction": [],
                    "text_alignment": [],
                    "text_mismatches": [],
                }
            ),
        )

        self.assertEqual(analysis.status, "completed")
        self.assertEqual(analysis.text_alignment, "not_available")

    def test_prompt_requires_evidence_based_ui_analysis(self) -> None:
        prompt = _vision_prompt(None)

        self.assertIn("Do not call a layout a form, table, or grid", prompt)
        self.assertIn("Visible page regions in top-to-bottom order", prompt)
        self.assertIn("Component name: purpose and visible anatomy", prompt)
        self.assertIn("Return valid JSON only", prompt)

    def test_extracts_a_local_palette_from_screenshot_pixels(self) -> None:
        image_path = self._root / "palette.png"
        image = Image.new("RGB", (100, 100), "#5865F2")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((0, 55, 100, 100), fill="#E2E5FF")
        drawing.rectangle((0, 55, 22, 100), fill="#FFF200")
        drawing.rectangle((22, 55, 35, 100), fill="#111111")
        drawing.rectangle((35, 55, 45, 100), fill="#EC3D9A")
        image.save(image_path)

        palette = extract_screenshot_palette(image_path)

        self.assertIn("#5865F2", palette)
        self.assertIn("#E2E5FF", palette)
        self.assertIn("#FFF200", palette)
        self.assertIn("#EC3D9A", palette)

    def _write_screenshot(self, filename: str) -> Path:
        path = self._root / filename
        path.write_bytes(b"\x89PNG\r\n\x1a\nlocal-test-image")
        return path


class _VisionSpy:
    def __init__(self) -> None:
        self.received_source: SourceRecord | None = None
        self.received_text_analysis: SiteStructureAnalysis | None = None

    async def analyze(
        self,
        source: SourceRecord,
        text_analysis: SiteStructureAnalysis | None,
    ) -> ScreenshotVisionAnalysis:
        self.received_source = source
        self.received_text_analysis = text_analysis
        return ScreenshotVisionAnalysis(
            run_id=source.run_id,
            source_url=source.source_url,
            source_content_hash=source.content_hash,
            status="completed",
            summary="A clean SaaS dashboard direction.",
            visual_style=["restrained contrast"],
            layout_patterns=["hero-led hierarchy"],
            component_patterns=["feature cards"],
            color_direction=["cool neutral base"],
            text_alignment="aligned",
            analyzed_at=utc_now(),
        )


class _ConcurrentVisionSpy:
    def __init__(self) -> None:
        self.started = 0
        self.both_started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(
        self,
        source: SourceRecord,
        text_analysis: SiteStructureAnalysis | None,
    ) -> ScreenshotVisionAnalysis:
        self.started += 1
        if self.started == 2:
            self.both_started.set()
        await self.release.wait()
        return ScreenshotVisionAnalysis(
            run_id=source.run_id,
            source_url=source.source_url,
            source_content_hash=source.content_hash,
            status="completed",
            summary="Parallel visual analysis.",
            analyzed_at=utc_now(),
        )


def _source(run_id: str, screenshot_path: Path) -> SourceRecord:
    return SourceRecord(
        run_id=run_id,
        source_url="user-screenshot://reference-one",
        final_url=None,
        status=SourceStatus.USER_PROVIDED,
        http_status=None,
        title="Reference one",
        visible_text_path=None,
        screenshot_path=str(screenshot_path),
        content_hash="a" * 64,
        redirect_chain=("user-screenshot://reference-one",),
        captured_at=utc_now(),
        capture_note="Primary screenshot accepted.",
    )


if __name__ == "__main__":
    unittest.main()
