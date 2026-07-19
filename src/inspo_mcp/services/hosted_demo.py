"""Stable, transparent judge-demo runs that do not require a hosted vision model."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from inspo_mcp.models.run import RunRecord, RunStatus, utc_now
from inspo_mcp.models.source import SourceRecord, SourceStatus
from inspo_mcp.repositories.kits import KitRepository
from inspo_mcp.repositories.runs import RunRepository
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas import Framework, InspirationKit, SourceWarning
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis
from inspo_mcp.services.kit_generator import EvidenceKitGenerator


@dataclass(frozen=True)
class _DemoAsset:
    """Curated, self-authored visual evidence bundled for the judge demo."""

    source_url: str
    filename: str
    title: str
    summary: str
    visual_style: tuple[str, ...]
    layout_patterns: tuple[str, ...]
    component_patterns: tuple[str, ...]
    color_direction: tuple[str, ...]
    color_palette: tuple[str, ...]


_DEMO_ASSETS = (
    _DemoAsset(
        source_url="demo://aurora-landing",
        filename="aurora-landing.png",
        title="Aurora landing page (self-authored demo asset)",
        summary=(
            "A dark product landing page with a compact header, centered display hero, "
            "pill actions, and a dashboard-preview proof panel."
        ),
        visual_style=(
            "dark indigo product surface",
            "oversized display typography",
            "rounded pill actions",
            "soft violet contrast",
        ),
        layout_patterns=(
            "compact top navigation",
            "centered hero hierarchy",
            "paired hero actions",
            "dashboard preview panel",
            "repeating metric cards",
        ),
        component_patterns=(
            "header navigation",
            "announcement chip",
            "primary action button",
            "secondary outline action",
            "metric card",
            "data visualization panel",
        ),
        color_direction=(
            "dark navy base with violet and pale-lilac accents",
            "high-contrast white text for the hero",
        ),
        color_palette=("#10111E", "#17334F", "#4B2B90", "#A78BFA", "#F8F7FF", "#E9E6F8"),
    ),
    _DemoAsset(
        source_url="demo://northstar-operations-dashboard",
        filename="ops-dashboard.png",
        title="Northstar operations dashboard (self-authored demo asset)",
        summary=(
            "A light operations dashboard with a dark sidebar, compact metric cards, "
            "an alert strip, and chart-led workspace panels."
        ),
        visual_style=(
            "light operational workspace",
            "dark navy navigation rail",
            "structured data hierarchy",
            "blue and amber status accents",
        ),
        layout_patterns=(
            "persistent sidebar navigation",
            "workspace header with utility actions",
            "four-column metric row",
            "chart and alert split layout",
            "stacked information panels",
        ),
        component_patterns=(
            "sidebar navigation",
            "workspace header",
            "status alert strip",
            "metric card",
            "bar chart panel",
            "alert list",
        ),
        color_direction=(
            "light canvas with navy structure, blue actions, and amber attention states",
            "dark text on pale surfaces for data readability",
        ),
        color_palette=("#F5F7FB", "#172A43", "#2F67D9", "#8CAAF0", "#F2B14B", "#FFFFFF"),
    ),
)


def _default_demo_root() -> Path:
    """Locate bundled demo screenshots in source and installed Docker builds."""

    configured_root = os.environ.get("INSPO_MCP_DEMO_ROOT")
    candidates = (
        Path(configured_root).expanduser() if configured_root else None,
        Path.cwd() / "demo",
        Path("/app/demo"),
        Path(__file__).resolve().parents[3] / "demo",
    )
    for candidate in candidates:
        if candidate is not None and all(
            (candidate / asset.filename).is_file() for asset in _DEMO_ASSETS
        ):
            return candidate

    searched = ", ".join(str(candidate) for candidate in candidates if candidate is not None)
    raise FileNotFoundError(
        "Bundled hosted-demo screenshots were not found. Searched: " + searched
    )


class HostedJudgeDemoService:
    """Create a durable, non-mock kit from bundled and disclosed demo evidence.

    This is intentionally separate from the live M5 pipeline: it never reads
    a user image, makes a network request, or claims that Ollama ran remotely.
    """

    def __init__(
        self,
        runs: RunRepository,
        sources: SourceRepository,
        vision_analyses: VisionAnalysisRepository,
        kits: KitRepository,
        kit_generator: EvidenceKitGenerator,
        *,
        demo_root: Path | None = None,
    ) -> None:
        self._runs = runs
        self._sources = sources
        self._vision_analyses = vision_analyses
        self._kits = kits
        self._kit_generator = kit_generator
        self._demo_root = demo_root or _default_demo_root()

    def create(
        self,
        *,
        project_goal: str,
        framework: Framework,
        privacy_mode: bool,
        retention_days: int,
    ) -> InspirationKit:
        """Persist a completed transparent demo run and return its reusable kit."""

        run = self._new_run(project_goal, framework, privacy_mode, retention_days)
        self._runs.create(run)
        try:
            run = self._runs.update(run.with_status(RunStatus.ANALYZING))
            analyses = tuple(self._persist_demo_evidence(run))
            run = self._runs.update(run.with_status(RunStatus.GENERATING))
            kit = self._kit_generator.generate(run, (), analyses)
            kit = kit.model_copy(
                update={
                    "warnings": [
                        *kit.warnings,
                        SourceWarning(
                            url="demo://hosted-judge-demo",
                            message=(
                                "Hosted judge demo: this kit uses precomputed visual evidence "
                                "from two self-authored screenshots bundled with InspoMCP. "
                                "It does not run Ollama or analyze judge-provided images."
                            ),
                        ),
                    ],
                }
            )
            self._kits.upsert(kit)
            self._runs.update(run.with_status(RunStatus.COMPLETED))
            return kit
        except Exception as error:
            self._runs.update(run.with_status(RunStatus.FAILED, error_message=str(error)))
            raise

    def _new_run(
        self,
        project_goal: str,
        framework: Framework,
        privacy_mode: bool,
        retention_days: int,
    ) -> RunRecord:
        now = utc_now()
        expiration = (datetime.now(timezone.utc) + timedelta(days=retention_days)).isoformat()
        return RunRecord(
            run_id=f"demo_{uuid4().hex[:12]}",
            status=RunStatus.VALIDATING,
            inspiration_urls=tuple(asset.source_url for asset in _DEMO_ASSETS),
            project_goal=project_goal,
            framework=framework,
            created_at=now,
            updated_at=now,
            privacy_mode=privacy_mode,
            retention_expires_at=expiration,
        )

    def _persist_demo_evidence(self, run: RunRecord) -> list[ScreenshotVisionAnalysis]:
        analyses: list[ScreenshotVisionAnalysis] = []
        for asset in _DEMO_ASSETS:
            image_path = self._demo_root / asset.filename
            image_bytes = image_path.read_bytes()
            content_hash = hashlib.sha256(image_bytes).hexdigest()
            self._sources.upsert(
                SourceRecord(
                    run_id=run.run_id,
                    source_url=asset.source_url,
                    final_url=asset.source_url,
                    status=SourceStatus.USER_PROVIDED,
                    http_status=None,
                    title=asset.title,
                    visible_text_path=None,
                    semantic_document_path=None,
                    screenshot_path=str(image_path),
                    content_hash=content_hash,
                    redirect_chain=(),
                    captured_at=utc_now(),
                    capture_note="Self-authored bundled asset used only by the transparent hosted judge demo.",
                )
            )
            analysis = ScreenshotVisionAnalysis(
                run_id=run.run_id,
                source_url=asset.source_url,
                source_content_hash=content_hash,
                status="completed",
                summary=asset.summary,
                visual_style=list(asset.visual_style),
                layout_patterns=list(asset.layout_patterns),
                component_patterns=list(asset.component_patterns),
                color_direction=list(asset.color_direction),
                color_palette=list(asset.color_palette),
                text_alignment="not_available",
                text_mismatches=[],
                message="Precomputed, curated evidence for the hosted judge demo; no model was called.",
                analyzed_at=utc_now(),
            )
            self._vision_analyses.upsert(analysis)
            analyses.append(analysis)
        return analyses
