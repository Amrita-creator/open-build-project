"""M9 tests for production configuration, authentication, tracing, and probes."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastmcp import FastMCP
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from inspo_mcp.config import ConfigurationError, RuntimeSettings
from inspo_mcp.observability.context import bind_trace_id
from inspo_mcp.observability.logging import JsonLogFormatter
from inspo_mcp.observability.middleware import _valid_bearer_token
from inspo_mcp.observability.telemetry import traced_tool
from inspo_mcp.production import create_production_app


class RuntimeSettingsTests(unittest.TestCase):
    def test_production_requires_token_and_explicit_persistent_paths(self) -> None:
        with self.assertRaises(ConfigurationError):
            RuntimeSettings.from_environment({"INSPO_MCP_ENVIRONMENT": "production"})

    def test_production_loads_token_without_exposing_it_in_settings_repr_assertions(self) -> None:
        settings = RuntimeSettings.from_environment(
            {
                "INSPO_MCP_ENVIRONMENT": "production",
                "INSPO_MCP_AUTH_TOKEN": "long-random-token",
                "INSPO_MCP_DATABASE_PATH": "/var/lib/inspo-mcp/inspo.db",
                "INSPO_MCP_CAPTURE_ROOT": "/var/lib/inspo-mcp/captures",
                "INSPO_MCP_CORS_ORIGINS": "https://app.example.com, https://admin.example.com",
                "PORT": "9000",
            }
        )

        self.assertTrue(settings.is_production)
        self.assertEqual(settings.port, 9000)
        self.assertEqual(settings.cors_origins, ("https://app.example.com", "https://admin.example.com"))

    def test_rejects_wildcard_cors_origin(self) -> None:
        with self.assertRaises(ConfigurationError):
            RuntimeSettings.from_environment({"INSPO_MCP_CORS_ORIGINS": "*"})

    def test_loads_optional_http_otlp_traces_endpoint(self) -> None:
        settings = RuntimeSettings.from_environment(
            {"INSPO_MCP_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://jaeger:4318/v1/traces"}
        )

        self.assertEqual(
            settings.otlp_traces_endpoint,
            "http://jaeger:4318/v1/traces",
        )

    def test_rejects_non_http_otlp_traces_endpoint(self) -> None:
        with self.assertRaises(ConfigurationError):
            RuntimeSettings.from_environment(
                {"INSPO_MCP_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "jaeger:4318"}
            )


class ProductionHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_is_public_and_mcp_requires_a_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings = _settings(root)
            app = create_production_app(settings, FastMCP("production-test"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                health = await client.get("/healthz")
                ready = await client.get("/readyz")
                rejected = await client.get("/mcp")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertTrue(health.headers["x-request-id"])
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(rejected.headers["www-authenticate"], "Bearer")

    async def test_authorized_mcp_request_reaches_the_fastmcp_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = create_production_app(_settings(Path(temporary_directory)), FastMCP("production-test"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/mcp", headers={"Authorization": "Bearer test-token"})

        self.assertNotEqual(response.status_code, 401)


class ObservabilityTests(unittest.TestCase):
    def test_json_logs_include_trace_id_and_safe_request_metadata(self) -> None:
        formatter = JsonLogFormatter(_settings(Path("data/test-observability")))
        record = logging.LogRecord(
            "inspo_mcp.test",
            logging.INFO,
            __file__,
            1,
            "request complete",
            (),
            None,
        )
        record.event = "http_request_completed"  # type: ignore[attr-defined]
        record.status_code = 200  # type: ignore[attr-defined]
        with bind_trace_id("trace-test-123"):
            payload = json.loads(formatter.format(record))

        self.assertEqual(payload["trace_id"], "trace-test-123")
        self.assertEqual(payload["status_code"], 200)
        self.assertNotIn("authorization", payload)

    def test_bearer_comparison_accepts_only_the_expected_scheme_and_token(self) -> None:
        self.assertTrue(_valid_bearer_token("Bearer correct", "correct"))
        self.assertFalse(_valid_bearer_token("Basic correct", "correct"))
        self.assertFalse(_valid_bearer_token("Bearer wrong", "correct"))


class TelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_telemetry_records_only_safe_request_metadata(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test")

        with tempfile.TemporaryDirectory() as temporary_directory:
            app = create_production_app(_settings(Path(temporary_directory)), FastMCP("trace-test"))
            transport = httpx.ASGITransport(app=app)
            with patch(
                "inspo_mcp.observability.middleware.trace.get_tracer",
                return_value=tracer,
            ):
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    response = await client.get(
                        "/healthz",
                        headers={"Authorization": "Bearer never-record-this"},
                    )

        self.assertEqual(response.status_code, 200)
        spans = exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "http.server.request")
        self.assertEqual(spans[0].attributes["http.request.method"], "GET")
        self.assertEqual(spans[0].attributes["url.path"], "/healthz")
        self.assertNotIn("authorization", spans[0].attributes)

    async def test_tool_telemetry_creates_a_child_span_without_arguments(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test")

        @traced_tool("sample_tool")
        async def sample_tool(secret_input: str) -> str:
            return secret_input.upper()

        with patch(
            "inspo_mcp.observability.telemetry.trace.get_tracer",
            return_value=tracer,
        ):
            self.assertEqual(await sample_tool("do-not-record-this"), "DO-NOT-RECORD-THIS")

        spans = exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "mcp.tool sample_tool")
        self.assertEqual(spans[0].attributes["mcp.tool.name"], "sample_tool")
        self.assertNotIn("secret_input", spans[0].attributes)


def _settings(root: Path) -> RuntimeSettings:
    return RuntimeSettings.from_environment(
        {
            "INSPO_MCP_ENVIRONMENT": "production",
            "INSPO_MCP_AUTH_TOKEN": "test-token",
            "INSPO_MCP_DATABASE_PATH": str(root / "inspo.db"),
            "INSPO_MCP_CAPTURE_ROOT": str(root / "captures"),
        }
    )


if __name__ == "__main__":
    unittest.main()
