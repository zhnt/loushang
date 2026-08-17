"""Product-neutral launch decisions for standard Agent CLI hosts."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.cli.agent_args import AgentCliArgs


@dataclass(frozen=True, slots=True)
class CliLaunchPlan:
    """Normalized launch intent supplied by a Product argument adapter."""

    mode: str = "text"
    force_tui: bool = False
    disable_tui: bool = False
    prompt_requested: bool = False
    workflow_requested: bool = False
    message_input: bool = False
    file_input: bool = False
    follow_up_input: bool = False
    render_tool_events: bool = False
    work_log_requested: bool = False
    method_requested: bool = False
    method_disabled: bool = False
    session_requested: bool = False
    continue_requested: bool = False
    resume_requested: bool = False
    fork_requested: bool = False
    command_operation: bool = False
    structured_operation_output: bool = False


@dataclass(frozen=True, slots=True)
class AgentCliLaunchOverlay:
    """Product additions to the standard Agent CLI launch projection."""

    workflow_requested: bool = False
    work_log_requested: bool = False
    method_requested: bool = False
    method_disabled: bool = False
    command_operation: bool = False
    structured_operation_output: bool = False


def agent_cli_launch_plan(
    args: AgentCliArgs,
    *,
    overlay: AgentCliLaunchOverlay = AgentCliLaunchOverlay(),
) -> CliLaunchPlan:
    """Project standard Agent arguments plus explicit Product additions."""

    command_operations = (
        args.list_sessions,
        args.source_info,
        args.list_models is not False,
        args.list_commands,
        args.list_diagnostics,
        args.list_skills,
        args.list_plugins,
        args.list_packages,
        args.export is not None,
        args.diag_export,
        args.command is not None,
        bool(args.enable_skills),
        bool(args.disable_skills),
        bool(args.add_plugin_sources),
        bool(args.remove_plugin_sources),
        bool(args.enable_plugins),
        bool(args.disable_plugins),
        bool(args.install_packages),
        bool(args.uninstall_packages),
        bool(args.materialize_packages),
        bool(args.update_packages),
        bool(args.remove_packages),
        args.update_all_packages,
        args.check_package_updates,
        overlay.command_operation,
    )
    structured_operations = (
        args.list_sessions and args.list_sessions_format == "json",
        args.list_models is not False and args.list_models_format == "json",
        args.list_commands and args.list_commands_format == "json",
        args.list_diagnostics and args.list_diagnostics_format == "json",
        args.list_skills and args.list_skills_format == "json",
        args.list_plugins and args.list_plugins_format == "json",
        args.list_packages and args.list_packages_format == "json",
        args.export is not None and args.export_result_format == "json",
        args.command is not None and args.command_result_format == "json",
        bool(args.materialize_packages),
        bool(args.update_packages),
        bool(args.remove_packages),
        args.update_all_packages,
        args.check_package_updates,
        overlay.structured_operation_output,
    )
    return CliLaunchPlan(
        mode=args.mode,
        force_tui=args.tui,
        disable_tui=args.no_tui,
        prompt_requested=args.prompt is not None,
        workflow_requested=overlay.workflow_requested,
        message_input=bool(args.messages),
        file_input=bool(args.file_args),
        follow_up_input=bool(args.message_prompts),
        render_tool_events=args.render_tool_events,
        work_log_requested=overlay.work_log_requested,
        method_requested=overlay.method_requested,
        method_disabled=overlay.method_disabled,
        session_requested=args.session is not None,
        continue_requested=args.continue_,
        resume_requested=bool(args.resume),
        fork_requested=args.fork is not None,
        command_operation=any(command_operations),
        structured_operation_output=any(structured_operations),
    )


def cli_help_belongs_on_stderr(plan: CliLaunchPlan) -> bool:
    return bool(
        plan.prompt_requested
        or plan.workflow_requested
        or plan.mode in {"print", "json", "rpc", "channel"}
    )


def cli_output_guard_enabled(plan: CliLaunchPlan) -> bool:
    return cli_help_belongs_on_stderr(plan) or plan.structured_operation_output


def resolve_effective_tui(
    plan: CliLaunchPlan,
    *,
    stdin_is_tty: bool,
    stdout_is_tty: bool,
) -> bool:
    if plan.force_tui:
        return True
    if plan.disable_tui:
        return False
    if not (stdin_is_tty and stdout_is_tty):
        return False
    if plan.mode != "text":
        return False
    if plan.prompt_requested or plan.workflow_requested:
        return False
    if plan.message_input or plan.file_input or plan.follow_up_input:
        return False
    return not plan.command_operation


def cli_static_error(plan: CliLaunchPlan) -> str | None:
    if plan.force_tui and plan.disable_tui:
        return "--tui and --no-tui cannot be used together"
    if plan.fork_requested and not (
        plan.session_requested or plan.continue_requested or plan.resume_requested
    ):
        return "--fork requires --session or --continue / --resume"
    if plan.session_requested and (plan.continue_requested or plan.resume_requested):
        return "--session cannot be used with --continue or --resume"
    if plan.continue_requested and plan.resume_requested:
        return "--continue and --resume cannot be used together"
    if plan.work_log_requested:
        if plan.force_tui:
            return "--work-log is not supported in TUI mode"
        if plan.mode == "rpc":
            return "--work-log is not supported in RPC mode"
        if plan.mode == "channel":
            return "--work-log is not supported in Channel mode"
        if plan.workflow_requested:
            return "--work-log is not supported with --prompt-steps"
    if plan.method_requested and plan.method_disabled:
        return "--method cannot be used with --no-method"
    if plan.method_requested:
        if plan.force_tui:
            return "--method is not supported in TUI mode"
        if plan.mode == "rpc":
            return "--method is not supported in RPC mode"
        if plan.mode == "channel":
            return "--method is not supported in Channel mode"
        if plan.workflow_requested:
            return "--method is not supported with --prompt-steps"
    if plan.mode != "channel":
        return None
    if plan.force_tui:
        return "--tui is not supported in Channel mode"
    if plan.prompt_requested:
        return "--prompt is not supported in Channel mode"
    if plan.workflow_requested:
        return "--prompt-steps is not supported in Channel mode"
    if plan.message_input:
        return "positional messages are not supported in Channel mode"
    if plan.file_input:
        return "@file arguments are not supported in Channel mode"
    if plan.render_tool_events:
        return "--render-tool-events is not supported in Channel mode"
    return None


def cli_runtime_error(
    plan: CliLaunchPlan,
    *,
    effective_tui: bool,
) -> str | None:
    if effective_tui and plan.work_log_requested:
        return "--work-log is not supported in TUI mode"
    if effective_tui and plan.method_requested:
        return "--method is not supported in TUI mode"
    return None


def cli_observability_mode(plan: CliLaunchPlan, *, effective_tui: bool) -> str:
    if effective_tui:
        return "tui"
    if plan.prompt_requested:
        return "prompt"
    if plan.workflow_requested:
        return "workflow"
    return plan.mode


__all__ = [
    "AgentCliLaunchOverlay",
    "CliLaunchPlan",
    "agent_cli_launch_plan",
    "cli_help_belongs_on_stderr",
    "cli_observability_mode",
    "cli_output_guard_enabled",
    "cli_runtime_error",
    "cli_static_error",
    "resolve_effective_tui",
]
