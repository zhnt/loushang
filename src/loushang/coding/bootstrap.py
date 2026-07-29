from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from loushang.agent import Agent, StreamFn, ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.diagnostics.profile import coding_runtime_identity
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE
from loushang.coding.prompt.defaults import DEFAULT_CODING_SYSTEM_PROMPT
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.runtime import AgentSessionRuntime
from loushang.coding.sandbox import bind_coding_sandbox_runtime
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.approval import (
    InteractiveApprovalResolver,
    approval_actor_id,
)
from loushang.harness.bootstrap import (
    create_standard_resource_bootstrap_runtime,
)
from loushang.harness.capabilities import (
    CapabilityCompositionRuntime,
    bind_capability_composition_runtime,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.diagnostics.types import StartupCheckResult
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import SessionStartEvent
from loushang.harness.multiagent import DelegatedExecutionProfile
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resources.packages.materializer import (
    GitPackageMaterializerBackend,
    resolve_session_package_install_root,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.session import (
    AgentProductConstructionBinding,
    AgentSessionServices,
    BootstrapServices,
    CreateAgentSessionResult,
    CwdBoundServicesAudit,
    build_agent_product_session_runtime,
    build_standard_agent_session_result,
    create_standard_agent_bootstrap_services,
    normalize_no_tools,
    project_root_from_settings_base,
    record_default_model_unavailable,
)
from loushang.harness.session import (
    CwdBoundServicesAuditIssue as _CwdBoundServicesAuditIssue,
)
from loushang.harness.session import (
    audit_cwd_bound_services as _audit_cwd_bound_services,
)
from loushang.harness.session import (
    prepare_agent_session_services as prepare_standard_agent_session_services,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import context_items_to_model_messages
from loushang.harness.workspace.exec import ExecService

AgentFactory = Callable[..., Agent]
ServicesFactory = Callable[[str], "BootstrapServices"]
NoToolsMode = Literal["all", "builtin"]
ExtensionFlagValues = Mapping[str, bool | str]
CwdBoundServicesAuditIssue = _CwdBoundServicesAuditIssue


def create_services(
    *,
    ai_model_registry: AiModelRegistry | None = None,
    resource_loader: DefaultResourceLoader | None = None,
    settings_manager: SettingsManager | None = None,
    exec_service: ExecService | None = None,
    default_model: ModelSelection | None = None,
    thinking_level: ThinkingLevel = "off",
    system_prompt: str = "",
) -> BootstrapServices:
    return create_standard_agent_bootstrap_services(
        resource_loader_factory=DefaultResourceLoader,
        ai_model_registry=ai_model_registry,
        resource_loader=resource_loader,
        settings_manager=settings_manager,
        exec_service=exec_service,
        default_model=default_model,
        thinking_level=thinking_level,
        system_prompt=system_prompt,
    )


def create_agent_session_services(
    *,
    cwd: str | Path,
    services: BootstrapServices | None = None,
    ai_model_registry: AiModelRegistry | None = None,
    resource_loader: DefaultResourceLoader | None = None,
    settings_manager: SettingsManager | None = None,
    exec_service: ExecService | None = None,
    default_model: ModelSelection | None = None,
    thinking_level: ThinkingLevel = "off",
    system_prompt: str = "",
    global_settings_path: str | Path | None = None,
    project_settings_path: str | Path | None = None,
    resource_loader_options: dict[str, object] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
) -> AgentSessionServices:
    def create_cwd_services(resolved_cwd: Path) -> BootstrapServices:
        resolved_settings_manager = settings_manager or SettingsManager(
            global_settings_path=Path(global_settings_path)
            if global_settings_path is not None
            else default_global_settings_path(),
            project_settings_path=Path(project_settings_path)
            if project_settings_path is not None
            else default_project_settings_path(resolved_cwd),
        )
        return create_services(
            ai_model_registry=ai_model_registry,
            resource_loader=resource_loader,
            settings_manager=resolved_settings_manager,
            exec_service=exec_service,
            default_model=default_model,
            thinking_level=thinking_level,
            system_prompt=system_prompt,
        )

    return prepare_standard_agent_session_services(
        cwd=cwd,
        services=services,
        create_services=create_cwd_services,
        service_overrides={
            "ai_model_registry": ai_model_registry,
            "resource_loader": resource_loader,
            "settings_manager": settings_manager,
            "exec_service": exec_service,
            "default_model": default_model,
        },
        build_resource_bootstrap=lambda resolved_services: (
            create_standard_resource_bootstrap_runtime(
                create_extension_runtime=lambda bundle: ExtensionRunner(
                    bundle.extensions
                ),
                diagnostics_service=resolved_services.diagnostics_service,
            )
        ),
        get_resource_loader=lambda resolved_services: resolved_services.resource_loader,
        resource_loader_options=resource_loader_options,
        configure_resource_loader=lambda loader, options: loader.set_runtime_options(
            **dict(options)
        ),
        extension_flag_values=extension_flag_values,
    )


def audit_cwd_bound_services(
    *,
    session_manager: SessionManager,
    services: BootstrapServices,
    resource_bundle: ResourceBundle | None = None,
) -> CwdBoundServicesAudit:
    return _audit_cwd_bound_services(
        session_cwd=session_manager.get_cwd(),
        project_root=project_root_from_settings_base(
            services.settings_manager.project_base_dir
        ),
        resource_cwd=resource_bundle.cwd if resource_bundle is not None else None,
    )


def _create_agent_session(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | None = None,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    services: BootstrapServices | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    sandbox_workspace_writable: bool = True,
    delegated_execution_profile: DelegatedExecutionProfile | None = None,
) -> AgentSession:
    enable_multiagent_tools = (
        enable_multiagent
        and allowed_tool_names is None
        and normalize_no_tools(no_tools) is None
    )
    if delegated_execution_profile is not None:
        if tuple(allowed_tool_names or ()) != delegated_execution_profile.allowed_tools:
            raise ValueError(
                "child allowed tools must match its delegated execution profile"
            )
        if (
            approval_actor_id(approval_resolver)
            != delegated_execution_profile.approval_actor_id
        ):
            raise ValueError(
                "child approval actor must match its delegated execution profile"
            )
    services = services or create_services()
    multiagent_types = None
    resolved_append_system_prompt = tuple(append_system_prompt or ())
    if enable_multiagent:
        from loushang.coding.multiagent import (
            coding_agent_types,
            coding_multiagent_system_prompt,
        )

        multiagent_types = coding_agent_types()
        if enable_multiagent_tools:
            resolved_append_system_prompt = (
                *resolved_append_system_prompt,
                coding_multiagent_system_prompt(multiagent_types),
            )
    session_tool_registry = (
        _clone_workspace_tool_registry(tool_registry)
        if enable_multiagent_tools and tool_registry is not None
        else tool_registry
    )
    resolved_package_materializer = (
        package_materializer or _default_package_materializer(session_manager)
    )
    session_id = session_manager.get_header().conversation_id

    def _create_session(
        capability_runtime: CapabilityCompositionRuntime,
        agent: Agent,
        bundle: ResourceBundle,
        extension_runner: ExtensionRunner,
        registry: WorkspaceToolRegistry | None,
        initial_active_tool_names: list[str] | None,
        session_base_prompt: str,
        session_no_tools_mode: NoToolsMode | None,
    ) -> AgentSession:
        base_exec_service = services.exec_service or ExecService()
        sandbox_runtime = bind_coding_sandbox_runtime(
            workspace_root=session_manager.get_cwd(),
            writable_workspace=sandbox_workspace_writable,
            settings=services.settings_manager.get_sandbox_settings(),
            base_exec_service=base_exec_service,
            diagnostics_service=services.diagnostics_service,
            session_id=session_id,
            execution_profile=(
                delegated_execution_profile.execution_profile_ceiling
                if delegated_execution_profile is not None
                else None
            ),
        )
        child_session = AgentSession(
            agent=agent,
            session_manager=session_manager,
            settings_manager=services.settings_manager,
            model_registry=services.model_registry,
            resource_loader=services.resource_loader,
            resource_bundle=bundle,
            extension_runner=extension_runner,
            tool_registry=registry,
            allowed_tool_names=[]
            if session_no_tools_mode == "all"
            else allowed_tool_names,
            active_tool_names=initial_active_tool_names,
            default_activate_new_tools=(
                session_no_tools_mode != "all" and active_tool_names is None
            ),
            show_empty_tool_prompt=session_no_tools_mode == "all",
            base_prompt=session_base_prompt,
            diagnostics_service=services.diagnostics_service,
            session_start_event=session_start_event,
            package_materializer=resolved_package_materializer,
            exec_service=sandbox_runtime.exec_service,
            approval_resolver=approval_resolver,
            tool_policy_evaluator=tool_policy_evaluator,
            capability_runtime=capability_runtime,
            sandbox_runtime=sandbox_runtime,
            delegated_execution_profile=delegated_execution_profile,
        )
        return child_session

    result = _CODING_AGENT_PRODUCT_CONSTRUCTION.construct(
        services=services,
        package_materializer=resolved_package_materializer,
        session_id=session_id,
        cwd=session_manager.get_cwd(),
        extension_flag_values=extension_flag_values,
        explicit_system_prompt=system_prompt,
        append_system_prompt=resolved_append_system_prompt,
        model=model,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=session_tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        stream_fn=stream_fn,
        convert_to_llm=lambda messages: context_items_to_model_messages(
            messages,
            image_placeholder=(
                "Image reading is disabled."
                if services.settings_manager.get_block_images()
                else None
            ),
        ),
        agent_factory=agent_factory,
        session_factory=_create_session,
        on_default_model_unavailable=lambda selection, error, reason: (
            record_default_model_unavailable(
                cast(ModelSelection, selection),
                error=error,
                reason=reason,
                diagnostics_service=services.diagnostics_service,
                session_id=session_id,
            )
        ),
        set_scoped_models=lambda session, scoped_models: session.set_scoped_models(
            cast(list[dict[str, object]], scoped_models)
        ),
    )
    result.session.cwd_bound_services_audit = (
        result.configuration.cwd_bound_services_audit
    )
    if enable_multiagent:
        from loushang.coding.multiagent import (
            CodingSubagentFactory,
            install_coding_multiagent_session,
        )
        from loushang.coding.worktree import CodingGitWorktreeLeasePort

        assert multiagent_types is not None
        install_coding_multiagent_session(
            result.session,
            child_factory=CodingSubagentFactory(
                session_dir=session_manager.get_session_dir(),
                cwd=session_manager.get_cwd(),
                tool_registry=(session_tool_registry or WorkspaceToolRegistry()),
                default_model_provider=lambda: result.session.agent.model,
                services=services,
                approval_resolver=approval_resolver,
                workspace_leases=CodingGitWorktreeLeasePort(
                    cwd=session_manager.get_cwd(),
                    exec_service=services.exec_service,
                ),
                runtime_builder=partial(
                    _create_agent_session_runtime,
                    stream_fn=stream_fn,
                    agent_factory=agent_factory,
                    tool_policy_evaluator=tool_policy_evaluator,
                ),
            ),
            agent_types=multiagent_types,
            register_tools=enable_multiagent_tools,
        )
    return result.session


def create_agent_session(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | None = None,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    services: BootstrapServices | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
) -> AgentSession:
    return _create_agent_session(
        session_manager=session_manager,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        services=services,
        agent_factory=agent_factory,
        session_start_event=session_start_event,
        package_materializer=package_materializer,
        append_system_prompt=append_system_prompt,
        extension_flag_values=extension_flag_values,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        sandbox_workspace_writable=True,
    )


def create_agent_session_from_services(
    *,
    agent_services: AgentSessionServices,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | None = None,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
) -> CreateAgentSessionResult:
    extension_flag_values = (
        agent_services.extension_runner.get_flag_values()
        if agent_services.extension_runner is not None
        else None
    )
    return create_agent_session_result(
        session_manager=session_manager,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        services=agent_services.services,
        agent_factory=agent_factory,
        session_start_event=session_start_event,
        package_materializer=package_materializer,
        append_system_prompt=append_system_prompt,
        extension_flag_values=extension_flag_values,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
    )


def create_agent_session_result(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | None = None,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    services: BootstrapServices | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
) -> CreateAgentSessionResult:
    resolved_services = services or create_services()
    session = create_agent_session(
        session_manager=session_manager,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        services=resolved_services,
        agent_factory=agent_factory,
        session_start_event=session_start_event,
        package_materializer=package_materializer,
        append_system_prompt=append_system_prompt,
        extension_flag_values=extension_flag_values,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
    )
    return build_standard_agent_session_result(
        session,
        resource_bundle=session.resource_bundle,
        diagnostics_service=resolved_services.diagnostics_service,
        session_id=session.session_id,
        cwd_bound_services_audit=session.cwd_bound_services_audit,
    )


def _default_package_materializer(
    session_manager: SessionManager,
) -> PackageMaterializer:
    return PackageMaterializer(
        install_root=resolve_session_package_install_root(
            session_dir=session_manager.get_session_dir(),
            cwd=session_manager.get_cwd(),
        ),
        backend=GitPackageMaterializerBackend(),
    )


def _source_identity_startup_check(cwd: str) -> StartupCheckResult:
    return StartupCheckResult(
        name="executable_source_identity",
        ok=True,
        code="executable_source_identity",
        level="info",
        message="Executable and import source identity captured.",
        source_path=Path(__file__).resolve(strict=False),
        details=coding_runtime_identity(cwd=cwd),
    )


_CODING_AGENT_PRODUCT_CONSTRUCTION = AgentProductConstructionBinding[
    Agent,
    AgentSession,
    ResourceBundle,
    ExtensionRunner,
    WorkspaceToolRegistry,
](
    default_system_prompt=DEFAULT_CODING_SYSTEM_PROMPT,
    bind_capabilities=lambda: bind_capability_composition_runtime(
        CODING_CAPABILITY_PROFILE
    ),
    create_extension_runtime=lambda bundle: ExtensionRunner(
        cast(Any, bundle.extensions)
    ),
    source_identity_check=_source_identity_startup_check,
    list_tool_definitions=lambda runner: runner.list_tool_definitions(),
    get_tool_source_info=lambda runner, name: runner.get_tool_source_info(name),
    product_tool_pack_id="coding.registry",
    extension_tool_pack_id="coding.extensions",
)


def _create_agent_session_runtime(
    *,
    session_dir: Path,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | None = None,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    services: BootstrapServices | None = None,
    services_factory: ServicesFactory | None = None,
    agent_factory: AgentFactory = Agent,
    persist: bool = True,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    sandbox_workspace_writable: bool = True,
    delegated_execution_profile: DelegatedExecutionProfile | None = None,
) -> AgentSessionRuntime:
    fixed_services = services if services is not None else create_services()
    return build_agent_product_session_runtime(
        session_dir=Path(session_dir),
        runtime_factory=AgentSessionRuntime,
        fixed_services=fixed_services,
        build_session=lambda session_manager, session_services, start_event: (
            _create_agent_session(
                session_manager=cast(SessionManager, session_manager),
                model=model,
                stream_fn=stream_fn,
                system_prompt=system_prompt,
                thinking_level=thinking_level,
                tools=tools,
                tool_registry=tool_registry,
                allowed_tool_names=allowed_tool_names,
                active_tool_names=active_tool_names,
                no_tools=no_tools,
                services=session_services,
                agent_factory=agent_factory,
                session_start_event=cast(SessionStartEvent | None, start_event),
                append_system_prompt=append_system_prompt,
                approval_resolver=approval_resolver,
                tool_policy_evaluator=tool_policy_evaluator,
                enable_multiagent=enable_multiagent,
                sandbox_workspace_writable=sandbox_workspace_writable,
                delegated_execution_profile=delegated_execution_profile,
            )
        ),
        session_cwd=lambda manager: cast(SessionManager, manager).get_cwd(),
        services_factory=services_factory,
        persist=persist,
        diagnostics_service=fixed_services.diagnostics_service,
        on_non_persistent_session=lambda session: setattr(
            session.agent,
            "session_id",
            None,
        ),
    )


def create_agent_session_runtime(
    *,
    session_dir: Path,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | None = None,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    services: BootstrapServices | None = None,
    services_factory: ServicesFactory | None = None,
    agent_factory: AgentFactory = Agent,
    persist: bool = True,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
) -> AgentSessionRuntime:
    return _create_agent_session_runtime(
        session_dir=session_dir,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        services=services,
        services_factory=services_factory,
        agent_factory=agent_factory,
        persist=persist,
        append_system_prompt=append_system_prompt,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        sandbox_workspace_writable=True,
    )


def _clone_workspace_tool_registry(
    registry: WorkspaceToolRegistry,
) -> WorkspaceToolRegistry:
    """Keep session-bound tool closures out of a shared Product registry."""

    cloned = WorkspaceToolRegistry()
    for contribution in registry.list_contributions():
        cloned.register_tool(
            contribution.definition,
            enabled=contribution.enabled,
            source_info=contribution.source_info,
        )
    return cloned
