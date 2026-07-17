"""M5 screenshot-first visual analysis through a local Ollama vision model."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Protocol, Sequence

import httpx
from PIL import Image

from inspo_mcp.models.source import SourceRecord, utc_now
from inspo_mcp.repositories.vision_analyses import VisionAnalysisRepository
from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis


class VisionAnalyzer(Protocol):
    """Analyze one persisted screenshot without knowing MCP or database details."""

    async def analyze(
        self,
        source: SourceRecord,
        text_analysis: SiteStructureAnalysis | None,
    ) -> ScreenshotVisionAnalysis:
        """Return a durable M5 visual analysis for one source."""


class VisionAnalysisService:
    """Run and persist M5 analysis after M4 structure extraction."""

    def __init__(
        self,
        repository: VisionAnalysisRepository,
        analyzer: VisionAnalyzer,
        *,
        max_concurrency: int = 2,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
        self._repository = repository
        self._analyzer = analyzer
        self._max_concurrency = max_concurrency

    def mark_pending(
        self,
        sources: Sequence[SourceRecord],
    ) -> tuple[ScreenshotVisionAnalysis, ...]:
        """Persist durable pending records before background vision work begins."""

        return tuple(
            self._repository.upsert(
                _base_analysis(
                    source,
                    status="pending",
                    message="M5 vision analysis is queued and running in the background.",
                )
            )
            for source in sources
        )

    async def analyze_and_store(
        self,
        sources: Sequence[SourceRecord],
        text_analyses: Sequence[SiteStructureAnalysis],
    ) -> tuple[ScreenshotVisionAnalysis, ...]:
        """Analyze sources concurrently and persist a status for every source."""

        text_by_url = {analysis.source_url: analysis for analysis in text_analyses}
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def analyze_one(source: SourceRecord) -> ScreenshotVisionAnalysis:
            async with semaphore:
                analysis = await self._analyzer.analyze(source, text_by_url.get(source.source_url))
            return self._repository.upsert(analysis)

        return tuple(await asyncio.gather(*(analyze_one(source) for source in sources)))


class OllamaVisionAnalyzer:
    """Analyze screenshot evidence through a local Ollama server only."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "gemma4:e4b",
        timeout_seconds: float = 300.0,
        max_image_bytes: int = 10_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        _require_local_ollama_url(base_url)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_image_bytes = max_image_bytes
        self._transport = transport

    @classmethod
    def from_environment(cls) -> "OllamaVisionAnalyzer":
        """Load safe local-only M5 configuration without requiring any API key."""

        return cls(
            base_url=os.getenv("INSPO_MCP_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            model=os.getenv("INSPO_MCP_OLLAMA_VISION_MODEL", "gemma4:e4b"),
            timeout_seconds=_ollama_timeout_seconds(),
        )

    async def analyze(
        self,
        source: SourceRecord,
        text_analysis: SiteStructureAnalysis | None,
    ) -> ScreenshotVisionAnalysis:
        if not source.screenshot_path:
            return _base_analysis(
                source,
                status="not_applicable",
                message="No screenshot evidence is available for M5 vision analysis.",
            )
        color_palette = _safe_extract_palette(Path(source.screenshot_path))
        try:
            return await self._analyze_local(source, text_analysis, color_palette=color_palette)
        except httpx.ConnectError:
            return _base_analysis(
                source,
                status="not_configured",
                message=(
                    "Local Ollama is not running at 127.0.0.1:11434. Install/start Ollama and "
                    f"run 'ollama pull {self._model}'."
                ),
                color_palette=color_palette,
            )
        except httpx.TimeoutException:
            return _base_analysis(
                source,
                status="failed",
                message="Local Ollama vision analysis timed out.",
                color_palette=color_palette,
            )
        except httpx.HTTPStatusError as error:
            return _base_analysis(
                source,
                status="not_configured" if error.response.status_code == 404 else "failed",
                message=(
                    f"Local Ollama could not use model '{self._model}' (HTTP "
                    f"{error.response.status_code}). Run 'ollama pull {self._model}' and retry."
                ),
                color_palette=color_palette,
            )
        except Exception as error:
            return _base_analysis(
                source,
                status="failed",
                message=f"Local M5 vision analysis failed: {type(error).__name__}: {error}",
                color_palette=color_palette,
            )

    async def _analyze_local(
        self,
        source: SourceRecord,
        text_analysis: SiteStructureAnalysis | None,
        *,
        color_palette: Sequence[str],
    ) -> ScreenshotVisionAnalysis:
        image_path = Path(source.screenshot_path or "")
        image_bytes = image_path.read_bytes()
        if len(image_bytes) > self._max_image_bytes:
            raise ValueError(
                f"Screenshot exceeds the M5 vision limit ({self._max_image_bytes} bytes)."
            )
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        request = {
            "model": self._model,
            "prompt": _vision_prompt(text_analysis),
            "images": [encoded_image],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.post("/api/generate", json=request)
            response.raise_for_status()
        payload = response.json()
        output = payload.get("response")
        if not isinstance(output, str):
            raise ValueError("Local Ollama response did not include generated text.")
        return _parse_model_output(source, output, color_palette=color_palette)


def configured_vision_analyzer() -> VisionAnalyzer:
    """Return the local-only vision analyzer; it never contacts a cloud provider."""

    return OllamaVisionAnalyzer.from_environment()


def _vision_prompt(text_analysis: SiteStructureAnalysis | None) -> str:
    """Ask for precise, original UI observations rather than copied content."""

    text_context = (
        text_analysis.model_dump_json()
        if text_analysis is not None and text_analysis.status == "extracted"
        else "No reliable text structure was extracted."
    )
    return (
        "You are a senior product designer performing a precise visual analysis of one UI screenshot. "
        "Extract reusable, original design patterns for a developer building a new interface. Analyze "
        "only what is visibly present, not what you assume exists.\n\n"
        "Important boundaries:\n"
        "- Do not copy source text, brand names, logos, product names, or exact wording.\n"
        "- Do not reproduce the source layout exactly; describe transferable patterns only.\n"
        "- Do not call a layout a form, table, or grid unless visual evidence clearly supports it. "
        "A form requires visible input controls, labels, or submission controls. A data table requires "
        "column headers and repeated tabular rows.\n"
        "- Use only observations supported by the screenshot. Omit uncertain details.\n"
        "- Return valid JSON only. Do not include Markdown or text outside the JSON object.\n\n"
        "Inspect the screenshot carefully for:\n"
        "1. Page purpose and visual mood: page type, tone, and content density.\n"
        "2. Visual hierarchy: the dominant element, headline region, supporting content, calls to action, "
        "imagery, contrast, and whitespace.\n"
        "3. Visible page regions in top-to-bottom order: utility/header/navigation, hero, cards or content "
        "sections, trust content, and footer only when visible.\n"
        "4. Layout system: containers, alignment, columns, card repetition, section spacing, and only "
        "justified responsive inferences.\n"
        "5. Reusable components: state each component's purpose and visible anatomy, for example a "
        "navigation bar, search control, hero banner, category tile, product card, or primary CTA.\n"
        "6. Design language: color relationships, typography scale and weight, borders, radius, shadows, "
        "dividers, spacing rhythm, imagery treatment, and button treatment.\n"
        "7. Name visible visual patterns precisely when present, including pill buttons, oversized display "
        "type, split-choice cards, dashboard action rows, and large-radius panels.\n"
        "8. Screenshot-to-text comparison: flag a mismatch only when captured text clearly indicates a "
        "blocked, unsupported, or unrelated page.\n\n"
        "Captured text structure:\n"
        + text_context
        + "\n\nReturn exactly this JSON shape:\n"
        + "{\n"
        + '  "summary": "Two or three sentences describing the page strategy and strongest reusable inspiration.",\n'
        + '  "visual_style": ["specific visual mood", "typography observation", "spacing or density observation", "imagery or surface treatment"],\n'
        + '  "layout_patterns": ["top-to-bottom page-region sequence", "hero composition", "content arrangement", "alignment strategy", "responsive inference only if justified"],\n'
        + '  "component_patterns": ["Component name: purpose and visible anatomy", "Component name: purpose and visible anatomy", "Component name: purpose and visible anatomy"],\n'
        + '  "color_direction": ["background and surface relationship", "primary contrast direction", "accent usage", "CTA color treatment"],\n'
        + '  "text_alignment": "aligned | partial | not_available",\n'
        + '  "text_mismatches": ["only concrete screenshot-versus-text mismatches"]\n'
        + "}"
    )


def _parse_model_output(
    source: SourceRecord,
    output_text: str,
    *,
    color_palette: Sequence[str] = (),
) -> ScreenshotVisionAnalysis:
    """Convert a model's JSON-only reply into bounded, durable M5 evidence."""

    cleaned = output_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Vision response was not a JSON object.")
    raw_alignment = payload.get("text_alignment")
    alignment = raw_alignment.strip().lower() if isinstance(raw_alignment, str) else "not_available"
    if alignment not in {"aligned", "partial", "not_available"}:
        alignment = "not_available"
    return ScreenshotVisionAnalysis(
        run_id=source.run_id,
        source_url=source.source_url,
        source_content_hash=source.content_hash,
        status="completed",
        summary=_string_or_none(payload.get("summary")),
        visual_style=_string_list(payload.get("visual_style"), limit=8),
        layout_patterns=_string_list(payload.get("layout_patterns"), limit=12),
        component_patterns=_string_list(payload.get("component_patterns"), limit=12),
        color_direction=_string_list(payload.get("color_direction"), limit=8),
        color_palette=_hex_color_list(color_palette, limit=8),
        text_alignment=alignment,
        text_mismatches=_string_list(payload.get("text_mismatches"), limit=8),
        analyzed_at=utc_now(),
    )


def _base_analysis(
    source: SourceRecord,
    *,
    status: str,
    message: str,
    color_palette: Sequence[str] = (),
) -> ScreenshotVisionAnalysis:
    return ScreenshotVisionAnalysis(
        run_id=source.run_id,
        source_url=source.source_url,
        source_content_hash=source.content_hash,
        status=status,  # type: ignore[arg-type]
        message=message,
        color_palette=_hex_color_list(color_palette, limit=8),
        analyzed_at=utc_now(),
    )


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][:limit]


def extract_screenshot_palette(image_path: Path, *, max_colors: int = 6) -> list[str]:
    """Return a compact, locally extracted palette without sending pixels anywhere else."""

    with Image.open(image_path) as opened_image:
        image = opened_image.convert("RGB")
    image.thumbnail((240, 240))
    quantized = image.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    color_counts = quantized.getcolors(maxcolors=32) or []
    if palette is None or not color_counts:
        return []

    total_pixels = sum(count for count, _ in color_counts)
    candidates = sorted(
        (
            (count, (palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2]))
            for count, index in color_counts
        ),
        reverse=True,
    )
    selected: list[tuple[int, int, int]] = []

    for _, color in candidates:
        if _is_visually_distinct(color, selected):
            selected.append(color)
        if len(selected) >= min(3, max_colors):
            break

    accent_candidates = sorted(
        candidates,
        key=lambda candidate: (
            _saturation(candidate[1]) * 0.12 + candidate[0] / max(total_pixels, 1),
            candidate[0],
        ),
        reverse=True,
    )
    for count, color in accent_candidates:
        if count / max(total_pixels, 1) < 0.002:
            continue
        if _is_visually_distinct(color, selected):
            selected.append(color)
        if len(selected) >= max_colors:
            break

    return [_rgb_to_hex(color) for color in selected]


def _safe_extract_palette(image_path: Path) -> list[str]:
    """Keep local colour extraction helpful but non-blocking for unsupported files."""

    try:
        return extract_screenshot_palette(image_path)
    except (OSError, ValueError):
        return []


def _is_visually_distinct(
    candidate: tuple[int, int, int],
    selected: Sequence[tuple[int, int, int]],
) -> bool:
    return all(sum((left - right) ** 2 for left, right in zip(candidate, color)) ** 0.5 >= 42 for color in selected)


def _saturation(color: tuple[int, int, int]) -> float:
    maximum = max(color)
    return 0.0 if maximum == 0 else (maximum - min(color)) / maximum


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in color)


def _hex_color_list(values: Sequence[str], *, limit: int) -> list[str]:
    colors: list[str] = []
    for value in values:
        normalized = value.strip().upper()
        if len(normalized) == 7 and normalized.startswith("#") and all(
            character in "0123456789ABCDEF" for character in normalized[1:]
        ) and normalized not in colors:
            colors.append(normalized)
    return colors[:limit]


def _require_local_ollama_url(value: str) -> None:
    """Reject remote endpoints so screenshots remain on the developer's machine."""

    url = httpx.URL(value)
    if url.scheme != "http" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("INSPO_MCP_OLLAMA_BASE_URL must point to a local HTTP Ollama server.")


def _ollama_timeout_seconds() -> float:
    """Read an explicit per-screenshot timeout for slower local vision models."""

    raw_value = os.getenv("INSPO_MCP_OLLAMA_TIMEOUT_SECONDS", "300")
    try:
        timeout_seconds = float(raw_value)
    except ValueError as error:
        raise ValueError("INSPO_MCP_OLLAMA_TIMEOUT_SECONDS must be a positive number.") from error
    if timeout_seconds <= 0:
        raise ValueError("INSPO_MCP_OLLAMA_TIMEOUT_SECONDS must be a positive number.")
    return timeout_seconds
