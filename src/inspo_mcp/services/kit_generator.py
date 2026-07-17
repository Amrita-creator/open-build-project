"""M6 evidence-first synthesis of reusable, original UI kits."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import re

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


class EvidenceIncompleteError(EvidenceNotReadyError):
    """Raised when one or more requested sources have not completed M5 analysis."""

    def __init__(self, missing_sources: Sequence[str]) -> None:
        self.missing_sources = tuple(missing_sources)
        source_list = ", ".join(self.missing_sources)
        super().__init__(
            "Final kit generation is blocked until M5 visual analysis completes for every "
            f"requested source. Retry or wait for: {source_list}"
        )


class EvidenceKitGenerator:
    """Build a stable, original kit from completed M4/M5 evidence only."""

    def generate(
        self,
        run: RunRecord,
        structures: Sequence[SiteStructureAnalysis],
        vision_analyses: Sequence[ScreenshotVisionAnalysis],
    ) -> InspirationKit:
        completed_by_source = {
            analysis.source_url: analysis
            for analysis in vision_analyses
            if analysis.status == "completed"
        }
        missing_sources = [
            source_url for source_url in run.inspiration_urls if source_url not in completed_by_source
        ]
        if missing_sources:
            raise EvidenceIncompleteError(missing_sources)

        completed_vision = [completed_by_source[source_url] for source_url in run.inspiration_urls]

        evidence = _EvidenceSummary.from_analyses(structures, completed_vision)
        components = _component_cards(run, evidence)
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
        color_palette: list[str],
        has_structure_cards: bool,
        has_structure_ctas: bool,
    ) -> None:
        self.visual_style = visual_style
        self.layout_patterns = layout_patterns
        self.component_patterns = component_patterns
        self.color_direction = color_direction
        self.color_palette = color_palette
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
            color_palette=_unique_strings(
                item for analysis in vision_analyses for item in analysis.color_palette
            )[:8],
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
    if evidence.color_palette:
        style = [
            *style,
            "locally extracted palette: " + ", ".join(evidence.color_palette[:5]),
        ]
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
    if _is_finance_goal(run.project_goal):
        principles.append(
            "Make balances, fees, and financial status understandable in text rather than colour alone."
        )
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
    if _is_finance_goal(run.project_goal):
        return PageBlueprint(
            summary=(
                "A finance landing-page blueprint that translates the completed visual evidence into "
                "an original, reassuring product journey."
            ),
            sections=[
                PageSection(
                    name="Header and product navigation",
                    purpose="Offer concise navigation, account access, and an obvious primary action.",
                    suggested_components=["FinanceHeader", "PillActionButton"],
                ),
                PageSection(
                    name="Hero and account choice",
                    purpose="Explain the financial value proposition and let visitors choose a relevant pathway.",
                    suggested_components=["FinanceHero", "SplitAccountCard", "PillActionButton"],
                ),
                PageSection(
                    name="Money overview",
                    purpose="Show a privacy-safe preview of balances, actions, and financial clarity.",
                    suggested_components=["BalancePreviewPanel", "FinanceDashboardPreview"],
                ),
                PageSection(
                    name="Goals and plan comparison",
                    purpose="Help visitors understand savings outcomes and choose the right plan.",
                    suggested_components=["SavingsGoalCard", "PlanComparison"],
                ),
                PageSection(
                    name="Trust and customer proof",
                    purpose="Build confidence with security information and original customer evidence.",
                    suggested_components=["SecurityTrustStrip", "TestimonialCard"],
                ),
                PageSection(
                    name="Questions and footer",
                    purpose="Resolve objections and provide complete support and policy navigation.",
                    suggested_components=["FAQAccordion", "FooterNavigation"],
                ),
            ],
        )

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


def _component_cards(run: RunRecord, evidence: _EvidenceSummary) -> list[ComponentCard]:
    if _is_finance_goal(run.project_goal):
        return _finance_component_cards()

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


def _finance_component_cards() -> list[ComponentCard]:
    """Return finance-specific components instead of relabelling generic SaaS cards."""

    return [
        ComponentCard(
            name="FinanceHeader",
            purpose="Provide product navigation, account access, and a compact mobile menu.",
            props=["brand_slot", "navigation_items", "account_action", "primary_action"],
            variants=["transparent", "surface", "sticky"],
            content_slots=["brand", "navigation", "account_action", "primary_action"],
            responsive_behavior="Collapse navigation into an accessible menu while retaining the account and primary actions.",
            accessibility_notes=[
                "Use semantic header and nav landmarks.",
                "Expose menu expanded state and preserve keyboard focus when the mobile menu opens.",
            ],
        ),
        ComponentCard(
            name="FinanceHero",
            purpose="State an original money-management promise and pair it with a credible visual preview.",
            props=["eyebrow", "heading", "body", "primary_action", "secondary_action", "visual"],
            variants=["split", "centered", "dashboard-preview"],
            content_slots=["eyebrow", "heading", "body", "actions", "visual"],
            responsive_behavior="Stack copy above the preview on small screens and keep the primary action visible without horizontal scrolling.",
            accessibility_notes=[
                "Use one page-level heading.",
                "Do not place essential financial claims only inside a visual preview.",
            ],
        ),
        ComponentCard(
            name="SplitAccountCard",
            purpose="Present two clear financial pathways, such as personal and business or saver and investor.",
            props=["options", "selected_option", "on_select", "illustration_slot"],
            variants=["two-up", "stacked", "compact"],
            content_slots=["option_title", "supporting_copy", "illustration", "action"],
            responsive_behavior="Show equal-width cards on desktop and stack them with full-width actions on mobile.",
            accessibility_notes=[
                "Use buttons or labelled radio controls for a selectable choice.",
                "Make each option understandable without relying on its illustration.",
            ],
        ),
        ComponentCard(
            name="PillActionButton",
            purpose="Offer a large, friendly call to action with distinct primary, dark, and attention states.",
            props=["label", "href", "icon", "variant", "size"],
            variants=["primary", "dark", "attention", "outline"],
            content_slots=["label", "leading_icon", "trailing_icon"],
            responsive_behavior="Maintain a 44px minimum touch target and allow full-width actions in narrow containers.",
            accessibility_notes=[
                "Use action-specific labels.",
                "Do not communicate button priority by colour alone.",
            ],
        ),
        ComponentCard(
            name="BalancePreviewPanel",
            purpose="Show an illustrative account balance, trend, and privacy control without exposing real user data.",
            props=["balance", "currency", "trend", "is_balance_hidden", "on_toggle_visibility"],
            variants=["primary", "surface", "compact"],
            content_slots=["label", "balance", "trend", "privacy_control"],
            responsive_behavior="Keep the balance and privacy control together; stack supporting statistics below on small screens.",
            accessibility_notes=[
                "Provide an accessible name for the show or hide balance control.",
                "State positive or negative trends in text as well as colour.",
            ],
        ),
        ComponentCard(
            name="SavingsGoalCard",
            purpose="Make a savings goal, progress, contribution action, and deadline easy to scan.",
            props=["title", "saved_amount", "target_amount", "deadline", "progress", "action"],
            variants=["featured", "default", "compact"],
            content_slots=["goal_label", "amount", "progress", "deadline", "action"],
            responsive_behavior="Use one column per card on mobile and never compress monetary values below readable size.",
            accessibility_notes=[
                "Expose progress as text such as '60 percent complete'.",
                "Label all monetary values with a currency.",
            ],
        ),
        ComponentCard(
            name="FinanceDashboardPreview",
            purpose="Preview a calm, action-oriented dashboard with grouped money actions and readable sections.",
            props=["quick_actions", "summary_rows", "active_section", "preview_mode"],
            variants=["overview", "goals", "transactions"],
            content_slots=["section_navigation", "quick_actions", "summary_content"],
            responsive_behavior="Convert horizontal action groups into a wrapped or stacked layout on smaller screens.",
            accessibility_notes=[
                "Use labelled controls for dashboard actions.",
                "Keep preview data visibly illustrative rather than presenting it as a live balance.",
            ],
        ),
        ComponentCard(
            name="PlanComparison",
            purpose="Compare pricing, fees, or membership benefits without hiding important conditions.",
            props=["plans", "featured_plan", "disclosures", "action"],
            variants=["three-column", "two-column", "stacked"],
            content_slots=["plan_name", "price_or_fee", "benefits", "disclosures", "action"],
            responsive_behavior="Stack plans on mobile and preserve a logical reading order before visual emphasis.",
            accessibility_notes=[
                "Describe fees and conditions in text.",
                "Do not use a visual badge as the only way to identify a recommended plan.",
            ],
        ),
        ComponentCard(
            name="SecurityTrustStrip",
            purpose="Communicate privacy, account protection, and support commitments near conversion points.",
            props=["items", "icon", "emphasis"],
            variants=["inline", "surface", "bordered"],
            content_slots=["icon", "heading", "supporting_text"],
            responsive_behavior="Wrap short trust statements into readable rows without shrinking text.",
            accessibility_notes=["Express every trust claim in text, not icons alone."],
        ),
        ComponentCard(
            name="TestimonialCard",
            purpose="Show original customer proof with a clear quotation, attribution, and optional outcome.",
            props=["quote", "name", "role", "outcome", "avatar"],
            variants=["card", "carousel-item", "inline"],
            content_slots=["quote", "attribution", "outcome"],
            responsive_behavior="Use a single readable column on small screens and avoid auto-advancing content.",
            accessibility_notes=["Do not convey testimonial meaning only through an avatar or star icon."],
        ),
        ComponentCard(
            name="FAQAccordion",
            purpose="Answer common questions about account access, privacy, eligibility, and fees.",
            props=["items", "allow_multiple_open"],
            variants=["divided", "surface", "bordered"],
            content_slots=["question", "answer"],
            responsive_behavior="Keep each trigger full width and preserve a comfortable touch target on mobile.",
            accessibility_notes=[
                "Use button triggers with aria-expanded and aria-controls.",
                "Keep answers in the DOM when needed for screen-reader access.",
            ],
        ),
        ComponentCard(
            name="FooterNavigation",
            purpose="Provide product, support, legal, and accessibility links at the end of the page.",
            props=["link_groups", "legal_links", "social_links", "disclosure"],
            variants=["compact", "multi-column"],
            content_slots=["brand", "link_groups", "legal", "disclosure"],
            responsive_behavior="Stack link groups in a logical order and keep legal disclosures readable on mobile.",
            accessibility_notes=["Use a footer landmark and descriptive link labels."],
        ),
    ]


def _design_tokens(evidence: _EvidenceSummary) -> DesignTokens:
    if evidence.color_palette:
        return _palette_derived_tokens(evidence)

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


def _palette_derived_tokens(evidence: _EvidenceSummary) -> DesignTokens:
    """Turn locally measured colours into named tokens without inventing a SaaS palette."""

    palette = [color for color in evidence.color_palette if _hex_to_rgb(color) is not None]
    rgb_palette = [(color, _hex_to_rgb(color)) for color in palette]
    rgb_palette = [(color, rgb) for color, rgb in rgb_palette if rgb is not None]
    background = palette[0]
    surface = _first_color(
        rgb_palette,
        lambda rgb: _luminance(rgb) >= 0.78 and rgb != _hex_to_rgb(background),
    ) or ("#FFFFFF" if _luminance(_hex_to_rgb(background) or (255, 255, 255)) < 0.72 else "#F8FAFC")
    text = _first_color(rgb_palette, lambda rgb: _luminance(rgb) <= 0.22) or "#111111"
    accents = [
        color
        for color, rgb in rgb_palette
        if color != background and color != text and _saturation(rgb) >= 0.5
    ]
    accent = accents[0] if accents else background
    attention = accents[1] if len(accents) > 1 else accent
    rounded = evidence.mentions("pill", "rounded", "large-radius", "large radius")
    bold_display = evidence.mentions("display", "oversized", "bold", "heavy")
    return DesignTokens(
        colors={
            "background": background,
            "surface": surface,
            "text": text,
            "muted_text": _muted_text(text, surface),
            "accent": accent,
            "accent_attention": attention,
            "action_dark": text,
        },
        typography={
            "display": "clamp(3rem, 7vw, 5.5rem)" if bold_display else "clamp(2.5rem, 6vw, 4.5rem)",
            "heading": "2.25rem" if bold_display else "2rem",
            "body": "1rem",
        },
        spacing={"section": "clamp(4rem, 8vw, 7rem)", "card": "1.5rem", "stack": "1rem"},
        radius={"card": "2.5rem" if rounded else "1rem", "button": "999px" if rounded else "0.75rem"},
        shadow={"card": "0 16px 40px rgb(15 23 42 / 0.14)"},
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
    if _is_finance_goal(run.project_goal):
        tasks.extend(
            [
                BuildTask(
                    title="Implement finance states and disclosures",
                    priority="high",
                    acceptance_criteria=[
                        "Balance visibility, currency labels, trends, and goal progress have accessible text equivalents.",
                        "Fee, eligibility, and security claims are written as original product content and remain readable on mobile.",
                    ],
                ),
                BuildTask(
                    title="Implement the responsive conversion sections",
                    priority="medium",
                    acceptance_criteria=[
                        "Account choice, plan comparison, trust, testimonials, FAQ, and footer use the shared component system.",
                        "The mobile menu and accordion work with keyboard and screen-reader controls.",
                    ],
                ),
            ]
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


def _is_finance_goal(project_goal: str) -> bool:
    return bool(
        re.search(
            r"\b(finance|financial|bank|banking|budget|budgeting|invest|investment|saving|savings|money|loan|credit)\b",
            project_goal.casefold(),
        )
    )


def _first_color(
    palette: Sequence[tuple[str, tuple[int, int, int]]],
    predicate: object,
) -> str | None:
    """Return the first hex colour whose RGB value satisfies a small role heuristic."""

    for color, rgb in palette:
        if callable(predicate) and predicate(rgb):
            return color
    return None


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    normalized = value.strip().lstrip("#")
    if len(normalized) != 6 or any(character not in "0123456789abcdefABCDEF" for character in normalized):
        return None
    return tuple(int(normalized[index : index + 2], 16) for index in range(0, 6, 2))  # type: ignore[return-value]


def _luminance(color: tuple[int, int, int]) -> float:
    red, green, blue = (channel / 255 for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _saturation(color: tuple[int, int, int]) -> float:
    maximum = max(color)
    return 0.0 if maximum == 0 else (maximum - min(color)) / maximum


def _muted_text(text: str, surface: str) -> str:
    """Use a readable supporting-text fallback that contrasts with the measured surface."""

    text_rgb = _hex_to_rgb(text) or (17, 17, 17)
    surface_rgb = _hex_to_rgb(surface) or (255, 255, 255)
    return "#3D4355" if _luminance(surface_rgb) > _luminance(text_rgb) else "#D7DBE8"


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
