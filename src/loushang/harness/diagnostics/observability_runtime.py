"""Product-neutral session observability binding.

The low-level sinks live in :mod:`loushang.foundation.observability`; this
module only binds CLI/session values to one runtime context and diagnostic
problem sink. Products may supply source classification and output directories.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loushang.foundation.observability.records import ProblemRecord
from loushang.foundation.observability.runtime import (
    disable_debug_file,
    enable_debug_file,
    observability_runtime_context,
    parse_scopes,
    path_from_args_or_env,
    session_log_label,
    value_from_args_or_env,
)
from loushang.harness.diagnostics.observability_bridge import (
    DiagnosticsProblemStore,
    diagnostic_source_for_problem,
)
from loushang.harness.diagnostics.types import DiagnosticSource

ProblemSourceResolver = Callable[[ProblemRecord], DiagnosticSource]


@contextmanager
def session_observability_context(
    *,
    args: Any,
    session: Any,
    cwd: str | Path,
    mode: str,
    source_resolver: ProblemSourceResolver | None = None,
    debug_dir: str | Path | None = None,
    trace_dir: str | Path | None = None,
    session_label: str | None = None,
) -> Iterator[None]:
    """Bind generic CLI/session observability values to the shared runtime."""

    cwd_path = Path(cwd).expanduser().resolve()
    session_id = _session_id(session)
    resolved_session_label = session_label or session_log_label(session_id, now=time.time())
    debug_raw = value_from_args_or_env(args, "debug", "LOUSHANG_DEBUG_SCOPES")
    trace_raw = value_from_args_or_env(args, "trace", "LOUSHANG_TRACE_SCOPES")
    debug_scopes = parse_scopes(debug_raw, bare_default=("all",))
    trace_scopes = parse_scopes(trace_raw, bare_default=("all",))
    debug_path = _output_path(
        args,
        "debug_file",
        "LOUSHANG_DEBUG_FILE",
        debug_raw,
        debug_dir,
        resolved_session_label,
        ".log",
    )
    trace_path = _output_path(
        args,
        "trace_file",
        "LOUSHANG_TRACE_FILE",
        trace_raw,
        trace_dir,
        resolved_session_label,
        ".jsonl",
    )
    problem_sink = _problem_sink(session, source_resolver)
    with observability_runtime_context(
        session_id=session_id,
        cwd=cwd_path,
        mode=mode,
        debug_path=debug_path,
        debug_scopes=debug_scopes,
        trace_path=trace_path,
        trace_scopes=trace_scopes,
        problem_sink=problem_sink,
    ):
        yield


@contextmanager
def startup_observability_context(
    *,
    args: Any,
    services: Any,
    cwd: str | Path,
    source_resolver: ProblemSourceResolver | None = None,
    debug_dir: str | Path | None = None,
    trace_dir: str | Path | None = None,
    session_label: str | None = None,
) -> Iterator[None]:
    startup_session = SimpleNamespace(
        session_id=None,
        diagnostics_service=getattr(services, "diagnostics_service", None),
    )
    with session_observability_context(
        args=args,
        session=startup_session,
        cwd=cwd,
        mode="startup",
        source_resolver=source_resolver,
        debug_dir=debug_dir,
        trace_dir=trace_dir,
        session_label=session_label,
    ):
        yield


def enable_session_debug(
    *,
    session: Any,
    scopes: tuple[str, ...] = ("all",),
    debug_file: str | Path | None = None,
    debug_dir: str | Path | None = None,
) -> Path:
    session_id = _session_id(session)
    output_dir = Path(debug_dir).expanduser() if debug_dir is not None else Path.home() / ".loushang" / "debug"
    debug_path = (
        Path(debug_file).expanduser().resolve()
        if debug_file is not None
        else output_dir / f"{session_log_label(session_id, now=time.time())}.log"
    )
    return enable_debug_file(debug_path, scopes=scopes)


def disable_session_debug() -> None:
    disable_debug_file()


def _output_path(
    args: Any,
    arg_name: str,
    env_name: str,
    raw_scope: str | None,
    output_dir: str | Path | None,
    session_label: str,
    suffix: str,
) -> Path | None:
    explicit = path_from_args_or_env(args, arg_name, env_name)
    if explicit:
        return Path(explicit).expanduser().resolve()
    if raw_scope is None:
        return None
    base = Path(output_dir).expanduser() if output_dir is not None else Path.home() / ".loushang" / "debug"
    if suffix == ".jsonl" and output_dir is None:
        base = Path.home() / ".loushang" / "traces"
    return base / f"{session_label}{suffix}"


def _session_id(session: Any) -> str | None:
    try:
        value = getattr(session, "session_id", None)
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def _problem_sink(
    session: Any,
    source_resolver: ProblemSourceResolver | None,
) -> DiagnosticsProblemStore | None:
    diagnostics_service = getattr(session, "diagnostics_service", None)
    if diagnostics_service is None or not callable(
        getattr(diagnostics_service, "record", None)
    ):
        return None
    return DiagnosticsProblemStore(
        diagnostics_service,
        source_resolver=source_resolver or diagnostic_source_for_problem,
    )


__all__ = [
    "ProblemSourceResolver",
    "disable_session_debug",
    "enable_session_debug",
    "session_observability_context",
    "startup_observability_context",
]
