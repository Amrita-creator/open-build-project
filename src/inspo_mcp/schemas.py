"""Typed contracts for the InspoMCP tools and their artifacts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


Framework = Literal["nextjs-tailwind", "react-css", "framework-agnostic"]
Priority = Literal["high", "medium", "low"]


class ScreenshotFallback(BaseModel):
    """A local user-provided screenshot that corresponds to one source URL."""

    source_url: HttpUrl
    image_path: str = Field(
        min_length=1,
        max_length=1024,
        description="Absolute path to a PNG, JPEG, or WebP screenshot supplied by the user.",
    )


class InspirationRequest(BaseModel):
    """Validated input for a design-inspiration analysis run."""

    inspiration_urls: list[HttpUrl] = Field(
        min_length=2,
        max_length=3,
        description="Two or three public UI-inspiration URLs.",
    )
    project_goal: str = Field(
        min_length=10,
        max_length=500,
        description="What the user wants to build.",
    )
    framework: Framework = Field(
        default="nextjs-tailwind",
        description="Target stack for the optional implementation guidance.",
    )
    fallback_screenshots: list[ScreenshotFallback] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Optional user-supplied screenshot fallbacks, one per inspiration URL. "
            "They are used only when automatic capture is blocked or fails."
        ),
    )

    @model_validator(mode="after")
    def validate_fallback_screenshots(self) -> "InspirationRequest":
        source_urls = {str(url) for url in self.inspiration_urls}
        fallback_urls = [str(fallback.source_url) for fallback in self.fallback_screenshots]
        unknown_urls = set(fallback_urls) - source_urls
        if unknown_urls:
            raise ValueError(
                "Each fallback screenshot must reference an inspiration URL in this request."
            )
        if len(set(fallback_urls)) != len(fallback_urls):
            raise ValueError("Only one fallback screenshot is allowed per inspiration URL.")
        return self

    @property
    def fallback_screenshot_map(self) -> dict[str, str]:
        """Map normalized source URLs to their user-provided image paths."""

        return {
            str(fallback.source_url): fallback.image_path
            for fallback in self.fallback_screenshots
        }


class DesignDirection(BaseModel):
    summary: str
    visual_style: list[str]
    principles: list[str]
    avoid: list[str]


class PageSection(BaseModel):
    name: str
    purpose: str
    suggested_components: list[str]


class PageBlueprint(BaseModel):
    summary: str
    sections: list[PageSection]


class ComponentCard(BaseModel):
    name: str
    purpose: str
    props: list[str]
    variants: list[str]
    content_slots: list[str]
    responsive_behavior: str
    accessibility_notes: list[str]


class DesignTokens(BaseModel):
    colors: dict[str, str]
    typography: dict[str, str]
    spacing: dict[str, str]
    radius: dict[str, str]
    shadow: dict[str, str]


class BuildTask(BaseModel):
    title: str
    priority: Priority
    acceptance_criteria: list[str]


class SourceWarning(BaseModel):
    url: str
    message: str


class InspirationKit(BaseModel):
    """The five reusable artifacts returned by the primary MCP tool."""

    run_id: str
    design_direction: DesignDirection
    page_blueprint: PageBlueprint
    component_cards: list[ComponentCard]
    design_tokens: DesignTokens
    build_tasks: list[BuildTask]
    warnings: list[SourceWarning] = Field(default_factory=list)
    is_mock: bool = True
