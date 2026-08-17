from __future__ import annotations

from collections.abc import Callable

from loushang.coding.interaction.settings_profile import (
    CODING_SETTING_BINDINGS,
    CODING_SETTING_COPY,
)
from loushang.coding.model_selection_tui import select_available_model
from loushang.harnesstui.settings.workflow import (
    BooleanSettingsWorkflowAdapter,
    SettingsPageView,
    build_session_settings_workflow_ports,
)
from loushang.harnesstui.status.line import StatusLinePreviewSnapshot
from loushang.harnesstui.status.provider import StatusProvider


async def build_coding_settings_page(
    *,
    session: object,
    status_provider: StatusProvider,
    usage_provider: Callable[[], object | None] | None = None,
    settings_manager: object | None = None,
    statusline_preview: Callable[[], StatusLinePreviewSnapshot] | None = None,
) -> SettingsPageView:
    """Compose shared settings workflow with Coding-owned facts and actions."""

    config = BooleanSettingsWorkflowAdapter(
        settings_manager,
        CODING_SETTING_BINDINGS,
        CODING_SETTING_COPY,
    )

    async def _apply_model(value: str) -> str:
        return await select_available_model(
            session,
            query=value,
            settings_manager=settings_manager,
        )

    return await SettingsPageView.create(
        status_provider=status_provider,
        ports=build_session_settings_workflow_ports(
            session=session,
            config=config,
            apply_model=_apply_model,
        ),
        usage_provider=usage_provider,
        statusline_preview=statusline_preview,
    )


__all__ = ["build_coding_settings_page"]
