from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.cli import (
    SessionResolutionRequest,
    agent_session_resolution_request,
    resolve_agent_cli_session,
    resolve_session,
)


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def new_session_operation(self, *, cwd: str):
        self.calls.append(("new", cwd))
        return type("Operation", (), {"current": "new-session"})()

    async def restore_session_operation(self, session_ref: str):
        self.calls.append(("restore", session_ref))
        return type("Operation", (), {"current": f"restored:{session_ref}"})()

    async def fork_session_operation(self, entry_id: str, *, position: str):
        self.calls.append(("fork", (entry_id, position)))
        return type("Operation", (), {"current": "forked"})()

    def list_sessions(self):
        return [type("Record", (), {"session_file": Path("/tmp/latest.jsonl")})()]


def test_agent_session_flags_project_resolution_request() -> None:
    from types import SimpleNamespace

    request = agent_session_resolution_request(
        SimpleNamespace(
            session="session-1",
            continue_=False,
            resume=False,
            fork="leaf-1",
        ),
        cwd="/workspace",
    )

    assert request == SessionResolutionRequest(
        session="session-1",
        fork="leaf-1",
        cwd="/workspace",
    )


def test_resolve_session_selects_new_restore_and_fork_operations() -> None:
    runtime = _Runtime()
    result = asyncio.run(
        resolve_session(
            runtime,
            SessionResolutionRequest(
                resume="session.jsonl",
                fork="entry-1",
                cwd=Path("/tmp/project"),
            ),
        )
    )
    assert result == "forked"
    assert runtime.calls == [
        ("restore", "session.jsonl"),
        ("fork", ("entry-1", "at")),
    ]


def test_resolve_agent_cli_session_projects_standard_arguments() -> None:
    from types import SimpleNamespace

    runtime = _Runtime()
    result = asyncio.run(
        resolve_agent_cli_session(
            SimpleNamespace(
                session="session-1",
                continue_=False,
                resume=False,
                fork="leaf-1",
            ),
            runtime,
            Path("/tmp/project"),
        )
    )

    assert result == "forked"
    assert runtime.calls == [
        ("restore", "session-1"),
        ("fork", ("leaf-1", "at")),
    ]


def test_resolve_session_continue_requires_an_existing_session() -> None:
    class EmptyRuntime(_Runtime):
        def list_sessions(self):
            return []

    with pytest.raises(RuntimeError, match="No existing session found"):
        asyncio.run(
            resolve_session(EmptyRuntime(), SessionResolutionRequest(continue_=True))
        )
