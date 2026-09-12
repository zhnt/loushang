from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from io import StringIO
from types import SimpleNamespace

import pytest

from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
from loushang.harnesstui.conversation.input import (
    ConversationInputHandled,
    ConversationInputRouter,
    ConversationPromptResult,
)
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.harnesstui.conversation.startup_host import ScreenConversationStartup
from loushang.tui.core import RenderLine, RenderResult
from loushang.tui.input import InputEvent
from loushang.tui.terminal import TerminalSize


def test_attached_product_keeps_loading_gate_until_complete_input_boundary():
    async def scenario():
        screen = app()
        product_context = ContextVar("resize_product", default="outside")

        class Router(ConversationInputRouter):
            def handle(self, event):
                if event.kind == "resize":
                    assert product_context.get() == "product"
                return super().handle(event)

        async def prepare():
            return 0

        class Host:
            async def submit(self, action):
                raise AssertionError("router result must not execute a Product action")

            steer = follow_up = abort = submit

        startup = ScreenConversationStartup(screen, prepare)
        boundary_calls = []
        empty = False

        def boundary():
            boundary_calls.append(empty)
            return empty

        startup.defer_submission_until_input_boundary(boundary)
        router = startup.build_router(
            app=screen,
            should_exit=lambda _: False,
            is_local_command=lambda _: False,
            width=80,
            height=24,
        )
        token = product_context.set("product")
        attach = asyncio.create_task(
            startup.attach(
                app=screen,
                stdin=StringIO(),
                stdout=StringIO(),
                action_host=Host(),
                profile=ConversationScreenRunProfile(
                    Router, "Interrupted", "Cancelled"
                ),
                should_exit=lambda _: False,
            )
        )
        product_context.reset(token)
        try:
            await asyncio.sleep(0)
            assert startup.attached and not startup.submission_armed
            assert screen.state.startup_pending
            router.handle(InputEvent(kind="paste", text="draft"))
            router.handle(InputEvent(kind="resize", columns=111, rows=33))
            assert (router.ready.width, router.ready.height) == (111, 33)
            assert not startup.submission_armed
            startup.before_input_read(False)
            assert boundary_calls == [False]
            assert isinstance(
                router.handle(InputEvent(kind="key", key="enter")),
                ConversationInputHandled,
            )
            assert screen.composer.value == "draft"
            empty = True
            startup.before_input_read(True)
            assert boundary_calls == [False], "pending parser blocks admission"
            startup.before_input_read(False)
            assert startup.submission_armed and not screen.state.startup_pending
            result = router.handle(InputEvent(kind="key", key="enter"))
            assert isinstance(result, ConversationPromptResult)
            assert result.text == "draft"
        finally:
            await startup.settle(0, None, router.dispose)
            assert await attach == 0

    asyncio.run(scenario())


class App(ScreenConversationApp):
    def _create_frame_presentation(self):
        return ScreenFramePresentation(
            ScreenFrameCopy("Working", "Steer", "", "Queue", "")
        )

    def startup_welcome_panel(self):
        return SimpleNamespace(render=lambda _constraints: RenderResult(lines=()))

    def render(self, _constraints):
        self.frames.append((self.state.status_message, self.composer.value))
        if self.changed is not None:
            self.changed.set()
        return RenderResult(
            lines=(
                RenderLine(self.state.status_message or "Ready"),
                RenderLine(self.composer.value),
            )
        )


def app():
    result = App(model_label=None, cwd="/repo", branch=None, session_label=None)
    result.frames = []
    result.changed = None
    return result


def options(events, queue):
    @contextmanager
    def terminal(_stdin, _stdout):
        events.append("terminal.enter")
        try:
            yield object()
        finally:
            events.append("terminal.exit")

    async def read(_stdin):
        return await queue.get()

    return dict(
        stdin=StringIO(),
        stdout=StringIO(),
        terminal_mode_factory=terminal,
        terminal_size_provider=lambda: TerminalSize(columns=80, rows=24),
        input_chunk_reader=read,
    )


async def frame_matching(screen, predicate):
    while not predicate():
        screen.changed.clear()
        await screen.changed.wait()


def test_first_frame_editing_gate_same_composer_and_context_attachment():
    async def scenario():
        events, submissions = [], []
        screen = app()
        screen.changed = asyncio.Event()
        composer = screen.composer
        queue = asyncio.Queue()
        allow_attach, started, attached = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        context = ContextVar("test_startup_context", default="outer")

        class Host:
            async def submit(self, action):
                submissions.append((action.text, context.get()))
                return 7

            async def steer(self, _action):
                pass

            async def follow_up(self, _action):
                pass

            async def abort(self):
                pass

        class Router(ConversationInputRouter):
            def __post_init__(self):
                super().__post_init__()
                asyncio.get_running_loop().call_soon(attached.set)

            def handle(self, event):
                assert context.get() == "prepared"
                return super().handle(event)

            def dispose(self):
                assert context.get() == "prepared"
                events.append("router.dispose")
                super().dispose()

        async def prepare():
            assert screen.frames, "runtime preparation must follow an actual frame"
            started.set()
            await allow_attach.wait()
            token = context.set("prepared")
            try:
                return await startup.attach(
                    app=screen,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    action_host=Host(),
                    profile=ConversationScreenRunProfile(
                        Router, "interrupted", "cancelled"
                    ),
                    should_exit=lambda text: text == "/quit",
                    keybindings={"tui.input.submit": ("ctrl+y",)},
                )
            finally:
                assert context.get() == "prepared"
                events.append("prepared.cleanup")
                context.reset(token)

        startup = ScreenConversationStartup(screen, prepare)

        async def drive():
            await started.wait()
            queue.put_nowait("hello")
            await frame_matching(
                screen, lambda: any(v == "hello" for _, v in screen.frames)
            )
            queue.put_nowait("\r\x16")  # Enter and image paste must not consume draft.
            queue.put_nowait("\x1b[200~ world\x1b[201~")
            await frame_matching(screen, lambda: screen.composer.value == "hello world")
            assert submissions == [] and not screen.state.running
            allow_attach.set()
            await attached.wait()
            assert screen.composer is composer and composer.value == "hello world"
            queue.put_nowait("\x19")

        driver = asyncio.create_task(drive())
        result = await startup.run(**options(events, queue))
        await driver
        assert result == 7
        assert submissions == [("hello world", "prepared")]
        assert events == [
            "terminal.enter",
            "router.dispose",
            "prepared.cleanup",
            "terminal.exit",
        ]
        assert context.get() == "outer"
        assert startup.task.done()

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("exit_input,expected", [("", 0), ("\x03", 130)])
def test_loading_exit_cancels_and_joins_before_terminal_restore(exit_input, expected):
    async def scenario():
        events, queue = [], asyncio.Queue()
        screen = app()

        async def prepare():
            assert screen.frames
            queue.put_nowait(exit_input)
            try:
                await asyncio.Event().wait()
            finally:
                events.append("cleanup")

        startup = ScreenConversationStartup(screen, prepare)
        assert await startup.run(**options(events, queue)) == expected
        assert events == ["terminal.enter", "cleanup", "terminal.exit"]
        assert startup.task.done()

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("failure", [9, RuntimeError("broken session")])
def test_failure_renders_without_input_and_keeps_original_exit_code(failure):
    async def scenario():
        events, queue = [], asyncio.Queue()
        screen = app()
        screen.changed = asyncio.Event()

        async def prepare():
            if isinstance(failure, Exception):
                raise failure
            return failure

        startup = ScreenConversationStartup(screen, prepare)

        async def drive():
            await frame_matching(
                screen,
                lambda: any(
                    text and "unavailable" in text for text, _ in screen.frames
                ),
            )
            queue.put_nowait("\x04")

        driver = asyncio.create_task(drive())
        assert await startup.run(**options(events, queue)) == (
            1 if isinstance(failure, Exception) else failure
        )
        await driver
        assert events[-1] == "terminal.exit"

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_repeated_external_cancellation_does_not_interrupt_cleanup():
    async def scenario():
        events, queue = [], asyncio.Queue()
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def prepare():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                startup.begin_cleanup()
                cleaning.set()
                await release.wait()
                events.append("cleanup")

        startup = ScreenConversationStartup(app(), prepare)
        runner = asyncio.create_task(startup.run(**options(events, queue)))
        await started.wait()
        runner.cancel()
        await cleaning.wait()
        runner.cancel()
        await asyncio.sleep(0)
        assert "terminal.exit" not in events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert events == ["terminal.enter", "cleanup", "terminal.exit"]
        assert startup.task.done()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_cleanup_fault_does_not_skip_continuation_or_terminal_release():
    async def scenario():
        events, queue = [], asyncio.Queue()

        class Router(ConversationInputRouter):
            def __post_init__(self):
                super().__post_init__()
                queue.put_nowait("/quit\r")

            def dispose(self):
                events.append("router.dispose")
                raise RuntimeError("router cleanup failed")

        host = SimpleNamespace(
            submit=lambda _action: None,
            steer=lambda _action: None,
            follow_up=lambda _action: None,
            abort=lambda: None,
        )

        async def prepare():
            try:
                return await startup.attach(
                    app=startup.app,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    action_host=host,
                    profile=ConversationScreenRunProfile(
                        Router, "interrupted", "cancelled"
                    ),
                    should_exit=lambda text: text == "/quit",
                )
            finally:
                events.append("cleanup")

        startup = ScreenConversationStartup(app(), prepare)
        with pytest.raises(BaseExceptionGroup, match="settlement failed"):
            await startup.run(**options(events, queue))
        assert events == [
            "terminal.enter",
            "router.dispose",
            "cleanup",
            "terminal.exit",
        ]
        assert startup.task.done()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_loading_multiline_resize_and_split_paste_survive_attach():
    async def scenario():
        events, queue = [], asyncio.Queue()
        screen = app()
        screen.changed = asyncio.Event()
        allow, attached, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        sizes = []

        class Router(ConversationInputRouter):
            def __post_init__(self):
                super().__post_init__()
                sizes.append((self.width, self.height))
                asyncio.get_running_loop().call_soon(attached.set)

        host = SimpleNamespace(
            submit=lambda _action: 0,
            steer=lambda _action: None,
            follow_up=lambda _action: None,
            abort=lambda: None,
        )

        async def prepare():
            started.set()
            await allow.wait()
            return await startup.attach(
                app=screen,
                stdin=StringIO(),
                stdout=StringIO(),
                action_host=host,
                profile=ConversationScreenRunProfile(
                    Router, "interrupted", "cancelled"
                ),
                should_exit=lambda text: text == "/quit",
            )

        startup = ScreenConversationStartup(screen, prepare)

        async def drive():
            await started.wait()
            queue.put_nowait("first\x1b\rsecond")  # alt-enter remains a local newline.
            await frame_matching(
                screen, lambda: screen.composer.value == "first\nsecond"
            )
            startup.router.handle(InputEvent(kind="resize", columns=111, rows=33))
            # Keep the terminal parser's bracketed paste open over attachment.
            queue.put_nowait("\x1b[200~ pasted")
            allow.set()
            await attached.wait()
            queue.put_nowait(" tail\x1b[201~")
            await frame_matching(
                screen, lambda: screen.composer.value == "first\nsecond pasted tail"
            )

        driver = asyncio.create_task(drive())

        # Exit via EOF after verifying the unchanged draft; no backend submission.
        async def close_after_drive():
            await driver
            queue.put_nowait("")

        closer = asyncio.create_task(close_after_drive())
        await startup.run(**options(events, queue))
        await closer
        assert sizes == [(111, 33)]
        assert screen.composer.value == "first\nsecond pasted tail"
        assert events.count("terminal.enter") == events.count("terminal.exit") == 1

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_all_attached_callbacks_keep_context_and_late_attach_is_rejected():
    async def scenario():
        marker = ContextVar("callback_context", default="outer")
        screen = app()
        attached = asyncio.Event()
        seen = []

        async def callback(*_args, **_kwargs):
            seen.append(marker.get())

        class Router(ConversationInputRouter):
            def __post_init__(self):
                super().__post_init__()
                asyncio.get_running_loop().call_soon(attached.set)

        host = SimpleNamespace(
            submit=callback, steer=callback, follow_up=callback, abort=callback
        )
        kwargs = dict(
            app=screen,
            stdin=StringIO(),
            stdout=StringIO(),
            action_host=host,
            profile=ConversationScreenRunProfile(Router, "interrupted", "cancelled"),
            should_exit=lambda _text: False,
            handle_local=callback,
            handle_surface_intent=callback,
        )

        async def prepare():
            token = marker.set("session-and-runtime")
            try:
                return await startup.attach(**kwargs)
            finally:
                seen.append(marker.get())
                marker.reset(token)

        startup = ScreenConversationStartup(screen, prepare)
        router = startup.build_router(
            app=screen,
            should_exit=lambda _text: False,
            is_local_command=lambda _text: False,
            keybindings=None,
            width=80,
            height=24,
        )
        startup.start(lambda: None)
        await attached.wait()
        for name in ("prompt", "local", "steer", "followup", "surface"):
            await startup.handler(name)("text")
        await startup.handler("abort")()
        with pytest.raises(RuntimeError, match="invalid or late"):
            await startup.attach(**kwargs)
        await startup.settle(0, None, router.dispose)
        with pytest.raises(RuntimeError, match="invalid or late"):
            await startup.attach(**kwargs)
        assert seen == ["session-and-runtime"] * 7
        assert marker.get() == "outer"

    asyncio.run(asyncio.wait_for(scenario(), 10))
