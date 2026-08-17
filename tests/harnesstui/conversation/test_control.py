from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import (
    AbortActionHandler,
    ConversationActionHost,
    ConversationRunControl,
    ConversationTextAction,
    FollowUpActionHandler,
    SteerActionHandler,
)


@dataclass
class _Result:
    exit_code: int | None = None
    error_message: str | None = None


class _StatusRenderer:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    def render_status(self, text: str) -> None:
        self.statuses.append(text)


class _ActionController:
    def __init__(self, result: _Result) -> None:
        self.result = result
        self.steers: list[str] = []
        self.follow_ups: list[str] = []

    async def steer(self, text: str) -> _Result:
        self.steers.append(text)
        return self.result

    async def follow_up(self, text: str) -> _Result:
        self.follow_ups.append(text)
        return self.result


async def _emit(write, *, label: str) -> None:
    del label
    write()


def test_conversation_text_action_is_an_immutable_neutral_value() -> None:
    attachment = PromptImageAttachment(
        bytes=b"png",
        mime_type="image/png",
        path=Path("/tmp/image.png"),
        display_path=".loushang/clipboard/image.png",
        marker="@.loushang/clipboard/image.png",
    )
    action = ConversationTextAction(
        text="describe this",
        attachments=(attachment,),
        source="composer",
    )

    assert action.text == "describe this"
    assert action.attachments == (attachment,)
    assert action.source == "composer"
    with pytest.raises(FrozenInstanceError):
        action.text = "changed"  # type: ignore[misc]


def test_conversation_action_host_is_structurally_implementable() -> None:
    class Host:
        async def submit(self, action: ConversationTextAction) -> int | None:
            return len(action.attachments)

        async def steer(self, action: ConversationTextAction) -> int | None:
            return len(action.text)

        async def follow_up(self, action: ConversationTextAction) -> int | None:
            return 7 if action.source else None

        async def abort(self) -> None:
            return None

    host: ConversationActionHost = Host()
    action = ConversationTextAction("next", source="command")

    assert asyncio.run(host.submit(action)) == 0
    assert asyncio.run(host.steer(action)) == 4
    assert asyncio.run(host.follow_up(action)) == 7
    assert asyncio.run(host.abort()) is None


def test_conversation_run_control_tracks_transient_ui_work() -> None:
    control = ConversationRunControl()

    assert control.visible_running(session_running=True) is True
    assert control.begin_work() == 1
    assert control.active is True

    control.mark_abort_requested()

    assert control.aborted_id == 1
    assert control.abort_is_settling() is True

    control.end_work()
    control.clear_aborted(1)

    assert control.active is False
    assert control.aborted_id is None


def test_abort_action_handler_marks_and_presents_before_action() -> None:
    calls: list[str] = []
    traces: list[tuple[str, dict[str, object]]] = []
    control = ConversationRunControl(active=True, active_id=5)

    class Renderer:
        def render_interruption(self) -> None:
            calls.append("render_interruption")

    async def emit(write, *, label: str) -> None:
        calls.append(f"emit:{label}")
        write()

    async def abort_action() -> None:
        calls.append("abort_action")

    handler = AbortActionHandler(
        run_control=control,
        abort_action=abort_action,
        renderer=Renderer(),
        emit=emit,
        session_running=lambda: False,
        trace=lambda name, **data: traces.append((name, data)),
    )

    asyncio.run(handler.abort())

    assert calls == [
        "emit:abort:interruption",
        "render_interruption",
        "abort_action",
    ]
    assert control.aborted_id == 5
    assert traces == [
        (
            "abort.start",
            {
                "active_run": True,
                "active_run_id": 5,
                "aborted_run_id": None,
                "session_running": False,
            },
        ),
        (
            "abort.end",
            {
                "active_run": True,
                "active_run_id": 5,
                "aborted_run_id": 5,
                "session_running": False,
            },
        ),
    ]


def test_steer_action_handler_uses_result_facts_without_fallback_copy() -> None:
    controller = _ActionController(
        _Result(exit_code=2, error_message="caller supplied steer error")
    )
    renderer = _StatusRenderer()
    handler = SteerActionHandler(
        lifecycle=ConversationRunControl(active_id=9),
        controller=controller,
        renderer=renderer,
        emit=_emit,
        trace=lambda _name, **_data: None,
    )

    assert asyncio.run(handler.steer("change")) == 2
    assert controller.steers == ["change"]
    assert renderer.statuses == ["caller supplied steer error"]


def test_follow_up_action_handler_uses_injected_idle_and_queued_copy() -> None:
    control = ConversationRunControl()
    controller = _ActionController(_Result(exit_code=3))
    renderer = _StatusRenderer()
    handler = FollowUpActionHandler(
        lifecycle=control,
        controller=controller,
        renderer=renderer,
        emit=_emit,
        trace=lambda _name, **_data: None,
        idle_status_message="caller idle",
        queued_status_message="caller queued",
    )

    assert asyncio.run(handler.queue("next", source="command")) is None
    control.begin_work()
    assert asyncio.run(handler.queue("  next step  ", source="command")) == 3

    assert controller.follow_ups == ["next step"]
    assert renderer.statuses == ["caller idle", "caller queued"]


def test_follow_up_action_handler_ignores_empty_text_and_traces_source() -> None:
    control = ConversationRunControl(active=True, active_id=7)
    controller = _ActionController(_Result())
    renderer = _StatusRenderer()
    traces: list[tuple[str, dict[str, object]]] = []
    handler = FollowUpActionHandler(
        lifecycle=control,
        controller=controller,
        renderer=renderer,
        emit=_emit,
        trace=lambda name, **data: traces.append((name, data)),
        idle_status_message="caller idle",
        queued_status_message="caller queued",
    )

    assert asyncio.run(handler.queue("   ", source="keybinding")) is None
    assert controller.follow_ups == []
    assert renderer.statuses == []
    assert traces == [
        (
            "prompt.follow_up.start",
            {
                "active_run_id": 7,
                "active_run": True,
                "source": "keybinding",
                "text_len": 0,
            },
        ),
        (
            "prompt.follow_up.ignored",
            {"reason": "empty", "source": "keybinding"},
        ),
    ]


def test_follow_up_action_handler_presents_controller_error_verbatim() -> None:
    control = ConversationRunControl(active=True, active_id=4)
    controller = _ActionController(
        _Result(exit_code=2, error_message="caller queue error")
    )
    renderer = _StatusRenderer()
    handler = FollowUpActionHandler(
        lifecycle=control,
        controller=controller,
        renderer=renderer,
        emit=_emit,
        trace=lambda _name, **_data: None,
        idle_status_message="caller idle",
        queued_status_message="caller queued",
    )

    assert asyncio.run(handler.queue("later", source="command")) == 2
    assert renderer.statuses == ["caller queue error"]
