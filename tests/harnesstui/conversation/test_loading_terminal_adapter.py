"""The shared startup lifecycle also runs through the Windows console adapter."""

import asyncio
import os
import time
from contextlib import contextmanager
from io import StringIO
from queue import Queue
from threading import get_ident
from types import SimpleNamespace

import pytest

from loushang.harnesstui.conversation import threaded_startup
from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
from loushang.harnesstui.conversation.startup_host import ScreenConversationStartup
from loushang.tui.terminal import TerminalSize
from loushang.tui.terminal_backends.windows import WindowsTerminalInputReader
from tests.harnesstui.conversation.test_loading_surface import Output, Screen


def test_windows_adapter_echoes_during_sync_prepare_then_transfers_once(monkeypatch):
    units = Queue()
    output = Output()
    events, submissions = [], []
    main_thread = get_ident()

    class Console:
        def kbhit(self):
            return not units.empty()

        def getwch(self):
            return units.get_nowait()

        def at_input_boundary(self):
            return units.empty()

    backend = SimpleNamespace(
        open_reader=lambda _: WindowsTerminalInputReader(Console())
    )
    monkeypatch.setattr(
        threaded_startup, "native_terminal_input_backend", lambda _: backend
    )

    def type_text(text):
        for char in text:
            units.put(char)

    @contextmanager
    def mode(*args):
        assert get_ident() == main_thread
        events.append("enter")
        try:
            yield None
        finally:
            assert coordinator._joined
            assert events[-1] == "cleanup"
            events.append("restore")

    class Host:
        async def submit(self, action):
            assert get_ident() == main_thread
            submissions.append(action.text)
            return 0

        async def steer(self, action):
            pass

        follow_up = abort = steer

    screen = Screen(None, "/test", None, None)
    stdin = StringIO()

    async def prepare():
        assert get_ident() == main_thread
        assert "Loading session" in output.getvalue()
        try:
            # The loading Enter must never become a later Product submission.
            type_text("draft\r")
            deadline = time.monotonic() + 3
            while "draft" not in output.getvalue() and time.monotonic() < deadline:
                sum(i * i for i in range(300))
            assert "draft" in output.getvalue(), "echo must progress during sync work"
            await coordinator.before_product_ui()
            assert coordinator._joined
            events.append("bind")
            return await startup.attach(
                app=screen,
                stdin=stdin,
                stdout=output,
                action_host=Host(),
                profile=ConversationScreenRunProfile(None, "Interrupted", "Cancelled"),
                should_exit=lambda _: False,
            )
        finally:
            events.append("cleanup")

    startup = ScreenConversationStartup(screen, prepare)
    coordinator = threaded_startup.ThreadedScreenStartup(startup)

    async def scenario():
        async def drive():
            while not startup.submission_armed:
                await asyncio.sleep(0.001)
            assert screen.composer.value == "draft"
            assert submissions == []
            type_text("\r")
            while not submissions:
                await asyncio.sleep(0.001)
            type_text("\x04")

        driver = asyncio.create_task(drive())
        try:
            assert (
                await coordinator.run(
                    stdin=stdin,
                    stdout=output,
                    terminal_mode_factory=mode,
                    terminal_size_provider=lambda: TerminalSize(columns=100, rows=30),
                )
                == 0
            )
            await driver
        finally:
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert submissions == ["draft"]
    assert events == ["enter", "bind", "cleanup", "restore"]


@pytest.mark.skipif(os.name != "posix", reason="native POSIX PTY")
@pytest.mark.parametrize("quit_during_loading", [False, True])
def test_native_pty_echo_and_mode_restore_during_sync_prepare(quit_during_loading):
    import pty
    import termios

    master, slave = pty.openpty()
    original_attrs = termios.tcgetattr(slave)
    output = Output()
    screen = Screen(None, "/test", None, None)
    cleaned = []

    async def prepare():
        try:
            active_attrs = termios.tcgetattr(slave)
            assert not active_attrs[3] & (termios.ECHO | termios.ICANON | termios.ISIG)
            os.write(master, b"\x03" if quit_during_loading else b"pty-draft\r")
            witness = "Closing" if quit_during_loading else "pty-draft"
            deadline = time.monotonic() + 3
            while witness not in output.getvalue() and time.monotonic() < deadline:
                sum(i * i for i in range(300))
            assert witness in output.getvalue()
            if quit_during_loading:
                await asyncio.Event().wait()
            await coordinator.before_product_ui()
            assert coordinator._joined
            assert screen.composer.value == "pty-draft"
            return 0
        finally:
            cleaned.append(True)

    startup = ScreenConversationStartup(screen, prepare)
    coordinator = threaded_startup.ThreadedScreenStartup(startup)
    try:
        with os.fdopen(slave, encoding="utf-8", closefd=False) as stdin:
            result = asyncio.run(
                asyncio.wait_for(
                    coordinator.run(
                        stdin=stdin,
                        stdout=output,
                        terminal_size_provider=lambda: TerminalSize(
                            columns=100, rows=30
                        ),
                    ),
                    5,
                )
            )
        assert result == (130 if quit_during_loading else 0)
        assert cleaned == [True]
        assert coordinator._joined
        assert termios.tcgetattr(slave) == original_attrs
    finally:
        os.close(master)
        os.close(slave)
