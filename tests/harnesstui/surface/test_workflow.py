from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from types import SimpleNamespace

from loushang.harness.commands import CommandDef, CommandKind
from loushang.harness.continuity import ContinuityTarget
from loushang.harnesstui.settings.workflow import SettingsApplyResult
from loushang.harnesstui.status.line import StatusLineSettings
from loushang.harnesstui.surface.controller import ApprovalSurfaceDecision
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.harnesstui.surface.workflow import (
    ScreenSurfaceCommand,
    ScreenSurfaceForkResult,
    ScreenSurfaceWorkflow,
    ScreenSurfaceWorkflowCopy,
    ScreenSurfaceWorkflowPorts,
)
from loushang.tui import InfoPanel, InputIntent, RenderRequestKind, SurfaceHost


class _Catalog:
    def __init__(self) -> None:
        self.definitions = {
            name: CommandDef(
                id=f"product.{name}",
                name=name,
                kind=CommandKind.LOCAL_UI,
            )
            for name in (
                "model",
                "models",
                "command",
                "commands",
                "terminal",
                "hotkeys",
                "settings",
                "agents",
                "permissions",
                "btw",
            )
        }

    def lookup(self, text: str) -> CommandDef | None:
        name = text.strip().split(maxsplit=1)[0].removeprefix("/")
        return self.definitions.get(name)

    def commands(self) -> tuple[CommandDef, ...]:
        return tuple(self.definitions.values())


@dataclass(slots=True)
class _State:
    statuses: list[str] = field(default_factory=list)
    command_texts: list[str] = field(default_factory=list)
    model_values: list[str] = field(default_factory=list)
    approvals: list[ApprovalSurfaceDecision | None] = field(default_factory=list)
    resumed_sessions: list[str] = field(default_factory=list)
    deleted_sessions: list[str] = field(default_factory=list)
    forked_entries: list[str] = field(default_factory=list)
    renamed_sessions: list[str | None] = field(default_factory=list)
    side_questions: list[str] = field(default_factory=list)
    permission_actions: list[str] = field(default_factory=list)
    statusline_visible: list[bool] = field(default_factory=list)
    statusline_settings: list[StatusLineSettings] = field(default_factory=list)
    model_refreshes: int = 0
    renders: int = 0
    fail_model: bool = False
    accept_approval: bool = True


@dataclass(slots=True)
class _Composer:
    state: _State

    def set_text(self, text: str) -> None:
        self.state.command_texts.append(text)


@dataclass(slots=True)
class _App:
    state: _State
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None
    composer: _Composer = field(init=False)

    def __post_init__(self) -> None:
        self.composer = _Composer(self.state)

    def set_status(self, message: str | None) -> None:
        if message is not None:
            self.state.statuses.append(message)

    def set_statusline_visible(self, visible: bool) -> None:
        self.state.statusline_visible.append(visible)

    def set_statusline_settings(self, settings: StatusLineSettings) -> None:
        self.state.statusline_settings.append(settings)

    def request_render(self, kind: RenderRequestKind = "product") -> None:
        assert kind == "product"
        self.state.renders += 1


class _SettingsPage:
    async def apply_setting(self, item_id: str, value: str) -> SettingsApplyResult:
        assert (item_id, value) == ("model.current", "provider/beta")
        return SettingsApplyResult(
            "selected",
            statusline_settings=StatusLineSettings(style="muted"),
            refresh_model_label=True,
        )


def _surface(title: str, purpose: str) -> ScreenSurfaceView:
    return ScreenSurfaceView(
        title=title,
        purpose=purpose,  # type: ignore[arg-type]
        content=InfoPanel(title=title, text="body"),
        presentation="bottom-exclusive",
    )


def _normalize(text: str, command: CommandDef) -> ScreenSurfaceCommand:
    query = text.strip().partition(" ")[2]
    kinds = {
        "model": "select_model",
        "models": "list_models",
        "command": "select_command",
        "commands": "list_commands",
        "terminal": "terminal_diagnostics",
        "hotkeys": "hotkeys",
        "settings": "settings",
        "agents": "agent_tree",
        "permissions": "permissions",
        "btw": "side_question",
    }
    if command.name == "command" and query:
        query = f"/{query.removeprefix('/')}"
    return ScreenSurfaceCommand(kinds[command.name], query)  # type: ignore[arg-type]


def _workflow(
    *,
    state: _State | None = None,
    workflow_type: type[ScreenSurfaceWorkflow] = ScreenSurfaceWorkflow,
) -> tuple[ScreenSurfaceWorkflow, _State]:
    state = state or _State()

    async def select_model(value: str) -> str:
        state.model_values.append(value)
        if state.fail_model:
            raise RuntimeError("catalog offline")
        return f"selected:{value}"

    async def refresh_model() -> None:
        state.model_refreshes += 1

    async def format_models(query: str) -> str:
        return f"models:{query}"

    async def format_commands(query: str) -> str:
        return f"commands:{query}"

    async def model_selector() -> ScreenSurfaceView:
        return _surface("Choose model", "model")

    async def command_selector() -> ScreenSurfaceView:
        return _surface("Choose command", "command")

    async def settings_content() -> object:
        return _SettingsPage()

    def resume_surface() -> ScreenSurfaceView:
        return _surface("Resume session", "session")

    async def activate_continuity(target: object) -> str:
        reference = str(target)
        state.resumed_sessions.append(reference)
        return f"resumed:{reference}"

    delete_target = ContinuityTarget(
        provider_id="coding.sessions",
        opaque_id="session-1",
        revision="1",
    )

    def delete_surface() -> ScreenSurfaceView:
        return ScreenSurfaceView(
            title="Delete session",
            purpose="delete",
            content=SimpleNamespace(
                selected_target=delete_target,
                selected_summary=SimpleNamespace(title="Parser review"),
            ),
            presentation="bottom-exclusive",
        )

    async def delete_continuity(target: object) -> str:
        reference = str(getattr(target, "opaque_id", target))
        state.deleted_sessions.append(reference)
        return f"deleted:{reference}"

    def fork_surface() -> ScreenSurfaceView:
        return _surface("Fork prompt", "fork")

    async def fork_session(target: object) -> ScreenSurfaceForkResult:
        entry_id = str(target)
        state.forked_entries.append(entry_id)
        return ScreenSurfaceForkResult(
            status=f"forked:{entry_id}",
            composer_text="selected prompt",
        )

    def rename_surface() -> ScreenSurfaceView:
        return _surface("Rename session", "rename")

    async def rename_session(name: str | None) -> str:
        state.renamed_sessions.append(name)
        return f"renamed:{name}"

    async def decide_approval(
        decision: ApprovalSurfaceDecision | None,
    ) -> bool | None:
        state.approvals.append(decision)
        return state.accept_approval

    def side_question_surface(question: str) -> ScreenSurfaceView:
        state.side_questions.append(question)
        return _surface("BTW", "dialog")

    def agent_tree_surface() -> ScreenSurfaceView:
        return _surface("Agents", "agent_tree")

    def permissions_surface() -> ScreenSurfaceView:
        return _surface("Permissions", "permissions")

    async def apply_permission_action(action: str) -> bool:
        state.permission_actions.append(action)
        return True

    workflow = workflow_type(
        app=_App(state),
        ports=ScreenSurfaceWorkflowPorts(
            select_model=select_model,
            refresh_model_label=refresh_model,
            command_catalog=_Catalog(),
            normalize_command=_normalize,
            format_models=format_models,
            models_info_body=lambda text: f"body<{text}>",
            format_commands=format_commands,
            build_model_selector=model_selector,
            build_command_selector=command_selector,
            build_settings_content=settings_content,
            terminal_diagnostics=lambda: "terminal body",
            hotkeys=lambda: "hotkeys body",
            decide_approval=decide_approval,
            normalize_interactive_command=lambda text: (
                ScreenSurfaceCommand("resume_session")
                if text.strip() == "/resume"
                else (
                    ScreenSurfaceCommand("fork_session")
                    if text.strip() == "/fork"
                    else (
                        ScreenSurfaceCommand("rename_session")
                        if text.strip() == "/rename"
                        else (
                            ScreenSurfaceCommand("delete_session")
                            if text.strip() == "/delete"
                            else None
                        )
                    )
                )
            ),
            build_resume_surface=resume_surface,
            activate_continuity=activate_continuity,
            build_delete_surface=delete_surface,
            delete_continuity=delete_continuity,
            build_fork_surface=fork_surface,
            fork_session=fork_session,
            build_rename_surface=rename_surface,
            rename_session=rename_session,
            build_agent_tree_surface=agent_tree_surface,
            build_permissions_surface=permissions_surface,
            apply_permission_action=apply_permission_action,
            build_side_question_surface=side_question_surface,
        ),
        copy=ScreenSurfaceWorkflowCopy(
            recoverable_error=lambda error: f"recoverable:{error}",
            command_selected=lambda command: f"command:{command}",
            approval_stale="stale",
            approval_confirmed=lambda action: f"approved:{action}",
            approval_rejected="rejected",
            models_title="Models title",
            commands_title="Commands title",
            terminal_title="Terminal title",
            hotkeys_title="Hotkeys title",
            settings_title="Settings title",
        ),
    )
    return workflow, state


def test_surface_workflow_confirms_before_deleting_a_continuity_item() -> None:
    workflow, state = _workflow()

    asyncio.run(workflow.handle_text("/delete"))
    assert isinstance(workflow.current, ScreenSurfaceView)
    assert workflow.current.purpose == "delete"

    asyncio.run(workflow.handle_intent(InputIntent(kind="select")))
    assert isinstance(workflow.current, ScreenSurfaceView)
    assert workflow.current.title == "Delete session"

    asyncio.run(workflow.handle_intent(InputIntent(kind="dialog_confirm")))
    assert state.deleted_sessions == ["session-1"]
    assert state.statuses[-1] == "deleted:session-1"
    assert isinstance(workflow.current, ScreenSurfaceView)
    assert workflow.current.purpose == "delete"


def test_delete_workflow_does_not_collide_with_a_product_delete_callback() -> None:
    class _ProductWorkflow(ScreenSurfaceWorkflow):
        async def _delete_continuity(self, _target: object) -> str:
            return "product deletion callback"

    workflow, state = _workflow(workflow_type=_ProductWorkflow)

    asyncio.run(workflow.handle_text("/delete"))
    asyncio.run(workflow.handle_intent(InputIntent(kind="select")))
    asyncio.run(workflow.handle_intent(InputIntent(kind="dialog_confirm")))

    assert state.deleted_sessions == ["session-1"]


def test_surface_workflow_opens_and_submits_session_rename() -> None:
    workflow, state = _workflow()

    asyncio.run(workflow.handle_text("/rename"))
    surface = workflow.current
    assert isinstance(surface, ScreenSurfaceView)
    assert surface.purpose == "rename"

    asyncio.run(
        workflow.handle_intent(InputIntent(kind="select", text="Project Alpha"))
    )

    assert workflow.current is None
    assert state.renamed_sessions == ["Project Alpha"]
    assert state.statuses == ["renamed:Project Alpha"]


def test_surface_workflow_routes_product_normalized_commands_and_copy() -> None:
    workflow, state = _workflow()

    assert workflow.is_local_command("/missing") is False
    assert workflow.is_local_command("/command inspect") is True
    asyncio.run(workflow.handle_text("/command inspect"))

    assert state.command_texts == ["/inspect "]
    assert state.statuses == ["command:/inspect"]

    asyncio.run(workflow.handle_text("/models beta"))
    surface = workflow.current
    assert isinstance(surface, ScreenSurfaceView)
    assert surface.title == "Models title"
    assert surface.presentation == "bottom-exclusive"
    assert isinstance(surface.content, InfoPanel)
    assert surface.content.text == "body<models:beta>"

    asyncio.run(workflow.handle_text("/terminal"))
    surface = workflow.current
    assert isinstance(surface, ScreenSurfaceView)
    assert surface.title == "Terminal title"
    assert isinstance(surface.content, InfoPanel)
    assert surface.content.text == "terminal body"


def test_surface_workflow_applies_model_and_keeps_recoverable_error_surface_open() -> (
    None
):
    state = _State(fail_model=True)
    workflow, _ = _workflow(state=state)
    asyncio.run(workflow.handle_text("/model"))
    model_surface = workflow.current

    asyncio.run(
        workflow.handle_surface_intent(InputIntent(kind="select", text="provider/beta"))
    )

    assert workflow.current is model_surface
    assert state.statuses == ["recoverable:catalog offline"]
    assert state.model_refreshes == 0

    state.fail_model = False
    asyncio.run(
        workflow.handle_surface_intent(InputIntent(kind="select", text="provider/beta"))
    )

    assert workflow.current is None
    assert state.statuses[-1] == "selected:provider/beta"
    assert state.model_refreshes == 1


def test_surface_workflow_applies_settings_effects_without_closing_page() -> None:
    workflow, state = _workflow()
    asyncio.run(workflow.handle_text("/settings"))
    settings_surface = workflow.current

    asyncio.run(
        workflow.handle_surface_intent(
            InputIntent(kind="setting", text="model.current", note="provider/beta")
        )
    )

    assert workflow.current is settings_surface
    assert state.statusline_settings == [StatusLineSettings(style="muted")]
    assert state.model_refreshes == 1
    assert state.renders == 1


def test_surface_workflow_opens_resume_picker_and_submits_reference() -> None:
    workflow, state = _workflow()

    assert workflow.is_local_command("/resume") is True
    assert workflow.is_local_command("/resume abc123") is False
    asyncio.run(workflow.handle_text("/resume"))

    picker = workflow.current
    assert isinstance(picker, ScreenSurfaceView)
    assert picker.purpose == "session"

    asyncio.run(
        workflow.handle_surface_intent(
            InputIntent(kind="select", text="/tmp/session.jsonl")
        )
    )

    assert state.resumed_sessions == ["/tmp/session.jsonl"]
    assert state.statuses == ["resumed:/tmp/session.jsonl"]
    assert workflow.current is None


def test_surface_workflow_routes_btw_as_an_immediate_side_question() -> None:
    workflow, state = _workflow()

    assert workflow.is_local_command("/btw why now?") is True
    asyncio.run(workflow.handle_text("/btw why now?"))

    surface = workflow.current
    assert isinstance(surface, ScreenSurfaceView)
    assert surface.title == "BTW"
    assert state.side_questions == ["why now?"]

    workflow.close()
    asyncio.run(workflow.handle_text("/btw"))
    assert state.statuses[-1] == "Usage: /btw <question>"


def test_surface_workflow_opens_agent_tree_page() -> None:
    workflow, _ = _workflow()

    assert workflow.is_local_command("/agents") is True
    asyncio.run(workflow.handle_text("/agents"))

    surface = workflow.current
    assert isinstance(surface, ScreenSurfaceView)
    assert surface.title == "Agents"
    assert surface.purpose == "agent_tree"


def test_surface_workflow_opens_fork_picker_and_restores_selected_prompt() -> None:
    workflow, state = _workflow()

    assert workflow.is_local_command("/fork") is True
    assert workflow.is_local_command("/fork entry-1 before") is False
    asyncio.run(workflow.handle_text("/fork"))

    picker = workflow.current
    assert isinstance(picker, ScreenSurfaceView)
    assert picker.purpose == "fork"

    asyncio.run(
        workflow.handle_surface_intent(InputIntent(kind="select", text="entry-1"))
    )

    assert state.forked_entries == ["entry-1"]
    assert state.command_texts == ["selected prompt"]
    assert state.statuses == ["forked:entry-1"]
    assert workflow.current is None


def test_surface_workflow_runs_continuity_activation_without_freezing_page() -> None:
    class _ActivationContent:
        selected_target = "typed-target"

        def __init__(self) -> None:
            self.activating = False
            self.closed = False
            self.failure: Exception | None = None

        def begin_activation(self) -> bool:
            if self.activating:
                return False
            self.activating = True
            return True

        def fail_activation(self, error: Exception) -> None:
            self.activating = False
            self.failure = error

        def close(self) -> None:
            self.closed = True

    async def scenario() -> None:
        workflow, state = _workflow()
        gate = asyncio.Event()

        async def activate(target: object) -> str:
            assert target == "typed-target"
            await gate.wait()
            return "resumed:typed-target"

        workflow.ports = replace(workflow.ports, activate_continuity=activate)
        content = _ActivationContent()
        picker = ScreenSurfaceView(
            title="Resume",
            purpose="session",
            content=content,
            presentation="page",
        )
        workflow.open(picker)

        await workflow.handle_surface_intent(
            InputIntent(kind="select", text="opaque-render-value")
        )

        assert workflow.current is picker
        assert content.activating is True
        assert state.statuses == []

        gate.set()
        task = workflow._session_activation_task
        assert task is not None
        await task

        assert workflow.current is None
        assert content.closed is True
        assert state.statuses == ["resumed:typed-target"]

    asyncio.run(scenario())


def test_surface_workflow_keeps_continuity_failure_visible_on_page() -> None:
    class _ActivationContent:
        selected_target = "typed-target"

        def __init__(self) -> None:
            self.failure: Exception | None = None

        def begin_activation(self) -> bool:
            return True

        def fail_activation(self, error: Exception) -> None:
            self.failure = error

    async def scenario() -> None:
        workflow, state = _workflow()

        async def fail(_target: object) -> str:
            raise RuntimeError("restore failed")

        workflow.ports = replace(workflow.ports, activate_continuity=fail)
        content = _ActivationContent()
        picker = ScreenSurfaceView(
            title="Resume",
            purpose="session",
            content=content,
            presentation="page",
        )
        workflow.open(picker)

        await workflow.handle_surface_intent(
            InputIntent(kind="select", text="opaque-render-value")
        )
        task = workflow._session_activation_task
        assert task is not None
        await task

        assert workflow.current is picker
        assert isinstance(content.failure, RuntimeError)
        assert state.statuses == ["recoverable:restore failed"]

    asyncio.run(scenario())


def test_surface_workflow_keeps_fork_failure_visible_on_page() -> None:
    class _ActivationContent:
        selected_entry_id = "entry-1"

        def __init__(self) -> None:
            self.failure: Exception | None = None

        def begin_activation(self) -> bool:
            return True

        def fail_activation(self, error: Exception) -> None:
            self.failure = error

    async def scenario() -> None:
        workflow, state = _workflow()

        async def fail(_target: object) -> ScreenSurfaceForkResult:
            raise RuntimeError("fork failed")

        workflow.ports = replace(workflow.ports, fork_session=fail)
        content = _ActivationContent()
        picker = ScreenSurfaceView(
            title="Fork",
            purpose="fork",
            content=content,
            presentation="page",
        )
        workflow.open(picker)

        await workflow.handle_surface_intent(
            InputIntent(kind="select", text="opaque-render-value")
        )
        task = workflow._fork_activation_task
        assert task is not None
        await task

        assert workflow.current is picker
        assert isinstance(content.failure, RuntimeError)
        assert state.statuses == ["recoverable:fork failed"]

    asyncio.run(scenario())


def test_surface_workflow_adapts_approval_decision_and_product_status_copy() -> None:
    state = _State(accept_approval=False)
    workflow, _ = _workflow(state=state)
    workflow.open_approval(action="delete cache", action_id="approval-1")

    asyncio.run(
        workflow.handle_surface_intent(
            InputIntent(kind="approval_decision", text="allow_once")
        )
    )

    assert state.approvals == [
        ApprovalSurfaceDecision(
            action_id="approval-1",
            action="delete cache",
            outcome="allow_once",
            raw_note="approval-1",
        )
    ]
    assert state.statuses == ["stale"]
    assert workflow.current is None


def test_surface_workflow_opens_and_applies_session_permissions() -> None:
    workflow, state = _workflow()

    asyncio.run(workflow.handle_text("/permissions"))

    assert isinstance(workflow.current, ScreenSurfaceView)
    assert workflow.current.purpose == "permissions"

    asyncio.run(
        workflow.handle_intent(InputIntent(kind="select", text="revoke:grant-1"))
    )

    assert state.permission_actions == ["revoke:grant-1"]
    assert state.statuses[-1] == "Session permission revoked."
