"""FastMCP entry point for InspoMCP."""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp import Context, FastMCP

from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.schemas import Framework, InspirationKit, InspirationRequest, ScreenshotFallback
from inspo_mcp.services.capture import CaptureService
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


database = SqliteDatabase(_database_path())
run_manager = RunManager(RunRepository(database))
capture_service = CaptureService(
    SourceRepository(database),
    LocalCaptureStore(_capture_root()),
)


@mcp.tool
async def create_inspiration_kit(
    inspiration_urls: list[str],
    project_goal: str,
    fallback_screenshots: list[ScreenshotFallback],
    ctx: Context,
    framework: Framework = "nextjs-tailwind",
) -> InspirationKit:
    """Return a five-part reusable design kit from two or three inspiration URLs."""

    request = InspirationRequest(
        inspiration_urls=inspiration_urls,
        project_goal=project_goal,
        framework=framework,
        fallback_screenshots=fallback_screenshots,
    )
    safe_urls = validate_public_urls(request.inspiration_urls)

    await ctx.info("Validated public URLs; capturing source evidence")
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
