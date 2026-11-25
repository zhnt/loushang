"""Fixed foreground command control over an existing process/client owner.

UI construction and terminal execution are borrowed exact endpoint bindings.
The public Product wrapper carries no duplicate lifecycle state.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import redirect_stdout, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Protocol, TextIO, TypeAlias, TypeVar

from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxReadV1,
    MuxSelectorV1,
    MuxSpaceV1,
    SessionScopeV1,
    WorkspaceRequestV1,
)

if TYPE_CHECKING:
    from loushang.apphost.launcher import HostedForegroundClientV1
    from loushang.appserver.client import AppServicePortV1, SessionDiscoveryPortV1


class _Shell(Protocol):
    async def close(self) -> None: ...


ShellT = TypeVar("ShellT", bound=_Shell)
_MuxScopes = tuple[tuple[SessionScopeV1, str], ...]
_LocalMuxPresentation: TypeAlias = tuple[
    Callable[[LocalAppClientConnectionV1, MuxSelectorV1, _MuxScopes], ShellT],
    Callable[[ShellT, TextIO], Awaitable[int]],
]


def emit_local_mux_value(value: dict[str, object], stream: TextIO) -> None:
    # ASCII JSON escapes terminal control sequences.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=stream, flush=True)


def mux_member_scopes(mux: MuxSpaceV1) -> _MuxScopes:
    return tuple(
        dict.fromkeys(
            (member.session.scope, member.session.scope_fingerprint)
            for member in mux.members
        )
    )


def _mux_summary(mux: MuxSpaceV1) -> dict[str, object]:
    return {
        "muxId": mux.mux_space_id,
        "name": mux.name,
        "revision": mux.revision,
        "members": len(mux.members),
    }


class _LocalMuxClientCommand(Generic[ShellT]):
    """Own the authenticated local connection through command or terminal settlement."""

    def __init__(
        self,
        root: Path,
        endpoint: str,
        action: str,
        name: str | None,
        output: TextIO,
        *,
        product_id: str,
    ) -> None:
        self._directory = LocalConnectionDirectoryV1(root)
        self._connection = LocalAppClientConnectionV1(
            self._directory,
            endpoint,
            expected_product_id=product_id,
            mode=LocalConnectionModeV1.STOP
            if action == "stop"
            else LocalConnectionModeV1.APP,
        )
        self._action, self._name, self._output = action, name, output
        self.cleanup_pending = True

    async def _attachment_scopes(
        self,
        selector: MuxSelectorV1,
    ) -> _MuxScopes:
        if self._connection.scopes:
            return tuple(
                (item.scope, item.fingerprint) for item in self._connection.scopes
            )
        client = self._connection.client
        mux = await client.read_mux(MuxReadV1(selector))
        scopes = mux_member_scopes(mux)
        if scopes:
            return scopes

        # An empty logical Workspace Mux can have no member-derived scope.
        workspaces = await client.workspace(WorkspaceRequestV1("workspaces"))
        for item in workspaces.workspaces:
            if item.workspace is not None and item.workspace.get("muxName") == mux.name:
                return ((item.scope, item.scope_fingerprint),)
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    async def run(
        self,
        load_presentation: Callable[[], _LocalMuxPresentation[ShellT]],
    ) -> None:
        shell = None
        try:
            await self._connection.start()
            if self._action == "stop":
                emit_local_mux_value({"status": "stop_requested"}, self._output)
                return
            client = self._connection.client
            if self._action == "attach":
                bind_shell, run_shell = load_presentation()
                selector = MuxSelectorV1(name=self._name)
                shell = bind_shell(
                    self._connection, selector, await self._attachment_scopes(selector)
                )
                if await run_shell(shell, self._output):
                    raise RuntimeError("interactive connection ended")
            elif self._action == "list":
                emit_local_mux_value(
                    {
                        "muxes": [
                            _mux_summary(item)
                            for item in (await client.list_muxes()).mux_spaces
                        ]
                    },
                    self._output,
                )
            elif self._action == "create":
                assert self._name is not None
                emit_local_mux_value(
                    _mux_summary(await client.create_mux(MuxCreateV1(self._name))),
                    self._output,
                )
            elif self._action == "close":
                selector = MuxSelectorV1(name=self._name)
                await client.attach_mux(MuxAttachV1(selector))
                await client.close_mux(MuxCloseV1(selector))
                emit_local_mux_value(
                    {"status": "mux_closed", "name": self._name}, self._output
                )
            else:
                raise ValueError("unsupported local management action")
        finally:
            try:
                if shell is not None:
                    await shell.close()
            finally:
                await self._connection.close()
                self._directory.close()
            self.cleanup_pending = False


_ShellArg = TypeVar("_ShellArg", bound=_Shell, contravariant=True)
_ShellFactory: TypeAlias = Callable[
    ["AppServicePortV1", "MuxSpaceV1", "SessionDiscoveryPortV1"], ShellT
]


class _TerminalRunner(Protocol[_ShellArg]):
    async def __call__(
        self,
        shell: _ShellArg,
        *,
        stdin: TextIO,
        stdout: TextIO,
        settlement: Callable[[], Awaitable[None]],
        startup_deadline: float,
    ) -> int: ...


class _Command(Protocol):
    @property
    def cleanup_pending(self) -> bool: ...
    @property
    def process_cleanup_pending(self) -> bool: ...
    async def run(self, *, stdin: TextIO, stdout: TextIO) -> int: ...
    async def close(self, *, retry_timeout: float | None = None) -> None: ...


def _observe(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


class _ForegroundClientControl(Generic[ShellT]):
    def __init__(
        self,
        owner: HostedForegroundClientV1,
        selector: MuxSelectorV1,
        started_at: float,
        bind_shell: Callable[[type[MuxSelectorV1]], _ShellFactory[ShellT]],
        bind_terminal: Callable[[], _TerminalRunner[ShellT]],
    ) -> None:
        self._owner, self._selector, self._started_at = owner, selector, started_at
        self._bind_shell, self._bind_terminal = bind_shell, bind_terminal
        self._shell: ShellT | None = None
        self._startup: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._close_deadline: float | None = None
        self._closing = self._settled = False

    def _remaining(self) -> float:
        remaining = 30 - (time.monotonic() - self._started_at)
        if not 0 < remaining <= 30:
            raise TimeoutError("hosted_startup_timeout")
        return remaining

    def _admit_next(self) -> None:
        if self._closing:
            raise RuntimeError("hosted_client_closed")
        self._remaining()

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    @property
    def process_cleanup_pending(self) -> bool:
        return self._owner.process_cleanup_pending

    async def _prepare(self) -> None:
        await asyncio.sleep(0)  # Publish the task even under eager task factories.
        from loushang.appserver.protocol import (
            AppErrorCodeV1,
            AppServiceError,
            MuxCreateV1,
            MuxReadV1,
            MuxSelectorV1,
        )

        make_shell = self._bind_shell(MuxSelectorV1)

        self._admit_next()
        await self._owner.start()
        self._admit_next()
        client = self._owner.client
        try:
            selected = await client.read_mux(MuxReadV1(self._selector))
        except AppServiceError as error:
            if error.code is not AppErrorCodeV1.NOT_FOUND:
                raise
            self._admit_next()
            assert self._selector.name is not None
            selected = await client.create_mux(MuxCreateV1(self._selector.name))
        self._admit_next()
        discovery = self._owner.discovery_client
        if discovery is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        # No await between the close fence and publication of the UI owner.
        self._shell = make_shell(client, selected, discovery)

    async def run(
        self, public_owner: _Command, *, stdin: TextIO, stdout: TextIO
    ) -> int:
        run_hosted_mux_shell = self._bind_terminal()

        if self._startup is not None or self._closing:
            raise RuntimeError("hosted_client_closed")
        status = 1
        try:
            deadline = asyncio.get_running_loop().time() + self._remaining()
            self._startup = asyncio.create_task(self._prepare())
            self._startup.add_done_callback(_observe)
            done, _ = await asyncio.wait({self._startup}, timeout=self._remaining())
            if not done:
                raise TimeoutError("hosted_startup_timeout")
            await asyncio.shield(self._startup)
            self._admit_next()
            assert self._shell is not None
            status = await run_hosted_mux_shell(
                self._shell,
                stdin=stdin,
                stdout=stdout,
                settlement=public_owner.close,
                startup_deadline=deadline,
            )
        finally:
            await public_owner.close()
        facts = self._owner.diagnostics
        return status or int(facts.forced_exit or facts.exit_code != 0)

    async def close(self, *, retry_timeout: float | None = None) -> None:
        from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

        if retry_timeout is not None and (
            type(retry_timeout) not in (int, float) or not 0 < retry_timeout <= 20
        ):
            raise ValueError("invalid foreground retry budget")
        self._closing = True  # Fence every late startup/mux response before awaits.
        if self._settled:
            return
        if (
            retry_timeout is not None
            and self._close_task is not None
            and not self._close_task.done()
        ):
            raise ValueError("foreground close still running")
        if self._close_task is None or retry_timeout is not None:
            self._close_deadline = asyncio.get_running_loop().time() + (
                retry_timeout or 20
            )
            if self._startup is not None and not self._startup.done():
                self._startup.cancel()
            self._close_task = asyncio.create_task(self._close_once(retry_timeout))
            self._close_task.add_done_callback(_observe)
        assert self._close_deadline is not None
        done, _ = await asyncio.wait(
            {self._close_task},
            timeout=max(0, self._close_deadline - asyncio.get_running_loop().time()),
        )
        if not done:
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        await asyncio.shield(self._close_task)

    async def _close_once(self, retry_timeout: float | None) -> None:
        await asyncio.sleep(0)  # Publish this retained owner before cleanup effects.
        options = {} if retry_timeout is None else {"retry_timeout": retry_timeout}
        await self._owner.close(
            detach=self._shell.close if self._shell else None, **options
        )
        if self._startup is not None:
            await asyncio.gather(self._startup, return_exceptions=True)
        self._settled = True


def _diagnostic(message: str) -> None:
    # A broken diagnostic sink cannot discard process ownership.
    with suppress(OSError, ValueError):
        print(message, file=sys.stderr, flush=True)


async def _recover(command: _Command, retry: asyncio.Event) -> None:
    # No new stdin reader: a failed UI input waiter may still own that stream.
    if command.process_cleanup_pending:
        _diagnostic(
            "hosted_cleanup_pending; controller retained; Ctrl+C explicitly retries cleanup"
        )
    while command.process_cleanup_pending:
        try:
            await asyncio.wait_for(retry.wait(), 0.1)
        except TimeoutError:
            continue
        retry.clear()
        try:
            await command.close(retry_timeout=20)
        except (Exception, asyncio.CancelledError):
            _diagnostic("hosted_cleanup_incomplete")


async def _run_owned(command: _Command, task: asyncio.Task[int]) -> int:
    try:
        return await asyncio.shield(task)
    finally:
        # Cancellation before task entry cannot bypass ownership of the empty host.
        await command.close()


def execute_foreground_command(command: _Command, output: TextIO) -> int:
    from loushang.appserver.protocol import AppServiceError

    runner = asyncio.Runner()
    loop = runner.get_loop()
    task = loop.create_task(command.run(stdin=sys.stdin, stdout=output))
    task.add_done_callback(_observe)
    retry = asyncio.Event()
    interrupted = False

    def interrupt(signum: int, frame: object) -> None:
        nonlocal interrupted
        if not interrupted and not task.done():
            interrupted = True
            loop.call_soon_threadsafe(task.cancel)
        else:
            loop.call_soon_threadsafe(retry.set)

    previous = signal.signal(signal.SIGINT, interrupt)
    status = 1
    with redirect_stdout(sys.stderr):
        try:
            status = runner.run(_run_owned(command, task))
        except (KeyboardInterrupt, asyncio.CancelledError):
            status = 130
            _diagnostic("hosted_interrupted")
        except AppServiceError as error:
            _diagnostic(error.code.value)
        except Exception:
            _diagnostic("hosted_client_failed")
        finally:
            if command.process_cleanup_pending:
                status = status or 1
            # The same non-raising SIGINT handler protects run handoffs, status
            # output and retries, not just awaits within a Runner.run call.
            runner.run(_recover(command, retry))
            if command.cleanup_pending:
                _diagnostic("hosted_cleanup_incomplete")
                os._exit(status or 1)
            signal.signal(signal.SIGINT, previous)
            runner.close()
    return status
