from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from loushang.harness.contributions import ExtensionSurfaceDescriptor
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS
from loushang.harness.extensions.routing import RegisteredExtensionHandler
from loushang.harness.extensions.types import (
    ExtensionHandler,
    LoadedExtension,
    RegisteredCommand,
    RegisteredControlContribution,
    RegisteredFlag,
    RegisteredRuntimeCapabilityReplacement,
    RegisteredShortcut,
)
from loushang.harness.resources.source import SourceInfo
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationLeaseCollector,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.workspace.exec import ExecResult, ExecUpdateCallback


class ExtensionContributionAPI:
    """Product-neutral API for declaring and binding extension contributions."""

    def __init__(
        self,
        *,
        name: str,
        source_path: Path,
        entry_path: Path | None = None,
    ) -> None:
        self._name = name
        self._source_path = source_path
        self._entry_path = entry_path
        self._hooks: dict[str, list[object]] = {}
        self._handler_registrations: list[RegisteredExtensionHandler] = []
        self._control_contributions: list[RegisteredControlContribution] = []
        self._runtime_capability_replacements: list[
            RegisteredRuntimeCapabilityReplacement
        ] = []
        self._tool_definitions: list[ToolDefinition] = []
        self._commands: dict[str, RegisteredCommand] = {}
        self._flags: dict[str, RegisteredFlag] = {}
        self._shortcuts: dict[str, RegisteredShortcut] = {}
        self._message_renderers: dict[
            str, Callable[[object, object, object], object | None]
        ] = {}
        self._diagnostics: list[DiagnosticDraft] = []
        self._runtime_state: object | None = None
        self._runtime_generation: int | None = None
        self._registrations: RegistrationLeaseCollector | None = None

    def on(
        self,
        event_name: str,
        handler: object,
        *,
        route_id: str | None = None,
        priority: int = 0,
        after: Sequence[str] = (),
        before: Sequence[str] = (),
        on_error: Literal["skip", "fail_chain"] = "skip",
    ) -> None:
        if event_name not in VALID_EXTENSION_EVENTS:
            raise ValueError(f"Unsupported extension event: {event_name}")
        if not callable(handler):
            raise TypeError("Extension hook handler must be callable.")
        event_registration_count = sum(
            registration.event_name == event_name
            for registration in self._handler_registrations
        )
        registration = RegisteredExtensionHandler(
            local_route_id=(
                f"legacy-{event_registration_count + 1:04d}"
                if route_id is None
                else route_id
            ),
            event_name=event_name,
            handler=cast(ExtensionHandler, handler),
            priority=priority,
            after=_normalize_references(after),
            before=_normalize_references(before),
            on_error=on_error,
        )
        self._handler_registrations.append(registration)
        self._hooks.setdefault(event_name, []).append(handler)

    def register_tool(
        self,
        tool_definition: ToolDefinition,
    ) -> None:
        if not isinstance(tool_definition, ToolDefinition):
            raise TypeError(
                "extension tools require direct_tool(...) or "
                "authorized_tool(...) before registration"
            )
        self._tool_definitions.append(tool_definition)
        self._register_runtime_tool(tool_definition)

    def register_policy(
        self,
        name: str,
        evaluator: object,
        *,
        priority: int = 0,
        after: Sequence[str] = (),
        before: Sequence[str] = (),
        on_error: Literal["skip", "fail_chain"] = "fail_chain",
    ) -> None:
        self._register_control_contribution(
            "policy",
            name,
            evaluator,
            priority=priority,
            after=after,
            before=before,
            on_error=on_error,
        )

    def register_approval(
        self,
        name: str,
        resolver: object,
        *,
        priority: int = 0,
        after: Sequence[str] = (),
        before: Sequence[str] = (),
    ) -> None:
        self._register_control_contribution(
            "approval",
            name,
            resolver,
            priority=priority,
            after=after,
            before=before,
            on_error="fail_chain",
        )

    def register_command(
        self,
        name: str,
        *,
        description: str | None = None,
        handler: Callable[[str, object], Awaitable[None]],
        get_argument_completions: (
            Callable[[str], list[object] | Awaitable[list[object] | None] | None] | None
        ) = None,
    ) -> None:
        self._commands[name] = RegisteredCommand(
            name=name,
            handler=handler,
            description=description,
            get_argument_completions=get_argument_completions,
        )

    def register_flag(
        self,
        name: str,
        *,
        type: Literal["boolean", "string"],
        description: str | None = None,
        default: bool | str | None = None,
    ) -> None:
        if type not in {"boolean", "string"}:
            raise ValueError(f"Unsupported flag type: {type}")
        if type == "boolean" and default is not None and not isinstance(default, bool):
            raise ValueError("Boolean flags must use a boolean default.")
        if type == "string" and default is not None and not isinstance(default, str):
            raise ValueError("String flags must use a string default.")
        self._flags[name] = RegisteredFlag(
            name=name,
            type=type,
            description=description,
            default=default,
        )

    def register_shortcut(
        self,
        shortcut: str,
        *,
        description: str | None = None,
        handler: Callable[[object], object | None],
    ) -> None:
        self._shortcuts[shortcut] = RegisteredShortcut(
            shortcut=shortcut,
            handler=handler,
            description=description,
        )

    def register_message_renderer(
        self,
        custom_type: str,
        renderer: Callable[[object, object, object], object | None],
    ) -> None:
        self._message_renderers[custom_type] = renderer

    def bind_runtime_state(
        self,
        runtime_state: object,
        registrations: RegistrationLeaseCollector | None = None,
    ) -> None:
        self._runtime_state = runtime_state
        generation = getattr(runtime_state, "generation", None)
        self._runtime_generation = generation if isinstance(generation, int) else None
        self._registrations = registrations

    def get_active_tools(self) -> list[str]:
        bindings = self._runtime_bindings()
        getter = getattr(bindings, "get_active_tool_names", None)
        return list(getter()) if callable(getter) else []

    def get_all_tools(self) -> list[object]:
        bindings = self._runtime_bindings()
        getter = getattr(bindings, "get_all_tools", None)
        return list(getter()) if callable(getter) else []

    def get_commands(self) -> list[object]:
        bindings = self._runtime_bindings()
        getter = getattr(bindings, "list_commands", None)
        return list(getter()) if callable(getter) else []

    def get_flag(self, name: str) -> bool | str | None:
        values = getattr(self._runtime_state, "flag_values", None)
        return values.get(name) if isinstance(values, dict) else None

    async def set_active_tools(self, tool_names: list[str]) -> None:
        callback = getattr(self._runtime_bindings(), "set_active_tools", None)
        if callable(callback):
            await callback(list(tool_names))

    async def exec_command(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
        preview_max_lines: int = 2000,
        preview_max_bytes: int = 50 * 1024,
        artifact_dir: str | None = None,
        capture_full_output: bool = True,
        rolling_max_bytes: int = 100 * 1024,
    ) -> ExecResult:
        bindings = self._runtime_bindings()
        if bindings is None:
            raise RuntimeError("Extension runtime is not bound.")
        callback = getattr(bindings, "exec_command", None)
        if not callable(callback):
            raise RuntimeError("Extension runtime does not provide exec_command.")
        if isinstance(args, str):
            raise TypeError(
                "exec_command args must be a sequence of strings, not a string"
            )
        result = callback(
            command,
            list(args),
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            signal=signal,
            on_update=on_update,
            preview_max_lines=preview_max_lines,
            preview_max_bytes=preview_max_bytes,
            artifact_dir=artifact_dir,
            capture_full_output=capture_full_output,
            rolling_max_bytes=rolling_max_bytes,
        )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ExecResult):
            raise TypeError("exec_command runtime binding must return ExecResult")
        return result

    def build_loaded_extension(self) -> LoadedExtension:
        return LoadedExtension(
            name=self._name,
            source_path=self._source_path,
            entry_path=self._entry_path,
            hooks={
                name: cast(list[ExtensionHandler], list(handlers))
                for name, handlers in self._hooks.items()
            },
            handler_registrations=list(self._handler_registrations),
            control_contributions=list(self._control_contributions),
            runtime_capability_replacements=list(self._runtime_capability_replacements),
            tool_definitions=list(self._tool_definitions),
            commands=dict(self._commands),
            flags=dict(self._flags),
            shortcuts=dict(self._shortcuts),
            message_renderers=dict(self._message_renderers),
            diagnostics=list(self._diagnostics),
            api=self,
        )

    def _runtime_bindings(self) -> object | None:
        runtime_state = self._runtime_state
        if runtime_state is None:
            return None
        generation = self._runtime_generation
        require = getattr(runtime_state, "require", None)
        if generation is not None and callable(require):
            return require(generation=generation)
        return getattr(runtime_state, "bindings", None)

    def _register_runtime_tool(self, definition: ToolDefinition) -> None:
        bindings = self._runtime_bindings()
        binder = getattr(bindings, "bind_tool", None)
        source_info = SourceInfo(path=self._entry_path or self._source_path)
        if callable(binder):
            registrations = self._registrations
            owner = registrations.owner if registrations is not None else self._name
            lease = binder(definition, owner, source_info)
            if not isinstance(lease, RegistrationLease):
                raise TypeError("live tool binding must return a RegistrationLease")
            if registrations is not None:
                registrations.capture(lease)
            return
        callback = getattr(bindings, "register_tool", None)
        if callable(callback):
            callback(definition, source_info)

    def _register_control_contribution(
        self,
        contribution_type: Literal["policy", "approval"],
        name: str,
        value: object,
        *,
        priority: int,
        after: Sequence[str],
        before: Sequence[str],
        on_error: Literal["skip", "fail_chain"],
    ) -> None:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Control contribution name must not be empty.")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypeError("Control contribution priority must be an integer.")
        normalized_after = _normalize_references(after)
        normalized_before = _normalize_references(before)
        if on_error not in {"skip", "fail_chain"}:
            raise ValueError(
                f"Unsupported control contribution error policy: {on_error}"
            )
        self._control_contributions.append(
            RegisteredControlContribution(
                descriptor=ExtensionSurfaceDescriptor(
                    type=contribution_type,
                    name=normalized_name,
                    extension_id=self._name,
                    source_path=self._entry_path or self._source_path,
                    priority=priority,
                    after=normalized_after,
                    before=normalized_before,
                    on_error=on_error,
                    metadata={"source": "runtime"},
                ),
                value=value,
            )
        )

    def _register_runtime_capability_replacement(
        self,
        replacement: RegisteredRuntimeCapabilityReplacement,
    ) -> None:
        if not isinstance(replacement, RegisteredRuntimeCapabilityReplacement):
            raise TypeError(
                "replacement must be a RegisteredRuntimeCapabilityReplacement"
            )
        self._runtime_capability_replacements.append(replacement)


def _normalize_references(references: Sequence[str]) -> tuple[str, ...]:
    if isinstance(references, str):
        raise TypeError("Extension ordering references must be a sequence of strings.")
    values = tuple(references)
    if not all(isinstance(reference, str) for reference in values):
        raise TypeError("Extension ordering references must be a sequence of strings.")
    normalized = tuple(reference.strip() for reference in values)
    if any(not reference for reference in normalized):
        raise ValueError("Extension ordering references must not be empty.")
    return normalized


__all__ = ["ExtensionContributionAPI"]
