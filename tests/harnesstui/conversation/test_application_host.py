from __future__ import annotations

import asyncio
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest

from loushang.harnesstui.conversation.application_host import (
    PreparedPlainConversationRun,
    PreparedScreenConversationRun,
    run_prepared_plain_conversation,
    run_prepared_screen_conversation,
)
from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.tui import CompletionProvider
from loushang.tui.transcript import UserPromptRecord


class _ScreenApp(ScreenConversationApp):
    def _create_frame_presentation(self) -> ScreenFramePresentation:
        return ScreenFramePresentation(
            ScreenFrameCopy(
                working_label="Running",
                steer_label="Steers",
                steer_hint="interrupt",
                followup_label="Follow-ups",
                followup_hint="edit",
            )
        )


class _ActionHost:
    async def submit(self, _action: object) -> None:
        return None

    async def steer(self, _action: object) -> None:
        return None

    async def follow_up(self, _action: object) -> None:
        return None

    async def abort(self) -> None:
        return None

    async def restore_queue_to_composer(self, _current_text: str) -> None:
        return None

    def pending_messages(self) -> None:
        return None

    def should_exit(self, _text: str) -> bool:
        return False


class _Surface:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def handle_text(self, _text: str) -> None:
        return None

    async def handle_surface_intent(self, _intent: object) -> None:
        return None

    def is_local_command(self, _text: str) -> bool:
        return False

    def clear_approval_surfaces(self) -> None:
        self.events.append("surface.clear")


class _EventSource:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def subscribe(self, _listener: object):
        self.events.append("subscribe")

        def unsubscribe() -> None:
            self.events.append("unsubscribe")

        return unsubscribe


class _Context:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __enter__(self) -> object:
        self.events.append("context.enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.append("context.exit")


def _binder(events: list[str], name: str):
    def bind():
        events.append(f"{name}.bind")

        def unbind() -> None:
            events.append(f"{name}.unbind")

        return unbind

    return bind


def _screen_run(events: list[str]) -> PreparedScreenConversationRun:
    app = _ScreenApp(
        model_label="model",
        cwd="/workspace",
        branch="main",
        session_label="session",
        active_transcript_line_budget=20,
    )
    return PreparedScreenConversationRun(
        app=app,
        action_host=_ActionHost(),  # type: ignore[arg-type]
        surface=_Surface(events),  # type: ignore[arg-type]
        event_source=_EventSource(events),
        event_listener_factory=lambda: events.append("listener") or object(),
        interaction_context=_Context(events),
        profile=ConversationScreenRunProfile(
            input_router_factory=None,
            interruption_message="Interrupted",
            cancellation_message="Cancelled",
        ),
        should_exit=lambda _text: False,
        trace=lambda name, **_data: events.append(f"trace:{name}"),
        history_records=(UserPromptRecord("old prompt"),),
        transcript_source_factory=lambda: SimpleNamespace(snapshot=lambda: None),
        completion_provider=CompletionProvider(()),
        bind_presenter=_binder(events, "presenter"),
        bind_transition=_binder(events, "transition"),
        on_history_installed=lambda history: events.append(
            f"history:{history.record_count}:{history.active_record_count}"
        ),
        on_start=lambda: events.append("start"),
        on_clean_exit=lambda code: events.append(f"clean:{code}"),
    )


def test_prepared_screen_host_installs_state_and_unwinds_in_reverse() -> None:
    events: list[str] = []
    run = _screen_run(events)

    async def screen_runner(**kwargs: Any) -> int:
        events.append("runner")
        assert kwargs["app"].state.records == [UserPromptRecord("old prompt")]
        assert kwargs["app"].transcript_source_factory is not None
        return 7

    result = asyncio.run(
        run_prepared_screen_conversation(
            run,
            stdin=StringIO(),
            stdout=StringIO(),
            screen_runner=screen_runner,
        )
    )

    assert result == 7
    assert events == [
        "history:1:1",
        "presenter.bind",
        "transition.bind",
        "listener",
        "context.enter",
        "start",
        "subscribe",
        "runner",
        "clean:7",
        "trace:tui.end",
        "unsubscribe",
        "context.exit",
        "transition.unbind",
        "surface.clear",
        "presenter.unbind",
    ]


def test_prepared_screen_host_cleans_outer_bindings_when_listener_factory_fails() -> (
    None
):
    events: list[str] = []
    run = _screen_run(events)

    def fail_listener() -> object:
        events.append("listener.fail")
        raise RuntimeError("projector failed")

    object.__setattr__(run, "event_listener_factory", fail_listener)

    with pytest.raises(RuntimeError, match="projector failed"):
        asyncio.run(
            run_prepared_screen_conversation(
                run,
                stdin=StringIO(),
                stdout=StringIO(),
                screen_runner=lambda **_kwargs: None,  # type: ignore[arg-type]
            )
        )

    assert events[-5:] == [
        "transition.bind",
        "listener.fail",
        "transition.unbind",
        "surface.clear",
        "presenter.unbind",
    ]
    assert "context.enter" not in events


def test_prepared_screen_host_unsubscribes_before_outer_cleanup_on_runner_error() -> (
    None
):
    events: list[str] = []
    run = _screen_run(events)

    async def fail_runner(**_kwargs: object) -> int:
        events.append("runner.fail")
        raise RuntimeError("terminal failed")

    with pytest.raises(RuntimeError, match="terminal failed"):
        asyncio.run(
            run_prepared_screen_conversation(
                run,
                stdin=StringIO(),
                stdout=StringIO(),
                screen_runner=fail_runner,
            )
        )

    assert events[-7:] == [
        "runner.fail",
        "trace:tui.end",
        "unsubscribe",
        "context.exit",
        "transition.unbind",
        "surface.clear",
        "presenter.unbind",
    ]


def test_prepared_plain_host_owns_subscription_and_context_lifetime() -> None:
    events: list[str] = []

    async def handle_prompt(text: str) -> int | None:
        events.append(f"handle:{text}")
        return None

    def build_app(_emit: object) -> Any:
        events.append("build")
        return SimpleNamespace(handle_prompt=handle_prompt)

    async def prompt_runner(**kwargs: Any) -> int:
        events.append("prompt")
        await kwargs["handle_prompt"]("hello")
        return 0

    run = PreparedPlainConversationRun(
        event_source=_EventSource(events),
        event_listener=object(),
        interaction_context=_Context(events),
        build_app=build_app,  # type: ignore[arg-type]
        render_header=lambda: events.append("header"),
        trace=lambda name, **_data: events.append(f"trace:{name}"),
        on_start=lambda: events.append("start"),
    )

    result = asyncio.run(
        run_prepared_plain_conversation(
            run,
            stdin=StringIO(),
            stdout=StringIO(),
            prompt_runner=prompt_runner,
        )
    )

    assert result == 0
    assert events == [
        "context.enter",
        "start",
        "subscribe",
        "build",
        "header",
        "prompt",
        "handle:hello",
        "trace:tui.end",
        "unsubscribe",
        "context.exit",
    ]
