"""Build a durable, poll-safe status report from persisted pipeline records."""

from __future__ import annotations

from collections.abc import Sequence

from inspo_mcp.models.run import RunRecord, RunStatus
from inspo_mcp.models.source import SourceRecord, SourceStatus
from inspo_mcp.schemas import SourceWarning
from inspo_mcp.schemas.run_status import RunStatusReport, SourceProgress
from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis


def build_run_status(
    run: RunRecord,
    sources: Sequence[SourceRecord],
    structures: Sequence[SiteStructureAnalysis],
    vision_analyses: Sequence[ScreenshotVisionAnalysis],
    *,
    kit_ready: bool,
) -> RunStatusReport:
    """Combine persisted records into one result without waiting for M5 work."""

    structures_by_url = {analysis.source_url: analysis for analysis in structures}
    vision_by_url = {analysis.source_url: analysis for analysis in vision_analyses}
    sources_by_url = {source.source_url: source for source in sources}
    source_urls = _ordered_source_urls(run, sources)
    source_progress = [
        _source_progress(
            source_url,
            sources_by_url.get(source_url),
            structures_by_url.get(source_url),
            vision_by_url.get(source_url),
        )
        for source_url in source_urls
    ]
    warnings = _warnings(run, sources, structures, vision_analyses)
    pending_vision = any(analysis.status == "pending" for analysis in vision_analyses)
    vision_by_source = {analysis.source_url: analysis for analysis in vision_analyses}
    complete_visual_evidence = bool(run.inspiration_urls) and all(
        vision_by_source.get(source_url) is not None
        and vision_by_source[source_url].status == "completed"
        for source_url in run.inspiration_urls
    )
    needs_vision_retry = not pending_vision and not complete_visual_evidence
    stage, progress, next_action = _run_summary(
        run,
        kit_ready=kit_ready,
        pending_vision=pending_vision,
        complete_visual_evidence=complete_visual_evidence,
        needs_vision_retry=needs_vision_retry,
    )
    is_terminal = kit_ready or run.status is RunStatus.FAILED
    return RunStatusReport(
        run_id=run.run_id,
        status=run.status.value,
        stage=stage,
        progress=progress,
        is_terminal=is_terminal,
        kit_ready=kit_ready,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_message=run.error_message,
        sources=source_progress,
        warnings=warnings,
        next_action=next_action,
    )


def _ordered_source_urls(run: RunRecord, sources: Sequence[SourceRecord]) -> list[str]:
    ordered = list(run.inspiration_urls)
    for source in sources:
        if source.source_url not in ordered:
            ordered.append(source.source_url)
    return ordered


def _source_progress(
    source_url: str,
    source: SourceRecord | None,
    structure: SiteStructureAnalysis | None,
    vision: ScreenshotVisionAnalysis | None,
) -> SourceProgress:
    if source is None:
        return SourceProgress(source_url=source_url, status="not_started")
    if source.status is SourceStatus.FAILED:
        return SourceProgress(
            source_url=source_url,
            status="capture_failed",
            capture_status=source.status.value,
            extraction_status=structure.status if structure else None,
            vision_status=vision.status if vision else None,
            message=source.error_message,
        )
    if vision is not None:
        return SourceProgress(
            source_url=source_url,
            status=vision.status,
            capture_status=source.status.value,
            extraction_status=structure.status if structure else None,
            vision_status=vision.status,
            message=vision.message,
        )
    if structure is not None:
        return SourceProgress(
            source_url=source_url,
            status=structure.status,
            capture_status=source.status.value,
            extraction_status=structure.status,
            message=structure.extraction_message,
        )
    return SourceProgress(
        source_url=source_url,
        status=source.status.value,
        capture_status=source.status.value,
        message=source.capture_note,
    )


def _warnings(
    run: RunRecord,
    sources: Sequence[SourceRecord],
    structures: Sequence[SiteStructureAnalysis],
    vision_analyses: Sequence[ScreenshotVisionAnalysis],
) -> list[SourceWarning]:
    warnings: list[SourceWarning] = []
    if run.error_message:
        warnings.append(SourceWarning(url=run.run_id, message=run.error_message))
    for source in sources:
        if source.status is SourceStatus.FAILED:
            warnings.append(
                SourceWarning(
                    url=source.source_url,
                    message=source.error_message or "Source capture failed.",
                )
            )
        elif source.status is SourceStatus.USER_PROVIDED and source.capture_note:
            warnings.append(SourceWarning(url=source.source_url, message=source.capture_note))
    for structure in structures:
        if structure.status == "unavailable":
            warnings.append(
                SourceWarning(
                    url=structure.source_url,
                    message=structure.extraction_message or "M4 structure extraction was unavailable.",
                )
            )
    for analysis in vision_analyses:
        if analysis.status in {"failed", "not_configured"}:
            warnings.append(
                SourceWarning(
                    url=analysis.source_url,
                    message=analysis.message or "M5 vision analysis was unavailable.",
                )
            )
    return _unique_warnings(warnings)


def _unique_warnings(warnings: Sequence[SourceWarning]) -> list[SourceWarning]:
    seen: set[tuple[str, str]] = set()
    result: list[SourceWarning] = []
    for warning in warnings:
        key = (warning.url, warning.message)
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result


def _run_summary(
    run: RunRecord,
    *,
    kit_ready: bool,
    pending_vision: bool,
    complete_visual_evidence: bool,
    needs_vision_retry: bool,
) -> tuple[str, int, str]:
    if kit_ready:
        return (
            "Reusable kit stored",
            100,
            "Call get_kit with this run_id to retrieve the saved non-mock kit.",
        )
    if run.status is RunStatus.FAILED:
        return (
            "Run failed",
            100,
            "Review error_message and warnings, then create a new run after correcting the problem.",
        )
    if pending_vision:
        return (
            "M5 visual analysis in progress",
            75,
            "Call get_status again after the local vision analysis finishes.",
        )
    if complete_visual_evidence:
        return (
            "M4 and M5 evidence ready for synthesis",
            90,
            "Call generate_reusable_kit with this run_id, then use get_kit for the durable result.",
        )
    if needs_vision_retry:
        return (
            "M5 visual evidence needs retry",
            80,
            "Fix the local vision setup if needed, then call retry_vision_analysis with this run_id. "
            "A final kit cannot be generated until every requested screenshot has completed M5 analysis.",
        )
    if run.status is RunStatus.COMPLETED:
        return (
            "Evidence collection finished without usable M5 visual evidence",
            90,
            "Configure a local vision model or provide usable screenshots, then create a new run.",
        )
    stages = {
        RunStatus.RECEIVED: ("Request received", 0),
        RunStatus.VALIDATING: ("Validating source URLs", 10),
        RunStatus.CAPTURING: ("Capturing source evidence", 30),
        RunStatus.EXTRACTING: ("Extracting page structure", 50),
        RunStatus.ANALYZING: ("Analyzing visual evidence", 75),
        RunStatus.GENERATING: ("Preparing reusable kit evidence", 85),
    }
    stage, progress = stages[run.status]
    return stage, progress, "Call get_status again to view the latest durable progress."
