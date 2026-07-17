"""Tool-schema tests for the FastMCP entry point."""

from __future__ import annotations

import unittest

from inspo_mcp.prompts import create_landing_page_ui_kit
from inspo_mcp.server import _primary_screenshots, mcp


class ServerToolSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_screenshot_input_is_a_non_null_path_array_with_an_example(self) -> None:
        tool = await mcp.get_tool("create_inspiration_kit")
        schema = tool.parameters["properties"]["inspiration_screenshots"]

        self.assertEqual(schema["type"], "array")
        self.assertEqual(schema["default"], [])
        self.assertNotIn("anyOf", schema)
        self.assertEqual(schema["items"], {"type": "string"})
        self.assertEqual(schema["examples"][0][0], "C:/Users/Amrita/Pictures/reference-one.png")

    async def test_exposes_a_polling_tool_for_background_m5_results(self) -> None:
        tool = await mcp.get_tool("get_vision_analyses")

        self.assertEqual(tool.parameters["required"], ["run_id"])
        self.assertEqual(tool.parameters["properties"]["run_id"]["type"], "string")
        self.assertIn("pending", tool.description.lower())

    async def test_exposes_m6_evidence_kit_generation(self) -> None:
        tool = await mcp.get_tool("generate_reusable_kit")

        self.assertEqual(tool.parameters["required"], ["run_id"])
        self.assertEqual(tool.parameters["properties"]["run_id"]["type"], "string")

    async def test_exposes_m7_durable_retrieval_tools(self) -> None:
        status_tool = await mcp.get_tool("get_status")
        kit_tool = await mcp.get_tool("get_kit")

        self.assertEqual(status_tool.parameters["required"], ["run_id"])
        self.assertEqual(kit_tool.parameters["required"], ["run_id"])
        self.assertEqual(status_tool.parameters["properties"]["run_id"]["type"], "string")
        self.assertEqual(kit_tool.parameters["properties"]["run_id"]["type"], "string")

    async def test_exposes_m8_component_code_generation(self) -> None:
        tool = await mcp.get_tool("generate_component_code")

        self.assertEqual(tool.parameters["required"], ["run_id", "component_name"])
        self.assertEqual(tool.parameters["properties"]["component_name"]["type"], "string")

    async def test_exposes_private_defaults_and_run_deletion(self) -> None:
        create_tool = await mcp.get_tool("create_inspiration_kit")
        delete_tool = await mcp.get_tool("delete_run")

        self.assertTrue(create_tool.parameters["properties"]["privacy_mode"]["default"])
        self.assertEqual(create_tool.parameters["properties"]["retention_days"]["default"], 30)
        self.assertEqual(delete_tool.parameters["required"], ["run_id"])

    def test_equal_length_screenshot_and_url_lists_are_paired(self) -> None:
        screenshots = _primary_screenshots(
            ["D:/img-one.png", "D:/img-two.png"],
            ["https://example.com", "https://example.org"],
        )

        self.assertEqual(str(screenshots[0].source_url), "https://example.com/")
        self.assertEqual(str(screenshots[1].source_url), "https://example.org/")

    def test_screenshot_only_paths_remain_independent_sources(self) -> None:
        screenshots = _primary_screenshots(["D:/img-one.png", "D:/img-two.png"], [])

        self.assertEqual([screenshot.source_url for screenshot in screenshots], [None, None])


class ServerPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_ten_user_workflow_prompts(self) -> None:
        names = {prompt.name for prompt in await mcp._prompt_manager.list_prompts()}

        self.assertEqual(len(names), 10)
        self.assertEqual(
            names,
            {
                "clarify_idea_and_create_ui_kit",
                "create_landing_page_ui_kit",
                "create_saas_dashboard_ui_kit",
                "create_ai_product_ui_kit",
                "create_ecommerce_ui_kit",
                "create_portfolio_ui_kit",
                "create_education_platform_ui_kit",
                "create_mobile_app_marketing_ui_kit",
                "create_booking_service_ui_kit",
                "create_developer_tool_ui_kit",
            },
        )

    async def test_landing_page_prompt_contains_the_safe_end_to_end_workflow(self) -> None:
        rendered = create_landing_page_ui_kit(
            product="AI StudyMate",
            audience="college students",
            value="create revision plans and practise for exams",
            primary_action="Start free",
            screenshot_paths=["C:/references/one.png", "C:/references/two.png"],
        )

        self.assertIn("create_inspiration_kit", rendered)
        self.assertIn("get_status", rendered)
        self.assertIn("generate_reusable_kit", rendered)
        self.assertIn('"inspiration_screenshots"', rendered)
        self.assertIn("Do not reproduce source logos", rendered)


if __name__ == "__main__":
    unittest.main()
