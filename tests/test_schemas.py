"""Contract tests for the Phase 1 MCP response shape."""

import unittest

from pydantic import ValidationError

from inspo_mcp.schemas import InspirationRequest
from inspo_mcp.services.mock_artifacts import create_mock_kit


class InspirationSchemaTests(unittest.TestCase):
    def test_request_needs_two_urls(self) -> None:
        from inspo_mcp.schemas import ScreenshotFallback
        with self.assertRaises(ValidationError):
            InspirationRequest(
                inspiration_urls=["https://example.com"],
                project_goal="Build a developer tool landing page.",
                fallback_screenshots=[
                    ScreenshotFallback(source_url="https://example.com", image_path="/path/1.png")
                ]
            )

    def test_mock_kit_has_all_five_artifacts(self) -> None:
        from inspo_mcp.schemas import ScreenshotFallback
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
            fallback_screenshots=[
                ScreenshotFallback(source_url="https://example.com", image_path="/path/1.png"),
                ScreenshotFallback(source_url="https://example.org", image_path="/path/2.png"),
            ]
        )

        kit = create_mock_kit(request, run_id="mock_test_run")

        self.assertTrue(kit.is_mock)
        self.assertEqual(kit.run_id, "mock_test_run")
        self.assertTrue(kit.design_direction.summary)
        self.assertTrue(kit.page_blueprint.sections)
        self.assertTrue(kit.component_cards)
        self.assertTrue(kit.design_tokens.colors)
        self.assertTrue(kit.build_tasks)

    def test_request_allows_a_fallback_for_only_one_source(self) -> None:
        from inspo_mcp.schemas import ScreenshotFallback
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
            fallback_screenshots=[
                ScreenshotFallback(source_url="https://example.com", image_path="/path/1.png")
            ]
        )

        self.assertEqual(
            request.fallback_screenshot_map,
            {"https://example.com/": "/path/1.png"},
        )

    def test_request_accepts_screenshot_only_sources(self) -> None:
        from inspo_mcp.schemas import InspirationScreenshot

        request = InspirationRequest(
            project_goal="Build a developer tool landing page.",
            inspiration_screenshots=[
                InspirationScreenshot(image_path="C:/screenshots/one.png", label="Linear"),
                InspirationScreenshot(image_path="C:/screenshots/two.png", label="Notion"),
            ],
        )

        self.assertEqual(request.inspiration_urls, [])
        self.assertEqual(len(request.source_identifiers), 2)
        self.assertTrue(all(identifier.startswith("user-screenshot://") for identifier in request.source_identifiers))

    def test_primary_screenshot_for_url_counts_as_one_source(self) -> None:
        from inspo_mcp.schemas import InspirationScreenshot

        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            inspiration_screenshots=[
                InspirationScreenshot(
                    source_url="https://example.com",
                    image_path="C:/screenshots/example.png",
                )
            ],
            project_goal="Build a developer tool landing page.",
        )

        self.assertEqual(len(request.source_identifiers), 2)
        self.assertEqual(request.primary_screenshot_url_keys, frozenset({"https://example.com/"}))


if __name__ == "__main__":
    unittest.main()
