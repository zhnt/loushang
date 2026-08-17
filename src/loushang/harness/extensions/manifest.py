from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS
from loushang.harness.resources.diagnostics import resource_diagnostic

PermissionLevel = Literal["safe", "standard", "powerful"]
HookKind = Literal["observe", "transform", "intercept", "augment"]

_VALID_PERMISSION_LEVELS = frozenset({"safe", "standard", "powerful"})
_VALID_HOOK_KINDS = frozenset({"observe", "transform", "intercept", "augment"})
_FATAL_DIAGNOSTIC_CODES = frozenset(
    {
        "missing_extension_manifest_metadata",
        "missing_extension_manifest_id",
        "missing_extension_manifest_name",
        "invalid_extension_permission_level",
    }
)
_SUPPORTED_TOP_LEVEL_SECTIONS = frozenset(
    {
        "extension",
        "permissions",
        "dependencies",
        "commands",
        "tools",
        "prompts",
        "skills",
        "hooks",
        "models",
        "providers",
        "ui",
        "autocomplete",
        "configuration",
    }
)


@dataclass(frozen=True)
class ExtensionPermissionDeclaration:
    level: PermissionLevel = "safe"
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionCommandDeclaration:
    name: str
    description: str | None = None


@dataclass(frozen=True)
class ExtensionToolDeclaration:
    name: str
    description: str | None = None


@dataclass(frozen=True)
class ExtensionHookDeclaration:
    event: str
    kind: HookKind = "observe"
    handler: str | None = None


@dataclass(frozen=True)
class PythonDependencyDeclaration:
    packages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionDependencyDeclaration:
    python: PythonDependencyDeclaration = field(
        default_factory=PythonDependencyDeclaration
    )


@dataclass(frozen=True)
class ExtensionManifest:
    id: str
    name: str
    version: str | None = None
    description: str | None = None
    permissions: ExtensionPermissionDeclaration = field(
        default_factory=ExtensionPermissionDeclaration
    )
    dependencies: ExtensionDependencyDeclaration = field(
        default_factory=ExtensionDependencyDeclaration
    )
    commands: tuple[ExtensionCommandDeclaration, ...] = ()
    tools: tuple[ExtensionToolDeclaration, ...] = ()
    hooks: tuple[ExtensionHookDeclaration, ...] = ()


@dataclass(frozen=True)
class ExtensionManifestParseResult:
    manifest: ExtensionManifest | None = None
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)


def parse_extension_manifest(path: Path) -> ExtensionManifestParseResult:
    diagnostics: list[DiagnosticDraft] = []
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        return ExtensionManifestParseResult(
            diagnostics=[
                _diagnostic(
                    "invalid_extension_manifest_toml",
                    f"Failed to parse extension manifest TOML: {exc}",
                    path,
                )
            ]
        )
    except OSError as exc:
        return ExtensionManifestParseResult(
            diagnostics=[
                _diagnostic(
                    "unreadable_extension_manifest",
                    f"Failed to read extension manifest: {exc}",
                    path,
                )
            ]
        )

    if not isinstance(data, dict):
        return ExtensionManifestParseResult(
            diagnostics=[
                _diagnostic(
                    "invalid_extension_manifest",
                    "Extension manifest must be a TOML table.",
                    path,
                )
            ]
        )

    for section in data:
        if section not in _SUPPORTED_TOP_LEVEL_SECTIONS:
            diagnostics.append(
                _diagnostic(
                    "unsupported_extension_manifest_section",
                    f"Unsupported extension manifest section: {section}",
                    path,
                    metadata={"section": section},
                )
            )

    extension = data.get("extension")
    if not isinstance(extension, dict):
        diagnostics.append(
            _diagnostic(
                "missing_extension_manifest_metadata",
                "Extension manifest must include an [extension] section.",
                path,
            )
        )
        return ExtensionManifestParseResult(diagnostics=diagnostics)

    extension_id = _identifier_or_none(extension.get("id"))
    name = _identifier_or_none(extension.get("name"))
    if not extension_id:
        diagnostics.append(
            _diagnostic(
                "missing_extension_manifest_id",
                "Extension manifest [extension].id is required.",
                path,
            )
        )
    if not name:
        diagnostics.append(
            _diagnostic(
                "missing_extension_manifest_name",
                "Extension manifest [extension].name is required.",
                path,
            )
        )

    permissions = _parse_permissions(data.get("permissions"), path, diagnostics)
    commands = _parse_named_declarations(
        data.get("commands"), path, "command", diagnostics
    )
    tools = _parse_named_declarations(data.get("tools"), path, "tool", diagnostics)
    hooks = _parse_hooks(data.get("hooks"), path, diagnostics)
    dependencies = _parse_dependencies(data.get("dependencies"))

    if any(diagnostic.code in _FATAL_DIAGNOSTIC_CODES for diagnostic in diagnostics):
        return ExtensionManifestParseResult(diagnostics=diagnostics)

    return ExtensionManifestParseResult(
        manifest=ExtensionManifest(
            id=extension_id or "",
            name=name or extension_id or "",
            version=_string_or_none(extension.get("version")),
            description=_string_or_none(extension.get("description")),
            permissions=permissions,
            dependencies=dependencies,
            commands=tuple(
                ExtensionCommandDeclaration(
                    name=declaration.name, description=declaration.description
                )
                for declaration in commands
            ),
            tools=tuple(
                ExtensionToolDeclaration(
                    name=declaration.name, description=declaration.description
                )
                for declaration in tools
            ),
            hooks=hooks,
        ),
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class _NamedDeclaration:
    name: str
    description: str | None = None


def _parse_permissions(
    value: object,
    path: Path,
    diagnostics: list[DiagnosticDraft],
) -> ExtensionPermissionDeclaration:
    if value is None:
        return ExtensionPermissionDeclaration()
    if not isinstance(value, dict):
        diagnostics.append(
            _diagnostic(
                "invalid_extension_permissions",
                "Extension manifest [permissions] must be a table.",
                path,
            )
        )
        return ExtensionPermissionDeclaration()

    level = value.get("level", "safe")
    if level not in _VALID_PERMISSION_LEVELS:
        diagnostics.append(
            _diagnostic(
                "invalid_extension_permission_level",
                f"Unsupported extension permission level: {level}",
                path,
                metadata={"level": str(level)},
            )
        )
        return ExtensionPermissionDeclaration()
    return ExtensionPermissionDeclaration(
        level=level,  # type: ignore[arg-type]
        capabilities=_string_tuple(value.get("capabilities")),
    )


def _parse_named_declarations(
    value: object,
    path: Path,
    resource_name: str,
    diagnostics: list[DiagnosticDraft],
) -> tuple[_NamedDeclaration, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        diagnostics.append(
            _diagnostic(
                f"invalid_extension_{resource_name}_declarations",
                f"Extension manifest {resource_name} declarations must be an array of tables.",
                path,
            )
        )
        return ()

    declarations: list[_NamedDeclaration] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    f"invalid_extension_{resource_name}_declaration",
                    f"Extension manifest {resource_name} declaration must be a table.",
                    path,
                    metadata={"index": index},
                )
            )
            continue
        name = _string_or_none(item.get("name"))
        if not name:
            diagnostics.append(
                _diagnostic(
                    f"missing_extension_{resource_name}_name",
                    f"Extension manifest {resource_name} declaration requires a name.",
                    path,
                    metadata={"index": index},
                )
            )
            continue
        declarations.append(
            _NamedDeclaration(
                name=name,
                description=_string_or_none(item.get("description")),
            )
        )
    return tuple(declarations)


def _parse_hooks(
    value: object,
    path: Path,
    diagnostics: list[DiagnosticDraft],
) -> tuple[ExtensionHookDeclaration, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        diagnostics.append(
            _diagnostic(
                "invalid_extension_hook_declarations",
                "Extension manifest hook declarations must be an array of tables.",
                path,
            )
        )
        return ()

    hooks: list[ExtensionHookDeclaration] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    "invalid_extension_hook_declaration",
                    "Extension manifest hook declaration must be a table.",
                    path,
                    metadata={"index": index},
                )
            )
            continue
        event = _string_or_none(item.get("event"))
        if not event:
            diagnostics.append(
                _diagnostic(
                    "missing_extension_hook_event",
                    "Extension manifest hook declaration requires an event.",
                    path,
                    metadata={"index": index},
                )
            )
            continue
        if event not in VALID_EXTENSION_EVENTS:
            diagnostics.append(
                _diagnostic(
                    "unsupported_extension_hook_event",
                    f"Unsupported extension hook event: {event}",
                    path,
                    metadata={"index": index, "event": event},
                )
            )
            continue
        kind = item.get("kind", "observe")
        if kind not in _VALID_HOOK_KINDS:
            diagnostics.append(
                _diagnostic(
                    "invalid_extension_hook_kind",
                    f"Unsupported extension hook kind: {kind}",
                    path,
                    metadata={"index": index, "kind": str(kind)},
                )
            )
            continue
        hooks.append(
            ExtensionHookDeclaration(
                event=event,
                kind=kind,  # type: ignore[arg-type]
                handler=_string_or_none(item.get("handler")),
            )
        )
    return tuple(hooks)


def _parse_dependencies(value: object) -> ExtensionDependencyDeclaration:
    if not isinstance(value, dict):
        return ExtensionDependencyDeclaration()
    python = value.get("python")
    if not isinstance(python, dict):
        return ExtensionDependencyDeclaration()
    return ExtensionDependencyDeclaration(
        python=PythonDependencyDeclaration(
            packages=_string_tuple(python.get("packages"))
        )
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _identifier_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _diagnostic(
    code: str,
    message: str,
    source_path: Path,
    *,
    metadata: dict[str, object] | None = None,
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=code,
        message=message,
        source_path=source_path,
        resource_type="extension",
        metadata=metadata or {},
    )


__all__ = [
    "ExtensionCommandDeclaration",
    "ExtensionDependencyDeclaration",
    "ExtensionHookDeclaration",
    "ExtensionManifest",
    "ExtensionManifestParseResult",
    "ExtensionPermissionDeclaration",
    "ExtensionToolDeclaration",
    "HookKind",
    "PermissionLevel",
    "PythonDependencyDeclaration",
    "parse_extension_manifest",
]
