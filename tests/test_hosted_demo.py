"""Regression checks for the hosted judge-demo packaging."""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from inspo_mcp.models.run import RunStatus
from inspo_mcp.repositories.kits import KitRepository
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.services.hosted_demo import HostedJudgeDemoService
from inspo_mcp.services.kit_generator import EvidenceKitGenerator
from inspo_mcp.storage.database import SqliteDatabase
from inspo_mcp.tools.get_status import build_run_status


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HostedDemoPackagingTests(unittest.TestCase):
    def test_demo_screenshots_are_valid_png_files(self) -> None:
        for name in ("aurora-landing", "ops-dashboard"):
            image = PROJECT_ROOT / "demo" / f"{name}.png"
            self.assertTrue(image.is_file(), f"Missing bundled judge-demo image: {image}")
            self.assertGreater(image.stat().st_size, 10_000)
            self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_docker_build_renders_and_copies_demo_assets(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY demo ./demo", dockerfile)
        self.assertIn("render_demo_screenshots.py", dockerfile)

    def test_railway_config_uses_docker_and_health_check(self) -> None:
        config = (PROJECT_ROOT / "railway.toml").read_text(encoding="utf-8")

        self.assertIn('builder = "DOCKERFILE"', config)
        self.assertIn('healthcheckPath = "/healthz"', config)


class HostedJudgeDemoServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = SqliteDatabase(Path(self._temporary_directory.name) / "hosted-demo.db")
        self.runs = RunRepository(self.database)
        self.sources = SourceRepository(self.database)
        self.vision = VisionAnalysisRepository(self.database)
        self.kits = KitRepository(self.database)
        self.service = HostedJudgeDemoService(
            self.runs,
            self.sources,
            self.vision,
            self.kits,
            EvidenceKitGenerator(),
            demo_root=PROJECT_ROOT / "demo",
        )

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_creates_a_durable_completed_non_mock_kit_from_disclosed_demo_evidence(self) -> None:
        kit = self.service.create(
            project_goal="Build a calm finance workspace for small business owners.",
            framework="nextjs-tailwind",
            privacy_mode=True,
            retention_days=7,
        )
        run = self.runs.get(kit.run_id)
        sources = self.sources.list_for_run(kit.run_id)
        analyses = self.vision.list_for_run(kit.run_id)
        report = build_run_status(
            run,
            sources,
            (),
            analyses,
            kit_ready=self.kits.get_optional(kit.run_id) is not None,
        )

        self.assertTrue(kit.run_id.startswith("demo_"))
        self.assertFalse(kit.is_mock)
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(source.source_url.startswith("demo://") for source in sources))
        self.assertTrue(all(analysis.status == "completed" for analysis in analyses))
        self.assertTrue(all("precomputed" in (analysis.message or "").lower() for analysis in analyses))
        self.assertTrue(any("does not run ollama" in warning.message.lower() for warning in kit.warnings))
        self.assertEqual(report.progress, 100)
        self.assertTrue(report.kit_ready)
        self.assertTrue(any(card.name == "FinanceHero" for card in kit.component_cards))


if __name__ == "__main__":
    unittest.main()
