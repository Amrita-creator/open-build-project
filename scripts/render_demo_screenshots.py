"""Render self-authored judge-demo HTML pages into fixed screenshot inputs."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


DEMO_ROOT = Path(__file__).resolve().parents[1] / "demo"
PAGES = ("aurora-landing", "ops-dashboard")


def main() -> None:
    """Create deterministic PNG evidence files during the Docker image build."""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
            for name in PAGES:
                source = DEMO_ROOT / f"{name}.html"
                destination = DEMO_ROOT / f"{name}.png"
                page.goto(source.as_uri(), wait_until="networkidle")
                page.screenshot(path=str(destination), full_page=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
