"""Explicit installed foreground TUI; no background or default-route activation."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from loushang.apphost.integrations._foreground_client_control import (
        _ShellFactory,
        _TerminalRunner,
    )
    from loushang.apphost.launcher import HostedForegroundClientV1
    from loushang.appserver.client import AppServicePortV1, SessionDiscoveryPortV1
    from loushang.appserver.protocol import MuxSelectorV1, MuxSpaceV1
    from loushang.coding.hosted.bootstrap import CodingHostedLaunchV1
    from loushang.harnesstui.mux.shell import HostedMuxShellV1
    from loushang.hosting.contracts import ProcessLaunchRequest


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
            "--session-execution",
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


class CodingHostedTuiCommandV1:
    """Product launch intent, prefix-task fence and one terminal settlement.

    The 30-second clock starts at main entry, not before Python imports this
    module's parent packages. No new launch/mux/terminal step is admitted after
    expiry; in-flight effects remain owned and reclaimed.
    """

    def __init__(
        self,
        launch: CodingHostedLaunchV1,
        *,
        mux_name: str = "main",
        started_at: float | None = None,
    ) -> None:
        started_at = time.monotonic() if started_at is None else started_at
        _remaining_at(started_at)
        from loushang.apphost.integrations._foreground_client_control import (
            _ForegroundClientControl,
        )
        from loushang.apphost.launcher import HostedForegroundClientV1
        from loushang.appserver.protocol import MuxSelectorV1
        from loushang.appserver.protocol.connection_profile import (
            AppConnectionProfileV1,
        )
        from loushang.hosting.runtime import create_process_host

        selector = MuxSelectorV1(name=mux_name)
        request = _launch_request(launch)
        preparation = _LaunchPreparation(request)
        remaining = _remaining_at(started_at)
        owner = HostedForegroundClientV1(
            request,
            host=create_process_host(max_processes=1),
            preparation=preparation,
            startup_timeout=remaining,
            profile=AppConnectionProfileV1.STDIO_DISCOVERY_EXECUTION,
        )
        # Preserve this original late import, including constructor failure.
        from loushang.harnesstui.mux.shell import HostedMuxShellV1  # noqa: F401

        def bind_shell(
            selector_type: type[MuxSelectorV1],
        ) -> _ShellFactory[HostedMuxShellV1]:
            return _bind_shell_factory(launch, owner, selector_type)

        self._control: _ForegroundClientControl[HostedMuxShellV1] = (
            _ForegroundClientControl(
                owner, selector, started_at, bind_shell, _bind_terminal_runner
            )
        )

    @property
    def cleanup_pending(self) -> bool:
        return self._control.cleanup_pending

    @property
    def process_cleanup_pending(self) -> bool:
        return self._control.process_cleanup_pending

    async def run(self, *, stdin: TextIO, stdout: TextIO) -> int:
        return await self._control.run(self, stdin=stdin, stdout=stdout)

    async def close(self, *, retry_timeout: float | None = None) -> None:
        await self._control.close(retry_timeout=retry_timeout)


def _remaining_at(started_at: float) -> float:
    remaining = 30 - (time.monotonic() - started_at)
    if not 0 < remaining <= 30:
        raise TimeoutError("hosted_startup_timeout")
    return remaining


def _bind_shell_factory(
    launch: CodingHostedLaunchV1,
    owner: HostedForegroundClientV1,
    selector_type: type[MuxSelectorV1],
) -> _ShellFactory[HostedMuxShellV1]:
    from loushang.harnesstui.conversation.theme import terminal_transcript_theme
    from loushang.harnesstui.mux.shell import HostedMuxShellV1

    def construct(
        client: AppServicePortV1,
        selected: MuxSpaceV1,
        discovery: SessionDiscoveryPortV1,
    ) -> HostedMuxShellV1:
        return HostedMuxShellV1(
            client,
            selector=selector_type(mux_space_id=selected.mux_space_id),
            product_id="coding",
            scopes=tuple((scope.scope, scope.fingerprint) for scope in launch.scopes),
            discovery_client=discovery,
            close_timeout=20,
            execution_client=owner.execution_client,
            exit_ends_application=True,
            transcript_theme=terminal_transcript_theme(),
        )

    return construct


def _bind_terminal_runner() -> _TerminalRunner[HostedMuxShellV1]:
    from loushang.harnesstui.mux.terminal import run_hosted_mux_shell

    return run_hosted_mux_shell


def _execute(command: CodingHostedTuiCommandV1, output: TextIO) -> int:
    from loushang.apphost.integrations._foreground_client_control import (
        execute_foreground_command,
    )

    return execute_foreground_command(command, output)


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
        from loushang.coding.hosted.bootstrap import CodingHostedLaunchV1

        MuxSelectorV1(name=args.mux)
        launch = CodingHostedLaunchV1(
            args.workspace.expanduser().resolve(),
            args.application_root.expanduser().resolve(), args.application_id,
            args.cwd_sessions.expanduser().resolve(), args.home_sessions.expanduser().resolve(),
        )
        if args.describe:
            value = launch.describe(
                profile=AppConnectionProfileV1.STDIO_DISCOVERY_EXECUTION
            )
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
