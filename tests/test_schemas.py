"""Contract tests for the Phase 1 MCP response shape."""

import unittest

from pydantic import ValidationError

from inspo_mcp.schemas import InspirationRequest
from inspo_mcp.services.mock_artifacts import create_mock_kit


class InspirationSchemaTests(unittest.TestCase):
    def test_request_needs_two_urls(self) -> None:
        with self.assertRaises(ValidationError):
            InspirationRequest(
                inspiration_urls=["https://example.com"],
                project_goal="Build a developer tool landing page.",
            )

    def test_mock_kit_has_all_five_artifacts(self) -> None:
        request = InspirationRequest(
            inspiration_urls=["https://example.com", "https://example.org"],
            project_goal="Build a developer tool landing page.",
        )

        kit = create_mock_kit(request, run_id="mock_test_run")

        self.assertTrue(kit.is_mock)
        self.assertEqual(kit.run_id, "mock_test_run")
        self.assertTrue(kit.design_direction.summary)
        self.assertTrue(kit.page_blueprint.sections)
        self.assertTrue(kit.component_cards)
        self.assertTrue(kit.design_tokens.colors)
        self.assertTrue(kit.build_tasks)


if __name__ == "__main__":
    unittest.main()
