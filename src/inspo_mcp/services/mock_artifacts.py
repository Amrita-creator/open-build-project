"""Deterministic placeholder artifacts for the Phase 1 server."""

from __future__ import annotations

from inspo_mcp.schemas import (
    BuildTask,
    ComponentCard,
    DesignDirection,
    DesignTokens,
    InspirationKit,
    InspirationRequest,
    PageBlueprint,
    PageSection,
)


def create_mock_kit(
    request: InspirationRequest,
    *,
    run_id: str | None = None,
) -> InspirationKit:
    """Return a stable-shaped kit before real capture and AI analysis exist."""

    return InspirationKit(
        run_id=run_id or "mock_unsaved",
        design_direction=DesignDirection(
            summary=(
                "A polished SaaS direction with a clear product story, restrained "
                "contrast, and reusable conversion-focused sections."
            ),
            visual_style=["premium SaaS", "clean hierarchy", "subtle gradients"],
            principles=[
                "Lead with one focused product promise.",
                "Use consistent card anatomy across sections.",
                "Reserve visual contrast for important actions.",
            ],
            avoid=[
                "Copying source-site layouts or text.",
                "Using decorative effects that weaken readability.",
            ],
        ),
        page_blueprint=PageBlueprint(
            summary=f"A landing-page blueprint aligned to: {request.project_goal}",
            sections=[
                PageSection(
                    name="Hero",
                    purpose="State the product promise and primary call to action.",
                    suggested_components=["GradientHero", "PrimaryCTA"],
                ),
                PageSection(
                    name="Product value",
                    purpose="Explain the most important benefits with visual proof.",
                    suggested_components=["FeatureBentoGrid", "MetricCard"],
                ),
                PageSection(
                    name="Closing CTA",
                    purpose="Give the visitor one clear next step.",
                    suggested_components=["StickyCTA"],
                ),
            ],
        ),
        component_cards=[
            ComponentCard(
                name="FeatureBentoGrid",
                purpose="Present several product benefits with clear hierarchy.",
                props=["items", "variant", "class_name"],
                variants=["light", "dark"],
                content_slots=["eyebrow", "heading", "body", "visual"],
                responsive_behavior="Three columns on desktop; one column on mobile.",
                accessibility_notes=[
                    "Use a semantic section and ordered heading hierarchy.",
                    "Do not place essential content only inside imagery.",
                ],
            ),
            ComponentCard(
                name="MetricCard",
                purpose="Highlight one proof point or product outcome.",
                props=["label", "value", "supporting_text", "trend"],
                variants=["default", "emphasized"],
                content_slots=["label", "value", "supporting_text"],
                responsive_behavior="Stack label and value in narrow containers.",
                accessibility_notes=[
                    "Express the metric in text, not color alone.",
                ],
            ),
        ],
        design_tokens=DesignTokens(
            colors={
                "background": "#0B1020",
                "surface": "#141B33",
                "text": "#F8FAFC",
                "muted_text": "#B6C2D9",
                "accent": "#8B5CF6",
            },
            typography={"display": "3rem", "heading": "2rem", "body": "1rem"},
            spacing={"section": "6rem", "card": "1.5rem", "stack": "1rem"},
            radius={"card": "1rem", "button": "0.625rem"},
            shadow={"card": "0 16px 48px rgb(0 0 0 / 0.18)"},
        ),
        build_tasks=[
            BuildTask(
                title="Create the shared design-token layer",
                priority="high",
                acceptance_criteria=[
                    "Color, typography, spacing, radius, and shadow tokens are defined.",
                    "Components consume tokens rather than hard-coded repeated values.",
                ],
            ),
            BuildTask(
                title="Implement FeatureBentoGrid",
                priority="high",
                acceptance_criteria=[
                    "The component supports light and dark variants.",
                    "The layout is responsive and keyboard-accessible.",
                ],
            ),
        ],
    )
