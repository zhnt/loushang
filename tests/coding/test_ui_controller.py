from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.host.types import HostActionResult


class _Session:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.bash_calls: list[tuple[str, dict[str, object]]] = []
        self.steers: list[str] = []
        self.follow_ups: list[str] = []
        self.aborted = False
        self.bash_aborted = False

    async def prompt(self, text: str, **_kwargs: object) -> None:
        self.prompts.append(text)

    async def execute_bash(self, command: str, **kwargs: object) -> None:
        self.bash_calls.append((command, kwargs))

    def abort(self) -> None:
        self.aborted = True

    def abort_bash(self) -> None:
        self.bash_aborted = True

    def clear_queue(self) -> dict[str, list[str]]:
        return {"steering": [], "follow_up": []}

    async def wait_for_idle(self) -> None:
        return None

    def steer(self, text: str, images=None) -> None:
        del images
        self.steers.append(text)

    def follow_up(self, text: str, images=None) -> None:
        del images
        self.follow_ups.append(text)


def test_parse_conversation_intent_skips_blank_input() -> None:
    from loushang.harnesstui.conversation.intents import parse_conversation_intent

    assert parse_conversation_intent("  \n") is None


def test_parse_conversation_intent_routes_regular_text_to_prompt() -> None:
    from loushang.harnesstui.conversation.intents import (
        PromptIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("hello") == PromptIntent(text="hello")


def test_parse_conversation_intent_routes_bang_bang_to_bash() -> None:
    from loushang.harnesstui.conversation.intents import (
        BashIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("!!  ls -al") == BashIntent(command="ls -al")


def test_parse_conversation_intent_routes_quit_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        QuitIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/quit") == QuitIntent()


def test_parse_conversation_intent_routes_debug_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        DebugIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/debug") == DebugIntent()


def test_parse_conversation_intent_routes_debug_scopes() -> None:
    from loushang.harnesstui.conversation.intents import (
        DebugIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/debug tui,agent") == DebugIntent(scopes=("tui", "agent"))
    assert parse_conversation_intent("/debug on provider tool") == DebugIntent(scopes=("provider", "tool"))


def test_parse_conversation_intent_routes_debug_off() -> None:
    from loushang.harnesstui.conversation.intents import (
        DebugIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/debug off") == DebugIntent(enabled=False, scopes=())


def test_parse_conversation_intent_routes_terminal_diagnostics_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        TerminalDiagnosticsIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/terminal") == TerminalDiagnosticsIntent()


def test_parse_conversation_intent_routes_settings_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        SettingsIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/settings") == SettingsIntent()
    assert parse_conversation_intent("/config") == SettingsIntent()


def test_parse_conversation_intent_routes_models_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        ModelsIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/models") == ModelsIntent()
    assert parse_conversation_intent("/models kimi") == ModelsIntent(query="kimi")


def test_parse_conversation_intent_routes_model_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        ModelSelectIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/model") == ModelSelectIntent()
    assert parse_conversation_intent("/model moonshot/kimi") == ModelSelectIntent(query="moonshot/kimi")


def test_parse_conversation_intent_routes_hotkeys_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        HotkeysIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/hotkeys") == HotkeysIntent()


def test_parse_conversation_intent_routes_commands_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        CommandSelectIntent,
        CommandsIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/commands") == CommandsIntent()
    assert parse_conversation_intent("/commands model") == CommandsIntent(query="model")
    assert parse_conversation_intent("/command") == CommandSelectIntent()
    assert parse_conversation_intent("/command demo") == CommandSelectIntent(query="demo")


def test_parse_conversation_intent_routes_follow_up_command() -> None:
    from loushang.harnesstui.conversation.intents import (
        FollowUpIntent,
        parse_conversation_intent,
    )

    assert parse_conversation_intent("/follow continue with tests") == FollowUpIntent(
        text="continue with tests"
    )


def test_controller_dispatches_prompt_intent_to_session_prompt() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="hello")))

    assert result.error_message is None
    assert session.prompts == ["hello"]


def test_controller_plugins_preview_is_local_and_never_prompts_agent() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    reads: list[str] = []

    def preview() -> dict[str, object]:
        reads.append("current")
        return {
            "snapshotStatus": "partial_evidence",
            "disposition": "blocked",
            "compiledPluginIds": ["coding.base"],
            "catalogResources": [
                {"resourceKind": "skill", "name": "review", "sourceKind": "external_package"}
            ],
            "catalogDiagnosticCodes": ["duplicate_resource_name"],
            "evidenceGaps": ["session_catalog_generation"],
            "blockingOwner": "resource-catalog",
            "blockingCode": "duplicate_owner_contribution_identity",
        }

    controller = build_coding_ui_controller(session=session, plugin_preview=preview)
    result = asyncio.run(controller.dispatch(PromptIntent(text="/plugins")))

    assert reads == ["current"]
    assert session.prompts == []
    assert "partial" in (result.status_message or "")
    assert "coding.base" in (result.status_message or "")
    assert "duplicate_owner_contribution_identity" in (result.status_message or "")


def test_controller_plugin_management_follows_current_session_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.ui.product_binding as binding_module
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = _Session()
    second = _Session()
    first.session_manager = SimpleNamespace(get_cwd=lambda: str(first_root))
    second.session_manager = SimpleNamespace(get_cwd=lambda: str(second_root))
    runtime = SimpleNamespace(current_session=first)
    runtime.get_current_session = lambda: runtime.current_session
    writes: list[Path] = []
    reads: list[Path] = []

    def command(workspace: Path, _text: str) -> HostActionResult:
        writes.append(Path(workspace))
        return HostActionResult(status_message="changed")

    def read_client(workspace: Path):
        reads.append(Path(workspace))
        return SimpleNamespace(preview_current=lambda **_kwargs: {
            "snapshotStatus": "complete",
            "disposition": "admitted",
            "compiledPluginIds": ["coding.base"],
            "catalogResources": [],
            "catalogDiagnosticCodes": [],
            "evidenceGaps": [],
            "blockingOwner": None,
            "blockingCode": None,
        })

    monkeypatch.setattr(
        binding_module, "execute_coding_plugin_management_ui_command", command
    )
    monkeypatch.setattr(
        binding_module, "open_coding_plugin_management_read_client", read_client
    )
    monkeypatch.setattr(
        binding_module, "_format_coding_plugin_preview", lambda _document: "preview"
    )
    controller = build_coding_ui_controller(
        session=first, runtime=runtime, plugin_workspace=first_root
    )
    assert asyncio.run(controller.dispatch(PromptIntent(text="/plugins"))).error_message is None
    assert asyncio.run(controller.dispatch(
        PromptIntent(text="/plugins disable example")
    )).error_message is None
    runtime.current_session = second
    assert asyncio.run(controller.dispatch(PromptIntent(text="/plugins"))).error_message is None
    assert asyncio.run(controller.dispatch(
        PromptIntent(text="/plugins disable example")
    )).error_message is None
    assert reads == [first_root, second_root]
    assert writes == [first_root, second_root]


def test_controller_plugins_reports_selected_command_name_conflict() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    session.list_commands = lambda: [
        SimpleNamespace(name="plugins", source="plugin", description="Other command")
    ]
    controller = build_coding_ui_controller(
        session=session,
        plugin_preview=lambda: {"snapshotStatus": "complete"},
    )
    result = asyncio.run(controller.dispatch(PromptIntent(text="/plugins")))
    assert result.error_message == (
        "/plugins conflicts with a selected Session command."
    )
    assert session.prompts == []


def test_controller_plugins_preview_unavailable_is_local() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    controller = build_coding_ui_controller(session=session)
    result = asyncio.run(controller.dispatch(PromptIntent(text="/plugins")))

    assert result.error_message == "Plugin preview is unavailable."
    assert session.prompts == []

    invalid = asyncio.run(controller.dispatch(PromptIntent(text="/plugins install")))
    assert invalid.error_message == (
        "Usage: /plugins [list | explain OPERATION_ID | enable ID | disable ID | remove ID | repair OPERATION_ID | repair-package ACTION OPERATION_ID]"
    )
    assert session.prompts == []

    attached = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins", images=(object(),)))
    )
    assert attached.error_message == "/plugins does not accept attachments."
    assert session.prompts == []


def test_controller_plugins_list_uses_management_read_without_model_prompt() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    controller = build_coding_ui_controller(
        session=session,
        plugin_management_snapshot=lambda: {
            "projectionVersion": 1,
            "ownerRevisions": {"desiredState": 7},
            "installations": [
                {
                    "installationKey": {"pluginId": "reviewpack"},
                    "desiredState": "installed_enabled",
                    "convergence": "unknown",
                    "unknownDimensions": ["instance"],
                    "backupRetention": {
                        "installationKey": {"pluginId": "reviewpack"},
                        "status": "retained",
                        "expiryReceiptId": None,
                    },
                    "operations": [
                        {"operationId": "tui-plugin-desired:pending", "status": "running"}
                    ],
                }
            ],
            "skew": [],
        },
    )

    result = asyncio.run(controller.dispatch(PromptIntent(text="/plugins list")))

    assert result.error_message is None
    assert "reviewpack: installed_enabled" in (result.status_message or "")
    assert "Desired State revision 7" in (result.status_message or "")
    assert "unknown" in (result.status_message or "")
    assert "backup: retained" in (result.status_message or "")
    assert "tui-plugin-desired:pending" in (result.status_message or "")
    assert session.prompts == []


def test_controller_plugins_list_refuses_foreign_backup_retention() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    controller = build_coding_ui_controller(
        session=session,
        plugin_management_snapshot=lambda: {
            "projectionVersion": 1,
            "ownerRevisions": {"desiredState": 1},
            "installations": [
                {
                    "installationKey": {"pluginId": "reviewpack"},
                    "desiredState": "installed_enabled",
                    "convergence": "converged",
                    "unknownDimensions": [],
                    "backupRetention": {
                        "installationKey": {"pluginId": "another-plugin"},
                        "status": "retained",
                        "expiryReceiptId": None,
                    },
                    "operations": [],
                }
            ],
            "skew": [],
        },
    )

    result = asyncio.run(controller.dispatch(PromptIntent(text="/plugins list")))

    assert result.error_message == "Plugin preview is unavailable."
    assert session.prompts == []


def test_controller_plugins_command_is_local_and_rejects_attachments() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harness.host.types import HostActionResult
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    submitted: list[str] = []

    def command(text: str) -> HostActionResult:
        submitted.append(text)
        return HostActionResult(status_message="Plugin disabled; new Session required.")

    controller = build_coding_ui_controller(session=session, plugin_command=command)
    result = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins disable reviewpack"))
    )

    assert result.status_message == "Plugin disabled; new Session required."
    assert submitted == ["/plugins disable reviewpack"]
    assert session.prompts == []

    attached = asyncio.run(
        controller.dispatch(
            PromptIntent(text="/plugins disable reviewpack", images=(object(),))
        )
    )
    assert attached.error_message == "/plugins does not accept attachments."
    assert submitted == ["/plugins disable reviewpack"]
    assert session.prompts == []


def test_controller_package_repair_runs_locally_without_model_prompt() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harness.host.types import HostActionResult
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    submitted: list[str] = []

    def command(text: str) -> HostActionResult:
        submitted.append(text)
        return HostActionResult(status_message="Package repair committed")

    controller = build_coding_ui_controller(
        session=session, plugin_package_repair_command=command
    )
    result = asyncio.run(controller.dispatch(PromptIntent(
        text="/plugins repair-package repair-retryable package:one"
    )))
    assert result.status_message == "Package repair committed"
    assert submitted == ["/plugins repair-package repair-retryable package:one"]
    assert session.prompts == []


def test_controller_plugins_explain_reads_owner_evidence_without_model_prompt() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    session = _Session()
    explained: list[str] = []

    def explanation(operation_id: str) -> dict[str, object]:
        explained.append(operation_id)
        return {
            "operationId": operation_id,
            "explanationVersion": 1,
            "snapshotStatus": "partial_evidence",
            "package": {
                "operationId": operation_id,
                "status": "observed",
                "phase": "committed",
                "disposition": "committed",
                "failureCode": None,
                "operatorAction": None,
            },
            "managementStatus": "observed",
            "managementDisposition": "succeeded",
            "handoffEvidence": "settled",
            "joinStatus": "same_identity",
            "evidenceGaps": ["product_selection", "session_capture"],
        }

    controller = build_coding_ui_controller(
        session=session, plugin_operation_explanation=explanation
    )
    result = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins explain package:install-1"))
    )
    assert result.error_message is None
    assert "Package: committed / committed" in (result.status_message or "")
    assert "Handoff: settled" in (result.status_message or "")
    assert "partial evidence" in (result.status_message or "")
    assert explained == ["package:install-1"]
    assert session.prompts == []

    attached = asyncio.run(controller.dispatch(PromptIntent(
        text="/plugins explain package:install-1", images=(object(),)
    )))
    assert attached.error_message == "/plugins does not accept attachments."
    assert explained == ["package:install-1"]


def test_controller_dispatches_catalog_session_command_without_prompting_agent() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    class CommandSession(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.commands: list[tuple[str, str]] = []

        def list_commands(self) -> list[object]:
            return [
                SimpleNamespace(
                    name="rename",
                    description="Rename the current session",
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
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(
        controller.dispatch(PromptIntent(text="/rename Project Alpha"))
    )

    assert result.error_message is None
    assert result.status_message == "Session name set: Project Alpha"
    assert session.commands == [("rename", "Project Alpha")]
    assert session.prompts == []


def test_controller_prefers_session_command_display_text_for_status() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    class CommandSession(_Session):
        def list_commands(self) -> list[object]:
            return [
                SimpleNamespace(
                    name="extensions",
                    description="Show loaded extensions and diagnostics",
                    source="builtin",
                )
            ]

        async def execute_command_async(self, invocation_name: str, args: str) -> object:
            return SimpleNamespace(
                invocation_name=invocation_name,
                result={
                    "source": "builtin",
                    "command": invocation_name,
                    "status": "ok",
                    "message": "Extensions: acme.review (standard, 2 surfaces)",
                    "display": "Extensions:\n- acme.review - Acme Review [standard]\n  Surfaces: command acme-review, tool review_lookup",
                },
            )

    controller = build_coding_ui_controller(session=CommandSession())

    result = asyncio.run(controller.dispatch(PromptIntent(text="/extensions")))

    assert result.error_message is None
    assert result.status_message == (
        "Extensions:\n"
        "- acme.review - Acme Review [standard]\n"
        "  Surfaces: command acme-review, tool review_lookup"
    )


def test_controller_dispatches_coding_lsp_session_status_without_model_prompt() -> None:
    from loushang.coding.lsp.commands import (
        execute_lsp_session_command,
        lsp_session_command_descriptor,
    )
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    class LspCommandSession(_Session):
        def list_commands(self) -> list[object]:
            return [lsp_session_command_descriptor()]

        async def execute_command_async(self, invocation_name: str, args: str) -> object:
            assert invocation_name == "lsp"
            return await execute_lsp_session_command(None, args)

    session = LspCommandSession()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="/lsp status")))

    assert result.error_message is None
    assert result.status_message == "LSP session capability: disabled"
    assert session.prompts == []


def test_controller_leaves_prompt_resource_commands_on_prompt_path() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

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
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="/review https://example.test/pr/1")))

    assert result.error_message is None
    assert session.commands == []
    assert session.prompts == ["/review https://example.test/pr/1"]


def test_controller_dispatches_prompt_images_to_session_prompt() -> None:
    from loushang.ai.types import ImagePart
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    class ImageSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[ImagePart] | None]] = []

        async def prompt(
            self,
            text: str,
            *,
            images: list[ImagePart] | None = None,
            **_kwargs: object,
        ) -> None:
            self.calls.append((text, images))

        async def wait_for_idle(self) -> None:
            return None

    image = ImagePart(type="image", data="abc", mime_type="image/png")
    session = ImageSession()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.dispatch(PromptIntent(text="hello", images=(image,))))

    assert result.error_message is None
    assert session.calls == [("hello", [image])]


def test_controller_dispatches_bash_intent_outside_context() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import BashIntent

    session = _Session()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.dispatch(BashIntent(command="pwd")))

    assert result.error_message is None
    assert session.bash_calls == [("pwd", {"exclude_from_context": True})]


def test_controller_does_not_execute_bash_on_a_detached_seed_session() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import BashIntent

    session = _Session()
    runtime = SimpleNamespace(
        get_current_session=lambda: None,
        current_session=session,
    )
    controller = build_coding_ui_controller(session=session, runtime=runtime)

    result = asyncio.run(controller.dispatch(BashIntent(command="pwd")))

    assert result.error_message == "Session runtime requires an active session"
    assert session.bash_calls == []


def test_controller_dispatches_abort_to_agent_and_bash() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import AbortIntent

    session = _Session()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.dispatch(AbortIntent()))

    assert result.error_message is None
    assert session.aborted is True
    assert session.bash_aborted is True


def test_controller_sends_steering_when_session_supports_it() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller

    session = _Session()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.steer("use a smaller diff"))

    assert result.error_message is None
    assert session.steers == ["use a smaller diff"]


def test_controller_uses_shared_session_steering_primitive() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller

    class SteeringSession:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def steer(self, text: str, images=None) -> None:
            del images
            self.calls.append(text)

    session = SteeringSession()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.steer("use a smaller diff"))

    assert result.error_message is None
    assert session.calls == ["use a smaller diff"]


def test_controller_does_not_mask_attribute_error_as_unavailable() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller

    class BrokenSteerSession:
        def steer(self, text: str, images=None) -> None:
            del text, images
            raise AttributeError("steering implementation bug")

    result = asyncio.run(
        build_coding_ui_controller(session=BrokenSteerSession()).steer("wait")
    )

    assert result.error_message == "steering implementation bug"


def test_controller_sends_follow_up_when_session_supports_it() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller

    session = _Session()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.follow_up("continue after this turn"))

    assert result.error_message is None
    assert session.follow_ups == ["continue after this turn"]
    assert session.steers == []


def test_controller_uses_shared_session_follow_up_primitive() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller

    class FollowUpSession:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def follow_up(self, text: str, images=None) -> None:
            del images
            self.calls.append(text)

    session = FollowUpSession()
    controller = build_coding_ui_controller(session=session)

    result = asyncio.run(controller.follow_up("continue after this turn"))

    assert result.error_message is None
    assert session.calls == ["continue after this turn"]


def test_controller_returns_error_result_without_verbose_traceback() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    class FailingSession(_Session):
        async def prompt(self, text: str, **_kwargs: object) -> None:
            raise RuntimeError(f"failed: {text}")

    result = asyncio.run(build_coding_ui_controller(session=FailingSession()).dispatch(PromptIntent(text="hello")))

    assert result.error_message == "failed: hello"
    assert result.traceback_text is None


def test_controller_records_problem_for_dispatch_failure() -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.foundation.observability import log_context
    from loushang.foundation.observability._router import (
        get_problem_store,
        reset_observability,
    )
    from loushang.harnesstui.conversation.intents import PromptIntent

    class FailingSession(_Session):
        async def prompt(self, text: str, **_kwargs: object) -> None:
            raise RuntimeError(f"failed: {text}")

    reset_observability()
    try:
        with log_context(session_id="session-1", run_id=7, cwd="/repo", mode="tui"):
            result = asyncio.run(build_coding_ui_controller(session=FailingSession()).dispatch(PromptIntent(text="hello")))

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
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.foundation.observability._router import (
        get_problem_store,
        reset_observability,
    )
    from loushang.harnesstui.conversation.intents import PromptIntent

    class CancelledSession(_Session):
        async def prompt(self, text: str, **_kwargs: object) -> None:
            raise asyncio.CancelledError

    reset_observability()
    try:
        result = asyncio.run(build_coding_ui_controller(session=CancelledSession()).dispatch(PromptIntent(text="hello")))

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
