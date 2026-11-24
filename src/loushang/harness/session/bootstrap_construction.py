"""Agent and Product session construction contracts."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, cast

from loushang.ai.model import (
    Model,
    available_thinking_levels,
    validate_reasoning_request,
)
from loushang.ai.model.selection import ModelSelection
from loushang.harness.bootstrap import (
    StandardExtensionRuntime,
    register_resource_extension_tools,
)
from loushang.harness.capabilities import StagedResourceCompositionCandidate
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.packs import CapabilityPackComposer
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.capabilities.prompt_assembly import assemble_prompt
from loushang.harness.capabilities.tools import (
    ToolSelection,
    normalize_allowed_tool_names,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.package_product._selected_plugin_revisions import (
    ProductAdmissionFailure,
    ProductBaseSelectionEvidence,
    ProductCatalogSelection,
    capture_catalog_base_selection,
    capture_selected_manifests,
    observe_requested_plugins,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeFactoryPort,
    PackageProductRuntimeRequestV1,
    activate_package_product_runtime,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.activation import (
    ResourceActivation,
    SkillActivationRuntime,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.catalog_diagnostics import (
    record_package_lockfile_diagnostics,
)
from loushang.harness.resources.packages.materializer import (
    GitPackageMaterializerBackend,
    PackageMaterializer,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleInventoryPort,
    PackageProductLifecycleMode,
    PackageProductLifecycleOperationPort,
)
from loushang.harness.resources.packages.roots import SelectedPluginPackageInput
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import ResolvedRuntimeProfile
from loushang.harness.runtime.registration import RegistrationLease
from loushang.harness.session._cleanup import (
    CleanupStep,
    ExplicitTemporaryDirectory,
    get_session_construction_cleanup,
    retain_session_construction_failure,
    run_cleanup_steps,
)
from loushang.harness.session.bootstrap_configuration import (
    CatalogBootstrapProjectionPreparer,
    ExtensionFlagValues,
    SourceIdentityCheck,
    StandardAgentSessionConfigurationRequest,
    StandardAgentSessionConfigurationResult,
    StandardAgentSessionConfigurationRuntime,
)
from loushang.harness.session.bootstrap_services import BootstrapServices
from loushang.harness.session.bootstrap_utils import (
    NoToolsMode,
    normalize_no_tools,
    resolve_base_system_prompt,
    resolve_initial_active_tool_names,
)
from loushang.harness.session.extension_profiles import (
    SessionExtensionProfileResolution,
)
from loushang.harness.session.legacy_side_question import LegacySideQuestionBinding
from loushang.harness.session.model_resolution import (
    resolve_session_model,
    scoped_models_from_patterns,
)
from loushang.harness.session.plugin_lifecycle._composition_cleanup import (
    share_startup_cleanup,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

if TYPE_CHECKING:
    from loushang.harness.resource_catalog.product_inputs import (
        InitialResourceCatalogProductAdapter,
    )
    from loushang.harness.resource_catalog.session_bootstrap import (
        InitialSessionResourceCatalogBootstrap,
    )
    from loushang.harness.session.agent_product import AgentProductSession


class _RootOwnedResourceHandles(Protocol):
    skill_activation: SkillActivationRuntime
    prompt_section_composer: PromptSectionComposer
    tool_pack_composer: CapabilityPackComposer

    def activate_resources(self, bundle: ResourceBundle) -> ResourceActivation: ...

    def dispose(self) -> None: ...


AgentT = TypeVar("AgentT")
SessionT = TypeVar("SessionT")
BundleT = TypeVar("BundleT")
RegistryT = TypeVar("RegistryT")
StandardExtensionT = TypeVar("StandardExtensionT", bound=StandardExtensionRuntime)
ConstructionDiagnosticT = TypeVar("ConstructionDiagnosticT")
PackageProductCatalogBootstrapProjectionPreparer = Callable[
    [ResourceLoader, Path, PackageProductRuntimeBindingV1], ResourceBundle
]


def _record_drafts(
    diagnostics_service: DiagnosticsService,
    diagnostics: Sequence[DiagnosticDraft],
    *,
    session_id: str,
) -> None:
    diagnostics_service.record_drafts(
        diagnostics,
        phase="resource_loading",
        source="bootstrap",
        session_id=session_id,
    )


def _register_workspace_tool(
    registry: WorkspaceToolRegistry,
    tool: ToolDefinition,
) -> None:
    registry.register_tool(tool)


@dataclass(frozen=True)
class AgentBootstrapRequest:
    """Neutral values needed to construct one Agent instance."""

    session_id: str
    system_prompt: str
    thinking_level: object
    model: object | None
    convert_to_llm: Callable[..., object]
    steering_mode: object
    follow_up_mode: object
    thinking_budgets: object
    max_retry_delay_ms: int | None
    stream_fn: Callable[..., object] | None = None
    restore_history: bool = False


class AgentBootstrapRuntime(Generic[AgentT, SessionT]):
    """Construct an Agent, then let the Product create its session facade."""

    def construct(
        self,
        request: AgentBootstrapRequest,
        *,
        agent_factory: Callable[..., AgentT],
        session_factory: Callable[[AgentT], SessionT],
    ) -> SessionT:
        initial_state: dict[str, object] = {
            "system_prompt": request.system_prompt,
            "thinking_level": request.thinking_level,
            "tools": [],
        }
        if request.model is not None:
            initial_state["model"] = request.model

        agent_kwargs: dict[str, object] = {
            "initial_state": initial_state,
            "session_id": request.session_id,
            "convert_to_llm": request.convert_to_llm,
            "steering_mode": request.steering_mode,
            "follow_up_mode": request.follow_up_mode,
            "thinking_budgets": request.thinking_budgets,
            "max_retry_delay_ms": request.max_retry_delay_ms,
        }
        if request.stream_fn is not None:
            agent_kwargs["stream_fn"] = request.stream_fn

        if request.restore_history:
            from loushang.ai.options import CallOptions

            # An interrupted transcript can have unmatched tool calls.
            agent_kwargs["call_options"] = CallOptions(pairing_mode="repair")

        agent = agent_factory(**agent_kwargs)
        setattr(agent, "session_id", request.session_id)
        return session_factory(agent)


@dataclass(frozen=True)
class AgentSessionConstructionRequest(Generic[BundleT, RegistryT]):
    """Inputs for the shared tool and Agent construction pipeline."""

    session_id: str
    base_prompt: str
    resolved_prompt: str
    thinking_level: object
    model: object | None
    convert_to_llm: Callable[..., object]
    steering_mode: object
    follow_up_mode: object
    thinking_budgets: object
    max_retry_delay_ms: int | None
    stream_fn: Callable[..., object] | None
    resource_bundle: BundleT
    tools: Sequence[ToolDefinition] | None
    tool_registry: RegistryT | None
    allowed_tool_names: Sequence[str] | ToolSelection | None
    active_tool_names: Sequence[str] | None
    no_tools_mode: NoToolsMode | None
    restore_history: bool = False


class AgentSessionConstructionRuntime(
    Generic[AgentT, SessionT, BundleT, RegistryT, ConstructionDiagnosticT]
):
    """Compose shared tool registration and Agent construction steps."""

    def construct(
        self,
        request: AgentSessionConstructionRequest[BundleT, RegistryT],
        *,
        agent_factory: Callable[..., AgentT],
        register_extension_tools: Callable[
            [BundleT, RegistryT | None],
            tuple[
                BundleT,
                RegistryT | None,
                Sequence[ConstructionDiagnosticT],
            ],
        ],
        record_extension_diagnostics: Callable[
            [Sequence[ConstructionDiagnosticT]],
            None,
        ],
        registry_factory: Callable[[], RegistryT],
        register_tool: Callable[[RegistryT, ToolDefinition], None],
        session_factory: Callable[
            [
                AgentT,
                BundleT,
                RegistryT | None,
                list[str] | None,
                str,
                NoToolsMode | None,
            ],
            SessionT,
        ],
    ) -> SessionT:
        resolved_registry = request.tool_registry
        allowed_tool_names = normalize_allowed_tool_names(request.allowed_tool_names)
        if request.no_tools_mode == "all":
            allowed_tool_names = frozenset()
        if resolved_registry is None and request.tools:
            new_registry = registry_factory()
            for tool in request.tools:
                register_tool(new_registry, tool)
            resolved_registry = new_registry

        resource_bundle, resolved_registry, extension_diagnostics = (
            register_extension_tools(request.resource_bundle, resolved_registry)
        )
        record_extension_diagnostics(extension_diagnostics)
        if request.no_tools_mode == "all" and resolved_registry is None:
            resolved_registry = registry_factory()
        resolved_active_tool_names = resolve_initial_active_tool_names(
            active_tool_names=(
                list(request.active_tool_names)
                if request.active_tool_names is not None
                else None
            ),
            allowed_tool_names=allowed_tool_names,
            no_tools_mode=request.no_tools_mode,
            tool_registry=resolved_registry,
        )

        return AgentBootstrapRuntime[AgentT, SessionT]().construct(
            AgentBootstrapRequest(
                session_id=request.session_id,
                system_prompt=request.resolved_prompt,
                thinking_level=request.thinking_level,
                model=request.model,
                convert_to_llm=request.convert_to_llm,
                steering_mode=request.steering_mode,
                follow_up_mode=request.follow_up_mode,
                thinking_budgets=request.thinking_budgets,
                max_retry_delay_ms=request.max_retry_delay_ms,
                stream_fn=request.stream_fn,
                restore_history=request.restore_history,
            ),
            agent_factory=agent_factory,
            session_factory=lambda agent: session_factory(
                agent,
                resource_bundle,
                resolved_registry,
                resolved_active_tool_names,
                request.base_prompt,
                request.no_tools_mode,
            ),
        )


@dataclass(frozen=True)
class AgentProductConstructionPorts(Generic[StandardExtensionT]):
    """Product callbacks around the standard configured Agent construction."""

    activate_resources: Callable[[ResourceBundle], ResourceActivation]
    prompt_section_composer: PromptSectionComposer
    tool_pack_composer: CapabilityPackComposer
    list_tool_definitions: Callable[
        [StandardExtensionT],
        Sequence[ToolDefinition],
    ]
    get_tool_source_info: Callable[[StandardExtensionT, str], object | None]
    dispose_capabilities: Callable[[], None]


@dataclass(frozen=True)
class AgentProductConstructionRequest(Generic[AgentT, SessionT, StandardExtensionT]):
    configuration: StandardAgentSessionConfigurationRequest[StandardExtensionT]
    ports: AgentProductConstructionPorts[StandardExtensionT]
    default_system_prompt: str
    explicit_system_prompt: str | None
    append_system_prompt: Sequence[str]
    model: Model | ModelSelection | None
    thinking_level: object
    tools: Sequence[ToolDefinition] | None
    tool_registry: WorkspaceToolRegistry | None
    allowed_tool_names: Sequence[str] | ToolSelection | None
    active_tool_names: Sequence[str] | None
    no_tools: NoToolsMode | bool | None
    stream_fn: Callable[..., object] | None
    convert_to_llm: Callable[..., object]
    agent_factory: Callable[..., AgentT]
    session_factory: Callable[
        [
            AgentT,
            ResourceBundle,
            StandardExtensionT,
            WorkspaceToolRegistry | None,
            list[str] | None,
            str,
            NoToolsMode | None,
            PackageProductLifecycleOperationPort | None,
            PackageProductLifecycleInventoryPort | None,
            PackageProductLifecycleMode,
        ],
        SessionT,
    ]
    on_default_model_unavailable: Callable[[ModelSelection, Exception, str], None]
    set_scoped_models: Callable[[SessionT, Sequence[object]], None]
    product_tool_pack_id: str = "product.registry"
    extension_tool_pack_id: str = "product.extensions"
    use_default_model: bool = True
    restore_history: bool = False


@dataclass(frozen=True)
class AgentProductConstructionResult(Generic[SessionT, StandardExtensionT]):
    session: SessionT
    configuration: StandardAgentSessionConfigurationResult[StandardExtensionT]


class AgentProductConstructionRuntime(Generic[AgentT, SessionT, StandardExtensionT]):
    """Compose existing configuration, prompt, model, tool, and Agent owners."""

    def construct(
        self,
        request: AgentProductConstructionRequest[
            AgentT,
            SessionT,
            StandardExtensionT,
        ],
    ) -> AgentProductConstructionResult[SessionT, StandardExtensionT]:
        session: SessionT | None = None
        try:
            configuration = StandardAgentSessionConfigurationRuntime[
                StandardExtensionT
            ]().configure(request.configuration)
            resource_bundle = configuration.resource_bundle
            extension_runtime = configuration.extension_runtime
            settings = request.configuration.settings
            base_prompt = resolve_base_system_prompt(
                explicit_prompt=request.explicit_system_prompt,
                resource_loader=request.configuration.resource_loader,
                configured_prompt=settings.system_prompt,
                default_prompt=request.default_system_prompt,
                append_fragments=request.append_system_prompt,
            )
            resolved_prompt = assemble_prompt(
                base_prompt=base_prompt,
                resource_bundle=resource_bundle,
                resource_activation=request.ports.activate_resources(resource_bundle),
                prompt_section_composer=request.ports.prompt_section_composer,
            ).system_prompt
            resolved_model = resolve_session_model(
                request.model,
                default_selection=settings.default_model if request.use_default_model else None,
                build_model=request.configuration.model_registry.build_model,
                endpoint_lookup=(
                    request.configuration.model_registry.ai_registry.get_endpoint
                ),
                on_default_unavailable=request.on_default_model_unavailable,
            )

            level = request.thinking_level
            if resolved_model is not None:
                if level is None:
                    configured_level = settings.thinking_level
                    if configured_level in available_thinking_levels(resolved_model):
                        level = configured_level
                elif isinstance(level, str):
                    validate_reasoning_request(
                        resolved_model,
                        enabled=level != "off",
                        effort=None if level == "off" else level,
                    )

            def register_extension_tools(
                bundle: ResourceBundle,
                registry: WorkspaceToolRegistry | None,
            ) -> tuple[
                ResourceBundle,
                WorkspaceToolRegistry | None,
                Sequence[DiagnosticDraft],
            ]:
                return register_resource_extension_tools(
                    extension_runtime=extension_runtime,
                    resource_bundle=bundle,
                    tool_registry=registry,
                    pack_composer=request.ports.tool_pack_composer,
                    list_tool_definitions=request.ports.list_tool_definitions,
                    get_tool_source_info=request.ports.get_tool_source_info,
                    product_pack_id=request.product_tool_pack_id,
                    extension_pack_id=request.extension_tool_pack_id,
                )

            session = AgentSessionConstructionRuntime[
                AgentT,
                SessionT,
                ResourceBundle,
                WorkspaceToolRegistry,
                DiagnosticDraft,
            ]().construct(
                AgentSessionConstructionRequest(
                    session_id=request.configuration.session_id,
                    base_prompt=base_prompt,
                    resolved_prompt=resolved_prompt,
                    thinking_level=level,
                    model=resolved_model,
                    convert_to_llm=request.convert_to_llm,
                    steering_mode=settings.steering_mode,
                    follow_up_mode=settings.follow_up_mode,
                    thinking_budgets=settings.thinking_budgets,
                    max_retry_delay_ms=settings.retry.provider_max_retry_delay_ms,
                    stream_fn=request.stream_fn,
                    resource_bundle=resource_bundle,
                    tools=request.tools,
                    tool_registry=request.tool_registry,
                    allowed_tool_names=request.allowed_tool_names,
                    active_tool_names=request.active_tool_names,
                    no_tools_mode=normalize_no_tools(request.no_tools),
                    restore_history=request.restore_history,
                ),
                agent_factory=request.agent_factory,
                register_extension_tools=register_extension_tools,
                record_extension_diagnostics=lambda diagnostics: _record_drafts(
                    request.configuration.diagnostics_service,
                    diagnostics,
                    session_id=request.configuration.session_id,
                ),
                registry_factory=WorkspaceToolRegistry,
                register_tool=_register_workspace_tool,
                session_factory=lambda agent, bundle, registry, active, prompt, mode: (
                    request.session_factory(
                        agent,
                        bundle,
                        extension_runtime,
                        registry,
                        active,
                        prompt,
                        mode,
                        request.configuration.package_product_lifecycle,
                        request.configuration.package_product_inventory,
                        request.configuration.package_product_lifecycle_mode,
                    )
                ),
            )
            scoped_models = scoped_models_from_patterns(
                settings.enabled_models,
                resolve_model=request.configuration.model_registry.get_model,
            )
            if scoped_models:
                request.set_scoped_models(session, scoped_models)
            return AgentProductConstructionResult(
                session=session,
                configuration=configuration,
            )
        except BaseException as error:
            if session is not None:
                from loushang.harness.session.agent_product import AgentProductSession

                if issubclass(type(session), AgentProductSession):
                    failure = retain_session_construction_failure(
                        error, cast(AgentProductSession, session)
                    )
                    if failure is error:
                        raise
                    raise failure from error
            if issubclass(type(error), Exception):
                request.ports.dispose_capabilities()
            raise


@dataclass(frozen=True)
class AgentProductConstructionBinding(Generic[AgentT, SessionT, StandardExtensionT]):
    """Compile Product policy onto the existing construction runtime."""

    default_system_prompt: str
    bind_capabilities: Callable[[], StagedResourceCompositionCandidate]
    create_extension_runtime: Callable[[ResourceBundle], StandardExtensionT]
    source_identity_check: SourceIdentityCheck
    list_tool_definitions: Callable[
        [StandardExtensionT],
        Sequence[ToolDefinition],
    ]
    get_tool_source_info: Callable[[StandardExtensionT, str], object | None]
    product_id: str | None = None
    product_tool_pack_id: str = "product.registry"
    extension_tool_pack_id: str = "product.extensions"
    bind_session_side_question: (
        Callable[[StandardExtensionT], LegacySideQuestionBinding] | None
    ) = None
    resolve_session_capability_profile: (
        Callable[
            [StandardExtensionT],
            ResolvedRuntimeProfile | SessionExtensionProfileResolution,
        ] | None
    ) = None

    def construct(
        self,
        *,
        services: BootstrapServices,
        package_materializer: PackageMaterializer | None,
        package_product_lifecycle: PackageProductLifecycleOperationPort | None = None,
        package_product_inventory: PackageProductLifecycleInventoryPort | None = None,
        package_product_lifecycle_mode: PackageProductLifecycleMode = "legacy",
        package_product_runtime_factory: PackageProductRuntimeFactoryPort | None = None,
        session_id: str,
        package_product_workspace: Path | None = None,
        cwd: str,
        extension_flag_values: ExtensionFlagValues | None,
        catalog_authoritative: bool = False,
        prepare_catalog_bootstrap_projection: (
            CatalogBootstrapProjectionPreparer | None
        ) = None,
        prepare_package_product_catalog_bootstrap_projection: (
            PackageProductCatalogBootstrapProjectionPreparer | None
        ) = None,
        package_product_catalog_failure: (
            tuple[Callable[[BaseException], None], str] | None
        ) = None,
        selected_plugin_packages: Sequence[SelectedPluginPackageInput] = (),
        explicit_system_prompt: str | None,
        append_system_prompt: Sequence[str],
        model: Model | ModelSelection | None,
        thinking_level: object | None,
        tools: Sequence[ToolDefinition] | None,
        tool_registry: WorkspaceToolRegistry | None,
        allowed_tool_names: Sequence[str] | ToolSelection | None,
        active_tool_names: Sequence[str] | None,
        no_tools: NoToolsMode | bool | None,
        stream_fn: Callable[..., object] | None,
        convert_to_llm: Callable[..., object],
        agent_factory: Callable[..., AgentT],
        session_factory: Callable[
            [
                StagedResourceCompositionCandidate,
                AgentT,
                ResourceBundle,
                StandardExtensionT,
                WorkspaceToolRegistry | None,
                list[str] | None,
                str,
                NoToolsMode | None,
                PackageProductLifecycleOperationPort | None,
                PackageProductLifecycleInventoryPort | None,
                PackageProductLifecycleMode,
            ],
            SessionT,
        ]
        | Callable[
            [
                StagedResourceCompositionCandidate,
                LegacySideQuestionBinding,
                AgentT,
                ResourceBundle,
                StandardExtensionT,
                WorkspaceToolRegistry | None,
                list[str] | None,
                str,
                NoToolsMode | None,
                PackageProductLifecycleOperationPort | None,
                PackageProductLifecycleInventoryPort | None,
                PackageProductLifecycleMode,
            ],
            SessionT,
        ],
        on_default_model_unavailable: Callable[
            [ModelSelection, Exception, str],
            None,
        ],
        set_scoped_models: Callable[[SessionT, Sequence[object]], None],
        use_default_model: bool = True,
        restore_history: bool = False,
    ) -> AgentProductConstructionResult[SessionT, StandardExtensionT]:
        """Build the canonical request and delegate all execution to its owner."""

        settings = services.settings_manager.get_settings()
        if package_product_runtime_factory is not None and (
            package_product_lifecycle is not None
            or package_product_inventory is not None
            or package_product_lifecycle_mode != "legacy"
        ):
            raise ValueError(
                "Package Product runtime factory cannot be mixed with split bindings"
            )
        if package_product_runtime_factory is not None and self.product_id is None:
            raise ValueError(
                "Package Product identity is required for runtime activation"
            )
        if (
            prepare_package_product_catalog_bootstrap_projection is not None
            and package_product_runtime_factory is None
        ):
            raise ValueError(
                "Package Product Catalog preparation requires an activated runtime"
            )
        bootstrap_capability_runtime = self.bind_capabilities()
        bootstrap_capability_handles = _root_owned_resource_handles(
            bootstrap_capability_runtime
        )
        session_side_question_bindings: list[LegacySideQuestionBinding] = []
        package_runtime: PackageProductRuntimeBindingV1 | None = None
        constructed_session: SessionT | None = None

        def bind_package_runtime(session: SessionT) -> SessionT:
            nonlocal constructed_session
            if package_runtime is not None and package_runtime.on_dispose is not None:
                bind = getattr(session, "_bind_package_product_runtime", None)
                if not callable(bind):
                    raise TypeError("Package Product Session cannot own its runtime")
                bind(package_runtime)
            constructed_session = session
            return session

        def create_session(
            agent: AgentT,
            bundle: ResourceBundle,
            extension_runtime: StandardExtensionT,
            registry: WorkspaceToolRegistry | None,
            active: list[str] | None,
            prompt: str,
            mode: NoToolsMode | None,
            product_lifecycle: PackageProductLifecycleOperationPort | None,
            product_inventory: PackageProductLifecycleInventoryPort | None,
            product_lifecycle_mode: PackageProductLifecycleMode,
        ) -> SessionT:
            factory_prefix: tuple[
                StagedResourceCompositionCandidate | LegacySideQuestionBinding, ...
            ] = (bootstrap_capability_runtime,)
            prepare_side_question = None
            if self.resolve_session_capability_profile is not None:
                resolved = self.resolve_session_capability_profile(extension_runtime)
                if isinstance(resolved, SessionExtensionProfileResolution):
                    bootstrap_capability_runtime.select_final_profile(resolved.profile)
                    prepare_side_question = resolved.bind_side_question
                else:
                    bootstrap_capability_runtime.select_final_profile(resolved)
            if self.bind_session_side_question is not None:
                side_question_binding = self.bind_session_side_question(extension_runtime)
            elif prepare_side_question is not None:
                side_question_binding = prepare_side_question()
            else:
                side_question_binding = None
            if side_question_binding is not None:
                session_side_question_bindings.append(side_question_binding)
                factory_prefix += (side_question_binding,)
            elif (
                self.bind_session_side_question is not None
                or prepare_side_question is not None
            ):
                raise AssertionError("Session side-question binding is unavailable")
            factory = cast(Callable[..., SessionT], session_factory)
            return bind_package_runtime(
                factory(
                    *factory_prefix,
                    agent,
                    bundle,
                    extension_runtime,
                    registry,
                    active,
                    prompt,
                    mode,
                    product_lifecycle,
                    product_inventory,
                    product_lifecycle_mode,
                )
            )

        try:
            if package_product_runtime_factory is not None:
                assert self.product_id is not None
                package_runtime = activate_package_product_runtime(
                    package_product_runtime_factory,
                    PackageProductRuntimeRequestV1(
                        product_id=self.product_id,
                        session_id=session_id,
                        cwd=str((package_product_workspace or Path(cwd)).resolve(strict=False)),
                    ),
                )
                package_product_lifecycle = package_runtime.lifecycle
                package_product_inventory = package_runtime.inventory
                package_product_lifecycle_mode = package_runtime.mode
            selected_catalog_preparer = prepare_catalog_bootstrap_projection
            if (
                package_runtime is not None
                and prepare_package_product_catalog_bootstrap_projection is not None
            ):
                activated_runtime = package_runtime
                product_catalog_preparer = (
                    prepare_package_product_catalog_bootstrap_projection
                )

                def prepare_selected_product_catalog(
                    loader: ResourceLoader, resolved_cwd: Path
                ) -> ResourceBundle:
                    try:
                        return product_catalog_preparer(
                            loader, resolved_cwd, activated_runtime
                        )
                    except BaseException as error:
                        if package_product_catalog_failure is not None:
                            record_failure, cleanup_label = (
                                package_product_catalog_failure
                            )
                            record_failure(error)
                            run_cleanup_steps(
                                error, ((cleanup_label, activated_runtime.dispose_runtime),)
                            )
                        raise

                selected_catalog_preparer = prepare_selected_product_catalog
            result = AgentProductConstructionRuntime[
                AgentT,
                SessionT,
                StandardExtensionT,
            ]().construct(
                AgentProductConstructionRequest(
                    configuration=StandardAgentSessionConfigurationRequest(
                        settings=settings,
                        settings_manager=services.settings_manager,
                        model_registry=services.model_registry,
                        resource_loader=services.resource_loader,
                        diagnostics_service=services.diagnostics_service,
                        package_materializer=package_materializer,
                        skill_activation_runtime=(
                            bootstrap_capability_handles.skill_activation
                        ),
                        session_id=session_id,
                        cwd=cwd,
                        create_extension_runtime=self.create_extension_runtime,
                        source_identity_check=self.source_identity_check,
                        extension_flag_values=extension_flag_values,
                        catalog_authoritative=catalog_authoritative,
                        prepare_catalog_bootstrap_projection=(
                            selected_catalog_preparer
                        ),
                        selected_plugin_packages=tuple(selected_plugin_packages),
                        package_product_lifecycle=package_product_lifecycle,
                        package_product_inventory=package_product_inventory,
                        package_product_lifecycle_mode=package_product_lifecycle_mode,
                    ),
                    ports=AgentProductConstructionPorts(
                        activate_resources=(
                            bootstrap_capability_handles.activate_resources
                        ),
                        prompt_section_composer=(
                            bootstrap_capability_handles.prompt_section_composer
                        ),
                        tool_pack_composer=(
                            bootstrap_capability_handles.tool_pack_composer
                        ),
                        list_tool_definitions=self.list_tool_definitions,
                        get_tool_source_info=self.get_tool_source_info,
                        dispose_capabilities=bootstrap_capability_handles.dispose,
                    ),
                    default_system_prompt=self.default_system_prompt,
                    explicit_system_prompt=explicit_system_prompt,
                    append_system_prompt=append_system_prompt,
                    model=model,
                    use_default_model=use_default_model,
                    restore_history=restore_history,
                    thinking_level=thinking_level,
                    tools=tools,
                    tool_registry=tool_registry,
                    allowed_tool_names=allowed_tool_names,
                    active_tool_names=active_tool_names,
                    no_tools=no_tools,
                    stream_fn=stream_fn,
                    convert_to_llm=convert_to_llm,
                    agent_factory=agent_factory,
                    session_factory=create_session,
                    on_default_model_unavailable=on_default_model_unavailable,
                    set_scoped_models=set_scoped_models,
                    product_tool_pack_id=self.product_tool_pack_id,
                    extension_tool_pack_id=self.extension_tool_pack_id,
                )
            )
        except BaseException as error:
            cleanup = get_session_construction_cleanup(error)
            if cleanup is not None and cleanup.owns_session(constructed_session):
                from loushang.harness.session.agent_product import AgentProductSession

                if issubclass(type(constructed_session), AgentProductSession):
                    raise
            if package_runtime is not None:
                run_cleanup_steps(
                    error,
                    (
                        (
                            "Package Product runtime cleanup",
                            lambda: cast(
                                PackageProductRuntimeBindingV1, package_runtime
                            ).dispose_runtime(),
                        ),
                    ),
                )
            for side_question_binding in reversed(session_side_question_bindings):

                def dispose_side_question(
                    binding: LegacySideQuestionBinding = side_question_binding,
                ) -> None:
                    binding.dispose()

                run_cleanup_steps(
                    error,
                    (("final Session side-question cleanup", dispose_side_question),),
                )
            run_cleanup_steps(
                error,
                (
                    (
                        "bootstrap capability cleanup",
                        lambda: bootstrap_capability_runtime.dispose(),
                    ),
                ),
            )
            raise

        return result


def _root_owned_resource_handles(
    runtime: StagedResourceCompositionCandidate,
) -> _RootOwnedResourceHandles:
    """Adapt legacy test/Product fakes while canonical code uses narrow handles."""

    factory = getattr(runtime, "_root_owned_handles", None)
    value = factory() if callable(factory) else runtime
    return cast(_RootOwnedResourceHandles, value)


__all__ = [
    "AgentBootstrapRequest",
    "AgentBootstrapRuntime",
    "AgentProductConstructionBinding",
    "AgentProductConstructionPorts",
    "AgentProductConstructionRequest",
    "AgentProductConstructionResult",
    "AgentProductConstructionRuntime",
    "AgentSessionConstructionRequest",
    "AgentSessionConstructionRuntime",
]


if TYPE_CHECKING:
    from loushang.harness.session.plugin_lifecycle._composition_cleanup import (
        _PreparationFailureCleanup,
        _PreparedCompositionCleanup,
    )

_PreparationT = TypeVar("_PreparationT", bound="_PreparedCompositionCleanup")


def rollback_unpublished_construction(
    error: BaseException,
    *,
    worker_tool_lease: RegistrationLease | None,
    abort_capability: Callable[[], None] | None,
    close_base: Callable[[], None] | None,
    owned_side_question: LegacySideQuestionBinding | None,
    owned_runtime: StagedResourceCompositionCandidate | None,
    product_label: str,
) -> None:
    steps: list[CleanupStep] = []
    if worker_tool_lease is not None:
        # The cleanup runner discards callback return values.
        rollback = cast("Callable[[], None]", worker_tool_lease.rollback_registration)
        steps.append((f"{product_label} Worker turn Tool admission rollback", rollback))
    if abort_capability is not None:
        steps.append(
            (
                f"{product_label} Capability Plugin evidence cleanup",
                abort_capability,
            )
        )
    if close_base is not None:
        steps.append(
            (f"{product_label} base Plugin evidence cleanup", close_base)
        )
    if owned_side_question is not None:
        steps.append(
            ("direct Session side-question cleanup", owned_side_question.dispose)
        )
    if owned_runtime is not None:
        steps.append(("direct Session capability cleanup", owned_runtime.dispose))
    run_cleanup_steps(error, steps)


def require_catalog_receipt(
    loader: ResourceLoader,
    cwd: Path,
    admission_failure: ProductAdmissionFailure,
    receipt: ResourceCatalogInputReceipt | None = None,
) -> ResourceCatalogInputReceipt:
    if receipt is None:
        try:
            receipt = loader.prepare_catalog_input_receipt(cwd)
        except (AttributeError, RuntimeError) as exc:
            raise admission_failure(("catalog_receipt_unavailable",)) from exc
    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise admission_failure(("catalog_receipt_unavailable",))
    return receipt


class _ManagedStartupLayout(Protocol):
    @property
    def package_install_root(self) -> Path: ...
    @property
    def package_lockfile(self) -> Path: ...
    @property
    def plugin_revision_root(self) -> Path: ...


class _ManagedStartupLifecycle(Protocol):
    def complete_startup_recovery(self) -> None: ...
    def release_owned_process_startup_lease(self) -> None: ...


_LayoutT = TypeVar("_LayoutT", bound=_ManagedStartupLayout)
_LifecycleT = TypeVar("_LifecycleT", bound=_ManagedStartupLifecycle)
_MaterializerT = TypeVar("_MaterializerT", bound=PackageMaterializer)
_PrimaryT = TypeVar("_PrimaryT")
_Cleanup = Callable[[], None]


def prepare_managed_plugin_startup(
    *,
    resolve_layout: Callable[[str | None], _LayoutT],
    build_lifecycle: Callable[[_LayoutT], _LifecycleT],
    materializer_type: type[_MaterializerT],
    package_materializer: _MaterializerT | None,
    resolved_package_materializer: _MaterializerT | None,
    ephemeral_prefix: str | None,
    prepare_primary: Callable[[_LifecycleT, _MaterializerT, _Cleanup | None], _PrimaryT] | None,
    needs_eager: bool,
    needs_deferred: bool,
    diagnostics_service: DiagnosticsService,
    session_id: str,
    authority_mismatch: Callable[[], Exception],
    record_failure: Callable[[BaseException], None],
    directory_factory: Callable[..., ExplicitTemporaryDirectory],
) -> tuple[_LifecycleT, _MaterializerT, _PrimaryT | None, _Cleanup | None, _Cleanup | None]:
    """Hand off the original startup lease and temporary root, or recover both."""
    ephemeral = directory_factory(prefix=ephemeral_prefix) if ephemeral_prefix is not None else None
    lifecycle = None
    materializer = None
    recorded_diagnostics: list[dict[str, object]] = []
    primary_cleanup = eager_cleanup = deferred_cleanup = None
    record_diagnostics = partial(
        record_package_lockfile_diagnostics,
        diagnostics_service=diagnostics_service,
        session_id=session_id,
    )
    try:
        layout = resolve_layout(ephemeral.name if ephemeral is not None else None)
        if (
            ephemeral is None
            and package_materializer is not None
            and not package_materializer.uses_storage_authority(
                install_root=layout.package_install_root,
                lockfile_path=layout.package_lockfile,
                plugin_revision_root=layout.plugin_revision_root,
            )
        ):
            raise authority_mismatch()
        lifecycle = build_lifecycle(layout)
        materializer = package_materializer or materializer_type(
            install_root=layout.package_install_root,
            lockfile_path=layout.package_lockfile,
            plugin_revision_root=layout.plugin_revision_root,
            backend=GitPackageMaterializerBackend(),
        )
        if materializer is not resolved_package_materializer:
            recorded_diagnostics = materializer.get_lockfile_diagnostics()
            record_diagnostics(recorded_diagnostics)
        if ephemeral is not None:
            primary_cleanup, eager_cleanup, deferred_cleanup = share_startup_cleanup(
                lifecycle.release_owned_process_startup_lease,
                ephemeral.cleanup,
                primary=prepare_primary is not None,
                eager=needs_eager,
                deferred=needs_deferred,
            )
        lifecycle.complete_startup_recovery()
        primary = (
            prepare_primary(lifecycle, materializer, primary_cleanup)
            if prepare_primary is not None
            else None
        )
    except BaseException as error:
        record_failure(error)
        if materializer is not None:
            record_diagnostics(
                [
                    diagnostic
                    for diagnostic in materializer.get_lockfile_diagnostics()
                    if diagnostic not in recorded_diagnostics
                ]
            )
        for cleanup in (primary_cleanup, eager_cleanup, deferred_cleanup):
            if cleanup is not None:
                cleanup()
        if lifecycle is not None:
            lifecycle.release_owned_process_startup_lease()
        if eager_cleanup is None and primary_cleanup is None and ephemeral is not None:
            ephemeral.cleanup()
        raise
    return lifecycle, materializer, primary, eager_cleanup, deferred_cleanup

@dataclass(slots=True)
class PreparationRootCustody(Generic[_PreparationT]):
    """One partial-progress authority for a preparation and its two roots."""

    state_root: ExplicitTemporaryDirectory | None = None
    private_root: ExplicitTemporaryDirectory | None = None
    preparation: _PreparationT | None = None
    started: bool = False

    def begin_once(self, message: str) -> None:
        if self.started:
            raise RuntimeError(message)
        self.started = True

    def prepare_roots(
        self,
        *,
        state_prefix: str | None,
        private_prefix: str | None,
        persistent_root: Callable[[], Path],
        directory_factory: Callable[..., ExplicitTemporaryDirectory] = ExplicitTemporaryDirectory,
    ) -> Path:
        self.state_root = (
            directory_factory(prefix=state_prefix) if state_prefix is not None else None
        )
        self.private_root = (
            directory_factory(prefix=private_prefix)
            if private_prefix is not None
            else None
        )
        return (
            Path(self.state_root.name)
            if self.state_root is not None
            else persistent_root()
        )

    def attach_cleanup(self, preparation: _PreparationT) -> None:
        preparation.state_cleanup = self.state_cleanup
        preparation.private_state_cleanup = self.private_cleanup

    @property
    def state_cleanup(self) -> Callable[[], None] | None:
        return self.state_root.cleanup if self.state_root is not None else None

    @property
    def private_cleanup(self) -> Callable[[], None] | None:
        return self.private_root.cleanup if self.private_root is not None else None

    def cleanup_preparation_sequentially(self) -> None:
        if self.preparation is not None:
            self.preparation.close()
        self.cleanup_roots_sequentially()

    def cleanup_roots_sequentially(self) -> None:
        if self.state_root is not None:
            self.state_root.cleanup()
        if self.private_root is not None:
            self.private_root.cleanup()

    def cleanup_roots_with_notes(
        self, error: BaseException, *, state_label: str, private_label: str
    ) -> None:
        run_cleanup_steps(
            error,
            tuple(
                (name, cleanup)
                for name, cleanup in (
                    (state_label, self.state_cleanup),
                    (private_label, self.private_cleanup),
                )
                if cleanup is not None
            ),
        )


_StartupSessionT = TypeVar("_StartupSessionT", bound="AgentProductSession")
_CatalogBaseT = TypeVar("_CatalogBaseT", bound=ProductBaseSelectionEvidence)


class _CatalogDataCompilation(Protocol):
    @property
    def selected_manifests(self) -> tuple[PackageProductSelectedPluginManifestV1, ...]: ...


_CatalogDataT = TypeVar("_CatalogDataT", bound=_CatalogDataCompilation)


@dataclass(slots=True, kw_only=True)
class SessionStartupCustody(PreparationRootCustody[_PreparationT]):
    """Hand prepared Catalog and Plugin owners to one original Session."""

    product_id: str
    product_label: str
    session_id: str
    admission_failure: ProductAdmissionFailure
    catalog_adapter: InitialResourceCatalogProductAdapter | None = field(
        default=None, init=False, repr=False
    )
    catalog_selection: ProductCatalogSelection = field(
        default_factory=ProductCatalogSelection, init=False, repr=False
    )
    _constructed_session: AgentProductSession | None = field(
        default=None, init=False, repr=False
    )

    def prepare_fenced_catalog(
        self,
        runtime: PackageProductRuntimeBindingV1,
        loader: ResourceLoader,
        *,
        cwd: Path,
        base_plugin_id: str,
        capability_requests: tuple[tuple[str, bool], ...],
        require_capabilities: bool,
        max_files: int,
        max_total_bytes: int,
        clock: Callable[[], int],
        compile_base: Callable[[PackageProductSelectedPluginManifestV1, int], _CatalogBaseT],
        compile_data: Callable[
            [_CatalogBaseT | None, tuple[PackageProductSelectedPluginManifestV1, ...], int],
            tuple[_CatalogBaseT | None, _CatalogDataT | None],
        ],
        prepare_capabilities: Callable[
            [_CatalogBaseT | None, list[str]], tuple[_CatalogBaseT | None, _PreparationT]
        ],
        build_adapter: Callable[
            [ResourceCatalogInputReceipt, _CatalogBaseT | None, _CatalogDataT | None, int | None],
            InitialResourceCatalogProductAdapter,
        ],
    ) -> tuple[ResourceBundle, _CatalogBaseT | None, _CatalogDataT | None]:
        """Prepare and retain one fenced selection for Session handoff and refresh."""
        disabled_base = capture_catalog_base_selection(runtime, base_plugin_id, self.admission_failure)
        capture_manifests = partial(
            capture_selected_manifests, runtime.capture_selected_plugin_manifest_for,
            max_files=max_files, max_total_bytes=max_total_bytes,
        )
        base = external = receipt = evaluated_at = None
        if disabled_base is not None:
            external_ids = runtime.selected_external_data_plugin_ids()
            if external_ids:
                base, external = compile_data(None, capture_manifests(external_ids), clock())
        else:
            (selected,) = capture_manifests((base_plugin_id,))
            evaluated_at = clock()
            base = compile_base(selected, evaluated_at)
            receipt = self.require_catalog_input(loader, cwd)

        enabled, selections = observe_requested_plugins(
            runtime, capability_requests, self.admission_failure
        )
        if enabled:
            base, self.preparation = prepare_capabilities(base, enabled)
            self.attach_cleanup(self.preparation)
        elif require_capabilities:
            raise self.admission_failure(("resume_plugin_participation_changed",))
        elif base is not None:
            assert evaluated_at is not None
            external_ids = runtime.selected_external_data_plugin_ids()
            if external_ids:
                base, external = compile_data(base, capture_manifests(external_ids), evaluated_at)

        if receipt is None:
            receipt = self.require_catalog_input(loader, cwd)
        bundle = self.prepare_initial_catalog(
            build_adapter(receipt, base, external, evaluated_at if base is not None else None),
            cwd=cwd,
        )
        self.catalog_selection = ProductCatalogSelection(
            runtime=runtime,
            capability_selections=selections,
            disabled_base=disabled_base,
            base=base.selected_manifest if base is not None else None,
            capabilities=base.selected_capability_manifests if base is not None else (),
            external=(
                base.selected_external_data_manifests
                if base is not None
                else external.selected_manifests if external is not None else ()
            ),
        )
        return bundle, base, external

    def prepare_legacy_catalog(
        self,
        loader: ResourceLoader,
        *,
        cwd: Path,
        clock: Callable[[], int] | None,
        compile_composition: Callable[
            [ResourceCatalogInputReceipt, int], ProductCompositionCompilation | None
        ],
        reconcile_compatibility: Callable[[], None],
        build_adapter: Callable[
            [ResourceCatalogInputReceipt, ProductCompositionCompilation | None, int],
            InitialResourceCatalogProductAdapter,
        ],
    ) -> ResourceBundle:
        """Settle the selected legacy Plugin plan before staging its Catalog."""
        receipt = self.require_catalog_input(loader, cwd)
        evaluated_at = clock() if clock is not None else int(time.time())
        composition = compile_composition(receipt, evaluated_at)
        reconcile_compatibility()
        if composition is not None:
            evaluated_at = composition.authority_context.evaluated_at
        return self.prepare_initial_catalog(
            build_adapter(receipt, composition, evaluated_at), cwd=cwd
        )

    def prepare_initial_catalog(
        self,
        adapter: InitialResourceCatalogProductAdapter,
        *,
        cwd: Path,
    ) -> ResourceBundle:
        """Stage only an adapter whose synchronous Catalog projection succeeded."""
        bundle = adapter.prepare_bootstrap_projection(
            product_id=self.product_id, session_id=self.session_id, cwd=cwd
        )
        self.catalog_adapter = adapter
        return bundle

    def prepare_catalog_refresh(
        self,
        catalog_generation: int,
        *,
        loader: ResourceLoader,
        get_cwd: Callable[[], str],
        prepare_adapter: Callable[
            [ResourceCatalogInputReceipt], InitialResourceCatalogProductAdapter
        ],
    ) -> InitialSessionResourceCatalogBootstrap:
        """Read and prepare a replacement only after rechecking startup evidence."""
        self.catalog_selection.require_current(
            product_label=self.product_label, refresh_failure=self.admission_failure
        )
        cwd = Path(get_cwd())
        adapter = prepare_adapter(self.require_catalog_input(loader, cwd))
        return adapter.prepare_session_bootstrap(
            product_id=self.product_id,
            session_id=self.session_id,
            base_resource_bundle=adapter.prepare_bootstrap_projection(
                product_id=self.product_id, session_id=self.session_id, cwd=cwd
            ),
            catalog_generation=catalog_generation,
        )

    def require_catalog_input(self, loader: ResourceLoader, cwd: Path) -> ResourceCatalogInputReceipt:
        return require_catalog_receipt(loader, cwd, self.admission_failure)

    def require_catalog_unprepared(self, error: str) -> None:
        if self.catalog_adapter is not None:
            raise RuntimeError(error)

    def take_catalog_adapter(self) -> InitialResourceCatalogProductAdapter:
        adapter = self.catalog_adapter
        if adapter is None:
            raise RuntimeError("Initial Resource Catalog projection adapter is unavailable")
        self.catalog_adapter = None
        self.catalog_selection.require_current(product_label=self.product_label)
        return adapter

    def construct_catalog_session(
        self,
        adapter: InitialResourceCatalogProductAdapter,
        *,
        bundle: ResourceBundle,
        construct: Callable[[InitialSessionResourceCatalogBootstrap], _StartupSessionT],
        abort_unpublished: CleanupStep | None = None,
    ) -> _StartupSessionT:
        # The Catalog rolls back its inputs before the outer Plugin handoff.
        try:
            session = adapter.construct_session(
                product_id=self.product_id,
                session_id=self.session_id,
                base_resource_bundle=bundle,
                construct=construct,
            )
        except BaseException as error:
            if abort_unpublished is not None:
                run_cleanup_steps(error, (abort_unpublished,))
            raise
        self._constructed_session = session
        return session

    async def emit_workspace_audit(self, event: Mapping[str, object]) -> None:
        session = self._constructed_session
        if session is None:
            raise RuntimeError(f"{self.product_label} workspace Session is not yet bound")
        await session.emit_product_tool_audit_event(event)

    @contextmanager
    def guard_startup(
        self,
        *,
        read_failure_custodian: Callable[[BaseException], _PreparationFailureCleanup | None],
        management_cleanup: Callable[[], None] | None,
        private_label: str,
        before: tuple[str, Callable[[], None] | None],
        base_preparation: _PreparedCompositionCleanup | None,
    ) -> Iterator[None]:
        """Rollback original startup owners until the Session owns its own cleanup."""
        try:
            yield
        except BaseException as error:
            cleanup = get_session_construction_cleanup(error)
            if cleanup is not None and cleanup.owns_session(self._constructed_session):
                raise
            failure_custodian = read_failure_custodian(error)
            after = (
                f"{self.product_label} base Plugin cleanup",
                base_preparation.close if base_preparation is not None else None,
            )
            # A retained failure custodian settles its own leases and roots.
            preparation = self.preparation if failure_custodian is None else failure_custodian
            preparation_label = f"{self.product_label} Capability Plugin preparation cleanup"
            steps: tuple[tuple[str, Callable[[], None] | None], ...]
            if preparation is None:
                steps = (
                    (
                        f"{self.product_label} Capability Plugin management-state cleanup",
                        management_cleanup,
                    ),
                    (preparation_label, self.state_cleanup),
                    (private_label, self.private_cleanup),
                )
            else:
                steps = ((preparation_label, preparation.close),)
            run_cleanup_steps(
                error,
                ((label, cleanup) for label, cleanup in (before, *steps, after) if cleanup is not None),
            )
            raise


_ConfigurationT = TypeVar("_ConfigurationT")
_BoundPluginT = TypeVar("_BoundPluginT")


def bind_deferred_plugin(
    *,
    state_prefix: Callable[[], str | None],
    persistent_root: Callable[[], Path],
    configure: Callable[[], _ConfigurationT],
    capture_fenced_selection: Callable[[], _Cleanup] | None,
    prepare: Callable[[_ConfigurationT, Path, _Cleanup | None], _PreparationT],
    bind: Callable[[_PreparationT], _BoundPluginT],
) -> tuple[_BoundPluginT, _Cleanup | None]:
    """Transfer preparation and root custody to a bound deferred plugin."""

    custody: PreparationRootCustody[_PreparationT] = PreparationRootCustody()
    state_root = custody.prepare_roots(
        state_prefix=state_prefix(),
        private_prefix=None,
        persistent_root=persistent_root,
    )
    try:
        configuration = configure()
        require_current = (
            capture_fenced_selection() if capture_fenced_selection is not None else None
        )
        custody.preparation = prepare(configuration, state_root, custody.state_cleanup)
        # Managed preparation receives cleanup up front for its failure custodian.
        if capture_fenced_selection is not None and custody.state_root is not None:
            custody.preparation.state_cleanup = custody.state_cleanup
        return bind(custody.preparation), require_current
    except BaseException:
        custody.cleanup_preparation_sequentially()
        raise
