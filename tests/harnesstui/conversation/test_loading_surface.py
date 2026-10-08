"""Real joined loading-screen ownership, independent of the main event loop."""

import asyncio
import os
import sys
import time
from contextlib import contextmanager
from io import StringIO
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
from loushang.harnesstui.conversation.loading_input import LoadingInputRouter
from loushang.harnesstui.conversation.loading_surface import LoadingSurfaceWorker
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.harnesstui.conversation.screen_runner import (
    ConversationScreenContinuation,
    run_conversation_screen,
)
from loushang.harnesstui.conversation.startup_host import ScreenConversationStartup
from loushang.tui.core import RenderResult
from loushang.tui.terminal import TerminalSize
from loushang.tui.terminal_backends.posix import PosixTerminalInputReader

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux loading worker")


class Screen(ScreenConversationApp):
    def _create_frame_presentation(self):
        return ScreenFramePresentation(
            ScreenFrameCopy("Working", "Steer", "", "Queue", "")
        )

    def startup_welcome_panel(self):
        return SimpleNamespace(render=lambda constraints: RenderResult(lines=()))


class Output(StringIO):
    def __init__(self):
        super().__init__()
        self.lock = Lock()

    def write(self, value):
        with self.lock:
            return super().write(value)

    def getvalue(self):
        with self.lock:
            return super().getvalue()


@contextmanager
def running_surface():
    app = Screen(None, "/test", None, None)
    read_fd, write_fd = os.pipe()
    output = Output()
    reader = PosixTerminalInputReader(read_fd)
    worker = LoadingSurfaceWorker(
        app=app,
        byte_reader=reader,
        stdout=output,
        terminal_context=None,
        size_provider=lambda: TerminalSize(columns=100, rows=30),
    )
    worker.start()
    try:
        worker.wait_first_frame(10)
        yield worker, reader, write_fd, output
    finally:
        worker.request_transfer()
        try:
            worker.join(5)
        finally:
            os.close(write_fd)
            os.close(read_fd)


def test_real_screen_echoes_while_main_thread_runs_synchronous_python():
    with running_surface() as (worker, _, write_fd, output):
        os.write(write_fd, b"worker-alive")
        deadline = time.monotonic() + 3
        # Deliberately no await/sleep: a main-loop coroutine cannot render here.
        while "worker-alive" not in output.getvalue() and time.monotonic() < deadline:
            sum(index * index for index in range(300))
        assert "worker-alive" in output.getvalue()
        worker.request_transfer()
        state = worker.join(5)
        assert state.app.composer.value == "worker-alive"
        assert state.app.render_requester is None
        assert state.submission_backlog_pending
        assert "\x1b[?1049l" not in output.getvalue()


def test_idle_escape_clears_visible_draft_without_another_input():
    with running_surface() as (worker, _, write_fd, output):
        os.write(write_fd, b"abc")
        deadline = time.monotonic() + 3
        while "abc" not in output.getvalue() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert "abc" in output.getvalue()
        before = output.getvalue().count("\x1b[?2026l")
        os.write(write_fd, b"\x1b")
        deadline = time.monotonic() + 3
        while (
            output.getvalue().count("\x1b[?2026l") == before
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert output.getvalue().count("\x1b[?2026l") > before
        worker.request_transfer()
        state = worker.join(5)
        assert state.app.composer.value == ""


def test_half_utf8_survives_actual_worker_join(monkeypatch):
    with running_surface() as (worker, reader, write_fd, _):
        consumed = Event()
        original_read = os.read

        def observe(fd, count):
            value = original_read(fd, count)
            if fd == reader.fd and value == b"\xe4":
                consumed.set()
            return value

        monkeypatch.setattr(os, "read", observe)
        os.write(write_fd, b"\xe4")
        assert consumed.wait(3)
        worker.request_transfer()
        state = worker.join(5)
        os.write(write_fd, b"\xbd\xa0")
        assert asyncio.run(state.byte_reader.read_chunk()) == "你"


def test_paste_parser_and_completed_read_survive_transfer(monkeypatch):
    with running_surface() as (worker, reader, write_fd, _):
        consumed = Event()
        original_read = os.read

        def observe(fd, count):
            value = original_read(fd, count)
            if fd == reader.fd and value.endswith(b"z"):
                consumed.set()
            return value

        monkeypatch.setattr(os, "read", observe)
        os.write(write_fd, b"\x1b[200~abz")
        assert consumed.wait(3)
        worker.request_transfer()
        state = worker.join(5)
        assert state.parser.has_pending
        events = state.parser.feed("\x1b[201~")
        assert len(events) == 1
        assert events[0].kind == "paste" and events[0].text == "abz"
        assert state.pending_idle_deadline is not None


@pytest.mark.parametrize(
    "payload,closing,text", [(b"abc\r\x16\tz", None, "abcz"), (b"\x03", 130, "")]
)
def test_loading_submission_gate_and_quit_win_transfer_race(
    monkeypatch, payload, closing, text
):
    with running_surface() as (worker, reader, write_fd, _):
        consumed = Event()
        original_read = os.read

        def observe(fd, count):
            value = original_read(fd, count)
            if fd == reader.fd and value.endswith(payload[-1:]):
                consumed.set()
            return value

        def forbidden_clipboard(*args, **kwargs):
            raise AssertionError("loading must not acquire clipboard images")

        monkeypatch.setattr(os, "read", observe)
        monkeypatch.setattr(
            "loushang.harnesstui.conversation.input.read_clipboard_image",
            forbidden_clipboard,
        )
        os.write(write_fd, payload)
        assert consumed.wait(3)
        worker.request_transfer()
        state = worker.join(5)
        assert worker.closing_code == closing
        assert state.app.composer.value == text
        if closing is not None:
            assert "Closing" in state.app.state.status_message


@pytest.mark.parametrize(
    "prefix,tail,expected",
    [(b"\xe4", b"\xbd\xa0", "你"), (b"\x1b[200~abc", b"\x1b[201~", "abc")],
)
def test_main_runner_continues_joined_input_and_render_state(
    monkeypatch, prefix, tail, expected
):
    with running_surface() as (worker, reader, write_fd, output):
        consumed = Event()
        original_read = os.read

        def observe(fd, count):
            value = original_read(fd, count)
            if fd == reader.fd and value == prefix:
                consumed.set()
            return value

        monkeypatch.setattr(os, "read", observe)
        os.write(write_fd, prefix)
        assert consumed.wait(3)
        worker.request_transfer()
        state = worker.join(5)

        def forbidden(*args, **kwargs):
            raise AssertionError("continuation must not reacquire or reset the screen")

        module = "loushang.harnesstui.conversation.screen_runner"
        for name in (
            "TerminalSession",
            "TuiRuntime",
            "write_startup_welcome",
            "configure_runtime_for_terminal_context",
        ):
            monkeypatch.setattr(f"{module}.{name}", forbidden)

        async def read(_stdin):
            return await state.byte_reader.read_chunk()

        continuation = ConversationScreenContinuation(
            app=state.app,
            parser=state.parser,
            runtime=state.runtime,
            terminal_context=state.terminal_context,
            input_chunk_reader=read,
            pending_idle_deadline=state.pending_idle_deadline,
        )
        os.write(write_fd, tail + b"\r\x04")
        result = asyncio.run(
            run_conversation_screen(
                app=state.app,
                stdin=StringIO(),
                stdout=output,
                handle_prompt=forbidden,
                on_abort=forbidden,
                should_exit=lambda _: False,
                interruption_message="Interrupted",
                cancellation_message="Cancelled",
                terminal_size_provider=lambda: TerminalSize(columns=100, rows=30),
                input_router_factory=LoadingInputRouter,
                continuation=continuation,
            )
        )
        assert result == 0
        assert state.app.composer.value == expected
        with pytest.raises(RuntimeError, match="already consumed"):
            continuation.claim(state.app)


def test_continuation_does_not_restart_expired_parser_idle_deadline(monkeypatch):
    with running_surface() as (worker, _, _, output):
        worker.request_transfer()
        state = worker.join(5)
        state.parser.feed("\x1b")
        observed = []

        async def read(_stdin):
            raise AssertionError("test controls runner wait")

        async def tick(_stdin, **kwargs):
            observed.append(kwargs["pending_input_idle_ms"])
            return None if len(observed) == 1 else "\x04"

        monkeypatch.setattr(
            "loushang.harnesstui.conversation.screen_runner.read_input_chunk_or_render_tick",
            tick,
        )
        continuation = ConversationScreenContinuation(
            app=state.app,
            parser=state.parser,
            runtime=state.runtime,
            terminal_context=state.terminal_context,
            input_chunk_reader=read,
            pending_idle_deadline=time.monotonic() - 1,
        )
        asyncio.run(
            run_conversation_screen(
                app=state.app,
                stdin=StringIO(),
                stdout=output,
                handle_prompt=lambda _: None,
                on_abort=lambda: None,
                should_exit=lambda _: False,
                interruption_message="Interrupted",
                cancellation_message="Cancelled",
                input_router_factory=LoadingInputRouter,
                continuation=continuation,
            )
        )
        assert observed == [0, None]


@pytest.mark.parametrize("failure_phase", ["size", "promotion"])
def test_continuation_initialization_failure_settles_owned_resources(
    monkeypatch, failure_phase
):
    with running_surface() as (worker, _, _, output):
        worker.request_transfer()
        state = worker.join(5)
        previous_surface = state.app.surface_host
        events = []
        error = RuntimeError("injected initialization failure")

        class Router(LoadingInputRouter):
            def dispose(self):
                events.append("dispose")
                super().dispose()

        class Lifecycle:
            def start(self, _wake):
                raise AssertionError("initialization failed before start")

            async def settle(self, code, active_task, dispose):
                assert code == 1 and active_task is None
                events.append("settle")
                dispose()

        def fail(*args):
            raise error

        async def read(_stdin):
            raise AssertionError("initialization failed before input")

        if failure_phase == "promotion":
            monkeypatch.setattr(
                "loushang.harnesstui.conversation.screen_runner.promote_pending_page_surface",
                fail,
            )
        continuation = ConversationScreenContinuation(
            state.app, state.parser, state.runtime, state.terminal_context, read
        )
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(
                run_conversation_screen(
                    app=state.app,
                    stdin=StringIO(),
                    stdout=output,
                    handle_prompt=lambda _: None,
                    on_abort=lambda: None,
                    should_exit=lambda _: False,
                    interruption_message="Interrupted",
                    cancellation_message="Cancelled",
                    terminal_size_provider=(
                        fail
                        if failure_phase == "size"
                        else lambda: TerminalSize(columns=100, rows=30)
                    ),
                    input_router_factory=Router,
                    lifecycle=Lifecycle(),
                    continuation=continuation,
                )
            )
        assert caught.value is error
        assert events == (
            ["settle"] if failure_phase == "size" else ["settle", "dispose"]
        )
        assert state.app.surface_host is previous_surface
        assert state.app.render_requester is None
        with pytest.raises(RuntimeError, match="already consumed"):
            continuation.claim(state.app)


@pytest.mark.parametrize("has_backlog", [False, True])
def test_joined_backlog_enter_is_gated_before_new_ready_submission(has_backlog):
    with running_surface() as (worker, _, write_fd, output):
        worker.request_transfer()
        state = worker.join(5)
        submissions = []
        read_started = asyncio.Event()

        class Host:
            async def submit(self, action):
                assert startup.submission_armed
                submissions.append(action.text)
                return 7

            async def steer(self, action):
                pass

            follow_up = abort = steer

        async def read(_stdin):
            read_started.set()
            return await state.byte_reader.read_chunk()

        async def prepare():
            await read_started.wait()
            return await startup.attach(
                app=state.app,
                stdin=StringIO(),
                stdout=output,
                action_host=Host(),
                profile=ConversationScreenRunProfile(None, "Interrupted", "Cancelled"),
                should_exit=lambda _: False,
            )

        startup = ScreenConversationStartup(state.app, prepare)
        startup.defer_submission_until_input_boundary(
            state.byte_reader.at_input_boundary
        )
        continuation = ConversationScreenContinuation(
            state.app,
            state.parser,
            state.runtime,
            state.terminal_context,
            read,
            pending_idle_deadline=state.pending_idle_deadline,
            before_input_read=startup.before_input_read,
        )
        if has_backlog:
            os.write(write_fd, b"draft\r")

        async def scenario():
            async def drive():
                while not startup.submission_armed:
                    await asyncio.sleep(0)
                assert submissions == []
                assert state.app.composer.value == ("draft" if has_backlog else "")
                os.write(write_fd, b"\r" if has_backlog else b"draft\r")

            driver = asyncio.create_task(drive())
            try:
                result = await asyncio.wait_for(
                    startup.run(
                        stdin=StringIO(),
                        stdout=output,
                        continuation=continuation,
                        terminal_size_provider=lambda: TerminalSize(
                            columns=100, rows=30
                        ),
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

        assert asyncio.run(scenario()) == 7
        assert submissions == ["draft"]
