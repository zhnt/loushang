"""Structural session values consumed by conversation presentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loushang.harness.workspace.git import get_git_branch


def session_cwd(*, session: Any, runtime: Any) -> str:
    session_manager = getattr(session, "session_manager", None)
    get_cwd = getattr(session_manager, "get_cwd", None)
    if callable(get_cwd):
        try:
            cwd = get_cwd()
            if cwd:
                return str(cwd)
        except Exception:
            pass

    runtime_get_cwd = getattr(runtime, "get_cwd", None)
    if callable(runtime_get_cwd):
        try:
            cwd = runtime_get_cwd()
            if cwd:
                return str(cwd)
        except Exception:
            pass
    return str(Path.cwd())


def git_branch(cwd: str) -> str | None:
    try:
        return get_git_branch(cwd)
    except Exception:
        return None


def session_label(session: Any) -> str | None:
    try:
        session_name = getattr(session, "session_name", None)
    except Exception:
        session_name = None
    if isinstance(session_name, str) and session_name:
        return session_name
    try:
        session_id = getattr(session, "session_id", None)
    except Exception:
        session_id = None
    return session_id if isinstance(session_id, str) and session_id else None


def session_observability_id(session: Any) -> str | None:
    try:
        session_id = getattr(session, "session_id", None)
    except Exception:
        return None
    return session_id if isinstance(session_id, str) and session_id else None


def thinking_level(session: Any) -> str | None:
    getter = getattr(session, "get_thinking_level", None)
    if callable(getter):
        try:
            value = getter()
            return value if isinstance(value, str) else None
        except Exception:
            return None
    value = getattr(session, "thinking_level", None)
    return value if isinstance(value, str) else None


def is_running(session: Any) -> bool:
    for name in ("is_processing", "is_running", "isBashRunning"):
        getter = getattr(session, name, None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
    for name in ("isStreaming", "is_streaming"):
        try:
            value = getattr(session, name, None)
        except Exception:
            return False
        if isinstance(value, bool):
            return value
    return False


def session_error_message(session: Any) -> str | None:
    targets = (
        session,
        getattr(session, "agent", None),
        getattr(getattr(session, "agent", None), "state", None),
    )
    for target in targets:
        error_message = getattr(target, "error_message", None)
        if isinstance(error_message, str) and error_message:
            return error_message
    return None


__all__ = [
    "git_branch",
    "is_running",
    "session_cwd",
    "session_error_message",
    "session_label",
    "session_observability_id",
    "thinking_level",
]
