from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from loushang.agent import ThinkingLevel
from loushang.ai.model import ModelSelection
from loushang.harness.config import (
    ConfigLayer,
    LayeredConfig,
    ScopedConfigRuntime,
    SettingsRuntime,
)
from loushang.harness.config.agent._settings_codec import (
    CONTROL_CONFIG_CODEC,
    control_config_to_patch,
    decode_package_source,
)
from loushang.harness.config.agent._settings_patch import (
    UNSET,
    AgentSettingsUpdate,
    Unset,
    build_settings_patch,
    prepare_override_patch,
)
from loushang.harness.config.agent.types import (
    BranchSummarySettings,
    CapabilityMountMode,
    CompactionSettings,
    ControlConfig,
    DoubleEscapeAction,
    ExternalToolPolicy,
    ImageSettings,
    KeybindingValue,
    MarkdownSettings,
    MethodSettings,
    PermissionSettings,
    QueueMode,
    RetrySettings,
    SandboxSettings,
    StatusLineControlSettings,
    TerminalSettings,
    ThinkingBudgetMap,
    ToolSettings,
    TreeFilterMode,
    WarningSettings,
)
from loushang.harness.permissions import (
    PermissionProfileCeiling,
    PermissionProfileId,
    PermissionProfileScope,
    PermissionProfileSnapshot,
    permission_profile,
    permission_profile_snapshot,
)
from loushang.harness.resources.packages.source import (
    PackageSourceConfig,
    package_source_match_key,
)

SettingsListener = Callable[[ControlConfig], None]
SettingsScope = Literal["session", "global", "project"]
ThinkingBudgetKey = Literal["minimal", "low", "medium", "high"]


@dataclass(frozen=True)
class SettingsError:
    scope: SettingsScope
    message: str
    error: Exception


class SettingsManager:
    """Manage the standard settings shared by Agent-backed products."""

    def __init__(
        self,
        initial: ControlConfig | None = None,
        *,
        global_settings_path: str | Path | None = None,
        project_settings_path: str | Path | None = None,
        permission_profile_ceiling: PermissionProfileCeiling | None = None,
    ) -> None:
        global_path = (
            Path(global_settings_path) if global_settings_path is not None else None
        )
        project_path = (
            Path(project_settings_path) if project_settings_path is not None else None
        )
        self._adapter_errors: list[SettingsError] = []
        self._permission_profile_ceiling = (
            permission_profile_ceiling or PermissionProfileCeiling()
        )
        self._config = SettingsRuntime(
            ScopedConfigRuntime(
                LayeredConfig(
                    codec=CONTROL_CONFIG_CODEC,
                    layers=(
                        ConfigLayer("global", global_path, persistent=True),
                        ConfigLayer("project", project_path, persistent=True),
                        ConfigLayer("session"),
                    ),
                    initial={"session": initial} if initial is not None else None,
                )
            )
        )

    @property
    def _settings(self) -> ControlConfig:
        return self._config.value

    def reload(self) -> None:
        self._config.reload()

    async def flush(self) -> None:
        return None

    def apply_overrides(self, overrides: Mapping[str, Any] | ControlConfig) -> None:
        patch = (
            control_config_to_patch(overrides)
            if isinstance(overrides, ControlConfig)
            else dict(overrides)
        )
        patch, removed_messages = prepare_override_patch(patch)
        self._adapter_errors.extend(
            SettingsError(
                scope="session",
                message=message,
                error=ValueError(message),
            )
            for message in removed_messages
        )
        self._config.update("session", patch)

    def drain_errors(self) -> list[SettingsError]:
        errors = list(self._adapter_errors)
        self._adapter_errors.clear()
        errors.extend(
            SettingsError(
                scope=cast(SettingsScope, issue.layer),
                message=issue.message,
                error=issue.error,
            )
            for issue in self._config.drain_issues()
        )
        return errors

    @property
    def global_base_dir(self) -> Path | None:
        return self._config.scope("global").base_dir

    @property
    def project_base_dir(self) -> Path | None:
        return self._config.scope("project").base_dir

    def update_settings(
        self,
        *,
        scope: SettingsScope = "session",
        default_model: ModelSelection | None | Unset = UNSET,
        thinking_level: ThinkingLevel | Unset = UNSET,
        steering_mode: QueueMode | Unset = UNSET,
        follow_up_mode: QueueMode | Unset = UNSET,
        theme: str | None | Unset = UNSET,
        system_prompt: str | Unset = UNSET,
        hide_thinking_block: bool | Unset = UNSET,
        shell_path: str | None | Unset = UNSET,
        quiet_startup: bool | Unset = UNSET,
        shell_command_prefix: str | None | Unset = UNSET,
        npm_command: Sequence[str] | None | Unset = UNSET,
        collapse_changelog: bool | Unset = UNSET,
        enable_install_telemetry: bool | Unset = UNSET,
        enable_skill_commands: bool | Unset = UNSET,
        enabled_models: Sequence[str] | None | Unset = UNSET,
        double_escape_action: DoubleEscapeAction | Unset = UNSET,
        tree_filter_mode: TreeFilterMode | Unset = UNSET,
        show_hardware_cursor: bool | Unset = UNSET,
        editor_padding_x: float | int | Unset = UNSET,
        autocomplete_max_visible: float | int | Unset = UNSET,
        keybindings: Mapping[str, object] | Unset = UNSET,
        capabilities: Mapping[str, CapabilityMountMode] | Unset = UNSET,
        thinking_budgets: ThinkingBudgetMap | None | Unset = UNSET,
        compaction: CompactionSettings | Unset = UNSET,
        branch_summary: BranchSummarySettings | Unset = UNSET,
        retry: RetrySettings | Unset = UNSET,
        images: ImageSettings | Unset = UNSET,
        terminal: TerminalSettings | Unset = UNSET,
        markdown: MarkdownSettings | Unset = UNSET,
        warnings: WarningSettings | Unset = UNSET,
        method: MethodSettings | Mapping[str, object] | Unset = UNSET,
        permissions: PermissionSettings | Mapping[str, object] | Unset = UNSET,
        tools: ToolSettings | Mapping[str, object] | Unset = UNSET,
        sandbox: SandboxSettings | Mapping[str, object] | Unset = UNSET,
        statusline: StatusLineControlSettings | Mapping[str, object] | Unset = UNSET,
        session_dir: str | None | Unset = UNSET,
        resource_roots: Iterable[str] | Unset = UNSET,
        package_roots: Iterable[str] | Unset = UNSET,
        package_sources: Iterable[PackageSourceConfig | str | Mapping[str, object]]
        | Unset = UNSET,
        plugin_sources: Iterable[str] | Unset = UNSET,
        disabled_skills: Iterable[str] | Unset = UNSET,
        disabled_plugins: Iterable[str] | Unset = UNSET,
    ) -> None:
        patch = build_settings_patch(
            AgentSettingsUpdate(
                default_model=default_model,
                thinking_level=thinking_level,
                steering_mode=steering_mode,
                follow_up_mode=follow_up_mode,
                theme=theme,
                system_prompt=system_prompt,
                hide_thinking_block=hide_thinking_block,
                shell_path=shell_path,
                quiet_startup=quiet_startup,
                shell_command_prefix=shell_command_prefix,
                npm_command=npm_command,
                collapse_changelog=collapse_changelog,
                enable_install_telemetry=enable_install_telemetry,
                enable_skill_commands=enable_skill_commands,
                enabled_models=enabled_models,
                double_escape_action=double_escape_action,
                tree_filter_mode=tree_filter_mode,
                show_hardware_cursor=show_hardware_cursor,
                editor_padding_x=editor_padding_x,
                autocomplete_max_visible=autocomplete_max_visible,
                keybindings=keybindings,
                capabilities=capabilities,
                thinking_budgets=thinking_budgets,
                compaction=compaction,
                branch_summary=branch_summary,
                retry=retry,
                images=images,
                terminal=terminal,
                markdown=markdown,
                warnings=warnings,
                method=method,
                permissions=permissions,
                tools=tools,
                sandbox=sandbox,
                statusline=statusline,
                session_dir=session_dir,
                resource_roots=resource_roots,
                package_roots=package_roots,
                package_sources=package_sources,
                plugin_sources=plugin_sources,
                disabled_skills=disabled_skills,
                disabled_plugins=disabled_plugins,
            )
        )

        layer = scope if scope in {"global", "project"} else "session"
        self._config.update(layer, patch)

    def set_default_model(
        self, selection: ModelSelection | None, *, scope: SettingsScope = "session"
    ) -> None:
        self.update_settings(scope=scope, default_model=selection)

    def set_steering_mode(
        self, mode: QueueMode, *, scope: SettingsScope = "session"
    ) -> None:
        self.update_settings(scope=scope, steering_mode=mode)

    def set_follow_up_mode(
        self, mode: QueueMode, *, scope: SettingsScope = "session"
    ) -> None:
        self.update_settings(scope=scope, follow_up_mode=mode)

    def get_theme(self) -> str | None:
        return self._settings.theme

    def set_theme(self, theme: str | None, *, scope: SettingsScope = "global") -> None:
        self.update_settings(scope=scope, theme=theme)

    def get_hide_thinking_block(self) -> bool:
        return self._settings.hide_thinking_block

    def set_hide_thinking_block(
        self, hide: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, hide_thinking_block=hide)

    def get_shell_path(self) -> str | None:
        return self._settings.shell_path

    def set_shell_path(
        self, path: str | None, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, shell_path=path)

    def get_quiet_startup(self) -> bool:
        return self._settings.quiet_startup

    def set_quiet_startup(
        self, quiet: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, quiet_startup=quiet)

    def get_shell_command_prefix(self) -> str | None:
        return self._settings.shell_command_prefix

    def set_shell_command_prefix(
        self, prefix: str | None, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, shell_command_prefix=prefix)

    def get_npm_command(self) -> list[str] | None:
        return (
            list(self._settings.npm_command)
            if self._settings.npm_command is not None
            else None
        )

    def set_npm_command(
        self, command: Sequence[str] | None, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, npm_command=command)

    def get_collapse_changelog(self) -> bool:
        return self._settings.collapse_changelog

    def set_collapse_changelog(
        self, collapse: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, collapse_changelog=collapse)

    def get_enable_install_telemetry(self) -> bool:
        return self._settings.enable_install_telemetry

    def set_enable_install_telemetry(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, enable_install_telemetry=enabled)

    def get_enable_skill_commands(self) -> bool:
        return self._settings.enable_skill_commands

    def set_enable_skill_commands(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, enable_skill_commands=enabled)

    def get_enabled_models(self) -> list[str] | None:
        return (
            list(self._settings.enabled_models)
            if self._settings.enabled_models is not None
            else None
        )

    def set_enabled_models(
        self, patterns: Sequence[str] | None, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, enabled_models=patterns)

    def get_double_escape_action(self) -> DoubleEscapeAction:
        return self._settings.double_escape_action

    def set_double_escape_action(
        self, action: DoubleEscapeAction, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, double_escape_action=action)

    def get_tree_filter_mode(self) -> TreeFilterMode:
        return self._settings.tree_filter_mode

    def set_tree_filter_mode(
        self, mode: TreeFilterMode, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, tree_filter_mode=mode)

    def get_show_hardware_cursor(self) -> bool:
        return self._settings.show_hardware_cursor

    def set_show_hardware_cursor(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, show_hardware_cursor=enabled)

    def get_editor_padding_x(self) -> int:
        return self._settings.editor_padding_x

    def set_editor_padding_x(
        self, padding: float | int, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, editor_padding_x=padding)

    def get_autocomplete_max_visible(self) -> int:
        return self._settings.autocomplete_max_visible

    def set_autocomplete_max_visible(
        self, max_visible: float | int, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, autocomplete_max_visible=max_visible)

    def get_keybindings(self) -> dict[str, KeybindingValue]:
        return dict(self._settings.keybindings)

    def set_keybindings(
        self, keybindings: Mapping[str, object], *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, keybindings=keybindings)

    def get_thinking_budgets(self) -> ThinkingBudgetMap | None:
        return deepcopy(self._settings.thinking_budgets)

    def get_compaction_settings(self) -> CompactionSettings:
        return self._settings.compaction

    def get_branch_summary_settings(self) -> BranchSummarySettings:
        return self._settings.branch_summary

    def get_branch_summary_skip_prompt(self) -> bool:
        return self._settings.branch_summary.skip_prompt

    def get_provider_retry_settings(self) -> dict[str, int | None]:
        retry = self._settings.retry
        return {
            "timeout_ms": retry.provider_timeout_ms,
            "max_retries": retry.provider_max_retries,
            "max_retry_delay_ms": retry.provider_max_retry_delay_ms,
        }

    def get_show_images(self) -> bool:
        return self._settings.terminal.show_images

    def set_show_images(self, show: bool, *, scope: SettingsScope = "global") -> None:
        self.update_settings(
            scope=scope, terminal=replace(self._settings.terminal, show_images=show)
        )

    def get_image_width_cells(self) -> int:
        return max(1, int(self._settings.terminal.image_width_cells))

    def set_image_width_cells(
        self, width: float | int, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(
            scope=scope,
            terminal=replace(
                self._settings.terminal, image_width_cells=max(1, int(width))
            ),
        )

    def get_clear_on_shrink(self) -> bool:
        return self._settings.terminal.clear_on_shrink

    def set_clear_on_shrink(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(
            scope=scope,
            terminal=replace(self._settings.terminal, clear_on_shrink=enabled),
        )

    def get_show_terminal_progress(self) -> bool:
        return self._settings.terminal.show_terminal_progress

    def set_show_terminal_progress(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(
            scope=scope,
            terminal=replace(self._settings.terminal, show_terminal_progress=enabled),
        )

    def get_image_auto_resize(self) -> bool:
        return self._settings.images.auto_resize

    def set_image_auto_resize(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(
            scope=scope, images=replace(self._settings.images, auto_resize=enabled)
        )

    def get_block_images(self) -> bool:
        return self._settings.images.block_images

    def set_block_images(
        self, enabled: bool, *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(
            scope=scope, images=replace(self._settings.images, block_images=enabled)
        )

    def get_image_settings(self) -> ImageSettings:
        return self._settings.images

    def get_terminal_settings(self) -> TerminalSettings:
        return self._settings.terminal

    def get_markdown_settings(self) -> MarkdownSettings:
        return self._settings.markdown

    def get_code_block_indent(self) -> str:
        return self._settings.markdown.code_block_indent

    def get_warnings(self) -> WarningSettings:
        return self._settings.warnings

    def get_method_settings(self) -> MethodSettings:
        return self._settings.method

    def set_method_settings(
        self,
        settings: MethodSettings | Mapping[str, object],
        *,
        scope: SettingsScope = "global",
    ) -> None:
        self.update_settings(scope=scope, method=settings)

    def get_permission_profile_id(self) -> PermissionProfileId:
        return self._settings.permissions.profile

    def get_permission_profile_ceiling(self) -> PermissionProfileCeiling:
        return self._permission_profile_ceiling

    def get_permission_profile_snapshot(self) -> PermissionProfileSnapshot:
        return permission_profile_snapshot(
            self.get_permission_profile_id(),
            self._permission_profile_ceiling,
        )

    def set_permission_profile(
        self,
        profile_id: PermissionProfileId | str,
        *,
        scope: PermissionProfileScope = "session",
    ) -> None:
        resolved_id = permission_profile(profile_id).profile_id
        if not self._permission_profile_ceiling.allows(resolved_id):
            raise PermissionError(
                self._permission_profile_ceiling.reason
                or (
                    "Permission profile is disabled by the managed ceiling: "
                    f"{resolved_id}"
                )
            )
        settings_scope: SettingsScope = (
            "global" if scope == "user" else cast(SettingsScope, scope)
        )
        settings = PermissionSettings(profile=resolved_id)
        self.update_settings(scope=settings_scope, permissions=settings)

    def get_tool_settings(self) -> ToolSettings:
        return self._settings.tools

    def get_sandbox_settings(self) -> SandboxSettings:
        return self._settings.sandbox

    def set_sandbox_settings(
        self,
        settings: SandboxSettings | Mapping[str, object],
        *,
        scope: SettingsScope = "global",
    ) -> None:
        self.update_settings(scope=scope, sandbox=settings)

    def get_statusline_settings(self) -> StatusLineControlSettings:
        return self._settings.statusline

    def set_statusline_settings(
        self,
        settings: StatusLineControlSettings | Mapping[str, object],
        *,
        scope: SettingsScope = "global",
    ) -> None:
        self.update_settings(scope=scope, statusline=settings)

    def get_external_tool_policy(self) -> ExternalToolPolicy:
        return self._settings.tools.external_tool_policy

    def set_external_tool_policy(
        self,
        policy: ExternalToolPolicy,
        *,
        scope: SettingsScope = "global",
    ) -> None:
        self.update_settings(
            scope=scope,
            tools=replace(
                self._settings.tools,
                external_tool_policy=policy,
            ),
        )

    def get_retry_settings(self) -> RetrySettings:
        return self._settings.retry

    def get_retry_enabled(self) -> bool:
        return self._settings.retry.enabled

    def set_retry_enabled(
        self, enabled: bool, *, scope: SettingsScope = "session"
    ) -> None:
        self.update_settings(
            scope=scope, retry=replace(self._settings.retry, enabled=enabled)
        )

    def get_resource_roots(self) -> list[str]:
        return list(self._settings.resource_roots)

    def set_resource_roots(
        self, roots: Iterable[str], *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, resource_roots=roots)

    def get_package_roots(self) -> list[str]:
        return list(self._settings.package_roots)

    def set_package_roots(
        self, roots: Iterable[str], *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, package_roots=roots)

    def get_package_sources(self) -> list[PackageSourceConfig]:
        return list(self._settings.package_sources)

    def set_package_sources(
        self,
        sources: Iterable[PackageSourceConfig | str | Mapping[str, object]],
        *,
        scope: SettingsScope = "global",
    ) -> None:
        self.update_settings(scope=scope, package_sources=sources)

    def add_package_source(
        self,
        source: PackageSourceConfig | str | Mapping[str, object],
        *,
        scope: SettingsScope = "project",
    ) -> bool:
        candidate = decode_package_source(source)
        current_sources = self._settings.package_sources
        next_sources = _with_package_source(current_sources, candidate)
        self.update_settings(scope=scope, package_sources=next_sources)
        return next_sources != current_sources

    def remove_package_source(
        self, source: str, *, scope: SettingsScope = "project"
    ) -> bool:
        current_sources = self._settings.package_sources
        next_sources = _without_package_source(current_sources, source)
        self.update_settings(scope=scope, package_sources=next_sources)
        return next_sources != current_sources

    def get_plugin_sources(self) -> list[str]:
        return list(self._settings.plugin_sources)

    def set_plugin_sources(
        self, sources: Iterable[str], *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, plugin_sources=sources)

    def get_disabled_skills(self) -> list[str]:
        return list(self._settings.disabled_skills)

    def set_disabled_skills(
        self, names: Iterable[str], *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, disabled_skills=names)

    def get_disabled_plugins(self) -> list[str]:
        return list(self._settings.disabled_plugins)

    def set_disabled_plugins(
        self, names: Iterable[str], *, scope: SettingsScope = "global"
    ) -> None:
        self.update_settings(scope=scope, disabled_plugins=names)

    def add_plugin_source(
        self, source: str, *, scope: SettingsScope = "project"
    ) -> bool:
        current_sources = self._settings.plugin_sources
        next_sources = _with_name(current_sources, source)
        self.update_settings(scope=scope, plugin_sources=next_sources)
        return next_sources != current_sources

    def remove_plugin_source(
        self, source: str, *, scope: SettingsScope = "project"
    ) -> bool:
        current_sources = self._settings.plugin_sources
        next_sources = _without_name(current_sources, source)
        self.update_settings(scope=scope, plugin_sources=next_sources)
        return next_sources != current_sources

    def enable_skill(self, name: str, *, scope: SettingsScope = "project") -> None:
        self.update_settings(
            scope=scope,
            disabled_skills=_without_name(self._settings.disabled_skills, name),
        )

    def disable_skill(self, name: str, *, scope: SettingsScope = "project") -> None:
        self.update_settings(
            scope=scope,
            disabled_skills=_with_name(self._settings.disabled_skills, name),
        )

    def enable_plugin(self, name: str, *, scope: SettingsScope = "project") -> None:
        self.update_settings(
            scope=scope,
            disabled_plugins=_without_name(self._settings.disabled_plugins, name),
        )

    def disable_plugin(self, name: str, *, scope: SettingsScope = "project") -> None:
        self.update_settings(
            scope=scope,
            disabled_plugins=_with_name(self._settings.disabled_plugins, name),
        )

    def get_settings(self) -> ControlConfig:
        return self._settings

    def get_setting(self, key: str) -> object | None:
        return getattr(self._settings, key, None)

    def get_global_settings(self) -> dict[str, Any]:
        return self._config.scope("global").patch

    def get_project_settings(self) -> dict[str, Any]:
        return self._config.scope("project").patch

    def get_session_settings(self) -> dict[str, Any]:
        return self._config.scope("session").patch

    def subscribe(self, listener: SettingsListener) -> Callable[[], None]:
        return self._config.subscribe(listener)


def _with_name(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    normalized = name.strip()
    if not normalized or normalized in values:
        return values
    return (*values, normalized)


def _without_name(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    normalized = name.strip()
    return tuple(value for value in values if value != normalized)


def _package_identity_key(source: str) -> str:
    return package_source_match_key(source.strip())


def _with_package_source(
    values: tuple[PackageSourceConfig, ...],
    candidate: PackageSourceConfig,
) -> tuple[PackageSourceConfig, ...]:
    normalized = candidate.source.strip()
    if not normalized:
        return values
    candidate = replace(candidate, source=normalized)
    candidate_key = _package_identity_key(candidate.source)
    for existing in values:
        if _package_identity_key(existing.source) == candidate_key:
            return values
    return (*values, candidate)


def _without_package_source(
    values: tuple[PackageSourceConfig, ...], source: str
) -> tuple[PackageSourceConfig, ...]:
    normalized = source.strip()
    if not normalized:
        return values
    target_key = _package_identity_key(normalized)
    return tuple(
        value for value in values if _package_identity_key(value.source) != target_key
    )
