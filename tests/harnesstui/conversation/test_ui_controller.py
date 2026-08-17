from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.harness.host.types import HostActionResult
from loushang.harness.session import (
    SessionOperationAvailability,
    SessionOperationRuntime,
)
from loushang.harnesstui.conversation.controller import (
    build_standard_conversation_ui_controller,
)
from loushang.harnesstui.conversation.intents import PromptIntent


def test_conversation_ui_controller_routes_actions_to_runtime_current_session() -> None:
    prompts: list[tuple[str, str]] = []
    followups: list[tuple[str, str]] = []

    class Session:
        def __init__(self, name: str) -> None:
            self.name = name

        async def prompt(self, text: str, **_kwargs: object) -> None:
            prompts.append((self.name, text))

        def follow_up(self, text: str, images=None) -> None:
            del images
            followups.append((self.name, text))

        async def wait_for_idle(self) -> None:
            return None

    current = Session("current")
    runtime = SimpleNamespace(current_session=current)
    controller = build_standard_conversation_ui_controller(
        get_operations=lambda: SessionOperationRuntime(runtime.current_session),
    )

    asyncio.run(controller.dispatch(PromptIntent("hello")))
    asyncio.run(controller.follow_up("later"))

    assert prompts == [("current", "hello")]
    assert followups == [("current", "later")]


def test_conversation_ui_controller_reports_explicitly_unavailable_input() -> None:
    controller = build_standard_conversation_ui_controller(
        get_operations=lambda: SessionOperationRuntime(
            SimpleNamespace(),
            availability=SessionOperationAvailability.from_capabilities(()),
        ),
    )

    result = asyncio.run(controller.follow_up("later"))

    assert result.error_message == "Follow-up is unavailable for this session."


def test_conversation_ui_controller_resolves_session_command_on_current_session() -> (
    None
):
    calls: list[tuple[str, str, str]] = []

    class Session:
        def __init__(self, name: str) -> None:
            self.name = name

        async def execute_command_async(self, command: str, args: str):
            calls.append((self.name, command, args))
            return SimpleNamespace(result={"status": "ok", "message": "restored"})

    current = Session("current")
    runtime = SimpleNamespace(current_session=current)

    async def dispatch_session_command(_intent: object) -> HostActionResult:
        calls.append(("catalog", runtime.current_session.name, ""))
        execution = await runtime.current_session.execute_command_async(
            "/resume",
            "session-2",
        )
        return HostActionResult(status_message=execution.result["message"])

    controller = build_standard_conversation_ui_controller(
        get_operations=lambda: SessionOperationRuntime(runtime.current_session),
        dispatch_session_command=dispatch_session_command,
    )

    result = asyncio.run(controller.dispatch(PromptIntent("/resume session-2")))

    assert isinstance(result, HostActionResult)
    assert result.status_message == "restored"
    assert calls == [
        ("catalog", "current", ""),
        ("current", "/resume", "session-2"),
    ]
