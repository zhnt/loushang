"""Native terminal loop for the explicit Hosted Mux shell; no process ownership."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import TextIO

from loushang.tui.input import InputReader
from loushang.tui.render_loop import RenderLoop
from loushang.tui.runtime import TuiRuntime
from loushang.tui.terminal import ProcessTerminalPort, TerminalPort
from loushang.tui.terminal_input import InputChunkReader, read_input_chunk
from loushang.tui.terminal_session import TerminalSession

from ..conversation.screen_runner import terminal_size
from .shell import HostedMuxShellV1


async def run_hosted_mux_shell(
    shell: HostedMuxShellV1,
    *,
    stdin: TextIO,
    stdout: TextIO,
    input_chunk_reader: InputChunkReader = read_input_chunk,
    terminal: TerminalPort | None = None,
    session: TerminalSession | None = None,
    settlement: Callable[[], Awaitable[None]] | None = None,
    startup_deadline: float | None = None,
) -> int:
    """Restore terminal mode before settling the selected outer cleanup owner.

    Default/G16 callers retain shell-only cleanup. Foreground Product composition
    may bind one process owner, including UI cleanup, to one absolute deadline.
    Startup failure can re-enter settlement in finally: the callback must join
    the same retained owner and must never grant a new budget on repetition.
    """
    if startup_deadline is not None and (
        type(startup_deadline) not in (int, float) or not math.isfinite(startup_deadline)
    ):
        raise ValueError("invalid startup deadline")
    input_task: asyncio.Task[str] | None = None
    poll_task: asyncio.Task[None] | None = None
    native = session or TerminalSession(stdin=stdin, stdout=stdout)
    runtime = TuiRuntime(
        RenderLoop(shell.screen),
        terminal
        or ProcessTerminalPort(
            output=stdout, size_provider=terminal_size, track_screen=False
        ),
    )

    async def poll() -> None:
        while not shell.exit_requested:
            await shell.poll()
            await asyncio.sleep(0.05)

    try:
        # Authentication/recovery precede terminal takeover. Startup failure
        # must not spend a separate UI budget before the outer settlement owner.
        if startup_deadline is None:
            await shell.start(settlement=settlement)
        else:
            if asyncio.get_running_loop().time() >= startup_deadline:
                raise TimeoutError("hosted_startup_timeout")
            async with asyncio.timeout_at(startup_deadline):
                await shell.start(settlement=settlement)
            if asyncio.get_running_loop().time() >= startup_deadline:
                raise TimeoutError("hosted_startup_timeout")
        with native:
            shell.screen.terminal_capabilities = native.capabilities
            reader = InputReader()
            pending_bytes = 0
            input_task = shell.start_terminal_waiter(lambda: input_chunk_reader(stdin))
            poll_task = shell.start_terminal_waiter(poll)
            runtime.render_now()
            while not shell.exit_requested:
                done, _ = await asyncio.wait(
                    {input_task, poll_task},
                    timeout=0.05,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if poll_task in done:
                    poll_task.result()
                    break
                if input_task in done:
                    data = input_task.result()
                    if data == "":
                        break  # Terminal EOF is detach, never a wait for remote turns.
                    pending_bytes += len(data.encode("utf-8"))
                    if pending_bytes > 64 * 1024 + 32:
                        # Fail visibly rather than interpreting a truncated paste as commands.
                        raise ValueError("terminal_input_limit")
                    events = reader.feed(native.normalize_input_chunk(data))
                    if not reader.has_pending:
                        pending_bytes = 0
                    input_task = shell.start_terminal_waiter(
                        lambda: input_chunk_reader(stdin)
                    )
                else:
                    events = reader.flush() if reader.has_pending else ()
                native.consume_control_events(events)
                native.flush_keyboard_protocol_fallback_if_due()
                size = runtime.terminal.size()
                shell.resize(size.columns, size.rows)
                for event in events:
                    shell.handle(event)
                runtime.render_now()
        return shell.exit_code
    finally:
        # One retained UI owner/deadline covers reader, poll and action waiters
        # and detach, including debt after this runner returns or is cancelled.
        # Native connection cleanup remains the Product command's responsibility.
        await (shell.close() if settlement is None else settlement())


__all__ = ["run_hosted_mux_shell"]
