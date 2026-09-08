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


def test_G17_connection_closed_error_retains_legacy_identity():
    from loushang.appserver.client import AppConnectionClosedError
    from loushang.appserver.framing import AppConnectionClosedError as LegacyClosed
    from loushang.appserver.framing import AppConnectionEOFError
    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

    assert LegacyClosed is AppConnectionClosedError
    assert issubclass(AppConnectionEOFError, AppConnectionClosedError)
    assert isinstance(AppConnectionClosedError(), AppServiceError)
    assert AppConnectionClosedError().code is AppErrorCodeV1.SERVICE_CLOSED


@pytest.mark.parametrize("hold_cancel", [False, True])
def test_G17_SETTLEMENT_cancelled_poll_send_closes_local_attachment(hold_cancel):
    from loushang.appserver.protocol.connection_profile import (
        AppConnectionProfileV1,
        connection_hello,
    )
    from loushang.appserver.remote_client import RemoteAppClientV1

    async def scenario():
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        hello = connection_hello(AppConnectionProfileV1.STDIO)
        sends, closed, detached = [], [], []

        class Stream:
            first = True

            async def receive(self):
                if self.first:
                    self.first = False
                    return hello
                await asyncio.Event().wait()

            async def send(self, value):
                if value == hello:
                    return
                sends.append(value)
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    if hold_cancel:
                        await release.wait()
                    raise

            async def close(self):
                closed.append(True)

        remote = RemoteAppClientV1(Stream(), profile=AppConnectionProfileV1.STDIO)
        await remote.start()
        client = _Client()
        client.read_events = remote.read_events

        async def detach(request):
            detached.append(request)
            return await remote.detach_mux(request)

        client.detach_mux = detach
        shell = _shell(client)
        await shell.start()
        poll = shell.start_terminal_waiter(shell.poll)
        settlement = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            settlement = asyncio.create_task(shell.close())
            await asyncio.wait_for(cancelled.wait(), 1)
            if hold_cancel:
                assert not settlement.done() and shell.cleanup_pending
                assert shell.state is not None and not detached
            release.set()
            await asyncio.wait_for(settlement, 1)
            assert poll.done() and poll.cancelled()
            assert not shell.cleanup_pending and shell._controller.state is None
            assert len(sends) == len(detached) == 1 and closed == [True]
            await shell.close()
            assert len(detached) == 1
        finally:
            release.set()
            if not poll.done():
                poll.cancel()
            await remote.close()
            await asyncio.gather(poll, *([settlement] if settlement else []), return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["service", "io"])
def test_G17_SETTLEMENT_unknown_detach_failure_remains_debt(kind):
    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

    async def scenario():
        client = _Client()

        async def detach(request):
            if kind == "service":
                raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
            raise OSError("unknown detach outcome")

        client.detach_mux = detach
        shell = _shell(client)
        await shell.start()
        with pytest.raises(AppServiceError if kind == "service" else OSError):
            await shell.close()
        assert shell.cleanup_pending and shell._controller.state is not None

    asyncio.run(scenario())


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


@pytest.mark.parametrize("expired", [False, True])
def test_G17_STARTUP_shared_deadline_bounds_attach_before_terminal_takeover(expired):
    async def scenario():
        client = _Client()
        events = []
        release = asyncio.Event()
        original_attach = client.attach_mux

        async def attach(request):
            events.append("attach")
            await release.wait()
            return await original_attach(request)

        client.attach_mux = attach
        shell = _shell(client)

        async def settlement():
            events.append("settlement")
            release.set()  # Stand-in for the outer owner's connection reclamation.
            await shell.close()

        class Mode:
            def __enter__(self):
                events.append("terminal.enter")

            def __exit__(self, *args):
                events.append("terminal.restore")

        stdin, stdout = StringIO(), StringIO()
        with pytest.raises(TimeoutError):
            await run_hosted_mux_shell(
                shell,
                stdin=stdin,
                stdout=stdout,
                session=TerminalSession(stdin, stdout, mode_factory=lambda *args: Mode()),
                settlement=settlement,
                startup_deadline=asyncio.get_running_loop().time() + (-1 if expired else 0.02),
            )
        assert "terminal.enter" not in events and "settlement" in events
        assert ("attach" in events) is not expired
        assert not shell.cleanup_pending

    asyncio.run(scenario())


def test_G17_STARTUP_deadline_does_not_limit_ready_terminal_interaction():
    async def scenario():
        shell = _shell(_Client())
        stdin, stdout = StringIO(), StringIO()
        deadline = asyncio.get_running_loop().time() + 0.05

        async def later_eof(stream):
            await asyncio.sleep(0.08)
            assert asyncio.get_running_loop().time() > deadline
            return ""

        assert await run_hosted_mux_shell(
            shell, stdin=stdin, stdout=stdout, input_chunk_reader=later_eof,
            terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=24)),
            session=TerminalSession(stdin, stdout), startup_deadline=deadline,
        ) == 0
        assert not shell.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("foreground", [False, True])
def test_G17_EXIT_copy_matches_the_selected_application_lifetime(foreground):
    from loushang.appserver.protocol import MuxSelectorV1, SessionScopeV1
    from loushang.harnesstui.mux.shell import HostedMuxShellV1
    from loushang.tui.core import RenderConstraints
    from loushang.tui.input import InputEvent

    async def scenario():
        client = _Client()
        shell = HostedMuxShellV1(
            client, selector=MuxSelectorV1(name="dev"), product_id="coding",
            scopes=((SessionScopeV1.CWD, "d" * 64),),
            exit_ends_application=foreground,
        )
        await shell.start()
        rendered = shell.screen.render(RenderConstraints(width=100, max_height=24))
        assert ("/exit ends app" in "\n".join(line.text for line in rendered.lines)) is foreground
        shell.screen.show_help()
        text = shell.screen._detail.text
        assert ("ends this application" in text) is foreground
        assert ("accepted work continues" in text) is not foreground
        assert ("no background management endpoint" in text) is foreground
        assert ("create/list/attach/close/stop" in text) is not foreground
        shell.handle(InputEvent(kind="key", key="escape"))
        shell.handle(InputEvent(kind="text", text="/exit"))
        shell.handle(InputEvent(kind="key", key="enter"))
        assert shell.exit_requested
        await shell.close()
        assert [name for name, _ in client.calls].count("detach") == 1

    asyncio.run(scenario())
