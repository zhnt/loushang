"""Agent and Product session construction contracts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from loushang.ai.model import Model
from loushang.ai.model.selection import ModelSelection
from loushang.harness.bootstrap import (
    StandardExtensionRuntime,
    register_resource_extension_tools,
)
from loushang.harness.capabilities import StagedResourceCompositionCandidate
from loushang.harness.capabilities.packs import CapabilityPackComposer
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.capabilities.prompt_assembly import assemble_prompt
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.activation import (
    ResourceActivation,
    SkillActivationRuntime,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import ResolvedRuntimeProfile
from loushang.harness.session.bootstrap_configuration import (
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
from loushang.harness.session.legacy_side_question import LegacySideQuestionBinding
from loushang.harness.session.model_resolution import (
    resolve_session_model,
    scoped_models_from_patterns,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


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
    allowed_tool_names: Sequence[str] | None
    active_tool_names: Sequence[str] | None
    no_tools_mode: NoToolsMode | None


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
        allowed_tool_names = (
            set(request.allowed_tool_names)
            if request.allowed_tool_names is not None
            else None
        )
        if request.no_tools_mode == "all":
            allowed_tool_names = set()
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
    allowed_tool_names: Sequence[str] | None
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
        ],
        SessionT,
    ]
    on_default_model_unavailable: Callable[[ModelSelection, Exception, str], None]
    set_scoped_models: Callable[[SessionT, Sequence[object]], None]
    product_tool_pack_id: str = "product.registry"
    extension_tool_pack_id: str = "product.extensions"


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
                default_selection=settings.default_model,
                build_model=request.configuration.model_registry.build_model,
                endpoint_lookup=(
                    request.configuration.model_registry.ai_registry.get_endpoint
                ),
                on_default_unavailable=request.on_default_model_unavailable,
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
                    thinking_level=request.thinking_level,
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
        except Exception:
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
    product_tool_pack_id: str = "product.registry"
    extension_tool_pack_id: str = "product.extensions"
    bind_session_side_question: (
        Callable[[StandardExtensionT], LegacySideQuestionBinding] | None
    ) = None
    resolve_session_capability_profile: (
        Callable[[StandardExtensionT], ResolvedRuntimeProfile] | None
    ) = None

    def construct(
        self,
        *,
        services: BootstrapServices,
        package_materializer: PackageMaterializer,
        session_id: str,
        cwd: str,
        extension_flag_values: ExtensionFlagValues | None,
        explicit_system_prompt: str | None,
        append_system_prompt: Sequence[str],
        model: Model | ModelSelection | None,
        thinking_level: object | None,
        tools: Sequence[ToolDefinition] | None,
        tool_registry: WorkspaceToolRegistry | None,
        allowed_tool_names: Sequence[str] | None,
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
            ],
            SessionT,
        ],
        on_default_model_unavailable: Callable[
            [ModelSelection, Exception, str],
            None,
        ],
        set_scoped_models: Callable[[SessionT, Sequence[object]], None],
    ) -> AgentProductConstructionResult[SessionT, StandardExtensionT]:
        """Build the canonical request and delegate all execution to its owner."""

        settings = services.settings_manager.get_settings()
        bootstrap_capability_runtime = self.bind_capabilities()
        bootstrap_capability_handles = _root_owned_resource_handles(
            bootstrap_capability_runtime
        )
        session_side_question_bindings: list[LegacySideQuestionBinding] = []

        def create_session(
            agent: AgentT,
            bundle: ResourceBundle,
            extension_runtime: StandardExtensionT,
            registry: WorkspaceToolRegistry | None,
            active: list[str] | None,
            prompt: str,
            mode: NoToolsMode | None,
        ) -> SessionT:
            if self.resolve_session_capability_profile is not None:
                bootstrap_capability_runtime.select_final_profile(
                    self.resolve_session_capability_profile(extension_runtime)
                )
            side_question_binding = (
                self.bind_session_side_question(extension_runtime)
                if self.bind_session_side_question is not None
                else None
            )
            if side_question_binding is not None:
                session_side_question_bindings.append(side_question_binding)
            if self.bind_session_side_question is None:
                legacy_factory = cast(
                    Callable[
                        [
                            StagedResourceCompositionCandidate,
                            AgentT,
                            ResourceBundle,
                            StandardExtensionT,
                            WorkspaceToolRegistry | None,
                            list[str] | None,
                            str,
                            NoToolsMode | None,
                        ],
                        SessionT,
                    ],
                    session_factory,
                )
                return legacy_factory(
                    bootstrap_capability_runtime,
                    agent,
                    bundle,
                    extension_runtime,
                    registry,
                    active,
                    prompt,
                    mode,
                )
            factory_with_side_question = cast(
                Callable[
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
                    ],
                    SessionT,
                ],
                session_factory,
            )
            assert side_question_binding is not None
            return factory_with_side_question(
                bootstrap_capability_runtime,
                side_question_binding,
                agent,
                bundle,
                extension_runtime,
                registry,
                active,
                prompt,
                mode,
            )

        try:
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
                    thinking_level=(
                        settings.thinking_level
                        if thinking_level is None
                        else thinking_level
                    ),
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
            for side_question_binding in reversed(session_side_question_bindings):
                try:
                    side_question_binding.dispose()
                except BaseException as cleanup_error:
                    error.add_note(
                        "final Session side-question cleanup also failed: "
                        f"{cleanup_error}"
                    )
            try:
                bootstrap_capability_runtime.dispose()
            except BaseException as cleanup_error:
                error.add_note(
                    f"bootstrap capability cleanup also failed: {cleanup_error}"
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
