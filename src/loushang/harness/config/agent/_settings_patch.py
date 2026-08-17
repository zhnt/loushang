"""Typed Agent settings updates and session override preparation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from loushang.agent import ThinkingLevel
from loushang.ai.model import ModelSelection
from loushang.harness.config.agent._settings_codec import (
    _REMOVED_SETTING_MESSAGES,
    _bool_value,
    _bounded_int,
    _deserialize_capability_mounts,
    _deserialize_double_escape_action,
    _deserialize_keybindings,
    _deserialize_queue_mode,
    _deserialize_tree_filter_mode,
    _non_negative_small_int,
    _normalize_package_source_sequence,
    _normalize_string_sequence,
    _optional_string,
    _serialize_keybindings,
    _serialize_model_selection,
    _serialize_package_source,
    _serialize_settings_slice,
    _serialize_statusline_settings,
    _serialize_tool_settings,
    _string_tuple_or_none,
    _thinking_budgets,
)
from loushang.harness.config.agent.types import (
    BranchSummarySettings,
    CapabilityMountMode,
    CompactionSettings,
    DoubleEscapeAction,
    ImageSettings,
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
from loushang.harness.resources.packages.source import PackageSourceConfig


class Unset:
    """Sentinel type distinguishing omitted updates from explicit null values."""

    __slots__ = ()


UNSET = Unset()


@dataclass(frozen=True)
class AgentSettingsUpdate:
    """One typed update command before conversion to a raw layer patch."""

    default_model: ModelSelection | None | Unset = UNSET
    thinking_level: ThinkingLevel | Unset = UNSET
    steering_mode: QueueMode | Unset = UNSET
    follow_up_mode: QueueMode | Unset = UNSET
    theme: str | None | Unset = UNSET
    system_prompt: str | Unset = UNSET
    hide_thinking_block: bool | Unset = UNSET
    shell_path: str | None | Unset = UNSET
    quiet_startup: bool | Unset = UNSET
    shell_command_prefix: str | None | Unset = UNSET
    npm_command: Sequence[str] | None | Unset = UNSET
    collapse_changelog: bool | Unset = UNSET
    enable_install_telemetry: bool | Unset = UNSET
    enable_skill_commands: bool | Unset = UNSET
    enabled_models: Sequence[str] | None | Unset = UNSET
    double_escape_action: DoubleEscapeAction | Unset = UNSET
    tree_filter_mode: TreeFilterMode | Unset = UNSET
    show_hardware_cursor: bool | Unset = UNSET
    editor_padding_x: float | int | Unset = UNSET
    autocomplete_max_visible: float | int | Unset = UNSET
    keybindings: Mapping[str, object] | Unset = UNSET
    capabilities: Mapping[str, CapabilityMountMode] | Unset = UNSET
    thinking_budgets: ThinkingBudgetMap | None | Unset = UNSET
    compaction: CompactionSettings | Unset = UNSET
    branch_summary: BranchSummarySettings | Unset = UNSET
    retry: RetrySettings | Unset = UNSET
    images: ImageSettings | Unset = UNSET
    terminal: TerminalSettings | Unset = UNSET
    markdown: MarkdownSettings | Unset = UNSET
    warnings: WarningSettings | Unset = UNSET
    method: MethodSettings | Mapping[str, object] | Unset = UNSET
    permissions: PermissionSettings | Mapping[str, object] | Unset = UNSET
    tools: ToolSettings | Mapping[str, object] | Unset = UNSET
    sandbox: SandboxSettings | Mapping[str, object] | Unset = UNSET
    statusline: StatusLineControlSettings | Mapping[str, object] | Unset = UNSET
    session_dir: str | None | Unset = UNSET
    resource_roots: Iterable[str] | Unset = UNSET
    package_roots: Iterable[str] | Unset = UNSET
    package_sources: (
        Iterable[PackageSourceConfig | str | Mapping[str, object]] | Unset
    ) = UNSET
    plugin_sources: Iterable[str] | Unset = UNSET
    disabled_skills: Iterable[str] | Unset = UNSET
    disabled_plugins: Iterable[str] | Unset = UNSET


def build_settings_patch(update: AgentSettingsUpdate) -> dict[str, Any]:
    """Validate and serialize one typed update into a raw layer patch."""

    patch: dict[str, Any] = {}
    if not isinstance(update.default_model, Unset):
        patch["default_model"] = _serialize_model_selection(update.default_model)
    if update.thinking_level is not UNSET:
        patch["thinking_level"] = update.thinking_level
    if update.steering_mode is not UNSET:
        patch["steering_mode"] = _deserialize_queue_mode(
            update.steering_mode, "steering_mode"
        )
    if update.follow_up_mode is not UNSET:
        patch["follow_up_mode"] = _deserialize_queue_mode(
            update.follow_up_mode, "follow_up_mode"
        )
    if update.theme is not UNSET:
        patch["theme"] = _optional_string(update.theme, "theme")
    if update.system_prompt is not UNSET:
        patch["system_prompt"] = update.system_prompt
    if update.hide_thinking_block is not UNSET:
        patch["hide_thinking_block"] = _bool_value(
            update.hide_thinking_block, "hide_thinking_block"
        )
    if update.shell_path is not UNSET:
        patch["shell_path"] = _optional_string(update.shell_path, "shell_path")
    if update.quiet_startup is not UNSET:
        patch["quiet_startup"] = _bool_value(update.quiet_startup, "quiet_startup")
    if update.shell_command_prefix is not UNSET:
        patch["shell_command_prefix"] = _optional_string(
            update.shell_command_prefix, "shell_command_prefix"
        )
    if update.npm_command is not UNSET:
        normalized_npm_command = _string_tuple_or_none(
            update.npm_command, "npm_command"
        )
        patch["npm_command"] = (
            list(normalized_npm_command)
            if normalized_npm_command is not None
            else None
        )
    if update.collapse_changelog is not UNSET:
        patch["collapse_changelog"] = _bool_value(
            update.collapse_changelog, "collapse_changelog"
        )
    if update.enable_install_telemetry is not UNSET:
        patch["enable_install_telemetry"] = _bool_value(
            update.enable_install_telemetry, "enable_install_telemetry"
        )
    if update.enable_skill_commands is not UNSET:
        patch["enable_skill_commands"] = _bool_value(
            update.enable_skill_commands, "enable_skill_commands"
        )
    if update.enabled_models is not UNSET:
        normalized_enabled_models = _string_tuple_or_none(
            update.enabled_models, "enabled_models"
        )
        patch["enabled_models"] = (
            list(normalized_enabled_models)
            if normalized_enabled_models is not None
            else None
        )
    if update.double_escape_action is not UNSET:
        patch["double_escape_action"] = _deserialize_double_escape_action(
            update.double_escape_action
        )
    if update.tree_filter_mode is not UNSET:
        patch["tree_filter_mode"] = _deserialize_tree_filter_mode(
            update.tree_filter_mode
        )
    if update.show_hardware_cursor is not UNSET:
        patch["show_hardware_cursor"] = _bool_value(
            update.show_hardware_cursor, "show_hardware_cursor"
        )
    if update.editor_padding_x is not UNSET:
        patch["editor_padding_x"] = _non_negative_small_int(
            update.editor_padding_x, "editor_padding_x", upper_bound=3
        )
    if update.autocomplete_max_visible is not UNSET:
        patch["autocomplete_max_visible"] = _bounded_int(
            update.autocomplete_max_visible,
            "autocomplete_max_visible",
            lower_bound=3,
            upper_bound=20,
        )
    if update.keybindings is not UNSET:
        patch["keybindings"] = _serialize_keybindings(
            _deserialize_keybindings(update.keybindings)
        )
    if update.capabilities is not UNSET:
        patch["capabilities"] = _deserialize_capability_mounts(update.capabilities)
    if update.thinking_budgets is not UNSET:
        patch["thinking_budgets"] = _thinking_budgets(update.thinking_budgets)
    if update.compaction is not UNSET:
        patch["compaction"] = _serialize_settings_slice(update.compaction)
    if update.branch_summary is not UNSET:
        patch["branch_summary"] = _serialize_settings_slice(update.branch_summary)
    if update.retry is not UNSET:
        patch["retry"] = _serialize_settings_slice(update.retry)
    if update.images is not UNSET:
        patch["images"] = _serialize_settings_slice(update.images)
    if update.terminal is not UNSET:
        patch["terminal"] = _serialize_settings_slice(update.terminal)
    if update.markdown is not UNSET:
        patch["markdown"] = _serialize_settings_slice(update.markdown)
    if update.warnings is not UNSET:
        patch["warnings"] = _serialize_settings_slice(update.warnings)
    if update.method is not UNSET:
        patch["method"] = _serialize_settings_slice(update.method)
    if update.permissions is not UNSET:
        patch["permissions"] = _serialize_settings_slice(update.permissions)
    if update.tools is not UNSET:
        patch["tools"] = _serialize_tool_settings(update.tools)
    if update.sandbox is not UNSET:
        patch["sandbox"] = _serialize_settings_slice(update.sandbox)
    if update.statusline is not UNSET:
        patch["statusline"] = _serialize_statusline_settings(update.statusline)
    if update.session_dir is not UNSET:
        patch["session_dir"] = update.session_dir
    if not isinstance(update.resource_roots, Unset):
        patch["resource_roots"] = list(
            _normalize_string_sequence(update.resource_roots, "resource_roots")
        )
    if not isinstance(update.package_roots, Unset):
        patch["package_roots"] = list(
            _normalize_string_sequence(update.package_roots, "package_roots")
        )
    if not isinstance(update.package_sources, Unset):
        patch["packages"] = [
            _serialize_package_source(source)
            for source in _normalize_package_source_sequence(
                list(update.package_sources), "package_sources"
            )
        ]
    if not isinstance(update.plugin_sources, Unset):
        patch["plugin_sources"] = list(
            _normalize_string_sequence(update.plugin_sources, "plugin_sources")
        )
    if not isinstance(update.disabled_skills, Unset):
        patch["disabled_skills"] = list(
            _normalize_string_sequence(update.disabled_skills, "disabled_skills")
        )
    if not isinstance(update.disabled_plugins, Unset):
        patch["disabled_plugins"] = list(
            _normalize_string_sequence(update.disabled_plugins, "disabled_plugins")
        )
    return patch


def prepare_override_patch(
    patch: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Drop removed session overrides while returning their adapter messages."""

    prepared = dict(patch)
    messages: list[str] = []
    for key, message in _REMOVED_SETTING_MESSAGES.items():
        if key not in prepared:
            continue
        prepared.pop(key)
        messages.append(message)
    return prepared, tuple(messages)
