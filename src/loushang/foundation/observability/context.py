from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LogContext:
    session_id: str | None = None
    run_id: int | str | None = None
    cwd: str | None = None
    mode: str | None = None


_UNSET = object()
_context: ContextVar[LogContext] = ContextVar(
    "loushang_observability_context",
    default=LogContext(),
)


def current_context() -> LogContext:
    return _context.get()


@contextmanager
def log_context(
    *,
    session_id: str | None | object = _UNSET,
    run_id: int | str | None | object = _UNSET,
    cwd: str | None | object = _UNSET,
    mode: str | None | object = _UNSET,
) -> Iterator[LogContext]:
    previous = current_context()
    next_context = LogContext(
        session_id=_select(previous.session_id, session_id),
        run_id=_select(previous.run_id, run_id),
        cwd=_select(previous.cwd, cwd),
        mode=_select(previous.mode, mode),
    )
    token = _context.set(next_context)
    try:
        yield next_context
    finally:
        _context.reset(token)


def _select(previous: Any, value: Any) -> Any:
    if value is _UNSET:
        return previous
    return value
