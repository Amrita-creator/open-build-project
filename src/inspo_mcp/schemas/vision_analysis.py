"""Durable M5 visual evidence inferred from a page or user screenshot."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


VisionStatus = Literal["pending", "completed", "not_configured", "failed", "not_applicable"]
TextAlignment = Literal["aligned", "partial", "not_available"]


class ScreenshotVisionAnalysis(BaseModel):
    """Vision-derived UI patterns, deliberately separated from generated UI kits."""

    run_id: str
    source_url: str
    source_content_hash: str | None = None
    status: VisionStatus
    summary: str | None = None
    visual_style: list[str] = Field(default_factory=list, max_length=8)
    layout_patterns: list[str] = Field(default_factory=list, max_length=12)
    component_patterns: list[str] = Field(default_factory=list, max_length=12)
    color_direction: list[str] = Field(default_factory=list, max_length=8)
    text_alignment: TextAlignment = "not_available"
    text_mismatches: list[str] = Field(default_factory=list, max_length=8)
    message: str | None = None
    analyzed_at: str
