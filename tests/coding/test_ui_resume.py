from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loushang.harnesstui.conversation.resume import resume_hint_for_session


def _coding_resume_hint(session: object):
    return resume_hint_for_session(
        session,
        command_prefix=("loushang", "--resume"),
    )


def test_coding_resume_hint_prefers_session_id() -> None:
    session = SimpleNamespace(
        session_id="session-id",
        session_manager=SimpleNamespace(
            get_session_file=lambda: Path("/tmp/session.jsonl"),
            get_header=lambda: SimpleNamespace(conversation_id="header-id"),
        ),
    )

    hint = _coding_resume_hint(session)

    assert hint is not None
    assert hint.heading == "Resume this session with:"
    assert hint.command == ("loushang", "--resume", "session-id")


def test_coding_resume_hint_falls_back_to_header_then_file() -> None:
    session_file = Path("/tmp/a session.jsonl")
    manager = SimpleNamespace(
        get_session_file=lambda: session_file,
        get_header=lambda: SimpleNamespace(conversation_id="header-id"),
    )

    header_hint = _coding_resume_hint(
        SimpleNamespace(session_id=None, session_manager=manager)
    )
    file_hint = _coding_resume_hint(
        SimpleNamespace(
            session_id=None,
            session_manager=SimpleNamespace(
                get_session_file=lambda: session_file,
                get_header=lambda: None,
            ),
        )
    )

    assert header_hint is not None
    assert header_hint.command[-1] == "header-id"
    assert file_hint is not None
    assert file_hint.command[-1] == str(session_file)


def test_coding_resume_hint_requires_a_session_file() -> None:
    session = SimpleNamespace(
        session_id="session-id",
        session_manager=SimpleNamespace(get_session_file=lambda: None),
    )

    assert _coding_resume_hint(session) is None


def test_coding_resume_hint_suppresses_a_known_empty_session() -> None:
    session = SimpleNamespace(
        session_id="empty-session",
        session_manager=SimpleNamespace(
            get_session_file=lambda: Path("/tmp/empty-session.jsonl"),
            get_session_summary=lambda: SimpleNamespace(message_count=0),
        ),
    )

    assert _coding_resume_hint(session) is None
