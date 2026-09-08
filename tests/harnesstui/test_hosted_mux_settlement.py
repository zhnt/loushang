"""G17 foreground composition must not stack UI and process close budgets."""

from __future__ import annotations

import asyncio
from io import StringIO

import pytest

from loushang.harnesstui.mux.terminal import run_hosted_mux_shell
from loushang.tui.terminal import FakeTerminalPort, TerminalSize
from loushang.tui.terminal_session import TerminalSession

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_shell import _shell


@pytest.mark.parametrize("failure", [None, "attach", "terminal"])
def test_G17_SETTLEMENT_one_outer_policy_covers_exit_and_startup_failures(failure):
    async def scenario():
        client = _Client()
        shell = _shell(client)
        events = []
        close = shell.close

        async def observed_close():
            events.append("ui.close")
            await close()

        shell.close = observed_close

        async def settlement():
            events.append("outer.settlement")
            await shell.close()

        if failure == "attach":

            async def attach(request):
                raise ValueError("attach failed")

            client.attach_mux = attach

        class Mode:
            def __enter__(self):
                events.append("terminal.enter")
                if failure == "terminal":
                    raise ValueError("terminal failed")

            def __exit__(self, *args):
                events.append("terminal.restore")

        async def eof(stream):
            return ""

        stdin, stdout = StringIO(), StringIO()

        async def run():
            return await run_hosted_mux_shell(
                shell,
                stdin=stdin,
                stdout=stdout,
                input_chunk_reader=eof,
                terminal=FakeTerminalPort(size=TerminalSize(columns=60, rows=24)),
                session=TerminalSession(
                    stdin, stdout, mode_factory=lambda *args: Mode()
                ),
                settlement=settlement,
            )

        if failure:
            with pytest.raises(ValueError, match=f"{failure} failed"):
                await run()
        else:
            assert await run() == 0
        assert "outer.settlement" in events
        assert events.index("outer.settlement") < events.index("ui.close")
        if failure is None:
            assert events.index("terminal.restore") < events.index("outer.settlement")
        assert not shell.cleanup_pending
        assert [name for name, _ in client.calls].count("detach") <= 1

    asyncio.run(scenario())


def test_G17_SETTLEMENT_startup_cancellation_enters_outer_owner_before_ui_close():
    async def scenario():
        client = _Client()
        entered, release = asyncio.Event(), asyncio.Event()
        events = []
        original = client.attach_mux

        async def attach(request):
            entered.set()
            await release.wait()
            return await original(request)

        client.attach_mux = attach
        shell = _shell(client)
        original_close = shell.close

        async def observed_close():
            events.append("ui.close")
            await original_close()

        shell.close = observed_close

        async def settlement():
            events.append("outer.settlement")
            release.set()  # Stand-in for the outer owner's independent reclamation.
            await shell.close()

        task = asyncio.create_task(shell.start(settlement=settlement))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            assert events == ["outer.settlement", "ui.close"]
            assert not shell.cleanup_pending
            assert [name for name, _ in client.calls] == ["attach", "detach"]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await original_close()

    asyncio.run(scenario())


def test_G17_SETTLEMENT_cleanup_failure_remains_visible_after_terminal_restore():
    async def scenario():
        shell = _shell(_Client())
        events = []

        class Mode:
            def __enter__(self):
                events.append("entered")

            def __exit__(self, *args):
                events.append("restored")

        async def settlement():
            events.append("settlement")
            raise RuntimeError("cleanup debt")

        async def eof(stream):
            return ""

        stdin, stdout = StringIO(), StringIO()
        try:
            with pytest.raises(RuntimeError, match="cleanup debt"):
                await run_hosted_mux_shell(
                    shell,
                    stdin=stdin,
                    stdout=stdout,
                    input_chunk_reader=eof,
                    terminal=FakeTerminalPort(size=TerminalSize(columns=60, rows=24)),
                    session=TerminalSession(
                        stdin, stdout, mode_factory=lambda *args: Mode()
                    ),
                    settlement=settlement,
                )
            assert events == ["entered", "restored", "settlement"]
            assert shell.cleanup_pending
        finally:
            await shell.close()

    asyncio.run(scenario())
