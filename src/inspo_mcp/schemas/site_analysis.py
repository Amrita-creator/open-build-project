"""Structured page evidence extracted from a captured inspiration source."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ExtractionStatus = Literal["extracted", "awaiting_vision", "unavailable"]
EvidenceConfidence = Literal["high", "medium", "low"]


class HeadingEvidence(BaseModel):
    """One inferred heading in the page's textual hierarchy."""

    text: str
    level: int = Field(ge=1, le=6)
    line_number: int = Field(ge=1)
    parent: str | None = None


class CallToActionEvidence(BaseModel):
    """A visible action label found in captured page text."""

    label: str
    line_number: int = Field(ge=1)
    section: str | None = None
    confidence: EvidenceConfidence


class CardEvidence(BaseModel):
    """A repeated title-and-description pattern that may represent a UI card."""

    title: str
    description: str | None = None
    line_number: int = Field(ge=1)
    section: str | None = None
    confidence: EvidenceConfidence


class SectionEvidence(BaseModel):
    """A page region inferred from a heading and its following visible text."""

    name: str
    heading_line_number: int = Field(ge=1)
    end_line_number: int = Field(ge=1)
    text_preview: str = Field(max_length=500)
    cta_labels: list[str] = Field(default_factory=list)
    card_titles: list[str] = Field(default_factory=list)


class SiteStructureAnalysis(BaseModel):
    """Durable M4 structure extraction for one captured source."""

    run_id: str
    source_url: str
    source_content_hash: str | None = None
    title: str | None = None
    status: ExtractionStatus
    sections: list[SectionEvidence] = Field(default_factory=list)
    calls_to_action: list[CallToActionEvidence] = Field(default_factory=list)
    cards: list[CardEvidence] = Field(default_factory=list)
    hierarchy: list[HeadingEvidence] = Field(default_factory=list)
    extraction_message: str | None = None
    extracted_at: str
