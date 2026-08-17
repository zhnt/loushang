from __future__ import annotations

from loushang.harnesstui.commands.catalog import ConversationCommandCatalog
from loushang.harnesstui.conversation.control import (
    ConversationRunControl,
    ConversationTextAction,
)
from loushang.harnesstui.conversation.host import (
    ConversationHostProfile,
    ConversationHostRoute,
    build_standard_conversation_host_profile,
)
from loushang.harnesstui.conversation.info import (
    ConversationInfoPresenter,
    ConversationLocalActionBinding,
    ConversationLocalActionRegistry,
    ConversationLocalActionResult,
)
from loushang.harnesstui.conversation.intents import (
    CommandSelectIntent,
    CommandsIntent,
    ConversationIntent,
    DebugIntent,
    HotkeysIntent,
    ModelSelectIntent,
    ModelsIntent,
    SettingsIntent,
)


async def _emit(operation, *, label: str) -> None:
    del label
    operation()


async def _local_result(_intent: ConversationIntent) -> ConversationLocalActionResult:
    return ConversationLocalActionResult()


def _local_actions() -> ConversationLocalActionRegistry[ConversationIntent]:
    return ConversationLocalActionRegistry(
        presenter=ConversationInfoPresenter(
            emit=_emit,
            render_status=lambda _text: None,
        ),
        bindings=(
            ConversationLocalActionBinding(
                "debug",
                DebugIntent,
                _local_result,
                deferred=True,
            ),
            ConversationLocalActionBinding(
                "model_select",
                ModelSelectIntent,
                _local_result,
            ),
            ConversationLocalActionBinding("models", ModelsIntent, _local_result),
            ConversationLocalActionBinding(
                "command_select",
                CommandSelectIntent,
                _local_result,
            ),
            ConversationLocalActionBinding("commands", CommandsIntent, _local_result),
            ConversationLocalActionBinding("hotkeys", HotkeysIntent, _local_result),
            ConversationLocalActionBinding("settings", SettingsIntent, _local_result),
        ),
    )


def _profile(
    lifecycle: ConversationRunControl,
    traces: list[tuple[str, dict[str, object]]] | None = None,
) -> ConversationHostProfile[ConversationIntent, str]:
    sink = traces if traces is not None else []
    return build_standard_conversation_host_profile(
        lifecycle=lifecycle,
        local_actions=_local_actions(),
        command_effect=ConversationCommandCatalog(
            session_commands=lambda: []
        ).effect_for_route,
        session_running=lambda: False,
        trace=lambda name, **data: sink.append((name, data)),
        now=lambda: 0.0,
    )


def _route(intent: ConversationIntent, lifecycle: ConversationRunControl):
    return _profile(lifecycle).decide(intent, ConversationTextAction("input"))


def test_coding_tui_profile_preserves_running_input_policy() -> None:
    from loushang.harnesstui.conversation.intents import (
        CommandSelectIntent,
        CommandsIntent,
        DebugIntent,
        FollowUpIntent,
        HotkeysIntent,
        ModelSelectIntent,
        ModelsIntent,
        PromptIntent,
        QuitIntent,
        SettingsIntent,
    )

    lifecycle = ConversationRunControl()
    lifecycle.begin_work()

    follow = _route(FollowUpIntent("later"), lifecycle)
    assert follow.route is ConversationHostRoute.FOLLOW_UP
    assert (follow.text, follow.source) == ("later", "command")
    assert _route(PromptIntent("steer"), lifecycle).route is ConversationHostRoute.STEER
    assert _route(DebugIntent(), lifecycle).route is ConversationHostRoute.STEER
    assert _route(QuitIntent(), lifecycle).route is ConversationHostRoute.DISPATCH

    local_cases = (
        (ModelSelectIntent(), "model_select"),
        (ModelsIntent(), "models"),
        (HotkeysIntent(), "hotkeys"),
        (SettingsIntent(), "settings"),
        (CommandSelectIntent(), "command_select"),
        (CommandsIntent(), "commands"),
    )
    for intent, action in local_cases:
        decision = _route(intent, lifecycle)
        assert decision.route is ConversationHostRoute.LOCAL
        assert decision.local == action


def test_coding_tui_profile_blocks_non_quit_input_while_abort_settles() -> None:
    from loushang.harnesstui.conversation.intents import PromptIntent, QuitIntent

    lifecycle = ConversationRunControl()
    lifecycle.begin_work()
    lifecycle.mark_abort_requested()

    assert (
        _route(PromptIntent("new prompt"), lifecycle).route
        is ConversationHostRoute.ABORT_SETTLING
    )
    assert _route(QuitIntent(), lifecycle).route is ConversationHostRoute.DISPATCH


def test_coding_tui_profile_classifies_idle_dispatch_and_local_actions() -> None:
    from loushang.harnesstui.conversation.intents import (
        BashIntent,
        DebugIntent,
        FollowUpIntent,
        PromptIntent,
        QuitIntent,
    )

    lifecycle = ConversationRunControl()

    debug = _route(DebugIntent(), lifecycle)
    assert debug.route is ConversationHostRoute.LOCAL
    assert debug.local == "debug"
    assert (
        _route(FollowUpIntent("later"), lifecycle).route
        is ConversationHostRoute.FOLLOW_UP
    )
    for intent in (PromptIntent("hello"), BashIntent("pwd"), QuitIntent()):
        assert _route(intent, lifecycle).route is ConversationHostRoute.DISPATCH


def test_coding_tui_profile_owns_prompt_trace_and_command_policy() -> None:
    from loushang.harnesstui.conversation.intents import SettingsIntent

    traces: list[tuple[str, dict[str, object]]] = []
    profile = _profile(ConversationRunControl(), traces)

    assert profile.parse(ConversationTextAction("   ")) is None
    decision = profile.decide(SettingsIntent(), ConversationTextAction("/settings"))

    assert decision.local == "settings"
    assert [name for name, _data in traces] == [
        "prompt.start",
        "prompt.ignored",
        "prompt.command",
    ]
