"""Standard live-session surfaces for Agent-backed screen Products."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from loushang.harness.continuity import (
    ContinuityHub,
    ContinuityTarget,
    consume_prepared_activation,
)
from loushang.harness.multiagent import HostCaller
from loushang.harness.session import SessionApprovalInteractionPort
from loushang.harnesstui.continuity import build_continuity_surface_view
from loushang.harnesstui.conversation.agent_application import (
    AgentScreenApprovalHandler,
    build_agent_screen_surface_workflow_ports,
    current_agent_runtime_session,
)
from loushang.harnesstui.conversation.fork import (
    ForkPromptCandidate,
    build_fork_prompt_surface_view,
)
from loushang.harnesstui.conversation.rename import (
    build_session_rename_surface_view,
)
from loushang.harnesstui.conversation.side_question import (
    build_side_question_surface_view,
)
from loushang.harnesstui.multiagent import build_agent_tree_surface_view
from loushang.harnesstui.selection.binding import (
    SessionModelSelectorSurfaceProfile,
)
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.harnesstui.surface.workflow import (
    ScreenSurfaceCommandCatalog,
    ScreenSurfaceForkResult,
    ScreenSurfaceWorkflowPorts,
)


def build_standard_agent_screen_surface_workflow_ports(
    session: object,
    *,
    runtime: object | None = None,
    continuity_hub: ContinuityHub | None = None,
    session_provider: Callable[[], object] | None = None,
    approval_interaction_provider: (
        Callable[[], SessionApprovalInteractionPort | None] | None
    ) = None,
    select_model: Callable[[str], Awaitable[str]],
    set_model_label: Callable[[str], None],
    set_session_label: Callable[[str | None], None],
    set_permission_profile_label: Callable[[str], None] | None = None,
    build_settings_content: Callable[[], Awaitable[object]],
    terminal_diagnostics: Callable[[], str],
    hotkeys: Callable[[], str],
    request_render: Callable[[Literal["product"]], None],
    on_approval: AgentScreenApprovalHandler | None = None,
    command_catalog: ScreenSurfaceCommandCatalog | None = None,
    model_selector_profile: SessionModelSelectorSurfaceProfile = (
        SessionModelSelectorSurfaceProfile()
    ),
) -> ScreenSurfaceWorkflowPorts:
    """Bind standard resume/delete/fork/rename/agents/question operations.

    Products keep their model selection, settings, diagnostics, hotkeys, and
    continuity-provider composition. This function owns only interaction
    mechanics shared by structurally compatible Agent sessions.
    """

    active_session = session_provider or (
        (lambda: current_agent_runtime_session(runtime, session))
        if runtime is not None
        else (lambda: session)
    )

    def require_continuity() -> ContinuityHub:
        if continuity_hub is None:
            raise RuntimeError("Session continuity is not available")
        return continuity_hub

    def build_resume_surface() -> ScreenSurfaceView:
        current = active_session()
        settings_manager = getattr(current, "settings_manager", None)
        keybindings = getattr(settings_manager, "get_keybindings", None)
        return build_continuity_surface_view(
            hub=require_continuity(),
            request_render=lambda _kind: request_render("product"),
            keybindings=keybindings() if callable(keybindings) else None,
        )

    async def activate_continuity(target: object) -> str:
        if not isinstance(target, ContinuityTarget):
            raise TypeError(
                "Resume requires a provider-qualified continuity target"
            )
        lease = await require_continuity().prepare(target)
        result = await consume_prepared_activation(lease)
        if getattr(result, "cancelled", False):
            raise RuntimeError("Session resume was cancelled")
        return f"Resumed session {target.opaque_id}"

    def build_delete_surface() -> ScreenSurfaceView:
        current_id = getattr(active_session(), "session_id", None)
        return build_continuity_surface_view(
            hub=require_continuity(),
            request_render=lambda _kind: request_render("product"),
            include_summary=lambda summary: summary.target.opaque_id != current_id,
            title="Delete a previous session",
            selection_action="delete",
            purpose="delete",
        )

    async def delete_continuity(target: object) -> str:
        if not isinstance(target, ContinuityTarget):
            raise TypeError(
                "Delete requires a provider-qualified continuity target"
            )
        deleted = await require_continuity().delete(target)
        if not deleted:
            raise RuntimeError("The selected session was already deleted")
        return f"Deleted session {target.opaque_id}"

    def build_fork_surface() -> ScreenSurfaceView:
        getter = getattr(active_session(), "get_user_messages_for_forking", None)
        if not callable(getter):
            raise RuntimeError("Prompt history is not available for this session")
        candidates: list[ForkPromptCandidate] = []
        for value in getter():
            if not isinstance(value, Mapping):
                raise TypeError("Fork prompt candidates must be mappings")
            entry_id = value.get("entry_id")
            text = value.get("text")
            if not isinstance(entry_id, str) or not entry_id.strip():
                raise TypeError("Fork prompt candidates require an entry_id")
            if isinstance(text, str) and text.strip():
                candidates.append(ForkPromptCandidate(entry_id=entry_id, text=text))
        return build_fork_prompt_surface_view(
            candidates=candidates,
            request_render=lambda: request_render("product"),
        )

    async def fork_session(target: object) -> ScreenSurfaceForkResult:
        if runtime is None:
            raise RuntimeError("Session runtime is not available")
        if not isinstance(target, str) or not target.strip():
            raise TypeError("Fork requires a selected prompt")
        operation = getattr(runtime, "fork_session_operation", None)
        if not callable(operation):
            raise RuntimeError("Session forking is not available")
        result = await operation(target, position="before")
        if getattr(result, "cancelled", False):
            raise RuntimeError("Session fork was cancelled")
        selected_text = getattr(result, "payload", None)
        if not isinstance(selected_text, str):
            raise RuntimeError("Forked session did not return the selected prompt")
        return ScreenSurfaceForkResult(
            status="Forked from selected prompt",
            composer_text=selected_text,
        )

    def build_rename_surface() -> ScreenSurfaceView:
        name = getattr(active_session(), "session_name", None)
        return build_session_rename_surface_view(
            current_name=name if isinstance(name, str) else None
        )

    async def rename_session(name: str | None) -> str:
        current = active_session()
        rename = getattr(current, "set_session_name", None)
        if not callable(rename):
            raise RuntimeError("Session renaming is not available")
        await rename(name)
        set_session_label(name or getattr(current, "session_id", None))
        return f"Session renamed to {name}" if name else "Session name cleared"

    def build_agent_tree_surface() -> ScreenSurfaceView:
        multiagent_runtime = getattr(active_session(), "multiagent_runtime", None)
        control = getattr(multiagent_runtime, "control", None)
        if multiagent_runtime is None or control is None:
            raise RuntimeError("Agent collaboration is not enabled for this session")
        return build_agent_tree_surface_view(
            records=multiagent_runtime.list_agents(caller=HostCaller()),
            subscribe_facts=control.subscribe_facts,
            request_render=lambda: request_render("product"),
        )

    def build_side_question_surface(question: str) -> ScreenSurfaceView:
        current = active_session()
        ask = getattr(current, "ask_side_question", None)
        cancel = getattr(current, "cancel_side_question", None)
        if not callable(ask) or not callable(cancel):
            raise RuntimeError("Side questions are not available for this session.")
        return build_side_question_surface_view(
            question=question,
            ask=ask,
            cancel=cancel,
            request_render=lambda: request_render("product"),
        )

    has_continuity = runtime is not None and continuity_hub is not None
    return build_agent_screen_surface_workflow_ports(
        session,
        session_provider=active_session,
        approval_interaction_provider=approval_interaction_provider,
        select_model=select_model,
        set_model_label=set_model_label,
        set_permission_profile_label=set_permission_profile_label,
        build_settings_content=build_settings_content,
        terminal_diagnostics=terminal_diagnostics,
        hotkeys=hotkeys,
        on_approval=on_approval,
        build_resume_surface=build_resume_surface if has_continuity else None,
        activate_continuity=activate_continuity if has_continuity else None,
        build_delete_surface=build_delete_surface if has_continuity else None,
        delete_continuity=delete_continuity if has_continuity else None,
        build_fork_surface=build_fork_surface if runtime is not None else None,
        fork_session=fork_session if runtime is not None else None,
        build_rename_surface=build_rename_surface,
        rename_session=rename_session,
        build_agent_tree_surface=build_agent_tree_surface,
        build_side_question_surface=build_side_question_surface,
        command_catalog=command_catalog,
        model_selector_profile=model_selector_profile,
    )


__all__ = ["build_standard_agent_screen_surface_workflow_ports"]
