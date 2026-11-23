"""Select Session workspace tools from an existing profile and native host facts."""

from __future__ import annotations

from collections.abc import Iterable, Set
from dataclasses import replace
from typing import Literal, TypeVar

from loushang.harness.environment import HostEnvironment
from loushang.harness.tools.workspace.factory import WorkspaceToolProfile
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

_Name = TypeVar("_Name", bound=str)


def _windows_tool_name(name: _Name) -> _Name | Literal["shell"]:
    return "shell" if name == "bash" else name


def platform_tool_names(
    names: Iterable[str], environment: HostEnvironment
) -> tuple[str, ...]:
    """Resolve workspace tool intents in order and collapse aliases to one name."""
    resolved: list[str] = []
    seen: set[str] = set()
    for name in names:
        platform_name = (
            _windows_tool_name(name) if environment.os_family == "windows" else name
        )
        if platform_name not in seen:
            resolved.append(platform_name)
            seen.add(platform_name)
    return tuple(resolved)


def platform_tool_profile(
    profile: WorkspaceToolProfile, environment: HostEnvironment
) -> WorkspaceToolProfile:
    """Resolve both name lists through the existing workspace profile type."""
    if environment.os_family != "windows":
        return profile
    return replace(
        profile,
        tool_names=tuple(_windows_tool_name(name) for name in profile.tool_names),
        builtin_tool_names=tuple(
            _windows_tool_name(name) for name in profile.builtin_tool_names
        ),
    )


def default_tool_names(
    names: tuple[str, ...], selected: Set[str] | None
) -> tuple[str, ...]:
    """Keep the declared default order within the selected base."""
    return (
        names if selected is None else tuple(name for name in names if name in selected)
    )


def initial_tool_names(
    defaults: tuple[str, ...], base: Set[str], registry: WorkspaceToolRegistry | None
) -> list[str]:
    """Add enabled peers to the selected base defaults in registry order."""
    selected = default_tool_names(defaults, base)
    peers = registry.list_enabled_definitions() if registry is not None else ()
    return [
        *selected,
        *(tool.name for tool in peers if tool.name not in base),
    ]


def peer_tool_names(
    names: tuple[str, ...], exact_owner_names: Iterable[str]
) -> tuple[str, ...]:
    """Leave exact-owner identities with their original published generation."""
    exact = frozenset(exact_owner_names)
    return tuple(name for name in names if name not in exact)
