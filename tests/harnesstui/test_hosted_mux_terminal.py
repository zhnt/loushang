from __future__ import annotations

import asyncio
from io import StringIO

import pytest

from loushang.harnesstui.mux.terminal import run_hosted_mux_shell
from loushang.tui.terminal import FakeTerminalPort, TerminalSize
from loushang.tui.terminal_session import TerminalSession

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_shell import _shell


def test_G16_TERMINAL_playback_edits_switches_and_restores_mode_on_detach():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        chunks = iter(("hello", "\t", "second", "\x02", "d"))
        events = []

        class Mode:
            def __enter__(self):
                events.append("entered")

            def __exit__(self, *args):
                events.append("restored")

        async def read(stream):
            await asyncio.sleep(0)
            return next(chunks, "")

        stdin, stdout = StringIO(), StringIO()
        terminal = FakeTerminalPort(size=TerminalSize(columns=60, rows=24))
        code = await run_hosted_mux_shell(
            shell,
            stdin=stdin,
            stdout=stdout,
            input_chunk_reader=read,
            terminal=terminal,
            session=TerminalSession(stdin, stdout, mode_factory=lambda *args: Mode()),
        )
        assert code == 0
        assert events == ["entered", "restored"]
        assert len(terminal.frames) >= 3
        assert any("dev" in frame.serialized_output for frame in terminal.frames)
        assert [name for name, _ in client.calls] == ["attach", "detach"]
        assert not shell.cleanup_pending

    asyncio.run(scenario())


def test_G16_TERMINAL_oversized_unterminated_paste_fails_without_command_execution():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        chunks = iter(("\x1b[200~", "x" * 64_000, "x" * 2_000, "/close --yes\r"))
        restored = []

        class Mode:
            def __enter__(self):
                pass

            def __exit__(self, *args):
                restored.append(True)

        async def read(stream):
            return next(chunks, "")

        stdin, stdout = StringIO(), StringIO()
        with pytest.raises(ValueError, match="terminal_input_limit"):
            await run_hosted_mux_shell(
                shell,
                stdin=stdin,
                stdout=stdout,
                input_chunk_reader=read,
                terminal=FakeTerminalPort(size=TerminalSize(columns=60, rows=24)),
                session=TerminalSession(
                    stdin, stdout, mode_factory=lambda *args: Mode()
                ),
            )
        assert restored == [True]
        assert [name for name, _ in client.calls] == ["attach", "detach"]
        assert not shell.cleanup_pending

    asyncio.run(scenario())


def test_G16_TERMINAL_shell_retains_reader_debt_and_repeated_close_joins_one_budget():
    async def scenario():
        from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

        shell = _shell(_Client())
        shell._timeout = 0.03
        await shell.start()
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def read():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return ""

        task = shell.start_terminal_waiter(read)
        await entered.wait()
        with pytest.raises(AppServiceError) as debt:
            await shell.close()
        assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert cancelled.is_set() and not task.done() and shell.cleanup_pending
        assert task in shell._terminal_waiters
        assert [name for name, _ in shell._client.calls] == ["attach"]
        release.set()
        await asyncio.wait_for(task, 1)
        await shell.close()
        assert not shell.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("lost_reply", [False, True])
def test_G16_TERMINAL_restore_precedes_detach_debt_and_close_never_resends(lost_reply):
    from loushang.appserver.protocol import AckV1, AppErrorCodeV1, AppServiceError

    async def scenario():
        client = _Client()
        shell = _shell(client)
        shell._timeout = 0.03
        events, release = [], asyncio.Event()

        class Mode:
            def __enter__(self):
                events.append("entered")

            def __exit__(self, *args):
                events.append("restored")

        async def detach(request):
            events.append("detach")
            if lost_reply:
                raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
            await release.wait()
            return AckV1()

        async def eof(stream):
            return ""

        client.detach_mux = detach
        stdin, stdout = StringIO(), StringIO()
        with pytest.raises(AppServiceError) as error:
            await run_hosted_mux_shell(
                shell,
                stdin=stdin,
                stdout=stdout,
                input_chunk_reader=eof,
                terminal=FakeTerminalPort(size=TerminalSize(columns=60, rows=24)),
                session=TerminalSession(
                    stdin, stdout, mode_factory=lambda *args: Mode()
                ),
            )
        assert error.value.code is (
            AppErrorCodeV1.SERVICE_CLOSED
            if lost_reply
            else AppErrorCodeV1.CLEANUP_INCOMPLETE
        )
        assert events == ["entered", "restored", "detach"]
        task, deadline = shell._detach_task, shell._deadline
        assert shell.cleanup_pending and task.done() is lost_reply
        assert not shell._terminal_waiters
        with pytest.raises(AppServiceError):
            await shell.close()
        assert shell._detach_task is task and shell._deadline == deadline
        assert events.count("detach") == 1
        if not lost_reply:
            release.set()
            await asyncio.wait_for(task, 1)
            await shell.close()
            assert not shell.cleanup_pending
        else:
            assert shell.cleanup_pending  # Unknown result is not a clean detach.

    asyncio.run(asyncio.wait_for(scenario(), 2))
