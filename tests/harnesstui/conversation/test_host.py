from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest

from loushang.harness.commands import (
    CommandDef,
    CommandEffect,
    CommandEffectKind,
    CommandKind,
)
from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import (
    ConversationRunControl,
    ConversationTextAction,
)
from loushang.harnesstui.conversation.host import (
    ConversationHostDecision,
    ConversationHostPorts,
    ConversationHostProfile,
    ConversationHostRoute,
    ConversationRoutingProfile,
    RoutedConversationActionHost,
    bind_action_host_to_screen_runner,
)
from loushang.tui import TerminalSize


@dataclass(frozen=True)
class _Intent:
    value: str


@dataclass(frozen=True)
class _Outcome:
    value: str


def test_routing_profile_owns_standard_conversation_state_machine() -> None:
    lifecycle = ConversationRunControl()
    traces: list[tuple[str, dict[str, object]]] = []
    command = CommandDef(
        id="product.settings",
        name="settings",
        kind=CommandKind.LOCAL_UI,
        source="product",
    )
    profile = ConversationRoutingProfile(
        lifecycle=lifecycle,
        parse_intent=lambda text: _Intent(text) if text.strip() else None,
        is_exit=lambda intent: intent.value == "quit",
        local_action=lambda intent: "settings" if intent.value == "settings" else None,
        deferred_local_action=lambda intent: (
            "debug" if intent.value == "debug" else None
        ),
        follow_up_text=lambda intent: "later" if intent.value == "follow" else None,
        command_effect=lambda action, _intent: (
            CommandEffect(CommandEffectKind.LOCAL_UI, command)
            if action == "settings"
            else None
        ),
        session_running=lambda: False,
        trace=lambda name, **data: traces.append((name, data)),
    ).host_profile(now=lambda: 1.0)

    assert profile.parse(ConversationTextAction(" ")) is None
    assert profile.decide(
        _Intent("debug"),
        ConversationTextAction("debug"),
    ) == ConversationHostDecision(ConversationHostRoute.LOCAL, local="debug")
    lifecycle.begin_work()
    assert profile.decide(
        _Intent("follow"),
        ConversationTextAction("follow"),
    ) == ConversationHostDecision(
        ConversationHostRoute.FOLLOW_UP,
        text="later",
        source="command",
    )
    assert (
        profile.decide(
            _Intent("prompt"),
            ConversationTextAction("prompt"),
        ).route
        is ConversationHostRoute.STEER
    )
    assert profile.decide(
        _Intent("settings"),
        ConversationTextAction("settings"),
    ) == ConversationHostDecision(
        ConversationHostRoute.LOCAL,
        local="settings",
    )
    lifecycle.mark_abort_requested()
    assert (
        profile.decide(
            _Intent("prompt"),
            ConversationTextAction("prompt"),
        ).route
        is ConversationHostRoute.ABORT_SETTLING
    )
    assert (
        profile.decide(
            _Intent("quit"),
            ConversationTextAction("quit"),
        ).route
        is ConversationHostRoute.DISPATCH
    )
    assert [name for name, _data in traces] == [
        "prompt.start",
        "prompt.ignored",
        "prompt.command",
        "prompt.ignored",
    ]


def _attachment() -> PromptImageAttachment:
    return PromptImageAttachment(
        bytes=b"png",
        mime_type="image/png",
        path=Path("/tmp/image.png"),
        display_path="image.png",
        marker="@image.png",
    )


def _host(
    *,
    decisions: dict[str, ConversationHostDecision[str]],
    calls: list[tuple[str, object]],
) -> RoutedConversationActionHost[_Intent, _Outcome, str, tuple[str, ...]]:
    def parse(action: ConversationTextAction) -> _Intent | None:
        calls.append(("parse", action))
        return None if not action.text.strip() else _Intent(action.text)

    def decide(
        intent: _Intent,
        action: ConversationTextAction,
    ) -> ConversationHostDecision[str]:
        calls.append(("decide", (intent, action)))
        return decisions[intent.value]

    async def abort_settling(
        action: ConversationTextAction,
        intent: _Intent,
    ) -> None:
        calls.append(("abort_settling", (action, intent)))

    async def follow_up(action: ConversationTextAction) -> int | None:
        calls.append(("follow_up", action))
        return 11

    async def steer(action: ConversationTextAction) -> int | None:
        calls.append(("steer", action))
        return 12

    async def local(
        action: ConversationTextAction,
        intent: _Intent,
        payload: str | None,
    ) -> int | None:
        calls.append(("local", (action, intent, payload)))
        return 13

    async def dispatch(
        action: ConversationTextAction,
        intent: _Intent,
    ) -> _Outcome:
        calls.append(("dispatch", (action, intent)))
        return _Outcome(f"done:{intent.value}")

    async def result(
        outcome: _Outcome,
        action: ConversationTextAction,
        intent: _Intent,
        prompt_started: float,
    ) -> int | None:
        calls.append(("result", (outcome, action, intent, prompt_started)))
        return 14

    async def abort() -> None:
        calls.append(("abort", None))

    async def restore_queue(current_text: str) -> str | None:
        calls.append(("restore_queue", current_text))
        return f"queued\n\n{current_text}"

    def pending_messages() -> tuple[str, ...]:
        calls.append(("pending_messages", None))
        return ("queued",)

    return RoutedConversationActionHost(
        profile=ConversationHostProfile(
            parse=parse,
            decide=decide,
            is_exit=lambda intent: intent.value == "/quit",
            now=lambda: 42.5,
        ),
        ports=ConversationHostPorts(
            abort_settling=abort_settling,
            follow_up=follow_up,
            steer=steer,
            local=local,
            dispatch=dispatch,
            result=result,
            abort=abort,
            restore_queue=restore_queue,
            pending_messages=pending_messages,
        ),
    )


def test_routed_host_preserves_order_and_attachments_for_every_route() -> None:
    attachment = _attachment()
    decisions = {
        "settling": ConversationHostDecision(ConversationHostRoute.ABORT_SETTLING),
        "follow": ConversationHostDecision(
            ConversationHostRoute.FOLLOW_UP,
            text="follow text",
            source="command",
        ),
        "steer": ConversationHostDecision(ConversationHostRoute.STEER),
        "local": ConversationHostDecision(
            ConversationHostRoute.LOCAL,
            local="settings",
        ),
        "dispatch": ConversationHostDecision(ConversationHostRoute.DISPATCH),
    }
    calls: list[tuple[str, object]] = []
    host = _host(decisions=decisions, calls=calls)

    async def exercise() -> list[int | None]:
        return [
            await host.submit(
                ConversationTextAction(
                    name,
                    attachments=(attachment,),
                    source="prompt",
                )
            )
            for name in decisions
        ]

    assert asyncio.run(exercise()) == [None, 11, 12, 13, 14]
    assert [name for name, _value in calls] == [
        "parse",
        "decide",
        "abort_settling",
        "parse",
        "decide",
        "follow_up",
        "parse",
        "decide",
        "steer",
        "parse",
        "decide",
        "local",
        "parse",
        "decide",
        "dispatch",
        "result",
    ]

    routed_actions = [
        value
        for name, value in calls
        if name in {"abort_settling", "local", "dispatch"}
    ]
    settling_action = routed_actions[0][0]
    local_action = routed_actions[1][0]
    dispatch_action = routed_actions[2][0]
    follow_action = next(value for name, value in calls if name == "follow_up")
    steer_action = next(value for name, value in calls if name == "steer")
    for action in (
        settling_action,
        follow_action,
        steer_action,
        local_action,
        dispatch_action,
    ):
        assert action.attachments == (attachment,)
    assert follow_action.text == "follow text"
    assert follow_action.source == "command"

    result_args = next(value for name, value in calls if name == "result")
    assert result_args[0] == _Outcome("done:dispatch")
    assert result_args[3] == 42.5


def test_routed_host_skips_decision_for_empty_input_and_dispatch_result_for_other_routes() -> (
    None
):
    calls: list[tuple[str, object]] = []
    host = _host(
        decisions={"follow": ConversationHostDecision(ConversationHostRoute.FOLLOW_UP)},
        calls=calls,
    )

    assert asyncio.run(host.submit(ConversationTextAction("   "))) is None
    assert [name for name, _value in calls] == ["parse"]

    calls.clear()
    assert asyncio.run(host.submit(ConversationTextAction("follow"))) == 11
    assert [name for name, _value in calls] == [
        "parse",
        "decide",
        "follow_up",
    ]


def test_routed_host_exposes_abort_queue_and_exit_ports() -> None:
    calls: list[tuple[str, object]] = []
    host = _host(decisions={}, calls=calls)
    attachment = _attachment()

    assert (
        asyncio.run(
            host.follow_up(ConversationTextAction("next", attachments=(attachment,)))
        )
        == 11
    )
    assert (
        asyncio.run(
            host.steer(
                ConversationTextAction(
                    "change",
                    attachments=(attachment,),
                    source="steer",
                )
            )
        )
        == 12
    )
    assert asyncio.run(host.abort()) is None
    assert asyncio.run(host.restore_queue_to_composer("draft")) == "queued\n\ndraft"
    assert host.pending_messages() == ("queued",)
    assert host.should_exit("/quit") is True
    assert host.should_exit("continue") is False

    follow_action = calls[0][1]
    assert follow_action.attachments == (attachment,)
    assert follow_action.source == "keybinding"
    assert [name for name, _value in calls] == [
        "follow_up",
        "steer",
        "abort",
        "restore_queue",
        "pending_messages",
        "parse",
        "parse",
    ]


def test_screen_runner_binding_preserves_sources_and_attachment_actions() -> None:
    calls: list[tuple[str, ConversationTextAction | None]] = []

    class Host:
        async def submit(self, action: ConversationTextAction) -> int | None:
            calls.append(("submit", action))
            return 1

        async def steer(self, action: ConversationTextAction) -> int | None:
            calls.append(("steer", action))
            return 2

        async def follow_up(
            self,
            action: ConversationTextAction,
        ) -> int | None:
            calls.append(("follow_up", action))
            return 3

        async def abort(self) -> None:
            calls.append(("abort", None))

    callbacks = bind_action_host_to_screen_runner(Host())
    attachment = _attachment()

    async def exercise() -> list[int | None]:
        return [
            await callbacks.handle_prompt("prompt", attachments=(attachment,)),
            await callbacks.handle_local("/settings"),
            await callbacks.handle_steer("steer", attachments=(attachment,)),
            await callbacks.handle_followup("later", attachments=(attachment,)),
        ]

    assert asyncio.run(exercise()) == [1, 1, 2, 3]
    assert asyncio.run(callbacks.on_abort()) is None
    assert [name for name, _action in calls] == [
        "submit",
        "submit",
        "steer",
        "follow_up",
        "abort",
    ]
    assert [action.source for _name, action in calls[:-1] if action] == [
        "prompt",
        "local",
        "steer",
        "follow_up",
    ]
    assert calls[0][1].attachments == (attachment,)
    assert calls[2][1].attachments == (attachment,)
    assert calls[3][1].attachments == (attachment,)


def test_screen_runner_binding_rejects_non_image_attachments() -> None:
    class Host:
        async def submit(self, action: ConversationTextAction) -> int | None:
            return None

        async def steer(self, action: ConversationTextAction) -> int | None:
            return None

        async def follow_up(
            self,
            action: ConversationTextAction,
        ) -> int | None:
            return None

        async def abort(self) -> None:
            return None

    callbacks = bind_action_host_to_screen_runner(Host())

    with pytest.raises(TypeError, match="must be prompt images"):
        asyncio.run(callbacks.handle_prompt("prompt", attachments=(object(),)))


def test_action_host_screen_run_forwards_profile_and_product_overrides(
    monkeypatch,
) -> None:
    import loushang.harnesstui.conversation.host as host_module

    calls: list[tuple[str, object]] = []
    captured: dict[str, object] = {}
    attachment = _attachment()

    class Host:
        async def submit(self, action: ConversationTextAction) -> int | None:
            calls.append(("submit", action))
            return 1

        async def steer(self, action: ConversationTextAction) -> int | None:
            calls.append(("steer", action))
            return 2

        async def follow_up(self, action: ConversationTextAction) -> int | None:
            calls.append(("follow_up", action))
            return 3

        async def abort(self) -> None:
            calls.append(("abort", None))

    async def local(text: str, **_kwargs) -> None:
        calls.append(("local", text))

    async def surface(intent) -> None:
        calls.append(("surface", intent))

    def input_factory(**_kwargs):
        return object()

    def terminal_factory(_stdin, _stdout):
        return nullcontext()

    def size_provider() -> TerminalSize:
        return TerminalSize(columns=80, rows=24)

    async def fake_runner(**kwargs) -> int:
        captured.update(kwargs)
        await kwargs["handle_prompt"]("prompt", attachments=(attachment,))
        await kwargs["handle_local"]("/local")
        await kwargs["handle_steer"]("change")
        await kwargs["handle_followup"]("later")
        await kwargs["on_abort"]()
        return 19

    monkeypatch.setattr(host_module, "run_conversation_screen", fake_runner)
    profile = host_module.ConversationScreenRunProfile(
        input_router_factory=input_factory,
        interruption_message="caller interruption",
        cancellation_message="caller cancellation",
    )

    result = asyncio.run(
        host_module.run_action_host_conversation_screen(
            app=object(),  # type: ignore[arg-type]
            stdin=StringIO(),
            stdout=StringIO(),
            action_host=Host(),
            profile=profile,
            handle_local=local,
            handle_surface_intent=surface,
            should_exit=lambda text: text == "/quit",
            is_local_command=lambda text: text.startswith("/"),
            terminal_mode_factory=terminal_factory,
            terminal_size_provider=size_provider,
        )
    )

    assert result == 19
    assert [name for name, _value in calls] == [
        "submit",
        "local",
        "steer",
        "follow_up",
        "abort",
    ]
    assert calls[0][1].attachments == (attachment,)
    assert captured["input_router_factory"] is input_factory
    assert captured["interruption_message"] == "caller interruption"
    assert captured["cancellation_message"] == "caller cancellation"
    assert captured["handle_surface_intent"] is surface
    assert captured["terminal_mode_factory"] is terminal_factory
    assert captured["terminal_size_provider"] is size_provider
