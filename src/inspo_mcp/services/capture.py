"""Safely capture durable source evidence for later extraction and analysis."""

from __future__ import annotations

import asyncio
import hashlib
import re
import socket
import time
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import HttpUrl, ValidationError
from inspo_mcp.models.source import SemanticBlock, SourceRecord, SourceStatus, utc_now
from inspo_mcp.repositories.sources import SourceRepository
from inspo_mcp.schemas import InspirationScreenshot
from inspo_mcp.services.privacy import redact_page_values, redact_text
from inspo_mcp.services.url_safety import SafeUrl, UrlSafetyError, validate_public_urls
from inspo_mcp.storage.capture_store import LocalCaptureStore


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SUPPORTED_MEDIA_TYPES = frozenset({"", "text/html", "application/xhtml+xml", "text/plain"})
_SKIP_TEXT_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "canvas"})
_BLOCK_TEXT_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)
_SEMANTIC_CONTAINER_TAGS = frozenset(
    {"header", "nav", "main", "section", "article", "aside", "footer"}
)
_SEMANTIC_TEXT_TAGS = frozenset({"p", "li"})
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
_CARD_MARKERS = frozenset({"card", "tile", "panel", "bento"})


class CaptureError(RuntimeError):
    """Raised when a source cannot be safely captured into usable evidence."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        final_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.final_url = final_url


@dataclass(frozen=True)
class CaptureSettings:
    """Bounded network and artifact settings for one source capture."""

    request_timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_response_bytes: int = 2_000_000
    max_visible_text_chars: int = 100_000
    max_user_screenshot_bytes: int = 10_000_000
    min_host_request_interval_seconds: float = 1.0
    screenshot_timeout_milliseconds: int = 30_000
    screenshot_settle_milliseconds: int = 500
    user_agent: str = "InspoMCP/0.1 (contact: configure INSPO_MCP_CONTACT_EMAIL)"


@dataclass(frozen=True)
class FetchedResponse:
    """The bounded HTTP response used to produce capture evidence."""

    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class SanitizedPage:
    """The non-executable page evidence retained after HTML sanitization."""

    title: str | None
    visible_text: str
    semantic_blocks: tuple[SemanticBlock, ...]
    redaction_counts: dict[str, int]


class PageFetcher(Protocol):
    """Fetch one URL without automatically following redirects."""

    async def get(self, url: str) -> FetchedResponse:
        """Return the response for ``url`` or raise an exception."""


class Screenshotter(Protocol):
    """Create a screenshot at a caller-provided path."""

    async def capture(self, url: str, output_path: Path) -> None:
        """Render ``url`` and write a PNG to ``output_path``."""


class HttpxPageFetcher:
    """Bounded HTTP fetcher that leaves redirects to :class:`CaptureService`."""

    def __init__(self, settings: CaptureSettings) -> None:
        self._settings = settings

    async def get(self, url: str) -> FetchedResponse:
        timeout = httpx.Timeout(self._settings.request_timeout_seconds)
        headers = {
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": self._settings.user_agent,
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                headers=headers,
                timeout=timeout,
                trust_env=False,
            ) as client:
                async with client.stream("GET", url) as response:
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self._settings.max_response_bytes:
                        raise CaptureError(
                            "Response exceeds the configured download limit "
                            f"({self._settings.max_response_bytes} bytes)."
                        )

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._settings.max_response_bytes:
                            raise CaptureError(
                                "Response exceeds the configured download limit "
                                f"({self._settings.max_response_bytes} bytes)."
                            )

                    return FetchedResponse(
                        url=str(response.url),
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        body=bytes(body),
                    )
        except CaptureError:
            raise
        except httpx.HTTPError as error:
            raise CaptureError(f"HTTP capture failed: {error}") from error
        except ValueError as error:
            raise CaptureError(f"Invalid HTTP response metadata: {error}") from error


class PlaywrightScreenshotter:
    """Render a page with Chromium while validating every routed network URL."""

    def __init__(
        self,
        settings: CaptureSettings,
        *,
        resolver: object = socket.getaddrinfo,
    ) -> None:
        self._settings = settings
        self._resolver = resolver

    async def capture(self, url: str, output_path: Path) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise CaptureError(
                "Screenshot capture requires Playwright. Install project dependencies "
                "and run 'python -m playwright install chromium'."
            ) from error

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                try:
                    context = await browser.new_context(
                        viewport={"width": 1440, "height": 1080},
                        user_agent=self._settings.user_agent,
                    )
                    try:
                        page = await context.new_page()

                        async def validate_routed_request(route: object) -> None:
                            request_url = route.request.url
                            scheme = urlsplit(request_url).scheme.lower()
                            if scheme in {"about", "blob", "data"}:
                                await route.continue_()
                                return
                            try:
                                self._validate_browser_url(request_url)
                            except CaptureError:
                                await route.abort()
                                return
                            await route.continue_()

                        await page.route("**/*", validate_routed_request)
                        response = await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=self._settings.screenshot_timeout_milliseconds,
                        )
                        if response is None:
                            raise CaptureError("Browser navigation did not receive a response.")
                        if response.status >= 400:
                            raise CaptureError(
                                f"Screenshot navigation returned HTTP {response.status}."
                            )
                        await page.wait_for_timeout(self._settings.screenshot_settle_milliseconds)
                        await page.screenshot(path=str(output_path), full_page=True, type="png")
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except CaptureError:
            raise
        except Exception as error:
            raise CaptureError(f"Screenshot capture failed: {error}") from error

    def _validate_browser_url(self, url: str) -> None:
        try:
            validate_public_urls([HttpUrl(url)], resolver=self._resolver)
        except (UrlSafetyError, ValidationError, ValueError) as error:
            raise CaptureError(f"Blocked unsafe browser request: {url}") from error


class CaptureService:
    """Capture, cache, and persist one evidence record for every safe source."""

    def __init__(
        self,
        repository: SourceRepository,
        store: LocalCaptureStore,
        *,
        settings: CaptureSettings | None = None,
        fetcher: PageFetcher | None = None,
        screenshotter: Screenshotter | None = None,
        resolver: object = socket.getaddrinfo,
    ) -> None:
        self._repository = repository
        self._store = store
        self._settings = settings or CaptureSettings()
        self._resolver = resolver
        self._fetcher = fetcher or HttpxPageFetcher(self._settings)
        self._screenshotter = screenshotter or PlaywrightScreenshotter(
            self._settings,
            resolver=resolver,
        )
        self._host_request_times: dict[str, float] = {}
        self._host_pacing_lock = asyncio.Lock()

    async def capture_sources(
        self,
        run_id: str,
        sources: Sequence[SafeUrl],
        *,
        fallback_screenshots: Mapping[str, str] | None = None,
    ) -> tuple[SourceRecord, ...]:
        """Return evidence records, preferring user images when automatic capture fails."""

        existing = {record.source_url: record for record in self._repository.list_for_run(run_id)}
        fallbacks = fallback_screenshots or {}
        captured: list[SourceRecord] = []
        for source in sources:
            previous = existing.get(source.url)
            if previous:
                if previous.status is SourceStatus.CAPTURED and self._store.has_complete_evidence(
                    previous.visible_text_path,
                    previous.screenshot_path,
                    previous.semantic_document_path,
                ):
                    captured.append(previous)
                    continue
                if previous.status is SourceStatus.USER_PROVIDED and self._store.has_screenshot(
                    previous.screenshot_path
                ):
                    captured.append(previous)
                    continue
            captured.append(
                await self._capture_source(
                    run_id,
                    source,
                    fallback_screenshot_path=fallbacks.get(source.url),
                )
            )
        return tuple(captured)

    async def capture_primary_screenshots(
        self,
        run_id: str,
        screenshots: Sequence[InspirationScreenshot],
    ) -> tuple[SourceRecord, ...]:
        """Persist user screenshots as the primary visual evidence for a run.

        No request is made to an optional URL here. URL text enrichment happens
        separately and never replaces the user-provided visual artifact.
        """

        existing = {record.source_url: record for record in self._repository.list_for_run(run_id)}
        sources: list[SourceRecord] = []
        for screenshot in screenshots:
            source_identifier = screenshot.source_identifier
            previous = existing.get(source_identifier)
            if previous and previous.status is SourceStatus.USER_PROVIDED and self._store.has_screenshot(
                previous.screenshot_path
            ):
                sources.append(previous)
                continue

            image_path = self._store.save_user_screenshot(
                run_id,
                source_identifier,
                screenshot.image_path,
                max_bytes=self._settings.max_user_screenshot_bytes,
            )
            label = redact_text(screenshot.label)
            source = SourceRecord(
                run_id=run_id,
                source_url=source_identifier,
                final_url=str(screenshot.source_url) if screenshot.source_url is not None else None,
                status=SourceStatus.USER_PROVIDED,
                http_status=None,
                title=label.text or None,
                visible_text_path=None,
                screenshot_path=str(image_path),
                content_hash=_hash_file(image_path),
                redirect_chain=(source_identifier,),
                captured_at=utc_now(),
                capture_note=(
                    "User-provided screenshot accepted as primary visual evidence. "
                    "It can be compared with any available text evidence during M5 vision analysis."
                ),
                redaction_counts=label.counts,
            )
            sources.append(self._repository.upsert(source))
        return tuple(sources)

    async def enrich_primary_screenshots(
        self,
        run_id: str,
        sources: Sequence[SafeUrl],
    ) -> tuple[SourceRecord, ...]:
        """Add text/semantic evidence to primary screenshots without recapturing visuals."""

        existing = {record.source_url: record for record in self._repository.list_for_run(run_id)}
        enriched: list[SourceRecord] = []
        for source in sources:
            primary = existing.get(source.url)
            if primary is None or primary.status is not SourceStatus.USER_PROVIDED:
                continue
            try:
                response, final_source = await self._fetch_with_safe_redirects(source, [source.url])
                if not 200 <= response.status_code < 300:
                    raise CaptureError(
                        f"Text enrichment returned HTTP {response.status_code}.",
                        http_status=response.status_code,
                        final_url=final_source.url,
                    )
                page = sanitize_page(
                    response.body,
                    _header_value(response.headers, "content-type"),
                    max_visible_text_chars=self._settings.max_visible_text_chars,
                )
                text_path = self._store.save_visible_text(run_id, source.url, page.visible_text)
                semantic_path = self._store.save_semantic_document(
                    run_id,
                    source.url,
                    page.semantic_blocks,
                )
                enriched.append(
                    self._repository.upsert(
                        SourceRecord(
                            run_id=primary.run_id,
                            source_url=primary.source_url,
                            final_url=final_source.url,
                            status=SourceStatus.USER_PROVIDED,
                            http_status=response.status_code,
                            title=page.title or primary.title,
                            visible_text_path=str(text_path),
                            semantic_document_path=str(semantic_path),
                            screenshot_path=primary.screenshot_path,
                            content_hash=hashlib.sha256(response.body).hexdigest(),
                            redirect_chain=(source.url, final_source.url)
                            if final_source.url != source.url
                            else (source.url,),
                            captured_at=utc_now(),
                            capture_note=(
                                "User-provided screenshot accepted as primary visual evidence; "
                                "safe URL text enrichment succeeded."
                            ),
                            redaction_counts=page.redaction_counts,
                        )
                    )
                )
            except Exception as error:
                enriched.append(
                    self._repository.upsert(
                        SourceRecord(
                            run_id=primary.run_id,
                            source_url=primary.source_url,
                            final_url=primary.final_url,
                            status=SourceStatus.USER_PROVIDED,
                            http_status=(
                                error.http_status if isinstance(error, CaptureError) else primary.http_status
                            ),
                            title=primary.title,
                            visible_text_path=primary.visible_text_path,
                            semantic_document_path=primary.semantic_document_path,
                            screenshot_path=primary.screenshot_path,
                            content_hash=primary.content_hash,
                            redirect_chain=primary.redirect_chain,
                            captured_at=utc_now(),
                            capture_note=(
                                "User-provided screenshot accepted as primary visual evidence. "
                                f"Optional URL text enrichment was unavailable: {error}"
                            ),
                            redaction_counts=primary.redaction_counts,
                        )
                    )
                )
        return tuple(enriched)

    async def _capture_source(
        self,
        run_id: str,
        source: SafeUrl,
        *,
        fallback_screenshot_path: str | None,
    ) -> SourceRecord:
        redirect_chain = [source.url]
        final_url: str | None = None
        http_status: int | None = None
        title: str | None = None
        visible_text_path: str | None = None
        semantic_document_path: str | None = None
        screenshot_path: str | None = None
        content_hash: str | None = None
        redaction_counts: dict[str, int] = {}
        image_path: Path | None = None

        try:
            response, final_source = await self._fetch_with_safe_redirects(source, redirect_chain)
            final_url = final_source.url
            http_status = response.status_code
            if not 200 <= response.status_code < 300:
                retry_after = _header_value(response.headers, "retry-after")
                retry_message = (
                    f" The server requested Retry-After: {retry_after}; no retry was attempted."
                    if retry_after
                    else ""
                )
                raise CaptureError(
                    f"Capture returned HTTP {response.status_code}.{retry_message}",
                    http_status=response.status_code,
                    final_url=final_url,
                )

            page = sanitize_page(
                response.body,
                _header_value(response.headers, "content-type"),
                max_visible_text_chars=self._settings.max_visible_text_chars,
            )
            title = page.title
            redaction_counts = page.redaction_counts
            text_path = self._store.save_visible_text(run_id, source.url, page.visible_text)
            visible_text_path = str(text_path)
            semantic_path = self._store.save_semantic_document(
                run_id,
                source.url,
                page.semantic_blocks,
            )
            semantic_document_path = str(semantic_path)
            content_hash = hashlib.sha256(response.body).hexdigest()

            image_path = self._store.screenshot_path(run_id, source.url)
            await self._screenshotter.capture(final_url, image_path)
            if not image_path.is_file() or image_path.stat().st_size == 0:
                raise CaptureError("Screenshot renderer did not create a non-empty PNG.")
            screenshot_path = str(image_path)

            return self._repository.upsert(
                SourceRecord(
                    run_id=run_id,
                    source_url=source.url,
                    final_url=final_url,
                    status=SourceStatus.CAPTURED,
                    http_status=http_status,
                    title=title,
                    visible_text_path=visible_text_path,
                    semantic_document_path=semantic_document_path,
                    screenshot_path=screenshot_path,
                    content_hash=content_hash,
                    redirect_chain=tuple(redirect_chain),
                    captured_at=utc_now(),
                    redaction_counts=redaction_counts,
                )
            )
        except Exception as error:
            if isinstance(error, CaptureError):
                http_status = error.http_status if error.http_status is not None else http_status
                final_url = error.final_url or final_url
            if image_path:
                image_path.unlink(missing_ok=True)
            screenshot_path = None
            if fallback_screenshot_path:
                try:
                    return self._capture_user_screenshot(
                        run_id,
                        source,
                        supplied_path=fallback_screenshot_path,
                        final_url=final_url or source.url,
                        http_status=http_status,
                        redirect_chain=tuple(redirect_chain),
                        automatic_capture_error=str(error),
                    )
                except Exception as fallback_error:
                    error = CaptureError(
                        f"{error} User-provided screenshot fallback could not be used: "
                        f"{fallback_error}",
                        http_status=http_status,
                        final_url=final_url,
                    )
            return self._repository.upsert(
                SourceRecord(
                    run_id=run_id,
                    source_url=source.url,
                    final_url=final_url,
                    status=SourceStatus.FAILED,
                    http_status=http_status,
                    title=title,
                    visible_text_path=visible_text_path,
                    semantic_document_path=semantic_document_path,
                    screenshot_path=screenshot_path,
                    content_hash=content_hash,
                    redirect_chain=tuple(redirect_chain),
                    captured_at=utc_now(),
                    error_message=str(error),
                    redaction_counts=redaction_counts,
                )
            )

    def _capture_user_screenshot(
        self,
        run_id: str,
        source: SafeUrl,
        *,
        supplied_path: str,
        final_url: str,
        http_status: int | None,
        redirect_chain: tuple[str, ...],
        automatic_capture_error: str,
    ) -> SourceRecord:
        """Persist a user image after automatic HTTP/browser capture is unavailable."""

        image_path = self._store.save_user_screenshot(
            run_id,
            source.url,
            supplied_path,
            max_bytes=self._settings.max_user_screenshot_bytes,
        )
        return self._repository.upsert(
            SourceRecord(
                run_id=run_id,
                source_url=source.url,
                final_url=final_url,
                status=SourceStatus.USER_PROVIDED,
                http_status=http_status,
                title=None,
                visible_text_path=None,
                semantic_document_path=None,
                screenshot_path=str(image_path),
                content_hash=_hash_file(image_path),
                redirect_chain=redirect_chain,
                captured_at=utc_now(),
                capture_note=(
                    "Automatic capture was unavailable; user-provided screenshot used. "
                    f"Reason: {automatic_capture_error}"
                ),
            )
        )

    async def _fetch_with_safe_redirects(
        self,
        source: SafeUrl,
        redirect_chain: list[str],
    ) -> tuple[FetchedResponse, SafeUrl]:
        current = source
        redirects_seen = 0
        while True:
            await self._wait_for_host_slot(current.url)
            response = await self._fetcher.get(current.url)
            if response.status_code not in _REDIRECT_STATUSES:
                return response, current

            location = _header_value(response.headers, "location")
            if not location:
                raise CaptureError(
                    "Redirect response did not include a Location header.",
                    http_status=response.status_code,
                    final_url=current.url,
                )
            if redirects_seen >= self._settings.max_redirects:
                raise CaptureError(
                    f"Capture exceeded the redirect limit ({self._settings.max_redirects}).",
                    http_status=response.status_code,
                    final_url=current.url,
                )

            target = urljoin(current.url, location)
            try:
                current = self._validate_redirect_target(target)
            except CaptureError as error:
                raise CaptureError(
                    str(error),
                    http_status=response.status_code,
                    final_url=current.url,
                ) from error
            redirect_chain.append(current.url)
            redirects_seen += 1

    def _validate_redirect_target(self, target: str) -> SafeUrl:
        try:
            return validate_public_urls([HttpUrl(target)], resolver=self._resolver)[0]
        except (UrlSafetyError, ValidationError, ValueError) as error:
            raise CaptureError(f"Unsafe redirect target blocked: {target}") from error

    async def _wait_for_host_slot(self, url: str) -> None:
        """Space requests to one host without adding retries or parallel pressure."""

        interval = self._settings.min_host_request_interval_seconds
        if interval <= 0:
            return
        host = urlsplit(url).netloc.lower()
        async with self._host_pacing_lock:
            now = time.monotonic()
            next_allowed = self._host_request_times.get(host, now)
            delay = max(0.0, next_allowed - now)
            self._host_request_times[host] = max(now, next_allowed) + interval
        if delay:
            await asyncio.sleep(delay)


def sanitize_page(
    body: bytes,
    content_type: str | None,
    *,
    max_visible_text_chars: int,
) -> SanitizedPage:
    """Decode supported page content and retain only bounded, non-executable text."""

    normalized_content_type = (content_type or "").lower()
    media_type = normalized_content_type.split(";", 1)[0].strip()
    if media_type not in _SUPPORTED_MEDIA_TYPES:
        raise CaptureError(f"Unsupported content type for page capture: {media_type}")

    decoded = _decode_page(body, normalized_content_type)

    if media_type == "text/plain":
        return _redact_sanitized_page(SanitizedPage(
            title=None,
            visible_text=_compact_text(decoded, max_visible_text_chars),
            semantic_blocks=(),
            redaction_counts={},
        ))

    parser = _SemanticPageParser()
    parser.feed(decoded)
    parser.close()
    parser.finish()
    return _redact_sanitized_page(SanitizedPage(
        title=_compact_text("".join(parser.title_parts), max_visible_text_chars) or None,
        visible_text=_compact_text("".join(parser.visible_parts), max_visible_text_chars),
        semantic_blocks=tuple(parser.semantic_blocks),
        redaction_counts={},
    ))


def _redact_sanitized_page(page: SanitizedPage) -> SanitizedPage:
    """Remove common PII and secrets before page evidence is written to disk."""

    title = redact_text(page.title)
    visible_text = redact_text(page.visible_text)
    block_texts, block_counts = redact_page_values(block.text for block in page.semantic_blocks)
    counts: dict[str, int] = {}
    for source_counts in (title.counts, visible_text.counts, block_counts):
        for kind, count in source_counts.items():
            counts[kind] = counts.get(kind, 0) + count
    return replace(
        page,
        title=title.text or None,
        visible_text=visible_text.text,
        semantic_blocks=tuple(
            replace(block, text=text) for block, text in zip(page.semantic_blocks, block_texts)
        ),
        redaction_counts=counts,
    )


@dataclass
class _OpenElement:
    """Open HTML element with text collected only for meaningful semantic blocks."""

    tag: str
    semantic_tag: str
    kind: str | None
    ancestry: tuple[str, ...]
    heading_level: int | None = None
    parts: list[str] = field(default_factory=list)


class _SemanticPageParser(HTMLParser):
    """Retain safe visible text plus text-only semantic HTML boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.visible_parts: list[str] = []
        self.semantic_blocks: list[SemanticBlock] = []
        self._suppressed_depth = 0
        self._in_title = False
        self._stack: list[_OpenElement] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._suppressed_depth:
            self._suppressed_depth += 1
            return
        if tag in _SKIP_TEXT_TAGS or _is_hidden(attrs):
            self._suppressed_depth = 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in _BLOCK_TEXT_TAGS:
            self.visible_parts.append("\n")
            self._append_separator_to_open_elements()
        if tag in _VOID_TAGS:
            return

        semantic_tag = "card" if _is_card_like(attrs) else _semantic_tag(tag, attrs)
        kind, heading_level = _semantic_kind(tag, semantic_tag, attrs)
        ancestry = tuple(element.semantic_tag for element in self._stack) + (semantic_tag,)
        self._stack.append(
            _OpenElement(
                tag=tag,
                semantic_tag=semantic_tag,
                kind=kind,
                ancestry=ancestry,
                heading_level=heading_level,
            )
        )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in _BLOCK_TEXT_TAGS:
            self.visible_parts.append("\n")
            self._append_separator_to_open_elements()

        match_index = next(
            (index for index in range(len(self._stack) - 1, -1, -1) if self._stack[index].tag == tag),
            None,
        )
        if match_index is None:
            return
        closing_elements = self._stack[match_index:]
        del self._stack[match_index:]
        for element in reversed(closing_elements):
            self._record_semantic_block(element)

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        self.visible_parts.append(data)
        for element in self._stack:
            if element.kind is not None:
                element.parts.append(data)

    def finish(self) -> None:
        """Record valid open elements if a page ends with imperfect HTML."""

        while self._stack:
            self._record_semantic_block(self._stack.pop())

    def _append_separator_to_open_elements(self) -> None:
        for element in self._stack:
            if element.kind is not None:
                element.parts.append("\n")

    def _record_semantic_block(self, element: _OpenElement) -> None:
        if element.kind is None:
            return
        text = _compact_text("".join(element.parts), max_chars=10_000)
        if not text:
            return
        self.semantic_blocks.append(
            SemanticBlock(
                kind=element.kind,
                tag=element.semantic_tag,
                text=text,
                ancestry=element.ancestry,
                heading_level=element.heading_level,
            )
        )


def _semantic_tag(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    values = {name.lower(): value or "" for name, value in attrs}
    role = values.get("role", "").lower()
    if role in {"navigation", "menubar"}:
        return "nav"
    if role == "contentinfo":
        return "footer"
    if role == "main":
        return "main"
    return tag


def _semantic_kind(
    tag: str,
    semantic_tag: str,
    attrs: list[tuple[str, str | None]],
) -> tuple[str | None, int | None]:
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "heading", int(tag[1])
    if _is_card_like(attrs):
        return "card", None
    if semantic_tag in _SEMANTIC_CONTAINER_TAGS:
        return semantic_tag, None
    if tag == "p":
        return "paragraph", None
    if tag == "li":
        return "list_item", None
    return None, None


def _is_card_like(attrs: list[tuple[str, str | None]]) -> bool:
    values = {
        (value or "").lower()
        for name, value in attrs
        if name.lower() in {"class", "id", "data-component", "data-testid"}
    }
    return any(marker in value for value in values for marker in _CARD_MARKERS)


def _decode_page(body: bytes, content_type: str) -> str:
    """Decode HTML defensively, preferring UTF-8 when a header is misleading."""

    candidates: list[str] = []
    charset_match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type)
    if charset_match:
        candidates.append(charset_match.group(1))
    meta_charset = _html_meta_charset(body)
    if meta_charset:
        candidates.append(meta_charset)
    candidates.extend(("utf-8", "windows-1252", "iso-8859-1"))

    decoded_candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, charset in enumerate(candidates):
        normalized_charset = charset.lower().strip()
        if not normalized_charset or normalized_charset in seen:
            continue
        seen.add(normalized_charset)
        try:
            decoded = body.decode(normalized_charset, errors="replace")
        except LookupError:
            continue
        decoded_candidates.append((_decode_quality(decoded), position, decoded))

    if not decoded_candidates:
        return body.decode("utf-8", errors="replace")
    return min(decoded_candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def _html_meta_charset(body: bytes) -> str | None:
    """Read a declared HTML charset from the first bytes without decoding them."""

    head = body[:8192]
    match = re.search(
        br"<meta\b[^>]*\bcharset\s*=\s*[\"']?([a-zA-Z0-9._-]+)",
        head,
        flags=re.IGNORECASE,
    )
    return match.group(1).decode("ascii") if match else None


def _decode_quality(value: str) -> int:
    """Lower values indicate fewer decoding failures or common mojibake markers."""

    replacement_score = value.count("\ufffd") * 100
    control_score = sum(1 for character in value if "\x80" <= character <= "\x9f") * 20
    mojibake_score = sum(value.count(marker) * 25 for marker in ("Ã", "Â", "â€", "â€™"))
    return replacement_score + control_score + mojibake_score


def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
    values = {name.lower(): value for name, value in attrs}
    if "hidden" in values or values.get("aria-hidden", "").lower() == "true":
        return True
    style = (values.get("style") or "").lower().replace(" ", "")
    return "display:none" in style or "visibility:hidden" in style


def _compact_text(value: str, max_chars: int) -> str:
    """Normalize whitespace, remove control characters, and enforce a text bound."""

    safe = "".join(
        character if character.isprintable() or character in "\n\t" else " "
        for character in value
    )
    lines = [" ".join(line.split()) for line in safe.replace("\u00a0", " ").splitlines()]
    compacted = "\n".join(line for line in lines if line)
    return compacted[:max_chars].strip()


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _hash_file(path: Path) -> str:
    """Return a SHA-256 digest without loading a supplied image into memory at once."""

    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()
