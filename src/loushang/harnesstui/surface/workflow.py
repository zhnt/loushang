from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from loushang.harness.commands import CommandDef, CommandKind
from loushang.harness.continuity import ContinuityTarget
from loushang.harnesstui.conversation.intents import (
    CommandSelectIntent,
    CommandsIntent,
    HotkeysIntent,
    ModelSelectIntent,
    ModelsIntent,
    SettingsIntent,
    TerminalDiagnosticsIntent,
    parse_conversation_intent,
)
from loushang.harnesstui.settings.workflow import SettingsApplyResult
from loushang.harnesstui.status.line import StatusLineSettings
from loushang.harnesstui.surface.controller import (
    ApprovalSurfaceDecision,
    ScreenSurfaceAppPort,
    ScreenSurfaceCoordinator,
)
from loushang.harnesstui.surface.factory import info_surface_view
from loushang.harnesstui.surface.view import (
    ScreenSurfacePresentation,
    ScreenSurfaceView,
)
from loushang.tui import ApprovalChoice, InputIntent, RenderRequestKind

ScreenSurfaceCommandKind = Literal[
    "select_model",
    "list_models",
    "select_command",
    "list_commands",
    "resume_session",
    "delete_session",
    "fork_session",
    "rename_session",
    "agent_tree",
    "permissions",
    "side_question",
    "terminal_diagnostics",
    "hotkeys",
    "settings",
]

ModelSelectionHandler = Callable[[str], Awaitable[str]]
ModelLabelRefresher = Callable[[], Awaitable[None]]
ApprovalDecisionHandler = Callable[
    [ApprovalSurfaceDecision | None], Awaitable[bool | None]
]


class ScreenSurfaceCommandCatalog(Protocol):
    def lookup(self, text: str) -> CommandDef | None: ...

    def commands(self) -> tuple[CommandDef, ...]: ...


class ScreenSurfaceComposerPort(Protocol):
    """Composer effect used by command-selection surfaces."""

    def set_text(self, text: str) -> None: ...


class ScreenSurfaceWorkflowAppPort(ScreenSurfaceAppPort, Protocol):
    """Generic screen-app effects owned by the shared surface workflow."""

    @property
    def composer(self) -> ScreenSurfaceComposerPort: ...

    def set_status(self, message: str | None) -> None: ...

    def set_statusline_visible(self, visible: bool) -> None: ...

    def set_statusline_settings(self, settings: StatusLineSettings) -> None: ...

    def request_render(self, kind: RenderRequestKind = "product") -> None: ...


@dataclass(frozen=True, slots=True)
class ScreenSurfaceCommand:
    """Product-normalized local command consumed by the surface host."""

    kind: ScreenSurfaceCommandKind
    query: str = ""


@dataclass(frozen=True, slots=True)
class ScreenSurfaceForkResult:
    """Effects produced after a Product forks one selected prompt."""

    status: str
    composer_text: str | None = None


@dataclass(frozen=True, slots=True)
class ScreenSurfaceWorkflowCopy:
    """Product copy used by the shared surface interaction workflow."""

    recoverable_error: Callable[[Exception], str]
    command_selected: Callable[[str], str]
    approval_stale: str
    approval_confirmed: Callable[[str | None], str]
    approval_rejected: str
    models_title: str
    commands_title: str
    terminal_title: str
    hotkeys_title: str
    settings_title: str
    approval_aborted: str = "Turn stopped"
    model_selection_recovery_hint: Callable[[Exception], str] = (
        lambda _error: "Choose another model, or press Esc to keep the current model."
    )


STANDARD_SCREEN_SURFACE_WORKFLOW_COPY = ScreenSurfaceWorkflowCopy(
    recoverable_error=lambda error: (
        f"Error: {str(error).strip() or error.__class__.__name__}"
    ),
    command_selected=lambda command: f"Command selected: {command}",
    approval_stale="Approval request is no longer pending",
    approval_confirmed=lambda action: f"Action confirmed: {action}",
    approval_rejected="Action rejected",
    models_title="Available Models",
    commands_title="Commands",
    terminal_title="Terminal",
    hotkeys_title="Hotkeys",
    settings_title="Settings",
    model_selection_recovery_hint=lambda error: (
        _image_model_selection_recovery_hint()
        if _is_image_capability_error(error)
        else "Choose another model, or press Esc to keep the current model."
    ),
)


def _is_image_capability_error(error: Exception) -> bool:
    info = getattr(error, "info", None)
    details = getattr(info, "details", None)
    return isinstance(details, Mapping) and details.get("capability") == "image_input"


def _image_model_selection_recovery_hint() -> str:
    return (
        "To use it: Esc, then /new, or /fork and select the image prompt (or an "
        "earlier one). /compact works only after the image leaves recent context "
        "(~32K tokens by default)."
    )


@dataclass(frozen=True, slots=True)
class ScreenSurfaceWorkflowPorts:
    """Product effects required by generic surface submissions."""

    select_model: ModelSelectionHandler
    refresh_model_label: ModelLabelRefresher
    command_catalog: ScreenSurfaceCommandCatalog
    normalize_command: Callable[[str, CommandDef], ScreenSurfaceCommand | None]
    format_models: Callable[[str], Awaitable[str]]
    models_info_body: Callable[[str], str]
    format_commands: Callable[[str], Awaitable[str]]
    build_model_selector: Callable[[], Awaitable[ScreenSurfaceView]]
    build_command_selector: Callable[[], Awaitable[ScreenSurfaceView]]
    build_settings_content: Callable[[], Awaitable[object]]
    terminal_diagnostics: Callable[[], str]
    hotkeys: Callable[[], str]
    decide_approval: ApprovalDecisionHandler | None = None
    normalize_interactive_command: (
        Callable[[str], ScreenSurfaceCommand | None] | None
    ) = None
    build_resume_surface: Callable[[], ScreenSurfaceView] | None = None
    activate_continuity: Callable[[object], Awaitable[str]] | None = None
    build_delete_surface: Callable[[], ScreenSurfaceView] | None = None
    delete_continuity: Callable[[object], Awaitable[str]] | None = None
    build_fork_surface: Callable[[], ScreenSurfaceView] | None = None
    fork_session: Callable[[object], Awaitable[ScreenSurfaceForkResult]] | None = None
    build_rename_surface: Callable[[], ScreenSurfaceView] | None = None
    rename_session: Callable[[str | None], Awaitable[str]] | None = None
    build_agent_tree_surface: Callable[[], ScreenSurfaceView] | None = None
    build_permissions_surface: Callable[[], ScreenSurfaceView] | None = None
    apply_permission_action: Callable[[str], Awaitable[bool]] | None = None
    build_side_question_surface: Callable[[str], ScreenSurfaceView] | None = None


@dataclass(slots=True)
class ScreenSurfaceWorkflow:
    """Run product-neutral submit, close, and approval surface mechanics."""

    app: ScreenSurfaceWorkflowAppPort
    ports: ScreenSurfaceWorkflowPorts
    copy: ScreenSurfaceWorkflowCopy
    request_render_reason: RenderRequestKind = "product"
    coordinator: ScreenSurfaceCoordinator = field(init=False)
    _surface_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _session_activation_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _fork_activation_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.coordinator = ScreenSurfaceCoordinator(
            app=self.app,
            handlers={
                "model": self._handle_model_submit,
                "command": self._handle_command_submit,
                "settings": self._handle_settings_submit,
                "session": self._handle_session_submit,
                "delete": self._handle_delete_submit,
                "fork": self._handle_fork_submit,
                "rename": self._handle_rename_submit,
                "dialog": self._handle_dialog_submit,
                "approval": self._handle_approval_submit,
                "permissions": self._handle_permission_submit,
            },
        )

    @property
    def current(self) -> ScreenSurfaceView | object | None:
        return self.coordinator.current

    async def handle_intent(self, intent: InputIntent) -> int | None:
        return await self.coordinator.handle_intent(intent)

    async def handle_surface_intent(self, intent: InputIntent) -> int | None:
        return await self.handle_intent(intent)

    def is_local_command(self, text: str) -> bool:
        return self._resolve_command(text) is not None

    async def handle_text(self, text: str) -> int | None:
        command = self._resolve_command(text)
        if command is None:
            return None
        if command.kind == "select_model":
            if command.query.strip():
                await self.select_model(command.query, close_surface=False)
            else:
                self.open(await self.ports.build_model_selector())
        elif command.kind == "list_models":
            models = await self.ports.format_models(command.query)
            self.open_info(
                title=self.copy.models_title,
                text=self.ports.models_info_body(models),
                presentation="bottom-exclusive",
            )
        elif command.kind == "select_command":
            if command.query.strip():
                self.select_command(command.query, close_surface=False)
            else:
                self.open(await self.ports.build_command_selector())
        elif command.kind == "list_commands":
            self.open_info(
                title=self.copy.commands_title,
                text=await self.ports.format_commands(command.query),
                presentation="bottom",
            )
        elif (
            command.kind == "resume_session"
            and self.ports.build_resume_surface is not None
        ):
            try:
                picker = self.ports.build_resume_surface()
            except Exception as error:
                self.app.set_status(self.copy.recoverable_error(error))
            else:
                self.open(picker)
        elif (
            command.kind == "delete_session"
            and self.ports.build_delete_surface is not None
        ):
            try:
                picker = self.ports.build_delete_surface()
            except Exception as error:
                self.app.set_status(self.copy.recoverable_error(error))
            else:
                self.open(picker)
        elif (
            command.kind == "fork_session" and self.ports.build_fork_surface is not None
        ):
            try:
                picker = self.ports.build_fork_surface()
            except Exception as error:
                self.app.set_status(self.copy.recoverable_error(error))
            else:
                self.open(picker)
        elif (
            command.kind == "rename_session"
            and self.ports.build_rename_surface is not None
        ):
            try:
                surface = self.ports.build_rename_surface()
            except Exception as error:
                self.app.set_status(self.copy.recoverable_error(error))
            else:
                self.open(surface)
        elif command.kind == "agent_tree":
            if self.ports.build_agent_tree_surface is None:
                self.app.set_status("Agent collaboration is not available.")
            else:
                try:
                    surface = self.ports.build_agent_tree_surface()
                except Exception as error:
                    self.app.set_status(self.copy.recoverable_error(error))
                else:
                    self.open(surface)
        elif command.kind == "permissions":
            if self.ports.build_permissions_surface is None:
                self.app.set_status("Session permissions are not available.")
            else:
                try:
                    surface = self.ports.build_permissions_surface()
                except Exception as error:
                    self.app.set_status(self.copy.recoverable_error(error))
                else:
                    self.open(surface)
        elif command.kind == "side_question":
            question = command.query.strip()
            if not question:
                self.app.set_status("Usage: /btw <question>")
            elif self.ports.build_side_question_surface is None:
                self.app.set_status("Side questions are not available.")
            else:
                try:
                    surface = self.ports.build_side_question_surface(question)
                except Exception as error:
                    self.app.set_status(self.copy.recoverable_error(error))
                else:
                    self.open(surface)
        elif command.kind == "terminal_diagnostics":
            self.open_info(
                title=self.copy.terminal_title,
                text=self.ports.terminal_diagnostics(),
                presentation="bottom",
            )
        elif command.kind == "hotkeys":
            self.open_info(
                title=self.copy.hotkeys_title,
                text=self.ports.hotkeys(),
                presentation="bottom",
            )
        elif command.kind == "settings":
            self.open_settings(
                title=self.copy.settings_title,
                content=await self.ports.build_settings_content(),
                presentation="bottom-exclusive",
                preferred_height=24,
            )
        return None

    async def select_model(self, value: str, *, close_surface: bool) -> None:
        try:
            message = await self.ports.select_model(value)
        except Exception as error:
            message = self.copy.recoverable_error(error)
            current = self.current
            if (
                close_surface
                and isinstance(current, ScreenSurfaceView)
                and current.purpose == "model"
            ):
                current.feedback = message
                current.feedback_hint = self.copy.model_selection_recovery_hint(error)
                current.preferred_height = max(current.preferred_height or 0, 20)
            self.app.set_status(message)
            return
        if close_surface:
            self.close()
        await self.ports.refresh_model_label()
        self.app.set_status(message)

    def select_command(self, value: str, *, close_surface: bool) -> None:
        command = value.strip()
        if command:
            self.app.composer.set_text(command + " ")
            self.app.set_status(self.copy.command_selected(command))
        if close_surface:
            self.close()

    def open(self, view: ScreenSurfaceView) -> None:
        self._close_surface_content()
        self.coordinator.open(view)
        starter = getattr(view.content, "start", None)
        if callable(starter):
            self._surface_task = asyncio.create_task(self._run_surface_starter(starter))

    def open_info(
        self,
        *,
        title: str,
        text: str,
        presentation: ScreenSurfacePresentation,
    ) -> None:
        self.open(
            info_surface_view(
                title=title,
                text=text,
                presentation=presentation,
            )
        )

    def open_settings(
        self,
        *,
        title: str,
        content: object,
        presentation: ScreenSurfacePresentation,
        preferred_height: int,
    ) -> None:
        self.open(
            ScreenSurfaceView(
                title=title,
                purpose="settings",
                content=content,
                footer="",
                presentation=presentation,
                preferred_height=preferred_height,
            )
        )

    def close(self) -> None:
        self._close_surface_content()
        self.coordinator.close()

    def close_surface(self) -> None:
        self.close()

    def present_approval(
        self,
        *,
        action: str,
        risk: str = "",
        requester: str = "",
        cwd: str = "",
        environment: str = "",
        grant_summary: str = "",
        action_id: str | None = None,
        allow_session: bool = False,
        options: tuple[ApprovalChoice, ...] = (),
    ) -> None:
        current = self.current
        if isinstance(current, ScreenSurfaceView) and current.purpose != "approval":
            self._close_surface_content()
        self.coordinator.present_approval(
            action=action,
            risk=risk,
            requester=requester,
            cwd=cwd,
            environment=environment,
            grant_summary=grant_summary,
            action_id=action_id,
            allow_session=allow_session,
            options=options,
        )

    def open_approval(
        self,
        *,
        action: str,
        risk: str = "",
        requester: str = "",
        cwd: str = "",
        environment: str = "",
        grant_summary: str = "",
        action_id: str | None = None,
        allow_session: bool = False,
        options: tuple[ApprovalChoice, ...] = (),
    ) -> None:
        self.present_approval(
            action=action,
            risk=risk,
            requester=requester,
            cwd=cwd,
            environment=environment,
            grant_summary=grant_summary,
            action_id=action_id,
            allow_session=allow_session,
            options=options,
        )

    def clear_approvals(self) -> None:
        self.coordinator.clear_approvals()

    def clear_approval_surfaces(self) -> None:
        self.clear_approvals()

    def dismiss_approval(self, action_id: str) -> None:
        self.coordinator.dismiss_approval(action_id)

    async def _handle_model_submit(self, payload: str) -> None:
        await self.select_model(payload, close_surface=True)

    async def _handle_command_submit(self, payload: str) -> None:
        self.select_command(payload, close_surface=True)

    async def _handle_settings_submit(self, payload: dict[str, str]) -> None:
        surface = self.current
        page = surface.content if isinstance(surface, ScreenSurfaceView) else None
        apply_setting = getattr(page, "apply_setting", None)
        if not callable(apply_setting):
            return
        result: SettingsApplyResult = await apply_setting(
            payload["id"], payload.get("value", "")
        )
        if result.statusline_settings is not None:
            self.app.set_statusline_settings(result.statusline_settings)
        elif result.statusline_visible is not None:
            self.app.set_statusline_visible(result.statusline_visible)
        if result.refresh_model_label:
            await self.ports.refresh_model_label()
        self.app.request_render(self.request_render_reason)

    async def _handle_session_submit(self, payload: object) -> None:
        if self.ports.activate_continuity is None:
            return
        surface = self.current
        content = surface.content if isinstance(surface, ScreenSurfaceView) else None
        begin_activation = getattr(content, "begin_activation", None)
        if isinstance(surface, ScreenSurfaceView) and callable(begin_activation):
            if not begin_activation():
                return
            self._session_activation_task = asyncio.create_task(
                self._run_session_activation(payload, surface)
            )
            return
        await self._activate_session(payload, surface)

    async def _run_session_activation(
        self,
        payload: object,
        surface: ScreenSurfaceView,
    ) -> None:
        try:
            await self._activate_session(payload, surface)
        finally:
            if self._session_activation_task is asyncio.current_task():
                self._session_activation_task = None

    async def _handle_fork_submit(self, payload: object) -> None:
        if self.ports.fork_session is None:
            return
        surface = self.current
        content = surface.content if isinstance(surface, ScreenSurfaceView) else None
        begin_activation = getattr(content, "begin_activation", None)
        if isinstance(surface, ScreenSurfaceView) and callable(begin_activation):
            if not begin_activation():
                return
            self._fork_activation_task = asyncio.create_task(
                self._run_fork_activation(payload, surface)
            )
            return
        await self._activate_fork(payload, surface)

    async def _handle_delete_submit(self, payload: object) -> None:
        if self.ports.delete_continuity is None:
            return
        surface = self.current
        content = surface.content if isinstance(surface, ScreenSurfaceView) else None
        if getattr(content, "target", None) is not None:
            await self._perform_continuity_deletion(payload, surface)
            return
        target = payload
        if not isinstance(target, ContinuityTarget):
            return
        summary = getattr(content, "selected_summary", None)
        title = getattr(summary, "title", None)
        if not isinstance(title, str) or not title:
            title = target.opaque_id
        from loushang.harnesstui.continuity import (
            build_delete_continuity_confirmation_surface,
        )

        self.open(
            build_delete_continuity_confirmation_surface(
                target=target,
                title=title,
            )
        )

    async def _handle_rename_submit(self, payload: object) -> None:
        rename = self.ports.rename_session
        if rename is None:
            return
        name = payload.strip() if isinstance(payload, str) else ""
        try:
            message = await rename(name or None)
        except Exception as error:
            self.app.set_status(self.copy.recoverable_error(error))
            return
        self.close()
        self.app.set_status(message)
        self.app.request_render(self.request_render_reason)

    async def _run_fork_activation(
        self,
        payload: object,
        surface: ScreenSurfaceView,
    ) -> None:
        try:
            await self._activate_fork(payload, surface)
        finally:
            if self._fork_activation_task is asyncio.current_task():
                self._fork_activation_task = None

    async def _activate_fork(
        self,
        payload: object,
        surface: ScreenSurfaceView | object | None,
    ) -> None:
        fork_session = self.ports.fork_session
        if fork_session is None:  # pragma: no cover - guarded by submit handler
            return
        try:
            result = await fork_session(payload)
        except Exception as error:
            if isinstance(surface, ScreenSurfaceView) and self.current is surface:
                fail_activation = getattr(surface.content, "fail_activation", None)
                if callable(fail_activation):
                    fail_activation(error)
            self.app.set_status(self.copy.recoverable_error(error))
            return
        if self.current is surface:
            self.close()
        if result.composer_text is not None:
            self.app.composer.set_text(result.composer_text)
        self.app.set_status(result.status)
        self.app.request_render(self.request_render_reason)

    async def _activate_session(
        self,
        payload: object,
        surface: ScreenSurfaceView | object | None,
    ) -> None:
        activate = self.ports.activate_continuity
        if activate is None:  # pragma: no cover - guarded by submit handler
            return
        try:
            message = await activate(payload)
        except Exception as error:
            if isinstance(surface, ScreenSurfaceView) and self.current is surface:
                fail_activation = getattr(surface.content, "fail_activation", None)
                if callable(fail_activation):
                    fail_activation(error)
            self.app.set_status(self.copy.recoverable_error(error))
            return
        if self.current is surface:
            self.close()
        self.app.set_status(message)
        self.app.request_render(self.request_render_reason)

    async def _perform_continuity_deletion(
        self,
        payload: object,
        surface: ScreenSurfaceView | object | None,
    ) -> None:
        delete = self.ports.delete_continuity
        if delete is None:  # pragma: no cover - guarded by submit handler
            return
        try:
            message = await delete(payload)
        except Exception as error:
            self.app.set_status(self.copy.recoverable_error(error))
            return
        if self.current is surface and self.ports.build_delete_surface is not None:
            self.open(self.ports.build_delete_surface())
        elif self.current is surface:
            self.close()
        self.app.set_status(message)
        self.app.request_render(self.request_render_reason)

    async def _run_surface_starter(self, starter: Callable[[], object]) -> None:
        try:
            result = starter()
            if hasattr(result, "__await__"):
                await result
        except asyncio.CancelledError:
            return
        except Exception as error:
            self.app.set_status(self.copy.recoverable_error(error))

    def _close_surface_content(self) -> None:
        surface = self.current
        if isinstance(surface, ScreenSurfaceView):
            close = getattr(surface.content, "close", None)
            if callable(close):
                close()
        if self._surface_task is not None and not self._surface_task.done():
            self._surface_task.cancel()
        self._surface_task = None

    async def _handle_dialog_submit(self, _payload: Any | None = None) -> None:
        self.close()

    async def _handle_approval_submit(
        self, payload: ApprovalSurfaceDecision | None = None
    ) -> None:
        accepted = True
        if self.ports.decide_approval is not None:
            accepted = await self.ports.decide_approval(payload) is not False
        if not accepted:
            self.app.set_status(self.copy.approval_stale)
        elif payload is not None and payload.approved:
            self.app.set_status(self.copy.approval_confirmed(payload.action))
        elif payload is not None and payload.outcome == "abort":
            self.app.set_status(self.copy.approval_aborted)
        elif payload is not None:
            self.app.set_status(self.copy.approval_rejected)

    async def _handle_permission_submit(self, payload: object) -> None:
        apply_action = self.ports.apply_permission_action
        if apply_action is None or not isinstance(payload, str):
            return
        surface = self.current
        try:
            accepted = await apply_action(payload)
        except Exception as error:
            self.app.set_status(self.copy.recoverable_error(error))
            return
        if not accepted:
            self.app.set_status("Permission is no longer active.")
        elif payload.startswith("reopen:"):
            self.app.set_status("Approval reopened.")
        elif payload.startswith("revoke-policy:"):
            self.app.set_status("Persistent Policy permission revoked.")
        elif payload.startswith("set-profile:"):
            _prefix, scope, profile_id = payload.split(":", 2)
            self.app.set_status(
                "Permissions updated to "
                f"{profile_id.replace('_', ' ').title()} ({scope})."
            )
        else:
            self.app.set_status("Session permission revoked.")
        if (
            self.current is surface
            and self.ports.build_permissions_surface is not None
        ):
            self.open(self.ports.build_permissions_surface())
        self.app.request_render(self.request_render_reason)

    def _resolve_command(self, text: str) -> ScreenSurfaceCommand | None:
        if self.ports.normalize_interactive_command is not None:
            interactive = self.ports.normalize_interactive_command(text)
            if interactive is not None:
                return interactive
        command = self.ports.command_catalog.lookup(text)
        if command is None or command.kind is not CommandKind.LOCAL_UI:
            return None
        return self.ports.normalize_command(text, command)


def normalize_standard_conversation_surface_command(
    text: str,
    command: CommandDef,
) -> ScreenSurfaceCommand | None:
    """Map standard conversation commands onto the shared surface grammar."""

    intent = parse_conversation_intent(text)
    if command.name == "model" and isinstance(intent, ModelSelectIntent):
        return ScreenSurfaceCommand("select_model", intent.query)
    if command.name == "models" and isinstance(intent, ModelsIntent):
        return ScreenSurfaceCommand("list_models", intent.query)
    if command.name == "command" and isinstance(intent, CommandSelectIntent):
        query = intent.query
        return ScreenSurfaceCommand(
            "select_command",
            query if not query or query.startswith("/") else f"/{query}",
        )
    if command.name == "commands" and isinstance(intent, CommandsIntent):
        return ScreenSurfaceCommand("list_commands", intent.query)
    if command.name == "btw":
        stripped = text.strip()
        parts = stripped.split(maxsplit=1)
        query = parts[1] if len(parts) == 2 else ""
        return ScreenSurfaceCommand("side_question", query)
    if command.name == "agents":
        return ScreenSurfaceCommand("agent_tree")
    if command.name == "permissions":
        return ScreenSurfaceCommand("permissions")
    if command.name == "terminal" and isinstance(
        intent,
        TerminalDiagnosticsIntent,
    ):
        return ScreenSurfaceCommand("terminal_diagnostics")
    if command.name == "hotkeys" and isinstance(intent, HotkeysIntent):
        return ScreenSurfaceCommand("hotkeys")
    if command.name in {"settings", "config"} and isinstance(
        intent,
        SettingsIntent,
    ):
        return ScreenSurfaceCommand("settings")
    return None


def normalize_standard_conversation_interactive_command(
    text: str,
) -> ScreenSurfaceCommand | None:
    """Recognize standard commands whose empty form requires screen interaction."""

    if text.strip() == "/resume":
        return ScreenSurfaceCommand("resume_session")
    if text.strip() == "/delete":
        return ScreenSurfaceCommand("delete_session")
    if text.strip() == "/fork":
        return ScreenSurfaceCommand("fork_session")
    if text.strip() == "/rename":
        return ScreenSurfaceCommand("rename_session")
    return None


def strip_available_models_heading(text: str) -> str:
    prefix = "Available models:\n"
    return text[len(prefix) :] if text.startswith(prefix) else text


__all__ = [
    "ApprovalDecisionHandler",
    "ModelLabelRefresher",
    "ModelSelectionHandler",
    "ScreenSurfaceWorkflow",
    "ScreenSurfaceWorkflowCopy",
    "ScreenSurfaceWorkflowPorts",
    "ScreenSurfaceCommand",
    "ScreenSurfaceCommandCatalog",
    "ScreenSurfaceCommandKind",
    "ScreenSurfaceComposerPort",
    "ScreenSurfaceForkResult",
    "ScreenSurfaceWorkflowAppPort",
    "STANDARD_SCREEN_SURFACE_WORKFLOW_COPY",
    "normalize_standard_conversation_interactive_command",
    "normalize_standard_conversation_surface_command",
    "strip_available_models_heading",
]
