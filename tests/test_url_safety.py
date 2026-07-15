"""Tests for the URL safety boundary added in M2."""

import socket
import unittest

from pydantic import HttpUrl

from inspo_mcp.services.url_safety import UrlSafetyError, validate_public_urls


def public_resolver(host: str, port: int | None, *, type: int) -> list[tuple]:
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
    ]


def private_resolver(host: str, port: int | None, *, type: int) -> list[tuple]:
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0)),
    ]


class UrlSafetyTests(unittest.TestCase):
    def test_accepts_public_https_url(self) -> None:
        result = validate_public_urls(
            [HttpUrl("https://example.com")], resolver=public_resolver
        )

        self.assertEqual(result[0].host, "example.com")
        self.assertEqual(result[0].resolved_ips, ("93.184.216.34",))

    def test_rejects_localhost(self) -> None:
        with self.assertRaisesRegex(UrlSafetyError, "Localhost"):
            validate_public_urls([HttpUrl("http://localhost")])

    def test_rejects_private_literal_ip(self) -> None:
        with self.assertRaisesRegex(UrlSafetyError, "Private or reserved"):
            validate_public_urls([HttpUrl("http://127.0.0.1")])

    def test_rejects_hostname_resolving_to_private_ip(self) -> None:
        with self.assertRaisesRegex(UrlSafetyError, "Private or reserved"):
            validate_public_urls(
                [HttpUrl("https://example.com")], resolver=private_resolver
            )

    def test_rejects_non_default_port(self) -> None:
        with self.assertRaisesRegex(UrlSafetyError, "default HTTPS port"):
            validate_public_urls(
                [HttpUrl("https://example.com:8443")], resolver=public_resolver
            )


if __name__ == "__main__":
    unittest.main()
