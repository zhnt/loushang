from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.runtime.registration import RegistrationLease, RegistrationOwner
from loushang.harness.workspace.exec import ExecResult

B = TypeVar("B")


def _unbound_tool(tool: object, source_info: object | None = None) -> None:
    del tool, source_info
    raise RuntimeError("live tool registration is not bound")


async def _ignore_entry(custom_type: str, data: object | None = None) -> None:
    del custom_type, data


async def _ignore_session_name(name: str | None) -> None:
    del name


async def _ignore_label(entry_id: str, label: str | None) -> None:
    del entry_id, label


async def _ignore_thinking_level(level: str) -> None:
    del level


@dataclass
class ProductRuntimeBindings:
    """Opaque product capabilities exposed to shared runtime surfaces."""

    cwd: str
    get_active_tool_names: Callable[[], list[str]]
    get_model_selection: Callable[[], object | None]
    set_active_tools: Callable[[list[str]], Awaitable[None]]
    set_model: Callable[[object], Awaitable[None]]
    request_resource_refresh: Callable[[], None]
    shutdown: Callable[[], None]
    record_diagnostic: Callable[[DiagnosticDraft], None]
    register_tool: Callable[[object, object | None], None] = _unbound_tool
    get_all_tools: Callable[[], list[object]] = lambda: []
    session_manager: object | None = None
    model_registry: object | None = None
    get_signal: Callable[[], object | None] = lambda: None
    append_entry: Callable[[str, object | None], Awaitable[None]] = _ignore_entry
    send_message: Callable[[object, object | None], Awaitable[None]] | None = None
    send_user_message: Callable[[object, object | None], Awaitable[None]] | None = None
    set_session_name: Callable[[str | None], Awaitable[None]] = _ignore_session_name
    get_session_name: Callable[[], str | None] = lambda: None
    set_label: Callable[[str, str | None], Awaitable[None]] = _ignore_label
    list_commands: Callable[[], Sequence[object]] = lambda: ()
    abort: Callable[[], None] = lambda: None
    is_idle: Callable[[], bool] = lambda: True
    has_pending_messages: Callable[[], bool] = lambda: False
    get_context_usage: Callable[[], object | None] = lambda: None
    get_thinking_level: Callable[[], str] = lambda: "off"
    set_thinking_level: Callable[[str], Awaitable[None]] = _ignore_thinking_level
    register_provider: Callable[[str, object], None] | None = None
    unregister_provider: Callable[[str], None] | None = None
    set_extension_status: Callable[[str, str | None], None] = lambda key, text: None
    footer_data_provider: object | None = None
    compact: Callable[[str | None], Awaitable[object | None]] | None = None
    get_system_prompt: Callable[[], str] = lambda: ""
    wait_for_idle: Callable[[], Awaitable[None]] | None = None
    reload: Callable[[], Awaitable[None]] | None = None
    navigate_tree: (
        Callable[[str, object | None], Awaitable[dict[str, object]]] | None
    ) = None
    fork: Callable[[str, object | None], Awaitable[dict[str, object]]] | None = None
    new_session: Callable[[object | None], Awaitable[dict[str, object]]] | None = None
    switch_session: (
        Callable[[str, object | None], Awaitable[dict[str, object]]] | None
    ) = None
    exec_command: Callable[..., Awaitable[ExecResult]] | None = None
    ui_context: object | None = None
    on_error: Callable[[dict[str, object]], None] | None = None
    bind_tool: (
        Callable[[object, RegistrationOwner | str, object | None], RegistrationLease]
        | None
    ) = None
    adopt_tool: (
        Callable[
            [object, RegistrationOwner, object | None],
            RegistrationLease | None,
        ]
        | None
    ) = None
    bind_provider: (
        Callable[[str, object, RegistrationOwner], RegistrationLease] | None
    ) = None
    bind_provider_removal: (
        Callable[[str, RegistrationOwner], RegistrationLease] | None
    ) = None
    stage_tool: (
        Callable[[object, RegistrationOwner, object | None], RegistrationLease] | None
    ) = None
    stage_provider: (
        Callable[[str, object, RegistrationOwner], RegistrationLease] | None
    ) = None
    stage_provider_removal: (
        Callable[[str, RegistrationOwner], RegistrationLease] | None
    ) = None


class RuntimeBindingState(Generic[B]):
    """Own live runtime bindings and invalidate generation-scoped contexts."""

    def __init__(
        self,
        bindings: B | None = None,
        *,
        unbound_message: str = "Runtime bindings have not been set.",
        stale_message: str = "Runtime context is stale.",
    ) -> None:
        self._bindings = bindings
        self._generation = 0
        self._unbound_message = unbound_message
        self._stale_message = stale_message

    @property
    def bindings(self) -> B | None:
        return self._bindings

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def stale_message(self) -> str:
        return self._stale_message

    @property
    def is_bound(self) -> bool:
        return self._bindings is not None

    def bind(self, bindings: B) -> None:
        self._bindings = bindings

    def refresh(self, bindings: B) -> None:
        self._bindings = bindings

    def invalidate(self, message: str | None = None) -> None:
        self._generation += 1
        if message is not None:
            self._stale_message = message

    def capture(self) -> RuntimeBindingLease[B]:
        return RuntimeBindingLease(state=self, generation=self._generation)

    def require(self, *, generation: int | None = None) -> B:
        if generation is not None and generation != self._generation:
            raise RuntimeError(self._stale_message)
        bindings = self._bindings
        if bindings is None:
            raise RuntimeError(self._unbound_message)
        return bindings


@dataclass(frozen=True)
class RuntimeBindingLease(Generic[B]):
    state: RuntimeBindingState[B]
    generation: int

    @property
    def is_current(self) -> bool:
        return self.generation == self.state.generation

    def require(self) -> B:
        return self.state.require(generation=self.generation)


__all__ = [
    "ProductRuntimeBindings",
    "RuntimeBindingLease",
    "RuntimeBindingState",
]
