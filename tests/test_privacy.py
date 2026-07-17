"""Focused tests for privacy input controls, redaction, and retention cleanup."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inspo_mcp.models.run import RunRecord, RunStatus
from inspo_mcp.repositories.runs import RunNotFoundError, RunRepository
from inspo_mcp.schemas import InspirationRequest, SourceWarning
from inspo_mcp.services.capture import sanitize_page
from inspo_mcp.services.privacy import (
    PrivacyInputError,
    mask_warnings,
    redact_text,
    reject_request_secrets,
)
from inspo_mcp.storage.database import SqliteDatabase


class PrivacyInputTests(unittest.TestCase):
    def test_rejects_secret_in_goal_or_url_query(self) -> None:
        with self.assertRaises(PrivacyInputError):
            reject_request_secrets("Build a page; password=super-secret-value", [])
        with self.assertRaises(PrivacyInputError):
            reject_request_secrets(
                "Build a responsive project dashboard for small teams.",
                ["https://example.com/?access_token=very-secret-token"],
            )

    def test_redacts_common_pii_and_credentials(self) -> None:
        result = redact_text(
            "Contact alice@example.com, phone +1 415 555 1234, card 4111 1111 1111 1111, "
            "or use Bearer abcdefghijklmnop."
        )

        self.assertNotIn("alice@example.com", result.text)
        self.assertNotIn("4111 1111 1111 1111", result.text)
        self.assertIn("[REDACTED_EMAIL]", result.text)
        self.assertGreaterEqual(result.counts["secrets"], 1)
        self.assertGreaterEqual(result.counts["emails"], 1)
        self.assertGreaterEqual(result.counts["payment_numbers"], 1)

    def test_capture_sanitization_redacts_before_persistence(self) -> None:
        page = sanitize_page(
            b"<html><head><title>alice@example.com</title></head><body>"
            b"Email alice@example.com. password=super-secret-value</body></html>",
            "text/html; charset=utf-8",
            max_visible_text_chars=1_000,
        )

        self.assertNotIn("alice@example.com", page.visible_text)
        self.assertNotIn("super-secret-value", page.visible_text)
        self.assertGreaterEqual(page.redaction_counts["emails"], 1)
        self.assertGreaterEqual(page.redaction_counts["secrets"], 1)


class PrivacyOutputAndRetentionTests(unittest.TestCase):
    def test_private_output_replaces_source_url_with_opaque_label(self) -> None:
        run = RunRecord(
            run_id="run_private",
            status=RunStatus.COMPLETED,
            inspiration_urls=("https://confidential.example/brief",),
            project_goal="Build a customer portal for a small team.",
            framework="nextjs-tailwind",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            privacy_mode=True,
        )
        warning = SourceWarning(
            url="https://confidential.example/brief",
            message="Contact alice@example.com for access.",
        )

        safe_warning = mask_warnings(run, [warning])[0]

        self.assertEqual(safe_warning.url[:10], "Reference ")
        self.assertNotIn("confidential.example", safe_warning.url)
        self.assertNotIn("alice@example.com", safe_warning.message)

    def test_privacy_metadata_persists_and_expired_run_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(SqliteDatabase(Path(directory) / "privacy.db"))
            request = InspirationRequest(
                inspiration_urls=["https://one.example", "https://two.example"],
                project_goal="Build a focused product page for independent designers.",
                privacy_mode=True,
                retention_days=7,
            )
            created = repository.create(RunRecord.new(request))

            persisted = repository.get(created.run_id)
            self.assertTrue(persisted.privacy_mode)
            self.assertIsNotNone(persisted.retention_expires_at)

            self.assertEqual(repository.delete_expired("9999-01-01T00:00:00+00:00"), (created.run_id,))
            with self.assertRaises(RunNotFoundError):
                repository.get(created.run_id)


if __name__ == "__main__":
    unittest.main()
