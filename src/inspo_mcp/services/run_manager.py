"""Orchestrate the lifecycle of an inspiration-kit run."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from inspo_mcp.models.run import RunRecord, RunStatus
from inspo_mcp.models.source import SourceRecord, SourceStatus
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.site_analyses import SiteAnalysisRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas import (
    InspirationKit,
    InspirationRequest,
    ScreenshotVisionAnalysis,
    SourceWarning,
)
from inspo_mcp.services.capture import CaptureService
from inspo_mcp.services.extract import StructureExtractor
from inspo_mcp.services.mock_artifacts import create_mock_kit
from inspo_mcp.services.url_safety import SafeUrl
from inspo_mcp.services.vision import VisionAnalysisService
from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis


@dataclass(frozen=True)
class DeferredVisionWork:
    """In-memory M5 work retained while the local development server stays alive."""

    sources: tuple[SourceRecord, ...]
    text_analyses: tuple[SiteStructureAnalysis, ...]


class RunManager:
    """Coordinates durable run state without coupling tools to SQLite."""

    def __init__(
        self,
        repository: RunRepository,
        extraction_service: StructureExtractor | None = None,
        vision_service: VisionAnalysisService | None = None,
        *,
        source_repository: SourceRepository | None = None,
        site_analysis_repository: SiteAnalysisRepository | None = None,
        vision_repository: VisionAnalysisRepository | None = None,
    ) -> None:
        self._repository = repository
        self._extraction_service = extraction_service
        self._vision_service = vision_service
        self._source_repository = source_repository
        self._site_analysis_repository = site_analysis_repository
        self._vision_repository = vision_repository
        self._deferred_vision_work: dict[str, DeferredVisionWork] = {}

    def create_mock_kit(self, request: InspirationRequest) -> InspirationKit:
        """Persist each stage of the existing mock pipeline and return its kit."""

        run = self._repository.create(RunRecord.new(request))
        try:
            run = self._repository.update(run.with_status(RunStatus.VALIDATING))
            run = self._repository.update(run.with_status(RunStatus.GENERATING))
            kit = create_mock_kit(request, run_id=run.run_id)
            self._repository.update(run.with_status(RunStatus.COMPLETED))
            return kit
        except Exception as error:
            self._repository.update(
                run.with_status(RunStatus.FAILED, error_message=str(error))
            )
            raise

    def get_run(self, run_id: str) -> RunRecord:
        """Return persisted metadata for later MCP retrieval tools."""

        return self._repository.get(run_id)

    def delete_run(self, run_id: str) -> None:
        """Delete durable state and queued in-memory work for one run."""

        self._deferred_vision_work.pop(run_id, None)
        self._repository.delete(run_id)

    def delete_expired_runs(self, now: str) -> tuple[str, ...]:
        """Remove expired durable state and any queued work for those runs."""

        run_ids = self._repository.delete_expired(now)
        for run_id in run_ids:
            self._deferred_vision_work.pop(run_id, None)
        return run_ids

    def has_resumable_vision(self, run_id: str) -> bool:
        """Report whether durable pending M5 work can be resumed after a restart."""

        if run_id in self._deferred_vision_work:
            return True
        if self._vision_repository is None or self._source_repository is None:
            return False
        return bool(self._source_repository.list_for_run(run_id)) and any(
            analysis.status == "pending"
            for analysis in self._vision_repository.list_for_run(run_id)
        )

    def retry_vision_analysis(
        self,
        run_id: str,
        source_urls: Sequence[str] = (),
    ) -> tuple[ScreenshotVisionAnalysis, ...]:
        """Queue failed or unavailable M5 sources again without discarding completed evidence."""

        if (
            self._vision_service is None
            or self._source_repository is None
            or self._site_analysis_repository is None
            or self._vision_repository is None
        ):
            raise RuntimeError("M5 retry requires the configured source and vision repositories.")
        run = self._repository.get(run_id)
        analyses_by_url = {
            analysis.source_url: analysis for analysis in self._vision_repository.list_for_run(run_id)
        }
        requested_urls = tuple(source_urls) or tuple(
            source_url
            for source_url in run.inspiration_urls
            if analyses_by_url.get(source_url) is None
            or analyses_by_url[source_url].status != "completed"
        )
        unknown_urls = set(requested_urls) - set(run.inspiration_urls)
        if unknown_urls:
            raise ValueError("Retry sources must belong to the original inspiration-kit run.")
        if not requested_urls:
            raise ValueError("All requested screenshot analyses are already complete.")

        sources_by_url = {
            source.source_url: source for source in self._source_repository.list_for_run(run_id)
        }
        missing_sources = [source_url for source_url in requested_urls if source_url not in sources_by_url]
        if missing_sources:
            raise ValueError("Retry sources are missing their durable screenshot evidence.")
        sources = tuple(sources_by_url[source_url] for source_url in requested_urls)
        pending = self._vision_service.mark_pending(sources)
        self._deferred_vision_work[run_id] = DeferredVisionWork(
            sources=sources,
            text_analyses=self._site_analysis_repository.list_for_run(run_id),
        )
        self._repository.update(run.with_status(RunStatus.ANALYZING))
        return pending

    async def create_captured_mock_kit(
        self,
        request: InspirationRequest,
        safe_urls: tuple[SafeUrl, ...],
        capture_service: CaptureService,
        *,
        defer_vision: bool = False,
    ) -> InspirationKit:
        """Prepare M3/M4 evidence, then run M5 now or queue it for background work."""

        run = self._repository.create(RunRecord.new(request))
        try:
            run = self._repository.update(run.with_status(RunStatus.VALIDATING))
            run = self._repository.update(run.with_status(RunStatus.CAPTURING))
            primary_sources = await capture_service.capture_primary_screenshots(
                run.run_id,
                request.inspiration_screenshots,
            )
            primary_url_sources = tuple(
                source for source in safe_urls if source.url in request.primary_screenshot_url_keys
            )
            enriched_primary_sources = await capture_service.enrich_primary_screenshots(
                run.run_id,
                primary_url_sources,
            )
            url_sources = await capture_service.capture_sources(
                run.run_id,
                tuple(source for source in safe_urls if source.url not in request.primary_screenshot_url_keys),
                fallback_screenshots=request.fallback_screenshot_map,
            )
            source_by_identifier = {
                source.source_url: source for source in (*primary_sources, *enriched_primary_sources, *url_sources)
            }
            sources = tuple(
                source_by_identifier[identifier]
                for identifier in request.source_identifiers
                if identifier in source_by_identifier
            )
            analyses = ()
            if self._extraction_service is not None:
                run = self._repository.update(run.with_status(RunStatus.EXTRACTING))
                analyses = self._extraction_service.extract_and_store(sources)
            vision_analyses = ()
            if self._vision_service is not None:
                run = self._repository.update(run.with_status(RunStatus.ANALYZING))
                if defer_vision:
                    vision_analyses = self._vision_service.mark_pending(sources)
                    self._deferred_vision_work[run.run_id] = DeferredVisionWork(
                        sources=sources,
                        text_analyses=tuple(analyses),
                    )
                else:
                    vision_analyses = await self._vision_service.analyze_and_store(sources, analyses)
            run = self._repository.update(run.with_status(RunStatus.GENERATING))

            kit = create_mock_kit(request, run_id=run.run_id)
            warnings: list[SourceWarning] = []
            for source in sources:
                if source.status is SourceStatus.FAILED:
                    warnings.append(
                        SourceWarning(
                            url=source.source_url,
                            message=(
                                (source.error_message or "URL evidence capture failed.")
                                + " Provide an inspiration_screenshot for this source to use M5 vision."
                            ),
                        )
                    )
                elif source.status is SourceStatus.USER_PROVIDED:
                    warnings.append(
                        SourceWarning(
                            url=source.source_url,
                            message=source.capture_note
                            or "User-provided screenshot evidence was used.",
                        )
                    )
            completed_vision_urls = {
                analysis.source_url
                for analysis in vision_analyses
                if analysis.status == "completed"
            }
            vision_urls = {analysis.source_url for analysis in vision_analyses}
            for analysis in analyses:
                if (
                    analysis.status != "extracted"
                    and analysis.source_url not in completed_vision_urls
                    and not (
                        analysis.status == "awaiting_vision" and analysis.source_url in vision_urls
                    )
                ):
                    warnings.append(
                        SourceWarning(
                            url=analysis.source_url,
                            message=analysis.extraction_message
                            or "Page-structure extraction was unavailable.",
                        )
                    )
            for analysis in vision_analyses:
                if analysis.status == "pending":
                    warnings.append(
                        SourceWarning(
                            url=analysis.source_url,
                            message=(
                                "M5 vision analysis is running in the background. "
                                f"Call get_vision_analyses with run_id '{run.run_id}' to check it."
                            ),
                        )
                    )
                elif analysis.status in {"not_configured", "failed"}:
                    warnings.append(
                        SourceWarning(
                            url=analysis.source_url,
                            message=analysis.message or "M5 vision analysis was unavailable.",
                        )
                    )
            kit = kit.model_copy(update={"warnings": warnings})
            if not defer_vision:
                self._repository.update(run.with_status(RunStatus.COMPLETED))
            return kit
        except Exception as error:
            self._repository.update(
                run.with_status(RunStatus.FAILED, error_message=str(error))
            )
            raise

    async def analyze_deferred_vision(
        self,
        run_id: str,
    ) -> tuple[ScreenshotVisionAnalysis, ...]:
        """Run queued M5 work and mark the run complete after all sources finish."""

        work = self._deferred_vision_work.pop(run_id, None)
        if work is None:
            work = self._restore_deferred_vision_work(run_id)
        if work is None or self._vision_service is None:
            return ()

        run = self._repository.get(run_id)
        try:
            run = self._repository.update(run.with_status(RunStatus.ANALYZING))
            analyses = await self._vision_service.analyze_and_store(
                work.sources,
                work.text_analyses,
            )
            self._repository.update(run.with_status(RunStatus.COMPLETED))
            return analyses
        except Exception as error:
            self._repository.update(
                run.with_status(RunStatus.FAILED, error_message=str(error))
            )
            raise

    def _restore_deferred_vision_work(self, run_id: str) -> DeferredVisionWork | None:
        """Recreate queued work from SQLite when the development server restarted."""

        if (
            self._source_repository is None
            or self._site_analysis_repository is None
            or self._vision_repository is None
        ):
            return None
        pending_urls = {
            analysis.source_url
            for analysis in self._vision_repository.list_for_run(run_id)
            if analysis.status == "pending"
        }
        if not pending_urls:
            return None
        sources = tuple(
            source
            for source in self._source_repository.list_for_run(run_id)
            if source.source_url in pending_urls
        )
        if not sources:
            return None
        return DeferredVisionWork(
            sources=sources,
            text_analyses=self._site_analysis_repository.list_for_run(run_id),
        )
