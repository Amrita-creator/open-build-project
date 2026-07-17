"""M6 evidence-first synthesis of reusable, original UI kits."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from inspo_mcp.models.run import RunRecord
from inspo_mcp.schemas import (
    BuildTask,
    ComponentCard,
    DesignDirection,
    DesignTokens,
    InspirationKit,
    PageBlueprint,
    PageSection,
    SourceWarning,
)
from inspo_mcp.schemas.site_analysis import SiteStructureAnalysis
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis


class EvidenceNotReadyError(ValueError):
    """Raised when M6 is requested before there is usable visual evidence."""


class EvidenceKitGenerator:
    """Build a stable, original kit from completed M4/M5 evidence only."""

    def generate(
        self,
        run: RunRecord,
        structures: Sequence[SiteStructureAnalysis],
        vision_analyses: Sequence[ScreenshotVisionAnalysis],
    ) -> InspirationKit:
        completed_vision = [
            analysis for analysis in vision_analyses if analysis.status == "completed"
        ]
        if not completed_vision:
            raise EvidenceNotReadyError(
                "M5 visual analysis is not ready. Wait until at least one vision result is completed."
            )

        evidence = _EvidenceSummary.from_analyses(structures, completed_vision)
        components = _component_cards(evidence)
        component_names = [component.name for component in components]

        return InspirationKit(
            run_id=run.run_id,
            design_direction=_design_direction(run, evidence),
            page_blueprint=_page_blueprint(run, evidence, component_names),
            component_cards=components,
            design_tokens=_design_tokens(evidence),
            build_tasks=_build_tasks(run, component_names),
            warnings=_evidence_warnings(structures, vision_analyses),
            is_mock=False,
        )


class _EvidenceSummary:
    """Normalized, bounded evidence used by the deterministic M6 rules."""

    def __init__(
        self,
        *,
        visual_style: list[str],
        layout_patterns: list[str],
        component_patterns: list[str],
        color_direction: list[str],
        has_structure_cards: bool,
        has_structure_ctas: bool,
    ) -> None:
        self.visual_style = visual_style
        self.layout_patterns = layout_patterns
        self.component_patterns = component_patterns
        self.color_direction = color_direction
        self.has_structure_cards = has_structure_cards
        self.has_structure_ctas = has_structure_ctas

    @classmethod
    def from_analyses(
        cls,
        structures: Sequence[SiteStructureAnalysis],
        vision_analyses: Sequence[ScreenshotVisionAnalysis],
    ) -> "_EvidenceSummary":
        return cls(
            visual_style=_unique_strings(
                item for analysis in vision_analyses for item in analysis.visual_style
            )[:6],
            layout_patterns=_unique_strings(
                item for analysis in vision_analyses for item in analysis.layout_patterns
            )[:8],
            component_patterns=_unique_strings(
                item for analysis in vision_analyses for item in analysis.component_patterns
            )[:8],
            color_direction=_unique_strings(
                item for analysis in vision_analyses for item in analysis.color_direction
            )[:5],
            has_structure_cards=any(structure.cards for structure in structures),
            has_structure_ctas=any(structure.calls_to_action for structure in structures),
        )

    @property
    def combined_text(self) -> str:
        return " ".join(
            [
                *self.visual_style,
                *self.layout_patterns,
                *self.component_patterns,
                *self.color_direction,
            ]
        ).lower()

    def mentions(self, *terms: str) -> bool:
        return any(term in self.combined_text for term in terms)


def _design_direction(run: RunRecord, evidence: _EvidenceSummary) -> DesignDirection:
    style = evidence.visual_style or ["clear visual hierarchy", "deliberate contrast"]
    summary = (
        f"An original interface direction for {run.project_goal.strip()} that combines "
        f"{_natural_list(style[:3])}. Reuse the observed hierarchy and component roles, "
        "not source branding, copy, or exact layout."
    )
    principles = [
        "Make the primary user action visually dominant within the first viewport.",
        "Use a shared spacing and card anatomy system across repeated content.",
        "Use contrast, typography, and whitespace to establish hierarchy before decoration.",
    ]
    if evidence.mentions("navigation", "header", "search"):
        principles.append("Keep global navigation compact and separate it from page-level actions.")
    if evidence.mentions("hero", "banner"):
        principles.append("Pair one focused hero message with a single primary call to action.")
    return DesignDirection(
        summary=summary,
        visual_style=style,
        principles=principles[:4],
        avoid=[
            "Copying source-site text, logos, imagery, or exact page geometry.",
            "Using color alone to communicate interactive state or importance.",
            "Turning repeated content into dense cards without a clear scanning hierarchy.",
        ],
    )


def _page_blueprint(
    run: RunRecord,
    evidence: _EvidenceSummary,
    component_names: Sequence[str],
) -> PageBlueprint:
    sections: list[PageSection] = []
    if "HeaderNavigation" in component_names:
        sections.append(
            PageSection(
                name="Header and navigation",
                purpose="Orient visitors and expose the most important global actions.",
                suggested_components=["HeaderNavigation"],
            )
        )
    sections.append(
        PageSection(
            name="Hero",
            purpose=f"State the primary value for: {run.project_goal.strip()}",
            suggested_components=["HeroPanel", "PrimaryAction"],
        )
    )
    if "ContentCardGrid" in component_names:
        sections.append(
            PageSection(
                name="Value or discovery grid",
                purpose="Present a small number of scannable benefits, categories, or featured items.",
                suggested_components=["ContentCardGrid"],
            )
        )
    if "ProofStrip" in component_names:
        sections.append(
            PageSection(
                name="Proof and reassurance",
                purpose="Add concise trust signals, supporting detail, or product proof.",
                suggested_components=["ProofStrip"],
            )
        )
    sections.append(
        PageSection(
            name="Closing action",
            purpose="Repeat one clear next step after the page value has been established.",
            suggested_components=["PrimaryAction"],
        )
    )
    return PageBlueprint(
        summary=(
            "An original page blueprint synthesized from completed visual evidence and "
            "the requested product goal."
        ),
        sections=sections,
    )


def _component_cards(evidence: _EvidenceSummary) -> list[ComponentCard]:
    cards: list[ComponentCard] = []
    if evidence.mentions("navigation", "header", "search"):
        cards.append(
            ComponentCard(
                name="HeaderNavigation",
                purpose="Provide consistent global navigation and optional utility actions.",
                props=["brand_slot", "navigation_items", "utility_actions", "variant"],
                variants=["light", "dark", "compact"],
                content_slots=["brand", "primary_navigation", "utility_actions"],
                responsive_behavior="Collapse navigation into a menu trigger while retaining the primary action.",
                accessibility_notes=[
                    "Use a semantic header and nav landmark.",
                    "Expose expanded state and keyboard navigation for menus.",
                ],
            )
        )
    cards.extend(
        [
            ComponentCard(
                name="HeroPanel",
                purpose="Lead with one product promise, supporting context, and a visual focal point.",
                props=["eyebrow", "heading", "body", "media", "alignment"],
                variants=["split", "centered", "media-forward"],
                content_slots=["eyebrow", "heading", "body", "actions", "media"],
                responsive_behavior="Stack content and media on narrow screens while keeping the primary action visible.",
                accessibility_notes=[
                    "Use one page-level heading.",
                    "Provide meaningful alternative text for essential media.",
                ],
            ),
            ComponentCard(
                name="PrimaryAction",
                purpose="Make the preferred next step obvious and consistent across page regions.",
                props=["label", "href", "icon", "size", "variant"],
                variants=["primary", "secondary", "text"],
                content_slots=["label", "leading_icon", "trailing_icon"],
                responsive_behavior="Keep a minimum touch target and allow full-width presentation on mobile.",
                accessibility_notes=[
                    "Use action-specific labels instead of generic text.",
                    "Preserve visible keyboard focus.",
                ],
            ),
        ]
    )
    if evidence.has_structure_cards or evidence.mentions("card", "tile", "category", "product"):
        cards.append(
            ComponentCard(
                name="ContentCardGrid",
                purpose="Group repeated value, category, or feature content into a scannable responsive layout.",
                props=["items", "columns", "card_variant", "section_title"],
                variants=["feature", "category", "editorial"],
                content_slots=["image_or_icon", "title", "description", "action"],
                responsive_behavior="Use one column on small screens, two on medium screens, and three or four only when width allows.",
                accessibility_notes=[
                    "Keep each card heading and action understandable out of context.",
                    "Do not make an entire card clickable when it contains nested controls.",
                ],
            )
        )
    if evidence.has_structure_ctas or evidence.mentions("proof", "trust", "rating", "testimonial"):
        cards.append(
            ComponentCard(
                name="ProofStrip",
                purpose="Present concise supporting proof without competing with the primary narrative.",
                props=["items", "icon", "emphasis"],
                variants=["inline", "bordered", "surface"],
                content_slots=["icon", "label", "supporting_text"],
                responsive_behavior="Wrap items into short rows and preserve readable spacing at narrow widths.",
                accessibility_notes=[
                    "Express proof in text, not visual symbols alone.",
                ],
            )
        )
    return cards[:5]


def _design_tokens(evidence: _EvidenceSummary) -> DesignTokens:
    combined = evidence.combined_text
    dark = "dark" in combined
    if "purple" in combined or "violet" in combined:
        accent = "#6D5DFB"
    elif "orange" in combined or "warm" in combined:
        accent = "#D97706"
    elif "teal" in combined or "cyan" in combined:
        accent = "#0891B2"
    else:
        accent = "#2563EB"
    return DesignTokens(
        colors=(
            {
                "background": "#0F172A",
                "surface": "#1E293B",
                "text": "#F8FAFC",
                "muted_text": "#CBD5E1",
                "accent": accent,
            }
            if dark
            else {
                "background": "#F8FAFC",
                "surface": "#FFFFFF",
                "text": "#0F172A",
                "muted_text": "#475569",
                "accent": accent,
            }
        ),
        typography={"display": "clamp(2.5rem, 6vw, 4.5rem)", "heading": "2rem", "body": "1rem"},
        spacing={"section": "clamp(4rem, 8vw, 7rem)", "card": "1.5rem", "stack": "1rem"},
        radius={"card": "1rem", "button": "0.75rem"},
        shadow={"card": "0 12px 32px rgb(15 23 42 / 0.12)"},
    )


def _build_tasks(run: RunRecord, component_names: Sequence[str]) -> list[BuildTask]:
    tasks = [
        BuildTask(
            title="Create the evidence-derived design-token layer",
            priority="high",
            acceptance_criteria=[
                "Colors, typography, spacing, radius, and shadow tokens are defined once.",
                "The selected accent and contrast meet accessible text requirements.",
            ],
        ),
        BuildTask(
            title="Implement the hero and primary action",
            priority="high",
            acceptance_criteria=[
                "The hero communicates the requested product goal without source-site copy.",
                "The primary action is visible, keyboard-accessible, and responsive.",
            ],
        ),
    ]
    if "ContentCardGrid" in component_names:
        tasks.append(
            BuildTask(
                title="Implement the reusable content-card grid",
                priority="high",
                acceptance_criteria=[
                    "Cards use shared anatomy and accept data through props.",
                    "The grid adapts from one to multiple columns without horizontal scrolling.",
                ],
            )
        )
    tasks.append(
        BuildTask(
            title=f"Validate the {run.framework} implementation",
            priority="medium",
            acceptance_criteria=[
                "Heading order, focus states, and semantic landmarks are verified.",
                "The result uses original content and does not reproduce source branding or layout.",
            ],
        )
    )
    return tasks


def _evidence_warnings(
    structures: Sequence[SiteStructureAnalysis],
    vision_analyses: Sequence[ScreenshotVisionAnalysis],
) -> list[SourceWarning]:
    warnings: list[SourceWarning] = []
    for analysis in vision_analyses:
        if analysis.status != "completed":
            warnings.append(
                SourceWarning(
                    url=analysis.source_url,
                    message=analysis.message or "This source did not produce completed M5 evidence.",
                )
            )
    for structure in structures:
        if structure.status == "unavailable":
            warnings.append(
                SourceWarning(
                    url=structure.source_url,
                    message=structure.extraction_message or "M4 structure evidence was unavailable.",
                )
            )
    return warnings


def _unique_strings(values: Iterable[str]) -> list[str]:
    """Preserve first-seen human-readable evidence without duplicating phrases."""

    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _natural_list(values: Sequence[str]) -> str:
    if not values:
        return "a clear visual hierarchy"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"
