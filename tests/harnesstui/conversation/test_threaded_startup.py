"""Terminal lease and Product context stay on main across loading handoff."""

import asyncio
import os
import sys
import time
from contextlib import contextmanager
from threading import Event, get_ident

import pytest

from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
from loushang.harnesstui.conversation.startup_host import (
    ScreenConversationStartup,
    startup_failure_summary,
)
from loushang.harnesstui.conversation.threaded_startup import ThreadedScreenStartup
from loushang.tui.terminal import TerminalSize
from tests.harnesstui.conversation.test_loading_surface import Output, Screen

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux loading owner")


def test_repeated_cancel_joins_live_worker_and_product_before_restore():
    read_fd, write_fd = os.pipe()
    block_worker, worker_blocked, release_worker = Event(), Event(), Event()
    events = []

    def size():
        if block_worker.is_set():
            worker_blocked.set()
            if not release_worker.wait(5):
                raise RuntimeError("test failed to release loading owner")
        return TerminalSize(columns=100, rows=30)

    @contextmanager
    def mode(*args):
        events.append("enter")
        try:
            yield None
        finally:
            assert coordinator._joined
            events.append("restore")

    async def scenario():
        prepared, cleaning, release_cleanup = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def prepare():
            prepared.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("cleanup-start")
                cleaning.set()
                await release_cleanup.wait()
                events.append("cleanup-done")

        nonlocal coordinator
        startup = ScreenConversationStartup(Screen(None, "/test", None, None), prepare)
        coordinator = ThreadedScreenStartup(startup)
        task = asyncio.create_task(
            coordinator.run(
                stdin=stdin,
                stdout=Output(),
                terminal_mode_factory=mode,
                terminal_size_provider=size,
            )
        )
        try:
            await asyncio.wait_for(prepared.wait(), 3)
            block_worker.set()

            async def wait_blocked():
                while not worker_blocked.is_set():
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(wait_blocked(), 3)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0.02)
                assert not task.done() and "restore" not in events
            release_worker.set()
            await asyncio.wait_for(cleaning.wait(), 3)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0.01)
                assert not task.done() and "restore" not in events
            release_cleanup.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert not startup.attached
            assert events == ["enter", "cleanup-start", "cleanup-done", "restore"]
        finally:
            release_worker.set()
            release_cleanup.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    coordinator = None
    try:
        with os.fdopen(read_fd) as stdin:
            asyncio.run(scenario())
    finally:
        release_worker.set()
        os.close(write_fd)


def test_sync_preparation_echo_handoff_and_cleanup_share_one_terminal_lease(
    monkeypatch,
):
    def forbidden_executor(*args, **kwargs):
        raise RuntimeError("executor submission unavailable")

    monkeypatch.setattr(asyncio, "to_thread", forbidden_executor)
    read_fd, write_fd = os.pipe()
    events, submissions = [], []
    output = Output()
    main_thread = get_ident()
    sizes = [TerminalSize(columns=100, rows=30)]
    resized = Event()

    class ResizingScreen(Screen):
        def render(self, constraints):
            result = super().render(constraints)
            if constraints.width == 111 and get_ident() != main_thread:
                resized.set()
            return result

    screen = ResizingScreen(None, "/test", None, None)

    @contextmanager
    def mode(_stdin, _stdout):
        assert get_ident() == main_thread
        events.append("enter")
        try:
            yield None
        finally:
            events.append("restore")

    class Host:
        async def submit(self, action):
            assert get_ident() == main_thread
            submissions.append(action.text)
            return 0

        async def steer(self, action):
            pass

        follow_up = abort = steer

    async def prepare():
        assert get_ident() == main_thread
        assert "Loading session" in output.getvalue()
        try:
            os.write(write_fd, b"draft")
            deadline = time.monotonic() + 3
            while "draft" not in output.getvalue() and time.monotonic() < deadline:
                sum(i * i for i in range(300))
            assert "draft" in output.getvalue(), (
                "loading owner must progress during sync work"
            )
            sizes[0] = TerminalSize(columns=111, rows=33)
            deadline = time.monotonic() + 3
            while not resized.is_set() and time.monotonic() < deadline:
                sum(i * i for i in range(300))
            assert resized.is_set(), "loading worker must render the new geometry"
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
    coordinator = ThreadedScreenStartup(startup)

    async def scenario():
        async def drive():
            while not (startup.attached and startup.submission_armed):
                await asyncio.sleep(0.001)
            assert (startup.router.ready.width, startup.router.ready.height) == (
                111,
                33,
            )
            assert screen.composer.value == "draft"
            os.write(write_fd, b"\r")
            while not submissions:
                await asyncio.sleep(0.001)
            os.write(write_fd, b"\x04")

        driver = asyncio.create_task(drive())
        try:
            result = await asyncio.wait_for(
                coordinator.run(
                    stdin=stdin,
                    stdout=output,
                    terminal_mode_factory=mode,
                    terminal_size_provider=lambda: sizes[0],
                ),
                5,
            )
            await driver
            return result
        finally:
            if not driver.done():
                driver.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await driver

    try:
        with os.fdopen(read_fd) as stdin:
            assert asyncio.run(scenario()) == 0
        assert submissions == ["draft"]
        assert events == ["enter", "bind", "cleanup", "restore"]
    finally:
        os.close(write_fd)


@pytest.mark.parametrize("phase,expected", [("quit", 130), ("error", 1), ("done", 0)])
def test_loading_terminal_is_retained_until_preparation_settles(phase, expected):
    read_fd, write_fd = os.pipe()
    output = Output()
    screen = Screen(None, "/test", None, None)
    events = []

    @contextmanager
    def mode(*args):
        events.append("enter")
        try:
            yield None
        finally:
            assert "cleanup" in events
            events.append("restore")

    async def prepare():
        try:
            if phase == "quit":
                os.write(write_fd, b"\x03")
                await asyncio.Event().wait()
            if phase == "error":
                raise ValueError("preparation exploded")
            return 0
        finally:
            await asyncio.sleep(0)
            events.append("cleanup")

    startup = ScreenConversationStartup(screen, prepare)
    coordinator = ThreadedScreenStartup(startup)

    async def scenario():
        async def drive():
            if phase == "error":
                while not startup._observed:
                    await asyncio.sleep(0.001)
                assert "Session unavailable" in screen.state.status_message
                os.write(write_fd, b"\x04")

        driver = asyncio.create_task(drive())
        try:
            result = await asyncio.wait_for(
                coordinator.run(
                    stdin=stdin,
                    stdout=output,
                    terminal_mode_factory=mode,
                    terminal_size_provider=lambda: TerminalSize(columns=100, rows=30),
                ),
                5,
            )
            await driver
            return result
        finally:
            if not driver.done():
                driver.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await driver

    try:
        with os.fdopen(read_fd) as stdin:
            assert asyncio.run(scenario()) == expected
        assert events == ["enter", "cleanup", "restore"]
        assert coordinator._joined
    finally:
        os.close(write_fd)


def test_worker_timeout_error_is_failure_not_an_endless_join_retry():
    read_fd, write_fd = os.pipe()
    events = []
    startup = ScreenConversationStartup(Screen(None, "/test", None, None), lambda: None)
    coordinator = ThreadedScreenStartup(startup)

    @contextmanager
    def mode(*args):
        try:
            yield None
        finally:
            events.append("restore")

    error = TimeoutError("worker failed independently of join")

    def size():
        raise error

    try:
        with os.fdopen(read_fd) as stdin:
            with pytest.raises(TimeoutError) as caught:
                asyncio.run(
                    coordinator.run(
                        stdin=stdin,
                        stdout=Output(),
                        terminal_mode_factory=mode,
                        terminal_size_provider=size,
                    )
                )
        assert caught.value is error
        assert coordinator._joined and startup.task is None
        assert events == ["restore"]
    finally:
        os.close(write_fd)


def test_worker_and_product_cleanup_failures_are_both_visible():
    from threading import Event

    read_fd, write_fd = os.pipe()
    fail_worker = Event()
    restored = []

    @contextmanager
    def mode(*args):
        try:
            yield None
        finally:
            assert coordinator._joined
            restored.append(True)

    def size():
        if fail_worker.is_set():
            raise ValueError("worker render failed")
        return TerminalSize(columns=100, rows=30)

    async def prepare():
        fail_worker.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("Product cleanup failed")

    startup = ScreenConversationStartup(Screen(None, "/test", None, None), prepare)
    coordinator = ThreadedScreenStartup(startup)
    try:
        with os.fdopen(read_fd) as stdin:
            with pytest.raises(BaseExceptionGroup) as caught:
                asyncio.run(
                    asyncio.wait_for(
                        coordinator.run(
                            stdin=stdin,
                            stdout=Output(),
                            terminal_mode_factory=mode,
                            terminal_size_provider=size,
                        ),
                        5,
                    )
                )
        summary = startup_failure_summary(caught.value)
        assert "worker render failed" in summary
        assert "Product cleanup failed" in summary
        assert restored == [True]
    finally:
        os.close(write_fd)
