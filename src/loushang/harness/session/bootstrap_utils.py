"""Small, product-neutral helpers used while constructing Agent sessions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from loushang.harness.session.model_resolution import split_model_thinking_pattern

NoToolsMode = Literal["all", "builtin"]


def normalize_no_tools(no_tools: NoToolsMode | bool | None) -> NoToolsMode | None:
    if no_tools is True:
        return "all"
    if no_tools is False or no_tools is None:
        return None
    if no_tools in {"all", "builtin"}:
        return no_tools
    raise ValueError("no_tools must be 'all', 'builtin', True, False, or None")


def loader_system_prompt_override(resource_loader: object) -> str | None:
    getter = getattr(resource_loader, "get_system_prompt_override", None)
    if not callable(getter):
        return None
    value = getter()
    return value if isinstance(value, str) else None


def loader_append_system_prompt(resource_loader: object) -> list[str]:
    getter = getattr(resource_loader, "get_append_system_prompt_overrides", None)
    if not callable(getter):
        return []
    values = getter()
    if not isinstance(values, list | tuple):
        return []
    return [value for value in values if isinstance(value, str) and value.strip()]


def append_system_prompt_fragments(
    base_prompt: str,
    fragments: Sequence[str],
) -> str:
    parts = (
        [base_prompt.strip()]
        if isinstance(base_prompt, str) and base_prompt.strip()
        else []
    )
    parts.extend(
        fragment.strip()
        for fragment in fragments
        if isinstance(fragment, str) and fragment.strip()
    )
    return "\n\n".join(parts)


def resolve_base_system_prompt(
    *,
    explicit_prompt: str | None,
    resource_loader: object,
    configured_prompt: str,
    default_prompt: str,
    append_fragments: Sequence[str] = (),
) -> str:
    """Resolve Product, loader, config, and appended prompt precedence."""

    loader_prompt = loader_system_prompt_override(resource_loader)
    base_prompt = (
        explicit_prompt
        if explicit_prompt is not None
        else loader_prompt
        if loader_prompt is not None
        else configured_prompt
    )
    resolved = append_system_prompt_fragments(
        base_prompt,
        (*loader_append_system_prompt(resource_loader), *append_fragments),
    )
    return resolved if resolved.strip() else default_prompt


def resolve_initial_active_tool_names(
    *,
    active_tool_names: list[str] | None,
    allowed_tool_names: set[str] | None,
    no_tools_mode: NoToolsMode | None,
    tool_registry: object | None,
) -> list[str] | None:
    if no_tools_mode == "all":
        return []
    if active_tool_names is not None:
        names = list(active_tool_names)
    elif no_tools_mode == "builtin":
        names = non_builtin_tool_names(tool_registry)
    else:
        return None
    if allowed_tool_names is not None:
        return [name for name in names if name in allowed_tool_names]
    return names


def non_builtin_tool_names(
    tool_registry: object | None,
) -> list[str]:
    if tool_registry is None:
        return []
    builtin_names = {"bash", "read", "ls", "find", "grep", "write", "edit"}
    list_enabled_definitions = getattr(tool_registry, "list_enabled_definitions", None)
    if not callable(list_enabled_definitions):
        return []
    return [
        definition.name
        for definition in list_enabled_definitions()
        if definition.name not in builtin_names
    ]


__all__ = [
    "NoToolsMode",
    "append_system_prompt_fragments",
    "loader_append_system_prompt",
    "loader_system_prompt_override",
    "non_builtin_tool_names",
    "normalize_no_tools",
    "resolve_initial_active_tool_names",
    "resolve_base_system_prompt",
    "split_model_thinking_pattern",
]
