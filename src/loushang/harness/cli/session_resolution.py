"""Shared CLI-to-session resolution over the Harness lifecycle capability."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from loushang.harness.cli.agent_args import AgentCliArgs
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session import require_session_operation_session


@dataclass(frozen=True, slots=True)
class SessionResolutionRequest:
    session: str | None = None
    continue_: bool = False
    resume: bool | str = False
    fork: str | None = None
    cwd: str | Path = "."


class SessionResolutionRuntime(Protocol):
    async def restore_session_operation(
        self,
        session: str,
    ) -> SessionOperationResult[Any, Any]: ...

    async def new_session_operation(
        self,
        *,
        cwd: str,
    ) -> SessionOperationResult[Any, Any]: ...

    async def fork_session_operation(
        self,
        entry_id: str,
        *,
        position: str,
    ) -> SessionOperationResult[Any, Any]: ...

    def list_sessions(self) -> list[object]: ...


def agent_session_resolution_request(
    args: AgentCliArgs,
    *,
    cwd: str | Path,
) -> SessionResolutionRequest:
    return SessionResolutionRequest(
        session=args.session,
        continue_=args.continue_,
        resume=args.resume,
        fork=args.fork,
        cwd=cwd,
    )


async def resolve_session(
    runtime: SessionResolutionRuntime,
    request: SessionResolutionRequest,
) -> object:
    """Resolve a new, resumed, continued, or forked session."""

    if isinstance(request.resume, str):
        session = require_session_operation_session(
            await runtime.restore_session_operation(request.resume)
        )
    elif request.continue_ or request.resume:
        latest_session_file = resolve_latest_session_file(runtime)
        if latest_session_file is None:
            raise RuntimeError(
                "No existing session found. Use --session or --resume <session> "
                "to restore a specific session."
            )
        session = require_session_operation_session(
            await runtime.restore_session_operation(latest_session_file)
        )
    elif request.session:
        session = require_session_operation_session(
            await runtime.restore_session_operation(request.session)
        )
    else:
        session = require_session_operation_session(
            await runtime.new_session_operation(cwd=str(request.cwd))
        )

    if request.fork:
        try:
            session = require_session_operation_session(
                await runtime.fork_session_operation(request.fork, position="at")
            )
        except Exception as error:
            raise RuntimeError(f"Failed to fork session: {error}") from error
    return session


async def resolve_agent_cli_session(
    args: AgentCliArgs,
    runtime: SessionResolutionRuntime,
    project_root: str | Path,
) -> object:
    """Resolve one standard Agent CLI session request."""

    return await resolve_session(
        runtime,
        agent_session_resolution_request(args, cwd=project_root),
    )


def resolve_latest_session_file(runtime: SessionResolutionRuntime) -> str | None:
    try:
        sessions = runtime.list_sessions()
    except Exception as error:
        raise RuntimeError(f"Failed to list sessions: {error}") from error
    if not isinstance(sessions, list):
        raise RuntimeError("session listing returned an invalid response.")
    if not sessions:
        return None
    for latest_session in sessions:
        session_file = getattr(latest_session, "session_file", None)
        if session_file is not None:
            return str(session_file)
    return None


__all__ = [
    "SessionResolutionRequest",
    "SessionResolutionRuntime",
    "agent_session_resolution_request",
    "resolve_agent_cli_session",
    "resolve_latest_session_file",
    "resolve_session",
]
