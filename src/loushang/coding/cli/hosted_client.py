"""Explicit installed foreground TUI; no background or default-route activation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import stat
import sys
import time
from collections.abc import Sequence
from contextlib import redirect_stdout, suppress
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from loushang.hosting.contracts import ProcessLaunchRequest

    from ..hosted_bootstrap import CodingHostedLaunchV1


def _launch_request(launch: CodingHostedLaunchV1) -> ProcessLaunchRequest:
    from loushang.hosting.contracts import (
        ProcessLaunchRequest,
        ProcessStderrMode,
        ProcessStdinMode,
        ProcessStdoutMode,
        ProcessStreamSpec,
    )

    return ProcessLaunchRequest(
        (
            sys.executable, "-I", "-m", "loushang.coding.cli.hosted",
            "--workspace", str(launch.workspace),
            "--application-root", str(launch.application_root),
            "--application-id", launch.application_id,
            "--cwd-sessions", str(launch.cwd_sessions),
            "--home-sessions", str(launch.home_sessions),
            "--session-discovery",
        ),
        str(launch.workspace),
        tuple(sorted(os.environ.items())),
        ProcessStreamSpec(
            ProcessStdinMode.PIPE, ProcessStdoutMode.PIPE, ProcessStderrMode.CAPTURE_TAIL
        ),
    )


def _launch_identity(request: ProcessLaunchRequest) -> tuple[int, ...]:
    executable, cwd = os.stat(request.argv[0]), os.stat(request.cwd)
    if not stat.S_ISREG(executable.st_mode) or not stat.S_ISDIR(cwd.st_mode):
        raise ValueError("hosted_launch_changed")
    return (
        executable.st_dev, executable.st_ino, executable.st_mode,
        executable.st_size, executable.st_mtime_ns,
        cwd.st_dev, cwd.st_ino, cwd.st_mode,
    )


class _PreparedLaunch:
    def __init__(self, request: ProcessLaunchRequest, identity: tuple[int, ...]) -> None:
        self.request = request
        self._identity, self._closed = identity, False

    async def verify_current(self) -> None:
        if self._closed or _launch_identity(self.request) != self._identity:
            raise ValueError("hosted_launch_changed")

    async def close(self) -> None:
        self._closed = True


class _LaunchPreparation:
    """Recheck the whole admitted request, not sealed execution or sandboxing.

    Preserve the venv interpreter's path; resolving its symlink can select a
    different installation. Isolated Python ignores workspace/PYTHONPATH and
    user-site imports. The installed environment itself remains trusted.
    """

    def __init__(self, request: ProcessLaunchRequest) -> None:
        self._request = request
        self._identity = _launch_identity(request)
        self._used = False

    async def prepare(self, request: ProcessLaunchRequest) -> _PreparedLaunch:
        if self._used or type(request) is not type(self._request) or request != self._request:
            raise ValueError("hosted_launch_not_admitted")
        self._used = True
        return _PreparedLaunch(self._request, self._identity)


def _observe(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


class CodingHostedTuiCommandV1:
    """Product launch intent, prefix-task fence and one terminal settlement.

    The 30-second clock starts at main entry, not before Python imports this
    module's parent packages. No new launch/mux/terminal step is admitted after
    expiry; in-flight effects remain owned and reclaimed.
    """

    def __init__(
        self, launch: CodingHostedLaunchV1, *, mux_name: str = "main",
        started_at: float | None = None,
    ) -> None:
        self._started_at = time.monotonic() if started_at is None else started_at
        self._remaining()
        from loushang.apphost.launcher import HostedForegroundClientV1
        from loushang.appserver.protocol import MuxSelectorV1
        from loushang.hosting.runtime import create_process_host

        self._launch = launch
        self._selector = MuxSelectorV1(name=mux_name)
        request = _launch_request(launch)
        preparation = _LaunchPreparation(request)
        remaining = self._remaining()
        self._owner = HostedForegroundClientV1(
            request, host=create_process_host(max_processes=1),
            preparation=preparation, startup_timeout=remaining,
        )
        from loushang.harnesstui.mux.shell import HostedMuxShellV1

        self._shell: HostedMuxShellV1 | None = None
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
        from loushang.harnesstui.mux.shell import HostedMuxShellV1

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
        self._shell = HostedMuxShellV1(
            client, selector=MuxSelectorV1(mux_space_id=selected.mux_space_id),
            product_id="coding",
            scopes=tuple((scope.scope, scope.fingerprint) for scope in self._launch.scopes),
            discovery_client=discovery, close_timeout=20,
            exit_ends_application=True,
        )

    async def run(self, *, stdin: TextIO, stdout: TextIO) -> int:
        from loushang.harnesstui.mux.terminal import run_hosted_mux_shell

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
                self._shell, stdin=stdin, stdout=stdout,
                settlement=self.close, startup_deadline=deadline,
            )
        finally:
            await self.close()
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
        if retry_timeout is not None and self._close_task is not None and not self._close_task.done():
            raise ValueError("foreground close still running")
        if self._close_task is None or retry_timeout is not None:
            self._close_deadline = asyncio.get_running_loop().time() + (retry_timeout or 20)
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
        await self._owner.close(detach=self._shell.close if self._shell else None, **options)
        if self._startup is not None:
            await asyncio.gather(self._startup, return_exceptions=True)
        self._settled = True


def _diagnostic(message: str) -> None:
    # A broken diagnostic sink cannot discard process ownership.
    with suppress(OSError, ValueError):
        print(message, file=sys.stderr, flush=True)


async def _recover(command: CodingHostedTuiCommandV1, retry: asyncio.Event) -> None:
    # No new stdin reader: a failed UI input waiter may still own that stream.
    if command.process_cleanup_pending:
        _diagnostic("hosted_cleanup_pending; controller retained; Ctrl+C explicitly retries cleanup")
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


async def _run_owned(command: CodingHostedTuiCommandV1, task: asyncio.Task[int]) -> int:
    try:
        return await asyncio.shield(task)
    finally:
        # Cancellation before task entry cannot bypass ownership of the empty host.
        await command.close()


def _execute(command: CodingHostedTuiCommandV1, output: TextIO) -> int:
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


def main(argv: Sequence[str] | None = None) -> int:
    started_at = time.monotonic()
    parser = argparse.ArgumentParser(
        prog="loushang-hosted-tui",
        description="Explicit foreground Coding TUI; exit ends its application, never backgrounds it.",
    )
    for flag in ("workspace", "application-root", "cwd-sessions", "home-sessions"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument("--application-id", default="coding.default")
    parser.add_argument("--mux", default="main", help="select this mux, creating it only if absent")
    parser.add_argument("--describe", action="store_true", help="path-free selectors without startup")
    args = parser.parse_args(argv)
    output = sys.stdout
    if not args.describe and (not sys.stdin.isatty() or not output.isatty()):
        parser.error("interactive foreground client requires terminal input and output")
    try:
        from loushang.appserver.protocol import MuxSelectorV1
        from loushang.appserver.protocol.connection_profile import (
            AppConnectionProfileV1,
        )

        from ..hosted_bootstrap import CodingHostedLaunchV1

        MuxSelectorV1(name=args.mux)
        launch = CodingHostedLaunchV1(
            args.workspace.expanduser().resolve(),
            args.application_root.expanduser().resolve(), args.application_id,
            args.cwd_sessions.expanduser().resolve(), args.home_sessions.expanduser().resolve(),
        )
        if args.describe:
            value = launch.describe(profile=AppConnectionProfileV1.STDIO_DISCOVERY)
            value.update(exitEndsApplication=True, mux=args.mux)
            print(json.dumps(value, ensure_ascii=True, sort_keys=True))
            return 0
        command = CodingHostedTuiCommandV1(launch, mux_name=args.mux, started_at=started_at)
    except Exception:
        print("hosted_configuration_unavailable", file=sys.stderr)
        return 1
    return _execute(command, output)


if __name__ == "__main__":
    raise SystemExit(main())
