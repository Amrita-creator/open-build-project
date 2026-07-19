"""FastMCP entry point for InspoMCP."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from inspo_mcp.repositories.kits import KitRepository
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.site_analyses import SiteAnalysisRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas import (
    ComponentCodeGeneration,
    Framework,
    InspirationKit,
    InspirationRequest,
    InspirationScreenshot,
    KitLookup,
    RunStatusReport,
    ScreenshotVisionAnalysis,
    ScreenshotFallback,
)
from inspo_mcp.services.capture import CaptureService, CaptureSettings
from inspo_mcp.services.extract import StructureExtractor
from inspo_mcp.services.hosted_demo import HostedJudgeDemoService
from inspo_mcp.services.kit_generator import EvidenceKitGenerator
from inspo_mcp.services.privacy import (
    mask_component_generation,
    mask_kit,
    mask_run_status,
    mask_vision_analysis,
    mask_warnings,
    privacy_guidance,
    redact_text,
    reject_request_secrets,
)
from inspo_mcp.services.run_manager import RunManager
from inspo_mcp.services.url_safety import validate_public_urls
from inspo_mcp.services.vision import VisionAnalysisService, configured_vision_analyzer
from inspo_mcp.observability.telemetry import traced_tool
from inspo_mcp.prompts import register_user_workflow_prompts
from inspo_mcp.storage.capture_store import LocalCaptureStore
from inspo_mcp.storage.database import SqliteDatabase
from inspo_mcp.tools.get_kit import build_kit_lookup
from inspo_mcp.tools.get_status import build_run_status
from inspo_mcp.tools.generate_component_code import generate_component_code_for_run


mcp = FastMCP(
    "InspoMCP",
    instructions=(
        "Turn two or three UI inspiration screenshots and/or public URLs into an "
        "original, reusable design starter kit. Screenshots are primary visual "
        "evidence; URLs are optional safe enrichment. Start with create_inspiration_kit. "
        "Poll get_status after M5. Call generate_reusable_kit only when every requested "
        "screenshot has completed M5; if status says retry is needed, call "
        "retry_vision_analysis instead. Never invent a final kit from partial visual evidence. "
        "For a hosted judge check that cannot run Ollama, use run_hosted_demo: it uses "
        "precomputed evidence from bundled self-authored screenshots and must be described as a demo."
    ),
)
register_user_workflow_prompts(mcp)
logger = logging.getLogger(__name__)


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


def _primary_screenshots(
    image_paths: list[str],
    inspiration_urls: list[str],
) -> list[InspirationScreenshot]:
    """Turn the Inspector-friendly path list into internal screenshot evidence.

    When callers provide the same number of URLs and screenshot paths, entries
    are paired by their order. This preserves URL attribution without making
    the common screenshot-only Inspector input harder to enter.
    """

    paired_urls = inspiration_urls if len(image_paths) == len(inspiration_urls) else []
    return [
        InspirationScreenshot(
            image_path=image_path,
            source_url=paired_urls[index] if paired_urls else None,
        )
        for index, image_path in enumerate(image_paths)
    ]


database = SqliteDatabase(_database_path())
source_repository = SourceRepository(database)
capture_store = LocalCaptureStore(_capture_root())
capture_service = CaptureService(
    source_repository,
    capture_store,
    settings=_capture_settings(),
)
site_analysis_repository = SiteAnalysisRepository(database)
structure_extractor = StructureExtractor(site_analysis_repository)
vision_repository = VisionAnalysisRepository(database)
vision_service = VisionAnalysisService(
    vision_repository,
    configured_vision_analyzer(),
)
kit_repository = KitRepository(database)
run_repository = RunRepository(database)
run_manager = RunManager(
    run_repository,
    structure_extractor,
    vision_service,
    source_repository=source_repository,
    site_analysis_repository=site_analysis_repository,
    vision_repository=vision_repository,
)
kit_generator = EvidenceKitGenerator()
hosted_judge_demo = HostedJudgeDemoService(
    run_repository,
    source_repository,
    vision_repository,
    kit_repository,
    kit_generator,
)
background_vision_tasks: dict[str, asyncio.Task[None]] = {}


def _cleanup_expired_runs() -> tuple[str, ...]:
    """Remove expired database and managed-capture artifacts at a safe boundary."""

    run_ids = run_manager.delete_expired_runs(datetime.now(timezone.utc).isoformat())
    for run_id in run_ids:
        task = background_vision_tasks.pop(run_id, None)
        if task is not None and not task.done():
            task.cancel()
        capture_store.delete_run(run_id)
    return run_ids


def _delete_run_artifacts(run_id: str) -> None:
    """Cancel queued work and remove all managed artifacts for one run."""

    task = background_vision_tasks.pop(run_id, None)
    if task is not None and not task.done():
        task.cancel()
    run_manager.delete_run(run_id)
    capture_store.delete_run(run_id)


async def _run_background_vision(run_id: str) -> None:
    """Complete M5 work after the primary MCP response has been returned."""

    try:
        await run_manager.analyze_deferred_vision(run_id)
    except Exception:
        logger.exception("Background M5 vision analysis failed for run %s", run_id)


def _schedule_background_vision(run_id: str) -> None:
    """Keep a reference to the task so background M5 work is not discarded."""

    existing = background_vision_tasks.get(run_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_run_background_vision(run_id), name=f"inspo-m5-{run_id}")
    background_vision_tasks[run_id] = task
    task.add_done_callback(lambda _: background_vision_tasks.pop(run_id, None))


@mcp.tool
@traced_tool("create_inspiration_kit")
async def create_inspiration_kit(
    project_goal: str,
    ctx: Context,
    inspiration_urls: Annotated[
        list[str],
        Field(
            description="Optional public inspiration URLs. Leave as an empty array when using screenshots only.",
            examples=[["https://example.com", "https://example.org"]],
        ),
    ] = [],
    framework: Framework = "nextjs-tailwind",
    inspiration_screenshots: Annotated[
        list[str],
        Field(
            description=(
                "Primary screenshot inputs. Enter an array of two or three distinct absolute image paths. "
                "Use forward slashes in Windows paths (for example C:/Users/Amrita/Pictures/reference.png). "
                "When this array has the same length as inspiration_urls, the path and URL at each index are paired."
            ),
            examples=[
                [
                    "C:/Users/Amrita/Pictures/reference-one.png",
                    "C:/Users/Amrita/Pictures/reference-two.png",
                ]
            ],
        ),
    ] = [],
    fallback_screenshots: Annotated[
        list[ScreenshotFallback],
        Field(
            description=(
                "Legacy URL-mapped fallback screenshots. Leave as an empty array for new screenshot-first calls."
            ),
        ),
    ] = [],
    privacy_mode: Annotated[
        bool,
        Field(
            description=(
                "Keep source identities private in MCP responses. Defaults to true; "
                "captured text is redacted in either mode."
            )
        ),
    ] = True,
    retention_days: Annotated[
        int,
        Field(
            ge=1,
            le=90,
            description="Keep durable run data and evidence for this many days (1-90; default 30).",
        ),
    ] = 30,
) -> InspirationKit:
    """Return a reusable kit from two or three screenshots and/or public URLs."""

    _cleanup_expired_runs()
    reject_request_secrets(project_goal, inspiration_urls)
    safe_goal = redact_text(project_goal)
    screenshots = _primary_screenshots(inspiration_screenshots, inspiration_urls)
    request = InspirationRequest(
        inspiration_urls=inspiration_urls,
        project_goal=safe_goal.text,
        framework=framework,
        privacy_mode=privacy_mode,
        retention_days=retention_days,
        inspiration_screenshots=screenshots,
        fallback_screenshots=fallback_screenshots,
    )
    safe_urls = validate_public_urls(request.inspiration_urls)

    if safe_goal.counts:
        await ctx.info("Sensitive text was redacted from the product goal before processing.")
    await ctx.info("Validated sources; accepting screenshots and safely enriching public URLs")
    await ctx.report_progress(progress=20, total=100)

    kit = await run_manager.create_captured_mock_kit(
        request,
        safe_urls,
        capture_service,
        defer_vision=True,
    )

    _schedule_background_vision(kit.run_id)
    await ctx.info(
        f"M5 vision is running in the background for run {kit.run_id}; "
        "use get_vision_analyses to poll its status."
    )
    await ctx.report_progress(progress=100, total=100)

    return mask_kit(run_manager.get_run(kit.run_id), kit)


@mcp.tool
@traced_tool("run_hosted_demo")
async def run_hosted_demo(
    ctx: Context,
    project_goal: Annotated[
        str,
        Field(
            min_length=10,
            max_length=500,
            description=(
                "The product goal to apply to the bundled self-authored judge-demo evidence. "
                "This tool does not inspect user-provided sources."
            ),
        ),
    ] = "Build a calm operations workspace for a product team.",
    framework: Framework = "nextjs-tailwind",
    privacy_mode: bool = True,
    retention_days: Annotated[
        int,
        Field(
            ge=1,
            le=90,
            description="Keep this demo run for this many days (1-90; default 7).",
        ),
    ] = 7,
) -> InspirationKit:
    """Return a completed kit from transparent, precomputed self-authored demo evidence.

    Use this only to verify the hosted MCP service when a hosted Ollama model is
    unavailable. It never analyzes caller screenshots or URLs.
    """

    _cleanup_expired_runs()
    reject_request_secrets(project_goal, [])
    safe_goal = redact_text(project_goal)
    if safe_goal.counts:
        await ctx.info("Sensitive text was redacted from the product goal before processing.")
    await ctx.info(
        "Creating a completed hosted demo from precomputed evidence for two self-authored "
        "screenshots; Ollama will not be called."
    )
    kit = hosted_judge_demo.create(
        project_goal=safe_goal.text,
        framework=framework,
        privacy_mode=privacy_mode,
        retention_days=retention_days,
    )
    await ctx.info(f"Hosted demo run {kit.run_id} is complete and stored.")
    return mask_kit(run_manager.get_run(kit.run_id), kit)


@mcp.tool
@traced_tool("get_vision_analyses")
async def get_vision_analyses(
    run_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Run ID returned by create_inspiration_kit.",
        ),
    ],
    ctx: Context,
) -> list[ScreenshotVisionAnalysis]:
    """Return pending or completed M5 visual analyses for one inspiration-kit run."""

    run = run_manager.get_run(run_id)
    if run_manager.has_resumable_vision(run_id):
        _schedule_background_vision(run_id)
    analyses = list(vision_repository.list_for_run(run_id))
    await ctx.info(f"Retrieved {len(analyses)} M5 vision result(s) for run {run_id}.")
    return [mask_vision_analysis(run, analysis) for analysis in analyses]


@mcp.tool
@traced_tool("retry_vision_analysis")
async def retry_vision_analysis(
    run_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Run ID whose incomplete M5 screenshot analyses should be queued again.",
        ),
    ],
    ctx: Context,
    source_urls: Annotated[
        list[str],
        Field(
            description=(
                "Optional source identifiers from get_status. Leave empty to retry every source "
                "that has not completed M5 analysis."
            )
        ),
    ] = [],
) -> RunStatusReport:
    """Retry incomplete M5 screenshot analyses before generating a final reusable kit."""

    queued = run_manager.retry_vision_analysis(run_id, source_urls)
    _schedule_background_vision(run_id)
    await ctx.info(f"Queued {len(queued)} M5 screenshot analysis retry or retries for run {run_id}.")
    return mask_run_status(run_manager.get_run(run_id), _status_report(run_id))


def _status_report(run_id: str) -> RunStatusReport:
    """Read the latest durable M3-M6 state without relying on memory-only state."""

    run = run_manager.get_run(run_id)
    return build_run_status(
        run,
        source_repository.list_for_run(run_id),
        site_analysis_repository.list_for_run(run_id),
        vision_repository.list_for_run(run_id),
        kit_ready=kit_repository.get_optional(run_id) is not None,
    )


@mcp.tool
@traced_tool("get_status")
async def get_status(
    run_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Run ID returned by create_inspiration_kit.",
        ),
    ],
    ctx: Context,
) -> RunStatusReport:
    """Return durable run progress, per-source results, warnings, and next action."""

    run = run_manager.get_run(run_id)
    if run_manager.has_resumable_vision(run_id):
        _schedule_background_vision(run_id)
    report = _status_report(run_id)
    await ctx.info(
        f"Run {run_id} is {report.status} at {report.progress}%: {report.stage}."
    )
    return mask_run_status(run, report)


@mcp.tool
@traced_tool("generate_reusable_kit")
async def generate_reusable_kit(
    run_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Run ID whose M5 analysis has at least one completed result.",
        ),
    ],
    ctx: Context,
) -> InspirationKit:
    """Synthesize a non-mock reusable UI kit from completed M4/M5 evidence."""

    run = run_manager.get_run(run_id)
    kit = kit_repository.upsert(kit_generator.generate(
        run,
        site_analysis_repository.list_for_run(run_id),
        vision_repository.list_for_run(run_id),
    ))
    await ctx.info(f"Generated and stored evidence-derived reusable kit for run {run_id}.")
    return mask_kit(run, kit)


@mcp.tool
@traced_tool("get_kit")
async def get_kit(
    run_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Run ID returned by create_inspiration_kit.",
        ),
    ],
    ctx: Context,
) -> KitLookup:
    """Retrieve durable M6 output; when ``state`` is ``ready``, the kit is in ``kit``."""

    run = run_manager.get_run(run_id)
    report = _status_report(run_id)
    lookup = build_kit_lookup(report, kit_repository.get_optional(run_id))
    await ctx.info(f"Kit retrieval for run {run_id}: {lookup.state}.")
    return lookup.model_copy(
        update={
            "kit": mask_kit(run, lookup.kit) if lookup.kit is not None else None,
            "warnings": mask_warnings(run, lookup.warnings),
        }
    )


@mcp.tool
@traced_tool("generate_component_code")
async def generate_component_code(
    run_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Run ID whose non-mock M6 kit has already been generated.",
        ),
    ],
    component_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            description="Exact component-card name, such as HeroPanel or PrimaryAction.",
        ),
    ],
    ctx: Context,
) -> ComponentCodeGeneration:
    """Generate original, framework-specific starter code for one M6 component."""

    run = run_manager.get_run(run_id)
    generation = generate_component_code_for_run(
        kit_repository,
        run_id=run_id,
        framework=run.framework,
        component_name=component_name,
    )
    await ctx.info(
        f"Generated {run.framework} starter code for {generation.component_name} in run {run_id}."
    )
    return mask_component_generation(run, generation)


@mcp.tool
@traced_tool("delete_run")
async def delete_run(
    run_id: Annotated[
        str,
        Field(min_length=1, description="Run ID whose database and managed capture artifacts should be deleted."),
    ],
    ctx: Context,
) -> dict[str, str]:
    """Permanently delete one run and its captured evidence before retention expiry."""

    _delete_run_artifacts(run_id)
    await ctx.info(f"Deleted run {run_id} and its managed capture artifacts.")
    return {"run_id": run_id, "state": "deleted"}


@mcp.resource(
    "inspo://guides/privacy-and-data-handling",
    name="Privacy and data handling",
    description="How InspoMCP handles credentials, personal data, retention, and deletion.",
    mime_type="text/markdown",
)
def get_privacy_guidance() -> str:
    """Expose static privacy guidance without adding it to each tool response."""

    return privacy_guidance()


@mcp.resource(
    "inspo://runs/{run_id}/privacy-report",
    name="Run privacy report",
    description="Aggregate redaction and retention metadata without source identities.",
    mime_type="application/json",
)
def get_privacy_report(run_id: str) -> str:
    """Expose aggregate redaction and retention information for one run."""

    run = run_manager.get_run(run_id)
    redaction_counts: Counter[str] = Counter()
    for source in source_repository.list_for_run(run_id):
        redaction_counts.update(source.redaction_counts)
    return json.dumps(
        {
            "run_id": run.run_id,
            "privacy_mode": run.privacy_mode,
            "source_count": len(run.inspiration_urls),
            "redaction_counts": dict(redaction_counts),
            "retention_expires_at": run.retention_expires_at,
            "deletion_tool": "delete_run",
            "single_tenant_warning": (
                "Authentication is a shared bearer token. Do not use this service for multiple users "
                "until per-user authentication and authorization are implemented."
            ),
        },
        sort_keys=True,
    )


if __name__ == "__main__":
    mcp.run()
