"""Regression checks for the hosted judge-demo packaging."""

from __future__ import annotations

import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
