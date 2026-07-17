"""Typed contracts for the InspoMCP tools and their artifacts."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


Framework = Literal["nextjs-tailwind", "react-css", "framework-agnostic"]
Priority = Literal["high", "medium", "low"]


class ScreenshotFallback(BaseModel):
    """Legacy fallback used only after automatic capture of one source URL fails."""

    source_url: HttpUrl
    image_path: str = Field(
        min_length=1,
        max_length=1024,
        description="Absolute path to a PNG, JPEG, or WebP screenshot supplied by the user.",
    )


class InspirationScreenshot(BaseModel):
    """Primary visual evidence supplied directly by the user.

    A source URL is optional. When present, the screenshot is preferred over an
    automated request to that URL; when absent, it is still a complete source
    for M5 vision analysis.
    """

    image_path: str = Field(
        min_length=1,
        max_length=1024,
        description="Absolute path to a PNG, JPEG, or WebP inspiration screenshot.",
    )
    source_url: HttpUrl | None = Field(
        default=None,
        description="Optional original page URL for attribution and text enrichment.",
    )
    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Optional short name for a screenshot-only inspiration source.",
    )

    @property
    def source_identifier(self) -> str:
        """Return a stable, non-path-revealing identity for persisted evidence."""

        if self.source_url is not None:
            return str(self.source_url)
        digest = hashlib.sha256(self.image_path.encode("utf-8")).hexdigest()[:16]
        return f"user-screenshot://{digest}"


class InspirationRequest(BaseModel):
    """Validated input for a design-inspiration analysis run."""

    inspiration_urls: list[HttpUrl] = Field(
        default_factory=list,
        max_length=3,
        description="Optional public UI-inspiration URLs for text and screenshot enrichment.",
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
    privacy_mode: bool = Field(
        default=False,
        description=(
            "Hide source identities in client-facing output. The main MCP tool enables this by default."
        ),
    )
    retention_days: int = Field(
        default=30,
        ge=1,
        le=90,
        description="How long captured evidence and durable run data may be retained.",
    )
    inspiration_screenshots: list[InspirationScreenshot] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Primary screenshot evidence. Supply two or three total inspiration sources "
            "across URLs and screenshots. A screenshot mapped to a URL takes priority "
            "over automated capture."
        ),
    )
    fallback_screenshots: list[ScreenshotFallback] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Legacy URL-mapped fallbacks, used only when automatic capture fails. "
            "Prefer inspiration_screenshots for new integrations."
        ),
    )

    @model_validator(mode="after")
    def validate_sources(self) -> "InspirationRequest":
        source_keys: set[str] = {str(url) for url in self.inspiration_urls}
        primary_keys = [screenshot.source_identifier for screenshot in self.inspiration_screenshots]
        if len(set(primary_keys)) != len(primary_keys):
            raise ValueError("Only one primary screenshot is allowed per inspiration source.")
        source_keys.update(primary_keys)
        if not 2 <= len(source_keys) <= 3:
            raise ValueError(
                "Provide two or three total inspiration sources across inspiration_urls "
                "and inspiration_screenshots."
            )

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

    @property
    def primary_screenshot_url_keys(self) -> frozenset[str]:
        """Return URL sources whose visual evidence was supplied by the user."""

        return frozenset(
            str(screenshot.source_url)
            for screenshot in self.inspiration_screenshots
            if screenshot.source_url is not None
        )

    @property
    def source_identifiers(self) -> tuple[str, ...]:
        """Return the ordered, unique sources persisted for one run."""

        identifiers: list[str] = []
        for url in self.inspiration_urls:
            identifier = str(url)
            if identifier not in identifiers:
                identifiers.append(identifier)
        for screenshot in self.inspiration_screenshots:
            identifier = screenshot.source_identifier
            if identifier not in identifiers:
                identifiers.append(identifier)
        return tuple(identifiers)


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


class GeneratedCodeFile(BaseModel):
    """One source file generated for a single reusable component."""

    path: str
    language: Literal["tsx", "css", "html"]
    content: str


class ComponentCodeGeneration(BaseModel):
    """Framework-specific starter code derived from one persisted component card."""

    run_id: str
    component_name: str
    framework: Framework
    files: list[GeneratedCodeFile] = Field(min_length=1, max_length=2)
    dependencies: list[str] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)
    warnings: list[SourceWarning] = Field(default_factory=list)


from .vision_analysis import ScreenshotVisionAnalysis
from .run_status import KitLookup, RunStatusReport, SourceProgress

__all__ = [
    "BuildTask",
    "ComponentCard",
    "ComponentCodeGeneration",
    "DesignDirection",
    "DesignTokens",
    "Framework",
    "GeneratedCodeFile",
    "InspirationKit",
    "InspirationRequest",
    "InspirationScreenshot",
    "KitLookup",
    "PageBlueprint",
    "PageSection",
    "ScreenshotFallback",
    "ScreenshotVisionAnalysis",
    "RunStatusReport",
    "SourceProgress",
    "SourceWarning",
]
