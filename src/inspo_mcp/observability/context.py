"""Context-local request trace identifiers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_trace_id: ContextVar[str] = ContextVar("inspo_mcp_trace_id", default="-")


def current_trace_id() -> str:
    """Return the request trace ID for the current async context."""

    return _trace_id.get()


@contextmanager
def bind_trace_id(trace_id: str) -> Iterator[None]:
    """Bind a trace ID only for the lifetime of one request."""

    token = _trace_id.set(trace_id)
    try:
        yield
    finally:
        _trace_id.reset(token)
