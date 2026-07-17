"""Build a durable M6-kit retrieval result that is safe to poll."""

from __future__ import annotations

from inspo_mcp.schemas import InspirationKit
from inspo_mcp.schemas.run_status import KitLookup, RunStatusReport


def build_kit_lookup(
    status: RunStatusReport,
    kit: InspirationKit | None,
) -> KitLookup:
    """Return the saved kit or a typed, actionable not-ready response."""

    if kit is not None:
        return KitLookup(
            run_id=status.run_id,
            state="ready",
            kit=kit,
            warnings=status.warnings,
            message="Reusable kit retrieved from durable storage.",
        )
    if status.status == "failed":
        return KitLookup(
            run_id=status.run_id,
            state="failed",
            warnings=status.warnings,
            message="This run failed before a reusable kit could be stored.",
        )
    return KitLookup(
        run_id=status.run_id,
        state="not_ready",
        warnings=status.warnings,
        message=status.next_action,
    )
