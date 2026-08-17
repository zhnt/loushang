from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

from loushang.ai.model import ModelSelection
from loushang.harnesstui.selection.catalog import ModelChoice
from loushang.harnesstui.settings.dashboard import StaticLinesPage
from loushang.harnesstui.settings.model import ModelPage
from loushang.harnesstui.settings.page import ConfigSettingsPage
from loushang.harnesstui.settings.schema import (
    BooleanSettingBinding,
    BooleanSettingCopy,
)
from loushang.harnesstui.settings.workflow import (
    BooleanSettingsWorkflowAdapter,
    SettingsConfigUpdate,
    SettingsModelSnapshot,
    SettingsPageView,
    SettingsWorkflowPorts,
    build_session_settings_workflow_ports,
    session_model_settings_snapshot,
)
from loushang.harnesstui.status.line import StatusLineSettings
from loushang.harnesstui.status.settings import StatusLineSettingsPage
from loushang.tui import InputEvent, RenderConstraints, TabGroup
from loushang.tui.settings import ConfigRow


class _BooleanManager:
    def __init__(self) -> None:
        self.enabled = False

    def get_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


def test_boolean_workflow_adapter_projects_rows_and_only_claims_bound_ids() -> None:
    manager = _BooleanManager()
    adapter = BooleanSettingsWorkflowAdapter(
        manager,
        (
            BooleanSettingBinding(
                "feature.enabled",
                "Feature",
                "get_enabled",
                "set_enabled",
                "Feature",
            ),
        ),
        BooleanSettingCopy(
            unknown=lambda item_id: f"unknown:{item_id}",
            invalid=lambda binding: f"invalid:{binding.id}",
            unavailable=lambda binding: f"unavailable:{binding.id}",
            applied=lambda binding, enabled: f"applied:{binding.id}:{enabled}",
        ),
    )

    assert adapter.config_rows() == (ConfigRow("feature.enabled", "Feature", "false"),)
    assert adapter.apply_config("model.current", "true") is None
    assert adapter.apply_config("feature.enabled", "true") == SettingsConfigUpdate(
        "applied:feature.enabled:True"
    )
    assert manager.enabled is True


def test_session_settings_binding_loads_models_and_reuses_product_config() -> None:
    class Session:
        async def get_model_selection(self) -> ModelSelection:
            return ModelSelection(
                provider="provider",
                endpoint_id="test-endpoint",
                model_id="research",
            )

        async def get_available_models(self) -> list[ModelSelection]:
            return [
                ModelSelection(
                    provider="provider",
                    endpoint_id="test-endpoint",
                    model_id="research",
                ),
                ModelSelection(
                    provider="provider",
                    endpoint_id="test-endpoint",
                    model_id="analysis",
                ),
            ]

    manager = _BooleanManager()
    config = BooleanSettingsWorkflowAdapter(
        manager,
        (
            BooleanSettingBinding(
                "feature.enabled",
                "Feature",
                "get_enabled",
                "set_enabled",
                "Feature",
            ),
        ),
        BooleanSettingCopy(
            unknown=lambda item_id: f"unknown:{item_id}",
            invalid=lambda binding: f"invalid:{binding.id}",
            unavailable=lambda binding: f"unavailable:{binding.id}",
            applied=lambda binding, enabled: f"applied:{binding.id}:{enabled}",
        ),
    )

    async def apply_model(value: str) -> str:
        return f"selected:{value}"

    ports = build_session_settings_workflow_ports(
        session=Session(),
        config=config,
        apply_model=apply_model,
    )
    snapshot = asyncio.run(ports.load_models())

    assert snapshot == asyncio.run(session_model_settings_snapshot(Session()))
    assert tuple(choice.value for choice in snapshot.choices) == (
        "provider:test-endpoint:research",
        "provider:test-endpoint:analysis",
    )
    assert snapshot.current_value == "provider:test-endpoint:research"
    assert ports.config_rows() == (ConfigRow("feature.enabled", "Feature", "false"),)
    assert asyncio.run(ports.apply_model("provider/analysis")) == (
        "selected:provider/analysis"
    )


@dataclass(frozen=True, slots=True)
class _StatusSnapshot:
    model_label: str | None = "provider/alpha"
    cwd: str = "/workspace"
    branch: str | None = "main"
    session_label: str | None = "session-1"
    thinking_level: str | None = "medium"
    running: bool = False
    statusline_visible: bool = True


class _StatusProvider:
    def __init__(self) -> None:
        self.model_label = "provider/alpha"
        self.settings = StatusLineSettings()
        self.apply_calls: list[tuple[str, str]] = []

    def snapshot(self) -> _StatusSnapshot:
        return _StatusSnapshot(
            model_label=self.model_label,
            statusline_visible=self.settings.enabled,
        )

    def statusline_settings(self) -> StatusLineSettings:
        return self.settings

    def apply_statusline_setting(self, item_id: str, value: str) -> str:
        self.apply_calls.append((item_id, value))
        if item_id == "statusline.enabled":
            enabled = value == "true"
            self.settings = replace(self.settings, enabled=enabled)
            return f"Status line: {'on' if enabled else 'off'}"
        raise AssertionError(f"unexpected status-line setting: {item_id}")


def _choice(value: str) -> ModelChoice:
    return ModelChoice(label=value, value=value, selection=object())


class _Ports:
    def __init__(self) -> None:
        self.config_values = {"first": "false", "second": "false"}
        self.config_order = ("first", "second")
        self.config_apply_calls: list[tuple[str, str]] = []
        self.model_apply_calls: list[str] = []
        self.model_load_calls = 0
        self.current_model = "provider/alpha"
        self.model_error: Exception | None = None

    def config_rows(self) -> tuple[ConfigRow, ...]:
        return tuple(
            ConfigRow(item_id, item_id.title(), self.config_values[item_id])
            for item_id in self.config_order
        )

    def apply_config(self, item_id: str, value: str) -> SettingsConfigUpdate | None:
        if item_id not in self.config_values:
            return None
        self.config_apply_calls.append((item_id, value))
        self.config_values[item_id] = value
        self.config_order = tuple(reversed(self.config_order))
        return SettingsConfigUpdate(f"{item_id}: {value}")

    async def load_models(self) -> SettingsModelSnapshot:
        self.model_load_calls += 1
        if self.model_error is not None:
            raise self.model_error
        return SettingsModelSnapshot(
            (_choice("provider/alpha"), _choice("provider/beta")),
            current_value=self.current_model,
        )

    async def apply_model(self, value: str) -> str:
        self.model_apply_calls.append(value)
        self.current_model = value
        return f"Model set: {value}"

    def workflow_ports(self) -> SettingsWorkflowPorts:
        return SettingsWorkflowPorts(
            config_rows=self.config_rows,
            apply_config=self.apply_config,
            load_models=self.load_models,
            apply_model=self.apply_model,
        )


def _create_view(
    *,
    status_provider: _StatusProvider | None = None,
    ports: _Ports | None = None,
) -> tuple[SettingsPageView, _StatusProvider, _Ports]:
    status_provider = status_provider or _StatusProvider()
    ports = ports or _Ports()
    view = asyncio.run(
        SettingsPageView.create(
            status_provider=status_provider,
            ports=ports.workflow_ports(),
        )
    )
    return view, status_provider, ports


def test_create_composes_product_neutral_settings_tabs() -> None:
    view, _, ports = _create_view()

    assert tuple((page.value, page.label) for page in view.tabs.pages) == (
        ("status", "Status"),
        ("config", "Config"),
        ("model", "Model"),
        ("status-line", "Status Line"),
        ("usage", "Usage"),
        ("stats", "Stats"),
    )
    assert view.tabs.value == "config"
    assert view.tabs.focused is True
    assert view.tabs.header_focused is False
    assert isinstance(view.status_page, StaticLinesPage)
    assert isinstance(view.config_page, ConfigSettingsPage)
    assert isinstance(view.model_page, ModelPage)
    assert isinstance(view.statusline_page, StatusLineSettingsPage)
    assert isinstance(view.usage_page, StaticLinesPage)
    assert isinstance(view.stats_page, TabGroup)
    assert tuple(page.value for page in view.stats_page.pages) == (
        "overview",
        "model-usage",
    )
    assert view.stats_page.value == "overview"
    assert ports.model_load_calls == 1


def test_apply_config_refreshes_rows_and_preserves_active_key() -> None:
    view, _, ports = _create_view()
    assert view.handle_input(InputEvent(kind="key", key="down")) is True
    assert view.handle_input(InputEvent(kind="key", key="down")) is True
    assert view.config_page.settings.active_key == "second"

    result = asyncio.run(view.apply_setting("second", "true"))

    assert ports.config_apply_calls == [("second", "true")]
    assert tuple(row.id for row in view.config_page.rows) == ("second", "first")
    assert view.config_page.settings.active_key == "second"
    assert view.config_page.settings.active_item is not None
    assert view.config_page.settings.active_item.value == "true"
    assert result.message == "second: true"
    assert view.feedback_message == "second: true"


def test_apply_model_reloads_choices_and_requests_host_label_refresh() -> None:
    view, _, ports = _create_view()
    overview = next(page for page in view.stats_page.pages if page.value == "overview")
    model_usage = next(
        page for page in view.stats_page.pages if page.value == "model-usage"
    )

    result = asyncio.run(view.apply_setting("model.current", "provider/beta"))

    assert ports.model_apply_calls == ["provider/beta"]
    assert ports.model_load_calls == 2
    assert view.model_page.current_value == "provider/beta"
    assert view.model_page.models.active_item is not None
    assert view.model_page.models.active_item.key == "provider/beta"
    assert view.model_page.models.active_item.value == "current"
    assert result.message == "Model set: provider/beta"
    assert result.refresh_model_label is True
    assert view.feedback_message == result.message
    assert isinstance(overview.content, StaticLinesPage)
    assert overview.content.lines[0] == "Session Overview"
    assert isinstance(model_usage.content, StaticLinesPage)
    assert model_usage.content.lines[2] == "Current model      provider/beta"


def test_apply_statusline_setting_returns_host_effects_and_refreshes_pages() -> None:
    view, status_provider, ports = _create_view()
    view.statusline_page.focus()
    assert view.statusline_page.handle_input(InputEvent(kind="key", key="down")) is True
    assert view.statusline_page.settings.active_key == "statusline.enabled"

    result = asyncio.run(view.apply_setting("statusline.enabled", "false"))

    assert status_provider.apply_calls == [("statusline.enabled", "false")]
    assert ports.config_apply_calls == []
    assert result.message == "Status line: off"
    assert result.statusline_visible is False
    assert result.statusline_settings == StatusLineSettings(enabled=False)
    assert result.refresh_model_label is False
    assert view.statusline_page.settings.active_key == "statusline.enabled"
    assert view.statusline_page.settings.active_item is not None
    assert view.statusline_page.settings.active_item.value == "false"
    assert view.status_page.lines[-1] == "Status line        false"
    assert view.feedback_message == result.message


def test_model_loader_exception_becomes_model_error_page() -> None:
    ports = _Ports()
    ports.model_error = RuntimeError("catalog offline")

    view, _, _ = _create_view(ports=ports)

    assert ports.model_load_calls == 1
    assert view.model_page.unavailable is True
    assert view.model_page.error == "catalog offline"
    rendered = view.model_page.render(RenderConstraints(width=40, max_height=4))
    assert tuple(line.text for line in rendered.lines) == (
        "Model selection unavailable",
        "catalog offline",
    )
