"""Serialization and patch codecs for standard Agent settings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass, replace
from typing import Any, Literal, cast

from loushang.ai.model import ModelSelection
from loushang.harness.config import (
    ConfigFieldSpec,
    SchemaConfigCodec,
    decode_dataclass_patch,
    encode_dataclass_diff,
)
from loushang.harness.config.agent.types import (
    CapabilityMountMode,
    ControlConfig,
    DoubleEscapeAction,
    ExternalToolPolicy,
    HeadlessApprovalMode,
    KeybindingValue,
    PermissionSettings,
    QueueMode,
    StatusLineAutoValue,
    StatusLineControlSettings,
    StatusLineSeparator,
    StatusLineStyle,
    ThinkingBudgetMap,
    ToolSettings,
    TreeFilterMode,
)
from loushang.harness.permissions import (
    PermissionProfileId,
    permission_profile,
)
from loushang.harness.resources.packages.source import (
    PackageSourceConfig,
)

ThinkingBudgetKey = Literal["minimal", "low", "medium", "high"]


_REMOVED_SETTING_MESSAGES = {
    "transport": "transport setting has been removed; use provider/contrib-specific configuration instead",
}


def _normalize_string_sequence(
    value: Iterable[str], field_name: str
) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings, not a string")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field_name} must only contain strings")
        normalized.append(item)
    return tuple(normalized)


def _normalize_package_source_sequence(
    value: object, field_name: str = "packages"
) -> tuple[PackageSourceConfig, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(_deserialize_package_source(item) for item in value)


def _deserialize_package_source(value: object) -> PackageSourceConfig:
    if isinstance(value, PackageSourceConfig):
        return value
    if isinstance(value, str):
        return PackageSourceConfig(source=value)
    if not isinstance(value, Mapping):
        raise TypeError("package source entries must be strings or objects")
    source = value.get("source")
    if not isinstance(source, str) or not source:
        raise TypeError("package source object must include a non-empty string source")
    return PackageSourceConfig(
        source=source,
        extensions=_optional_string_tuple(value.get("extensions"), "extensions"),
        skills=_optional_string_tuple(value.get("skills"), "skills"),
        prompts=_optional_string_tuple(value.get("prompts"), "prompts"),
        themes=_optional_string_tuple(value.get("themes"), "themes"),
    )


def _optional_string_tuple(value: object, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings")
    return _normalize_string_sequence(value, field_name)


def _serialize_package_source(source: PackageSourceConfig) -> str | dict[str, object]:
    if not source.filtered:
        return source.source
    payload: dict[str, object] = {"source": source.source}
    if source.extensions is not None:
        payload["extensions"] = list(source.extensions)
    if source.skills is not None:
        payload["skills"] = list(source.skills)
    if source.prompts is not None:
        payload["prompts"] = list(source.prompts)
    if source.themes is not None:
        payload["themes"] = list(source.themes)
    return payload


def _serialize_model_selection(
    selection: ModelSelection | None,
) -> dict[str, str] | None:
    if selection is None:
        return None
    return {
        "provider": selection.provider,
        "endpoint_id": selection.endpoint_id,
        "model_id": selection.model_id,
    }


def _deserialize_model_selection(value: object) -> ModelSelection | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("default_model must be a JSON object or null")
    provider = value.get("provider")
    endpoint_id = value.get("endpoint_id") or value.get("endpointId")
    model_id = value.get("model_id")
    if (
        not isinstance(provider, str)
        or not isinstance(endpoint_id, str)
        or not isinstance(model_id, str)
    ):
        raise TypeError(
            "default_model must include string provider, endpoint_id, and model_id values"
        )
    return ModelSelection(
        provider=provider,
        endpoint_id=endpoint_id,
        model_id=model_id,
    )


def _deserialize_queue_mode(value: object, field_name: str) -> QueueMode:
    if value not in {"all", "one-at-a-time"}:
        raise ValueError(f"{field_name} must be 'all' or 'one-at-a-time'")
    return cast(QueueMode, value)


def _deserialize_double_escape_action(value: object) -> DoubleEscapeAction:
    if value not in {"fork", "tree", "none"}:
        raise ValueError("double_escape_action must be 'fork', 'tree', or 'none'")
    return cast(DoubleEscapeAction, value)


def _deserialize_tree_filter_mode(value: object) -> TreeFilterMode:
    if value not in {"default", "no-tools", "user-only", "labeled-only", "all"}:
        raise ValueError(
            "tree_filter_mode must be 'default', 'no-tools', 'user-only', 'labeled-only', or 'all'"
        )
    return cast(TreeFilterMode, value)


def _deserialize_external_tool_policy(value: object) -> ExternalToolPolicy:
    if value not in {"never", "auto", "required"}:
        raise ValueError("external_tool_policy must be 'never', 'auto', or 'required'")
    return cast(ExternalToolPolicy, value)


def _deserialize_headless_approval_mode(value: object) -> HeadlessApprovalMode | None:
    if value is None:
        return None
    if value not in {"allow", "deny"}:
        raise ValueError("approval_mode must be 'allow', 'deny', or null")
    return cast(HeadlessApprovalMode, value)


def _deserialize_capability_mounts(
    value: object,
) -> dict[str, CapabilityMountMode]:
    if not isinstance(value, Mapping):
        raise TypeError("capabilities must be a JSON object")
    normalized: dict[str, CapabilityMountMode] = {}
    for capability, mode in value.items():
        if not isinstance(capability, str) or not capability.strip():
            raise TypeError("capability ids must be non-empty strings")
        if mode not in {"disabled", "on_demand", "always"}:
            raise ValueError(
                f"capabilities.{capability} must be 'disabled', "
                "'on_demand', or 'always'"
            )
        normalized[capability.strip()] = cast(CapabilityMountMode, mode)
    return normalized


def _decode_capability_mount_overlay(
    value: object,
    current: object,
) -> dict[str, CapabilityMountMode]:
    existing = (
        dict(cast(Mapping[str, CapabilityMountMode], current))
        if isinstance(current, Mapping)
        else {}
    )
    existing.update(_deserialize_capability_mounts(value))
    return existing


def _deserialize_permission_profile(value: object) -> PermissionProfileId:
    if not isinstance(value, str):
        raise TypeError("permissions.profile must be a string")
    permission_profile(value)
    return cast(PermissionProfileId, value)


def _deserialize_statusline_auto_value(
    value: object, field_name: str
) -> StatusLineAutoValue:
    if value not in {"auto", "true", "false"}:
        raise ValueError(f"{field_name} must be 'auto', 'true', or 'false'")
    return cast(StatusLineAutoValue, value)


def _deserialize_statusline_separator(
    value: object, field_name: str
) -> StatusLineSeparator:
    if value not in {"pipe", "dot"}:
        raise ValueError(f"{field_name} must be 'pipe' or 'dot'")
    return cast(StatusLineSeparator, value)


def _deserialize_statusline_style(value: object, field_name: str) -> StatusLineStyle:
    if value not in {"codex-like", "muted", "plain"}:
        raise ValueError(f"{field_name} must be 'codex-like', 'muted', or 'plain'")
    return cast(StatusLineStyle, value)


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or null")
    return value


def _bool_value(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _string_tuple_or_none(value: object, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings or null")
    return _normalize_string_sequence(value, field_name)


def _deserialize_keybindings(value: object) -> dict[str, KeybindingValue]:
    if not isinstance(value, Mapping):
        raise TypeError("keybindings must be a JSON object")
    normalized: dict[str, KeybindingValue] = {}
    for action, keys in value.items():
        if not isinstance(action, str):
            raise TypeError("keybinding action ids must be strings")
        if keys is None:
            normalized[action] = None
            continue
        if isinstance(keys, str):
            normalized[action] = keys
            continue
        normalized[action] = _normalize_string_sequence(keys, f"keybindings.{action}")
    return normalized


def _serialize_keybindings(value: Mapping[str, KeybindingValue]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for action, keys in value.items():
        serialized[action] = list(keys) if isinstance(keys, tuple) else keys
    return serialized


def _non_negative_small_int(
    value: object, field_name: str, *, upper_bound: int | None = None
) -> int:
    if not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a number")
    coerced = max(0, int(value))
    if upper_bound is not None:
        coerced = min(upper_bound, coerced)
    return coerced


def _bounded_int(
    value: object, field_name: str, *, lower_bound: int, upper_bound: int
) -> int:
    if not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a number")
    return max(lower_bound, min(upper_bound, int(value)))


def _thinking_budgets(value: object) -> ThinkingBudgetMap | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("thinking_budgets must be a JSON object or null")
    normalized: ThinkingBudgetMap = {}
    for key, item in value.items():
        if key not in {"minimal", "low", "medium", "high"}:
            raise ValueError(
                "thinking_budgets may only contain minimal, low, medium, or high"
            )
        if not isinstance(item, int):
            raise TypeError("thinking_budgets values must be integers")
        normalized[cast(ThinkingBudgetKey, key)] = item
    return normalized


def _serialize_settings_slice(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return _serialize_dataclass_slice(value)


def _serialize_tool_settings(value: object) -> dict[str, Any]:
    if isinstance(value, ToolSettings):
        return {
            "external_tool_policy": _deserialize_external_tool_policy(
                value.external_tool_policy
            ),
            "blocked_tools": list(value.blocked_tools),
            "ask_tools": list(value.ask_tools),
            "blocked_capabilities": list(value.blocked_capabilities),
            "ask_capabilities": list(value.ask_capabilities),
            "blocked_substrings": list(value.blocked_substrings),
            "ask_substrings": list(value.ask_substrings),
            "blocked_path_substrings": list(value.blocked_path_substrings),
            "ask_path_substrings": list(value.ask_path_substrings),
            "approval_mode": _deserialize_headless_approval_mode(value.approval_mode),
            "approval_reason": value.approval_reason,
        }
    if not isinstance(value, Mapping):
        raise TypeError("tools must be a JSON object")
    patch = dict(value)
    if "external_tool_policy" in patch:
        patch["external_tool_policy"] = _deserialize_external_tool_policy(
            patch["external_tool_policy"]
        )
    for key in (
        "blocked_tools",
        "ask_tools",
        "blocked_capabilities",
        "ask_capabilities",
        "blocked_substrings",
        "ask_substrings",
        "blocked_path_substrings",
        "ask_path_substrings",
    ):
        if key in patch:
            patch[key] = list(_normalize_string_sequence(patch[key], key))
    if "approval_mode" in patch:
        patch["approval_mode"] = _deserialize_headless_approval_mode(
            patch["approval_mode"]
        )
    if "approval_reason" in patch:
        patch["approval_reason"] = _optional_string(
            patch["approval_reason"], "approval_reason"
        )
    return patch


def _serialize_statusline_settings(value: object) -> dict[str, Any]:
    if isinstance(value, StatusLineControlSettings):
        return _serialize_dataclass_slice(value)
    if not isinstance(value, Mapping):
        raise TypeError("statusline must be a JSON object")
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        field_name = f"statusline.{key}"
        if key in {
            "enabled",
            "model",
            "workspace",
            "branch",
            "session",
            "permissions",
            "runtime",
        }:
            normalized[key] = _bool_value(item, field_name)
        elif key in {"queue", "message"}:
            normalized[key] = _deserialize_statusline_auto_value(item, field_name)
        elif key == "separator":
            normalized[key] = _deserialize_statusline_separator(item, field_name)
        elif key == "style":
            normalized[key] = _deserialize_statusline_style(item, field_name)
        else:
            raise ValueError(f"Unknown statusline setting: {field_name}")
    return normalized


def _serialize_dataclass_slice(value: object) -> dict[str, Any]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("settings slice must be a dataclass or mapping")
    return dict(asdict(cast(Any, value)))


def control_config_to_patch(config: ControlConfig) -> dict[str, Any]:
    return dict(CONTROL_CONFIG_CODEC.encode(config))


def decode_package_source(value: object) -> PackageSourceConfig:
    """Strictly decode one package source for SettingsManager collection commands."""

    return _deserialize_package_source(value)


def _apply_dataclass_patch(current: object, patch_value: object, field_name: str):
    return decode_dataclass_patch(
        patch_value,
        current,
        field_name=field_name,
    )


def _apply_tool_settings_patch(
    current: ToolSettings, patch_value: object
) -> ToolSettings:
    if not isinstance(patch_value, Mapping):
        raise TypeError("tools must be a JSON object")
    next_settings = current
    if "external_tool_policy" in patch_value:
        next_settings = replace(
            next_settings,
            external_tool_policy=_deserialize_external_tool_policy(
                patch_value["external_tool_policy"]
            ),
        )
    for key in (
        "blocked_tools",
        "ask_tools",
        "blocked_capabilities",
        "ask_capabilities",
        "blocked_substrings",
        "ask_substrings",
        "blocked_path_substrings",
        "ask_path_substrings",
    ):
        if key in patch_value:
            normalized = _normalize_string_sequence(patch_value[key], key)
            if key == "blocked_tools":
                next_settings = replace(next_settings, blocked_tools=normalized)
            elif key == "ask_tools":
                next_settings = replace(next_settings, ask_tools=normalized)
            elif key == "blocked_capabilities":
                next_settings = replace(
                    next_settings,
                    blocked_capabilities=normalized,
                )
            elif key == "ask_capabilities":
                next_settings = replace(
                    next_settings,
                    ask_capabilities=normalized,
                )
            elif key == "blocked_substrings":
                next_settings = replace(next_settings, blocked_substrings=normalized)
            elif key == "ask_substrings":
                next_settings = replace(next_settings, ask_substrings=normalized)
            elif key == "blocked_path_substrings":
                next_settings = replace(
                    next_settings,
                    blocked_path_substrings=normalized,
                )
            else:
                next_settings = replace(
                    next_settings,
                    ask_path_substrings=normalized,
                )
    if "approval_mode" in patch_value:
        next_settings = replace(
            next_settings,
            approval_mode=_deserialize_headless_approval_mode(
                patch_value["approval_mode"]
            ),
        )
    if "approval_reason" in patch_value:
        next_settings = replace(
            next_settings,
            approval_reason=_optional_string(
                patch_value["approval_reason"], "approval_reason"
            ),
        )
    return next_settings


def _apply_statusline_settings_patch(
    current: StatusLineControlSettings,
    patch_value: object,
) -> StatusLineControlSettings:
    patch = _serialize_statusline_settings(patch_value)
    return replace(current, **patch)


def _apply_permission_settings_patch(
    current: PermissionSettings,
    patch_value: object,
) -> PermissionSettings:
    if not isinstance(patch_value, Mapping):
        raise TypeError("permissions must be a JSON object")
    unknown = set(patch_value) - {"profile"}
    if unknown:
        raise ValueError(
            f"Unknown permission setting: permissions.{sorted(unknown)[0]}"
        )
    if "profile" not in patch_value:
        return current
    return replace(
        current,
        profile=_deserialize_permission_profile(patch_value["profile"]),
    )


def _decode_bool(field_name: str):
    return lambda raw, current: _bool_value(raw, field_name)


def _decode_optional_string(field_name: str):
    return lambda raw, current: _optional_string(raw, field_name)


def _decode_optional_string_tuple(field_name: str):
    return lambda raw, current: _string_tuple_or_none(raw, field_name)


def _decode_string_tuple(field_name: str):
    def decode(raw: object, current: object) -> tuple[str, ...]:
        del current
        if not isinstance(raw, Sequence):
            raise TypeError(f"{field_name} must be a sequence of strings")
        return _normalize_string_sequence(raw, field_name)

    return decode


def _decode_dataclass(field_name: str):
    return lambda raw, current: _apply_dataclass_patch(current, raw, field_name)


def _encode_optional_tuple(current: object, default: object) -> object:
    del default
    return list(cast(Iterable[object], current)) if current is not None else None


def _encode_tuple(current: object, default: object) -> object:
    del default
    return list(cast(tuple[object, ...], current))


def _decode_keybinding_overlay(raw: object, current: object) -> object:
    return {
        **cast(Mapping[str, KeybindingValue], current),
        **_deserialize_keybindings(raw),
    }


def _decode_session_dir(raw: object, current: object) -> object:
    del current
    if raw is not None and not isinstance(raw, str):
        raise TypeError("session_dir must be a string or null")
    return raw


def _decode_package_sources(raw: object, current: object) -> object:
    del current
    return _normalize_package_source_sequence(raw)


def _encode_package_sources(current: object, default: object) -> object:
    del default
    return [
        _serialize_package_source(source)
        for source in cast(tuple[PackageSourceConfig, ...], current)
    ]


CONTROL_CONFIG_CODEC = SchemaConfigCodec(
    default_factory=ControlConfig,
    fields=(
        ConfigFieldSpec(
            "default_model",
            decode=lambda raw, current: _deserialize_model_selection(raw),
            encode=lambda current, default: _serialize_model_selection(
                cast(ModelSelection | None, current)
            ),
        ),
        ConfigFieldSpec("thinking_level"),
        ConfigFieldSpec(
            "steering_mode",
            decode=lambda raw, current: _deserialize_queue_mode(raw, "steering_mode"),
        ),
        ConfigFieldSpec(
            "follow_up_mode",
            decode=lambda raw, current: _deserialize_queue_mode(raw, "follow_up_mode"),
        ),
        ConfigFieldSpec("theme", decode=_decode_optional_string("theme")),
        ConfigFieldSpec("system_prompt"),
        ConfigFieldSpec(
            "hide_thinking_block",
            decode=_decode_bool("hide_thinking_block"),
        ),
        ConfigFieldSpec("shell_path", decode=_decode_optional_string("shell_path")),
        ConfigFieldSpec("quiet_startup", decode=_decode_bool("quiet_startup")),
        ConfigFieldSpec(
            "shell_command_prefix",
            decode=_decode_optional_string("shell_command_prefix"),
        ),
        ConfigFieldSpec(
            "npm_command",
            decode=_decode_optional_string_tuple("npm_command"),
            encode=_encode_optional_tuple,
        ),
        ConfigFieldSpec(
            "collapse_changelog",
            decode=_decode_bool("collapse_changelog"),
        ),
        ConfigFieldSpec(
            "enable_install_telemetry",
            decode=_decode_bool("enable_install_telemetry"),
        ),
        ConfigFieldSpec(
            "enable_skill_commands",
            decode=_decode_bool("enable_skill_commands"),
        ),
        ConfigFieldSpec(
            "enabled_models",
            decode=_decode_optional_string_tuple("enabled_models"),
            encode=_encode_optional_tuple,
        ),
        ConfigFieldSpec(
            "double_escape_action",
            decode=lambda raw, current: _deserialize_double_escape_action(raw),
        ),
        ConfigFieldSpec(
            "tree_filter_mode",
            decode=lambda raw, current: _deserialize_tree_filter_mode(raw),
        ),
        ConfigFieldSpec(
            "show_hardware_cursor",
            decode=_decode_bool("show_hardware_cursor"),
        ),
        ConfigFieldSpec(
            "editor_padding_x",
            decode=lambda raw, current: _non_negative_small_int(
                raw,
                "editor_padding_x",
                upper_bound=3,
            ),
        ),
        ConfigFieldSpec(
            "autocomplete_max_visible",
            decode=lambda raw, current: _bounded_int(
                raw,
                "autocomplete_max_visible",
                lower_bound=3,
                upper_bound=20,
            ),
        ),
        ConfigFieldSpec(
            "keybindings",
            decode=_decode_keybinding_overlay,
            encode=lambda current, default: _serialize_keybindings(
                cast(Mapping[str, KeybindingValue], current)
            ),
        ),
        ConfigFieldSpec(
            "capabilities",
            decode=_decode_capability_mount_overlay,
            encode=lambda current, default: dict(
                cast(Mapping[str, CapabilityMountMode], current)
            ),
        ),
        ConfigFieldSpec(
            "thinking_budgets",
            decode=lambda raw, current: _thinking_budgets(raw),
        ),
        *(
            ConfigFieldSpec(
                field_name,
                decode=_decode_dataclass(field_name),
                encode=encode_dataclass_diff,
            )
            for field_name in (
                "compaction",
                "branch_summary",
                "retry",
                "images",
                "terminal",
                "markdown",
                "warnings",
                "method",
            )
        ),
        ConfigFieldSpec(
            "permissions",
            decode=lambda raw, current: _apply_permission_settings_patch(
                cast(PermissionSettings, current), raw
            ),
            encode=encode_dataclass_diff,
            recover_errors=(TypeError, ValueError),
        ),
        ConfigFieldSpec(
            "tools",
            decode=lambda raw, current: _apply_tool_settings_patch(
                cast(ToolSettings, current), raw
            ),
            encode=encode_dataclass_diff,
        ),
        ConfigFieldSpec(
            "sandbox",
            decode=_decode_dataclass("sandbox"),
            encode=encode_dataclass_diff,
            recover_errors=(TypeError, ValueError),
        ),
        ConfigFieldSpec(
            "statusline",
            decode=lambda raw, current: _apply_statusline_settings_patch(
                cast(StatusLineControlSettings, current), raw
            ),
            encode=encode_dataclass_diff,
            recover_errors=(TypeError, ValueError),
        ),
        ConfigFieldSpec("session_dir", decode=_decode_session_dir),
        ConfigFieldSpec(
            "resource_roots",
            decode=_decode_string_tuple("resource_roots"),
            encode=_encode_tuple,
        ),
        ConfigFieldSpec(
            "package_roots",
            decode=_decode_string_tuple("package_roots"),
            encode=_encode_tuple,
        ),
        ConfigFieldSpec(
            "package_sources",
            input_keys=("packages", "package_sources"),
            output_key="package_sources",
            decode=_decode_package_sources,
            encode=_encode_package_sources,
        ),
        ConfigFieldSpec(
            "plugin_sources",
            decode=_decode_string_tuple("plugin_sources"),
            encode=_encode_tuple,
        ),
        ConfigFieldSpec(
            "disabled_skills",
            decode=_decode_string_tuple("disabled_skills"),
            encode=_encode_tuple,
        ),
        ConfigFieldSpec(
            "disabled_plugins",
            decode=_decode_string_tuple("disabled_plugins"),
            encode=_encode_tuple,
        ),
    ),
    removed_fields=_REMOVED_SETTING_MESSAGES,
    unknown_fields="ignore",
)
