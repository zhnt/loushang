from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from loushang.agent import Agent, StreamFn, ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.coding._resource_catalog_shadow import (
    prepare_coding_initial_resource_catalog_shadow_adapter,
)
from loushang.coding.capabilities import (
    CODING_LSP_CAPABILITY,
    coding_capability_mount_mode,
)
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.diagnostics.profile import coding_runtime_identity
from loushang.coding.lsp.discovery import (
    coding_lsp_config_paths,
    default_lsp_environment,
    discover_lsp_catalog,
)
from loushang.coding.lsp.model import LspServerDefinition
from loushang.coding.lsp.ports import WorkspaceTextReader
from loushang.coding.lsp.runtime import (
    CodingLspRuntime,
    DeferredCodingLspRuntime,
    _bind_coding_lsp_runtime_from_launcher,
)
from loushang.coding.lsp.tool_pack import register_coding_lsp_tools
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE, CODING_PRODUCT_ID
from loushang.coding.prompt.defaults import DEFAULT_CODING_SYSTEM_PROMPT
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.runtime import AgentSessionRuntime
from loushang.coding.runtime_capability_admission import (
    bind_coding_side_question,
    resolve_coding_capability_profile,
)
from loushang.coding.sandbox import (
    bind_coding_sandbox_runtime,
    coding_workspace_execution_profile,
)
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.coding.workspace_operations import CodingWorkspaceOperations
from loushang.harness.approval import (
    InteractiveApprovalResolver,
    approval_actor_id,
)
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    constrain_execution_profile,
)
from loushang.harness.bootstrap import (
    create_standard_resource_bootstrap_runtime,
)
from loushang.harness.capabilities import (
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
)
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
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
from loushang.harness.session.legacy_side_question import LegacySideQuestionBinding
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import context_items_to_model_messages
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.operations import LOCAL_TOOL_OPERATIONS
from loushang.harness.workspace.process import (
    AuthorizedProcessLauncher,
    ProcessHandle,
    ProcessLaunchRequest,
)

AgentFactory = Callable[..., Agent]
ServicesFactory = Callable[[str], "BootstrapServices"]
NoToolsMode = Literal["all", "builtin"]
ExtensionFlagValues = Mapping[str, bool | str]
CwdBoundServicesAuditIssue = _CwdBoundServicesAuditIssue


class _DeferredWorkspaceProcessLauncher:
    def __init__(self) -> None:
        self._launcher: AuthorizedProcessLauncher | None = None

    def bind(self, launcher: AuthorizedProcessLauncher) -> None:
        if self._launcher is not None:
            raise RuntimeError("workspace process launcher is already bound")
        self._launcher = launcher

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle:
        launcher = self._launcher
        if launcher is None:
            raise RuntimeError("workspace process launcher is not yet bound")
        return await launcher.start(
            request,
            correlation_id=correlation_id,
            signal=signal,
        )


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
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
    enable_initial_resource_catalog_shadow: bool = False,
    initial_resource_catalog_package_admissions: Sequence[Any] = (),
) -> AgentSession:
    if not isinstance(enable_initial_resource_catalog_shadow, bool):
        raise TypeError("initial Resource Catalog shadow flag must be a bool")
    package_resource_admissions = tuple(initial_resource_catalog_package_admissions)
    if package_resource_admissions and not enable_initial_resource_catalog_shadow:
        raise ValueError(
            "initial Resource Catalog package admissions require the shadow"
        )
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
    lsp_mode = coding_capability_mount_mode(
        services.settings_manager,
        CODING_LSP_CAPABILITY,
    )
    resolved_lsp_environment = (
        dict(lsp_baseline_environment)
        if lsp_baseline_environment is not None
        else default_lsp_environment()
    )
    lsp_enabled_for_session = (
        lsp_mode != "disabled" and normalize_no_tools(no_tools) != "all"
    )
    global_lsp_config, project_lsp_config = coding_lsp_config_paths(
        services.settings_manager,
        workspace_root=session_manager.get_cwd(),
    )
    resolved_lsp_definitions = (
        discover_lsp_catalog(
            workspace_root=session_manager.get_cwd(),
            baseline_environment=resolved_lsp_environment,
            explicit_definitions=tuple(lsp_definitions),
            global_config_path=global_lsp_config,
            project_config_path=project_lsp_config,
        ).definitions
        if lsp_enabled_for_session
        else ()
    )
    lsp_slot = DeferredCodingLspRuntime() if lsp_enabled_for_session else None
    # Restored sessions carry historical transcript.  A previous run may have
    # been interrupted between a tool call and its result, leaving an unpaired
    # toolCall in the transcript.  Force repair pairing for such sessions so
    # resume recovers automatically instead of raising
    # "Missing tool results before next message".  New sessions have no
    # history and stay on the (global) default.
    if len(session_manager.get_entries()) > 0:
        base_factory = agent_factory

        def _resume_agent_factory(**kwargs: object) -> Agent:
            from loushang.ai.options import CallOptions

            call_options = kwargs.get("call_options")
            if call_options is None:
                kwargs["call_options"] = CallOptions(pairing_mode="repair")
            else:
                kwargs["call_options"] = replace(
                    cast(CallOptions, call_options), pairing_mode="repair"
                )
            return base_factory(**kwargs)

        agent_factory = _resume_agent_factory
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
        tool_registry.copy()
        if (enable_multiagent_tools or lsp_slot is not None)
        and tool_registry is not None
        else tool_registry
    )
    construction_tools = tools
    if lsp_slot is not None:
        if session_tool_registry is None:
            session_tool_registry = WorkspaceToolRegistry()
            for definition in tools or ():
                session_tool_registry.register_tool(definition)
            if tools is not None:
                construction_tools = None
        register_coding_lsp_tools(
            session_tool_registry,
            runtime=lsp_slot,
            mode=lsp_mode,
        )
    resolved_package_materializer = (
        package_materializer or _default_package_materializer(session_manager)
    )
    session_id = session_manager.get_header().conversation_id

    def _create_session(
        capability_runtime: StagedResourceCompositionCandidate,
        side_question_binding: LegacySideQuestionBinding | None,
        agent: Agent,
        bundle: ResourceBundle,
        extension_runner: ExtensionRunner,
        registry: WorkspaceToolRegistry | None,
        initial_active_tool_names: list[str] | None,
        session_base_prompt: str,
        session_no_tools_mode: NoToolsMode | None,
    ) -> AgentSession:
        resource_catalog_shadow_adapter = None
        if enable_initial_resource_catalog_shadow:
            resource_catalog_shadow_adapter = (
                prepare_coding_initial_resource_catalog_shadow_adapter(
                    services.resource_loader,
                    disabled_skills=(
                        services.settings_manager.get_settings().disabled_skills
                    ),
                    package_resource_admissions=package_resource_admissions,
                )
            )
        base_exec_service = services.exec_service or ExecService()
        workspace_root_path = Path(session_manager.get_cwd()).resolve()
        workspace_execution_profile = (
            coding_workspace_execution_profile(
                workspace_root_path,
                writable=sandbox_workspace_writable,
            )
            if workspace_root_path.is_dir()
            else EffectiveExecutionProfile(
                readable_roots=(workspace_root_path,),
                writable_roots=(workspace_root_path,)
                if sandbox_workspace_writable
                else (),
                network="allowed",
            )
        )
        requested_profiles = (
            getattr(base_exec_service, "execution_profile", None),
            (
                delegated_execution_profile.execution_profile_ceiling
                if delegated_execution_profile is not None
                else None
            ),
        )
        for requested_profile in requested_profiles:
            if requested_profile is None:
                continue
            if not isinstance(requested_profile, EffectiveExecutionProfile):
                raise TypeError(
                    "Coding workspace execution ceiling must be an "
                    "EffectiveExecutionProfile"
                )
            workspace_execution_profile = constrain_execution_profile(
                workspace_execution_profile,
                requested_profile,
            )
        sandbox_runtime = bind_coding_sandbox_runtime(
            workspace_root=session_manager.get_cwd(),
            writable_workspace=sandbox_workspace_writable,
            settings=services.settings_manager.get_sandbox_settings(),
            base_exec_service=base_exec_service,
            diagnostics_service=services.diagnostics_service,
            session_id=session_id,
            execution_profile=workspace_execution_profile,
        )
        process_session: AgentSession | None = None

        async def emit_process_audit_event(event: Mapping[str, object]) -> None:
            if process_session is None:
                raise RuntimeError("Coding workspace Session is not yet bound")
            await process_session.emit_product_tool_audit_event(event)

        authorized_process_launcher = sandbox_runtime.bind_process_launcher(
            ProcessExecutionScope(
                policy_evaluator=tool_policy_evaluator,
                approval_resolver=approval_resolver,
                audit_sink=emit_process_audit_event,
                execution_profile_ceiling=workspace_execution_profile,
            )
        )
        workspace_root = str(workspace_root_path)
        workspace_binding_fingerprint = hashlib.sha256(
            "\0".join(
                (
                    "coding.workspace.standard.v1",
                    *(str(path) for path in workspace_execution_profile.readable_roots),
                    "--writable--",
                    *(str(path) for path in workspace_execution_profile.writable_roots),
                    "--denied--",
                    *(str(path) for path in workspace_execution_profile.denied_roots),
                    f"network:{workspace_execution_profile.network}",
                )
            ).encode("utf-8")
        ).hexdigest()
        workspace_binding = workspace_capability_provider_binding(
            operations=CodingWorkspaceOperations(
                root=workspace_root_path,
                operations=LOCAL_TOOL_OPERATIONS,
                execution_profile=workspace_execution_profile,
            ),
            process_launcher=authorized_process_launcher,
            scope_instance_id=f"workspace:{workspace_root}",
            binding_input_fingerprint=workspace_binding_fingerprint,
            provider_id="coding.workspace.standard",
            source_id="coding",
        )
        lsp_runtime: CodingLspRuntime | None = None
        deferred_lsp_launcher: _DeferredWorkspaceProcessLauncher | None = None
        if lsp_slot is not None:
            deferred_lsp_launcher = _DeferredWorkspaceProcessLauncher()
            lsp_runtime = _bind_coding_lsp_runtime_from_launcher(
                workspace_root=session_manager.get_cwd(),
                definitions=resolved_lsp_definitions,
                process_launcher=deferred_lsp_launcher,
                read_text=lsp_read_text or _read_lsp_workspace_text,
                baseline_environment=resolved_lsp_environment,
            )
            lsp_slot.bind(lsp_runtime)

        def construct_child_session(
            initial_resource_catalog_bootstrap: Any | None = None,
        ) -> AgentSession:
            return AgentSession(
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
                side_question_binding=side_question_binding,
                sandbox_runtime=sandbox_runtime,
                lsp_runtime=lsp_runtime,
                delegated_execution_profile=delegated_execution_profile,
                workspace_capability_binding=workspace_binding,
                initial_resource_catalog_bootstrap=(initial_resource_catalog_bootstrap),
            )

        if resource_catalog_shadow_adapter is not None:
            child_session = resource_catalog_shadow_adapter.construct_session(
                product_id=CODING_PRODUCT_ID,
                session_id=session_id,
                base_resource_bundle=bundle,
                construct=construct_child_session,
            )
        else:
            child_session = construct_child_session()
        process_session = child_session
        if deferred_lsp_launcher is not None:
            deferred_lsp_launcher.bind(child_session.get_workspace_process_launcher())
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
        tools=construction_tools,
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
                selection,
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
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
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
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
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
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
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
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
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
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
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
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
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


def _read_lsp_workspace_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    ExtensionRunner,
](
    default_system_prompt=DEFAULT_CODING_SYSTEM_PROMPT,
    bind_capabilities=lambda: stage_resource_composition_candidate(
        CODING_CAPABILITY_PROFILE
    ),
    create_extension_runtime=lambda bundle: ExtensionRunner(bundle.extensions),
    source_identity_check=_source_identity_startup_check,
    list_tool_definitions=lambda runner: runner.list_tool_definitions(),
    get_tool_source_info=lambda runner, name: runner.get_tool_source_info(name),
    bind_session_side_question=bind_coding_side_question,
    resolve_session_capability_profile=lambda runner: (
        resolve_coding_capability_profile(runner.active_extensions).profile
    ),
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
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
) -> AgentSessionRuntime:
    fixed_services = services if services is not None else create_services()
    fixed_lsp_definitions = tuple(lsp_definitions)
    fixed_lsp_environment = (
        dict(lsp_baseline_environment) if lsp_baseline_environment is not None else None
    )
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
                lsp_definitions=fixed_lsp_definitions,
                lsp_baseline_environment=fixed_lsp_environment,
                lsp_read_text=lsp_read_text,
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
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
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
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
    )
