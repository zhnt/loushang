"""Reusable Product binding for the standard Agent session composition."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, Protocol, cast

from loushang.agent import Agent
from loushang.ai.api_registry import (
    APIRegistry,
    get_default_api_registry,
)
from loushang.ai.model import ModelSelection
from loushang.ai.types import ImagePart
from loushang.foundation.json import JSONValue
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    MODEL_INPUT_PREPARATION_REQUIREMENT,
    RESOURCES_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
    CapabilityBundleProviderBinding,
    CapabilityFacetSet,
    CapabilityGraphExplanation,
    CapabilityGraphPlanRequest,
    EffectiveRuntimeDiff,
    EffectiveRuntimeView,
    RegistrationExplanation,
    RegistrationInventoryEntry,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphProjector,
    RuntimeCapabilityGraphRuntime,
    RuntimeProfileSlotExplanation,
    ScopedSourcePublicationReference,
    StagedResourceCompositionCandidate,
)
from loushang.harness.capabilities.component_host import (
    CapabilityComponentHost,
    PreparedCapabilityComponent,
)
from loushang.harness.capabilities.effective_runtime import (
    runtime_profile_fingerprint,
)
from loushang.harness.capabilities.prompt_preflight import SkillBodyLoader
from loushang.harness.capabilities.resources_consumers import (
    ResourceSkillStatusCatalogCapabilityConsumer,
)
from loushang.harness.capabilities.resources_contracts import (
    RESOURCES_CAPABILITY_DEFINITION_V4,
    RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT,
)
from loushang.harness.capabilities.resources_provider import (
    resources_capability_provider_binding,
)
from loushang.harness.capabilities.session_contracts import (
    SESSION_CAPABILITY_DEFINITION,
    SESSION_RESOURCE_COMPOSITION_REQUIREMENT,
    SESSION_SIDE_QUESTION_REQUIREMENT,
    SESSION_TRANSCRIPT_REQUIREMENT,
    SESSION_WORKSPACE_PROCESS_REQUIREMENT,
    SESSION_WORKSPACE_TOOL_REQUIREMENT,
)
from loushang.harness.config.agent import (
    CompactionSettings,
    RetrySettings,
    SettingsManager,
)
from loushang.harness.context import serialize_context_usage_payload
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.extensions import ExtensionProviderRuntime
from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.extensions.context import (
    ReplacedSessionContext,
    SessionBeforeCompactEvent,
    SessionShutdownEvent,
    SessionStartEvent,
)
from loushang.harness.extensions.provider_config import provider_from_extension_config
from loushang.harness.extensions.runtime_bindings import ExtensionRuntimeBindingFactory
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resource_catalog.joint_generation import (
    ExtensionGenerationRetirementPort,
)
from loushang.harness.resource_catalog.session_bootstrap import (
    InitialExtensionGenerationHost,
    InitialSessionResourceCatalogBootstrap,
    InitialSessionResourcePublication,
)
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._skill_catalog_consumer import (
    LoadedSkillBody,
    SkillCatalogConsumer,
    SkillCatalogSummary,
)
from loushang.harness.resources._skill_catalog_status import (
    SkillCatalogStatusSummary,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.catalog import PackageSummaryProvider
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.roots import SelectedPluginPackageInput
from loushang.harness.resources.packages.session import (
    SessionPackageController,
    SessionPackageSettingsManager,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import (
    CancellationSignal,
    ResolvedRuntimeProfile,
    SideQuestionAnswer,
    SideQuestionProvider,
    SideQuestionProviderFactory,
    SideQuestionUpdate,
)
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.session.agent_adapter import (
    AgentSessionAdapterMixin,
    initialize_composed_session,
)
from loushang.harness.session.approval_interaction import (
    AgentSessionApprovalRuntime,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerGenerationBinding,
    SessionCapabilityOwnerGenerationStagingError,
    StagedSessionCapabilityOwnerGeneration,
    dispose_session_capability_owner_generations,
    stage_session_capability_owner_generations,
    validate_session_capability_composition_closure,
    validate_session_capability_owner_generation_bindings,
)
from loushang.harness.session.command_controller import (
    SessionCommandGenerationRegistry,
    StandardSessionCommandController,
)
from loushang.harness.session.commands.execution import StandardSessionCommandPorts
from loushang.harness.session.composition import (
    ProductCompactionExecutor,
    SessionCompositionPorts,
    SessionExtensionCompositionPort,
    SessionFoundationInputs,
    SessionMaintenanceInputs,
    SessionModelCatalogPort,
    SessionProductInputs,
    SessionResourceCompositionPorts,
    SessionWorkspaceCompositionPorts,
    compose_session_runtime,
    supports_prepare_model_call,
)
from loushang.harness.session.diagnostics import SessionDiagnosticsRuntime
from loushang.harness.session.extension_bridge import AgentSessionExtensionBridge
from loushang.harness.session.legacy_side_question import (
    LegacySideQuestionBinding,
    bind_legacy_side_question,
)
from loushang.harness.session.model_call import (
    SessionModelCallCapabilityConsumer,
    SessionModelCallRuntime,
    build_session_model_call_capability_binding,
)
from loushang.harness.session.operations_runtime import SessionOperationsPorts
from loushang.harness.session.output_artifacts import (
    persist_session_command_outputs,
)
from loushang.harness.session.request_evidence import (
    SessionRequestEvidenceRuntime,
)
from loushang.harness.session.resource_capability_ports import (
    SessionResourceCapabilityPorts,
)
from loushang.harness.session.resource_refresh import ExtensionDeclarationPreflight
from loushang.harness.session.resource_refresh_gate import (
    ResourceCatalogRefreshGatePort,
)
from loushang.harness.session.session_capability_consumer import (
    SessionResourceCompositionCapabilityConsumer,
    SessionSideQuestionCapabilityConsumer,
    SessionTranscriptCapabilityConsumer,
    SessionWorkspaceProcessCapabilityConsumer,
    SessionWorkspaceToolCapabilityConsumer,
)
from loushang.harness.session.session_capability_provider import (
    session_capability_provider_binding,
)
from loushang.harness.session.session_transcript_capability_ports import (
    SessionTranscriptCapabilityPorts,
)
from loushang.harness.session.settings import SessionSettingsBinding
from loushang.harness.session.side_question import (
    SIDE_QUESTION_BOUNDARY_PROMPT,
    AgentSideQuestionProvider,
)
from loushang.harness.session.turn_performance import TurnStartPerformanceRuntime
from loushang.harness.session.workspace_capability_ports import (
    SessionWorkspaceCapabilityPorts,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionHookDecision,
    CompactionHookRequest,
    CompactionResult,
    ProductTranscriptSession,
)
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.process import AuthorizedProcessLauncher

ResourceCatalogRefreshBootstrapFactory = Callable[
    [int], InitialSessionResourceCatalogBootstrap
]


class ResourceCatalogRefreshRetirementError(RuntimeError):
    """Published Catalog refresh has retryable old-generation cleanup debt."""


BranchSummaryExecutor = Callable[..., Awaitable[BranchSummaryOutput]]
ChangelogProvider = Callable[[str, str], object]
ClipboardWriter = Callable[[str], object]
RetrySleeper = Callable[[int, CancellationSignal], Awaitable[None]]


def _require_durable_summary_executor(
    callback: Callable[..., object], *, name: str
) -> None:
    if not supports_prepare_model_call(callback):
        raise ValueError(f"durable Product {name} must accept prepare_model_call")


class FooterDataPort(Protocol):
    """Footer updates consumed by the shared Product session adapter."""

    def set_extension_status(self, name: str, status: str | None) -> None: ...

    def set_available_provider_count(self, count: int) -> None: ...

    def dispose(self) -> None: ...


class AgentProductSession(AgentSessionAdapterMixin):
    """Bind Product callbacks to the existing standard session runtimes."""

    resource_bundle: ResourceBundle | None

    async def prompt(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
        *,
        streaming_behavior: str | None = None,
        source: str | None = None,
        preflight_result: Callable[[bool], None] | None = None,
    ) -> None:
        """Publish the Session composition before command/model visibility."""

        await self.prepare_model_call_runtime()
        await super().prompt(
            user_input,
            images=images,
            streaming_behavior=streaming_behavior,
            source=source,
            preflight_result=preflight_result,
        )

    async def continue_run(self) -> None:
        await self.prepare_model_call_runtime()
        await super().continue_run()

    async def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> object | None:
        await self.prepare_model_call_runtime()
        return await super().execute_command_async(invocation_name, args)

    def __init__(
        self,
        *,
        agent: Agent,
        session_manager: ProductTranscriptSession[Any, Any],
        capability_runtime: StagedResourceCompositionCandidate,
        execute_compaction: ProductCompactionExecutor,
        execute_branch_summary: BranchSummaryExecutor,
        get_changelog: ChangelogProvider,
        copy_to_clipboard: ClipboardWriter,
        retry_sleep: RetrySleeper,
        footer_data_provider: FooterDataPort,
        side_question_binding: LegacySideQuestionBinding | None = None,
        package_summary_provider: PackageSummaryProvider | None = None,
        settings_manager: SettingsManager | None = None,
        model_registry: SessionModelCatalogPort | None = None,
        resource_loader: ResourceLoader | None = None,
        resource_bundle: ResourceBundle | None = None,
        extension_runner: SessionExtensionCompositionPort | None = None,
        tool_registry: WorkspaceToolRegistry | None = None,
        allowed_tool_names: list[str] | None = None,
        active_tool_names: list[str] | None = None,
        default_activate_new_tools: bool | None = None,
        show_empty_tool_prompt: bool = False,
        base_prompt: str | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        package_materializer: PackageMaterializer | None = None,
        selected_plugin_packages: tuple[SelectedPluginPackageInput, ...] = (),
        session_start_event: SessionStartEvent | None = None,
        api_registry: APIRegistry | None = None,
        exec_service: ExecService | None = None,
        tool_exec_service: ExecService | None = None,
        approval_resolver: InteractiveApprovalResolver | None = None,
        tool_policy_evaluator: PolicyEvaluator | None = None,
        workspace_capability_binding: CapabilityBundleProviderBinding | None = None,
        extension_declaration_preflight: ExtensionDeclarationPreflight | None = None,
        capability_composition_inputs: SessionCapabilityCompositionInputs | None = None,
        capability_component_host: CapabilityComponentHost | None = None,
        capability_owner_generation_bindings: tuple[
            SessionCapabilityOwnerGenerationBinding, ...
        ] = (),
        command_generation_registry: SessionCommandGenerationRegistry | None = None,
        initial_resource_catalog_bootstrap: (
            InitialSessionResourceCatalogBootstrap | None
        ) = None,
        resource_catalog_refresh_bootstrap_factory: (
            ResourceCatalogRefreshBootstrapFactory | None
        ) = None,
        resource_catalog_refresh_lock: ResourceCatalogRefreshGatePort | None = None,
    ) -> None:
        self.agent = agent
        self._session_default_model = agent.model
        self.session_manager = session_manager
        self._settings_controller = SessionSettingsBinding(
            settings_manager=settings_manager,
            create_settings_manager=SettingsManager,
            default_compaction=CompactionSettings,
            default_retry=RetrySettings,
            get_steering_mode_callback=lambda: self.agent.steering_mode,
            set_steering_mode_callback=self._set_agent_steering_mode,
            get_follow_up_mode_callback=lambda: self.agent.follow_up_mode,
            set_follow_up_mode_callback=self._set_agent_follow_up_mode,
        )
        self.model_registry = model_registry
        self.api_registry = api_registry or get_default_api_registry()
        self._resource_loader = (
            resource_loader.create_catalog_session_view()
            if resource_loader is not None
            and initial_resource_catalog_bootstrap is not None
            else resource_loader
        )
        self.resource_bundle = resource_bundle
        self._extension_runner = extension_runner
        self._initial_resource_catalog_bootstrap = initial_resource_catalog_bootstrap
        self._resource_catalog_refresh_bootstrap_factory = (
            resource_catalog_refresh_bootstrap_factory
        )
        self._resource_catalog_refresh_lock = resource_catalog_refresh_lock
        self._resource_catalog_snapshot: object | None = None
        self._resource_catalog_projection: object | None = None
        self._skill_catalog_consumer: SkillCatalogConsumer | None = None
        self._resource_skill_catalog_facets: CapabilityFacetSet | None = None
        self._mounted_resource_candidate: StagedResourceCompositionCandidate | None = (
            None
        )
        self._pending_resource_catalog_retirements: list[
            ExtensionGenerationRetirementPort
        ] = []
        self._extension_declaration_preflight = extension_declaration_preflight
        self._extension_bridge = AgentSessionExtensionBridge()
        if (
            session_manager.persist
            and not agent.model_transport_is_prepared_request_conformant
            and not agent.model_transport_is_explicitly_synthetic
        ):
            raise ValueError(
                "durable Product sessions require the standard AI stream or a "
                "prepared_request_conformant custom stream"
            )
        if self.agent.prepare_model_call is not None:
            raise ValueError(
                "Agent Product session owns the model-call preparation boundary"
            )
        if session_manager.persist:
            _require_durable_summary_executor(
                execute_compaction,
                name="compaction executor",
            )
            _require_durable_summary_executor(
                execute_branch_summary,
                name="branch-summary executor",
            )
        self._capability_profile_provider: (
            Callable[[], ResolvedRuntimeProfile] | None
        ) = lambda: capability_runtime.profile
        self._staged_resource_candidate: StagedResourceCompositionCandidate | None = (
            capability_runtime
        )
        self._resource_capability_ports = SessionResourceCapabilityPorts(
            capability_runtime
        )
        runtime_id = "session:" + str(
            self.session_manager.get_session_record().session_id
        )
        initial_profile = capability_runtime.profile.snapshot()
        if initial_resource_catalog_bootstrap is not None:
            if not isinstance(
                initial_resource_catalog_bootstrap,
                InitialSessionResourceCatalogBootstrap,
            ):
                raise TypeError("initial Resource Catalog bootstrap is invalid")
            if extension_runner is None:
                raise ValueError(
                    "initial Resource Catalog bootstrap requires an Extension runtime"
                )
            if (
                initial_resource_catalog_bootstrap.product_id
                != initial_profile.product_id
            ):
                raise ValueError(
                    "initial Resource Catalog bootstrap belongs to another Product"
                )
            if initial_resource_catalog_bootstrap.scope_id != runtime_id:
                raise ValueError(
                    "initial Resource Catalog bootstrap belongs to another Session"
                )
        if resource_catalog_refresh_bootstrap_factory is not None:
            if initial_resource_catalog_bootstrap is None:
                raise ValueError(
                    "Resource Catalog refresh requires initial Catalog authority"
                )
            if not callable(resource_catalog_refresh_bootstrap_factory):
                raise TypeError("Resource Catalog refresh factory is invalid")
        self._turn_start_performance = TurnStartPerformanceRuntime(
            session_id=str(self.session_manager.get_session_record().session_id)
        )
        self._request_evidence_runtime = SessionRequestEvidenceRuntime(
            get_context_message_bindings=(
                self.session_manager.get_context_message_bindings
            ),
            get_active_records=self.session_manager.get_active_entries,
            rebuild_model_input=self.session_manager.rebuild_model_input,
        )
        if (
            capability_composition_inputs is not None
            and capability_composition_inputs.product_id != initial_profile.product_id
        ):
            raise ValueError("Session plugin composition belongs to another Product")
        if (
            capability_composition_inputs is not None
            and capability_composition_inputs.component_requests
            and capability_component_host is None
        ):
            raise ValueError("Session plugin composition requires a Component Host")
        if capability_composition_inputs is None and (
            capability_component_host is not None
            or capability_owner_generation_bindings
        ):
            raise ValueError("Session Component Host/owners require composition inputs")
        self._capability_composition_inputs = capability_composition_inputs
        self._capability_component_host = capability_component_host
        if command_generation_registry is not None and not isinstance(
            command_generation_registry,
            SessionCommandGenerationRegistry,
        ):
            raise TypeError("Session Command generation registry is invalid")
        self._command_generation_registry = command_generation_registry
        self._capability_owner_generation_bindings = tuple(
            capability_owner_generation_bindings
        )
        self._external_consumer_captures: tuple[
            SessionCapabilityConsumerCapture, ...
        ] = ()
        self._capability_owner_generations: tuple[
            StagedSessionCapabilityOwnerGeneration, ...
        ] = ()
        self._pending_capability_components: tuple[
            PreparedCapabilityComponent, ...
        ] = ()
        if capability_composition_inputs is not None:
            validate_session_capability_owner_generation_bindings(
                admissions=(
                    capability_composition_inputs.product_composition.catalog_admissions
                ),
                bindings=self._capability_owner_generation_bindings,
            )
        if (
            workspace_capability_binding is not None
            and workspace_capability_binding.provider.capability_id
            != WORKSPACE_CAPABILITY_DEFINITION.capability_id
        ):
            raise ValueError("Session workspace binding must provide harness.workspace")
        self._capability_graph_runtime = RuntimeCapabilityGraphRuntime(
            product_id=initial_profile.product_id,
            runtime_id=runtime_id,
            profile_fingerprint=runtime_profile_fingerprint(initial_profile),
        )
        self._capability_graph_binder = RuntimeCapabilityGraphBinder()
        self._capability_graph_projector = RuntimeCapabilityGraphProjector(
            self._capability_graph_runtime
        )
        self._model_call_bind_lock = asyncio.Lock()
        self._model_call_consumer: SessionModelCallCapabilityConsumer | None = None
        self._workspace_capability_ports = SessionWorkspaceCapabilityPorts(
            self._ensure_session_graph_prepared
        )
        self._staged_transcript_candidate = (
            session_manager.transcript_capability_candidate()
        )
        self._transcript_capability_ports = SessionTranscriptCapabilityPorts(
            self._staged_transcript_candidate
        )
        self._resource_capability_binding = (
            self._build_resource_capability_provider_binding()
        )
        self._workspace_capability_binding = workspace_capability_binding
        self._staged_side_question_candidate: LegacySideQuestionBinding | None = (
            side_question_binding
            if side_question_binding is not None
            else bind_legacy_side_question(capability_runtime.profile)
        )
        self._session_capability_binding = session_capability_provider_binding(
            scope_instance_id=runtime_id,
            staged_side_question=self._staged_side_question_candidate,
            staged_transcript=self._staged_transcript_candidate,
            bind_provider=self._bind_selected_side_question_provider,
        )
        self._model_call_capability_binding = (
            build_session_model_call_capability_binding(
                transcript=self._transcript_capability_ports,
                projector=self._capability_graph_projector,
                product_id=initial_profile.product_id,
                runtime_id=runtime_id,
                conversation_id=(self.session_manager.get_session_record().session_id),
                is_current=self._is_current_model_call_session,
                registration_entries_provider=self._effective_registration_entries,
                profile_fingerprint_provider=self._current_profile_fingerprint,
                session_provider=self._session_capability_binding.provider,
                resources_provider=self._resource_capability_binding.provider,
                workspace_provider=(
                    workspace_capability_binding.provider
                    if workspace_capability_binding is not None
                    else None
                ),
                turn_performance=self._turn_start_performance,
                request_evidence_provider=(
                    self._request_evidence_runtime.project_model_input
                ),
            )
        )
        self._side_question_consumer: SessionSideQuestionCapabilityConsumer | None = (
            None
        )
        self._transcript_consumer: SessionTranscriptCapabilityConsumer | None = None
        workspace_binding = self._workspace_capability_binding
        workspace_definitions = (
            (WORKSPACE_CAPABILITY_DEFINITION,) if workspace_binding is not None else ()
        )
        built_in_definitions = (
            MODEL_INPUT_CAPABILITY_DEFINITION,
            RESOURCES_CAPABILITY_DEFINITION,
            SESSION_CAPABILITY_DEFINITION,
            *workspace_definitions,
        )
        built_in_providers = (
            self._model_call_capability_binding.provider_binding.provider,
            self._resource_capability_binding.provider,
            self._session_capability_binding.provider,
            *((workspace_binding.provider,) if workspace_binding is not None else ()),
        )
        external_definitions = (
            tuple(
                item.definition
                for item in capability_composition_inputs.resolved_providers.entries
            )
            if capability_composition_inputs is not None
            else ()
        )
        external_providers = (
            capability_composition_inputs.resolved_providers.providers
            if capability_composition_inputs is not None
            else ()
        )
        built_in_ids = {item.capability_id for item in built_in_definitions}
        if built_in_ids.intersection(
            item.capability_id for item in external_definitions
        ):
            raise ValueError("External composition duplicates a built-in Capability")
        if capability_composition_inputs is not None:
            built_in_provider_by_id = {
                item.capability_id: item for item in built_in_providers
            }
            if any(
                built_in_provider_by_id.get(item.capability_id) != item
                for item in (
                    capability_composition_inputs.resolved_providers.prebound_providers
                )
            ):
                raise ValueError(
                    "External composition prebound Providers do not match Session built-ins"
                )
        graph_roots: tuple[str, ...] = (
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
        )
        if capability_composition_inputs is not None:
            requirements = (
                capability_composition_inputs.product_composition.consumer_requirements
            )
            if (
                MODEL_INPUT_CAPABILITY_DEFINITION.capability_id
                not in requirements.roots
            ):
                raise ValueError("Session composition must retain model-input root")
            validate_session_capability_composition_closure(
                capability_composition_inputs.product_composition,
                capability_composition_inputs.resolved_providers,
                host_capability_ids=tuple(sorted(built_in_ids)),
                host_providers=built_in_providers,
            )
            graph_roots = requirements.roots
        self._session_capability_plan = RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id=initial_profile.product_id,
                roots=graph_roots,
                definitions=(*built_in_definitions, *external_definitions),
                providers=(*built_in_providers, *external_providers),
            )
        )
        self._model_call_runtime = SessionModelCallRuntime(
            transcript=self._transcript_capability_ports,
            ensure_consumer=self._ensure_session_graph_prepared,
            projector=self._capability_graph_projector,
            registration_entries_provider=self._effective_registration_entries,
            source_publication_provider=self._source_publication_reference,
        )
        self._previous_agent_prepare_model_call = self.agent.prepare_model_call
        self._installed_agent_prepare_model_call: object | None = None
        self._previous_transport_requirement = (
            self.agent.model_transport_requires_prepared_request_conformance
        )
        self._installed_transport_requirement: bool | None = None
        self._extension_tool_registration_leases = []
        self._tool_registry = tool_registry
        self.diagnostics_service = diagnostics_service
        self._package_materializer = package_materializer
        self._selected_plugin_packages = tuple(selected_plugin_packages)
        if any(
            not isinstance(item, SelectedPluginPackageInput)
            for item in self._selected_plugin_packages
        ):
            raise TypeError("Selected Plugin package inputs are invalid")
        base_exec_service = exec_service or ExecService()
        session_temporary_root = resolve_platform_paths().temporary
        self._exec_service = persist_session_command_outputs(
            base_exec_service,
            session_dir=session_manager.session_dir,
            session_id=session_manager.get_header().conversation_id,
            persist=session_manager.persist,
            temporary_root=session_temporary_root,
        )
        if not session_manager.persist:
            self._tool_exec_service = tool_exec_service
        elif tool_exec_service is None or tool_exec_service is base_exec_service:
            self._tool_exec_service = self._exec_service
        else:
            self._tool_exec_service = persist_session_command_outputs(
                tool_exec_service,
                session_dir=session_manager.session_dir,
                session_id=session_manager.get_header().conversation_id,
                persist=True,
                temporary_root=session_temporary_root,
            )
        self.footer_data_provider = footer_data_provider
        self._base_prompt = (
            base_prompt if base_prompt is not None else self.agent.system_prompt
        )
        self._execute_product_compaction = execute_compaction
        self._execute_product_branch_summary = execute_branch_summary
        self._get_product_changelog = get_changelog
        self._copy_product_text = copy_to_clipboard
        self._retry_sleep = retry_sleep
        self._bind_package_progress_events()
        self._session_start_event = session_start_event or SessionStartEvent(
            reason="startup"
        )
        self._approval_runtime = AgentSessionApprovalRuntime(
            resolver=approval_resolver,
            get_permission_profile_snapshot=(
                self._settings_controller.get_permission_profile_snapshot
            ),
            set_permission_profile=self._settings_controller.set_permission_profile,
            dispatch_event=self._dispatch_event,
            abort=self.abort,
        )
        self._tool_policy_evaluator = tool_policy_evaluator
        self._package_controller = SessionPackageController(
            get_session_id=lambda: self.session_manager.get_session_record().session_id,
            get_cwd=self.session_manager.get_cwd,
            get_settings_manager=lambda: cast(
                SessionPackageSettingsManager | None,
                self._settings_controller.get_settings_manager(),
            ),
            get_package_materializer=lambda: self._package_materializer,
            get_resource_loader=lambda: self._resource_loader,
            get_diagnostics_service=lambda: self.diagnostics_service,
            refresh_resources=self._refresh_resources_for_extension_runtime,
            selected_plugin_packages=self._selected_plugin_packages,
            refresh_resource_transaction=(self._refresh_package_resource_transaction),
            summary_provider=package_summary_provider,
            supports_synchronous_refresh=(
                lambda: (
                    self._composition.resource_refresh_runtime.refresh_catalog is None
                )
            ),
        )
        self._extension_provider_controller = ExtensionProviderRuntime(
            model_registry=self.model_registry,
            api_registry=self.api_registry,
            provider_factory=provider_from_extension_config,
        )
        self._extension_replacement_controller = ExtensionReplacementRuntime(
            get_runtime_host=lambda: self._extension_bridge.runtime_host,
        )
        self._extension_runtime_binding_factory = ExtensionRuntimeBindingFactory(
            get_cwd=self.session_manager.get_cwd,
            session_manager=self.session_manager,
            model_registry=self.model_registry,
            get_active_tool_names=lambda: self.get_active_tool_names(),
            get_all_tools=lambda: list(self.get_all_tools()),
            get_model_selection=self._get_extension_model_selection,
            set_active_tools=self._set_active_tools_from_extension,
            set_model=self._set_model_from_extension,
            register_tool=self._register_extension_runtime_tool,
            bind_tool=self._bind_extension_runtime_tool,
            adopt_tool=self._adopt_extension_runtime_tool,
            stage_tool=self._stage_extension_runtime_tool,
            append_entry=self._append_extension_entry,
            send_message=self._send_message_from_extension,
            send_user_message=self._send_user_message_from_extension_async,
            get_signal=lambda: self.agent.signal,
            set_session_name=self.set_session_name,
            get_session_name=lambda: self.session_name,
            set_label=self._set_extension_label,
            list_commands=lambda: self.list_commands(),
            request_resource_refresh=self.request_resource_refresh,
            shutdown=self._abort_from_extension,
            record_diagnostic=self._record_extension_runtime_diagnostic,
            abort=self._abort_from_extension,
            is_idle=lambda: not self.agent.is_streaming,
            has_pending_messages=self.has_pending_messages,
            get_context_usage=self.get_context_usage,
            get_thinking_level=lambda: self.agent.thinking_level,
            set_thinking_level=self.set_thinking_level,
            register_provider=self._register_provider_from_extension,
            unregister_provider=self._unregister_provider_from_extension,
            bind_provider=self._bind_provider_from_extension,
            bind_provider_removal=self._bind_provider_removal_from_extension,
            stage_provider=self._stage_provider_from_extension,
            stage_provider_removal=self._stage_provider_removal_from_extension,
            set_extension_status=self._set_extension_status_from_extension,
            get_footer_data_provider=lambda: self.footer_data_provider,
            compact=self._compact_from_extension,
            get_system_prompt=lambda: self.agent.system_prompt,
            wait_for_idle=self.wait_for_idle,
            reload=self._reload_from_extension,
            navigate_tree=self._navigate_tree_from_extension,
            fork=self._fork_from_extension,
            new_session=self._new_session_from_extension,
            switch_session=self._switch_session_from_extension,
            get_ui_context=lambda: self._extension_bridge.ui_context,
            exec_command=self._exec_command_from_extension,
        )
        composition = compose_session_runtime(
            self._composition_ports(
                allowed_tool_names=allowed_tool_names,
                active_tool_names=active_tool_names,
                default_activate_new_tools=default_activate_new_tools,
                show_empty_tool_prompt=show_empty_tool_prompt,
            )
        )
        initialize_composed_session(
            self,
            composition,
            operations_ports=SessionOperationsPorts(
                composition=composition,
                agent=self.agent,
                session_manager=self.session_manager,
                extension_runner=self._extension_runner,
                execute_branch_summary=self._execute_product_branch_summary,
                before_tree=self._apply_before_tree_hook,
                dispose_runtime_profile=self._dispose_session_runtime_profile,
                finalize_shutdown=self._finalize_after_session_shutdown,
                invalidate_extension_contexts=self._invalidate_extension_contexts,
                sync_extension_diagnostics=self._sync_extension_diagnostics,
                close_approvals=self._close_session_approvals,
            ),
            settings=self._settings_controller,
            session_manager=self.session_manager,
            active_tool_names=active_tool_names,
            show_empty_tool_prompt=show_empty_tool_prompt,
            tool_registry=self._tool_registry,
            apply_context=self._apply_agent_transcript_context,
            sync_footer=self._sync_footer_available_provider_count,
        )
        self._install_agent_model_call_boundary()

    @property
    def capability_profile(self) -> ResolvedRuntimeProfile:
        """Return the final resolved Session capability profile."""

        provider = self._capability_profile_provider
        if provider is None:
            raise RuntimeError("Session capability profile has been disposed.")
        return provider()

    def get_effective_runtime_view(
        self,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> EffectiveRuntimeView:
        """Compose current runtime facts without claiming one atomic clock."""

        return self._model_call_runtime.effective_view(
            self.capability_profile.snapshot(),
            model_input_snapshot_id=model_input_snapshot_id,
        )

    def explain_runtime_capability(
        self,
        capability_id: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> CapabilityGraphExplanation:
        return self._model_call_runtime.explain_capability(
            self.capability_profile.snapshot(),
            capability_id,
            model_input_snapshot_id=model_input_snapshot_id,
        )

    def explain_runtime_profile_slot(
        self,
        slot: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> RuntimeProfileSlotExplanation:
        return self._model_call_runtime.explain_profile_slot(
            self.capability_profile.snapshot(),
            slot,
            model_input_snapshot_id=model_input_snapshot_id,
        )

    def explain_runtime_registration(
        self,
        registration_id: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> RegistrationExplanation:
        return self._model_call_runtime.explain_registration(
            self.capability_profile.snapshot(),
            registration_id,
            model_input_snapshot_id=model_input_snapshot_id,
        )

    def diff_effective_runtime(
        self,
        before: EffectiveRuntimeView,
        after: EffectiveRuntimeView,
    ) -> EffectiveRuntimeDiff:
        return self._model_call_runtime.diff(before, after)

    def effective_runtime_to_json(
        self,
        value: EffectiveRuntimeView
        | EffectiveRuntimeDiff
        | CapabilityGraphExplanation
        | RuntimeProfileSlotExplanation
        | RegistrationExplanation,
    ) -> dict[str, JSONValue]:
        return self._model_call_runtime.to_json(value)

    def _effective_registration_entries(
        self,
    ) -> tuple[RegistrationInventoryEntry, ...]:
        tool_registry = self._tool_registry
        if tool_registry is None:
            tool_registry = self._composition.tool_controller.tool_registry
        raw = [
            (*item, "effective")
            for item in (
                tool_registry.registration_inventory
                if tool_registry is not None
                else ()
            )
        ]
        command_generations = getattr(
            self,
            "_command_generation_registry",
            None,
        )
        raw.extend(
            (*item, "effective")
            for item in (
                command_generations.registration_inventory
                if command_generations is not None
                else ()
            )
        )
        raw.extend(
            (*item, "effective")
            for item in getattr(
                self._extension_runner,
                "registration_inventory",
                (),
            )
        )
        raw.extend(
            (*item, "pending_retirement")
            for item in getattr(
                self._extension_runner,
                "retired_registration_inventory",
                (),
            )
        )
        entries: dict[str, RegistrationInventoryEntry] = {}
        for owner, identity, state, attachment in raw:
            if state == "disposed":
                continue
            entry = RegistrationInventoryEntry(
                registration_id=identity.registration_id,
                surface=identity.surface,
                public_key=identity.public_key,
                owner_kind=owner.owner_kind,
                owner_id=owner.owner_id,
                runtime_id=owner.runtime_id,
                owner_generation=owner.generation,
                attachment=cast(Literal["effective", "pending_retirement"], attachment),
                state=state,
            )
            existing = entries.get(entry.registration_id)
            if existing is not None and not _same_registration_identity(
                existing, entry
            ):
                raise RuntimeError(
                    "registration id maps to conflicting Session inventory entries"
                )
            entries[entry.registration_id] = entry
        return tuple(entries.values())

    def _composition_ports(
        self,
        *,
        allowed_tool_names: list[str] | None,
        active_tool_names: list[str] | None,
        default_activate_new_tools: bool | None,
        show_empty_tool_prompt: bool,
    ) -> SessionCompositionPorts:
        def build_command_controller(
            diagnostics_runtime: SessionDiagnosticsRuntime,
        ) -> StandardSessionCommandController:
            return StandardSessionCommandController(
                session_manager=self.session_manager,
                get_extension_runner=lambda: self._extension_runner,
                get_resource_bundle=lambda: self.resource_bundle,
                get_effective_skills=self._effective_skill_summaries,
                get_skill_body_loader=self._skill_body_loader,
                skill_body_authority=(
                    "catalog_required"
                    if self._initial_resource_catalog_bootstrap is not None
                    else "legacy_explicit"
                ),
                get_diagnostics_service=lambda: self.diagnostics_service,
                diagnostics_runtime=diagnostics_runtime,
                standard_ports=StandardSessionCommandPorts(
                    get_session_info=self._get_builtin_session_info,
                    set_session_name=self.set_session_name,
                    export_html=self.export_to_html,
                    export_jsonl=self.export_to_jsonl,
                    export_bundle=self.export_to_bundle,
                    compact=self.compact,
                    reload=self.reload_extension_runtime,
                    get_recent_assistant_texts=self.get_recent_assistant_texts,
                    get_last_assistant_text=self.get_last_assistant_text,
                    copy_text=self._copy_product_text,
                    get_changelog=lambda args: self._get_product_changelog(
                        self.session_manager.get_cwd(), args
                    ),
                    new_session=self._new_session_from_extension,
                    resume_session=self._switch_session_from_extension,
                    fork_session=self._fork_from_extension,
                    clone_session=self._extension_replacement_controller.clone_session,
                    navigate_tree=self._navigate_tree_from_extension,
                    import_session=self._extension_replacement_controller.import_session,
                    get_active_tool_names=self.get_active_tool_names,
                    get_all_tools=self.get_all_tool_infos,
                    set_active_tools=self.set_active_tools,
                    get_default_active_tool_names=self._default_active_tool_names,
                    get_extensions=self.list_extensions,
                ),
                command_generations=self._command_generation_registry,
                pack_composer=cast(
                    Any,
                    self._resource_capability_ports.commands,
                ),
            )

        return SessionCompositionPorts(
            agent=self.agent,
            session_manager=self.session_manager,
            settings=self._settings_controller,
            product_id=self.capability_profile.product_id,
            resources=SessionResourceCompositionPorts(
                activation=self._resource_capability_ports.activation,
                skill_activation=self._resource_capability_ports.skills,
                prompt_sections=self._resource_capability_ports.prompt,
                tool_packs=self._resource_capability_ports.tools,
                command_packs=self._resource_capability_ports.commands,
            ),
            workspace=SessionWorkspaceCompositionPorts(
                operation_bindings=(
                    self._workspace_capability_ports.operation_bindings
                    if self._workspace_capability_binding is not None
                    else {}
                ),
            ),
            foundation=SessionFoundationInputs(
                resource_loader=self._resource_loader,
                get_resource_bundle=lambda: self.resource_bundle,
                get_effective_skills=self._effective_skill_summaries,
                tool_registry=self._tool_registry,
                allowed_tool_names=allowed_tool_names,
                active_tool_names=active_tool_names,
                default_activate_new_tools=default_activate_new_tools,
                show_empty_tool_prompt=show_empty_tool_prompt,
                base_prompt=self._base_prompt,
                diagnostics_service=self.diagnostics_service,
                tool_exec_service=self._tool_exec_service,
                approval_resolver=self._approval_runtime.resolver,
                tool_policy_evaluator=self._tool_policy_evaluator,
                apply_context=self._apply_agent_transcript_context,
                refresh_agent_messages=self._refresh_agent_messages,
                dispatch_event=self._dispatch_event,
                record_runtime_exception=self._record_runtime_exception,
                before_bash=self._before_bash,
                get_bash_definition=self._get_bash_definition,
                create_bash_call_id=self._create_bash_call_id,
                get_resource_watch_paths=self._resource_watch_paths,
                prepare_resource_refresh=self._prepare_resource_refresh,
                rebuild_prompt_and_tools_view=self._rebuild_prompt_and_tools_view,
                set_resource_bundle=self._set_resource_bundle,
                record_extension_runtime_diagnostic=(
                    self._record_extension_runtime_diagnostic
                ),
                extension_declaration_preflight=(self._extension_declaration_preflight),
                request_evidence=self._request_evidence_runtime,
                refresh_catalog=(
                    self._refresh_resource_catalog
                    if self._resource_catalog_refresh_bootstrap_factory is not None
                    else None
                ),
                resource_catalog_refresh_lock=self._resource_catalog_refresh_lock,
            ),
            maintenance=SessionMaintenanceInputs(
                execute_compaction=self._execute_product_compaction,
                before_compaction=self._before_product_compaction,
                after_compaction=self._after_product_compaction,
                sleep_for_retry=self._retry_sleep,
                get_compaction_capability=(
                    self._transcript_capability_ports.compaction_capability
                ),
            ),
            product=SessionProductInputs(
                model_registry=self.model_registry,
                api_registry=self.api_registry,
                extension_runner=self._extension_runner,
                session_start_event=self._session_start_event,
                footer_data_provider=self.footer_data_provider,
                command_controller=build_command_controller,
                extension_provider_controller=self._extension_provider_controller,
                extension_replacement_controller=(
                    self._extension_replacement_controller
                ),
                extension_runtime_binding_factory=(
                    self._extension_runtime_binding_factory
                ),
                extension_bridge=self._extension_bridge,
                get_context_usage=lambda: self.get_context_usage(),
                package_controller=self._package_controller,
                execute_branch_summary=lambda entries, signal: (
                    self._branch_summary_runner(
                        custom_instructions=None,
                        replace_instructions=False,
                    )(entries, signal)
                ),
                before_agent_start_system_prompt_options=(
                    self._before_agent_start_system_prompt_options
                ),
                turn_performance=self._turn_start_performance,
            ),
        )

    def get_context_usage(self):
        return serialize_context_usage_payload(super().get_context_usage())

    def get_exec_service(self) -> ExecService:
        """Return the live session execution service for Product-owned runners."""

        return self._exec_service

    def get_workspace_process_launcher(self) -> AuthorizedProcessLauncher:
        """Return the Session's graph-backed authorized process port."""

        return self._workspace_capability_ports.process_launcher

    async def ask_side_question(
        self,
        question: str,
        *,
        on_update: SideQuestionUpdate | None = None,
    ) -> SideQuestionAnswer:
        await self._ensure_session_graph_prepared()
        consumer = self._side_question_consumer
        if consumer is None:
            raise RuntimeError("Session side-question Capability was not mounted")
        return await consumer.ask(question, on_update=on_update)

    def create_side_question_provider(self) -> AgentSideQuestionProvider:
        return AgentSideQuestionProvider(
            session=self,
            boundary_prompt=SIDE_QUESTION_BOUNDARY_PROMPT,
        )

    def _bind_selected_side_question_provider(
        self,
        factory: SideQuestionProviderFactory,
    ) -> SideQuestionProvider:
        return factory.bind(self)

    def cancel_side_question(self) -> bool:
        consumer = self._side_question_consumer
        return consumer.cancel() if consumer is not None else False

    async def dispose(
        self,
        session_shutdown_event: SessionShutdownEvent | None = None,
    ) -> None:
        self._require_external_dispose_task()
        await super().dispose(session_shutdown_event)

    async def _dispose_after_session_shutdown(self) -> None:
        self._require_external_dispose_task()
        await super()._dispose_after_session_shutdown()

    def _require_external_dispose_task(self) -> None:
        owner: str | None = None
        if self._composition.compaction_runtime.owns_current_task():
            owner = "compaction"
        elif self._composition.navigation_runtime.owns_current_task():
            owner = "branch-summary"
        else:
            consumer = self._side_question_consumer
            if consumer is not None and consumer.owns_current_task():
                owner = "side-question"
        if owner is not None:
            raise RuntimeError(
                "Session disposal cannot run from its active "
                f"{owner} task; request disposal from the Session host"
            )

    async def _dispose_session_runtime_profile(self) -> None:
        base_dispose = super()._dispose_session_runtime_profile
        task = asyncio.create_task(
            self._dispose_owned_model_call_runtime(base_dispose=base_dispose)
        )
        await _await_cancellation_atomic(task)

    async def _dispose_owned_model_call_runtime(
        self,
        *,
        base_dispose: Callable[[], Awaitable[None]],
    ) -> None:
        errors: list[BaseException] = []
        side_question_consumer = self._side_question_consumer
        if side_question_consumer is not None:
            try:
                await side_question_consumer.cancel_and_wait()
            except BaseException as exc:
                errors.append(exc)
        self._restore_agent_model_call_boundary()
        owner_cleanup_failed = False
        async with self._model_call_bind_lock:
            self._model_call_consumer = None
            self._skill_catalog_consumer = None
            self._resource_skill_catalog_facets = None
            self._side_question_consumer = None
            self._transcript_consumer = None
            self._workspace_capability_ports.invalidate()
            self._transcript_capability_ports.invalidate()
            staged_candidate = self._staged_resource_candidate
            staged_side_question = self._staged_side_question_candidate
            owner_generations = self._capability_owner_generations
            pending_components = self._pending_capability_components
            if pending_components:
                remaining_components: list[PreparedCapabilityComponent] = []
                for prepared in reversed(pending_components):
                    try:
                        await prepared.abort_uncommitted()
                    except BaseException as exc:
                        remaining_components.append(prepared)
                        errors.append(exc)
                self._pending_capability_components = tuple(
                    reversed(remaining_components)
                )
                if remaining_components:
                    owner_cleanup_failed = True
            if owner_generations:
                try:
                    await dispose_session_capability_owner_generations(
                        owner_generations
                    )
                except BaseException as exc:
                    owner_cleanup_failed = True
                    errors.append(exc)
                else:
                    self._capability_owner_generations = ()
                    self._external_consumer_captures = ()
            self._resource_capability_ports.invalidate()
            try:
                await self._retire_resource_catalog_replacements()
            except BaseException as exc:
                errors.append(exc)
            catalog_rollback_handled = False
            catalog_bootstrap = self._initial_resource_catalog_bootstrap
            if (
                not owner_cleanup_failed
                and catalog_bootstrap is not None
                and catalog_bootstrap.state in {"unprepared", "prepared"}
            ):
                catalog_rollback_handled = True
                rollback_task = asyncio.create_task(
                    catalog_bootstrap.abort(
                        dispose_graph=lambda: self._capability_graph_binder.dispose(
                            self._capability_graph_runtime
                        )
                    )
                )
                try:
                    await _await_cancellation_atomic(rollback_task)
                except BaseException as exc:
                    owner_cleanup_failed = True
                    errors.append(exc)
            if not owner_cleanup_failed:
                if not catalog_rollback_handled:
                    try:
                        cleanup_codes = await self._capability_graph_binder.dispose(
                            self._capability_graph_runtime
                        )
                        if (
                            cleanup_codes
                            and self._capability_graph_runtime.has_pending_retirements
                        ):
                            errors.append(
                                RuntimeError(
                                    "Session Capability graph cleanup remains pending: "
                                    + ", ".join(cleanup_codes)
                                )
                            )
                        if not self._capability_graph_runtime.has_pending_retirements:
                            self._mounted_resource_candidate = None
                    except BaseException as exc:
                        errors.append(exc)
                if staged_candidate is not None:
                    try:
                        staged_candidate.dispose()
                    except BaseException as exc:
                        errors.append(exc)
                    else:
                        self._staged_resource_candidate = None
                if (
                    staged_side_question is not None
                    and staged_side_question.ownership_state == "root_owned"
                ):
                    try:
                        staged_side_question.dispose()
                    except BaseException as exc:
                        errors.append(exc)
                    else:
                        self._staged_side_question_candidate = None
                elif (
                    staged_side_question is not None
                    and staged_side_question.ownership_state == "disposed"
                ):
                    self._staged_side_question_candidate = None
        if owner_cleanup_failed:
            primary = errors[0]
            for cleanup_error in errors[1:]:
                primary.add_note(
                    f"Additional Session model-call cleanup failure: {cleanup_error!r}"
                )
            raise primary
        try:
            await base_dispose()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            primary = errors[0]
            for cleanup_error in errors[1:]:
                primary.add_note(
                    f"Additional Session model-call cleanup failure: {cleanup_error!r}"
                )
            raise primary

    def _install_agent_model_call_boundary(self) -> None:
        prepare = self._model_call_runtime.prepare
        self.agent.prepare_model_call = prepare
        self._installed_agent_prepare_model_call = prepare
        requirement = self._previous_transport_requirement or bool(
            self.session_manager.persist
        )
        self.agent.model_transport_requires_prepared_request_conformance = requirement
        self._installed_transport_requirement = requirement

    def _restore_agent_model_call_boundary(self) -> None:
        installed_prepare = self._installed_agent_prepare_model_call
        if (
            installed_prepare is not None
            and self.agent.prepare_model_call is installed_prepare
        ):
            self.agent.prepare_model_call = self._previous_agent_prepare_model_call
        self._installed_agent_prepare_model_call = None
        installed_requirement = self._installed_transport_requirement
        if (
            installed_requirement is not None
            and self.agent.model_transport_requires_prepared_request_conformance
            == installed_requirement
        ):
            self.agent.model_transport_requires_prepared_request_conformance = (
                self._previous_transport_requirement
            )
        self._installed_transport_requirement = None

    async def prepare_model_call_runtime(self) -> None:
        """Commit the candidate-private graph before Session publication."""

        await self._ensure_session_graph_prepared()

    async def _ensure_session_graph_prepared(
        self,
    ) -> SessionModelCallCapabilityConsumer:
        consumer = self._model_call_consumer
        if consumer is not None:
            return consumer
        async with self._model_call_bind_lock:
            consumer = self._model_call_consumer
            if consumer is not None:
                return consumer
            if (
                self._capability_owner_generations
                or self._pending_capability_components
                or self._capability_graph_runtime.has_pending_retirements
            ):
                raise RuntimeError(
                    "Session Capability composition cleanup is pending; "
                    "the Session must retire before another prepare."
                )
            binding = self._model_call_capability_binding
            prepared_components: list[PreparedCapabilityComponent] = []
            owner_generations: tuple[StagedSessionCapabilityOwnerGeneration, ...] = ()
            resource_consumer_installed = False
            skill_catalog_consumer_installed = False
            try:
                composition_inputs = self._capability_composition_inputs
                component_host = self._capability_component_host
                if composition_inputs is not None:
                    if composition_inputs.component_requests:
                        assert component_host is not None
                    for request in composition_inputs.component_requests:
                        assert component_host is not None
                        prepared_components.append(
                            component_host.prepare_component(
                                request.resolved,
                                package=request.package,
                                owner_snapshot=request.owner_snapshot,
                                trust_snapshot=request.trust_snapshot,
                                decision_id=request.activation_decision_id,
                            )
                        )
                catalog_bootstrap = self._initial_resource_catalog_bootstrap
                if catalog_bootstrap is not None:
                    extension_host = self._extension_runner
                    assert extension_host is not None
                    await catalog_bootstrap.prepare(
                        extension_host=cast(
                            InitialExtensionGenerationHost,
                            extension_host,
                        ),
                        staged_resource_candidate=(
                            self._require_staged_resource_candidate()
                        ),
                        bindings=self._extension_runtime_binding_factory.build(),
                        extension_declaration_preflight=(
                            self._extension_declaration_preflight
                        ),
                    )
                    self._replace_initial_resource_catalog_graph_inputs()
                await self._capability_graph_binder.bind(
                    self._capability_graph_runtime,
                    self._session_capability_plan,
                    tuple(
                        item
                        for item in (
                            binding.provider_binding,
                            self._resource_capability_binding,
                            self._session_capability_binding,
                            self._workspace_capability_binding,
                            *(item.binding for item in prepared_components),
                        )
                        if item is not None
                    ),
                )
                for prepared in prepared_components:
                    prepared.commit_after_graph_publication()
                consumer = SessionModelCallCapabilityConsumer(
                    self._capability_graph_runtime.capture(
                        MODEL_INPUT_PREPARATION_REQUIREMENT
                    )
                )
                resource_consumer = SessionResourceCompositionCapabilityConsumer(
                    self._capability_graph_runtime.capture(
                        SESSION_RESOURCE_COMPOSITION_REQUIREMENT
                    )
                )
                if catalog_bootstrap is not None:
                    skill_facets = self._capability_graph_runtime.capture(
                        RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT
                    )
                    skill_catalog = ResourceSkillStatusCatalogCapabilityConsumer(
                        skill_facets
                    )
                    self._resource_skill_catalog_facets = skill_facets
                    self._skill_catalog_consumer = SkillCatalogConsumer(skill_catalog)
                    skill_catalog_consumer_installed = True
                side_question = SessionSideQuestionCapabilityConsumer(
                    self._capability_graph_runtime.capture(
                        SESSION_SIDE_QUESTION_REQUIREMENT
                    )
                )
                transcript_consumer = SessionTranscriptCapabilityConsumer(
                    self._capability_graph_runtime.capture(
                        SESSION_TRANSCRIPT_REQUIREMENT
                    )
                )
                workspace_tools = SessionWorkspaceToolCapabilityConsumer(
                    self._capability_graph_runtime.capture(
                        SESSION_WORKSPACE_TOOL_REQUIREMENT
                    )
                )
                workspace_process = SessionWorkspaceProcessCapabilityConsumer(
                    self._capability_graph_runtime.capture(
                        SESSION_WORKSPACE_PROCESS_REQUIREMENT
                    )
                )
                self._resource_capability_ports.install(
                    consumer=resource_consumer,
                )
                resource_consumer_installed = True
                external_captures: tuple[SessionCapabilityConsumerCapture, ...] = ()
                if composition_inputs is not None:
                    external_captures = tuple(
                        SessionCapabilityConsumerCapture(
                            entry=entry,
                            facets=self._capability_graph_runtime.capture(
                                entry.requirement
                            ),
                        )
                        for entry in composition_inputs.product_composition.consumer_requirements.satisfied_entries
                    )
                    try:
                        owner_generations = await stage_session_capability_owner_generations(
                            admissions=(
                                composition_inputs.product_composition.catalog_admissions
                            ),
                            bindings=self._capability_owner_generation_bindings,
                            captures=external_captures,
                        )
                    except SessionCapabilityOwnerGenerationStagingError as exc:
                        owner_generations = exc.pending_generations
                        raise
                if catalog_bootstrap is not None:
                    retirement = catalog_bootstrap.publish(
                        InitialSessionResourcePublication(
                            capture=self._capture_initial_resource_publication,
                            commit=self._commit_initial_resource_publication,
                            restore=self._restore_initial_resource_publication,
                        )
                    )
                    retirement_reports = await retirement.retire()
                    if any(report.has_failures for report in retirement_reports):
                        raise RuntimeError(
                            "initial Extension generation retirement remains pending"
                        )
            except BaseException as error:
                owner_cleanup_failed = False
                if owner_generations:
                    try:
                        await dispose_session_capability_owner_generations(
                            owner_generations
                        )
                    except BaseException as cleanup_error:
                        owner_cleanup_failed = True
                        self._capability_owner_generations = owner_generations
                        error.add_note(
                            "Session owner generation rollback also failed: "
                            f"{cleanup_error!r}"
                        )
                if resource_consumer_installed:
                    self._resource_capability_ports.invalidate()
                if skill_catalog_consumer_installed:
                    self._skill_catalog_consumer = None
                    self._resource_skill_catalog_facets = None
                for prepared in reversed(prepared_components):
                    try:
                        await prepared.abort_uncommitted()
                    except BaseException as cleanup_error:
                        self._pending_capability_components = (
                            prepared,
                            *self._pending_capability_components,
                        )
                        error.add_note(
                            "Prepared component cancellation also failed: "
                            f"{cleanup_error!r}"
                        )
                catalog_rollback_attempted = False
                catalog_bootstrap = self._initial_resource_catalog_bootstrap
                if (
                    catalog_bootstrap is not None
                    and catalog_bootstrap.state != "published"
                ):
                    catalog_rollback_attempted = True
                    rollback_task = asyncio.create_task(
                        catalog_bootstrap.abort(
                            dispose_graph=lambda: self._capability_graph_binder.dispose(
                                self._capability_graph_runtime
                            )
                        )
                    )
                    try:
                        await _await_cancellation_atomic(rollback_task)
                    except BaseException as cleanup_error:
                        error.add_note(
                            "Initial Resource Catalog rollback also failed: "
                            f"{cleanup_error!r}"
                        )
                if (
                    not owner_cleanup_failed
                    and not catalog_rollback_attempted
                    and self._capability_graph_runtime.snapshot is not None
                    and not self._capability_graph_runtime.is_closed
                ):
                    cleanup_task = asyncio.create_task(
                        self._capability_graph_binder.dispose(
                            self._capability_graph_runtime
                        )
                    )
                    try:
                        cleanup_codes = await _await_cancellation_atomic(cleanup_task)
                        if (
                            cleanup_codes
                            and self._capability_graph_runtime.has_pending_retirements
                        ):
                            error.add_note(
                                "Session Capability graph cleanup remains pending: "
                                + ", ".join(cleanup_codes)
                            )
                    except BaseException as cleanup_error:
                        error.add_note(
                            "Session Capability graph cleanup also failed: "
                            f"{cleanup_error!r}"
                        )
                staged_candidate = self._staged_resource_candidate
                if (
                    staged_candidate is not None
                    and staged_candidate.ownership_state == "root_owned"
                ):
                    try:
                        staged_candidate.dispose()
                    except BaseException as cleanup_error:
                        error.add_note(
                            "staged resource candidate cleanup also failed: "
                            f"{cleanup_error!r}"
                        )
                    else:
                        self._staged_resource_candidate = None
                staged_side_question = self._staged_side_question_candidate
                if (
                    staged_side_question is not None
                    and staged_side_question.ownership_state == "root_owned"
                ):
                    try:
                        staged_side_question.dispose()
                    except BaseException as cleanup_error:
                        error.add_note(
                            "staged side-question candidate cleanup also failed: "
                            f"{cleanup_error!r}"
                        )
                    else:
                        self._staged_side_question_candidate = None
                staged_transcript = self._staged_transcript_candidate
                if staged_transcript.ownership_state == "root_owned":
                    try:
                        await staged_transcript.dispose_root_owned()
                    except BaseException as cleanup_error:
                        error.add_note(
                            "staged transcript candidate cleanup also failed: "
                            f"{cleanup_error!r}"
                        )
                raise
            staged_candidate = self._staged_resource_candidate
            if catalog_bootstrap is not None:
                if (
                    staged_candidate is None
                    or staged_candidate.ownership_state != "graph_owned"
                ):
                    raise RuntimeError(
                        "Resource Catalog graph did not retain its mounted candidate"
                    )
                self._mounted_resource_candidate = staged_candidate
            if (
                staged_candidate is not None
                and staged_candidate.ownership_state == "root_owned"
            ):
                # Graph-wide or node reuse intentionally skipped Provider.create().
                staged_candidate.dispose()
            self._staged_resource_candidate = None
            staged_side_question = self._staged_side_question_candidate
            if (
                staged_side_question is not None
                and staged_side_question.ownership_state == "root_owned"
            ):
                # Graph-wide or node reuse intentionally skipped Provider.create().
                staged_side_question.dispose()
            self._staged_side_question_candidate = None
            if self._staged_transcript_candidate.ownership_state == "root_owned":
                # Graph reuse rejected the freshly supplied transcript candidate.
                await self._staged_transcript_candidate.dispose_root_owned()
            self._workspace_capability_ports.install(
                tools=workspace_tools,
                process=workspace_process,
            )
            self._transcript_capability_ports.install(transcript_consumer)
            self._external_consumer_captures = external_captures
            self._capability_owner_generations = owner_generations
            self._transcript_consumer = transcript_consumer
            self._side_question_consumer = side_question
            self._model_call_consumer = consumer
            return consumer

    def _require_staged_resource_candidate(
        self,
    ) -> StagedResourceCompositionCandidate:
        candidate = self._staged_resource_candidate
        if candidate is None:
            raise RuntimeError("Session Resource candidate is not available")
        return candidate

    def _build_resource_capability_provider_binding(
        self,
        *,
        enable_skill_catalog_v4: bool = False,
    ) -> CapabilityBundleProviderBinding:
        """Freeze the current Resource candidate through one mount-owner seam."""

        candidate = self._require_staged_resource_candidate()
        return resources_capability_provider_binding(
            profile=candidate.profile,
            scope_instance_id=self._capability_graph_runtime.runtime_id,
            staged_candidate=candidate,
            enable_skill_catalog_v4=enable_skill_catalog_v4,
        )

    def _replace_initial_resource_catalog_graph_inputs(self) -> None:
        resource_binding = self._build_resource_capability_provider_binding(
            enable_skill_catalog_v4=True
        )
        if resource_binding.provider.implementation_version != 4:
            raise RuntimeError(
                "initial Resource Catalog did not select the v4 Resources Provider"
            )
        composition_inputs = self._capability_composition_inputs
        external_definitions = (
            tuple(
                item.definition
                for item in composition_inputs.resolved_providers.entries
            )
            if composition_inputs is not None
            else ()
        )
        external_providers = (
            composition_inputs.resolved_providers.providers
            if composition_inputs is not None
            else ()
        )
        workspace_binding = self._workspace_capability_binding
        definitions = (
            MODEL_INPUT_CAPABILITY_DEFINITION,
            RESOURCES_CAPABILITY_DEFINITION_V4,
            SESSION_CAPABILITY_DEFINITION,
            *((WORKSPACE_CAPABILITY_DEFINITION,) if workspace_binding else ()),
            *external_definitions,
        )
        providers = (
            self._model_call_capability_binding.provider_binding.provider,
            resource_binding.provider,
            self._session_capability_binding.provider,
            *((workspace_binding.provider,) if workspace_binding else ()),
            *external_providers,
        )
        if composition_inputs is not None:
            composition_inputs.product_composition.consumer_requirements.validate_provider_metadata(
                providers
            )
        self._resource_capability_binding = resource_binding
        self._session_capability_plan = RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id=self._capability_graph_runtime.product_id,
                roots=self._session_capability_plan.roots,
                definitions=definitions,
                providers=providers,
            )
        )

    def list_skill_statuses(self) -> tuple[SkillCatalogStatusSummary, ...]:
        """Return exact-v4 all-Skill status records for Product presentation."""

        consumer = self._skill_catalog_consumer
        if consumer is None:
            raise RuntimeError("Session Skill Catalog v4 capture is not available")
        return consumer.list_skill_statuses()

    def _effective_skill_summaries(
        self,
    ) -> tuple[SkillCatalogSummary, ...] | None:
        consumer = self._skill_catalog_consumer
        if consumer is not None:
            return consumer.list_effective_skills()
        # A Catalog-intended Session must never enumerate the compatibility
        # Bundle while exact-v4 is still being prepared.  An empty projection
        # keeps construction body-free; publication rebuilds the view.
        if self._initial_resource_catalog_bootstrap is not None:
            return ()
        return None

    def _skill_body_loader(self) -> SkillBodyLoader | None:
        if self._initial_resource_catalog_bootstrap is None:
            return None
        return self._load_effective_skill_body

    async def _load_effective_skill_body(
        self,
        name: str,
    ) -> LoadedSkillBody | None:
        consumer = self._skill_catalog_consumer
        if consumer is None:
            raise RuntimeError("Session Skill Catalog v4 capture is not available")
        summary = consumer.get_effective_skill(name)
        if summary is None:
            return None
        return await consumer.load(consumer.load_handle(summary))

    async def _refresh_resource_catalog(
        self,
        reason: str,
    ) -> ResourceBundle | None:
        """Prepare and atomically publish one exact next Catalog generation."""

        del reason
        factory = self._resource_catalog_refresh_bootstrap_factory
        if factory is None:
            raise RuntimeError("Session Resource Catalog refresh is not configured")
        await self._ensure_session_graph_prepared()
        await self._retire_resource_catalog_replacements()
        mounted = self._mounted_resource_candidate
        if mounted is None or mounted.ownership_state != "graph_owned":
            raise RuntimeError("Session Resource Catalog candidate is not mounted")
        current_generation = getattr(
            self._resource_catalog_snapshot,
            "catalog_generation",
            None,
        )
        if (
            isinstance(current_generation, bool)
            or not isinstance(current_generation, int)
            or current_generation < 1
        ):
            raise RuntimeError("Session Resource Catalog generation is invalid")
        next_generation = current_generation + 1
        bootstrap = factory(next_generation)
        if not isinstance(bootstrap, InitialSessionResourceCatalogBootstrap):
            raise TypeError(
                "Resource Catalog refresh factory returned an invalid value"
            )
        if (
            bootstrap.product_id != self._capability_graph_runtime.product_id
            or bootstrap.scope_id != self._capability_graph_runtime.runtime_id
            or bootstrap.catalog_generation != next_generation
        ):
            bootstrap.close_unprepared()
            raise ValueError("Resource Catalog refresh bootstrap belongs elsewhere")

        successor = mounted.stage_refresh_successor()
        replacement = None
        try:
            extension_host = self._extension_runner
            if extension_host is None:
                raise RuntimeError(
                    "Resource Catalog refresh requires an Extension generation host"
                )
            await bootstrap.prepare(
                extension_host=cast(InitialExtensionGenerationHost, extension_host),
                staged_resource_candidate=successor,
                bindings=self._extension_runtime_binding_factory.build(),
                extension_declaration_preflight=(self._extension_declaration_preflight),
            )
            successor._claim_refresh_successor()

            def capture() -> object:
                return (
                    self._resource_catalog_snapshot,
                    self._resource_catalog_projection,
                    self.resource_bundle,
                    self._skill_catalog_consumer,
                )

            def commit(
                catalog: object,
                projection: object,
                bundle: ResourceBundle,
            ) -> None:
                nonlocal replacement
                replacement = mounted.begin_owner_generation_replacement(successor)
                facets = self._resource_skill_catalog_facets
                if facets is None:
                    raise RuntimeError(
                        "Session Skill Catalog v4 facets are not available"
                    )
                skill_catalog = ResourceSkillStatusCatalogCapabilityConsumer(facets)
                self._resource_catalog_snapshot = catalog
                self._resource_catalog_projection = projection
                self._skill_catalog_consumer = SkillCatalogConsumer(skill_catalog)
                self._adopt_resource_loader_catalog_projection(projection)
                self._set_resource_bundle(bundle)
                self._rebuild_prompt_and_tools_view()

            def restore(previous: object) -> None:
                if not isinstance(previous, tuple) or len(previous) != 4:
                    raise TypeError("Resource Catalog refresh snapshot is invalid")
                catalog, projection, bundle, skill_consumer = previous
                rollback_error: BaseException | None = None
                if replacement is not None:
                    try:
                        replacement.rollback()
                    except BaseException as exc:
                        rollback_error = exc
                try:
                    if bundle is not None and not isinstance(bundle, ResourceBundle):
                        raise TypeError(
                            "Resource Catalog refresh snapshot Bundle is invalid"
                        )
                    if skill_consumer is not None and not isinstance(
                        skill_consumer,
                        SkillCatalogConsumer,
                    ):
                        raise TypeError(
                            "Resource Catalog refresh Skill Consumer is invalid"
                        )
                    self._resource_catalog_snapshot = catalog
                    self._resource_catalog_projection = projection
                    self._skill_catalog_consumer = skill_consumer
                    self._restore_resource_loader_catalog_projection(projection)
                    self._set_resource_bundle(bundle)
                    self._rebuild_prompt_and_tools_view()
                except BaseException as restoration_error:
                    if rollback_error is not None:
                        restoration_error.add_note(
                            "Resource generation rollback also failed: "
                            f"{rollback_error!r}"
                        )
                    raise
                if rollback_error is not None:
                    raise rollback_error

            retirement = bootstrap.publish(
                InitialSessionResourcePublication(
                    capture=capture,
                    commit=commit,
                    restore=restore,
                )
            )
            if replacement is None:
                raise RuntimeError(
                    "Resource Catalog refresh published without replacing its owner"
                )
            replacement.commit()
        except BaseException as publication_error:
            cleanup_task = asyncio.create_task(
                self._abort_resource_catalog_refresh(
                    bootstrap=bootstrap,
                    successor=successor,
                    mounted=mounted,
                )
            )
            try:
                await _await_cancellation_atomic(cleanup_task)
            except BaseException as cleanup_error:
                publication_error.add_note(
                    f"Resource Catalog refresh rollback also failed: {cleanup_error!r}"
                )
            raise

        self._pending_resource_catalog_retirements.append(retirement)
        await self._retire_resource_catalog_replacements()
        return self.resource_bundle

    async def _abort_resource_catalog_refresh(
        self,
        *,
        bootstrap: InitialSessionResourceCatalogBootstrap,
        successor: StagedResourceCompositionCandidate,
        mounted: StagedResourceCompositionCandidate,
    ) -> None:
        if successor.ownership_state == "disposed":
            codes = await mounted.retire_replaced_owner_generations()
            if codes:
                raise ResourceCatalogRefreshRetirementError(
                    "Resource Catalog rollback retirement remains pending: "
                    + ", ".join(codes)
                )
            await bootstrap.abort()
            return
        if successor.ownership_state == "root_owned":
            try:
                await bootstrap.abort()
            finally:
                if successor.has_prepared_owner_generation:
                    await successor.dispose_root_owned()
                else:
                    successor.dispose()
            return
        await bootstrap.abort(dispose_graph=successor.dispose_refresh_successor)

    async def _retire_resource_catalog_replacements(self) -> None:
        mounted = self._mounted_resource_candidate
        if mounted is not None:
            codes = await mounted.retire_replaced_owner_generations()
            if codes:
                raise ResourceCatalogRefreshRetirementError(
                    "Resource Catalog generation retirement remains pending: "
                    + ", ".join(codes)
                )
        pending = tuple(self._pending_resource_catalog_retirements)
        remaining: list[ExtensionGenerationRetirementPort] = []
        for index, retirement in enumerate(pending):
            try:
                reports = await retirement.retire()
            except BaseException:
                remaining.append(retirement)
                self._pending_resource_catalog_retirements = remaining + list(
                    pending[index + 1 :]
                )
                raise
            if any(report.has_failures for report in reports):
                remaining.append(retirement)
        self._pending_resource_catalog_retirements = remaining
        if remaining:
            raise ResourceCatalogRefreshRetirementError(
                "Extension generation retirement remains pending"
            )

    def _capture_initial_resource_publication(self) -> object:
        return (
            self._resource_catalog_snapshot,
            self._resource_catalog_projection,
            self.resource_bundle,
        )

    def _commit_initial_resource_publication(
        self,
        catalog: object,
        projection: object,
        bundle: ResourceBundle,
    ) -> None:
        self._resource_catalog_snapshot = catalog
        self._resource_catalog_projection = projection
        self._adopt_resource_loader_catalog_projection(projection)
        self._set_resource_bundle(bundle)
        self._rebuild_prompt_and_tools_view()

    def _restore_initial_resource_publication(self, previous: object) -> None:
        if not isinstance(previous, tuple) or len(previous) != 3:
            raise TypeError("initial Resource publication snapshot is invalid")
        catalog, projection, bundle = previous
        if bundle is not None and not isinstance(bundle, ResourceBundle):
            raise TypeError("initial Resource publication Bundle is invalid")
        self._resource_catalog_snapshot = catalog
        self._resource_catalog_projection = projection
        self._restore_resource_loader_catalog_projection(projection)
        self._set_resource_bundle(bundle)
        self._rebuild_prompt_and_tools_view()

    def _adopt_resource_loader_catalog_projection(self, projection: object) -> None:
        loader = self._resource_loader
        if loader is None:
            return
        if not isinstance(projection, ResourceCatalogProjection):
            raise TypeError("Session Resource Catalog projection is invalid")
        loader.adopt_catalog_projection(projection)

    def _restore_resource_loader_catalog_projection(self, projection: object) -> None:
        loader = self._resource_loader
        if loader is None:
            return
        if projection is not None and not isinstance(
            projection,
            ResourceCatalogProjection,
        ):
            raise TypeError("Session Resource Catalog projection is invalid")
        loader.restore_catalog_projection(projection)

    def evaluate_capability_composition_change(
        self,
        candidate: SessionCapabilityCompositionInputs | None,
    ) -> Literal["no_change", "restart_required"]:
        """A live sealed Session never hot-swaps its pinned plugin graph."""

        current = self._capability_composition_inputs
        if current is None or candidate is None:
            return "no_change" if current is candidate else "restart_required"
        return current.compare(candidate)

    def _current_profile_fingerprint(self) -> str:
        return runtime_profile_fingerprint(self.capability_profile.snapshot())

    def _source_publication_reference(
        self,
    ) -> ScopedSourcePublicationReference:
        extension_runtime = self._extension_runner
        source_runtime_id = getattr(extension_runtime, "source_runtime_id", None)
        extension_generation = getattr(extension_runtime, "generation", None)
        if (
            not isinstance(source_runtime_id, str)
            or not source_runtime_id
            or not isinstance(extension_generation, int)
            or isinstance(extension_generation, bool)
        ):
            source_runtime_id = self._capability_graph_runtime.runtime_id
            extension_generation = None
        composition = getattr(self, "_composition", None)
        resource_refresh = getattr(composition, "resource_refresh_runtime", None)
        resource_revision = getattr(
            resource_refresh,
            "resource_revision",
            1 if self.resource_bundle is not None else 0,
        )
        catalog_generation = getattr(
            self._resource_catalog_snapshot,
            "catalog_generation",
            None,
        )
        if (
            isinstance(catalog_generation, int)
            and not isinstance(catalog_generation, bool)
            and catalog_generation >= 1
        ):
            resource_revision = catalog_generation
        return ScopedSourcePublicationReference(
            schema_version=1,
            owner_capability_id=RESOURCES_CAPABILITY_DEFINITION.capability_id,
            source_runtime_id=source_runtime_id,
            extension_generation=extension_generation,
            declaration_revision=extension_generation,
            resource_revision=resource_revision,
        )

    def _is_current_model_call_session(self) -> bool:
        runtime_host = self._extension_bridge.runtime_host
        if runtime_host is None:
            return True
        return getattr(runtime_host, "current_session", None) is self

    def _finalize_after_session_shutdown(self) -> None:
        self.cancel_side_question()
        self._close_session_approvals()
        if self._extension_runner is not None:
            self._invalidate_extension_contexts(
                "Extension context is stale after session replacement or shutdown."
            )
        self.footer_data_provider.dispose()
        self._capability_profile_provider = None

    def _abort_from_extension(self) -> None:
        self.abort()

    def _register_provider_from_extension(self, name: str, config: object) -> None:
        self._extension_provider_controller.register_provider(name, config)
        self._sync_footer_available_provider_count()

    def _bind_provider_from_extension(
        self,
        name: str,
        config: object,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        lease = self._extension_provider_controller.bind_provider(name, config, owner)

        async def dispose_provider() -> RegistrationDisposalResult:
            result = await lease.dispose()
            self._sync_footer_available_provider_count()
            return result

        def rollback_provider() -> RegistrationDisposalResult:
            result = lease.rollback_registration()
            self._sync_footer_available_provider_count()
            return result

        self._sync_footer_available_provider_count()
        return RegistrationLease(
            owner=lease.owner,
            identity=lease.identity,
            dispose=dispose_provider,
            rollback=rollback_provider,
        )

    def _stage_provider_from_extension(
        self,
        name: str,
        config: object,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        lease = self._extension_provider_controller.stage_provider(
            name,
            config,
            owner,
        )

        async def dispose_provider() -> RegistrationDisposalResult:
            result = await lease.dispose()
            self._sync_footer_available_provider_count()
            return result

        def activate_provider() -> None:
            lease.activate()
            self._sync_footer_available_provider_count()

        def deactivate_provider() -> None:
            lease.deactivate()
            self._sync_footer_available_provider_count()

        def rollback_provider() -> RegistrationDisposalResult:
            result = lease.rollback_registration()
            self._sync_footer_available_provider_count()
            return result

        return RegistrationLease(
            owner=lease.owner,
            identity=lease.identity,
            dispose=dispose_provider,
            activate=activate_provider,
            deactivate=deactivate_provider,
            rollback=rollback_provider,
        )

    def _bind_provider_removal_from_extension(
        self,
        name: str,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        lease = self._extension_provider_controller.bind_provider_removal(name, owner)

        async def dispose_provider() -> RegistrationDisposalResult:
            result = await lease.dispose()
            self._sync_footer_available_provider_count()
            return result

        def rollback_provider() -> RegistrationDisposalResult:
            result = lease.rollback_registration()
            self._sync_footer_available_provider_count()
            return result

        self._sync_footer_available_provider_count()
        return RegistrationLease(
            owner=lease.owner,
            identity=lease.identity,
            dispose=dispose_provider,
            rollback=rollback_provider,
        )

    def _stage_provider_removal_from_extension(
        self,
        name: str,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        lease = self._extension_provider_controller.stage_provider_removal(name, owner)

        async def dispose_provider() -> RegistrationDisposalResult:
            result = await lease.dispose()
            self._sync_footer_available_provider_count()
            return result

        def activate_provider() -> None:
            lease.activate()
            self._sync_footer_available_provider_count()

        def deactivate_provider() -> None:
            lease.deactivate()
            self._sync_footer_available_provider_count()

        def rollback_provider() -> RegistrationDisposalResult:
            result = lease.rollback_registration()
            self._sync_footer_available_provider_count()
            return result

        return RegistrationLease(
            owner=lease.owner,
            identity=lease.identity,
            dispose=dispose_provider,
            activate=activate_provider,
            deactivate=deactivate_provider,
            rollback=rollback_provider,
        )

    def _get_extension_model_selection(self) -> ModelSelection | None:
        return cast(ModelSelection | None, self.get_model_selection())

    def _unregister_provider_from_extension(self, name: str) -> None:
        self._extension_provider_controller.unregister_provider(name)
        self._sync_footer_available_provider_count()

    def _set_extension_status_from_extension(self, key: str, text: str | None) -> None:
        self.footer_data_provider.set_extension_status(key, text)

    def _sync_footer_available_provider_count(self) -> None:
        providers = {
            selection.provider
            for selection in self._composition.selection_runtime.get_available_models()
            if isinstance(selection.provider, str)
        }
        self.footer_data_provider.set_available_provider_count(len(providers))

    def _create_replaced_session_context(
        self, session: object | None
    ) -> ReplacedSessionContext:
        if not isinstance(session, AgentProductSession):
            raise RuntimeError(
                "Session replacement callback requires a valid Agent session."
            )
        return cast(
            ReplacedSessionContext,
            self._extension_replacement_controller.create_context(session),
        )

    def _branch_summary_runner(
        self,
        *,
        custom_instructions: str | None,
        replace_instructions: bool,
    ) -> Callable[
        [Sequence[object], CancellationSignal], Awaitable[BranchSummaryOutput]
    ]:
        async def run(
            entries: Sequence[object], signal: CancellationSignal
        ) -> BranchSummaryOutput:
            return await self._execute_product_branch_summary(
                entries,
                model=self.agent.model,
                signal=signal,
                custom_instructions=custom_instructions,
                replace_instructions=replace_instructions,
                prepare_model_call=self.agent.prepare_model_call,
            )

        return run

    async def _before_product_compaction(
        self,
        request: CompactionHookRequest,
    ) -> CompactionHookDecision | None:
        extension_runner = self._extension_runner
        if extension_runner is None:
            return None
        decision = await extension_runner.before_session_compact(
            SessionBeforeCompactEvent(
                reason=request.reason,
                cwd=str(self.session_manager.get_cwd()),
                custom_instructions=request.custom_instructions,
            )
        )
        if decision is not None and decision.cancel:
            self._sync_extension_diagnostics(phase="runtime")
            return CompactionHookDecision(cancel=True)
        result = decision.compaction if decision is not None else None
        if result is not None and not isinstance(result, CompactionResult):
            raise TypeError(
                "Extension compaction hooks must return a CompactionResult."
            )
        return CompactionHookDecision(result=result) if result is not None else None

    async def _after_product_compaction(
        self,
        result: CompactionResult,
        record_id: str,
        from_hook: bool,
    ) -> None:
        extension_runner = self._extension_runner
        if extension_runner is None:
            return
        await extension_runner.emit_agent_event(
            {
                "type": "session_compact",
                "compaction": result,
                "compaction_entry": self.session_manager.get_entry(record_id),
                "from_extension": from_hook,
            },
            cwd=self.session_manager.get_cwd(),
        )


def _same_registration_identity(
    left: RegistrationInventoryEntry,
    right: RegistrationInventoryEntry,
) -> bool:
    return (
        left.registration_id,
        left.surface,
        left.public_key,
        left.owner_kind,
        left.owner_id,
        left.runtime_id,
        left.owner_generation,
    ) == (
        right.registration_id,
        right.surface,
        right.public_key,
        right.owner_kind,
        right.owner_id,
        right.runtime_id,
        right.owner_generation,
    )


__all__ = ["AgentProductSession"]
