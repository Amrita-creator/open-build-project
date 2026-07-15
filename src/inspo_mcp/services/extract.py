"""Deterministic M4 extraction from captured, sanitized page text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from inspo_mcp.models.source import SourceRecord, SourceStatus, utc_now
from inspo_mcp.repositories.site_analyses import SiteAnalysisRepository
from inspo_mcp.schemas.site_analysis import (
    CallToActionEvidence,
    CardEvidence,
    HeadingEvidence,
    SectionEvidence,
    SiteStructureAnalysis,
)


_CTA_PATTERN = re.compile(
    r"^(?:get started|start(?: for free)?|try(?: it)?(?: free)?|sign up|"
    r"log in|learn more|book(?: a)? demo|request(?: a)? demo|contact(?: us)?|"
    r"join(?: now)?|subscribe|download|buy now|see pricing|view pricing)$",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    r"^(?:hero|features?|benefits?|how it works|integrations?|pricing|"
    r"testimonials?|customers?|security|resources?|faq|about|contact|footer)$",
    re.IGNORECASE,
)
_BULLET_PATTERN = re.compile(r"^[•*\-–]\s*(.+)$")


class StructureExtractor:
    """Infer conservative page structure without executing page HTML or scripts."""

    def __init__(self, repository: SiteAnalysisRepository) -> None:
        self._repository = repository

    def extract_and_store(
        self,
        sources: Sequence[SourceRecord],
    ) -> tuple[SiteStructureAnalysis, ...]:
        """Extract and persist structure for every source in a completed capture stage."""

        return tuple(self._repository.upsert(self.extract(source)) for source in sources)

    def extract(self, source: SourceRecord) -> SiteStructureAnalysis:
        """Create a source analysis or a precise reason M4 cannot extract one yet."""

        if source.status is SourceStatus.FAILED:
            return self._unavailable(source, "Source capture failed; no page evidence is available.")
        if not source.visible_text_path:
            if source.screenshot_path:
                return self._awaiting_vision(
                    source,
                    "Only screenshot evidence is available; M5 vision analysis is required.",
                )
            return self._unavailable(source, "The captured source has no visible text evidence.")

        try:
            text = Path(source.visible_text_path).read_text(encoding="utf-8")
        except OSError as error:
            return self._unavailable(source, f"Could not read captured visible text: {error}")

        lines = _normalized_lines(text)
        if not lines:
            return self._unavailable(source, "The captured visible text was empty.")

        return _extract_text_structure(source, lines)

    @staticmethod
    def _base(source: SourceRecord, *, status: str, message: str) -> SiteStructureAnalysis:
        return SiteStructureAnalysis(
            run_id=source.run_id,
            source_url=source.source_url,
            source_content_hash=source.content_hash,
            title=source.title,
            status=status,  # type: ignore[arg-type]
            extraction_message=message,
            extracted_at=utc_now(),
        )

    def _awaiting_vision(self, source: SourceRecord, message: str) -> SiteStructureAnalysis:
        return self._base(source, status="awaiting_vision", message=message)

    def _unavailable(self, source: SourceRecord, message: str) -> SiteStructureAnalysis:
        return self._base(source, status="unavailable", message=message)


def _extract_text_structure(source: SourceRecord, lines: list[str]) -> SiteStructureAnalysis:
    heading_indices = _heading_indices(lines)
    sections = _sections(lines, heading_indices)
    hierarchy = _hierarchy(lines, heading_indices, source.title)
    ctas = _ctas(lines, sections)
    cards = _cards(lines, sections, heading_indices)
    sections = _annotate_sections(sections, ctas, cards)
    return SiteStructureAnalysis(
        run_id=source.run_id,
        source_url=source.source_url,
        source_content_hash=source.content_hash,
        title=source.title,
        status="extracted",
        sections=sections,
        calls_to_action=ctas,
        cards=cards,
        hierarchy=hierarchy,
        extracted_at=utc_now(),
    )


def _normalized_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _heading_indices(lines: list[str]) -> list[int]:
    headings = [0]
    for index, line in enumerate(lines[1:], start=1):
        if _SECTION_PATTERN.match(line):
            headings.append(index)
    return headings


def _sections(lines: list[str], heading_indices: list[int]) -> list[SectionEvidence]:
    sections: list[SectionEvidence] = []
    for position, start in enumerate(heading_indices):
        end = heading_indices[position + 1] - 1 if position + 1 < len(heading_indices) else len(lines) - 1
        body_lines = lines[start : end + 1]
        section_name = body_lines[0]
        preview = " ".join(body_lines[1:])[:500]
        sections.append(
            SectionEvidence(
                name=section_name,
                heading_line_number=start + 1,
                end_line_number=end + 1,
                text_preview=preview,
            )
        )
    return sections


def _hierarchy(
    lines: list[str],
    heading_indices: list[int],
    title: str | None,
) -> list[HeadingEvidence]:
    hierarchy: list[HeadingEvidence] = []
    root = title or lines[0]
    hierarchy.append(HeadingEvidence(text=root, level=1, line_number=1))
    for index in heading_indices:
        if index == 0 and lines[index] == root:
            continue
        hierarchy.append(
            HeadingEvidence(text=lines[index], level=2, line_number=index + 1, parent=root)
        )
    return hierarchy


def _annotate_sections(
    sections: list[SectionEvidence],
    ctas: list[CallToActionEvidence],
    cards: list[CardEvidence],
) -> list[SectionEvidence]:
    return [
        section.model_copy(
            update={
                "cta_labels": [cta.label for cta in ctas if cta.section == section.name],
                "card_titles": [card.title for card in cards if card.section == section.name],
            }
        )
        for section in sections
    ]


def _ctas(lines: list[str], sections: list[SectionEvidence]) -> list[CallToActionEvidence]:
    ctas: list[CallToActionEvidence] = []
    for index, line in enumerate(lines):
        if _CTA_PATTERN.match(line):
            ctas.append(
                CallToActionEvidence(
                    label=line,
                    line_number=index + 1,
                    section=_section_for_line(index + 1, sections),
                    confidence="high",
                )
            )
    return ctas


def _cards(
    lines: list[str],
    sections: list[SectionEvidence],
    heading_indices: list[int],
) -> list[CardEvidence]:
    cards: list[CardEvidence] = []
    section_heading_indices = set(heading_indices)
    for index, line in enumerate(lines):
        bullet = _BULLET_PATTERN.match(line)
        if bullet:
            cards.append(
                CardEvidence(
                    title=bullet.group(1),
                    line_number=index + 1,
                    section=_section_for_line(index + 1, sections),
                    confidence="medium",
                )
            )
            continue
        if index in section_heading_indices or not _is_short_label(line):
            continue
        if index + 1 >= len(lines) or _is_short_label(lines[index + 1]):
            continue
        cards.append(
            CardEvidence(
                title=line,
                description=lines[index + 1],
                line_number=index + 1,
                section=_section_for_line(index + 1, sections),
                confidence="low",
            )
        )
    return cards


def _is_short_label(value: str) -> bool:
    return (
        1 <= len(value.split()) <= 6
        and len(value) <= 72
        and not value.rstrip().endswith((".", "!", "?", ";", ":"))
        and not _CTA_PATTERN.match(value)
    )


def _section_for_line(line_number: int, sections: list[SectionEvidence]) -> str | None:
    for section in sections:
        if section.heading_line_number <= line_number <= section.end_line_number:
            return section.name
    return None
