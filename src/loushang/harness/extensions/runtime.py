"""Composition runtime for loaded extension contributions.

The registry, route planner, dispatcher, and resource runtime are independent
components.  ``ExtensionRuntime`` composes them into the common operational
surface that Products need after they have loaded extensions and selected a
context implementation.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.dispatch import ExtensionDispatcher
from loushang.harness.extensions.manifest import ExtensionManifest
from loushang.harness.extensions.registry import (
    resolve_extension_registry,
    source_info_from_extension,
)
from loushang.harness.extensions.resources import ExtensionResourceRuntime
from loushang.harness.extensions.routing import (
    ExtensionRoutePlan,
    ExtensionRouter,
)
from loushang.harness.extensions.types import (
    InputEventResult,
    LoadedExtension,
    ResolvedCommand,
    ResolvedFlag,
    ResolvedShortcut,
    extension_is_active,
)
from loushang.harness.extensions.wrapper import wrap_registered_tool_definition
from loushang.harness.resources.source import SourceInfo
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.tools.core import ToolDefinition

ExtensionRuntimeContextFactory = Callable[[str, LoadedExtension | None], object]
ExtensionResourceContextFactory = Callable[[str], object]
ExtensionRuntimeErrorHandler = Callable[[LoadedExtension, str, Exception], None]


@dataclass(frozen=True)
class _ExtensionRuntimeCompositionState:
    extensions: tuple[LoadedExtension, ...]
    active_extensions: tuple[LoadedExtension, ...]
    route_plan: ExtensionRoutePlan
    tool_definitions: tuple[ToolDefinition, ...]
    tool_source_info_by_name: dict[str, SourceInfo[Path]]
    tool_extension_name_by_name: dict[str, str]
    command_diagnostics: tuple[DiagnosticDraft, ...]
    flag_diagnostics: tuple[DiagnosticDraft, ...]
    shortcut_diagnostics: tuple[DiagnosticDraft, ...]
    registered_commands: tuple[ResolvedCommand, ...]
    registered_commands_by_invocation_name: dict[str, ResolvedCommand]
    resolved_flags: tuple[ResolvedFlag, ...]
    resolved_shortcuts: tuple[ResolvedShortcut, ...]
    flag_values: dict[str, bool | str]


class ExtensionRuntime:
    """Compose standard extension contributions without Product hook semantics.

    Products load or adapt their extension descriptors before constructing this
    runtime.  They also provide contexts and optional runtime-error handling.
    The runtime deliberately does not interpret Product model/session values,
    UI callbacks, or Agent-specific hook return types.
    """

    def __init__(
        self,
        extensions: Sequence[LoadedExtension],
        *,
        context_factory: ExtensionRuntimeContextFactory,
        resource_context_factory: ExtensionResourceContextFactory | None = None,
        diagnostics: list[DiagnosticDraft] | None = None,
        runtime_error_handler: ExtensionRuntimeErrorHandler | None = None,
    ) -> None:
        self._extensions = tuple(extensions)
        self._active_extensions = tuple(
            extension
            for extension in self._extensions
            if extension_is_active(extension)
        )
        self._context_factory = context_factory
        self._resource_context_factory = (
            resource_context_factory
            if resource_context_factory is not None
            else lambda cwd: context_factory(cwd, None)
        )
        self._diagnostics = diagnostics if diagnostics is not None else []
        self._runtime_error_handler = runtime_error_handler
        self._tool_definitions: list[ToolDefinition] = []
        self._tool_source_info_by_name: dict[str, SourceInfo[Path]] = {}
        self._tool_extension_name_by_name: dict[str, str] = {}
        self._command_diagnostics: list[DiagnosticDraft] = []
        self._flag_diagnostics: list[DiagnosticDraft] = []
        self._shortcut_diagnostics: list[DiagnosticDraft] = []
        self._registered_commands: list[ResolvedCommand] = []
        self._registered_commands_by_invocation_name: dict[str, ResolvedCommand] = {}
        self._resolved_flags: list[ResolvedFlag] = []
        self._resolved_shortcuts: list[ResolvedShortcut] = []
        self._flag_values: dict[str, bool | str] = {}
        self._route_plan = ExtensionRoutePlan.from_extensions(
            self._extensions,
            diagnostics=self._diagnostics,
        )
        self._router = ExtensionRouter(
            self._route_plan,
            diagnostics=self._diagnostics,
            runtime_error_handler=self._emit_runtime_error,
            include_route_id_in_error_metadata=False,
        )
        self._plain_diagnostic_router = ExtensionRouter(
            self._route_plan,
            diagnostics=self._diagnostics,
            runtime_error_handler=self._emit_runtime_error,
            include_route_id_in_error_metadata=False,
            include_provenance_in_error_metadata=False,
        )
        self._apply_registry_snapshot()

    @property
    def extensions(self) -> tuple[LoadedExtension, ...]:
        return self._extensions

    @property
    def active_extensions(self) -> tuple[LoadedExtension, ...]:
        return self._active_extensions

    @property
    def route_plan(self) -> ExtensionRoutePlan:
        return self._route_plan

    @property
    def router(self) -> ExtensionRouter:
        return self._router

    @property
    def plain_diagnostic_router(self) -> ExtensionRouter:
        return self._plain_diagnostic_router

    def get_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self._diagnostics)

    def get_command_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self._command_diagnostics)

    def get_flag_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self._flag_diagnostics)

    def get_shortcut_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self._shortcut_diagnostics)

    def get_registered_commands(self) -> list[ResolvedCommand]:
        return list(self._registered_commands)

    def get_command(self, invocation_name: str) -> ResolvedCommand | None:
        return self._registered_commands_by_invocation_name.get(invocation_name)

    async def get_command_argument_completions(
        self, invocation_name: str, prefix: str
    ) -> list[object] | None:
        command = self.get_command(invocation_name)
        if command is None or command.get_argument_completions is None:
            return None
        try:
            result = command.get_argument_completions(prefix)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self._diagnostics.append(
                DiagnosticDraft(
                    code="extension_command_argument_completions_failed",
                    message=f"Extension command argument completions failed: {exc}",
                    source_path=command.source_info.path,
                )
            )
            self._emit_runtime_error(
                self._extension_by_name(command.extension_name),
                "command_argument_completions",
                exc,
            )
            return None
        if result is None:
            return None
        if not isinstance(result, list):
            self._diagnostics.append(
                DiagnosticDraft(
                    code="invalid_extension_command_argument_completions",
                    message="Command argument completions must return a list or None.",
                    source_path=command.source_info.path,
                )
            )
            return None
        return result

    def get_flags(self) -> list[ResolvedFlag]:
        return list(self._resolved_flags)

    def get_shortcuts(self) -> list[ResolvedShortcut]:
        return list(self._resolved_shortcuts)

    def set_flag_value(self, name: str, value: bool | str) -> None:
        self._flag_values[name] = value

    def apply_flag_values(
        self,
        values: Mapping[str, bool | str] | None,
    ) -> tuple[DiagnosticDraft, ...]:
        """Validate and apply Product-provided extension flag values."""

        if not values:
            return ()
        flags_by_name = {flag.name: flag for flag in self._resolved_flags}
        diagnostics: list[DiagnosticDraft] = []
        for raw_name, value in values.items():
            name = raw_name[2:] if raw_name.startswith("--") else raw_name
            flag = flags_by_name.get(name)
            if flag is None:
                diagnostics.append(
                    DiagnosticDraft(
                        code="unknown_extension_flag",
                        message=f"Unknown extension flag: --{name}",
                        details={"metadata": {"flag": name}},
                    )
                )
                continue
            if flag.type == "string" and not isinstance(value, str):
                diagnostics.append(
                    DiagnosticDraft(
                        code="extension_flag_value_required",
                        message=f'Extension flag "--{name}" requires a value.',
                        source_path=flag.source_info.path,
                        details={"metadata": {"flag": name}},
                    )
                )
                continue
            self.set_flag_value(name, value if flag.type == "string" else bool(value))
        return tuple(diagnostics)

    def get_flag_value(self, name: str) -> bool | str | None:
        return self._flag_values.get(name)

    def get_flag_values(self) -> dict[str, bool | str]:
        return dict(self._flag_values)

    def has_handlers(self, hook_name: str) -> bool:
        return self._router.has_handlers(hook_name)

    async def emit_user_bash(
        self,
        event: object,
        *,
        cwd: str = "",
    ) -> object | None:
        return await self._dispatcher(cwd).dispatch_first_truthy("user_bash", event)

    async def emit_event(
        self,
        event_name: str,
        event: object,
        *,
        cwd: str = "",
    ) -> None:
        await self._dispatcher(cwd).dispatch(event_name, event)

    async def emit_input(
        self,
        text: str,
        images: list[object] | None = None,
        *,
        source: str = "interactive",
        cwd: str = "",
    ) -> InputEventResult:
        return await self._dispatcher(cwd).dispatch_input(
            text,
            images,
            source=source,
        )

    def list_tool_definitions(self) -> list[ToolDefinition]:
        return list(self._tool_definitions)

    def get_tool_source_info(self, name: str) -> SourceInfo[Path] | None:
        return self._tool_source_info_by_name.get(name)

    def get_tool_extension_name(self, name: str) -> str | None:
        return self._tool_extension_name_by_name.get(name)

    def get_message_renderer(self, custom_type: str):
        for extension in self._active_extensions:
            renderer = extension.message_renderers.get(custom_type)
            if renderer is not None:
                return renderer
        return None

    def list_message_renderers(self) -> list[dict[str, object]]:
        renderers: list[dict[str, object]] = []
        for extension in self._active_extensions:
            source_info = source_info_from_extension(extension)
            for custom_type in extension.message_renderers:
                renderers.append(
                    {
                        "custom_type": custom_type,
                        "customType": custom_type,
                        "extension_name": extension.name,
                        "extensionName": extension.name,
                        "source_info": _serialize_source_info(source_info),
                        "sourceInfo": _serialize_source_info(source_info),
                    }
                )
        return renderers

    def get_diagnostic_snapshot(self) -> dict[str, object]:
        return {
            "total": len(self._diagnostics),
            "commands": len(self._command_diagnostics),
            "flags": len(self._flag_diagnostics),
            "shortcuts": len(self._shortcut_diagnostics),
            "diagnostics": [
                _serialize_diagnostic(diagnostic) for diagnostic in self._diagnostics
            ],
        }

    def list_extensions(self) -> list[dict[str, object]]:
        return [
            _extension_visibility_snapshot(extension, diagnostics=self._diagnostics)
            for extension in self._extensions
        ]

    def discover_resources(
        self,
        bundle: ResourceBundle,
        *,
        reason: str = "refresh",
    ) -> ResourceBundle:
        del reason
        return self._resource_runtime().discover(
            bundle,
            context=self._resource_context_factory(str(bundle.cwd)),
        )

    async def discover_resources_async(
        self,
        bundle: ResourceBundle,
        *,
        reason: str = "refresh",
    ) -> ResourceBundle:
        del reason
        return await self._resource_runtime().discover_async(
            bundle,
            context=self._resource_context_factory(str(bundle.cwd)),
        )

    def _apply_registry_snapshot(self) -> None:
        registry = resolve_extension_registry(self._active_extensions)
        self._diagnostics.extend(registry.diagnostics)
        self._flag_diagnostics.extend(registry.flag_diagnostics)
        self._shortcut_diagnostics.extend(registry.shortcut_diagnostics)
        self._registered_commands.extend(registry.commands)
        self._registered_commands_by_invocation_name.update(registry.command_index())
        self._resolved_flags.extend(registry.flags)
        self._resolved_shortcuts.extend(registry.shortcuts)
        for name, value in registry.flag_defaults.items():
            self._flag_values.setdefault(name, value)
        for registration in registry.tools:
            source_info = registration.source_info
            self._tool_source_info_by_name[registration.definition.name] = source_info
            self._tool_extension_name_by_name[registration.definition.name] = (
                registration.extension_name
            )
            self._tool_definitions.append(
                wrap_registered_tool_definition(
                    registration.definition,
                    str(source_info.path.parent),
                )
            )

    def _capture_composition_state(self) -> _ExtensionRuntimeCompositionState:
        return _ExtensionRuntimeCompositionState(
            extensions=self._extensions,
            active_extensions=self._active_extensions,
            route_plan=self._route_plan,
            tool_definitions=tuple(self._tool_definitions),
            tool_source_info_by_name=dict(self._tool_source_info_by_name),
            tool_extension_name_by_name=dict(self._tool_extension_name_by_name),
            command_diagnostics=tuple(self._command_diagnostics),
            flag_diagnostics=tuple(self._flag_diagnostics),
            shortcut_diagnostics=tuple(self._shortcut_diagnostics),
            registered_commands=tuple(self._registered_commands),
            registered_commands_by_invocation_name=dict(
                self._registered_commands_by_invocation_name
            ),
            resolved_flags=tuple(self._resolved_flags),
            resolved_shortcuts=tuple(self._resolved_shortcuts),
            flag_values=dict(self._flag_values),
        )

    def _install_composition_state(
        self,
        state: _ExtensionRuntimeCompositionState,
    ) -> None:
        self._extensions = state.extensions
        self._active_extensions = state.active_extensions
        self._route_plan = state.route_plan
        self._tool_definitions = list(state.tool_definitions)
        self._tool_source_info_by_name = dict(state.tool_source_info_by_name)
        self._tool_extension_name_by_name = dict(state.tool_extension_name_by_name)
        self._command_diagnostics = list(state.command_diagnostics)
        self._flag_diagnostics = list(state.flag_diagnostics)
        self._shortcut_diagnostics = list(state.shortcut_diagnostics)
        self._registered_commands = list(state.registered_commands)
        self._registered_commands_by_invocation_name = dict(
            state.registered_commands_by_invocation_name
        )
        self._resolved_flags = list(state.resolved_flags)
        self._resolved_shortcuts = list(state.resolved_shortcuts)
        self._flag_values = dict(state.flag_values)
        self._router = ExtensionRouter(
            self._route_plan,
            diagnostics=self._diagnostics,
            runtime_error_handler=self._emit_runtime_error,
            include_route_id_in_error_metadata=False,
        )
        self._plain_diagnostic_router = ExtensionRouter(
            self._route_plan,
            diagnostics=self._diagnostics,
            runtime_error_handler=self._emit_runtime_error,
            include_route_id_in_error_metadata=False,
            include_provenance_in_error_metadata=False,
        )

    def _dispatcher(self, fallback_cwd: str) -> ExtensionDispatcher:
        return ExtensionDispatcher(
            self._extensions,
            context_factory=lambda extension: self._context_factory(
                fallback_cwd,
                extension,
            ),
            diagnostics=self._diagnostics,
            runtime_error_handler=self._emit_runtime_error,
            route_plan=self._route_plan,
        )

    def _resource_runtime(self) -> ExtensionResourceRuntime:
        return ExtensionResourceRuntime(
            self._extensions,
            diagnostics=self._diagnostics,
            route_plan=self._route_plan,
        )

    def _extension_by_name(self, name: str) -> LoadedExtension:
        for extension in self._active_extensions:
            if extension.name == name:
                return extension
        return LoadedExtension(name=name, source_path=Path("<unknown>"))

    def _emit_runtime_error(
        self,
        extension: LoadedExtension,
        event: str,
        error: Exception,
    ) -> None:
        if self._runtime_error_handler is not None:
            self._runtime_error_handler(extension, event, error)


def _extension_visibility_snapshot(
    extension: LoadedExtension,
    *,
    diagnostics: Sequence[DiagnosticDraft],
) -> dict[str, object]:
    manifest = extension.manifest
    manifest = manifest if isinstance(manifest, ExtensionManifest) else None
    policy = extension.policy
    source_info = source_info_from_extension(extension)
    extension_id = manifest.id if manifest is not None else extension.name
    extension_name = manifest.name if manifest is not None else extension.name
    manifest_path = _extension_manifest_path(extension)
    surfaces = [_serialize_surface(surface) for surface in extension.surfaces]
    return {
        "id": extension_id,
        "name": extension_name,
        "runtimeName": extension.name,
        "version": manifest.version if manifest is not None else None,
        "description": manifest.description if manifest is not None else None,
        "sourcePath": source_info.path.as_posix(),
        "manifestPath": manifest_path.as_posix() if manifest_path is not None else None,
        "enabled": policy.enabled if policy is not None else True,
        "permissionLevel": (
            policy.permission_level
            if policy is not None
            else manifest.permissions.level
            if manifest is not None
            else "safe"
        ),
        "capabilities": list(
            policy.capabilities
            if policy is not None
            else manifest.permissions.capabilities
            if manifest is not None
            else ()
        ),
        "surfaces": surfaces,
        "contributions": list(surfaces),
        "diagnostics": [
            _serialize_diagnostic(diagnostic)
            for diagnostic in _extension_visibility_diagnostics(
                extension,
                diagnostics=diagnostics,
                manifest_path=manifest_path,
            )
        ],
    }


def _serialize_surface(surface: object) -> dict[str, object]:
    metadata = getattr(surface, "metadata", {})
    source = metadata.get("source") if isinstance(metadata, dict) else None
    return {
        "type": str(getattr(surface, "type", "")),
        "name": str(getattr(surface, "name", "")),
        "active": bool(getattr(surface, "active", True)),
        "priority": int(getattr(surface, "priority", 0)),
        "source": source if isinstance(source, str) else "",
        "sourcePath": _path_text(getattr(surface, "source_path", None)),
        "diagnostics": [
            _serialize_diagnostic(diagnostic)
            for diagnostic in getattr(surface, "diagnostics", ())
            if isinstance(diagnostic, DiagnosticDraft)
        ],
    }


def _extension_visibility_diagnostics(
    extension: LoadedExtension,
    *,
    diagnostics: Sequence[DiagnosticDraft],
    manifest_path: Path | None,
) -> list[DiagnosticDraft]:
    source_paths = {
        path
        for path in (
            extension.source_path,
            extension.entry_path,
            manifest_path,
            *_extension_manifest_candidate_paths(extension),
        )
        if path is not None
    }
    result: list[DiagnosticDraft] = []
    seen: set[tuple[str, str, str | None]] = set()
    for diagnostic in extension.diagnostics:
        _append_extension_diagnostic(result, seen, diagnostic)
    for diagnostic in diagnostics:
        if diagnostic.source_path is None or diagnostic.source_path not in source_paths:
            continue
        _append_extension_diagnostic(result, seen, diagnostic)
    return result


def _append_extension_diagnostic(
    result: list[DiagnosticDraft],
    seen: set[tuple[str, str, str | None]],
    diagnostic: DiagnosticDraft,
) -> None:
    key = (
        diagnostic.code,
        diagnostic.message,
        diagnostic.source_path.as_posix()
        if diagnostic.source_path is not None
        else None,
    )
    if key not in seen:
        seen.add(key)
        result.append(diagnostic)


def _serialize_diagnostic(diagnostic: DiagnosticDraft) -> dict[str, object]:
    metadata = diagnostic.details.get("metadata")
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "sourcePath": diagnostic.source_path.as_posix()
        if diagnostic.source_path is not None
        else None,
        "resourceId": diagnostic.details.get("resource_id"),
        "resourceType": diagnostic.details.get("resource_type"),
        "sourceKind": diagnostic.details.get("source_kind"),
        "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
    }


def _extension_manifest_path(extension: LoadedExtension) -> Path | None:
    for candidate in _extension_manifest_candidate_paths(extension):
        if candidate.is_file():
            return candidate
    return None


def _extension_manifest_candidate_paths(extension: LoadedExtension) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if extension.source_path.suffix:
        candidates.append(extension.source_path.with_name("loushang-extension.toml"))
    else:
        candidates.append(extension.source_path / "loushang-extension.toml")
    if extension.entry_path is not None:
        candidates.append(extension.entry_path.parent / "loushang-extension.toml")
    return tuple(dict.fromkeys(candidates))


def _path_text(value: object) -> str:
    return value.as_posix() if isinstance(value, Path) else str(value or "")


def _serialize_source_info(source_info: SourceInfo[Path]) -> dict[str, object]:
    return {
        "path": source_info.path.as_posix(),
        "source": source_info.source,
        "scope": source_info.scope,
        "origin": source_info.origin,
        "baseDir": source_info.base_dir.as_posix()
        if source_info.base_dir is not None
        else None,
        "base_dir": source_info.base_dir.as_posix()
        if source_info.base_dir is not None
        else None,
    }


__all__ = [
    "ExtensionRuntime",
    "ExtensionRuntimeContextFactory",
    "ExtensionRuntimeErrorHandler",
]
