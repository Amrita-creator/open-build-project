"""Privacy controls for user input, captured evidence, and client-facing output."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit

from inspo_mcp.models.run import RunRecord
from inspo_mcp.schemas import ComponentCodeGeneration, InspirationKit, SourceWarning
from inspo_mcp.schemas.run_status import RunStatusReport
from inspo_mcp.schemas.vision_analysis import ScreenshotVisionAnalysis


class PrivacyInputError(ValueError):
    """Raised when a request appears to include a credential or secret."""


@dataclass(frozen=True)
class RedactionResult:
    """A redacted value and aggregate metadata about removed values."""

    text: str
    counts: dict[str, int]


_SECRET_ASSIGNMENT = re.compile(
    r"""\b(?:password|passwd|api[_ -]?key|secret|access[_ -]?token|auth(?:orization)?)
    \b\s*(?:=|:)\s*(?:bearer\s+)?['\"]?[^\s,;'\"]{6,}""",
    flags=re.IGNORECASE | re.VERBOSE,
)
_BEARER_TOKEN = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", flags=re.IGNORECASE)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    flags=re.DOTALL,
)
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_OPENAI_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?)\d{3,4}[ .-]\d{4}(?!\w)")
_PAYMENT_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_URL = re.compile(r"https?://[^\s<>()\[\]{}]+", flags=re.IGNORECASE)
_SENSITIVE_QUERY_KEYS = frozenset(
    {"access_token", "api_key", "apikey", "auth", "authorization", "key", "password", "secret", "token"}
)


def reject_request_secrets(project_goal: str, urls: Iterable[str]) -> None:
    """Block credentials before they reach storage, logs, or model context."""

    if _secret_kind(project_goal) is not None:
        raise PrivacyInputError(
            "Do not submit passwords, API keys, bearer tokens, or private keys to InspoMCP."
        )
    for url in urls:
        if _secret_kind(url) is not None or _url_has_sensitive_query(url):
            raise PrivacyInputError(
                "Inspiration URLs must not contain passwords, API keys, tokens, or secret query parameters."
            )


def redact_text(value: str | None) -> RedactionResult:
    """Mask common credentials and PII without preserving the matches."""

    if not value:
        return RedactionResult(text=value or "", counts={})

    counts: Counter[str] = Counter()
    result = value
    for pattern, label, replacement in (
        (_PRIVATE_KEY, "secrets", "[REDACTED_PRIVATE_KEY]"),
        (_SECRET_ASSIGNMENT, "secrets", "[REDACTED_SECRET]"),
        (_BEARER_TOKEN, "secrets", "[REDACTED_SECRET]"),
        (_GITHUB_TOKEN, "secrets", "[REDACTED_SECRET]"),
        (_OPENAI_SECRET, "secrets", "[REDACTED_SECRET]"),
        (_JWT, "secrets", "[REDACTED_SECRET]"),
        (_EMAIL, "emails", "[REDACTED_EMAIL]"),
        (_PAYMENT_NUMBER, "payment_numbers", "[REDACTED_PAYMENT_NUMBER]"),
        (_PHONE, "phone_numbers", "[REDACTED_PHONE]"),
    ):
        result, replaced = pattern.subn(replacement, result)
        counts[label] += replaced
    return RedactionResult(text=result, counts=dict(counts))


def redact_page_values(values: Iterable[str]) -> tuple[list[str], dict[str, int]]:
    """Redact evidence strings and return only aggregate count metadata."""

    counts: Counter[str] = Counter()
    redacted: list[str] = []
    for value in values:
        result = redact_text(value)
        redacted.append(result.text)
        counts.update(result.counts)
    return redacted, dict(counts)


def source_label(run: RunRecord, source_identifier: str) -> str:
    """Use an opaque, stable reference label for privacy-mode client output."""

    if not run.privacy_mode:
        return source_identifier
    reference_id = hashlib.sha256(source_identifier.encode("utf-8")).hexdigest()[:8]
    return f"Reference {reference_id}"


def sanitize_output_text(value: str | None, *, private_mode: bool) -> str | None:
    """Redact PII everywhere and hide URLs from private client-facing output."""

    if value is None:
        return None
    safe = redact_text(value).text
    return _URL.sub("[REDACTED_URL]", safe) if private_mode else safe


def mask_warnings(run: RunRecord, warnings: Iterable[SourceWarning]) -> list[SourceWarning]:
    """Mask source identities and sensitive message fragments in warnings."""

    return [
        warning.model_copy(
            update={
                "url": source_label(run, warning.url),
                "message": sanitize_output_text(warning.message, private_mode=run.privacy_mode)
                or "Sensitive detail removed.",
            }
        )
        for warning in warnings
    ]


def mask_kit(run: RunRecord, kit: InspirationKit) -> InspirationKit:
    """Return a client-safe kit without altering the durable stored record."""

    return kit.model_copy(update={"warnings": mask_warnings(run, kit.warnings)})


def mask_component_generation(run: RunRecord, generation: ComponentCodeGeneration) -> ComponentCodeGeneration:
    """Return generated-code metadata with privacy-safe warnings."""

    return generation.model_copy(update={"warnings": mask_warnings(run, generation.warnings)})


def mask_run_status(run: RunRecord, report: RunStatusReport) -> RunStatusReport:
    """Remove source names, URLs, and common PII from a status response."""

    return report.model_copy(
        update={
            "sources": [
                source.model_copy(
                    update={
                        "source_url": source_label(run, source.source_url),
                        "message": sanitize_output_text(source.message, private_mode=run.privacy_mode),
                    }
                )
                for source in report.sources
            ],
            "warnings": mask_warnings(run, report.warnings),
            "error_message": sanitize_output_text(report.error_message, private_mode=run.privacy_mode),
        }
    )


def mask_vision_analysis(run: RunRecord, analysis: ScreenshotVisionAnalysis) -> ScreenshotVisionAnalysis:
    """Return visual findings with opaque sources and redacted text values."""

    def strings(values: list[str]) -> list[str]:
        return [sanitize_output_text(value, private_mode=run.privacy_mode) or "" for value in values]

    return analysis.model_copy(
        update={
            "source_url": source_label(run, analysis.source_url),
            "summary": sanitize_output_text(analysis.summary, private_mode=run.privacy_mode),
            "visual_style": strings(analysis.visual_style),
            "layout_patterns": strings(analysis.layout_patterns),
            "component_patterns": strings(analysis.component_patterns),
            "color_direction": strings(analysis.color_direction),
            "text_mismatches": strings(analysis.text_mismatches),
            "message": sanitize_output_text(analysis.message, private_mode=run.privacy_mode),
        }
    )


def privacy_guidance() -> str:
    """Return the client-readable privacy guidance resource."""

    return """# InspoMCP privacy and data handling

Never submit passwords, API keys, bearer tokens, private keys, customer records,
or confidential screenshots. InspoMCP rejects obvious credentials and redacts
common emails, phone numbers, payment-number-like values, and secret patterns
from captured text before analysis is persisted.

Enable privacy mode for opaque reference labels in client responses. Crop or blur
confidential visual details before supplying screenshots: automated text redaction
cannot reliably detect every detail inside an image. Runs have a retention expiry
and can be deleted. This server uses a shared bearer token, so it must be treated
as single-tenant until per-user authentication and authorization are configured.
"""


def _secret_kind(value: str) -> str | None:
    for pattern, label in (
        (_SECRET_ASSIGNMENT, "credential assignment"),
        (_BEARER_TOKEN, "bearer token"),
        (_PRIVATE_KEY, "private key"),
        (_GITHUB_TOKEN, "access token"),
        (_OPENAI_SECRET, "API key"),
        (_JWT, "JWT"),
    ):
        if pattern.search(value):
            return label
    return None


def _url_has_sensitive_query(url: str) -> bool:
    try:
        query = urlsplit(url).query
    except ValueError:
        return True
    return any(key.casefold() in _SENSITIVE_QUERY_KEYS and value for key, value in parse_qsl(query))
