from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.source import SourceInfo
from loushang.harness.runtime.bindings import RuntimeBindingLease
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationLeaseCollector,
)
from loushang.harness.workspace.exec import ExecResult, ExecUpdateCallback


def _normalize_exec_args(args: Sequence[str]) -> list[str]:
    if isinstance(args, str):
        raise TypeError("exec_command args must be a sequence of strings, not a string")
    return list(args)


def _compact_custom_instructions(options: object | None) -> str | None:
    if isinstance(options, str):
        return options
    if isinstance(options, dict):
        value = options.get("customInstructions", options.get("custom_instructions"))
        return value if isinstance(value, str) else None
    return None


@dataclass(frozen=True)
class UnboundProductRuntimeContext:
    cwd: str
    get_flag_value: Callable[[str], bool | str | None] = lambda name: None

    @property
    def ui(self) -> "UnboundProductRuntimeContext":
        return self

    @property
    def has_ui(self) -> bool:
        return False

    @property
    def session_manager(self) -> object | None:
        return None

    @property
    def model_registry(self) -> object | None:
        return None

    @property
    def model(self) -> object | None:
        return None

    @property
    def signal(self) -> object | None:
        return None

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
        del command, args, cwd, env, timeout_seconds, stdin, signal, on_update
        del (
            preview_max_lines,
            preview_max_bytes,
            artifact_dir,
            capture_full_output,
            rolling_max_bytes,
        )
        raise RuntimeError("Extension runtime is not bound.")

    def get_active_tool_names(self) -> list[str]:
        return []

    def get_all_tools(self) -> list[object]:
        return []

    def register_tool(self, tool: object) -> None:
        del tool

    def get_flag(self, name: str) -> bool | str | None:
        return self.get_flag_value(name)

    def get_model_selection(self):
        return None

    async def set_active_tools(self, tool_names: list[str]) -> None:
        del tool_names

    async def set_model(self, selection) -> None:
        del selection

    def get_thinking_level(self) -> str:
        return "off"

    async def set_thinking_level(self, level: str) -> None:
        del level

    async def append_entry(self, custom_type: str, data: object | None = None) -> None:
        del custom_type, data

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None:
        del message, options

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None:
        del content, options

    async def set_session_name(self, name: str | None) -> None:
        del name

    def get_session_name(self) -> str | None:
        return None

    async def set_label(self, entry_id: str, label: str | None) -> None:
        del entry_id, label

    def list_commands(self):
        return []

    def request_resource_refresh(self) -> None:
        return None

    def abort(self) -> None:
        return None

    def is_idle(self) -> bool:
        return True

    def has_pending_messages(self) -> bool:
        return False

    def get_context_usage(self) -> object | None:
        return None

    async def compact(self, options: object | None = None) -> object | None:
        del options
        return None

    def get_system_prompt(self) -> str:
        return ""

    async def wait_for_idle(self) -> None:
        return None

    async def reload(self) -> None:
        return None

    async def navigate_tree(
        self, target_id: str, options: object | None = None
    ) -> dict[str, object]:
        del target_id, options
        return {"cancelled": False}

    async def fork(
        self, entry_id: str, options: object | None = None
    ) -> dict[str, object]:
        del entry_id, options
        return {"cancelled": True}

    async def new_session(self, options: object | None = None) -> dict[str, object]:
        del options
        return {"cancelled": True}

    async def switch_session(
        self, session_path: str, options: object | None = None
    ) -> dict[str, object]:
        del session_path, options
        return {"cancelled": True}

    def shutdown(self) -> None:
        return None

    def record_diagnostic(self, diagnostic: DiagnosticDraft) -> None:
        del diagnostic

    def notify(self, message: str, notify_type: str | None = None) -> None:
        del message, notify_type

    def set_status(self, key: str, text: str | None) -> None:
        del key, text

    def set_widget(
        self, key: str, lines: list[str] | None, *, placement: str | None = None
    ) -> None:
        del key, lines, placement

    def set_title(self, title: str) -> None:
        del title

    def set_editor_text(self, text: str) -> None:
        del text

    def get_editor_text(self) -> str:
        return ""

    async def select(
        self, title: str, options: list[str], *, timeout: float | None = None
    ) -> str | None:
        del title, options, timeout
        return None

    async def confirm(
        self, title: str, message: str, *, timeout: float | None = None
    ) -> bool:
        del title, message, timeout
        return False

    async def input(
        self,
        title: str,
        placeholder: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None:
        del title, placeholder, timeout
        return None

    async def editor(
        self,
        title: str,
        prefill: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None:
        del title, prefill, timeout
        return None


class BoundProductRuntimeContext:
    def __init__(
        self,
        runtime_bindings: RuntimeBindingLease[Any],
        tool_source_info: SourceInfo[Path] | None = None,
        *,
        tool_owner_id: str | None = None,
        registrations: RegistrationLeaseCollector | None = None,
        get_flag_value: Callable[[str], bool | str | None] | None = None,
    ) -> None:
        self._runtime_bindings = runtime_bindings
        self._tool_source_info = tool_source_info
        self._tool_owner_id = tool_owner_id
        self._registrations = registrations
        self._get_flag_value = get_flag_value or (lambda name: None)

    @property
    def ui(self) -> "BoundProductRuntimeContext":
        return self

    @property
    def has_ui(self) -> bool:
        return self._ui_context() is not None

    @property
    def cwd(self) -> str:
        return str(self._require_bindings().cwd)

    @property
    def session_manager(self) -> object | None:
        return self._require_bindings().session_manager

    @property
    def model_registry(self) -> object | None:
        return self._require_bindings().model_registry

    @property
    def model(self) -> object | None:
        return self.get_model_selection()

    @property
    def signal(self) -> object | None:
        return self._require_bindings().get_signal()

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
        callback = self._require_bindings().exec_command
        if callback is None:
            raise RuntimeError("Extension runtime does not provide exec_command.")
        return await callback(
            command,
            _normalize_exec_args(args),
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

    def get_active_tool_names(self) -> list[str]:
        return list(self._require_bindings().get_active_tool_names())

    def get_all_tools(self) -> list[object]:
        return list(self._require_bindings().get_all_tools())

    def register_tool(self, tool: object) -> None:
        bindings = self._require_bindings()
        binder = bindings.bind_tool
        registrations = self._registrations
        owner = registrations.owner if registrations is not None else self._tool_owner_id
        if binder is None or owner is None:
            bindings.register_tool(tool, self._tool_source_info)
            return
        lease = binder(tool, owner, self._tool_source_info)
        if not isinstance(lease, RegistrationLease):
            raise TypeError("live tool binding must return a RegistrationLease")
        if registrations is not None:
            registrations.capture(lease)

    def get_flag(self, name: str) -> bool | str | None:
        return self._get_flag_value(name)

    def get_model_selection(self):
        return self._require_bindings().get_model_selection()

    async def set_active_tools(self, tool_names: list[str]) -> None:
        await self._require_bindings().set_active_tools(list(tool_names))

    async def set_model(self, selection) -> None:
        await self._require_bindings().set_model(selection)

    def get_thinking_level(self) -> str:
        return str(self._require_bindings().get_thinking_level())

    async def set_thinking_level(self, level: str) -> None:
        await self._require_bindings().set_thinking_level(level)

    async def append_entry(self, custom_type: str, data: object | None = None) -> None:
        await self._require_bindings().append_entry(custom_type, data)

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None:
        callback = self._require_bindings().send_message
        if callback is None:
            return None
        await callback(message, options)
        return None

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None:
        callback = self._require_bindings().send_user_message
        if callback is None:
            return None
        await callback(content, options)
        return None

    async def set_session_name(self, name: str | None) -> None:
        await self._require_bindings().set_session_name(name)

    def get_session_name(self) -> str | None:
        return self._require_bindings().get_session_name()

    async def set_label(self, entry_id: str, label: str | None) -> None:
        await self._require_bindings().set_label(entry_id, label)

    def list_commands(self):
        return list(self._require_bindings().list_commands())

    def request_resource_refresh(self) -> None:
        self._require_bindings().request_resource_refresh()

    def abort(self) -> None:
        self._require_bindings().abort()

    def is_idle(self) -> bool:
        return bool(self._require_bindings().is_idle())

    def has_pending_messages(self) -> bool:
        return bool(self._require_bindings().has_pending_messages())

    def get_context_usage(self) -> object | None:
        return self._require_bindings().get_context_usage()

    async def compact(self, options: object | None = None) -> object | None:
        callback = self._require_bindings().compact
        if callback is None:
            return None
        return await callback(_compact_custom_instructions(options))

    def get_system_prompt(self) -> str:
        return str(self._require_bindings().get_system_prompt())

    async def wait_for_idle(self) -> None:
        callback = self._require_bindings().wait_for_idle
        if callback is None:
            return None
        await callback()
        return None

    async def reload(self) -> None:
        callback = self._require_bindings().reload
        if callback is None:
            return None
        await callback()
        return None

    async def navigate_tree(
        self, target_id: str, options: object | None = None
    ) -> dict[str, object]:
        callback = self._require_bindings().navigate_tree
        if callback is None:
            return {"cancelled": False}
        result = await callback(target_id, options)
        return result if isinstance(result, dict) else {"cancelled": False}

    async def fork(
        self, entry_id: str, options: object | None = None
    ) -> dict[str, object]:
        callback = self._require_bindings().fork
        if callback is None:
            return {"cancelled": True}
        result = await callback(entry_id, options)
        return result if isinstance(result, dict) else {"cancelled": False}

    async def new_session(self, options: object | None = None) -> dict[str, object]:
        callback = self._require_bindings().new_session
        if callback is None:
            return {"cancelled": True}
        result = await callback(options)
        return result if isinstance(result, dict) else {"cancelled": False}

    async def switch_session(
        self, session_path: str, options: object | None = None
    ) -> dict[str, object]:
        callback = self._require_bindings().switch_session
        if callback is None:
            return {"cancelled": True}
        result = await callback(session_path, options)
        return result if isinstance(result, dict) else {"cancelled": False}

    def shutdown(self) -> None:
        self._require_bindings().shutdown()

    def record_diagnostic(self, diagnostic: DiagnosticDraft) -> None:
        self._require_bindings().record_diagnostic(diagnostic)

    def notify(self, message: str, notify_type: str | None = None) -> None:
        ui = self._ui_context()
        if ui is not None:
            ui.notify(message, notify_type)

    def set_status(self, key: str, text: str | None) -> None:
        setter = getattr(self._require_bindings(), "set_extension_status", None)
        if callable(setter):
            setter(key, text)
        ui = self._ui_context()
        if ui is not None:
            ui.set_status(key, text)

    def set_widget(
        self, key: str, lines: list[str] | None, *, placement: str | None = None
    ) -> None:
        ui = self._ui_context()
        if ui is not None:
            ui.set_widget(key, lines, placement=placement)

    def set_title(self, title: str) -> None:
        ui = self._ui_context()
        if ui is not None:
            ui.set_title(title)

    def set_editor_text(self, text: str) -> None:
        ui = self._ui_context()
        if ui is not None:
            ui.set_editor_text(text)

    def get_editor_text(self) -> str:
        ui = self._ui_context()
        getter = getattr(ui, "get_editor_text", None) if ui is not None else None
        return getter() if callable(getter) else ""

    async def select(
        self, title: str, options: list[str], *, timeout: float | None = None
    ) -> str | None:
        ui = self._ui_context()
        return (
            await ui.select(title, options, timeout=timeout) if ui is not None else None
        )

    async def confirm(
        self, title: str, message: str, *, timeout: float | None = None
    ) -> bool:
        ui = self._ui_context()
        return (
            await ui.confirm(title, message, timeout=timeout)
            if ui is not None
            else False
        )

    async def input(
        self,
        title: str,
        placeholder: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None:
        ui = self._ui_context()
        return (
            await ui.input(title, placeholder, timeout=timeout)
            if ui is not None
            else None
        )

    async def editor(
        self,
        title: str,
        prefill: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None:
        ui = self._ui_context()
        return (
            await ui.editor(title, prefill, timeout=timeout) if ui is not None else None
        )

    def _require_bindings(self):
        return self._runtime_bindings.require()

    def _ui_context(self):
        return getattr(self._require_bindings(), "ui_context", None)


__all__ = ["BoundProductRuntimeContext", "UnboundProductRuntimeContext"]
