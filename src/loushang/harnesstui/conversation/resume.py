"""Product-neutral presentation of a command that resumes a conversation."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True, slots=True)
class ConversationResumeHint:
    """Prepared copy and command arguments for one resume hint."""

    heading: str
    command: tuple[str, ...]


def render_conversation_resume_hint(hint: ConversationResumeHint) -> str:
    """Render a prepared resume hint without knowing product session policy."""

    return f"\n{hint.heading}\n{shlex.join(hint.command)}\n"


def write_clean_exit_resume_hint(
    *,
    stdout: TextIO,
    exit_code: int,
    hint: ConversationResumeHint | None,
) -> None:
    """Write and flush a prepared hint only after a successful exit."""

    if exit_code != 0 or hint is None:
        return
    stdout.write(render_conversation_resume_hint(hint))
    stdout.flush()


def resume_hint_for_session(
    session: object,
    *,
    command_prefix: tuple[str, ...],
    heading: str = "Resume this session with:",
) -> ConversationResumeHint | None:
    """Resolve the stable resume reference from standard Product session shapes."""

    if not _has_resumable_messages(session):
        return None
    session_file = _session_file_for_resume(session)
    if session_file is None:
        return None
    session_id = getattr(session, "session_id", None)
    if not isinstance(session_id, str) or not session_id:
        manager = getattr(session, "session_manager", None)
        get_header = getattr(manager, "get_header", None)
        if callable(get_header):
            try:
                session_id = getattr(get_header(), "conversation_id", None)
            except Exception:
                session_id = None
    resume_ref = (
        session_id if isinstance(session_id, str) and session_id else str(session_file)
    )
    return ConversationResumeHint(
        heading=heading,
        command=(*command_prefix, resume_ref),
    )


def _session_file_for_resume(session: object) -> object | None:
    manager = getattr(session, "session_manager", None)
    get_session_file = getattr(manager, "get_session_file", None)
    if callable(get_session_file):
        try:
            return get_session_file()
        except Exception:
            return None
    return getattr(session, "session_file", None)


def _has_resumable_messages(session: object) -> bool:
    """Suppress hints for known-empty sessions without imposing a Product type."""

    manager = getattr(session, "session_manager", None)
    get_summary = getattr(manager, "get_session_summary", None)
    if not callable(get_summary):
        return True
    try:
        message_count = getattr(get_summary(), "message_count", None)
    except Exception:
        return True
    return not isinstance(message_count, int) or message_count > 0


__all__ = [
    "ConversationResumeHint",
    "render_conversation_resume_hint",
    "resume_hint_for_session",
    "write_clean_exit_resume_hint",
]
