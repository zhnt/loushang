from __future__ import annotations

import asyncio
from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace


def test_prompt_handler_forwards_neutral_attachments() -> None:
    from loushang.harnesstui.conversation.screen_runner import run_prompt_handler

    seen: dict[str, object] = {}
    attachments = (object(),)

    async def handle_prompt(
        text: str,
        *,
        attachments: tuple[object, ...] | None = None,
    ) -> int:
        seen["text"] = text
        seen["attachments"] = attachments
        return 4

    result = asyncio.run(
        run_prompt_handler(
            handle_prompt,
            "describe",
            attachments=attachments,
        )
    )

    assert result == 4
    assert seen == {"text": "describe", "attachments": attachments}


def test_prompt_handler_ignores_attachments_for_text_only_handler() -> None:
    from loushang.harnesstui.conversation.screen_runner import run_prompt_handler

    seen: list[str] = []

    def handle_prompt(text: str) -> None:
        seen.append(text)

    asyncio.run(
        run_prompt_handler(
            handle_prompt,
            "describe",
            attachments=(object(),),
        )
    )

    assert seen == ["describe"]


def test_conversation_screen_forwards_neutral_attachments_end_to_end() -> None:
    from loushang.harnesstui.conversation.input import ConversationInputResult
    from loushang.harnesstui.conversation.screen_runner import (
        run_conversation_screen,
    )
    from loushang.tui.terminal import TerminalSize

    app = _RunnerApp()
    attachment = object()
    seen: dict[str, object] = {}

    class Router:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def handle(self, event: object) -> ConversationInputResult:
            if getattr(event, "kind", None) != "text":
                return ConversationInputResult(render_requested=False)
            app.state.active_started_at = app.now()
            return ConversationInputResult(
                prompt_text="describe",
                prompt_attachments=(attachment,),
            )

    async def handle_prompt(
        text: str,
        *,
        attachments: tuple[object, ...] | None = None,
    ) -> None:
        seen["text"] = text
        seen["attachments"] = attachments

    exit_code = asyncio.run(
        run_conversation_screen(
            app=app,
            stdin=StringIO("x"),
            stdout=StringIO(),
            handle_prompt=handle_prompt,
            on_abort=lambda: None,
            should_exit=lambda _text: False,
            terminal_mode_factory=lambda _stdin, _stdout: nullcontext(object()),
            terminal_size_provider=lambda: TerminalSize(columns=80, rows=24),
            interruption_message="interrupted",
            cancellation_message="cancelled",
            input_router_factory=Router,
        )
    )

    assert exit_code == 0
    assert seen == {
        "text": "describe",
        "attachments": (attachment,),
    }


def test_finish_active_task_preserves_success_error_and_cancellation_state() -> None:
    from loushang.harnesstui.conversation.screen_runner import finish_active_task

    async def scenario() -> tuple[int | None, int | None, int | None, _RunnerApp]:
        app = _RunnerApp()

        async def success() -> int:
            return 7

        async def failure() -> int:
            raise RuntimeError("prompt failed")

        async def pending() -> int:
            await asyncio.Event().wait()
            return 0

        success_task = asyncio.create_task(success())
        success_result = await finish_active_task(
            app=app,
            active_task=success_task,
            started_at=0.5,
            cancellation_message="cancelled",
        )
        failure_task = asyncio.create_task(failure())
        failure_result = await finish_active_task(
            app=app,
            active_task=failure_task,
            started_at=0.5,
            cancellation_message="cancelled",
        )
        cancelled_task = asyncio.create_task(pending())
        cancelled_task.cancel()
        cancelled_result = await finish_active_task(
            app=app,
            active_task=cancelled_task,
            started_at=0.5,
            cancellation_message="cancelled",
        )
        return success_result, failure_result, cancelled_result, app

    success, failure, cancelled, app = asyncio.run(scenario())

    assert (success, failure, cancelled) == (7, 1, None)
    assert app.errors == ["prompt failed"]
    assert app.completions == [0.5, 0.5]
    assert app.state.aborts == [("cancelled", 0.0)]


def test_abort_active_waits_for_natural_completion_before_presenting_interruption() -> (
    None
):
    from loushang.harnesstui.conversation.screen_runner import abort_active

    calls: list[str] = []
    app = _RunnerApp(calls=calls)

    async def scenario() -> None:
        release = asyncio.Event()

        async def pending() -> None:
            await release.wait()
            calls.append("task.complete")

        async def on_abort() -> None:
            calls.append("on_abort")
            release.set()

        task = asyncio.create_task(pending())
        await asyncio.sleep(0)
        await abort_active(
            app=app,
            active_task=task,
            on_abort=on_abort,
            interruption_message="interrupted",
        )
        assert task.cancelled() is False

    asyncio.run(scenario())

    assert calls == ["on_abort", "task.complete", "state.abort"]
    assert app.state.aborts == [("interrupted", 0.0)]


def test_abort_active_presents_prompt_failure_without_escaping_the_loop() -> None:
    from loushang.harnesstui.conversation.screen_runner import abort_active

    calls: list[str] = []
    app = _RunnerApp(calls=calls)

    async def scenario() -> None:
        async def fail() -> None:
            raise RuntimeError("prompt failed while aborting")

        task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        await abort_active(
            app=app,
            active_task=task,
            on_abort=lambda: calls.append("on_abort"),
            interruption_message="interrupted",
        )

    asyncio.run(scenario())

    assert app.errors == ["prompt failed while aborting"]
    assert calls == ["on_abort", "state.abort"]
    assert app.state.aborts == [("interrupted", 0.0)]


def test_pop_interrupt_pending_steer_is_fifo_and_empty_safe() -> None:
    from loushang.harnesstui.conversation.screen_runner import (
        pop_interrupt_pending_steer,
    )

    app = SimpleNamespace(state=SimpleNamespace(pending_steers=[]))

    assert pop_interrupt_pending_steer(app) is None
    app.state.pending_steers.extend(["first", "second"])
    assert pop_interrupt_pending_steer(app) == "first"
    assert app.state.pending_steers == ["second"]


class _RunnerState:
    def __init__(self, *, calls: list[str] | None = None) -> None:
        self.records: list[object] = []
        self.active_started_at: float | None = None
        self.pending_steers: list[str] = []
        self.assistant_draft_buffer = None
        self.aborts: list[tuple[str, float]] = []
        self._calls = calls

    @property
    def running(self) -> bool:
        return self.active_started_at is not None

    def abort(self, *, message: str, elapsed_seconds: float) -> None:
        self.aborts.append((message, elapsed_seconds))
        self.active_started_at = None
        if self._calls is not None:
            self._calls.append("state.abort")


class _RunnerApp:
    def __init__(self, *, calls: list[str] | None = None) -> None:
        self.state = _RunnerState(calls=calls)
        self.surface_host = None
        self.render_requester = None
        self.terminal_diagnostics_provider = None
        self.terminal_capabilities = None
        self.errors: list[str] = []
        self.completions: list[float] = []

    def now(self) -> float:
        return 1.0

    def elapsed_seconds(self) -> float:
        return 0.0

    def start_pending_prompt(self, _text: str) -> None:
        self.state.active_started_at = self.now()

    def add_error(self, summary: str, diagnostics: str = "") -> None:
        del diagnostics
        self.errors.append(summary)

    def complete_run(self, *, elapsed_seconds: float | None = None) -> None:
        self.completions.append(0.0 if elapsed_seconds is None else elapsed_seconds)
        self.state.active_started_at = None

    def startup_welcome_panel(self) -> _RunnerApp:
        return self

    def render(self, constraints: object):
        from loushang.tui.core import RenderResult

        del constraints
        return RenderResult(lines=())
