"""Assemble the extension-facing profile of a composed Agent session."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from loushang.agent.types import ThinkingLevel
from loushang.ai.api_registry import APIRegistry
from loushang.ai.model import ModelSelection
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions import ExtensionProviderRuntime
from loushang.harness.extensions.agent import ExtensionInputRuntime
from loushang.harness.extensions.agent.input_adapter import ExtensionInputAdapter
from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.extensions.context import (
    ExtensionRuntimeBindings,
    SessionStartEvent,
)
from loushang.harness.extensions.provider_config import provider_from_extension_config
from loushang.harness.extensions.runtime_bindings import ExtensionRuntimeBindingFactory
from loushang.harness.extensions.session_runtime import (
    ExtensionSessionRuntime,
    SessionExtensionRuntimePort,
)
from loushang.harness.resources.watcher import ResourceChangeWatcher
from loushang.harness.session.bindings import SessionExtensionBinding
from loushang.harness.session.command_controller import SessionCommandController
from loushang.harness.session.extension_bridge import AgentSessionExtensionBridge
from loushang.harness.session.resource_refresh import SessionResourceRefreshRuntime
from loushang.harness.session.runtime import SessionRuntime
from loushang.harness.session.tool_controller import SessionToolController
from loushang.harness.transcript import (
    AgentTranscriptNavigationRuntime,
    AgentTranscriptSelectionRuntime,
    BranchSummaryOutput,
    ProductTranscriptSession,
)

BranchSummaryExecutor = Callable[..., Awaitable[BranchSummaryOutput]]


class ExtensionCompositionAgentPort(Protocol):
    """Live Agent state exposed through extension runtime bindings."""

    @property
    def is_streaming(self) -> bool: ...

    @property
    def signal(self) -> object: ...

    @property
    def system_prompt(self) -> str: ...

    @property
    def thinking_level(self) -> ThinkingLevel: ...


class SessionExtensionAssemblyPort(
    SessionExtensionRuntimePort[ExtensionRuntimeBindings],
    Protocol,
):
    """Extension runtime surface needed during session assembly."""

    def list_extensions(self) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class AgentSessionExtensionCompositionPorts:
    """Narrow inputs for the extension-facing session profile."""

    agent: ExtensionCompositionAgentPort
    session: ProductTranscriptSession[Any, Any]
    model_registry: object | None
    api_registry: APIRegistry
    extension_runner: SessionExtensionAssemblyPort | None
    provider_controller: ExtensionProviderRuntime | None
    replacement_controller: ExtensionReplacementRuntime | None
    runtime_binding_factory: ExtensionRuntimeBindingFactory | None
    bridge: AgentSessionExtensionBridge
    session_start_event: SessionStartEvent
    tool_controller: SessionToolController
    command_controller: SessionCommandController[Any]
    selection_runtime: AgentTranscriptSelectionRuntime
    session_runtime: SessionRuntime
    navigation_runtime: AgentTranscriptNavigationRuntime
    resource_refresh_runtime: SessionResourceRefreshRuntime
    resource_watch_controller: ResourceChangeWatcher
    footer_data_provider: object
    get_context_usage: Callable[[], object | None]
    set_model: Callable[[ModelSelection], Awaitable[None]]
    set_session_name: Callable[[str | None], Awaitable[None]]
    compact: Callable[[str | None], Awaitable[object | None]]
    execute_branch_summary: BranchSummaryExecutor
    record_runtime_diagnostic: Callable[[DiagnosticDraft], None]
    sync_extension_diagnostics: Callable[..., None]


@dataclass(frozen=True)
class AgentSessionExtensionComposition:
    """Extension components installed into the standard session composition."""

    input_runtime: ExtensionInputRuntime
    message_controller: ExtensionInputAdapter
    provider_controller: ExtensionProviderRuntime
    replacement_controller: ExtensionReplacementRuntime
    runtime_binding_factory: ExtensionRuntimeBindingFactory
    binding: SessionExtensionBinding


def compose_agent_session_extensions(
    ports: AgentSessionExtensionCompositionPorts,
) -> AgentSessionExtensionComposition:
    """Build and bind all extension-facing components for one session."""

    input_runtime = ExtensionInputRuntime(
        application_inputs=ports.session_runtime.application_inputs,
        prepared_user_inputs=ports.session_runtime.queue,
        run_prompt=ports.session_runtime.run_agent_prompt,
    )
    message_controller = ExtensionInputAdapter(
        agent=ports.agent,
        runtime=input_runtime,
    )
    provider_controller = ports.provider_controller or ExtensionProviderRuntime(
        model_registry=ports.model_registry,
        api_registry=ports.api_registry,
        provider_factory=provider_from_extension_config,
    )
    replacement_controller = (
        ports.replacement_controller
        or ExtensionReplacementRuntime(
            get_runtime_host=lambda: ports.bridge.runtime_host,
        )
    )
    runtime_binding_factory = ports.runtime_binding_factory or _build_binding_factory(
        ports,
        message_controller=message_controller,
    )
    runtime_controller = ExtensionSessionRuntime(
        extension_runtime=ports.extension_runner,
        build_bindings=runtime_binding_factory.build,
        session_start_event=ports.session_start_event,
        refresh_resources=lambda: ports.resource_refresh_runtime.refresh_async(
            reason="reload"
        ),
        record_runtime_diagnostic=ports.record_runtime_diagnostic,
        sync_extension_diagnostics=ports.sync_extension_diagnostics,
    )
    ports.bridge.attach_runtime(runtime_controller)
    binding = SessionExtensionBinding(
        start_runtime_callback=lambda reason: ports.bridge.bind(reason=reason),
        reload_runtime_callback=lambda: ports.bridge.bind(reason="reload"),
        poll_resource_changes_callback=ports.resource_watch_controller.poll_once,
        start_resource_watcher_callback=lambda interval: (
            ports.resource_watch_controller.start(interval_seconds=interval)
        ),
        stop_resource_watcher_callback=ports.resource_watch_controller.stop,
        set_ui_context_callback=ports.bridge.set_ui_context,
        set_runtime_host_callback=ports.bridge.set_runtime_host,
        list_extensions_callback=lambda: (
            ports.extension_runner.list_extensions()
            if ports.extension_runner is not None
            else []
        ),
    )
    return AgentSessionExtensionComposition(
        input_runtime=input_runtime,
        message_controller=message_controller,
        provider_controller=provider_controller,
        replacement_controller=replacement_controller,
        runtime_binding_factory=runtime_binding_factory,
        binding=binding,
    )


def _build_binding_factory(
    ports: AgentSessionExtensionCompositionPorts,
    *,
    message_controller: ExtensionInputAdapter,
) -> ExtensionRuntimeBindingFactory:
    session = ports.session
    agent = ports.agent
    selection_runtime = ports.selection_runtime
    tool_controller = ports.tool_controller
    session_runtime = ports.session_runtime
    return ExtensionRuntimeBindingFactory(
        get_cwd=session.get_cwd,
        session_manager=session,
        model_registry=ports.model_registry,
        get_active_tool_names=tool_controller.get_active_tool_names,
        get_all_tools=lambda: list(tool_controller.get_all_tools()),
        get_model_selection=selection_runtime.get_model_selection,
        set_active_tools=lambda names: _set_active_tools(
            tool_controller,
            names,
            ports.resource_refresh_runtime.refresh,
        ),
        set_model=ports.set_model,
        register_tool=partial(_register_extension_tool, tool_controller),
        append_entry=partial(_append_extension_entry, session),
        send_message=message_controller.send_message,
        send_user_message=message_controller.send_user_message,
        get_signal=lambda: agent.signal,
        set_session_name=ports.set_session_name,
        get_session_name=lambda: session.get_session_record().metadata.name,
        set_label=partial(_set_extension_label, session),
        list_commands=ports.command_controller.list_commands,
        request_resource_refresh=ports.resource_refresh_runtime.request_refresh,
        shutdown=lambda: _abort_session(session_runtime),
        record_diagnostic=ports.record_runtime_diagnostic,
        abort=lambda: _abort_session(session_runtime),
        is_idle=lambda: not agent.is_streaming,
        has_pending_messages=message_controller.has_pending_messages,
        get_context_usage=ports.get_context_usage,
        get_thinking_level=lambda: agent.thinking_level,
        set_thinking_level=selection_runtime.set_thinking_level,
        register_provider=None,
        unregister_provider=None,
        set_extension_status=lambda _key, _text: None,
        get_footer_data_provider=lambda: ports.footer_data_provider,
        compact=ports.compact,
        get_system_prompt=lambda: agent.system_prompt,
        wait_for_idle=session_runtime.wait_for_idle,
        reload=lambda: ports.bridge.bind(reason="reload"),
        navigate_tree=partial(
            _navigate_tree,
            ports.navigation_runtime,
            summary_executor=ports.execute_branch_summary,
        ),
        fork=_unsupported_fork,
        new_session=_unsupported_new,
        switch_session=_unsupported_switch,
        get_ui_context=lambda: None,
        exec_command=None,
    )


def _register_extension_tool(
    controller: SessionToolController,
    tool: object,
    source_info: object | None,
) -> None:
    controller.register_runtime_tool(tool, source_info=source_info)


async def _append_extension_entry(
    session: ProductTranscriptSession[Any, Any],
    custom_type: str,
    data: object | None,
) -> None:
    await session.append_custom_entry(custom_type, data)


async def _set_extension_label(
    session: ProductTranscriptSession[Any, Any],
    target_id: str,
    label: str | None,
) -> None:
    await session.append_label(target_id, label)


async def _set_active_tools(
    controller: SessionToolController,
    names: list[str],
    refresh: Callable[[], None],
) -> None:
    controller.apply_active_tools(names)
    refresh()


def _abort_session(session_runtime: SessionRuntime) -> None:
    session_runtime.abort()


async def _navigate_tree(
    navigation_runtime: AgentTranscriptNavigationRuntime,
    target: str,
    options: object | None,
    summary_executor: BranchSummaryExecutor,
) -> dict[str, object]:
    opts = options if isinstance(options, Mapping) else {}
    plan = navigation_runtime.prepare(target)
    if plan is None:
        return {"cancelled": False}
    result = await navigation_runtime.navigate(
        plan,
        summarize=bool(opts.get("summarize", False)),
        label=opts.get("label") if isinstance(opts.get("label"), str) else None,
        summary_runner=(summary_executor if opts.get("summarize", False) else None),
    )
    return {"cancelled": result.cancelled}


async def _unsupported_replacement(
    operation: str,
    value: object | None,
    options: object | None,
) -> dict[str, object]:
    raise RuntimeError(f"Session replacement operation is not bound: {operation}")


async def _unsupported_fork(
    entry: str,
    options: object | None,
) -> dict[str, object]:
    return await _unsupported_replacement("fork", entry, options)


async def _unsupported_new(options: object | None) -> dict[str, object]:
    return await _unsupported_replacement("new", None, options)


async def _unsupported_switch(
    path: str,
    options: object | None,
) -> dict[str, object]:
    return await _unsupported_replacement("switch", path, options)


__all__ = [
    "AgentSessionExtensionComposition",
    "AgentSessionExtensionCompositionPorts",
    "ExtensionCompositionAgentPort",
    "SessionExtensionAssemblyPort",
    "compose_agent_session_extensions",
]
