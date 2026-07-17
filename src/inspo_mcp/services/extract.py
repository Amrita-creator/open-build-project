"""Deterministic M4 extraction from captured text and semantic HTML evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Sequence

from inspo_mcp.models.source import SemanticBlock, SourceRecord, SourceStatus, utc_now
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
_BULLET_PATTERN = re.compile(r"^[\u2022*\-\u2013]\s*(.+)$")
_EXCLUDED_REGIONS = frozenset({"nav", "footer"})
_GENERIC_CARD_LABELS = frozenset(
    {
        "news",
        "latest",
        "featured",
        "feature",
        "video",
        "videos",
        "more",
        "explore",
        "read more",
        "view more",
    }
)


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

        semantic_blocks = _load_semantic_blocks(source.semantic_document_path)
        if semantic_blocks:
            semantic_analysis = _extract_semantic_structure(source, semantic_blocks)
            if semantic_analysis is not None:
                return semantic_analysis

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


def _load_semantic_blocks(path: str | None) -> tuple[SemanticBlock, ...]:
    """Read valid semantic sidecar blocks; older captures safely fall back to text."""

    if not path:
        return ()
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_blocks = payload.get("blocks") if isinstance(payload, dict) else None
        if not isinstance(raw_blocks, list):
            return ()
        return tuple(SemanticBlock.from_dict(block) for block in raw_blocks)
    except (OSError, ValueError, json.JSONDecodeError):
        return ()


def _extract_semantic_structure(
    source: SourceRecord,
    blocks: Sequence[SemanticBlock],
) -> SiteStructureAnalysis | None:
    """Extract from DOM boundaries, omitting chrome before text heuristics run."""

    lines: list[str] = []
    explicit_heading_indices: set[int] = set()
    card_anchor_lines: dict[int, int] = {}
    for block_index, block in enumerate(blocks):
        if not _is_page_content_block(block):
            continue
        if block.kind == "card":
            card_anchor_lines[block_index] = max(1, len(lines))
            continue
        if block.kind not in {"heading", "paragraph", "list_item"}:
            continue
        for line in _normalized_lines(block.text):
            lines.append(line)
            if block.kind == "heading":
                explicit_heading_indices.add(len(lines) - 1)

    if not lines:
        return None

    heading_indices = _heading_indices(lines, explicit_heading_indices)
    sections = _sections(lines, heading_indices)
    hierarchy = _hierarchy(lines, heading_indices, source.title)
    ctas = _ctas(lines, sections)
    semantic_cards = _semantic_cards(blocks, sections, card_anchor_lines)
    heuristic_cards = _cards(lines, sections, heading_indices)
    cards = _deduplicate_cards([*semantic_cards, *heuristic_cards])
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


def _is_page_content_block(block: SemanticBlock) -> bool:
    """Keep meaningful page content while excluding navigation and footer chrome."""

    ancestry = set(block.ancestry)
    if ancestry & _EXCLUDED_REGIONS:
        return False
    # Header is preserved in the sidecar but commonly contains site navigation.
    # Its H1/H2 headings remain useful; labels, lists, and cards do not.
    return not ("header" in ancestry and block.kind in {"paragraph", "list_item", "card"})


def _extract_text_structure(
    source: SourceRecord,
    lines: list[str],
) -> SiteStructureAnalysis:
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


def _heading_indices(
    lines: list[str],
    explicit_heading_indices: set[int] | None = None,
) -> list[int]:
    headings = [0]
    explicit = explicit_heading_indices or set()
    for index, line in enumerate(lines[1:], start=1):
        if index in explicit or _SECTION_PATTERN.match(line):
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


def _semantic_cards(
    blocks: Sequence[SemanticBlock],
    sections: list[SectionEvidence],
    anchor_lines: dict[int, int],
) -> list[CardEvidence]:
    """Turn explicit card boundaries into candidates before applying deduplication."""

    cards: list[CardEvidence] = []
    for block_index, block in enumerate(blocks):
        if block.kind != "card" or not _is_page_content_block(block):
            continue
        card_lines = _normalized_lines(block.text)
        if not card_lines:
            continue
        title = card_lines[0]
        if _is_generic_card_label(title) or not _is_short_label(title):
            continue
        line_number = anchor_lines.get(block_index, 1)
        cards.append(
            CardEvidence(
                title=title,
                description=" ".join(card_lines[1:]) or None,
                line_number=line_number,
                section=_section_for_line(line_number, sections),
                confidence="high",
            )
        )
    return cards


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
            title = bullet.group(1)
            if not _is_generic_card_label(title):
                cards.append(
                    CardEvidence(
                        title=title,
                        line_number=index + 1,
                        section=_section_for_line(index + 1, sections),
                        confidence="medium",
                    )
                )
            continue
        if index in section_heading_indices or _is_generic_card_label(line) or not _is_short_label(line):
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
    return _deduplicate_cards(cards)


def _deduplicate_cards(cards: Sequence[CardEvidence]) -> list[CardEvidence]:
    """Avoid emitting the same UI card label repeatedly across a source page."""

    deduplicated: list[CardEvidence] = []
    seen_titles: set[str] = set()
    for card in cards:
        key = _normalized_label(card.title)
        if not key or key in seen_titles or _is_generic_card_label(card.title):
            continue
        seen_titles.add(key)
        deduplicated.append(card)
    return deduplicated


def _is_generic_card_label(value: str) -> bool:
    return _normalized_label(value) in _GENERIC_CARD_LABELS


def _normalized_label(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


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
