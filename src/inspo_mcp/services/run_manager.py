"""Orchestrate the lifecycle of an inspiration-kit run."""

from __future__ import annotations

from inspo_mcp.models.run import RunRecord, RunStatus
from inspo_mcp.models.source import SourceStatus
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.schemas import InspirationKit, InspirationRequest, SourceWarning
from inspo_mcp.services.capture import CaptureService
from inspo_mcp.services.extract import StructureExtractor
from inspo_mcp.services.mock_artifacts import create_mock_kit
from inspo_mcp.services.url_safety import SafeUrl


class RunManager:
    """Coordinates durable run state without coupling tools to SQLite."""

    def __init__(
        self,
        repository: RunRepository,
        extraction_service: StructureExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._extraction_service = extraction_service

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

    async def create_captured_mock_kit(
        self,
        request: InspirationRequest,
        safe_urls: tuple[SafeUrl, ...],
        capture_service: CaptureService,
    ) -> InspirationKit:
        """Persist M3 source evidence before returning the still-mocked kit."""

        run = self._repository.create(RunRecord.new(request))
        try:
            run = self._repository.update(run.with_status(RunStatus.VALIDATING))
            run = self._repository.update(run.with_status(RunStatus.CAPTURING))
            sources = await capture_service.capture_sources(
                run.run_id,
                safe_urls,
                fallback_screenshots=request.fallback_screenshot_map,
            )
            analyses = ()
            if self._extraction_service is not None:
                run = self._repository.update(run.with_status(RunStatus.EXTRACTING))
                analyses = self._extraction_service.extract_and_store(sources)
            run = self._repository.update(run.with_status(RunStatus.GENERATING))

            kit = create_mock_kit(request, run_id=run.run_id)
            warnings: list[SourceWarning] = []
            for source in sources:
                if source.status is SourceStatus.FAILED:
                    warnings.append(
                        SourceWarning(
                            url=source.source_url,
                            message=source.error_message or "Source evidence capture failed.",
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
            for analysis in analyses:
                if analysis.status != "extracted":
                    warnings.append(
                        SourceWarning(
                            url=analysis.source_url,
                            message=analysis.extraction_message
                            or "Page-structure extraction was unavailable.",
                        )
                    )
            kit = kit.model_copy(update={"warnings": warnings})
            self._repository.update(run.with_status(RunStatus.COMPLETED))
            return kit
        except Exception as error:
            self._repository.update(
                run.with_status(RunStatus.FAILED, error_message=str(error))
            )
            raise
