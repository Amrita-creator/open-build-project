"""Verify the complete hosted judge-demo workflow against a remote InspoMCP URL.

Set INSPO_MCP_URL and INSPO_MCP_AUTH_TOKEN in the current shell before running
this script. It never prints the bearer token.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from fastmcp import Client


def _environment_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set in the current shell.")
    return value


def _structured_result(result: Any) -> dict[str, Any]:
    """Return a FastMCP v2 result without exposing its raw request data."""

    if result.is_error:
        raise RuntimeError(str(result.content))
    if not isinstance(result.structured_content, dict):
        raise RuntimeError("The MCP tool returned no structured JSON result.")
    return result.structured_content


async def main() -> None:
    url = _environment_value("INSPO_MCP_URL")
    token = _environment_value("INSPO_MCP_AUTH_TOKEN")

    async with Client(url, auth=token) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        required_tools = {"run_hosted_demo", "get_kit", "generate_component_code"}
        missing = required_tools - names
        if missing:
            raise RuntimeError("Hosted endpoint is missing tools: " + ", ".join(sorted(missing)))
        print("1/3 Connected and required tools are available.")

        demo = _structured_result(
            await client.call_tool(
                "run_hosted_demo",
                {
                    "project_goal": "Build a calm finance workspace for small business owners.",
                    "framework": "nextjs-tailwind",
                },
            )
        )
        run_id = str(demo["run_id"])
        print(f"2/3 Hosted demo created and stored: {run_id}")

        lookup = _structured_result(await client.call_tool("get_kit", {"run_id": run_id}))
        kit = lookup.get("kit")
        if lookup.get("state") != "ready" or not isinstance(kit, dict):
            raise RuntimeError("get_kit did not return a ready stored kit.")
        cards = kit.get("component_cards")
        if not isinstance(cards, list) or not cards or not isinstance(cards[0], dict):
            raise RuntimeError("The stored kit does not contain a reusable component card.")

        component_name = str(cards[0]["name"])
        generated = _structured_result(
            await client.call_tool(
                "generate_component_code",
                {"run_id": run_id, "component_name": component_name},
            )
        )
        file_count = len(generated.get("files", []))
        print(
            "3/3 Retrieved the stored kit and generated "
            f"{file_count} code file(s) for {component_name}."
        )
        print("Hosted judge-demo verification passed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"Hosted judge-demo verification failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
