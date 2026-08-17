"""Product-neutral assembly of the standard Agent session runtimes.

The composition function deliberately accepts callbacks instead of importing a
Product session.  A Product therefore supplies policy and content while the
Harness owns construction and lifetime of transcript, queue, retry,
compaction, tools, resources, extensions, and command runtimes.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from loushang.agent import Agent, PrepareModelCallFn
from loushang.ai.api_registry import APIRegistry
from loushang.ai.model import Model, ModelSelection
from loushang.ai.prepared_request import PreparedRequestLimits
from loushang.ai.types import AssistantMessage
from loushang.ai.utils import is_context_overflow
from loushang.ai.utils.capabilities import validate_image_input_compatibility
from loushang.harness.approval import ApprovalResolver
from loushang.harness.capabilities import CapabilityCompositionRuntime
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.events import (
    ConversationMetadataChanged,
)
from loushang.harness.extensions import ExtensionProviderRuntime
from loushang.harness.extensions.agent import (
    ExtensionAgentEventRuntime,
    ExtensionInputRuntime,
)
from loushang.harness.extensions.agent.hooks import ExtensionAgentHookPort
from loushang.harness.extensions.agent.input_adapter import ExtensionInputAdapter
from loushang.harness.extensions.agent.lifecycle import ExtensionEventPort
from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.extensions.context import (
    SessionActionDecision,
    SessionBeforeCompactResult,
    SessionBeforeForkResult,
    SessionBeforeTreeResult,
    SessionStartEvent,
)
from loushang.harness.extensions.runtime_bindings import (
    ExtensionRuntimeBindingFactory,
    ExtensionRuntimeBindings,
)
from loushang.harness.extensions.session_runtime import SessionExtensionRuntimePort
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resources.packages.session import SessionPackageController
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.resources.watcher import ResourceChangeWatcher
from loushang.harness.runtime import CancellationSignal
from loushang.harness.runtime.retry import RetryPolicy
from loushang.harness.session.bash import (
    BashCommandHook,
    BashExecutionPorts,
    BashExecutionRuntime,
)
from loushang.harness.session.bindings import (
    SessionExtensionBinding,
    SessionIdentityBinding,
    SessionMaintenanceBinding,
    SessionModelBinding,
)
from loushang.harness.session.command_controller import SessionCommandController
from loushang.harness.session.command_sources import ExtensionCommandProvider
from loushang.harness.session.diagnostics import (
    ExtensionDiagnosticsPort,
    SessionDiagnosticScope,
    SessionDiagnosticsRuntime,
)
from loushang.harness.session.extension_bridge import AgentSessionExtensionBridge
from loushang.harness.session.extension_composition import (
    AgentSessionExtensionComposition,
    AgentSessionExtensionCompositionPorts,
    compose_agent_session_extensions,
)
from loushang.harness.session.inspection import AgentSessionInspector
from loushang.harness.session.resource_refresh import (
    ResourceLoaderPort,
    ResourceSettingsPort,
    SessionResourceRefreshRuntime,
)
from loushang.harness.session.runtime import (
    AfterTurnPolicyPort,
    SessionRuntime,
    TranscriptRuntimePort,
    TurnPolicyPort,
)
from loushang.harness.session.settings import SessionSettingsBinding
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace import ExecServiceBashOperations
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    TURN_AWARE_SUMMARY_VERSION,
    AgentTranscriptCompactionCapability,
    AgentTranscriptCompactionRuntime,
    AgentTranscriptContext,
    AgentTranscriptNavigationRuntime,
    AgentTranscriptRetryRuntime,
    AgentTranscriptSelectionRuntime,
    AutoCompactionOutcome,
    BranchSummaryOutput,
    CompactionHookDecision,
    CompactionHookRequest,
    CompactionPreparation,
    CompactionResult,
    ModelSelectionCatalog,
    ProductTranscriptSession,
    TranscriptCompactionPolicy,
)
from loushang.harness.workspace.exec import ExecService

if TYPE_CHECKING:
    from loushang.harness.session.tool_controller import SessionToolController

AsyncEvent = Callable[[object], Awaitable[None]]
EventDispatcher = Callable[..., Awaitable[None]]
BranchSummaryExecutor = Callable[..., Awaitable[BranchSummaryOutput]]


class ProductCompactionExecutor(Protocol):
    """Live Product binding for the standard Harness compaction mechanism."""

    async def __call__(
        self,
        *,
        preparation: CompactionPreparation,
        model: object,
        headers: Mapping[str, str] | None,
        signal: object | None,
        custom_instructions: str | None = None,
        prepare_model_call: PrepareModelCallFn | None = None,
        request_limits: PreparedRequestLimits | None = None,
    ) -> CompactionResult: ...


class ModelDetailRegistryPort(Protocol):
    """Read-only model details needed by Product session presentation."""

    def list_models(self) -> Sequence[object]: ...


class SessionModelCatalogPort(ModelSelectionCatalog, Protocol):
    """Model selection plus detail projection used during session composition."""

    @property
    def ai_registry(self) -> ModelDetailRegistryPort: ...


class SessionExtensionCompositionPort(
    ExtensionDiagnosticsPort,
    ExtensionEventPort,
    ExtensionAgentHookPort,
    ExtensionCommandProvider,
    SessionExtensionRuntimePort[ExtensionRuntimeBindings],
    Protocol,
):
    """Extension operations consumed while composing one Agent session."""

    def list_extensions(self) -> list[dict[str, object]]: ...

    def has_handlers(self, hook_name: str) -> bool: ...

    async def emit_user_bash(
        self,
        event: object,
        *,
        cwd: str = "",
    ) -> object | None: ...

    async def emit_session_shutdown(self, event: object) -> None: ...

    async def before_session_compact(
        self,
        event: object,
    ) -> SessionBeforeCompactResult | None: ...

    async def before_session_fork(
        self,
        event: object,
    ) -> SessionBeforeForkResult | None: ...

    async def before_session_switch(
        self,
        event: object,
    ) -> SessionActionDecision | None: ...

    async def before_session_tree(
        self,
        event: object,
    ) -> SessionBeforeTreeResult | None: ...


@dataclass(frozen=True)
class SessionFoundationInputs:
    """Inputs for diagnostics, tools, resources, navigation, and bash."""

    resource_loader: ResourceLoaderPort | None
    get_resource_bundle: Callable[[], ResourceBundle | None]
    tool_registry: WorkspaceToolRegistry | None
    allowed_tool_names: list[str] | None
    active_tool_names: list[str] | None
    default_activate_new_tools: bool | None
    show_empty_tool_prompt: bool
    base_prompt: str
    diagnostics_service: DiagnosticsService | None
    tool_exec_service: ExecService | None
    approval_resolver: ApprovalResolver | None
    tool_policy_evaluator: PolicyEvaluator | None
    apply_context: Callable[[AgentTranscriptContext], None]
    refresh_agent_messages: Callable[[], None]
    dispatch_event: EventDispatcher
    record_runtime_exception: Callable[..., None]
    before_bash: BashCommandHook | None
    get_bash_definition: Callable[[], ToolDefinition | None]
    create_bash_call_id: Callable[[], str]
    get_resource_watch_paths: Callable[[], list[Path]]
    prepare_resource_refresh: Callable[[], None]
    rebuild_prompt_and_tools_view: Callable[[], None]
    set_resource_bundle: Callable[[ResourceBundle | None], None]
    record_extension_runtime_diagnostic: Callable[[DiagnosticDraft], None]


@dataclass(frozen=True)
class SessionMaintenanceInputs:
    """Product policy injected into shared compaction and retry mechanisms."""

    execute_compaction: ProductCompactionExecutor
    before_compaction: Callable[
        [CompactionHookRequest], Awaitable[CompactionHookDecision | None]
    ]
    after_compaction: Callable[[CompactionResult, str, bool], Awaitable[None]]
    sleep_for_retry: Callable[[int, CancellationSignal], Awaitable[None]]


@dataclass(frozen=True)
class SessionProductInputs:
    """Product-facing model, command, extension, and presentation bindings."""

    model_registry: SessionModelCatalogPort | None
    api_registry: APIRegistry
    extension_runner: SessionExtensionCompositionPort | None
    session_start_event: SessionStartEvent
    footer_data_provider: object
    command_controller: Callable[
        [SessionDiagnosticsRuntime], SessionCommandController[Any]
    ]
    extension_provider_controller: ExtensionProviderRuntime | None
    extension_replacement_controller: ExtensionReplacementRuntime | None
    extension_runtime_binding_factory: ExtensionRuntimeBindingFactory | None
    extension_bridge: AgentSessionExtensionBridge
    get_context_usage: Callable[[], object | None]
    package_controller: SessionPackageController | None
    execute_branch_summary: BranchSummaryExecutor
    before_agent_start_system_prompt_options: Callable[[], dict[str, object]]


@dataclass(frozen=True, init=False)
class SessionCompositionPorts:
    """Cohesive inputs needed to assemble a standard Product session.

    The three input groups follow the assembly phases.  They contain ports and
    callbacks rather than Product types, so Research, Design, Coding, or an OEM
    Product can supply them without depending on another Product package.
    """

    agent: Agent
    session_manager: ProductTranscriptSession[Any, Any]
    settings: SessionSettingsBinding
    capability_runtime: CapabilityCompositionRuntime
    foundation: SessionFoundationInputs
    maintenance: SessionMaintenanceInputs
    product: SessionProductInputs

    def __init__(
        self,
        agent: Agent,
        session_manager: ProductTranscriptSession[Any, Any],
        settings: SessionSettingsBinding,
        *,
        capability_runtime: CapabilityCompositionRuntime,
        foundation: SessionFoundationInputs | None = None,
        maintenance: SessionMaintenanceInputs | None = None,
        product: SessionProductInputs | None = None,
        **legacy: Any,
    ) -> None:
        """Accept phase inputs or the former flat keyword contract.

        Product adapters in this repository use the phase-oriented form.  The
        keyword adapter preserves source compatibility for external Products
        while they migrate without keeping the flat shape inside the object.
        """

        groups = (foundation, maintenance, product)
        if all(group is not None for group in groups):
            if legacy:
                unexpected = ", ".join(sorted(legacy))
                raise TypeError(
                    "phase-oriented SessionCompositionPorts received legacy "
                    f"arguments: {unexpected}"
                )
            resolved_foundation = cast(SessionFoundationInputs, foundation)
            resolved_maintenance = cast(SessionMaintenanceInputs, maintenance)
            resolved_product = cast(SessionProductInputs, product)
        elif any(group is not None for group in groups):
            raise TypeError(
                "foundation, maintenance, and product must be supplied together"
            )
        else:
            resolved_foundation, resolved_maintenance, resolved_product = (
                _legacy_composition_inputs(legacy)
            )

        object.__setattr__(self, "agent", agent)
        object.__setattr__(self, "session_manager", session_manager)
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "capability_runtime", capability_runtime)
        object.__setattr__(self, "foundation", resolved_foundation)
        object.__setattr__(self, "maintenance", resolved_maintenance)
        object.__setattr__(self, "product", resolved_product)


def _legacy_composition_inputs(
    values: dict[str, Any],
) -> tuple[SessionFoundationInputs, SessionMaintenanceInputs, SessionProductInputs]:
    """Translate the former flat keyword record into phase inputs."""

    remaining = dict(values)

    def take(name: str) -> Any:
        try:
            return remaining.pop(name)
        except KeyError as exc:
            raise TypeError(
                f"legacy SessionCompositionPorts is missing {name!r}"
            ) from exc

    foundation = SessionFoundationInputs(
        resource_loader=take("resource_loader"),
        get_resource_bundle=take("get_resource_bundle"),
        tool_registry=take("tool_registry"),
        allowed_tool_names=take("allowed_tool_names"),
        active_tool_names=take("active_tool_names"),
        default_activate_new_tools=take("default_activate_new_tools"),
        show_empty_tool_prompt=take("show_empty_tool_prompt"),
        base_prompt=take("base_prompt"),
        diagnostics_service=take("diagnostics_service"),
        tool_exec_service=take("tool_exec_service"),
        approval_resolver=take("approval_resolver"),
        tool_policy_evaluator=take("tool_policy_evaluator"),
        apply_context=take("apply_context"),
        refresh_agent_messages=take("refresh_agent_messages"),
        dispatch_event=take("dispatch_event"),
        record_runtime_exception=take("record_runtime_exception"),
        before_bash=take("before_bash"),
        get_bash_definition=take("get_bash_definition"),
        create_bash_call_id=take("create_bash_call_id"),
        get_resource_watch_paths=take("get_resource_watch_paths"),
        prepare_resource_refresh=take("prepare_resource_refresh"),
        rebuild_prompt_and_tools_view=take("rebuild_prompt_and_tools_view"),
        set_resource_bundle=take("set_resource_bundle"),
        record_extension_runtime_diagnostic=take("record_extension_runtime_diagnostic"),
    )
    maintenance = SessionMaintenanceInputs(
        execute_compaction=take("execute_compaction"),
        before_compaction=take("before_compaction"),
        after_compaction=take("after_compaction"),
        sleep_for_retry=take("sleep_for_retry"),
    )
    product = SessionProductInputs(
        model_registry=take("model_registry"),
        api_registry=take("api_registry"),
        extension_runner=take("extension_runner"),
        session_start_event=take("session_start_event"),
        footer_data_provider=take("footer_data_provider"),
        command_controller=take("command_controller"),
        extension_provider_controller=take("extension_provider_controller"),
        extension_replacement_controller=take("extension_replacement_controller"),
        extension_runtime_binding_factory=take("extension_runtime_binding_factory"),
        extension_bridge=take("extension_bridge"),
        get_context_usage=take("get_context_usage"),
        package_controller=take("package_controller"),
        execute_branch_summary=take("execute_branch_summary"),
        before_agent_start_system_prompt_options=take(
            "before_agent_start_system_prompt_options"
        ),
    )
    if remaining:
        unexpected = ", ".join(sorted(remaining))
        raise TypeError(
            f"legacy SessionCompositionPorts received unexpected arguments: {unexpected}"
        )
    return foundation, maintenance, product


@dataclass(frozen=True)
class SessionComposition:
    """Phase-oriented assembly result for one Product session.

    Compatibility properties keep the established flat read API while the
    stored shape exposes the actual lifetime and ownership groups.
    """

    capability_runtime: CapabilityCompositionRuntime
    foundation: _FoundationRuntimes
    maintenance: _MaintenanceRuntimes
    product: _ProductBindings
    package_controller: SessionPackageController | None
    command_controller: SessionCommandController[Any]
    extension_event_sink: ExtensionAgentEventRuntime
    session_runtime: SessionRuntime
    extension_bridge: AgentSessionExtensionBridge

    @property
    def diagnostics_bridge(self) -> SessionDiagnosticsRuntime:
        return self.foundation.diagnostics_bridge

    @property
    def tool_controller(self) -> SessionToolController:
        return self.foundation.tool_controller

    @property
    def resource_refresh_runtime(self) -> SessionResourceRefreshRuntime:
        return self.foundation.resource_refresh_runtime

    @property
    def resource_watch_controller(self) -> ResourceChangeWatcher:
        return self.foundation.resource_watch_controller

    @property
    def navigation_runtime(self) -> AgentTranscriptNavigationRuntime:
        return self.foundation.navigation_runtime

    @property
    def bash_runtime(self) -> BashExecutionRuntime:
        return self.foundation.bash_runtime

    @property
    def compaction_capability(self) -> AgentTranscriptCompactionCapability:
        return self.maintenance.compaction_capability

    @property
    def compaction_runtime(self) -> AgentTranscriptCompactionRuntime:
        return self.maintenance.compaction_runtime

    @property
    def retry_runtime(self) -> AgentTranscriptRetryRuntime:
        return self.maintenance.retry_runtime

    @property
    def extension_input_runtime(self) -> ExtensionInputRuntime:
        return self.product.extension_composition.input_runtime

    @property
    def extension_message_controller(self) -> ExtensionInputAdapter:
        return self.product.extension_composition.message_controller

    @property
    def extension_provider_controller(self) -> ExtensionProviderRuntime:
        return self.product.extension_composition.provider_controller

    @property
    def extension_replacement_controller(self) -> ExtensionReplacementRuntime:
        return self.product.extension_composition.replacement_controller

    @property
    def extension_runtime_binding_factory(self) -> ExtensionRuntimeBindingFactory:
        return self.product.extension_composition.runtime_binding_factory

    @property
    def selection_runtime(self) -> AgentTranscriptSelectionRuntime:
        return self.product.selection_runtime

    @property
    def model_binding(self) -> SessionModelBinding:
        return self.product.model_binding

    @property
    def identity_binding(self) -> SessionIdentityBinding:
        return self.product.identity_binding

    @property
    def maintenance_binding(self) -> SessionMaintenanceBinding:
        return self.product.maintenance_binding

    @property
    def extension_binding(self) -> SessionExtensionBinding:
        return self.product.extension_composition.binding

    @property
    def session_inspector(self) -> AgentSessionInspector:
        return self.product.session_inspector


@dataclass(frozen=True)
class _FoundationRuntimes:
    diagnostics_bridge: SessionDiagnosticsRuntime
    tool_controller: SessionToolController
    resource_refresh_runtime: SessionResourceRefreshRuntime
    resource_watch_controller: ResourceChangeWatcher
    navigation_runtime: AgentTranscriptNavigationRuntime
    bash_runtime: BashExecutionRuntime


@dataclass(frozen=True)
class _MaintenanceRuntimes:
    compaction_capability: AgentTranscriptCompactionCapability
    compaction_runtime: AgentTranscriptCompactionRuntime
    retry_runtime: AgentTranscriptRetryRuntime


@dataclass(frozen=True)
class _ProductBindings:
    selection_runtime: AgentTranscriptSelectionRuntime
    model_binding: SessionModelBinding
    identity_binding: SessionIdentityBinding
    maintenance_binding: SessionMaintenanceBinding
    extension_composition: AgentSessionExtensionComposition
    session_inspector: AgentSessionInspector


def compose_session_runtime(ports: SessionCompositionPorts) -> SessionComposition:
    """Build the standard Agent session runtime from Product ports."""

    agent = ports.agent
    session = ports.session_manager
    foundation = _build_foundation_runtimes(ports)
    maintenance = _build_maintenance_runtimes(ports)
    command_controller = ports.product.command_controller(foundation.diagnostics_bridge)
    extension_event_sink = ExtensionAgentEventRuntime(
        get_extension_runtime=lambda: ports.product.extension_runner,
        get_cwd=session.get_cwd,
    )

    async def check_auto_compaction(
        message: AssistantMessage,
    ) -> AutoCompactionOutcome:
        return await maintenance.compaction_runtime.maybe_compact_after_turn(
            message,
            is_context_overflow_fn=is_context_overflow,
        )

    async def compact_before_prompt() -> AutoCompactionOutcome:
        message = _last_assistant_message(agent.state.messages)
        if message is None:
            return AutoCompactionOutcome()
        return await check_auto_compaction(message)

    session_runtime = SessionRuntime(
        agent=agent,
        transcript=TranscriptRuntimePort(
            session_id=session.get_header().conversation_id,
            append_message=session.append_message,
            commit_application_message=session.commit_application_message,
            refresh_context=lambda: ports.foundation.apply_context(
                session.build_session_context()
            ),
            set_commit_observer=session.set_commit_observer,
        ),
        turn_policy=TurnPolicyPort(
            get_extension_runner=lambda: ports.product.extension_runner,
            get_cwd=session.get_cwd,
            extract_extension_command_invocation=(
                command_controller.extract_extension_command_invocation
            ),
            execute_command_async=command_controller.execute_command_async,
            preflight_user_input=command_controller.preflight_user_input,
            reject_queued_extension_command=(
                command_controller.raise_if_queued_extension_command
            ),
            preflight_user_input_async=command_controller.preflight_user_input_async,
            before_agent_start_system_prompt_options=(
                ports.product.before_agent_start_system_prompt_options
            ),
            sync_extension_diagnostics=(
                foundation.diagnostics_bridge.sync_extension_diagnostics
            ),
            compact_before_prompt_async=compact_before_prompt,
        ),
        after_turn_policy=AfterTurnPolicyPort(
            emit_extension_agent_event=extension_event_sink.emit_agent_event,
            record_tool_execution_error=(
                foundation.diagnostics_bridge.record_tool_execution_error
            ),
            retry_controller=maintenance.retry_runtime,
            compaction_controller=maintenance.compaction_runtime,
            sync_extension_diagnostics=(
                foundation.diagnostics_bridge.sync_extension_diagnostics
            ),
            record_assistant_response_error=(
                foundation.diagnostics_bridge.record_assistant_response_error
            ),
            check_auto_compaction=check_auto_compaction,
        ),
    )
    bindings = _build_product_bindings(
        ports,
        foundation=foundation,
        maintenance=maintenance,
        command_controller=command_controller,
        session_runtime=session_runtime,
    )
    return SessionComposition(
        capability_runtime=ports.capability_runtime,
        foundation=foundation,
        maintenance=maintenance,
        product=bindings,
        package_controller=ports.product.package_controller,
        command_controller=command_controller,
        extension_event_sink=extension_event_sink,
        session_runtime=session_runtime,
        extension_bridge=ports.product.extension_bridge,
    )


def _build_foundation_runtimes(
    ports: SessionCompositionPorts,
) -> _FoundationRuntimes:
    session = ports.session_manager
    inputs = ports.foundation
    product = ports.product
    diagnostics_bridge = SessionDiagnosticsRuntime(
        diagnostics_service=inputs.diagnostics_service,
        get_scope=lambda: SessionDiagnosticScope(
            session_id=session.get_header().conversation_id,
            entry_id=session.get_leaf_id(),
        ),
        get_extension_diagnostics=lambda: product.extension_runner,
        recorded_extension_diagnostics=(
            len(product.extension_runner.get_diagnostics())
            if product.extension_runner is not None
            else 0
        ),
    )
    tool_controller = _build_tool_controller(ports, diagnostics_bridge)
    resource_refresh_runtime = SessionResourceRefreshRuntime(
        get_resource_loader=lambda: inputs.resource_loader,
        get_resource_bundle=inputs.get_resource_bundle,
        get_cwd=session.get_cwd,
        get_extension_runtime=lambda: product.extension_runner,
        get_settings=lambda: cast(
            ResourceSettingsPort | None,
            ports.settings.get_settings_manager(),
        ),
        set_resource_bundle=inputs.set_resource_bundle,
        rebuild_prompt_and_tools_view=inputs.rebuild_prompt_and_tools_view,
        record_refresh_failure=lambda error: inputs.record_extension_runtime_diagnostic(
            DiagnosticDraft(
                code="extension_resource_refresh_failed",
                message=f"Extension resource refresh failed: {error}",
            )
        ),
        sync_extension_diagnostics=lambda: (
            diagnostics_bridge.sync_extension_diagnostics(phase="resource_loading")
        ),
        prepare_resource_refresh=inputs.prepare_resource_refresh,
        skill_activation_runtime=ports.capability_runtime.skill_activation,
    )
    resource_watch_controller = ResourceChangeWatcher(
        get_paths=inputs.get_resource_watch_paths,
        on_change=lambda: _reload_resources_from_watch(
            resource_refresh_runtime,
            product.extension_runner,
            lambda: product.extension_bridge.bind(reason="reload"),
        ),
    )
    navigation_runtime = AgentTranscriptNavigationRuntime(
        session=session,
        apply_context=lambda: inputs.apply_context(session.build_session_context()),
        dispatch_event=inputs.dispatch_event,
        on_failure=lambda error: inputs.record_runtime_exception(
            code="branch_summary_failed", exc=error
        ),
    )
    bash_runtime = BashExecutionRuntime(
        BashExecutionPorts(
            get_cwd=session.get_cwd,
            get_definition=inputs.get_bash_definition,
            execute_definition=tool_controller.execute_tool_definition,
            create_call_id=inputs.create_bash_call_id,
            append_record=session.append_message,
            refresh_context=inputs.refresh_agent_messages,
            before_execute=inputs.before_bash,
            operations=(
                ExecServiceBashOperations(inputs.tool_exec_service)
                if inputs.tool_exec_service is not None
                else None
            ),
        )
    )
    return _FoundationRuntimes(
        diagnostics_bridge=diagnostics_bridge,
        tool_controller=tool_controller,
        resource_refresh_runtime=resource_refresh_runtime,
        resource_watch_controller=resource_watch_controller,
        navigation_runtime=navigation_runtime,
        bash_runtime=bash_runtime,
    )


def _build_maintenance_runtimes(
    ports: SessionCompositionPorts,
) -> _MaintenanceRuntimes:
    agent = ports.agent
    session = ports.session_manager
    foundation = ports.foundation
    maintenance = ports.maintenance
    compaction_capability = _resolve_compaction_capability(session)

    def get_compaction_policy() -> TranscriptCompactionPolicy:
        return _current_compaction_policy(ports, compaction_capability)

    compaction_runtime = AgentTranscriptCompactionRuntime(
        transcript=session,
        get_policy=get_compaction_policy,
        get_model=lambda: agent.model,
        get_context_messages=lambda: list(session.build_session_context().messages),
        refresh_context=foundation.refresh_agent_messages,
        prepare_compaction=compaction_capability.prepare,
        execute_compaction=lambda preparation, custom_instructions: _execute_compaction(
            maintenance.execute_compaction,
            agent,
            preparation,
            custom_instructions,
        ),
        dispatch_event=foundation.dispatch_event,
        has_queued_messages=agent.has_queued_messages,
        before_compaction=maintenance.before_compaction,
        after_compaction=maintenance.after_compaction,
        record_runtime_exception=foundation.record_runtime_exception,
        product_id=ports.capability_runtime.profile.product_id,
        session_id=session.get_header().conversation_id,
    )
    retry_runtime = AgentTranscriptRetryRuntime(
        get_policy=lambda: _retry_policy(ports.settings.get_retry_settings()),
        get_messages=lambda: list(agent.state.messages),
        set_messages=agent.state.set_messages,
        get_context_window=lambda: agent.model.context_window,
        dispatch_event=foundation.dispatch_event,
        record_runtime_exception=foundation.record_runtime_exception,
        sleep_for_retry=maintenance.sleep_for_retry,
        is_context_overflow_fn=is_context_overflow,
    )
    return _MaintenanceRuntimes(
        compaction_capability=compaction_capability,
        compaction_runtime=compaction_runtime,
        retry_runtime=retry_runtime,
    )


def _build_product_bindings(
    ports: SessionCompositionPorts,
    *,
    foundation: _FoundationRuntimes,
    maintenance: _MaintenanceRuntimes,
    command_controller: SessionCommandController[Any],
    session_runtime: SessionRuntime,
) -> _ProductBindings:
    agent = ports.agent
    session = ports.session_manager
    foundation_inputs = ports.foundation
    product = ports.product
    selection_runtime = AgentTranscriptSelectionRuntime(
        session=session,
        get_model=lambda: agent.model,
        set_model=lambda model: setattr(agent, "model", model),
        get_thinking_level=lambda: agent.thinking_level,
        set_thinking_level_value=lambda level: setattr(agent, "thinking_level", level),
        get_model_catalog=lambda: product.model_registry,
    )

    async def refresh_extension_runtime(reason: str) -> None:
        await product.extension_bridge.refresh(reason=reason)

    async def apply_model_selection(
        selection: object,
        *,
        source: str = "set",
    ) -> None:
        await apply_agent_session_model_selection(
            selection_runtime,
            selection,
            agent,
            session_runtime,
            product.extension_runner,
            refresh_extension_runtime,
            session.get_cwd,
            source=source,
        )

    extension_composition = compose_agent_session_extensions(
        AgentSessionExtensionCompositionPorts(
            agent=agent,
            session=session,
            model_registry=product.model_registry,
            api_registry=product.api_registry,
            extension_runner=product.extension_runner,
            provider_controller=product.extension_provider_controller,
            replacement_controller=product.extension_replacement_controller,
            runtime_binding_factory=product.extension_runtime_binding_factory,
            bridge=product.extension_bridge,
            session_start_event=product.session_start_event,
            tool_controller=foundation.tool_controller,
            command_controller=command_controller,
            selection_runtime=selection_runtime,
            session_runtime=session_runtime,
            navigation_runtime=foundation.navigation_runtime,
            resource_refresh_runtime=foundation.resource_refresh_runtime,
            resource_watch_controller=foundation.resource_watch_controller,
            footer_data_provider=product.footer_data_provider,
            get_context_usage=product.get_context_usage,
            set_model=apply_model_selection,
            set_session_name=lambda name: _set_session_name(
                session,
                foundation_inputs.dispatch_event,
                name,
            ),
            compact=partial(
                _compact_manual,
                session_runtime,
                maintenance.compaction_runtime,
            ),
            execute_branch_summary=product.execute_branch_summary,
            record_runtime_diagnostic=(
                foundation_inputs.record_extension_runtime_diagnostic
            ),
            sync_extension_diagnostics=(
                foundation.diagnostics_bridge.sync_extension_diagnostics
            ),
        )
    )

    def get_compaction_policy() -> TranscriptCompactionPolicy:
        return _current_compaction_policy(ports, maintenance.compaction_capability)

    model_binding = SessionModelBinding(
        get_model_selection_callback=selection_runtime.get_model_selection,
        set_model_callback=apply_model_selection,
        cycle_model_selection_callback=selection_runtime.cycle_model_selection,
        apply_cycled_model_callback=lambda selection: apply_model_selection(
            selection,
            source="cycle",
        ),
        cycle_scoped_selection_callback=selection_runtime.cycle_scoped_selection,
        set_thinking_level_callback=selection_runtime.set_thinking_level,
        cycle_thinking_level_callback=selection_runtime.cycle_thinking_level,
        supports_thinking_callback=selection_runtime.supports_thinking,
        available_thinking_levels_callback=selection_runtime.get_available_thinking_levels,
        available_models_callback=selection_runtime.get_available_models,
        available_model_details_callback=lambda: (
            list(product.model_registry.ai_registry.list_models())
            if product.model_registry is not None
            else []
        ),
        get_scoped_models_callback=selection_runtime.get_scoped_models,
        set_scoped_models_callback=selection_runtime.set_scoped_models,
    )
    identity_binding = SessionIdentityBinding(
        get_session_id=lambda: session.get_session_record().session_id,
        get_session_name=lambda: session.get_session_record().metadata.name,
        set_session_name_callback=lambda name: _set_session_name(
            session, foundation_inputs.dispatch_event, name
        ),
    )
    maintenance_binding = SessionMaintenanceBinding(
        is_compacting_callback=lambda: (
            maintenance.compaction_runtime.is_compacting
            or foundation.navigation_runtime.is_summarizing
        ),
        auto_retry_enabled_callback=lambda: ports.settings.auto_retry_enabled,
        auto_compaction_enabled_callback=lambda: get_compaction_policy().enabled,
        set_auto_retry_enabled_callback=ports.settings.set_auto_retry_enabled,
        set_auto_compaction_enabled_callback=(
            ports.settings.set_auto_compaction_enabled
        ),
        compact_callback=partial(
            _compact_manual,
            session_runtime,
            maintenance.compaction_runtime,
        ),
        abort_compaction_callback=maintenance.compaction_runtime.abort,
    )
    session_inspector = AgentSessionInspector(
        agent=agent,
        session=session,
        get_session_id=lambda: session.get_session_record().session_id,
        get_session_name=lambda: session.get_session_record().metadata.name,
        get_active_tool_names=foundation.tool_controller.get_active_tool_names,
        is_retrying=lambda: maintenance.retry_runtime.is_retrying,
        is_compacting=lambda: (
            maintenance.compaction_runtime.is_compacting
            or foundation.navigation_runtime.is_summarizing
        ),
        get_last_diagnostics=foundation.diagnostics_bridge.get_last_diagnostics,
        get_model_selection=selection_runtime.get_model_selection,
        is_host_running=lambda: session_runtime.is_active,
        get_compaction_reserve_tokens=lambda: get_compaction_policy().reserve_tokens,
        get_compaction_compact_percent=lambda: get_compaction_policy().compact_percent,
        get_compaction_keep_recent_tokens=lambda: (
            get_compaction_policy().keep_recent_tokens
        ),
    )
    return _ProductBindings(
        selection_runtime=selection_runtime,
        model_binding=model_binding,
        identity_binding=identity_binding,
        maintenance_binding=maintenance_binding,
        extension_composition=extension_composition,
        session_inspector=session_inspector,
    )


def _build_tool_controller(
    ports: SessionCompositionPorts,
    diagnostics: SessionDiagnosticsRuntime,
) -> SessionToolController:
    from loushang.harness.session.tool_controller import ToolController

    inputs = ports.foundation
    return ToolController(
        agent=ports.agent,
        get_cwd=ports.session_manager.get_cwd,
        tool_registry=inputs.tool_registry,
        allowed_tool_names=(
            set(inputs.allowed_tool_names)
            if inputs.allowed_tool_names is not None
            else None
        ),
        initial_active_tool_names=list(
            inputs.active_tool_names or [tool.name for tool in ports.agent.tools]
        ),
        default_activate_new_tools=(
            inputs.active_tool_names is None
            if inputs.default_activate_new_tools is None
            else inputs.default_activate_new_tools
        ),
        show_empty_tool_prompt=inputs.show_empty_tool_prompt,
        base_prompt=inputs.base_prompt,
        get_resource_bundle=inputs.get_resource_bundle,
        get_diagnostics_service=lambda: inputs.diagnostics_service,
        get_exec_service=(
            (lambda: inputs.tool_exec_service)
            if inputs.tool_exec_service is not None
            else None
        ),
        get_approval_resolver=lambda: inputs.approval_resolver,
        policy_evaluator=inputs.tool_policy_evaluator,
        emit_tool_audit_event=inputs.dispatch_event,
        resource_activation_runtime=ports.capability_runtime.resource_runtime,
        prompt_section_composer=ports.capability_runtime.prompt_section_composer,
    )


def _resolve_compaction_capability(
    session: ProductTranscriptSession[Any, Any],
) -> AgentTranscriptCompactionCapability:
    capability = getattr(session, "get_runtime_capability", None)
    if callable(capability):
        value = capability("context.compaction")
        if isinstance(value, AgentTranscriptCompactionCapability):
            return value
    from loushang.harness.transcript import (
        create_agent_transcript_compaction_capability,
    )

    return create_agent_transcript_compaction_capability(
        implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
        implementation_version=TURN_AWARE_SUMMARY_VERSION,
        config={
            "enabled": True,
            "compactPercent": 80.0,
            "reserveTokens": 8_192,
            "keepRecentTokens": 32_768,
        },
    )


def _retry_policy(settings: object) -> RetryPolicy:
    return RetryPolicy(
        enabled=bool(getattr(settings, "enabled", False)),
        max_attempts=int(getattr(settings, "max_retries", 0)),
        base_delay_ms=int(getattr(settings, "base_delay_ms", 0)),
    )


def _current_compaction_policy(
    ports: SessionCompositionPorts,
    capability: AgentTranscriptCompactionCapability,
) -> TranscriptCompactionPolicy:
    return _compaction_policy(
        ports.settings.get_compaction_policy_override(),
        capability.policy,
    )


def _compaction_policy(
    settings: object | None,
    capability: TranscriptCompactionPolicy,
) -> TranscriptCompactionPolicy:
    if settings is None:
        return capability
    return TranscriptCompactionPolicy(
        enabled=_bool_setting(
            settings,
            "enabled",
            capability.enabled,
        ),
        reserve_tokens=_int_setting(
            settings,
            "reserve_tokens",
            capability.reserve_tokens,
        ),
        compact_percent=_float_setting(
            settings,
            "compact_percent",
            capability.compact_percent,
        ),
        keep_recent_tokens=_optional_int_setting(
            settings,
            "keep_recent_tokens",
            capability.keep_recent_tokens,
        ),
    )


def _int_setting(settings: object, name: str, fallback: int) -> int:
    value = getattr(settings, name, fallback)
    return fallback if value is None else int(value)


def _bool_setting(settings: object, name: str, fallback: bool) -> bool:
    value = getattr(settings, name, fallback)
    return fallback if value is None else bool(value)


def _float_setting(settings: object, name: str, fallback: float) -> float:
    value = getattr(settings, name, fallback)
    return fallback if value is None else float(value)


def _optional_int_setting(
    settings: object,
    name: str,
    fallback: int | None,
) -> int | None:
    value = getattr(settings, name, fallback)
    return fallback if value is None else int(value)


async def sleep_for_retry(delay_ms: int, signal: CancellationSignal) -> None:
    """Sleep in abort-aware intervals for the standard Agent retry runtime."""

    remaining = max(delay_ms, 0) / 1000
    while remaining > 0:
        if getattr(signal, "aborted", False):
            raise asyncio.CancelledError
        interval = min(0.05, remaining)
        await asyncio.sleep(interval)
        remaining -= interval
    if getattr(signal, "aborted", False):
        raise asyncio.CancelledError


async def _execute_compaction(
    executor: ProductCompactionExecutor,
    agent: Agent,
    preparation: CompactionPreparation,
    custom_instructions: str | None,
) -> CompactionResult:
    if supports_prepare_model_call(executor):
        if _supports_keyword(executor, "request_limits"):
            return await executor(
                preparation=preparation,
                model=agent.model,
                headers=None,
                signal=agent.signal,
                custom_instructions=custom_instructions,
                prepare_model_call=agent.prepare_model_call,
                request_limits=agent.call_options.request_limits,
            )
        return await executor(
            preparation=preparation,
            model=agent.model,
            headers=None,
            signal=agent.signal,
            custom_instructions=custom_instructions,
            prepare_model_call=agent.prepare_model_call,
        )
    legacy_executor = cast(
        Callable[..., Awaitable[CompactionResult]],
        executor,
    )
    return await legacy_executor(
        preparation=preparation,
        model=agent.model,
        headers=None,
        signal=agent.signal,
        custom_instructions=custom_instructions,
    )


def supports_prepare_model_call(callback: Callable[..., object]) -> bool:
    """Return whether a Product summary callback accepts the PR8 seam."""

    return _supports_keyword(callback, "prepare_model_call")


def _supports_keyword(callback: Callable[..., object], name: str) -> bool:
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return False
    parameter = parameters.get(name)
    if parameter is not None and parameter.kind in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }:
        return True
    return any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    )


async def _compact_manual(
    session_runtime: SessionRuntime,
    compaction_runtime: AgentTranscriptCompactionRuntime,
    custom_instructions: str | None = None,
) -> CompactionResult:
    session_runtime.abort()
    await session_runtime.wait_for_idle()
    result = await compaction_runtime.compact(
        reason="manual",
        will_retry=False,
        raise_on_error=True,
        custom_instructions=custom_instructions,
    )
    assert result is not None
    return result


async def apply_agent_session_model_selection(
    selection_runtime: AgentTranscriptSelectionRuntime,
    selection: object,
    agent: Agent,
    session_runtime: SessionRuntime,
    extension_runner: ExtensionEventPort | None,
    refresh_extension_runtime: Callable[[str], Awaitable[None]],
    get_cwd: Callable[[], str],
    source: str = "set",
) -> None:
    async def apply_selection() -> None:
        resolved = selection_runtime.resolve_model(
            cast(Model | ModelSelection, selection)
        )
        validate_image_input_compatibility(resolved, agent.state.messages)
        previous = agent.model
        await selection_runtime.apply_model(resolved)
        await refresh_extension_runtime("model_selection_changed")
        if extension_runner is not None and previous != resolved:
            await extension_runner.emit_agent_event(
                {
                    "type": "model_select",
                    "model": resolved,
                    "previous_model": previous,
                    "source": source,
                },
                cwd=get_cwd(),
            )

    await session_runtime.host_runtime.run_after_idle(apply_selection)


async def _set_session_name(
    session: ProductTranscriptSession[Any, Any],
    dispatch: EventDispatcher,
    name: str | None,
) -> None:
    record_id = await session.append_session_info(name)
    await dispatch(
        ConversationMetadataChanged(name=name),
        source_record_id=record_id,
    )


async def _reload_resources_from_watch(
    refresh_runtime: SessionResourceRefreshRuntime,
    extension_runner: SessionExtensionCompositionPort | None,
    reload_extensions: Callable[[], Awaitable[None]],
) -> None:
    if extension_runner is not None:
        await reload_extensions()
        return
    await refresh_runtime.refresh_async(reason="watch")


def _last_assistant_message(
    messages: Sequence[object],
) -> AssistantMessage | None:
    for message in reversed(messages):
        if isinstance(message, AssistantMessage):
            return message
    return None


__all__ = [
    "ProductCompactionExecutor",
    "SessionComposition",
    "SessionCompositionPorts",
    "SessionFoundationInputs",
    "SessionMaintenanceInputs",
    "SessionProductInputs",
    "apply_agent_session_model_selection",
    "compose_session_runtime",
    "sleep_for_retry",
]
