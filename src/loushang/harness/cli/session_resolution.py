"""Shared CLI-to-session resolution over the Harness lifecycle capability."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TextIO

from loushang.harness.cli.agent_args import AgentCliArgs
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session import require_session_operation_session
from loushang.harness.transcript import SessionQuery

if TYPE_CHECKING:
    from loushang.harness.continuity import ContinuityTarget
    from loushang.harness.continuity._binding_lifetime import (
        _ContinuityCompositionLifetime,
    )

_COMPATIBILITY_SESSION_PRIORITIES = {
    "sessions.cwd_compatibility": 10,
    "sessions.home_compatibility": 20,
}


def prepare_platform_session_directory(path: Path) -> None:
    """Prepare the selected platform directory before opening a Session writer."""
    from loushang.harness.machine_resources import prepare_private_directory_chain

    prepare_private_directory_chain(path)
    path.chmod(0o700)


def configure_agent_cli_session_discovery(
    runtime: object, *, cwd: Path, session_dir: Path
) -> None:
    """Bind the platform Session writer and its read-only compatibility sources."""
    from loushang.harness.machine_resources import resolve_machine_resource_layout
    from loushang.harness.transcript import (
        SessionDiscoverySource,
        session_origin_from_resource_id,
    )

    layout = resolve_machine_resource_layout(cwd=cwd)
    platform_sessions = layout.sessions
    if session_dir.expanduser().resolve(strict=False) != platform_sessions:
        return
    prepare_platform_session_directory(platform_sessions)
    set_authority = getattr(runtime, "set_session_authority_source", None)
    if callable(set_authority):
        set_authority(
            SessionDiscoverySource(
                source_id="sessions.global",
                root=platform_sessions,
                mode="canonical",
                origin="global",
                priority=0,
            )
        )
    add_source = getattr(runtime, "add_session_discovery_source", None)
    if callable(add_source):
        for resource in layout.resources:
            if (
                resource.resource_id.startswith("sessions.")
                and resource.mode == "compatibility"
            ):
                add_source(
                    SessionDiscoverySource(
                        source_id=resource.resource_id,
                        root=resource.path,
                        mode="compatibility",
                        origin=session_origin_from_resource_id(resource.resource_id),
                        priority=_COMPATIBILITY_SESSION_PRIORITIES.get(
                            resource.resource_id, 100
                        ),
                    )
                )
    else:
        add_legacy_source = getattr(runtime, "add_session_discovery_dir", None)
        if callable(add_legacy_source):
            add_legacy_source(cwd / ".loushang" / "sessions")


@dataclass(frozen=True, slots=True)
class SessionResolutionRequest:
    session: str | None = None
    continue_: bool = False
    resume: bool | str = False
    fork: str | None = None
    cwd: str | Path = "."
    all_sessions: bool = False


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
        all_sessions=bool(getattr(args, "all_sessions", False)),
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
        latest_session_file = resolve_latest_session_file(
            runtime,
            cwd=None if request.all_sessions else request.cwd,
            discovered=request.all_sessions,
        )
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


class _ContinuitySelection(Protocol):
    @property
    def activation_result(self) -> object: ...


async def resolve_agent_cli_continuity_session(
    runtime: object,
    *,
    open_composition: Callable[[], Awaitable[_ContinuityCompositionLifetime]],
    shutdown_continuity: Callable[[object], Awaitable[None]],
    run_picker: Callable[..., Awaitable[_ContinuitySelection | None]],
    stdin: TextIO,
    stdout: TextIO,
    settings_manager: object | None,
    cleanup_label: str,
) -> object | None:
    """Activate a picked session, releasing the startup composition on exit."""
    from loushang.harness.continuity import consume_prepared_activation

    try:
        composition = await open_composition()
    except BaseException as bootstrap_error:
        try:
            await shutdown_continuity(runtime)
        except BaseException as cleanup_error:
            bootstrap_error.add_note(
                f"{cleanup_label} also failed: {type(cleanup_error).__name__}"
            )
        raise

    reference = composition.hub.reference()
    session = None
    try:

        async def activate(target: ContinuityTarget) -> object:
            return await consume_prepared_activation(await reference.prepare(target))

        get_keybindings = getattr(settings_manager, "get_keybindings", None)
        selection = await run_picker(
            reference=reference,
            activate=activate,
            stdin=stdin,
            stdout=stdout,
            keybindings=get_keybindings() if callable(get_keybindings) else None,
        )
        if selection is None:
            return None
        session = getattr(selection.activation_result, "current", None)
        if session is None:
            get_session = getattr(runtime, "get_current_session", None)
            session = get_session() if callable(get_session) else None
        if session is None:
            raise RuntimeError("Continuity activation did not publish a Product session")
        return session
    finally:
        reference.release()
        await composition.dispose()
        if session is None:
            await shutdown_continuity(runtime)


def resolve_latest_session_file(
    runtime: SessionResolutionRuntime,
    *,
    cwd: str | Path | None = None,
    discovered: bool = False,
) -> str | None:
    """Return the newest resumable transcript, scoped to ``cwd`` when possible."""

    try:
        finder = getattr(runtime, "find_discovered_session_summaries", None)
        if not callable(finder):
            finder = getattr(runtime, "find_session_summaries", None)
        sessions = (
            finder(
                SessionQuery(
                    cwd=str(Path(cwd).expanduser().resolve(strict=False)),
                    sort_by="recent",
                )
            )
            if cwd is not None and callable(finder)
            else finder(SessionQuery(sort_by="recent"))
            if discovered and callable(finder)
            else runtime.list_sessions()
        )
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
    "resolve_agent_cli_continuity_session",
    "resolve_agent_cli_session",
    "resolve_latest_session_file",
    "resolve_session",
]
