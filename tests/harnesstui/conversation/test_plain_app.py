from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO

from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.conversation.host import (
    ConversationHostDecision,
    ConversationHostProfile,
    ConversationHostRoute,
)
from loushang.harnesstui.conversation.plain_app import (
    PlainConversationPorts,
    PlainConversationProductBinding,
    PlainConversationProfile,
    build_plain_conversation_app,
)


@dataclass
class _Result:
    exit_code: int | None = None
    error_message: str | None = None
    status_message: str | None = None
    traceback_text: str | None = None


class _Controller:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls
        self.on_suppress = None

    async def dispatch(self, intent: str) -> _Result:
        self.calls.append(("dispatch", intent))
        if intent == "suppress":
            if self.on_suppress is not None:
                self.on_suppress()
            return _Result(exit_code=9, error_message="skip")
        return _Result(status_message=f"done:{intent}")

    async def steer(self, text: str) -> _Result:
        self.calls.append(("steer", text))
        return _Result(exit_code=2)

    async def follow_up(self, text: str) -> _Result:
        self.calls.append(("follow_up", text))
        return _Result(exit_code=3)


class _Renderer:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def render_interruption(self) -> None:
        self.calls.append(("render_interruption", None))

    def render_status(self, text: str) -> None:
        self.calls.append(("render_status", text))

    def render_error(self, text: str) -> None:
        self.calls.append(("render_error", text))

    def render_worked(self, elapsed_seconds: float) -> None:
        self.calls.append(("render_worked", elapsed_seconds))


def _build_app():
    calls: list[tuple[str, object]] = []
    traces: list[tuple[str, dict[str, object]]] = []
    parsed_actions: list[ConversationTextAction] = []

    def parse(action: ConversationTextAction) -> str | None:
        parsed_actions.append(action)
        return action.text or None

    def decide(intent: str, _action: ConversationTextAction):
        if intent == "settle":
            return ConversationHostDecision(ConversationHostRoute.ABORT_SETTLING)
        if intent == "follow":
            return ConversationHostDecision(
                ConversationHostRoute.FOLLOW_UP,
                text="queued",
                source="command",
            )
        if intent == "steer":
            return ConversationHostDecision(ConversationHostRoute.STEER)
        if intent == "local":
            return ConversationHostDecision(
                ConversationHostRoute.LOCAL,
                local="panel",
            )
        return ConversationHostDecision(ConversationHostRoute.DISPATCH)

    async def emit(write, *, label: str) -> None:
        calls.append(("emit", label))
        write()

    async def local(
        action: ConversationTextAction,
        intent: str,
        payload: str | None,
    ) -> int | None:
        calls.append(("local", (action, intent, payload)))
        return 4

    async def restore(text: str) -> str | None:
        calls.append(("restore", text))
        return f"queued\n\n{text}"

    controller = _Controller(calls)

    def bind_product(assembly):
        calls.append(("bind_local", assembly.settings_text()))
        return PlainConversationProductBinding(
            host_profile=ConversationHostProfile(
                parse=parse,
                decide=decide,
                is_exit=lambda intent: intent == "quit",
                now=lambda: 10.0,
            ),
            controller=controller,
            abort_action=lambda: _record(calls, "abort_action"),
            is_work_intent=lambda intent: intent in {"dispatch", "suppress"},
            local=local,
            fallback_error_message=lambda: None,
            suppress_aborted_error=lambda error_message: error_message == "skip",
        )

    app = build_plain_conversation_app(
        profile=PlainConversationProfile(
            abort_settling_message="settling",
            idle_follow_up_message="idle",
            queued_follow_up_message="queued",
            now=lambda: 12.0,
        ),
        ports=PlainConversationPorts(
            bind_product=bind_product,
            renderer=_Renderer(calls),
            emit=emit,
            trace=lambda name, **data: traces.append((name, data)),
            stderr=StringIO(),
            session_running=lambda: False,
            last_error_message=lambda: None,
            restore_queue=restore,
            pending_messages=lambda: ("pending",),
        ),
    )
    controller.on_suppress = app.lifecycle.mark_abort_requested
    return app, calls, traces, parsed_actions


def test_plain_app_composes_dispatch_result_and_product_suppression() -> None:
    app, calls, _traces, parsed_actions = _build_app()

    assert asyncio.run(app.handle_prompt("dispatch")) is None
    assert asyncio.run(app.handle_prompt("suppress")) == 9

    assert parsed_actions[0].source == "plain_prompt"
    assert ("render_status", "done:dispatch") in calls
    assert ("render_error", "skip") not in calls
    assert app.lifecycle.aborted_id is None
    assert ("bind_local", "Settings\nStatus line: true") in calls


def test_plain_app_wires_routes_queue_sources_restore_and_abort() -> None:
    app, calls, traces, _parsed_actions = _build_app()
    app.lifecycle.begin_work()

    async def scenario() -> None:
        assert await app.action_host.submit(ConversationTextAction("settle")) is None
        assert await app.action_host.submit(ConversationTextAction("follow")) == 3
        assert await app.action_host.follow_up(ConversationTextAction(" direct ")) == 3
        assert await app.action_host.submit(ConversationTextAction("steer")) == 2
        assert await app.action_host.submit(ConversationTextAction("local")) == 4
        assert (
            await app.action_host.restore_queue_to_composer("draft")
            == "queued\n\ndraft"
        )
        assert app.action_host.pending_messages() == ("pending",)
        await app.action_host.abort()

    asyncio.run(scenario())

    assert ("follow_up", "queued") in calls
    assert ("follow_up", "direct") in calls
    assert ("render_status", "settling") in calls
    sources = [
        data["source"] for name, data in traces if name == "prompt.follow_up.start"
    ]
    assert sources == ["command", "keybinding"]
    assert ("restore", "draft") in calls
    assert ("render_interruption", None) in calls
    assert ("abort_action", None) in calls


async def _record(calls: list[tuple[str, object]], name: str) -> None:
    calls.append((name, None))
