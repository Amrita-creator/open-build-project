"""Validate public inspiration URLs before any network-facing pipeline stage."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, Iterable

from pydantic import HttpUrl


Resolver = Callable[..., list[tuple]]


class UrlSafetyError(ValueError):
    """Raised when an inspiration URL would be unsafe for the server to process."""


@dataclass(frozen=True)
class SafeUrl:
    """A URL that passed scheme, host, port, and DNS safety checks."""

    url: str
    host: str
    resolved_ips: tuple[str, ...]


def validate_public_urls(
    urls: Iterable[HttpUrl],
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> tuple[SafeUrl, ...]:
    """Return validated public URLs or raise a clear safety error.

    DNS resolution is included so a public-looking hostname cannot silently map
    to localhost or a private network. The capture stage will re-run this check
    for every redirect target in M3.
    """

    return tuple(_validate_public_url(url, resolver=resolver) for url in urls)


def _validate_public_url(url: HttpUrl, *, resolver: Resolver) -> SafeUrl:
    raw_url = str(url)
    host = url.host

    if url.scheme not in {"http", "https"}:
        raise UrlSafetyError(f"Only http and https URLs are allowed: {raw_url}")
    if not host:
        raise UrlSafetyError(f"A hostname is required: {raw_url}")

    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise UrlSafetyError(f"Localhost URLs are not allowed: {raw_url}")

    _validate_port(url, raw_url)
    literal_ip = _parse_ip(normalized_host)
    if literal_ip is not None:
        _require_public_ip(literal_ip, raw_url)
        return SafeUrl(
            url=raw_url,
            host=normalized_host,
            resolved_ips=(str(literal_ip),),
        )

    resolved_ips = _resolve_public_host(normalized_host, raw_url, resolver)
    return SafeUrl(url=raw_url, host=normalized_host, resolved_ips=resolved_ips)


def _validate_port(url: HttpUrl, raw_url: str) -> None:
    """Restrict capture targets to the default web ports in the first release."""

    if url.port is None:
        return
    default_port = 80 if url.scheme == "http" else 443
    if url.port != default_port:
        raise UrlSafetyError(
            f"Only the default {url.scheme.upper()} port is allowed: {raw_url}"
        )


def _resolve_public_host(
    host: str,
    raw_url: str,
    resolver: Resolver,
) -> tuple[str, ...]:
    try:
        results = resolver(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise UrlSafetyError(f"Could not resolve URL hostname: {raw_url}") from error

    resolved_ips: set[str] = set()
    for result in results:
        address = result[4][0]
        ip = _parse_ip(address)
        if ip is None:
            continue
        _require_public_ip(ip, raw_url)
        resolved_ips.add(str(ip))

    if not resolved_ips:
        raise UrlSafetyError(f"Could not resolve a public IP address: {raw_url}")
    return tuple(sorted(resolved_ips))


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _require_public_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    raw_url: str,
) -> None:
    if not ip.is_global:
        raise UrlSafetyError(f"Private or reserved network targets are not allowed: {raw_url}")
