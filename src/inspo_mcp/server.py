"""FastMCP entry point for InspoMCP."""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp import Context, FastMCP

from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.site_analyses import SiteAnalysisRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.schemas import (
    Framework,
    InspirationKit,
    InspirationRequest,
    ScreenshotFallback,
)
from inspo_mcp.services.capture import CaptureService, CaptureSettings
from inspo_mcp.services.extract import StructureExtractor
from inspo_mcp.services.run_manager import RunManager
from inspo_mcp.services.url_safety import validate_public_urls
from inspo_mcp.storage.capture_store import LocalCaptureStore
from inspo_mcp.storage.database import SqliteDatabase


mcp = FastMCP(
    "InspoMCP",
    instructions=(
        "Turn two or three public UI inspiration URLs into an original, reusable "
        "design starter kit. Start with create_inspiration_kit. Results in this "
        "version are intentionally mocked while the analysis pipeline is being "
        "built."
    ),
)


def _database_path() -> Path:
    """Allow deployments to supply a database path without changing tool code."""

    configured_path = os.getenv("INSPO_MCP_DATABASE_PATH")
    if configured_path:
        return Path(configured_path)
    return Path(__file__).resolve().parents[2] / "data" / "inspo_mcp.db"


def _capture_root() -> Path:
    """Allow deployments to supply a capture-artifact root without tool changes."""

    configured_path = os.getenv("INSPO_MCP_CAPTURE_ROOT")
    if configured_path:
        return Path(configured_path)
    return Path(__file__).resolve().parents[2] / "data" / "captures"


def _capture_settings() -> CaptureSettings:
    """Build a transparent, site-visible client identity and polite request pace."""

    user_agent = os.getenv("INSPO_MCP_USER_AGENT")
    if not user_agent:
        contact_email = os.getenv("INSPO_MCP_CONTACT_EMAIL")
        contact = f"mailto:{contact_email}" if contact_email else "configure INSPO_MCP_CONTACT_EMAIL"
        user_agent = f"InspoMCP/0.1 (contact: {contact})"

    configured_interval = os.getenv("INSPO_MCP_MIN_HOST_REQUEST_INTERVAL_SECONDS", "1.0")
    try:
        request_interval = max(0.0, float(configured_interval))
    except ValueError as error:
        raise ValueError(
            "INSPO_MCP_MIN_HOST_REQUEST_INTERVAL_SECONDS must be a non-negative number."
        ) from error
    return CaptureSettings(
        user_agent=user_agent,
        min_host_request_interval_seconds=request_interval,
    )


database = SqliteDatabase(_database_path())
capture_service = CaptureService(
    SourceRepository(database),
    LocalCaptureStore(_capture_root()),
    settings=_capture_settings(),
)
structure_extractor = StructureExtractor(SiteAnalysisRepository(database))
run_manager = RunManager(RunRepository(database), structure_extractor)


@mcp.tool
async def create_inspiration_kit(
    inspiration_urls: list[str],
    project_goal: str,
    ctx: Context,
    framework: Framework = "nextjs-tailwind",
    fallback_screenshots: list[ScreenshotFallback] | None = None,
) -> InspirationKit:
    """Return a five-part reusable design kit from two or three inspiration URLs."""

    request = InspirationRequest(
        inspiration_urls=inspiration_urls,
        project_goal=project_goal,
        framework=framework,
        fallback_screenshots=fallback_screenshots or [],
    )
    safe_urls = validate_public_urls(request.inspiration_urls)

    await ctx.info("Validated public URLs; capturing and extracting source evidence")
    await ctx.report_progress(progress=20, total=100)

    kit = await run_manager.create_captured_mock_kit(
        request,
        safe_urls,
        capture_service,
    )

    await ctx.report_progress(progress=100, total=100)

    return kit


if __name__ == "__main__":
    mcp.run()
