from __future__ import annotations

import asyncio
from io import StringIO


class _Lifecycle:
    def __init__(self, *, aborted_id: int | None = None) -> None:
        self.aborted_id = aborted_id
        self.cleared: list[int] = []

    def clear_aborted(self, run_id: int) -> None:
        self.cleared.append(run_id)
        if self.aborted_id == run_id:
            self.aborted_id = None


class _Renderer:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.worked: list[float] = []
        self.statuses: list[str] = []

    def render_error(self, text: str) -> None:
        self.errors.append(text)

    def render_worked(self, elapsed_seconds: float) -> None:
        self.worked.append(elapsed_seconds)

    def render_status(self, text: str) -> None:
        self.statuses.append(text)


async def _emit(write, *, label: str) -> None:
    write()


def test_prompt_result_suppresses_cancelled_error_for_aborted_run() -> None:
    from loushang.coding.ui.controller import ControllerResult
    from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome
    from loushang.coding.ui.prompt_result import PromptResultHandler

    lifecycle = _Lifecycle(aborted_id=4)
    renderer = _Renderer()
    traces: list[tuple[str, dict[str, object]]] = []
    outcome = PromptDispatchOutcome(
        result=ControllerResult(exit_code=1, error_message="Request aborted by user"),
        run_id=4,
        work_intent=True,
        started_at=10.0,
    )

    handler = PromptResultHandler(
        lifecycle=lifecycle,
        renderer=renderer,
        emit=_emit,
        stderr=StringIO(),
        verbose=False,
        last_error_message=lambda: None,
        session_error_message=lambda: None,
        now=lambda: 12.0,
        trace=lambda name, **data: traces.append((name, data)),
    )

    exit_code = asyncio.run(handler.handle(outcome, prompt_started=9.0))

    assert exit_code == 1
    assert lifecycle.aborted_id is None
    assert lifecycle.cleared == [4]
    assert renderer.errors == []
    assert traces == [
        ("prompt.suppressed_cancelled", {"run_id": 4, "error_message": "Request aborted by user"})
    ]


def test_prompt_result_renders_error_and_verbose_traceback() -> None:
    from loushang.coding.ui.controller import ControllerResult
    from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome
    from loushang.coding.ui.prompt_result import PromptResultHandler

    renderer = _Renderer()
    stderr = StringIO()
    emitted: list[str] = []
    traces: list[str] = []
    outcome = PromptDispatchOutcome(
        result=ControllerResult(exit_code=2, error_message="provider failed", traceback_text="traceback text"),
        run_id=3,
        work_intent=True,
        started_at=10.0,
    )

    async def emit(write, *, label: str) -> None:
        emitted.append(label)
        write()

    handler = PromptResultHandler(
        lifecycle=_Lifecycle(),
        renderer=renderer,
        emit=emit,
        stderr=stderr,
        verbose=True,
        last_error_message=lambda: None,
        session_error_message=lambda: None,
        now=lambda: 12.0,
        trace=lambda name, **_data: traces.append(name),
    )

    exit_code = asyncio.run(handler.handle(outcome, prompt_started=9.0))

    assert exit_code == 2
    assert emitted == ["prompt:error"]
    assert renderer.errors == ["provider failed"]
    assert stderr.getvalue() == "traceback text"
    assert traces[-1] == "prompt.end"


def test_prompt_result_does_not_duplicate_existing_event_error() -> None:
    from loushang.coding.ui.controller import ControllerResult
    from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome
    from loushang.coding.ui.prompt_result import PromptResultHandler

    renderer = _Renderer()
    emitted: list[str] = []
    outcome = PromptDispatchOutcome(
        result=ControllerResult(error_message="same error"),
        run_id=1,
        work_intent=True,
        started_at=10.0,
    )

    async def emit(write, *, label: str) -> None:
        emitted.append(label)
        write()

    handler = PromptResultHandler(
        lifecycle=_Lifecycle(),
        renderer=renderer,
        emit=emit,
        stderr=StringIO(),
        verbose=False,
        last_error_message=lambda: "same error",
        session_error_message=lambda: None,
        now=lambda: 12.0,
        trace=lambda _name, **_data: None,
    )

    exit_code = asyncio.run(handler.handle(outcome, prompt_started=9.0))

    assert exit_code is None
    assert emitted == []
    assert renderer.errors == []


def test_prompt_result_renders_worked_for_successful_work_intent() -> None:
    from loushang.coding.ui.controller import ControllerResult
    from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome
    from loushang.coding.ui.prompt_result import PromptResultHandler

    renderer = _Renderer()
    emitted: list[str] = []
    outcome = PromptDispatchOutcome(
        result=ControllerResult(exit_code=None),
        run_id=2,
        work_intent=True,
        started_at=10.0,
    )

    async def emit(write, *, label: str) -> None:
        emitted.append(label)
        write()

    handler = PromptResultHandler(
        lifecycle=_Lifecycle(),
        renderer=renderer,
        emit=emit,
        stderr=StringIO(),
        verbose=False,
        last_error_message=lambda: None,
        session_error_message=lambda: None,
        now=lambda: 12.5,
        trace=lambda _name, **_data: None,
    )

    exit_code = asyncio.run(handler.handle(outcome, prompt_started=8.0))

    assert exit_code is None
    assert emitted == ["prompt:worked"]
    assert renderer.worked == [2.5]


def test_prompt_result_renders_controller_status_message_instead_of_worked() -> None:
    from loushang.coding.ui.controller import ControllerResult
    from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome
    from loushang.coding.ui.prompt_result import PromptResultHandler

    renderer = _Renderer()
    emitted: list[str] = []
    outcome = PromptDispatchOutcome(
        result=ControllerResult(exit_code=None, status_message="Session name set: Project Alpha"),
        run_id=2,
        work_intent=True,
        started_at=10.0,
    )

    async def emit(write, *, label: str) -> None:
        emitted.append(label)
        write()

    handler = PromptResultHandler(
        lifecycle=_Lifecycle(),
        renderer=renderer,
        emit=emit,
        stderr=StringIO(),
        verbose=False,
        last_error_message=lambda: None,
        session_error_message=lambda: None,
        now=lambda: 12.5,
        trace=lambda _name, **_data: None,
    )

    exit_code = asyncio.run(handler.handle(outcome, prompt_started=8.0))

    assert exit_code is None
    assert emitted == ["prompt:status"]
    assert renderer.statuses == ["Session name set: Project Alpha"]
    assert renderer.worked == []
