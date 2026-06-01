from __future__ import annotations

import asyncio
from types import SimpleNamespace


class _Session:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.bash_calls: list[tuple[str, dict[str, object]]] = []
        self.steers: list[str] = []
        self.follow_ups: list[str] = []
        self.aborted = False
        self.bash_aborted = False

    async def prompt(self, text: str) -> None:
        self.prompts.append(text)

    async def execute_bash(self, command: str, **kwargs: object) -> None:
        self.bash_calls.append((command, kwargs))

    def abort(self) -> None:
        self.aborted = True

    def abort_bash(self) -> None:
        self.bash_aborted = True

    async def steer(self, text: str) -> None:
        self.steers.append(text)

    async def follow_up(self, text: str) -> None:
        self.follow_ups.append(text)


def test_parse_prompt_intent_skips_blank_input() -> None:
    from loushang.coding.ui.intent import parse_prompt_intent

    assert parse_prompt_intent("  \n") is None


def test_parse_prompt_intent_routes_regular_text_to_prompt() -> None:
    from loushang.coding.ui.intent import PromptIntent, parse_prompt_intent

    assert parse_prompt_intent("hello") == PromptIntent(text="hello")


def test_parse_prompt_intent_routes_bang_bang_to_bash() -> None:
    from loushang.coding.ui.intent import BashIntent, parse_prompt_intent

    assert parse_prompt_intent("!!  ls -al") == BashIntent(command="ls -al")


def test_parse_prompt_intent_routes_quit_command() -> None:
    from loushang.coding.ui.intent import QuitIntent, parse_prompt_intent

    assert parse_prompt_intent("/quit") == QuitIntent()


def test_parse_prompt_intent_routes_debug_command() -> None:
    from loushang.coding.ui.intent import DebugIntent, parse_prompt_intent

    assert parse_prompt_intent("/debug") == DebugIntent()


def test_parse_prompt_intent_routes_debug_scopes() -> None:
    from loushang.coding.ui.intent import DebugIntent, parse_prompt_intent

    assert parse_prompt_intent("/debug tui,agent") == DebugIntent(scopes=("tui", "agent"))
    assert parse_prompt_intent("/debug on provider tool") == DebugIntent(scopes=("provider", "tool"))


def test_parse_prompt_intent_routes_debug_off() -> None:
    from loushang.coding.ui.intent import DebugIntent, parse_prompt_intent

    assert parse_prompt_intent("/debug off") == DebugIntent(enabled=False, scopes=())


def test_parse_prompt_intent_routes_status_command() -> None:
    from loushang.coding.ui.intent import StatusIntent, parse_prompt_intent

    assert parse_prompt_intent("/status") == StatusIntent()


def test_parse_prompt_intent_routes_terminal_diagnostics_command() -> None:
    from loushang.coding.ui.intent import TerminalDiagnosticsIntent, parse_prompt_intent

    assert parse_prompt_intent("/terminal") == TerminalDiagnosticsIntent()


def test_parse_prompt_intent_routes_settings_command() -> None:
    from loushang.coding.ui.intent import SettingsIntent, parse_prompt_intent

    assert parse_prompt_intent("/settings") == SettingsIntent()


def test_parse_prompt_intent_routes_models_command() -> None:
    from loushang.coding.ui.intent import ModelsIntent, parse_prompt_intent

    assert parse_prompt_intent("/models") == ModelsIntent()
    assert parse_prompt_intent("/models kimi") == ModelsIntent(query="kimi")


def test_parse_prompt_intent_routes_model_command() -> None:
    from loushang.coding.ui.intent import ModelSelectIntent, parse_prompt_intent

    assert parse_prompt_intent("/model") == ModelSelectIntent()
    assert parse_prompt_intent("/model moonshot/kimi") == ModelSelectIntent(query="moonshot/kimi")


def test_parse_prompt_intent_routes_hotkeys_command() -> None:
    from loushang.coding.ui.intent import HotkeysIntent, parse_prompt_intent

    assert parse_prompt_intent("/hotkeys") == HotkeysIntent()


def test_parse_prompt_intent_routes_statusline_command() -> None:
    from loushang.coding.ui.intent import StatuslineIntent, parse_prompt_intent

    assert parse_prompt_intent("/statusline") == StatuslineIntent()
    assert parse_prompt_intent("/statusline on") == StatuslineIntent(enabled=True)
    assert parse_prompt_intent("/statusline off") == StatuslineIntent(enabled=False)


def test_parse_prompt_intent_routes_commands_command() -> None:
    from loushang.coding.ui.intent import (
        CommandSelectIntent,
        CommandsIntent,
        parse_prompt_intent,
    )

    assert parse_prompt_intent("/commands") == CommandsIntent()
    assert parse_prompt_intent("/commands model") == CommandsIntent(query="model")
    assert parse_prompt_intent("/command") == CommandSelectIntent()
    assert parse_prompt_intent("/command demo") == CommandSelectIntent(query="demo")


def test_parse_prompt_intent_routes_follow_up_command() -> None:
    from loushang.coding.ui.intent import FollowUpIntent, parse_prompt_intent

    assert parse_prompt_intent("/follow continue with tests") == FollowUpIntent(
        text="continue with tests"
    )


def test_controller_dispatches_prompt_intent_to_session_prompt() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent

    session = _Session()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="hello")))

    assert result.error_message is None
    assert session.prompts == ["hello"]


def test_controller_dispatches_catalog_session_command_without_prompting_agent() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent

    class CommandSession(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.commands: list[tuple[str, str]] = []

        def list_commands(self) -> list[object]:
            return [
                SimpleNamespace(
                    name="name",
                    description="Set session display name",
                    source="builtin",
                    argument_hint="<name>",
                )
            ]

        async def execute_command_async(self, invocation_name: str, args: str) -> object:
            self.commands.append((invocation_name, args))
            return SimpleNamespace(
                invocation_name=invocation_name,
                result={
                    "source": "builtin",
                    "command": invocation_name,
                    "status": "ok",
                    "message": "Session name set: Project Alpha",
                },
            )

    session = CommandSession()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="/name Project Alpha")))

    assert result.error_message is None
    assert result.status_message == "Session name set: Project Alpha"
    assert session.commands == [("name", "Project Alpha")]
    assert session.prompts == []


def test_controller_leaves_prompt_resource_commands_on_prompt_path() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent

    class PromptResourceSession(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.commands: list[tuple[str, str]] = []

        def list_commands(self) -> list[object]:
            return [
                SimpleNamespace(
                    name="review",
                    description="Review pull request",
                    source="prompt",
                    argument_hint="<PR-URL>",
                )
            ]

        async def execute_command_async(self, invocation_name: str, args: str) -> object:
            self.commands.append((invocation_name, args))
            return SimpleNamespace(invocation_name=invocation_name, result={"text": "expanded prompt"})

    session = PromptResourceSession()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="/review https://example.test/pr/1")))

    assert result.error_message is None
    assert session.commands == []
    assert session.prompts == ["/review https://example.test/pr/1"]


def test_controller_dispatches_prompt_images_to_session_prompt() -> None:
    from loushang.ai.types import ImagePart
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent

    class ImageSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[ImagePart] | None]] = []

        async def prompt(self, text: str, *, images: list[ImagePart] | None = None) -> None:
            self.calls.append((text, images))

    image = ImagePart(type="image", data="abc", mime_type="image/png")
    session = ImageSession()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="hello", images=(image,))))

    assert result.error_message is None
    assert session.calls == [("hello", [image])]


def test_controller_dispatches_bash_intent_outside_context() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import BashIntent

    session = _Session()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.dispatch(BashIntent(command="pwd")))

    assert result.error_message is None
    assert session.bash_calls == [("pwd", {"exclude_from_context": True})]


def test_controller_dispatches_abort_to_agent_and_bash() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import AbortIntent

    session = _Session()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.dispatch(AbortIntent()))

    assert result.error_message is None
    assert session.aborted is True
    assert session.bash_aborted is True


def test_controller_sends_steering_when_session_supports_it() -> None:
    from loushang.coding.ui.controller import CodingUiController

    session = _Session()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.steer("use a smaller diff"))

    assert result.error_message is None
    assert session.steers == ["use a smaller diff"]


def test_controller_prefers_session_prompt_streaming_behavior_for_steering() -> None:
    from loushang.coding.ui.controller import CodingUiController

    class StreamingPromptSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None, str | None]] = []

        async def prompt(
            self,
            text: str,
            *,
            streaming_behavior: str | None = None,
            source: str | None = None,
        ) -> None:
            self.calls.append((text, streaming_behavior, source))

        async def steer(self, _text: str) -> None:
            raise AssertionError("steer fallback should not be used")

    session = StreamingPromptSession()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.steer("use a smaller diff"))

    assert result.error_message is None
    assert session.calls == [("use a smaller diff", "steer", "interactive")]


def test_controller_reports_when_steering_is_unavailable() -> None:
    from loushang.coding.ui.controller import CodingUiController

    class NoSteerSession:
        pass

    result = asyncio.run(CodingUiController(session=NoSteerSession()).steer("wait"))

    assert result.error_message == "Steering is unavailable for this session."


def test_controller_sends_follow_up_when_session_supports_it() -> None:
    from loushang.coding.ui.controller import CodingUiController

    session = _Session()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.follow_up("continue after this turn"))

    assert result.error_message is None
    assert session.follow_ups == ["continue after this turn"]
    assert session.steers == []


def test_controller_prefers_session_prompt_streaming_behavior_for_follow_up() -> None:
    from loushang.coding.ui.controller import CodingUiController

    class StreamingPromptSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None, str | None]] = []

        async def prompt(
            self,
            text: str,
            *,
            streaming_behavior: str | None = None,
            source: str | None = None,
        ) -> None:
            self.calls.append((text, streaming_behavior, source))

        async def follow_up(self, _text: str) -> None:
            raise AssertionError("follow_up fallback should not be used")

    session = StreamingPromptSession()
    controller = CodingUiController(session=session)

    result = asyncio.run(controller.follow_up("continue after this turn"))

    assert result.error_message is None
    assert session.calls == [("continue after this turn", "followUp", "interactive")]


def test_controller_returns_error_result_without_verbose_traceback() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent

    class FailingSession(_Session):
        async def prompt(self, text: str) -> None:
            raise RuntimeError(f"failed: {text}")

    result = asyncio.run(CodingUiController(session=FailingSession()).dispatch(PromptIntent(text="hello")))

    assert result.error_message == "failed: hello"
    assert result.traceback_text is None


def test_controller_records_problem_for_dispatch_failure() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent
    from loushang.observability import (
        get_problem_store,
        log_context,
        reset_observability,
    )

    class FailingSession(_Session):
        async def prompt(self, text: str) -> None:
            raise RuntimeError(f"failed: {text}")

    reset_observability()
    try:
        with log_context(session_id="session-1", run_id=7, cwd="/repo", mode="tui"):
            result = asyncio.run(CodingUiController(session=FailingSession()).dispatch(PromptIntent(text="hello")))

        records = get_problem_store().all()
        assert result.error_message == "failed: hello"
        assert len(records) == 1
        assert records[0].code == "coding_ui_dispatch_failed"
        assert records[0].source == "agent"
        assert records[0].recoverable is True
        assert records[0].message == "failed: hello"
        assert records[0].details == {"intent": "PromptIntent"}
        assert records[0].exception_type == "RuntimeError"
        assert records[0].session_id == "session-1"
        assert records[0].run_id == 7
        assert records[0].mode == "tui"
    finally:
        reset_observability()


def test_controller_records_problem_for_cancelled_prompt() -> None:
    from loushang.coding.ui.controller import CodingUiController
    from loushang.coding.ui.intent import PromptIntent
    from loushang.observability import get_problem_store, reset_observability

    class CancelledSession(_Session):
        async def prompt(self, text: str) -> None:
            raise asyncio.CancelledError

    reset_observability()
    try:
        result = asyncio.run(CodingUiController(session=CancelledSession()).dispatch(PromptIntent(text="hello")))

        records = get_problem_store().all()
        assert result.error_message == "Request cancelled."
        assert len(records) == 1
        assert records[0].code == "coding_ui_request_cancelled"
        assert records[0].source == "agent"
        assert records[0].recoverable is True
        assert records[0].details == {"intent": "PromptIntent"}
        assert records[0].exception_type == "CancelledError"
    finally:
        reset_observability()
