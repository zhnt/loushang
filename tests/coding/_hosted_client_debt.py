"""POSIX real-process debt probe; only cleanup delay and terminal are synthetic."""

from __future__ import annotations

import asyncio
import sys
from io import StringIO
from pathlib import Path

from loushang.coding.cli.hosted_client import CodingHostedTuiCommandV1, _execute
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.harnesstui.mux import terminal
from loushang.hosting import runtime
from loushang.tui.terminal import FakeTerminalPort, TerminalSize
from loushang.tui.terminal_session import TerminalSession

root = Path(sys.argv[1])
create_host = runtime.create_process_host


class HeldLease:
    def __init__(self, lease):
        self._lease = lease
        # Native test instrumentation only; no Product code reads backend PIDs.
        (root / "child.pid").write_text(str(lease._process._process.pid))

    def __getattr__(self, name):
        return getattr(self._lease, name)

    async def close_stdin(self):
        pass  # Model a child which does not observe graceful EOF.

    async def terminate(self):
        while not (root / "release-reclamation").exists():
            await asyncio.sleep(0.01)
        return await self._lease.terminate()


class Host:
    def __init__(self, **kwargs):
        self._host = create_host(**kwargs)

    async def start(self, *args):
        return HeldLease(await self._host.start(*args))

    async def close(self):
        await self._host.close()


class Mode:
    def __enter__(self):
        pass

    def __exit__(self, *args):
        (root / "terminal-restored").touch()


async def eof(stream):
    return ""


run_terminal = terminal.run_hosted_mux_shell


async def simulated_terminal(shell, **kwargs):
    return await run_terminal(
        shell, **kwargs, input_chunk_reader=eof,
        terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=24)),
        session=TerminalSession(kwargs["stdin"], kwargs["stdout"], mode_factory=lambda *args: Mode()),
    )


runtime.create_process_host = Host
terminal.run_hosted_mux_shell = simulated_terminal
launch = CodingHostedLaunchV1(
    root, root / "application", "coding.default", root / "cwd", root / "home"
)
command = CodingHostedTuiCommandV1(launch)
command._owner._close_timeout = 0.1
command._owner._graceful_timeout = 0.02
raise SystemExit(_execute(command, StringIO()))
