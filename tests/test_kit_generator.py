"""Tests for M6 evidence-derived reusable-kit synthesis."""

from __future__ import annotations

import unittest
from dataclasses import replace

from inspo_mcp.models.run import RunRecord, RunStatus, utc_now
from inspo_mcp.schemas.site_analysis import (
    CallToActionEvidence,
    CardEvidence,
    SiteStructureAnalysis,
)
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis
from inspo_mcp.services.kit_generator import (
    EvidenceIncompleteError,
    EvidenceKitGenerator,
)


class EvidenceKitGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = EvidenceKitGenerator()
        self.run = RunRecord(
            run_id="run_m6",
            status=RunStatus.COMPLETED,
            inspiration_urls=("user-screenshot://one", "user-screenshot://two"),
            project_goal="Build a modern AI developer tool landing page.",
            framework="nextjs-tailwind",
            created_at=utc_now(),
            updated_at=utc_now(),
        )

    def test_generates_non_mock_kit_from_completed_visual_evidence(self) -> None:
        kit = self.generator.generate(
            self.run,
            (_structure(self.run.run_id),),
            (_vision(self.run.run_id), _vision(self.run.run_id, source_url="user-screenshot://two")),
        )

        self.assertFalse(kit.is_mock)
        self.assertEqual(kit.run_id, self.run.run_id)
        self.assertIn("gradient", " ".join(kit.design_direction.visual_style).lower())
        self.assertIn("HeaderNavigation", [card.name for card in kit.component_cards])
        self.assertIn("ContentCardGrid", [card.name for card in kit.component_cards])
        self.assertEqual(kit.design_tokens.colors["accent"], "#6D5DFB")
        self.assertTrue(kit.page_blueprint.sections)
        self.assertTrue(kit.build_tasks)

    def test_requires_every_requested_visual_analysis_to_complete(self) -> None:
        pending = _vision(self.run.run_id).model_copy(update={"status": "pending"})

        with self.assertRaises(EvidenceIncompleteError) as error:
            self.generator.generate(self.run, (), (pending,))
        self.assertEqual(error.exception.missing_sources, self.run.inspiration_urls)

    def test_blocks_a_final_kit_when_one_source_failed(self) -> None:
        failed = _vision(self.run.run_id).model_copy(
            update={"source_url": "user-screenshot://two", "status": "failed", "message": "Timed out."}
        )

        with self.assertRaises(EvidenceIncompleteError) as error:
            self.generator.generate(self.run, (), (_vision(self.run.run_id), failed))
        self.assertEqual(error.exception.missing_sources, ("user-screenshot://two",))

    def test_finance_goal_generates_palette_derived_finance_components(self) -> None:
        finance_run = replace(
            self.run,
            project_goal="Build a personal finance landing page for savings and budgeting.",
        )
        first = _vision(
            finance_run.run_id,
            color_palette=["#5865F2", "#E2E5FF", "#111111", "#FFF200", "#EC3D9A"],
        )
        second = _vision(
            finance_run.run_id,
            source_url="user-screenshot://two",
            color_palette=["#E2E5FF", "#5865F2", "#111111", "#EC3D9A", "#FFF200"],
        )

        kit = self.generator.generate(finance_run, (), (first, second))

        component_names = [component.name for component in kit.component_cards]
        self.assertIn("SplitAccountCard", component_names)
        self.assertIn("FinanceDashboardPreview", component_names)
        self.assertIn("FAQAccordion", component_names)
        self.assertEqual(kit.design_tokens.colors["background"], "#5865F2")
        self.assertEqual(kit.design_tokens.colors["surface"], "#E2E5FF")
        self.assertEqual(kit.design_tokens.colors["accent"], "#FFF200")
        self.assertEqual(kit.design_tokens.radius["button"], "999px")


def _structure(run_id: str) -> SiteStructureAnalysis:
    return SiteStructureAnalysis(
        run_id=run_id,
        source_url="user-screenshot://one",
        status="extracted",
        cards=[
            CardEvidence(
                title="A source card title that must not enter the generated kit.",
                line_number=1,
                confidence="high",
            )
        ],
        calls_to_action=[
            CallToActionEvidence(
                label="A source CTA that must not enter the generated kit.",
                line_number=2,
                confidence="high",
            )
        ],
        extracted_at=utc_now(),
    )


def _vision(
    run_id: str,
    *,
    source_url: str = "user-screenshot://one",
    color_palette: list[str] | None = None,
) -> ScreenshotVisionAnalysis:
    return ScreenshotVisionAnalysis(
        run_id=run_id,
        source_url=source_url,
        status="completed",
        summary="An original visual direction.",
        visual_style=["Vibrant purple-to-blue gradient", "Large display typography", "Rounded pill controls"],
        layout_patterns=["Compact navigation", "Media-forward hero", "Feature card row"],
        component_patterns=["Search control", "Category tile", "Product card"],
        color_direction=["Purple accent over a light surface"],
        color_palette=color_palette or [],
        text_alignment="not_available",
        analyzed_at=utc_now(),
    )


if __name__ == "__main__":
    unittest.main()
