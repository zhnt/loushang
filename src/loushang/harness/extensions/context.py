"""Product-neutral extension context and session lifecycle contracts.

The contracts in this module describe capabilities an extension may receive at
runtime.  Products bind those capabilities from their own session, model, and
presentation layers; Harness does not interpret their values.  UI operations
use snake_case only.  Pi-style camelCase UI aliases are intentionally not part
of this API.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.runtime.bindings import ProductRuntimeBindings
from loushang.harness.runtime.context import (
    BoundProductRuntimeContext,
    UnboundProductRuntimeContext,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.workspace.exec import ExecResult, ExecUpdateCallback

# The capability record is deliberately opaque about Product values such as
# model selection.  A Product may add typed helpers without changing this
# shared extension contract.
ExtensionRuntimeBindings = ProductRuntimeBindings
BoundExtensionContext = BoundProductRuntimeContext
UnboundExtensionContext = UnboundProductRuntimeContext


class ExtensionUiContext(Protocol):
    """Portable, channel-independent UI operations available to extensions."""

    def notify(self, message: str, notify_type: str | None = None) -> None: ...

    def set_status(self, key: str, text: str | None) -> None: ...

    def set_widget(
        self, key: str, lines: list[str] | None, *, placement: str | None = None
    ) -> None: ...

    def set_title(self, title: str) -> None: ...

    def set_editor_text(self, text: str) -> None: ...

    def get_editor_text(self) -> str: ...

    async def select(
        self, title: str, options: list[str], *, timeout: float | None = None
    ) -> str | None: ...

    async def confirm(
        self, title: str, message: str, *, timeout: float | None = None
    ) -> bool: ...

    async def input(
        self,
        title: str,
        placeholder: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None: ...

    async def editor(
        self,
        title: str,
        prefill: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None: ...


class ExtensionContext(ExtensionUiContext, Protocol):
    """Standard extension runtime surface.

    All Product-specific values flow through opaque objects or injected
    callbacks.  The protocol therefore works for Coding, Research, Design,
    PPT, OEM hosts, and remote channels without importing a Product package.
    """

    @property
    def ui(self) -> ExtensionUiContext: ...

    @property
    def has_ui(self) -> bool: ...

    @property
    def cwd(self) -> str: ...

    @property
    def session_manager(self) -> object | None: ...

    @property
    def model_registry(self) -> object | None: ...

    @property
    def model(self) -> object | None: ...

    @property
    def signal(self) -> object | None: ...

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
    ) -> ExecResult: ...

    def get_active_tool_names(self) -> list[str]: ...

    def get_all_tools(self) -> list[object]: ...

    def register_tool(self, tool: ToolDefinition) -> None: ...

    def get_flag(self, name: str) -> bool | str | None: ...

    def get_model_selection(self) -> object | None: ...

    async def set_active_tools(self, tool_names: list[str]) -> None: ...

    async def set_model(self, selection: object) -> None: ...

    def get_thinking_level(self) -> str: ...

    async def set_thinking_level(self, level: str) -> None: ...

    async def append_entry(
        self, custom_type: str, data: object | None = None
    ) -> None: ...

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None: ...

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None: ...

    async def set_session_name(self, name: str | None) -> None: ...

    def get_session_name(self) -> str | None: ...

    async def set_label(self, entry_id: str, label: str | None) -> None: ...

    def list_commands(self) -> list[object]: ...

    def request_resource_refresh(self) -> None: ...

    def abort(self) -> None: ...

    def is_idle(self) -> bool: ...

    def has_pending_messages(self) -> bool: ...

    def get_context_usage(self) -> object | None: ...

    def compact(self, options: object | None = None) -> Awaitable[object | None]: ...

    def get_system_prompt(self) -> str: ...

    async def wait_for_idle(self) -> None: ...

    async def reload(self) -> None: ...

    async def navigate_tree(
        self, target_id: str, options: object | None = None
    ) -> dict[str, object]: ...

    async def fork(
        self, entry_id: str, options: object | None = None
    ) -> dict[str, object]: ...

    async def new_session(self, options: object | None = None) -> dict[str, object]: ...

    async def switch_session(
        self, session_path: str, options: object | None = None
    ) -> dict[str, object]: ...

    def shutdown(self) -> None: ...

    def record_diagnostic(self, diagnostic: DiagnosticDraft) -> None: ...


class ExtensionCommandContext(ExtensionContext, Protocol):
    """Context passed to a command contribution."""


class ReplacedSessionContext(ExtensionCommandContext, Protocol):
    """Context passed after a product session has been replaced."""


@dataclass(frozen=True)
class SessionStartEvent:
    reason: str = "startup"
    previous_session_file: str | None = None
    type: Literal["session_start"] = "session_start"

@dataclass(frozen=True)
class SessionShutdownEvent:
    reason: str = "quit"
    target_session_file: str | None = None
    type: Literal["session_shutdown"] = "session_shutdown"

@dataclass(frozen=True)
class SessionRefreshEvent:
    reason: str
    type: Literal["session_refresh"] = "session_refresh"


@dataclass(frozen=True)
class SessionBeforeSwitchEvent:
    reason: str
    cwd: str
    target_session_file: str | None = None
    type: Literal["session_before_switch"] = "session_before_switch"

@dataclass(frozen=True)
class SessionBeforeForkEvent:
    entry_id: str
    cwd: str
    position: str = "before"
    type: Literal["session_before_fork"] = "session_before_fork"

@dataclass(frozen=True)
class SessionBeforeCompactEvent:
    reason: str
    cwd: str
    custom_instructions: str | None = None
    type: Literal["session_before_compact"] = "session_before_compact"

@dataclass(frozen=True)
class SessionBeforeTreeEvent:
    target_id: str
    old_leaf_id: str | None
    cwd: str
    new_leaf_id: str | None = None
    summarize: bool = False
    custom_instructions: str | None = None
    replace_instructions: bool = False
    label: str | None = None
    type: Literal["session_before_tree"] = "session_before_tree"

@dataclass(frozen=True)
class SessionActionDecision:
    cancel: bool = False
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)


@dataclass(frozen=True)
class SessionBeforeForkResult(SessionActionDecision):
    skip_conversation_restore: bool = False


@dataclass(frozen=True)
class SessionBeforeCompactResult(SessionActionDecision):
    compaction: object | None = None


@dataclass(frozen=True)
class SessionBeforeTreeResult(SessionActionDecision):
    summary: object | None = None
    custom_instructions: str | None = None
    replace_instructions: bool | None = None
    label: str | None = None


__all__ = [
    "ExtensionCommandContext",
    "ExtensionContext",
    "ExtensionRuntimeBindings",
    "ExtensionUiContext",
    "BoundExtensionContext",
    "ReplacedSessionContext",
    "SessionActionDecision",
    "SessionBeforeCompactEvent",
    "SessionBeforeCompactResult",
    "SessionBeforeForkEvent",
    "SessionBeforeForkResult",
    "SessionBeforeSwitchEvent",
    "SessionBeforeTreeEvent",
    "SessionBeforeTreeResult",
    "SessionRefreshEvent",
    "SessionShutdownEvent",
    "SessionStartEvent",
    "UnboundExtensionContext",
]
