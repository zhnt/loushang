"""Reusable observability configuration lifecycle for product hosts."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from ._router import (
    DebugLogSinkProtocol,
    InMemoryProblemStore,
    TraceSinkProtocol,
    capture_observability,
    configure_debug_logging,
    configure_observability,
    get_problem_store,
    restore_observability,
)
from .context import log_context
from .debug_sink import DebugLogSink
from .trace_sink import TraceJSONLSink


class _ConfigureKwargs(TypedDict, total=False):
    debug_sink: DebugLogSinkProtocol | None
    trace_sink: TraceSinkProtocol | None
    problem_sink: InMemoryProblemStore | None
    debug_scopes: frozenset[str]
    trace_scopes: frozenset[str]


@contextmanager
def observability_runtime_context(
    *,
    session_id: str | None,
    cwd: str | Path,
    mode: str,
    debug_path: str | Path | None = None,
    debug_scopes: frozenset[str] = frozenset(),
    trace_path: str | Path | None = None,
    trace_scopes: frozenset[str] = frozenset(),
    problem_sink: InMemoryProblemStore | None = None,
) -> Iterator[None]:
    """Temporarily bind sinks and context, then restore the previous state."""

    configure_kwargs: _ConfigureKwargs = {}
    if debug_path is not None:
        resolved_debug_path = Path(debug_path)
        configure_kwargs["debug_sink"] = DebugLogSink(
            resolved_debug_path,
            latest_path=resolved_debug_path.parent / "latest",
        )
        configure_kwargs["debug_scopes"] = debug_scopes
    if trace_path is not None:
        resolved_trace_path = Path(trace_path)
        configure_kwargs["trace_sink"] = TraceJSONLSink(
            resolved_trace_path,
            latest_path=resolved_trace_path.parent / "latest",
        )
        configure_kwargs["trace_scopes"] = trace_scopes
    if problem_sink is not None:
        configure_kwargs["problem_sink"] = problem_sink

    previous = capture_observability() if configure_kwargs else None
    if configure_kwargs:
        configure_observability(**configure_kwargs)
    try:
        with log_context(session_id=session_id, cwd=str(Path(cwd)), mode=mode):
            yield
    finally:
        if previous is not None:
            restore_observability(previous)


def enable_debug_file(
    path: str | Path,
    *,
    scopes: tuple[str, ...] = ("all",),
) -> Path:
    """Enable global debug logging to a product-selected file."""

    resolved_path = Path(path).expanduser().resolve()
    configure_debug_logging(
        debug_sink=DebugLogSink(
            resolved_path, latest_path=resolved_path.parent / "latest"
        ),
        debug_scopes=scopes,
    )
    return resolved_path


def disable_debug_file() -> None:
    configure_debug_logging(debug_sink=None)


def parse_scopes(
    raw: str | None,
    *,
    bare_default: tuple[str, ...] = ("all",),
) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if raw == "":
        return frozenset(bare_default)
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def value_from_args_or_env(args: Any, arg_name: str, env_name: str) -> str | None:
    value = getattr(args, arg_name, None)
    return value if value is not None else os.environ.get(env_name)


def path_from_args_or_env(args: Any, arg_name: str, env_name: str) -> str | None:
    value = getattr(args, arg_name, None)
    return value if value else os.environ.get(env_name)


def session_log_label(
    session_id: str | None,
    *,
    now: float | None = None,
    process_id: int | None = None,
) -> str:
    raw = (
        session_id
        or f"startup-{int((time.time() if now is None else now) * 1000)}-{os.getpid() if process_id is None else process_id}"
    )
    return "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "_"
        for character in raw
    )


__all__ = [
    "InMemoryProblemStore",
    "disable_debug_file",
    "enable_debug_file",
    "get_problem_store",
    "observability_runtime_context",
    "parse_scopes",
    "path_from_args_or_env",
    "session_log_label",
    "value_from_args_or_env",
]
