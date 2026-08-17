from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.types import (
    LoadedExtension,
    ResolvedCommand,
    ResolvedFlag,
    ResolvedShortcut,
    extension_is_active,
)
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.source import SourceInfo
from loushang.harness.tools.core import ToolDefinition


@dataclass(frozen=True)
class ExtensionToolRegistration:
    definition: ToolDefinition
    source_info: SourceInfo[Path]
    extension_name: str


@dataclass(frozen=True)
class ExtensionRegistrySnapshot:
    commands: tuple[ResolvedCommand, ...] = ()
    flags: tuple[ResolvedFlag, ...] = ()
    shortcuts: tuple[ResolvedShortcut, ...] = ()
    tools: tuple[ExtensionToolRegistration, ...] = ()
    flag_defaults: dict[str, bool | str] = field(default_factory=dict)
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    flag_diagnostics: tuple[DiagnosticDraft, ...] = ()
    shortcut_diagnostics: tuple[DiagnosticDraft, ...] = ()

    def command_index(self) -> dict[str, ResolvedCommand]:
        return {command.invocation_name: command for command in self.commands}

    def tool_source_index(self) -> dict[str, SourceInfo[Path]]:
        return {tool.definition.name: tool.source_info for tool in self.tools}


def resolve_extension_registry(
    extensions: list[LoadedExtension] | tuple[LoadedExtension, ...],
) -> ExtensionRegistrySnapshot:
    active_extensions = tuple(
        extension for extension in extensions if extension_is_active(extension)
    )
    commands = _resolve_commands(active_extensions)
    flags, flag_defaults, flag_diagnostics = _resolve_flags(active_extensions)
    shortcuts, shortcut_diagnostics = _resolve_shortcuts(active_extensions)
    tools, tool_diagnostics = _resolve_tools(active_extensions)
    return ExtensionRegistrySnapshot(
        commands=commands,
        flags=flags,
        shortcuts=shortcuts,
        tools=tools,
        flag_defaults=flag_defaults,
        diagnostics=(*tool_diagnostics, *flag_diagnostics, *shortcut_diagnostics),
        flag_diagnostics=flag_diagnostics,
        shortcut_diagnostics=shortcut_diagnostics,
    )


def source_info_from_extension(extension: LoadedExtension) -> SourceInfo[Path]:
    return SourceInfo(
        path=extension.entry_path or extension.source_path,
        source=extension.source,
        scope=_scope_from_extension(extension),
        origin=_origin_from_extension(extension),
        base_dir=extension.source_root,
    )


def _resolve_commands(
    extensions: list[LoadedExtension] | tuple[LoadedExtension, ...],
) -> tuple[ResolvedCommand, ...]:
    literal_names = {name for extension in extensions for name in extension.commands}
    counts: dict[str, int] = {}
    for name in literal_names:
        counts[name] = sum(name in extension.commands for extension in extensions)

    resolved: list[ResolvedCommand] = []
    next_suffixes: dict[str, int] = {}
    taken_names: set[str] = set()
    for extension in extensions:
        for name, command in extension.commands.items():
            invocation_name = name
            if counts.get(name, 0) > 1:
                suffix = next_suffixes.get(name, 1)
                invocation_name = f"{name}:{suffix}"
                while (
                    invocation_name in taken_names or invocation_name in literal_names
                ):
                    suffix += 1
                    invocation_name = f"{name}:{suffix}"
                next_suffixes[name] = suffix + 1
            resolved.append(
                ResolvedCommand(
                    name=command.name,
                    handler=command.handler,
                    description=command.description,
                    get_argument_completions=command.get_argument_completions,
                    invocation_name=invocation_name,
                    source_info=source_info_from_extension(extension),
                    extension_name=extension.name,
                )
            )
            taken_names.add(invocation_name)
    return tuple(resolved)


def _resolve_flags(
    extensions: list[LoadedExtension] | tuple[LoadedExtension, ...],
) -> tuple[
    tuple[ResolvedFlag, ...],
    dict[str, bool | str],
    tuple[DiagnosticDraft, ...],
]:
    resolved: list[ResolvedFlag] = []
    defaults: dict[str, bool | str] = {}
    diagnostics: list[DiagnosticDraft] = []
    seen: set[str] = set()
    for extension in extensions:
        for name, flag in extension.flags.items():
            if name in seen:
                diagnostics.append(
                    _duplicate_diagnostic("flag", name, extension.source_path)
                )
                continue
            seen.add(name)
            resolved.append(
                ResolvedFlag(
                    name=flag.name,
                    type=flag.type,
                    description=flag.description,
                    default=flag.default,
                    source_info=source_info_from_extension(extension),
                    extension_name=extension.name,
                )
            )
            if flag.default is not None:
                defaults[name] = flag.default
    return tuple(resolved), defaults, tuple(diagnostics)


def _resolve_shortcuts(
    extensions: list[LoadedExtension] | tuple[LoadedExtension, ...],
) -> tuple[tuple[ResolvedShortcut, ...], tuple[DiagnosticDraft, ...]]:
    resolved: list[ResolvedShortcut] = []
    diagnostics: list[DiagnosticDraft] = []
    seen: set[str] = set()
    for extension in extensions:
        for shortcut, definition in extension.shortcuts.items():
            if shortcut in seen:
                diagnostics.append(
                    _duplicate_diagnostic("shortcut", shortcut, extension.source_path)
                )
                continue
            seen.add(shortcut)
            resolved.append(
                ResolvedShortcut(
                    shortcut=definition.shortcut,
                    handler=definition.handler,
                    description=definition.description,
                    source_info=source_info_from_extension(extension),
                    extension_name=extension.name,
                )
            )
    return tuple(resolved), tuple(diagnostics)


def _resolve_tools(
    extensions: list[LoadedExtension] | tuple[LoadedExtension, ...],
) -> tuple[tuple[ExtensionToolRegistration, ...], tuple[DiagnosticDraft, ...]]:
    resolved: list[ExtensionToolRegistration] = []
    diagnostics: list[DiagnosticDraft] = []
    seen: set[str] = set()
    for extension in extensions:
        for definition in extension.tool_definitions:
            if definition.name in seen:
                diagnostics.append(
                    _duplicate_diagnostic(
                        "tool", definition.name, extension.source_path
                    )
                )
                continue
            seen.add(definition.name)
            resolved.append(
                ExtensionToolRegistration(
                    definition=definition,
                    source_info=source_info_from_extension(extension),
                    extension_name=extension.name,
                )
            )
    return tuple(resolved), tuple(diagnostics)


def _duplicate_diagnostic(
    contribution_type: Literal["tool", "flag", "shortcut"],
    name: str,
    source_path: Path,
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=f"duplicate_extension_{contribution_type}",
        message=(f"Duplicate extension {contribution_type} '{name}' was rejected."),
        source_path=source_path,
    )


def _origin_from_extension(
    extension: LoadedExtension,
) -> Literal["top-level", "package"]:
    if extension.source_scope in {"package", "builtin"} or extension.source_kind in {
        "external_package",
        "built_in",
    }:
        return "package"
    return "top-level"


def _scope_from_extension(
    extension: LoadedExtension,
) -> Literal["temporary", "user", "project"]:
    if extension.source in {"inline", "sdk"}:
        return "temporary"
    if extension.source_scope == "user":
        return "user"
    return "project"


__all__ = [
    "ExtensionRegistrySnapshot",
    "ExtensionToolRegistration",
    "resolve_extension_registry",
    "source_info_from_extension",
]
