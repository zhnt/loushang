from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from loushang.harnesstui.selection.binding import (
    available_session_model_choices,
    current_session_model_choice_value,
)
from loushang.harnesstui.selection.catalog import ModelChoice
from loushang.harnesstui.settings.dashboard import (
    SettingsDashboard,
    StaticLinesPage,
    StatusSnapshotView,
    UsageProvider,
    model_usage_lines,
    stats_overview_lines,
    status_lines,
    usage_lines,
)
from loushang.harnesstui.settings.model import ModelPage
from loushang.harnesstui.settings.page import ConfigSettingsPage
from loushang.harnesstui.settings.schema import (
    BooleanSettingBinding,
    BooleanSettingCopy,
    apply_boolean_setting,
    boolean_setting_facts,
)
from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    StatusLineSettings,
)
from loushang.harnesstui.status.settings import StatusLineSettingsPage
from loushang.tui import TabGroup, TabPage
from loushang.tui.settings import SETTINGS_PAGE_THEME, ConfigRow


class SettingsStatusProvider(Protocol):
    """Status operations consumed by the shared settings workflow."""

    def snapshot(self) -> StatusSnapshotView: ...

    def statusline_settings(self) -> StatusLineSettings: ...

    def apply_statusline_setting(self, item_id: str, value: str) -> str: ...


@dataclass(frozen=True, slots=True)
class SettingsConfigUpdate:
    """Result of applying one product-owned configuration setting."""

    message: str


@dataclass(frozen=True, slots=True)
class SettingsModelSnapshot:
    """Presentation-ready model state supplied by a product adapter."""

    choices: tuple[ModelChoice, ...]
    current_value: str | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class SettingsApplyResult:
    """Effects a surface host must reflect after applying a setting."""

    message: str
    statusline_visible: bool | None = None
    statusline_settings: StatusLineSettings | None = None
    refresh_model_label: bool = False


ConfigRowsProvider = Callable[[], tuple[ConfigRow, ...]]
ConfigApplyHandler = Callable[[str, str], SettingsConfigUpdate | None]
ModelSnapshotProvider = Callable[[], Awaitable[SettingsModelSnapshot]]
ModelApplyHandler = Callable[[str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class SettingsWorkflowPorts:
    """Product callbacks required to populate and mutate shared settings UI."""

    config_rows: ConfigRowsProvider
    apply_config: ConfigApplyHandler
    load_models: ModelSnapshotProvider
    apply_model: ModelApplyHandler


@dataclass(frozen=True, slots=True)
class BooleanSettingsWorkflowAdapter:
    """Adapt a product boolean schema to settings-dashboard callbacks."""

    manager: object | None
    bindings: tuple[BooleanSettingBinding, ...]
    copy: BooleanSettingCopy

    def config_rows(self) -> tuple[ConfigRow, ...]:
        return tuple(
            ConfigRow(fact.id, fact.label, fact.value)
            for fact in boolean_setting_facts(self.manager, self.bindings)
        )

    def apply_config(self, item_id: str, value: str) -> SettingsConfigUpdate | None:
        outcome = apply_boolean_setting(
            self.manager,
            item_id,
            value,
            bindings=self.bindings,
            copy=self.copy,
        )
        if not outcome.matched:
            return None
        return SettingsConfigUpdate(outcome.message)


async def session_model_settings_snapshot(session: object) -> SettingsModelSnapshot:
    """Load presentation-ready model settings from a standard Agent session."""

    choices = await available_session_model_choices(session)
    current_value = await current_session_model_choice_value(
        session,
        choices=choices,
    )
    return SettingsModelSnapshot(tuple(choices), current_value=current_value)


def build_session_settings_workflow_ports(
    *,
    session: object,
    config: BooleanSettingsWorkflowAdapter,
    apply_model: ModelApplyHandler,
) -> SettingsWorkflowPorts:
    """Bind standard session model data and a Product configuration adapter."""

    return SettingsWorkflowPorts(
        config_rows=config.config_rows,
        apply_config=config.apply_config,
        load_models=lambda: session_model_settings_snapshot(session),
        apply_model=apply_model,
    )


@dataclass(slots=True)
class SettingsPageView(SettingsDashboard):
    """Harness-backed settings dashboard over product-prepared callbacks."""

    status_provider: SettingsStatusProvider
    ports: SettingsWorkflowPorts
    usage_provider: UsageProvider | None = None
    status_page: StaticLinesPage = field(init=False)
    config_page: ConfigSettingsPage = field(init=False)
    model_page: ModelPage = field(init=False)
    statusline_page: StatusLineSettingsPage = field(init=False)
    usage_page: StaticLinesPage = field(init=False)
    stats_page: TabGroup = field(init=False)
    statusline_preview: Callable[[], StatusLinePreviewSnapshot] | None = None

    @classmethod
    async def create(
        cls,
        *,
        status_provider: SettingsStatusProvider,
        ports: SettingsWorkflowPorts,
        usage_provider: UsageProvider | None = None,
        statusline_preview: Callable[[], StatusLinePreviewSnapshot] | None = None,
    ) -> SettingsPageView:
        view = cls(
            status_provider=status_provider,
            ports=ports,
            usage_provider=usage_provider,
            statusline_preview=statusline_preview,
        )
        await view._build()
        view.focus()
        return view

    async def apply_setting(self, item_id: str, value: str) -> SettingsApplyResult:
        if item_id == "statusline" or item_id.startswith("statusline."):
            message = self.status_provider.apply_statusline_setting(item_id, value)
            self._refresh_status_page()
            self._refresh_statusline_page(preserve_active_key=item_id)
            settings = self.status_provider.statusline_settings()
            self.feedback_message = message
            return SettingsApplyResult(
                message,
                statusline_visible=settings.enabled,
                statusline_settings=settings,
            )

        config_update = self.ports.apply_config(item_id, value)
        if config_update is not None:
            self._refresh_config_rows(preserve_active_key=item_id)
            self.feedback_message = config_update.message
            return SettingsApplyResult(config_update.message)

        if item_id == "model.current":
            message = await self.ports.apply_model(value)
            await self._refresh_model_page()
            self._refresh_status_page()
            self.feedback_message = message
            return SettingsApplyResult(message, refresh_model_label=True)

        message = f"Unknown setting: {item_id}"
        self.feedback_message = message
        return SettingsApplyResult(message)

    async def _build(self) -> None:
        snapshot = self.status_provider.snapshot()
        self.status_page = StaticLinesPage(status_lines(snapshot))
        self.config_page = ConfigSettingsPage(self.ports.config_rows())
        models = await self._load_models()
        self.model_page = ModelPage(
            models.choices,
            current_value=models.current_value,
            error=models.error,
        )
        self.statusline_page = StatusLineSettingsPage(
            self.status_provider.statusline_settings(),
            self._statusline_preview_snapshot,
        )
        self.usage_page = StaticLinesPage(usage_lines(self.usage_provider))
        self.stats_page = TabGroup(
            (
                TabPage(
                    "overview",
                    "Overview",
                    StaticLinesPage(stats_overview_lines(snapshot)),
                ),
                TabPage(
                    "model-usage",
                    "Model Usage",
                    StaticLinesPage(model_usage_lines(models.current_value)),
                ),
            ),
            value="overview",
            level=1,
            theme=SETTINGS_PAGE_THEME,
        )
        self.tabs = TabGroup(
            (
                TabPage("status", "Status", self.status_page),
                TabPage("config", "Config", self.config_page),
                TabPage("model", "Model", self.model_page),
                TabPage("status-line", "Status Line", self.statusline_page),
                TabPage("usage", "Usage", self.usage_page),
                TabPage("stats", "Stats", self.stats_page),
            ),
            value="config",
            theme=SETTINGS_PAGE_THEME,
        )

    def _refresh_status_page(self) -> None:
        self.status_page.lines = status_lines(self.status_provider.snapshot())

    def _refresh_config_rows(self, *, preserve_active_key: str = "") -> None:
        self.config_page.set_rows(
            self.ports.config_rows(),
            preserve_active_key=preserve_active_key,
        )

    def _refresh_statusline_page(self, *, preserve_active_key: str = "") -> None:
        self.statusline_page.set_statusline_settings(
            self.status_provider.statusline_settings(),
            preserve_active_key=preserve_active_key,
        )

    async def _refresh_model_page(self) -> None:
        models = await self._load_models()
        self.model_page.set_choices(
            models.choices,
            current_value=models.current_value,
            error=models.error,
        )
        model_usage_page = next(
            (page for page in self.stats_page.pages if page.value == "model-usage"),
            None,
        )
        if model_usage_page is not None and isinstance(
            model_usage_page.content,
            StaticLinesPage,
        ):
            model_usage_page.content.lines = model_usage_lines(models.current_value)

    async def _load_models(self) -> SettingsModelSnapshot:
        try:
            return await self.ports.load_models()
        except Exception as error:
            return SettingsModelSnapshot((), error=str(error))

    def _statusline_preview_snapshot(self) -> StatusLinePreviewSnapshot:
        if self.statusline_preview is not None:
            return self.statusline_preview()
        snapshot = self.status_provider.snapshot()
        return StatusLinePreviewSnapshot(
            model_label=snapshot.model_label,
            cwd=snapshot.cwd,
            branch=snapshot.branch,
            session_label=snapshot.session_label,
            running=snapshot.running,
        )


__all__ = [
    "BooleanSettingsWorkflowAdapter",
    "SettingsApplyResult",
    "SettingsConfigUpdate",
    "SettingsModelSnapshot",
    "SettingsPageView",
    "SettingsStatusProvider",
    "SettingsWorkflowPorts",
    "build_session_settings_workflow_ports",
    "session_model_settings_snapshot",
]
