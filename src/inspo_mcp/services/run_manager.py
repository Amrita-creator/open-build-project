"""Orchestrate the lifecycle of an inspiration-kit run."""

from __future__ import annotations

from inspo_mcp.models.run import RunRecord, RunStatus
from inspo_mcp.models.source import SourceStatus
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.schemas import InspirationKit, InspirationRequest, SourceWarning
from inspo_mcp.services.capture import CaptureService
from inspo_mcp.services.mock_artifacts import create_mock_kit
from inspo_mcp.services.url_safety import SafeUrl


class RunManager:
    """Coordinates durable run state without coupling tools to SQLite."""

    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

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
            run = self._repository.update(run.with_status(RunStatus.GENERATING))

            kit = create_mock_kit(request, run_id=run.run_id)
            warnings = [
                SourceWarning(
                    url=source.source_url,
                    message=source.error_message or "Source evidence capture failed.",
                )
                for source in sources
                if source.status is SourceStatus.FAILED
            ]
            kit = kit.model_copy(update={"warnings": warnings})
            self._repository.update(run.with_status(RunStatus.COMPLETED))
            return kit
        except Exception as error:
            self._repository.update(
                run.with_status(RunStatus.FAILED, error_message=str(error))
            )
            raise
