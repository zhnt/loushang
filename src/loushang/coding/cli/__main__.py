from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO, cast

from loushang.ai.model import (
    model_selection_ref,
    parse_model_selection_reference,
)
from loushang.ai.model.registry import get_default_model_registry
from loushang.coding.adapters.harnesswork import (
    create_coding_work_runtime,
    run_coding_work_channel,
)
from loushang.coding.agent_invocation import register_coding_agent_delegate_tool
from loushang.coding.arch.tool import INSPECT_IMPORT_GRAPH_TOOL_NAME
from loushang.coding.arch.tool_pack import register_coding_arch_tools
from loushang.coding.bootstrap import (
    BootstrapServices,
    create_agent_session_runtime,
    create_agent_session_services,
    create_services,
)
from loushang.coding.capabilities import (
    CODING_ARCH_CAPABILITY,
    coding_capability_mount_mode,
)
from loushang.coding.cli.args import CliArgs, ExtensionFlag, help_text, parse_args
from loushang.coding.cli.lsp import extract_lsp_argv, run_coding_lsp_command
from loushang.coding.cli.multiagent import run_coding_multiagent_command
from loushang.coding.cli.workspace import (
    extract_workspace_argv,
    run_coding_workspace_command,
)
from loushang.coding.continuity import (
    bind_coding_continuity,
    shutdown_coding_continuity,
)
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.diagnostics.profile import (
    coding_diagnostic_source,
    coding_runtime_identity,
    format_coding_runtime_identity_text,
)
from loushang.coding.domain import (
    CodingDomainApp,
    CodingDomainPreparedTurn,
    CodingDomainRequest,
)
from loushang.coding.model_selection import (
    apply_model_selection,
    persistence_warning_message,
)
from loushang.coding.prompt_command import (
    run_prompt_command,
    run_prompt_plan_command,
)
from loushang.coding.resource_runtime import collect_coding_package_entries
from loushang.coding.tool_pack import register_coding_builtin_tools
from loushang.coding.ui.mode import run_coding_tui
from loushang.coding.workflow import run_prompt_steps_workflow
from loushang.harness.approval import (
    ApprovalResolver,
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
    configure_persistent_approval_policy,
)
from loushang.harness.cli import (
    AgentCliApplicationBinding,
    AgentCliApplicationState,
    AgentCliHostRunners,
    AgentCliLaunchOverlay,
    AgentCliSessionHostBinding,
    AgentCliStatePreparationContext,
    AgentCliStatePreparationPorts,
    CliBootstrapContext,
    CliLaunchPlan,
    CliOperationInsertion,
    CliOperationStage,
    CliParseResult,
    CliPhaseResult,
    CliSessionContext,
    MethodListingError,
    MethodListingRequest,
    PreparedAgentCliHostInput,
    agent_cli_launch_plan,
    agent_cli_output_mode,
    agent_image_auto_resize,
    agent_standard_cli_operation_request,
    agent_tool_selection,
    capture_cli_parse,
    configure_agent_cli_session,
    configure_agent_resource_loader,
    cwd_bound_services_factory,
    distribution_version,
    extract_multiagent_argv,
    format_agent_cli_help,
    prepare_agent_cli_host_input,
    project_domain_turns_to_cli,
    resolve_agent_prompt_input,
    resolve_effective_tui,
    run_agent_cli_application,
    run_diagnostics_export_operation,
    run_method_listing,
    run_package_listing_operation,
    run_resource_toggle_operation,
    run_standard_cli_operations,
)
from loushang.harness.cli import (
    format_cli_error as _format_cli_error,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.continuity import consume_prepared_activation
from loushang.harness.diagnostics.observability_runtime import (
    session_observability_context,
    startup_observability_context,
)
from loushang.harness.host.product_host import ProductHostLifecycle, stream_is_tty
from loushang.harness.host.rpc import run_rpc_host
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.resources.packages import (
    record_package_source_policy_denial,
)
from loushang.harness.resources.packages.security import PackageSecurityPolicy
from loushang.harness.resources.plugins import is_remote_plugin_source
from loushang.harness.scenario import run_fake_workflow_cli
from loushang.harness.tools.agent_delegate import AGENT_DELEGATE_TOOL_NAME
from loushang.harness.tools.workspace import (
    WorkspaceToolRuntimeSettings,
    workspace_tool_runtime_settings,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harnesstui.continuity import run_continuity_picker
from loushang.harnesstui.conversation.agent_binding import (
    run_agent_mode,
    run_agent_plain_mode,
    run_agent_plain_plan_mode,
)
from loushang.harnesswork import (
    create_work_event_log,
    run_work_log_inspection_operation,
)
from loushang.harnesswork.integrations.session import (
    SessionWorkHostPort,
    project_prepared_session_work_turns,
)
from loushang.method import (
    MethodCompiler,
    MethodContext,
    MethodLoader,
    resolve_method_policy,
)

_WORK_LOG_INSPECT_LIMIT = 20


def build_default_services(project_root: Path) -> BootstrapServices:
    settings_manager = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(project_root),
    )
    return create_services(
        ai_model_registry=get_default_model_registry(),
        settings_manager=settings_manager,
    )


def build_builtin_tool_registry(
    *,
    diagnostics_service: object | None = None,
    settings_manager: object | None = None,
    approval_resolver: ApprovalResolver | None = None,
    runtime_settings: WorkspaceToolRuntimeSettings | None = None,
) -> WorkspaceToolRegistry:
    resolved_runtime_settings = runtime_settings or workspace_tool_runtime_settings(
        settings_manager, policy_factory=PolicyEngine
    )
    resolved_approval_resolver = (
        approval_resolver
        if approval_resolver is not None
        else resolved_runtime_settings.approval_resolver
    )
    registry = WorkspaceToolRegistry()
    configure_persistent_approval_policy(
        resolved_approval_resolver,
        settings_manager,
    )
    get_external_tool_policy = getattr(
        settings_manager, "get_external_tool_policy", None
    )
    get_shell_path = getattr(settings_manager, "get_shell_path", None)
    get_shell_command_prefix = getattr(
        settings_manager,
        "get_shell_command_prefix",
        None,
    )
    register_coding_builtin_tools(
        registry,
        diagnostics_service=diagnostics_service,
        external_tool_policy=get_external_tool_policy()
        if callable(get_external_tool_policy)
        else None,
        shell_path=get_shell_path() if callable(get_shell_path) else None,
        command_prefix=(
            get_shell_command_prefix()
            if callable(get_shell_command_prefix)
            else None
        ),
    )
    register_coding_arch_tools(
        registry,
        mode=coding_capability_mount_mode(
            settings_manager,
            CODING_ARCH_CAPABILITY,
        ),
    )
    return registry


def default_runtime_builder(
    *,
    args: CliArgs,
    cwd: Path,
    session_dir: Path,
    services: BootstrapServices,
    tool_registry: WorkspaceToolRegistry,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: object | None = None,
):
    if not any(
        definition.name == INSPECT_IMPORT_GRAPH_TOOL_NAME
        for definition in tool_registry.list_definitions()
    ):
        register_coding_arch_tools(
            tool_registry,
            mode=coding_capability_mount_mode(
                getattr(services, "settings_manager", None),
                CODING_ARCH_CAPABILITY,
            ),
        )
    allowed_tool_names, active_tool_names = agent_tool_selection(args)
    runtime_tool_registry = tool_registry.copy()
    if (
        not getattr(args, "no_builtin_tools", False)
        and allowed_tool_names is not None
        and AGENT_DELEGATE_TOOL_NAME in allowed_tool_names
    ):
        registered_parent_tools = tuple(
            definition.name
            for definition in runtime_tool_registry.list_enabled_definitions()
            if allowed_tool_names is None or definition.name in allowed_tool_names
        )
        register_coding_agent_delegate_tool(
            runtime_tool_registry,
            parent_allowed_tools=registered_parent_tools,
        )
    resource_loader_options = configure_agent_resource_loader(
        services.resource_loader,
        args,
    )
    services_factory = cwd_bound_services_factory(
        services,
        resource_loader_options,
        create_services=create_agent_session_services,
    )
    return create_agent_session_runtime(
        session_dir=session_dir,
        services=services,
        services_factory=services_factory,
        tool_registry=runtime_tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        persist=not args.no_session,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=True,
    )


async def run_cli(
    argv: list[str] | tuple[str, ...] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    cwd: str | Path | None = None,
    services: BootstrapServices | Any | None = None,
    runtime_builder=default_runtime_builder,
    mode_runner=run_agent_mode,
    prompt_runner=run_prompt_command,
    workflow_runner=run_prompt_steps_workflow,
    print_runner=run_agent_plain_mode,
    rpc_runner=run_rpc_host,
    channel_runner=run_coding_work_channel,
    tui_runner=run_coding_tui,
    continuity_runner=run_continuity_picker,
    multiagent_runner=run_coding_multiagent_command,
    workspace_runner=run_coding_workspace_command,
    lsp_runner=run_coding_lsp_command,
) -> int:
    raw_argv = tuple(argv or ())
    workspace_argv = extract_workspace_argv(raw_argv)
    if workspace_argv is not None:
        return await workspace_runner(
            workspace_argv,
            stdin=stdin or sys.stdin,
            stdout=stdout or sys.stdout,
            stderr=stderr or sys.stderr,
            cwd=cwd,
        )
    lsp_argv = extract_lsp_argv(raw_argv)
    if lsp_argv is not None:
        return await lsp_runner(
            lsp_argv,
            stdin=stdin or sys.stdin,
            stdout=stdout or sys.stdout,
            stderr=stderr or sys.stderr,
            cwd=cwd,
            services=services,
            build_services=build_default_services,
        )
    multiagent_argv = extract_multiagent_argv(raw_argv)
    if multiagent_argv is not None:
        return await multiagent_runner(
            multiagent_argv,
            stdin=stdin or sys.stdin,
            stdout=stdout or sys.stdout,
            stderr=stderr or sys.stderr,
            cwd=cwd,
            services=services,
            build_services=build_default_services,
            build_tool_registry=build_builtin_tool_registry,
        )
    host_lifecycle = ProductHostLifecycle.resolve(
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
    state_preparation_ports = _coding_state_preparation_ports(workflow_runner)
    host_binding = AgentCliSessionHostBinding[
        CliArgs,
        AgentCliApplicationState[CliArgs],
    ](
        stream_is_tty=stream_is_tty,
        resolve_work_event_log=lambda args, project_root: create_work_event_log(
            args.work_log, project_root
        ),
        build_work_runtime=lambda session, event_log: create_coding_work_runtime(
            session=session,
            event_log=event_log,
            session_id=lambda: session.session_id,
        ),
        bind_plain_work_port=SessionWorkHostPort,
        workflow_path=lambda args: (
            Path(args.prompt_steps) if args.prompt_steps is not None else None
        ),
        workflow_output_mode=agent_cli_output_mode,
        prepare_host_input=_prepare_coding_host_input,
        observability_context=lambda args, session, project_root, mode: (
            session_observability_context(
                args=args,
                session=session,
                cwd=project_root,
                mode=mode,
                source_resolver=coding_diagnostic_source,
            )
        ),
    )
    host_runners = AgentCliHostRunners(
        run_turns=host_lifecycle.run_turns,
        mode=mode_runner,
        prompt=prompt_runner,
        workflow=workflow_runner,
        plain=print_runner,
        rpc=rpc_runner,
        channel=channel_runner,
        tui=tui_runner,
        prompt_plan=run_prompt_plan_command,
        plain_plan=run_agent_plain_plan_mode,
        default_mode=run_agent_mode,
        default_prompt=run_prompt_command,
        default_plain=run_agent_plain_mode,
        default_rpc=run_rpc_host,
    )
    binding = AgentCliApplicationBinding(
        parse_args=_parse_application_args,
        launch_plan=_cli_launch_plan,
        state_ports=state_preparation_ports,
        runtime_builder=runtime_builder,
        format_help=_help_text,
        package_version=lambda: distribution_version("loushang"),
        runtime_identity=lambda project_root: coding_runtime_identity(cwd=project_root),
        format_runtime_identity=format_coding_runtime_identity_text,
        validated_operation=_run_work_log_inspect,
        startup_context=lambda context, state: startup_observability_context(
            args=context.args,
            services=state.services,
            cwd=context.project_root,
            source_resolver=coding_diagnostic_source,
        ),
        configure_session=_configure_coding_cli_session,
        session_operations=_run_coding_cli_operations,
        run_host=host_binding.bind(host_runners),
        host_lifecycle=host_lifecycle,
        services=services,
        session_resolution_error=_coding_session_resolution_error,
        pre_session_bootstrap=lambda context: _run_coding_pre_session_bootstrap(
            context,
            continuity_runner=continuity_runner,
        ),
    )
    return await run_agent_cli_application(
        raw_argv,
        binding=binding,
        cwd=cwd,
    )


def _coding_session_resolution_error(context) -> str | None:
    args = context.state.args
    if args.resume is True and not resolve_effective_tui(
        context.bootstrap.launch_plan,
        stdin_is_tty=stream_is_tty(context.bootstrap.stdin),
        stdout_is_tty=stream_is_tty(context.bootstrap.stdout),
    ):
        return (
            "--resume without a session reference requires an interactive TUI; "
            "use --continue for the latest session or --resume <session>"
        )
    return None


async def _run_coding_pre_session_bootstrap(
    context,
    *,
    continuity_runner,
) -> CliPhaseResult[object] | None:
    args = context.state.args
    if args.resume is not True:
        return None
    if not resolve_effective_tui(
        context.bootstrap.launch_plan,
        stdin_is_tty=stream_is_tty(context.bootstrap.stdin),
        stdout_is_tty=stream_is_tty(context.bootstrap.stdout),
    ):
        raise RuntimeError(
            "--resume without a session reference requires an interactive TUI; "
            "use --continue for the latest session or --resume <session>"
        )

    composition = bind_coding_continuity(context.runtime)
    activated = False
    try:

        async def activate(target):
            lease = await composition.hub.prepare(target)
            return await consume_prepared_activation(lease)

        selection = await continuity_runner(
            hub=composition.hub,
            activate=activate,
            stdin=context.bootstrap.stdin,
            stdout=context.bootstrap.stdout,
            keybindings=_continuity_keybindings(context.state.settings_manager),
        )
        if selection is None:
            return CliPhaseResult.exit(0)
        result = selection.activation_result
        session = getattr(result, "current", None)
        if session is None:
            getter = getattr(context.runtime, "get_current_session", None)
            session = getter() if callable(getter) else None
        if session is None:
            raise RuntimeError(
                "Continuity activation did not publish a Product session"
            )
        activated = True
        return CliPhaseResult.continue_with(session)
    finally:
        await composition.dispose()
        if not activated:
            await shutdown_coding_continuity(context.runtime)


def _continuity_keybindings(settings_manager: object | None) -> object | None:
    getter = getattr(settings_manager, "get_keybindings", None)
    return getter() if callable(getter) else None


def _parse_application_args(
    argv: Sequence[str],
    stderr: TextIO,
    extension_flags: Mapping[str, object] | None,
    allow_unknown: bool,
) -> CliParseResult[CliArgs]:
    return capture_cli_parse(
        parse_args,
        argv,
        stderr,
        cast(
            Mapping[str, ExtensionFlag] | None,
            extension_flags,
        ),
        allow_unknown,
    )


def _coding_state_preparation_ports(
    workflow_runner: Any,
) -> AgentCliStatePreparationPorts[CliArgs]:
    return AgentCliStatePreparationPorts(
        build_services=build_default_services,
        product_catalog_operation=lambda args: any(
            (
                args.list_methods,
                args.show_method is not None,
                args.show_method_plan is not None,
            )
        ),
        pre_runtime_operation=lambda context: _run_coding_pre_runtime_operation(
            context,
            workflow_runner=workflow_runner,
        ),
        build_empty_tool_registry=WorkspaceToolRegistry,
        build_tool_registry=lambda services, runtime_settings, approval_resolver: (
            build_builtin_tool_registry(
                diagnostics_service=getattr(
                    services,
                    "diagnostics_service",
                    None,
                ),
                settings_manager=getattr(services, "settings_manager", None),
                approval_resolver=cast(ApprovalResolver | None, approval_resolver),
                runtime_settings=runtime_settings,
            )
        ),
        policy_factory=PolicyEngine,
        build_interactive_approval_resolver=lambda: InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        ),
        run_resource_toggle=run_resource_toggle_operation,
        evaluate_plugin_source=_package_source_policy_reason,
        is_remote_plugin_source=is_remote_plugin_source,
        on_policy_denied=lambda services, package_source, reason: (
            record_package_source_policy_denial(
                getattr(services, "diagnostics_service", None),
                package_source=package_source,
                reason=reason,
            )
        ),
        format_error=_format_cli_error,
    )


async def _run_coding_pre_runtime_operation(
    context: AgentCliStatePreparationContext[CliArgs],
    *,
    workflow_runner: Any,
) -> int | None:
    args = context.args
    if args.capability_modes:
        settings_manager = getattr(context.services, "settings_manager", None)
        apply_overrides = getattr(settings_manager, "apply_overrides", None)
        if callable(apply_overrides):
            apply_overrides({"capabilities": dict(args.capability_modes)})
    diagnostics_result = run_diagnostics_export_operation(
        requested=args.diag_export,
        project_root=context.project_root,
        session_dir=context.session_dir,
        output=args.diag_output,
        diagnostics_service=getattr(
            context.services,
            "diagnostics_service",
            None,
        ),
        debug_latest_path=args.debug_file,
        trace_latest_path=args.trace_file,
        stdout=context.stdout,
        stderr=context.stderr,
        format_error=_format_cli_error,
    )
    if diagnostics_result is not None or args.prompt_steps is None:
        return diagnostics_result
    return await run_fake_workflow_cli(
        args.prompt_steps,
        project_root=context.project_root,
        runner=workflow_runner,
        stdout=context.stdout,
        stderr=context.stderr,
        verbose=args.verbose,
        output_mode=agent_cli_output_mode(args),
        format_error=_format_cli_error,
    )


async def _configure_coding_cli_session(
    context: CliSessionContext[
        CliArgs,
        AgentCliApplicationState[CliArgs],
        object,
        object,
    ],
) -> int | None:
    args = context.args
    return await configure_agent_cli_session(
        context.session,
        session_name=args.session_name,
        extension_flag_values=args.extension_flag_values,
        model_selection=None,
        resolve_model_selection=lambda: parse_model_selection_reference(
            args.model,
            provider=args.provider,
            registry=getattr(
                getattr(context.state.services, "model_registry", None),
                "ai_registry",
                None,
            ),
        ),
        thinking_level=args.thinking,
        apply_model_selection=lambda session, selection: apply_model_selection(
            session,
            selection,
            settings_manager=context.state.settings_manager,
        ),
        model_result_warning=_model_result_warning,
        stderr=context.bootstrap.stderr,
        format_error=_format_cli_error,
    )


async def _run_coding_cli_operations(
    context: CliSessionContext[
        CliArgs,
        AgentCliApplicationState[CliArgs],
        object,
        object,
    ],
) -> int | None:
    args = context.args
    session = context.session
    bootstrap = context.bootstrap
    return await run_standard_cli_operations(
        session,
        context.state.settings_manager,
        agent_standard_cli_operation_request(args),
        stdout=bootstrap.stdout,
        stderr=bootstrap.stderr,
        insertions=(
            CliOperationInsertion(
                CliOperationStage(
                    "method_visibility",
                    lambda: _run_method_visibility(
                        args,
                        bootstrap.project_root,
                        bootstrap.stdout,
                        bootstrap.stderr,
                    ),
                ),
                target_operation_id="list_skills",
            ),
            CliOperationInsertion(
                CliOperationStage(
                    "list_packages",
                    lambda: _run_list_packages(
                        args,
                        session,
                        context.state.services,
                        bootstrap.project_root,
                        bootstrap.stdout,
                        bootstrap.stderr,
                    ),
                ),
                target_operation_id="list_plugins",
            ),
        ),
        evaluate_install_source=_package_source_policy_reason,
        on_policy_denied=lambda package_source, reason: (
            record_package_source_policy_denial(
                getattr(context.state.services, "diagnostics_service", None),
                package_source=package_source,
                reason=reason,
            )
        ),
        format_error=_format_cli_error,
    )


def _prepare_coding_host_input(
    context: CliSessionContext[
        CliArgs,
        AgentCliApplicationState[CliArgs],
        object,
        object,
    ],
) -> CliPhaseResult[PreparedAgentCliHostInput]:
    args = context.args
    bootstrap = context.bootstrap
    domain_app = CodingDomainApp(cwd=bootstrap.project_root)
    return prepare_agent_cli_host_input(
        resolve_input=lambda: resolve_agent_prompt_input(
            args,
            stdin=bootstrap.stdin,
            cwd=bootstrap.project_root,
            auto_resize_images=agent_image_auto_resize(context.state.settings_manager),
        ),
        prepare_turns=lambda user_input: domain_app.prepare_turns(
            CodingDomainRequest(
                user_input=user_input,
                cwd=bootstrap.project_root,
                method_policy=resolve_method_policy(
                    explicit_method=args.method,
                    disabled=args.no_method,
                    settings_manager=context.state.settings_manager,
                ),
            )
        ),
        project_cli_turns=lambda turns: project_domain_turns_to_cli(
            cast(Sequence[CodingDomainPreparedTurn], turns)
        ),
        project_plan_turns=lambda turns, images, follow_up_messages: (
            project_prepared_session_work_turns(
                cast(Sequence[CodingDomainPreparedTurn], turns),
                images=cast(Sequence[object] | None, images),
                follow_up_messages=follow_up_messages,
            ),
        ),
        stderr=bootstrap.stderr,
        format_error=_format_cli_error,
        format_preparation_error=_format_method_cli_error,
    )


def _cli_launch_plan(args: CliArgs) -> CliLaunchPlan:
    product_command_operation = any(
        (
            args.list_methods,
            args.show_method is not None,
            args.show_method_plan is not None,
            args.work_log_inspect is not None,
        )
    )
    product_structured_operation = any(
        (
            args.list_methods and args.list_methods_format == "json",
            args.show_method is not None and args.show_method_format == "json",
            args.show_method_plan is not None
            and args.show_method_plan_format == "json",
        )
    )
    return agent_cli_launch_plan(
        args,
        overlay=AgentCliLaunchOverlay(
            workflow_requested=args.prompt_steps is not None,
            work_log_requested=args.work_log is not None,
            method_requested=args.method is not None,
            method_disabled=args.no_method,
            command_operation=product_command_operation,
            structured_operation_output=product_structured_operation,
        ),
    )


def _run_work_log_inspect(
    context: CliBootstrapContext[CliArgs],
) -> int | None:
    args = context.args
    return run_work_log_inspection_operation(
        path=args.work_log_inspect,
        project_root=context.project_root,
        run_id=args.work_log_run,
        output_format=args.work_log_inspect_format,
        limit=_WORK_LOG_INSPECT_LIMIT,
        stdout=context.stdout,
        stderr=context.stderr,
        format_error=_format_cli_error,
    )


def _format_method_cli_error(error: ValueError) -> str:
    message = _format_cli_error(error)
    if message.startswith("method not found:"):
        return f"{message}\nRun 'loushang method list' to inspect available methods."
    return message


def _model_result_warning(result: object) -> str | None:
    warning = persistence_warning_message(result)
    if warning is None:
        return None
    selection = getattr(result, "selection")
    return f"Model changed to {model_selection_ref(selection)}, but {warning}"


def _run_method_visibility(
    args: CliArgs,
    project_root: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if (
        not args.list_methods
        and args.show_method is None
        and args.show_method_plan is None
    ):
        return None

    request = MethodListingRequest(
        list_methods=args.list_methods,
        list_format=args.list_methods_format,
        show_method=args.show_method,
        show_format=args.show_method_format,
        show_method_plan=args.show_method_plan,
        show_plan_format=args.show_method_plan_format,
    )
    if not request.has_operation:
        return None
    try:
        result = run_method_listing(
            request,
            discover_methods=lambda: MethodLoader().discover_methods(project_root),
            compile_plan=lambda method: MethodCompiler().compile(
                method, context=MethodContext(domain="coding")
            ),
        )
    except MethodListingError as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    stdout.write(result.output)
    return 0


def _run_list_packages(
    args: CliArgs,
    session: Any,
    services: Any,
    project_root: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    get_packages = getattr(session, "get_packages", None)
    settings_manager = getattr(services, "settings_manager", None)
    get_settings = getattr(settings_manager, "get_settings", None)

    def fallback_records() -> list[Mapping[str, object]]:
        if not callable(get_settings):
            return []
        settings = get_settings()
        return collect_coding_package_entries(
            package_roots=tuple(getattr(settings, "package_roots", ())),
            plugin_sources=tuple(getattr(settings, "plugin_sources", ())),
            package_sources=tuple(getattr(settings, "package_sources", ())),
            disabled_plugins=tuple(getattr(settings, "disabled_plugins", ())),
            cwd=project_root,
            settings_manager=settings_manager,
            catalog_path=Path(args.package_catalog).expanduser().resolve()
            if args.package_catalog
            else None,
            materializer=getattr(session, "_package_materializer", None),
        )

    return run_package_listing_operation(
        requested=args.list_packages,
        output_format=args.list_packages_format,
        list_records=(
            lambda: (
                get_packages(catalog_path=args.package_catalog)
                if callable(get_packages)
                else []
            )
        )
        if callable(get_packages)
        else None,
        fallback_records=fallback_records,
        stdout=stdout,
        stderr=stderr,
        format_error=_format_cli_error,
    )


def _package_source_policy_reason(source: str) -> str | None:
    decision = PackageSecurityPolicy().evaluate_package_source(source)
    if decision.disposition == "deny":
        return decision.reason or "Package source denied by policy."
    return None


def _help_text(extension_flags: Mapping[str, ExtensionFlag] | None = None) -> str:
    return format_agent_cli_help(
        help_text(),
        extension_flags=cast(Mapping[str, object] | None, extension_flags),
    )


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    try:
        return asyncio.run(run_cli(sys.argv[1:] if argv is None else argv))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted.\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
