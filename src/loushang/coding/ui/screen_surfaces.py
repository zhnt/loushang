from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loushang.coding.continuity import bind_coding_continuity
from loushang.coding.model_selection_tui import select_available_model
from loushang.coding.ui.hotkeys import format_hotkeys
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.settings_page import build_coding_settings_page
from loushang.harness.session import SessionApprovalInteractionPort
from loushang.harnesstui.conversation.agent_application import (
    current_agent_runtime_session,
)
from loushang.harnesstui.conversation.agent_surfaces import (
    build_standard_agent_screen_surface_workflow_ports,
)
from loushang.harnesstui.selection.binding import (
    SessionModelSelectorSurfaceProfile,
)
from loushang.harnesstui.status.provider import StatusProvider
from loushang.harnesstui.surface.workflow import (
    STANDARD_SCREEN_SURFACE_WORKFLOW_COPY,
    ScreenSurfaceCommandCatalog,
    ScreenSurfaceWorkflow,
)

_CODING_MODEL_SELECTOR_PROFILE = SessionModelSelectorSurfaceProfile(
    subtitle=(
        "Choose a model for this session · legacy: "
        "loushang --model <provider:model>"
    ),
    presentation="bottom-exclusive",
)


class ScreenSurfaceManager(ScreenSurfaceWorkflow):
    """Coding product adapter over the shared surface interaction host."""

    def __init__(
        self,
        *,
        app: ScreenCodingTuiApp,
        session: Any,
        runtime: Any | None = None,
        status_provider: StatusProvider,
        on_approval: Callable[[dict[str, Any]], Awaitable[bool | None]] | None = None,
        approval_interaction_provider: (
            Callable[[], SessionApprovalInteractionPort | None] | None
        ) = None,
        command_catalog: ScreenSurfaceCommandCatalog | None = None,
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.status_provider = status_provider
        continuity = bind_coding_continuity(runtime) if runtime is not None else None
        ports = build_standard_agent_screen_surface_workflow_ports(
            session,
            runtime=runtime,
            continuity_hub=continuity.hub if continuity is not None else None,
            session_provider=self._current_session,
            approval_interaction_provider=approval_interaction_provider,
            select_model=lambda value: select_available_model(
                self._current_session(),
                query=value,
            ),
            set_model_label=lambda label: setattr(
                app.state,
                "model_label",
                label,
            ),
            set_session_label=lambda label: setattr(
                app.state,
                "session_label",
                label,
            ),
            set_permission_profile_label=lambda label: setattr(
                app.state,
                "permission_profile",
                label,
            ),
            build_settings_content=self._build_settings_content,
            terminal_diagnostics=self._terminal_diagnostics,
            hotkeys=format_hotkeys,
            request_render=app.request_render,
            on_approval=on_approval,
            command_catalog=command_catalog,
            model_selector_profile=_CODING_MODEL_SELECTOR_PROFILE,
        )
        self.command_catalog = ports.command_catalog
        super().__init__(
            app=app,
            ports=ports,
            copy=STANDARD_SCREEN_SURFACE_WORKFLOW_COPY,
        )

    @property
    def coding_app(self) -> ScreenCodingTuiApp:
        app = self.app
        if not isinstance(app, ScreenCodingTuiApp):  # pragma: no cover - constructor
            raise TypeError("Coding surface manager requires ScreenCodingTuiApp")
        return app

    def _terminal_diagnostics(self) -> str:
        provider = self.coding_app.terminal_diagnostics_provider
        return (
            provider()
            if provider is not None
            else "Terminal diagnostics are not available outside an active TUI session."
        )

    def _current_session(self) -> object:
        if self.runtime is None:
            return self.session
        return current_agent_runtime_session(self.runtime, self.session)

    async def _build_settings_content(self) -> object:
        session = self._current_session()
        return await build_coding_settings_page(
            session=session,
            status_provider=self.status_provider,
            settings_manager=getattr(session, "settings_manager", None),
            statusline_preview=self.coding_app.statusline_preview_snapshot,
        )


__all__ = ["ScreenSurfaceManager"]
