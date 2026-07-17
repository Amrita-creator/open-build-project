"""M8 tests for focused code generation from persisted M6 component cards."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inspo_mcp.repositories.kits import KitRepository
from inspo_mcp.schemas import (
    ComponentCard,
    DesignDirection,
    DesignTokens,
    InspirationKit,
    PageBlueprint,
)
from inspo_mcp.services.component_codegen import ComponentCodeGenerator, ComponentNotFoundError
from inspo_mcp.storage.database import SqliteDatabase
from inspo_mcp.tools.generate_component_code import generate_component_code_for_run


class ComponentCodeGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kit = _kit()
        self.generator = ComponentCodeGenerator()

    def test_generates_a_tailwind_hero_from_its_component_card(self) -> None:
        result = self.generator.generate(
            self.kit,
            framework="nextjs-tailwind",
            component_name="HeroPanel",
        )

        self.assertEqual(result.component_name, "HeroPanel")
        self.assertEqual(result.dependencies, ["react", "tailwindcss"])
        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.files[0].path, "components/HeroPanel.tsx")
        self.assertIn("export function HeroPanel", result.files[0].content)
        self.assertIn("text-[#6D5DFB]", result.files[0].content)
        self.assertIn("Use one page-level heading.", result.implementation_notes)

    def test_generates_react_and_css_files_for_a_card_grid(self) -> None:
        result = self.generator.generate(
            self.kit,
            framework="react-css",
            component_name="contentcardgrid",
        )

        self.assertEqual(result.component_name, "ContentCardGrid")
        self.assertEqual([item.path for item in result.files], [
            "components/ContentCardGrid.tsx",
            "components/content-card-grid.css",
        ])
        self.assertIn("import type { ReactNode }", result.files[0].content)
        self.assertIn("--accent: #6D5DFB", result.files[1].content)

    def test_generates_framework_agnostic_html_and_css_for_one_action(self) -> None:
        result = self.generator.generate(
            self.kit,
            framework="framework-agnostic",
            component_name="PrimaryAction",
        )

        self.assertEqual(result.dependencies, [])
        self.assertEqual([item.language for item in result.files], ["html", "css"])
        self.assertIn("{{label}}", result.files[0].content)
        self.assertIn("min-height: 2.75rem", result.files[1].content)

    def test_rejects_a_component_that_is_not_in_the_saved_kit(self) -> None:
        with self.assertRaises(ComponentNotFoundError) as error:
            self.generator.generate(
                self.kit,
                framework="nextjs-tailwind",
                component_name="InventedComponent",
            )

        self.assertIn("Available components", str(error.exception))

    def test_tool_helper_loads_the_durable_kit_before_generating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = KitRepository(SqliteDatabase(Path(temporary_directory) / "m8.db"))
            repository.upsert(self.kit)

            result = generate_component_code_for_run(
                repository,
                run_id=self.kit.run_id,
                framework="nextjs-tailwind",
                component_name="PrimaryAction",
            )

        self.assertEqual(result.run_id, self.kit.run_id)
        self.assertIn("export function PrimaryAction", result.files[0].content)


def _kit() -> InspirationKit:
    return InspirationKit(
        run_id="run_m8",
        design_direction=DesignDirection(
            summary="Original reusable visual direction.",
            visual_style=["strong hierarchy"],
            principles=["Prioritize one action."],
            avoid=["Do not copy source branding."],
        ),
        page_blueprint=PageBlueprint(summary="Original page blueprint.", sections=[]),
        component_cards=[
            ComponentCard(
                name="HeroPanel",
                purpose="Lead with one focused product promise.",
                props=["eyebrow", "heading", "body", "media", "alignment"],
                variants=["split", "centered"],
                content_slots=["eyebrow", "heading", "body", "actions", "media"],
                responsive_behavior="Stack content and media on narrow screens.",
                accessibility_notes=["Use one page-level heading."],
            ),
            ComponentCard(
                name="PrimaryAction",
                purpose="Make the preferred next step obvious.",
                props=["label", "href", "icon", "size", "variant"],
                variants=["primary", "secondary"],
                content_slots=["label"],
                responsive_behavior="Keep a minimum touch target.",
                accessibility_notes=["Preserve visible keyboard focus."],
            ),
            ComponentCard(
                name="ContentCardGrid",
                purpose="Present repeated value in a scannable layout.",
                props=["items", "columns", "card_variant", "section_title"],
                variants=["feature"],
                content_slots=["title", "description", "action"],
                responsive_behavior="Use one column on small screens.",
                accessibility_notes=["Keep card actions understandable out of context."],
            ),
        ],
        design_tokens=DesignTokens(
            colors={
                "background": "#F8FAFC",
                "surface": "#FFFFFF",
                "text": "#0F172A",
                "muted_text": "#475569",
                "accent": "#6D5DFB",
            },
            typography={"display": "4rem", "heading": "2rem", "body": "1rem"},
            spacing={"section": "6rem", "card": "1.5rem", "stack": "1rem"},
            radius={"card": "1rem", "button": "0.75rem"},
            shadow={"card": "0 12px 32px rgb(15 23 42 / 0.12)"},
        ),
        build_tasks=[],
        is_mock=False,
    )


if __name__ == "__main__":
    unittest.main()
