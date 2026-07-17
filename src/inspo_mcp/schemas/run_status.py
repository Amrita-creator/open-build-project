"""Typed M7 contracts for durable run retrieval and partial progress."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from . import InspirationKit, SourceWarning


KitLookupState = Literal["ready", "not_ready", "failed"]


class SourceProgress(BaseModel):
    """The durable capture, extraction, and vision state of one source."""

    source_url: str
    status: str
    capture_status: str | None = None
    extraction_status: str | None = None
    vision_status: str | None = None
    message: str | None = None


class RunStatusReport(BaseModel):
    """A poll-safe summary for a run that may still have partial M5 results."""

    run_id: str
    status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    is_terminal: bool
    kit_ready: bool
    created_at: str
    updated_at: str
    error_message: str | None = None
    sources: list[SourceProgress] = Field(default_factory=list)
    warnings: list[SourceWarning] = Field(default_factory=list)
    next_action: str


class KitLookup(BaseModel):
    """A durable kit response that remains useful before M6 is ready."""

    run_id: str
    state: KitLookupState
    kit: InspirationKit | None = None
    warnings: list[SourceWarning] = Field(default_factory=list)
    message: str
