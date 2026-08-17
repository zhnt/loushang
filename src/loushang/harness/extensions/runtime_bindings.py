"""Build the shared extension runtime binding record from Product ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import cast

from loushang.agent import ThinkingLevel
from loushang.ai.model import ModelSelection
from loushang.harness.commands import SessionCommandDescriptor
from loushang.harness.context import serialize_context_usage_payload
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.context import ExtensionRuntimeBindings
from loushang.harness.runtime.registration import RegistrationLease, RegistrationOwner
from loushang.harness.workspace.exec import ExecResult


@dataclass
class ExtensionRuntimeBindingFactory:
    """Compose opaque Product callbacks into the shared extension contract."""

    get_cwd: Callable[[], str]
    session_manager: object | None
    model_registry: object | None
    get_active_tool_names: Callable[[], list[str]]
    get_all_tools: Callable[[], list[object]]
    get_model_selection: Callable[[], ModelSelection | None]
    set_active_tools: Callable[[list[str]], Awaitable[None]]
    set_model: Callable[[ModelSelection], Awaitable[None]]
    register_tool: Callable[[object, object | None], None]
    append_entry: Callable[[str, object | None], Awaitable[None]]
    send_message: Callable[[object, object | None], Awaitable[None]]
    send_user_message: Callable[[object, object | None], Awaitable[None]]
    get_signal: Callable[[], object | None]
    set_session_name: Callable[[str | None], Awaitable[None]]
    get_session_name: Callable[[], str | None]
    set_label: Callable[[str, str | None], Awaitable[None]]
    list_commands: Callable[[], list[SessionCommandDescriptor]]
    request_resource_refresh: Callable[[], None]
    shutdown: Callable[[], None]
    record_diagnostic: Callable[[DiagnosticDraft], None]
    abort: Callable[[], None]
    is_idle: Callable[[], bool]
    has_pending_messages: Callable[[], bool]
    get_context_usage: Callable[[], object | None]
    get_thinking_level: Callable[[], ThinkingLevel]
    set_thinking_level: Callable[[ThinkingLevel], Awaitable[None]]
    register_provider: Callable[[str, object], None] | None
    unregister_provider: Callable[[str], None] | None
    set_extension_status: Callable[[str, str | None], None]
    get_footer_data_provider: Callable[[], object | None]
    compact: Callable[[str | None], Awaitable[object | None]]
    get_system_prompt: Callable[[], str]
    wait_for_idle: Callable[[], Awaitable[None]]
    reload: Callable[[], Awaitable[None]]
    navigate_tree: Callable[[str, object | None], Awaitable[dict[str, object]]]
    fork: Callable[[str, object | None], Awaitable[dict[str, object]]]
    new_session: Callable[[object | None], Awaitable[dict[str, object]]]
    switch_session: Callable[[str, object | None], Awaitable[dict[str, object]]]
    get_ui_context: Callable[[], object | None]
    exec_command: Callable[..., Awaitable[ExecResult]] | None = None
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

    def build(self) -> ExtensionRuntimeBindings:
        async def set_model(selection: object) -> None:
            if not isinstance(selection, ModelSelection):
                raise TypeError("model selection must be a ModelSelection")
            await self.set_model(selection)

        def list_commands() -> Sequence[object]:
            return self.list_commands()

        async def set_thinking_level(level: str) -> None:
            if level not in {"off", "minimal", "low", "medium", "high", "xhigh"}:
                raise ValueError(f"unsupported thinking level: {level}")
            await self.set_thinking_level(cast(ThinkingLevel, level))

        ui_context = self.get_ui_context()
        extension_error_handler = (
            getattr(ui_context, "emit_extension_error", None)
            if ui_context is not None
            else None
        )
        return ExtensionRuntimeBindings(
            cwd=self.get_cwd(),
            session_manager=self.session_manager,
            model_registry=self.model_registry,
            get_active_tool_names=self.get_active_tool_names,
            get_all_tools=self.get_all_tools,
            get_model_selection=self.get_model_selection,
            set_active_tools=self.set_active_tools,
            set_model=set_model,
            register_tool=self.register_tool,
            bind_tool=self.bind_tool,
            adopt_tool=self.adopt_tool,
            append_entry=self.append_entry,
            send_message=self.send_message,
            send_user_message=self.send_user_message,
            get_signal=self.get_signal,
            set_session_name=self.set_session_name,
            get_session_name=self.get_session_name,
            set_label=self.set_label,
            list_commands=list_commands,
            request_resource_refresh=self.request_resource_refresh,
            shutdown=self.shutdown,
            record_diagnostic=self.record_diagnostic,
            abort=self.abort,
            is_idle=self.is_idle,
            has_pending_messages=self.has_pending_messages,
            get_context_usage=lambda: serialize_context_usage_payload(
                self.get_context_usage()
            ),
            get_thinking_level=self.get_thinking_level,
            set_thinking_level=set_thinking_level,
            register_provider=self.register_provider,
            unregister_provider=self.unregister_provider,
            bind_provider=self.bind_provider,
            bind_provider_removal=self.bind_provider_removal,
            stage_tool=self.stage_tool,
            stage_provider=self.stage_provider,
            stage_provider_removal=self.stage_provider_removal,
            set_extension_status=self.set_extension_status,
            footer_data_provider=self.get_footer_data_provider(),
            compact=self.compact,
            get_system_prompt=self.get_system_prompt,
            wait_for_idle=self.wait_for_idle,
            reload=self.reload,
            navigate_tree=self.navigate_tree,
            fork=self.fork,
            new_session=self.new_session,
            switch_session=self.switch_session,
            exec_command=self.exec_command,
            ui_context=ui_context,
            on_error=(
                extension_error_handler if callable(extension_error_handler) else None
            ),
        )


__all__ = ["ExtensionRuntimeBindingFactory"]
