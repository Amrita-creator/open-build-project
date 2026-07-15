"""Domain models that are independent of MCP transport details."""

from .run import RunRecord, RunStatus
from .source import SourceRecord, SourceStatus

__all__ = ["RunRecord", "RunStatus", "SourceRecord", "SourceStatus"]
