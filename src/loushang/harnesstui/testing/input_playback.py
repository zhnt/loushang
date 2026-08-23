from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Self, TypeVar, assert_never, cast

from loushang.harnesstui.conversation.input import (
    ConversationAbortResult,
    ConversationClipboardResult,
    ConversationExitResult,
    ConversationFollowupResult,
    ConversationInputHandled,
    ConversationInputIgnored,
    ConversationInputResult,
    ConversationInputRouter,
    ConversationLocalResult,
    ConversationPromptResult,
    ConversationSteerResult,
    ConversationSurfaceResult,
)
from loushang.harnesstui.testing.ports import (
    ConversationPlaybackAppPort,
    ConversationPlaybackInputRouterFactoryPort,
    ConversationPlaybackInputRouterPort,
    ConversationResultPayloadPort,
    ConversationStateSnapshotPort,
)
from loushang.tui.completion_models import CompletionItem, CompletionProvider
from loushang.tui.input import InputIntent, InputReader
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.playback import (
    PlaybackEvent,
    PlaybackHarness,
    PlaybackResult,
    PlaybackScenario,
    PlaybackStep,
    RenderDiagnostics,
)
from loushang.tui.render_loop import RenderLoop, ScreenRoot
from loushang.tui.runtime import TuiRuntime
from loushang.tui.terminal import FakeTerminalPort, TerminalSize
from loushang.tui.transcript import DisplayRecord

AppT = TypeVar("AppT", bound=ConversationPlaybackAppPort)


def default_conversation_state_snapshot(
    app: ConversationPlaybackAppPort,
) -> Mapping[str, object]:
    """Capture the shared composer and queue state without product fields."""

    return {
        "composer_text": app.composer.value,
        "running": app.state.running,
        "pending_steers": list(app.state.pending_steers),
        "pending_followups": list(app.state.pending_followups),
    }


def default_conversation_result_payload(
    result: ConversationInputResult,
) -> Mapping[str, object]:
    """Serialize the neutral action surface of an input result."""

    payload: dict[str, object] = {
        "prompt_text": None,
        "prompt_attachment_count": 0,
        "local_text": None,
        "steer_text": None,
        "steer_attachment_count": 0,
        "followup_text": None,
        "followup_attachment_count": 0,
        "surface_intent": None,
        "abort_requested": False,
        "exit_code": None,
        "render_requested": result.render_requested,
    }
    if isinstance(result, ConversationPromptResult):
        payload["prompt_text"] = result.text
        payload["prompt_attachment_count"] = _attachment_count(result.attachments)
    elif isinstance(result, ConversationLocalResult):
        payload["local_text"] = result.text
    elif isinstance(result, ConversationSteerResult):
        payload["steer_text"] = result.text
        payload["steer_attachment_count"] = _attachment_count(result.attachments)
    elif isinstance(result, ConversationFollowupResult):
        payload["followup_text"] = result.text
        payload["followup_attachment_count"] = _attachment_count(result.attachments)
    elif isinstance(result, ConversationSurfaceResult):
        payload["surface_intent"] = _surface_intent_payload(result.intent)
    elif isinstance(result, ConversationAbortResult):
        payload["abort_requested"] = True
    elif isinstance(result, ConversationExitResult):
        payload["exit_code"] = result.exit_code
    elif isinstance(result, ConversationClipboardResult):
        pass
    elif isinstance(result, ConversationInputHandled):
        pass
    elif isinstance(result, ConversationInputIgnored):
        pass
    else:
        assert_never(result)
    return payload


class ConversationInputPlayback(Generic[AppT]):
    """Drive decoded terminal input through a conversation router and renderer."""

    def __init__(
        self,
        app: AppT,
        *,
        columns: int = 80,
        rows: int = 12,
        should_exit: Callable[[str], bool] | None = None,
        is_local_command: Callable[[str], bool] | None = None,
        keybindings: KeybindingManager | KeybindingConfig | None = None,
        input_router_factory: ConversationPlaybackInputRouterFactoryPort | None = None,
        state_snapshot: ConversationStateSnapshotPort[AppT] | None = None,
        result_payload: ConversationResultPayloadPort | None = None,
    ) -> None:
        self.app = app
        self.reader = InputReader()
        self.input_results: list[ConversationInputResult] = []
        self.step_input_results: list[tuple[ConversationInputResult, ...]] = []
        self.step_state_snapshots: list[dict[str, object]] = []
        self._state_snapshot = state_snapshot or default_conversation_state_snapshot
        self._result_payload = result_payload or default_conversation_result_payload
        factory = input_router_factory or _default_input_router_factory
        self.router = factory(
            app=app,
            should_exit=should_exit or (lambda _text: False),
            is_local_command=is_local_command or (lambda _text: False),
            keybindings=keybindings,
            width=columns,
            height=rows,
        )
        self.render_loop = RenderLoop(
            cast(ScreenRoot, app),
            clear_scrollback_policy="disabled",
        )
        port = FakeTerminalPort(
            size=TerminalSize(columns=columns, rows=rows),
        )
        app.surface_host = TuiRuntime(
            render_loop=self.render_loop,
            terminal=port,
        ).overlay_host()
        self.harness = PlaybackHarness(render=self._render, port=port)

    @property
    def port(self) -> FakeTerminalPort:
        return self.harness.port

    def play(self, events: Iterable[PlaybackEvent]) -> tuple[PlaybackStep, ...]:
        return self.harness.play(events)

    def result(self) -> ConversationInputPlaybackResult[AppT]:
        return ConversationInputPlaybackResult(
            steps=self.harness.steps,
            port=self.port,
            input_results=tuple(self.input_results),
            step_input_results=tuple(self.step_input_results),
            step_state_snapshots=tuple(self.step_state_snapshots),
            app=self.app,
            result_payload=self._result_payload,
        )

    def run(
        self,
        events: Iterable[PlaybackEvent],
    ) -> ConversationInputPlaybackResult[AppT]:
        self.play(events)
        return self.result()

    def _render(
        self,
        event: PlaybackEvent,
        size: TerminalSize,
        _previous: RenderDiagnostics | None,
    ) -> RenderDiagnostics:
        step_results: list[ConversationInputResult] = []
        if event.kind == "resize":
            _resize_router(self.router, size)
        elif event.kind == "input":
            if not isinstance(event.payload, str):
                raise TypeError("input playback event payload must be str")
            batch = self.reader.feed_batch(event.payload)
            input_events = list(batch.app_events)
            if self.reader.has_pending:
                input_events.extend(self.reader.flush_pending_batch().app_events)
            for input_event in input_events:
                result = self.router.handle(input_event)
                self.input_results.append(result)
                step_results.append(result)
        self.step_input_results.append(tuple(step_results))
        self.step_state_snapshots.append(dict(self._state_snapshot(self.app)))
        diagnostics = self.render_loop.plan(size)
        self.render_loop.commit(diagnostics, size=size)
        return diagnostics


@dataclass(frozen=True, slots=True)
class ConversationInputPlaybackResult(PlaybackResult, Generic[AppT]):
    """Terminal frames paired with neutral routed actions and state snapshots."""

    input_results: tuple[ConversationInputResult, ...]
    step_input_results: tuple[tuple[ConversationInputResult, ...], ...]
    step_state_snapshots: tuple[dict[str, object], ...]
    app: AppT
    result_payload: ConversationResultPayloadPort

    def assert_composer_text(self, expected: str) -> None:
        assert self.app.composer.value == expected

    def assert_prompt_texts(self, *expected: str) -> None:
        assert [
            result.text
            for result in self.input_results
            if isinstance(result, ConversationPromptResult)
        ] == list(expected)

    def assert_local_texts(self, *expected: str) -> None:
        assert [
            result.text
            for result in self.input_results
            if isinstance(result, ConversationLocalResult)
        ] == list(expected)

    def assert_steer_texts(self, *expected: str) -> None:
        assert [
            result.text
            for result in self.input_results
            if isinstance(result, ConversationSteerResult)
        ] == list(expected)

    def assert_followup_texts(self, *expected: str) -> None:
        assert [
            result.text
            for result in self.input_results
            if isinstance(result, ConversationFollowupResult)
        ] == list(expected)

    def assert_surface_intents(self, *expected: tuple[str, str]) -> None:
        assert [
            (result.intent.kind, result.intent.text)
            for result in self.input_results
            if isinstance(result, ConversationSurfaceResult)
        ] == list(expected)

    def assert_abort_requested(self) -> None:
        assert any(
            isinstance(result, ConversationAbortResult)
            for result in self.input_results
        )

    def assert_no_abort_requested(self) -> None:
        assert not any(
            isinstance(result, ConversationAbortResult)
            for result in self.input_results
        )

    def assert_pending_steers(self, *expected: str) -> None:
        assert self.app.state.pending_steers == list(expected)

    def assert_pending_followups(self, *expected: str) -> None:
        assert self.app.state.pending_followups == list(expected)

    def _jsonl_row(
        self,
        step: PlaybackStep,
        *,
        include_frames: bool,
    ) -> dict[str, Any]:
        row = PlaybackResult._jsonl_row(
            self,
            step,
            include_frames=include_frames,
        )
        step_results = (
            self.step_input_results[step.index]
            if step.index < len(self.step_input_results)
            else ()
        )
        state_snapshot = (
            self.step_state_snapshots[step.index]
            if step.index < len(self.step_state_snapshots)
            else dict(default_conversation_state_snapshot(self.app))
        )
        row["conversation"] = {
            "state": state_snapshot,
            "input_results": [
                dict(self.result_payload(result)) for result in step_results
            ],
        }
        return row


@dataclass(slots=True)
class ConversationInputScenario(PlaybackScenario, Generic[AppT]):
    """Fluent input recipe around a configured neutral playback driver."""

    playback: ConversationInputPlayback[AppT]

    @property
    def app(self) -> AppT:
        return self.playback.app

    def with_running_prompt(self, text: str) -> Self:
        self.app.start_prompt(text)
        return self

    def with_pending_steers(self, *texts: str) -> Self:
        for text in texts:
            self.app.queue_steer(text)
        return self

    def with_pending_followups(self, *texts: str) -> Self:
        for text in texts:
            self.app.queue_followup(text)
        return self

    def with_history(self, *texts: str) -> Self:
        for text in texts:
            self.app.composer.add_history(text)
        return self

    def with_composer_text(self, text: str) -> Self:
        self.app.composer.set_text(text)
        return self

    def with_active_surface(self, surface: object) -> Self:
        self.app.active_surface = surface
        return self

    def with_records(self, records: Iterable[DisplayRecord]) -> Self:
        self.app.state.records.extend(records)
        self.app.state.mark_records_changed()
        return self

    def with_completion_items(self, *values: str) -> Self:
        self.app.composer.set_completion_provider(
            CompletionProvider(tuple(CompletionItem(value=value) for value in values))
        )
        return self

    def run(self) -> ConversationInputPlaybackResult[AppT]:
        return self.playback.run(self.events)


def _default_input_router_factory(
    *,
    app: ConversationPlaybackAppPort,
    should_exit: Callable[[str], bool],
    is_local_command: Callable[[str], bool],
    keybindings: KeybindingManager | KeybindingConfig | None,
    width: int,
    height: int,
) -> ConversationPlaybackInputRouterPort:
    return ConversationInputRouter(
        app=app,
        should_exit=should_exit,
        is_local_command=is_local_command,
        keybindings=keybindings,
        width=width,
        height=height,
    )


def _resize_router(
    router: ConversationPlaybackInputRouterPort,
    size: TerminalSize,
) -> None:
    if hasattr(router, "width"):
        setattr(router, "width", size.columns)
    if hasattr(router, "height"):
        setattr(router, "height", size.rows)


def _attachment_count(attachments: tuple[object, ...] | None) -> int:
    return len(attachments or ())


def _surface_intent_payload(intent: InputIntent[str] | None) -> dict[str, str] | None:
    if intent is None:
        return None
    return {"kind": intent.kind, "text": intent.text}


__all__ = [
    "ConversationInputPlayback",
    "ConversationInputPlaybackResult",
    "ConversationInputScenario",
    "default_conversation_result_payload",
    "default_conversation_state_snapshot",
]
