"""Protect structured host output from incidental process stdout writes."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TextIO


@dataclass
class _StdoutTakeoverState:
    original_stdout: TextIO
    raw_stdout: TextIO
    redirected_stdout: TextIO


_state: _StdoutTakeoverState | None = None


def take_over_stdout(
    *, stdout: TextIO | None = None, stderr: TextIO | None = None
) -> bool:
    """Route incidental stdout writes to stderr while preserving raw stdout."""

    global _state
    if _state is not None:
        return False
    raw_stdout = sys.stdout if stdout is None else stdout
    redirected_stdout = sys.stderr if stderr is None else stderr
    _state = _StdoutTakeoverState(
        original_stdout=sys.stdout,
        raw_stdout=raw_stdout,
        redirected_stdout=redirected_stdout,
    )
    sys.stdout = redirected_stdout
    return True


def restore_stdout() -> None:
    """Restore stdout if this process currently owns the redirect."""

    global _state
    if _state is None:
        return
    sys.stdout = _state.original_stdout
    _state = None


def is_stdout_taken_over() -> bool:
    """Whether a structured-output host currently redirects process stdout."""

    return _state is not None


def write_raw_stdout(text: str) -> None:
    """Write a protocol frame to the preserved stdout stream."""

    target = _state.raw_stdout if _state is not None else sys.stdout
    target.write(text)


def flush_raw_stdout() -> None:
    """Flush the preserved stdout stream when supported."""

    target = _state.raw_stdout if _state is not None else sys.stdout
    flush = getattr(target, "flush", None)
    if callable(flush):
        flush()


@contextmanager
def stdout_guard(
    *, stdout: TextIO | None = None, stderr: TextIO | None = None
) -> Iterator[None]:
    """Protect one structured output scope from incidental stdout writes."""

    acquired = take_over_stdout(stdout=stdout, stderr=stderr)
    try:
        yield
    finally:
        if acquired:
            restore_stdout()


__all__ = [
    "flush_raw_stdout",
    "is_stdout_taken_over",
    "restore_stdout",
    "stdout_guard",
    "take_over_stdout",
    "write_raw_stdout",
]
