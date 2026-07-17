"""Tests for M6 evidence-derived reusable-kit synthesis."""

from __future__ import annotations

import unittest

from inspo_mcp.models.run import RunRecord, RunStatus, utc_now
from inspo_mcp.schemas.site_analysis import (
    CallToActionEvidence,
    CardEvidence,
    SiteStructureAnalysis,
)
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis
from inspo_mcp.services.kit_generator import EvidenceKitGenerator, EvidenceNotReadyError


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
            (_vision(self.run.run_id),),
        )

        self.assertFalse(kit.is_mock)
        self.assertEqual(kit.run_id, self.run.run_id)
        self.assertIn("gradient", " ".join(kit.design_direction.visual_style).lower())
        self.assertIn("HeaderNavigation", [card.name for card in kit.component_cards])
        self.assertIn("ContentCardGrid", [card.name for card in kit.component_cards])
        self.assertEqual(kit.design_tokens.colors["accent"], "#6D5DFB")
        self.assertTrue(kit.page_blueprint.sections)
        self.assertTrue(kit.build_tasks)

    def test_requires_at_least_one_completed_visual_analysis(self) -> None:
        pending = _vision(self.run.run_id).model_copy(update={"status": "pending"})

        with self.assertRaises(EvidenceNotReadyError):
            self.generator.generate(self.run, (), (pending,))

    def test_surfaces_failed_source_as_a_warning_without_discarding_completed_evidence(self) -> None:
        failed = _vision(self.run.run_id).model_copy(
            update={"source_url": "user-screenshot://failed", "status": "failed", "message": "Timed out."}
        )

        kit = self.generator.generate(self.run, (), (_vision(self.run.run_id), failed))

        self.assertEqual(len(kit.warnings), 1)
        self.assertEqual(kit.warnings[0].message, "Timed out.")


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


def _vision(run_id: str) -> ScreenshotVisionAnalysis:
    return ScreenshotVisionAnalysis(
        run_id=run_id,
        source_url="user-screenshot://one",
        status="completed",
        summary="An original visual direction.",
        visual_style=["Vibrant purple-to-blue gradient", "Large display typography"],
        layout_patterns=["Compact navigation", "Media-forward hero", "Feature card row"],
        component_patterns=["Search control", "Category tile", "Product card"],
        color_direction=["Purple accent over a light surface"],
        text_alignment="not_available",
        analyzed_at=utc_now(),
    )


if __name__ == "__main__":
    unittest.main()
