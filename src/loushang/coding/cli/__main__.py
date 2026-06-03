from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager, nullcontext, redirect_stderr
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Mapping, TextIO

from loushang.ai.model.registry import get_default_model_registry
from loushang.ai.types import ImagePart
from loushang.coding.bootstrap import (
    BootstrapServices,
    create_agent_session_runtime,
    create_agent_session_services,
    create_services,
)
from loushang.coding.cli.args import CliArgs, ExtensionFlag, help_text, parse_args
from loushang.coding.control import SettingsManager
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.diag_export import export_diagnostics_bundle
from loushang.coding.diagnostics import serialize_diagnostic
from loushang.coding.domain import CodingDomainApp, CodingDomainRequest, MethodPolicy
from loushang.coding.extensions.types import ResolvedFlag
from loushang.coding.mode import ModeConfig, run_mode, run_print_mode, run_rpc_mode
from loushang.coding.observability import (
    coding_observability_context,
    coding_startup_observability_context,
)
from loushang.coding.package.projection import collect_package_entries
from loushang.coding.platform.output_guard import stdout_guard
from loushang.coding.plugin import PluginManager
from loushang.coding.plugin.lifecycle import is_remote_plugin_source
from loushang.coding.policy import (
    ApprovalResolver,
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
    PackageSecurityPolicy,
    PolicyEngine,
)
from loushang.coding.prompt_command import run_prompt_command
from loushang.coding.store import SessionQuery
from loushang.coding.tools import ToolRegistry, register_builtin_tools
from loushang.coding.tools.path_utils import resolve_tool_path
from loushang.coding.tools.read import (
    PillowReadImageResizer,
    detect_image_dimensions,
    format_image_dimension_note,
    image_exceeds_inline_limits,
)
from loushang.coding.types import ModelSelection
from loushang.coding.ui import run_coding_tui
from loushang.coding.workflow import (
    load_workflow,
    resolve_workflow_files,
    run_prompt_steps_workflow,
)
from loushang.method import MethodLoader
from loushang.work import JsonlEventLogBackend

_MISSING = object()
_WORK_LOG_INSPECT_LIMIT = 20


@dataclass(frozen=True)
class PrintInputPlan:
    user_input: str | None
    images: list[ImagePart] | None
    follow_up_messages: tuple[str, ...]


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
) -> ToolRegistry:
    registry = ToolRegistry()
    tool_settings = _tool_settings_from_settings_manager(settings_manager)
    resolved_approval_resolver = (
        approval_resolver if approval_resolver is not None else _approval_resolver_from_tool_settings(tool_settings)
    )
    get_external_tool_policy = getattr(settings_manager, "get_external_tool_policy", None)
    register_builtin_tools(
        registry,
        diagnostics_service=diagnostics_service,
        external_tool_policy=get_external_tool_policy() if callable(get_external_tool_policy) else None,
        policy_engine=_policy_engine_from_tool_settings(tool_settings),
        approval_resolver=resolved_approval_resolver,
    )
    return registry


def _tool_settings_from_settings_manager(settings_manager: object | None) -> object | None:
    get_tool_settings = getattr(settings_manager, "get_tool_settings", None)
    if callable(get_tool_settings):
        return get_tool_settings()
    get_settings = getattr(settings_manager, "get_settings", None)
    if callable(get_settings):
        return getattr(get_settings(), "tools", None)
    return None


def _policy_engine_from_tool_settings(tool_settings: object | None) -> PolicyEngine | None:
    if tool_settings is None:
        return None
    kwargs = {
        "blocked_tools": _tool_setting_tuple(tool_settings, "blocked_tools"),
        "ask_tools": _tool_setting_tuple(tool_settings, "ask_tools"),
        "blocked_substrings": _tool_setting_tuple(tool_settings, "blocked_substrings"),
        "ask_substrings": _tool_setting_tuple(tool_settings, "ask_substrings"),
        "blocked_path_substrings": _tool_setting_tuple(tool_settings, "blocked_path_substrings"),
        "ask_path_substrings": _tool_setting_tuple(tool_settings, "ask_path_substrings"),
    }
    if not any(kwargs.values()):
        return None
    return PolicyEngine(**kwargs)


def _approval_resolver_from_tool_settings(tool_settings: object | None) -> HeadlessApprovalResolver | None:
    if tool_settings is None:
        return None
    approval_mode = getattr(tool_settings, "approval_mode", None)
    if approval_mode is None:
        return None
    return HeadlessApprovalResolver(
        mode=approval_mode,
        reason=getattr(tool_settings, "approval_reason", None),
    )


def _tool_setting_tuple(tool_settings: object, name: str) -> tuple[str, ...]:
    value = getattr(tool_settings, name, ())
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def default_runtime_builder(
    *,
    args: CliArgs,
    cwd: Path,
    session_dir: Path,
    services: BootstrapServices,
    tool_registry: ToolRegistry,
):
    if args.no_tools:
        allowed_tool_names = []
        active_tool_names = []
    elif args.tools:
        allowed_tool_names = list(args.tools)
        active_tool_names = list(args.tools)
    else:
        allowed_tool_names = None
        active_tool_names = None
    resource_loader_options = _resource_loader_options_from_args(args)
    _configure_resource_loader(services.resource_loader, resource_loader_options)
    services_factory = _cwd_bound_services_factory(services, resource_loader_options)
    return create_agent_session_runtime(
        session_dir=session_dir,
        services=services,
        services_factory=services_factory,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        persist=not args.no_session,
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
    mode_runner=run_mode,
    prompt_runner=run_prompt_command,
    workflow_runner=run_prompt_steps_workflow,
    print_runner=run_print_mode,
    rpc_runner=run_rpc_mode,
    tui_runner=run_coding_tui,
) -> int:
    raw_argv = list(argv or ())
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    bootstrap_args, parse_error_code = _parse_args_for_cli(
        raw_argv,
        stderr=stderr,
        allow_unknown=True,
    )
    if bootstrap_args is None:
        return parse_error_code
    project_root = Path(cwd or bootstrap_args.cwd or Path.cwd()).resolve()
    _apply_offline_mode(bootstrap_args)

    if bootstrap_args.help:
        with _stdout_guard_context(bootstrap_args, stdout, stderr):
            extension_flags = await _collect_extension_flags_for_help(
                raw_argv=raw_argv,
                project_root=project_root,
                services=services,
                runtime_builder=runtime_builder,
            )
        help_output = stderr if _help_belongs_on_stderr(bootstrap_args) else stdout
        help_output.write(_help_text(extension_flags))
        return 0
    if bootstrap_args.version:
        stdout.write(f"{_package_version()}\n")
        return 0

    if bootstrap_args.tui and bootstrap_args.no_tui:
        stderr.write("Error: --tui and --no-tui cannot be used together.\n")
        return 2
    if bootstrap_args.fork and not (
        bootstrap_args.session or bootstrap_args.continue_ or bootstrap_args.resume
    ):
        stderr.write("Error: --fork requires --session or --continue / --resume.\n")
        return 2
    if bootstrap_args.session and (bootstrap_args.continue_ or bootstrap_args.resume):
        stderr.write("Error: --session cannot be used with --continue or --resume.\n")
        return 2
    if bootstrap_args.continue_ and bootstrap_args.resume:
        stderr.write("Error: --continue and --resume cannot be used together.\n")
        return 2
    work_log_error = _work_log_static_error(bootstrap_args)
    if work_log_error is not None:
        stderr.write(f"Error: {work_log_error}.\n")
        return 2
    method_error = _method_static_error(bootstrap_args)
    if method_error is not None:
        stderr.write(f"Error: {method_error}.\n")
        return 2
    work_log_inspect_result = _run_work_log_inspect(bootstrap_args, project_root, stdout, stderr)
    if work_log_inspect_result is not None:
        return work_log_inspect_result

    with _stdout_guard_context(bootstrap_args, stdout, stderr):
        resolved_services = services or build_default_services(project_root)
        _report_settings_errors_for_resource_commands(bootstrap_args, resolved_services, stderr)
        resource_toggle_result = _run_resource_toggles(bootstrap_args, resolved_services, stdout, stderr)
        if resource_toggle_result is not None:
            return resource_toggle_result
        runtime_args = _runtime_args_for_bootstrap(bootstrap_args)
        session_dir = _resolve_session_dir(runtime_args, project_root, resolved_services)
        diag_export_result = _run_diag_export(
            bootstrap_args,
            project_root,
            session_dir,
            resolved_services,
            stdout,
            stderr,
        )
        if diag_export_result is not None:
            return diag_export_result
        fake_workflow_result = await _run_fake_prompt_steps_workflow_if_requested(
            bootstrap_args,
            project_root=project_root,
            workflow_runner=workflow_runner,
            stdout=stdout,
            stderr=stderr,
        )
        if fake_workflow_result is not None:
            return fake_workflow_result
        settings_manager = getattr(resolved_services, "settings_manager", None)
        tool_settings = _tool_settings_from_settings_manager(settings_manager)
        configured_approval_resolver = _approval_resolver_from_tool_settings(tool_settings)
        use_tui_approval_presenter = configured_approval_resolver is None
        if configured_approval_resolver is None:
            configured_approval_resolver = HeadlessApprovalResolver(mode="deny")
        approval_resolver = InteractiveApprovalResolver(fallback=configured_approval_resolver)
        if runtime_args.no_builtin_tools:
            tool_registry = ToolRegistry()
        else:
            tool_registry = build_builtin_tool_registry(
                diagnostics_service=getattr(resolved_services, "diagnostics_service", None),
                settings_manager=getattr(resolved_services, "settings_manager", None),
                approval_resolver=approval_resolver,
            )

    with coding_startup_observability_context(
        args=bootstrap_args,
        services=resolved_services,
        cwd=project_root,
    ):
        with _stdout_guard_context(bootstrap_args, stdout, stderr):
            runtime = runtime_builder(
                args=runtime_args,
                cwd=project_root,
                session_dir=session_dir,
                services=resolved_services,
                tool_registry=tool_registry,
            )
        with _stdout_guard_context(runtime_args, stdout, stderr):
            list_sessions_result = _run_list_sessions(runtime_args, runtime, stdout, stderr)
        if list_sessions_result is not None:
            return list_sessions_result

        try:
            with _stdout_guard_context(bootstrap_args, stdout, stderr):
                session = await _resolve_session(runtime_args, runtime, project_root)
        except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as error:
            stderr.write(f"Error: {_format_cli_error(error)}\n")
            return 1
    if session is None:
        return 2
    if use_tui_approval_presenter:
        approval_setter = getattr(session, "set_approval_presenter", None)
        if callable(approval_setter):
            approval_setter(approval_resolver.set_request_presenter)
    extension_flags = _collect_extension_flags(session)
    args, parse_error_code = _parse_args_for_cli(
        raw_argv,
        stderr=stderr,
        extension_flags=extension_flags,
    )
    if args is None:
        return parse_error_code
    with _stdout_guard_context(args, stdout, stderr):
        _apply_extension_flag_values(session, args.extension_flag_values)

        if args.session_name is not None:
            setter = getattr(session, "set_session_name", None)
            if callable(setter):
                setter(args.session_name)

        override_result = await _apply_model_and_thinking_overrides(args, session, stderr)
        if override_result is not None:
            return override_result

        export_result = _run_export(args, session, stdout, stderr)
        if export_result is not None:
            return export_result

        list_commands_result = _run_list_commands(args, session, stdout, stderr)
        if list_commands_result is not None:
            return list_commands_result

        list_diagnostics_result = _run_list_diagnostics(args, session, stdout, stderr)
        if list_diagnostics_result is not None:
            return list_diagnostics_result

        list_skills_result = _run_list_skills(args, session, stdout, stderr)
        if list_skills_result is not None:
            return list_skills_result

        method_visibility_result = _run_method_visibility(args, project_root, stdout, stderr)
        if method_visibility_result is not None:
            return method_visibility_result

        list_plugins_result = _run_list_plugins(args, resolved_services, stdout, stderr)
        if list_plugins_result is not None:
            return list_plugins_result

        list_packages_result = _run_list_packages(args, session, resolved_services, project_root, stdout, stderr)
        if list_packages_result is not None:
            return list_packages_result

        package_lifecycle_result = await _run_package_lifecycle(args, session, resolved_services, stdout, stderr)
        if package_lifecycle_result is not None:
            return package_lifecycle_result

        command_result = await _run_command(args, session, stdout, stderr)
        if command_result is not None:
            return command_result

        list_models_result = _run_list_models(args, session, stdout, stderr)
        if list_models_result is not None:
            return list_models_result

        effective_tui = _effective_tui(args, stdin=stdin, stdout=stdout)
        work_log_error = _work_log_runtime_error(args, effective_tui=effective_tui)
        if work_log_error is not None:
            stderr.write(f"Error: {work_log_error}.\n")
            return 2
        method_error = _method_runtime_error(args, effective_tui=effective_tui)
        if method_error is not None:
            stderr.write(f"Error: {method_error}.\n")
            return 2
        work_event_log = _resolve_work_event_log(args.work_log, project_root)
        with coding_observability_context(
            args=args,
            session=session,
            cwd=project_root,
            mode=_observability_mode(args, effective_tui=effective_tui),
        ):
            if effective_tui:
                return await tui_runner(
                    runtime=runtime,
                    session=session,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    verbose=args.verbose,
                )

            if args.mode == "rpc":
                if args.file_args:
                    stderr.write("Error: @file arguments are not supported in RPC mode.\n")
                    return 2
                if rpc_runner is not run_rpc_mode:
                    return await rpc_runner(
                        runtime=runtime,
                        stdin=stdin,
                        stdout=stdout,
                        stderr=stderr,
                        render_tool_events=args.render_tool_events,
                    )
                return await mode_runner(
                    config=ModeConfig(mode="rpc", render_tool_events=args.render_tool_events),
                    runtime=runtime,
                    session=session,
                    user_input=None,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                )

            if args.prompt_steps is not None:
                return await workflow_runner(
                    runtime=runtime,
                    session=session,
                    workflow_path=Path(args.prompt_steps),
                    cwd=project_root,
                    stdout=stdout,
                    stderr=stderr,
                    verbose=args.verbose,
                    output_mode=_workflow_output_mode(args),
                )

            try:
                print_input = _resolve_print_input_plan(
                    args,
                    stdin,
                    project_root,
                    auto_resize_images=_get_image_auto_resize(resolved_services),
                )
            except (OSError, UnicodeDecodeError, RuntimeError) as error:
                stderr.write(f"Error: {_format_cli_error(error)}\n")
                return 1
            if print_input.user_input is None:
                stderr.write("Error: prompt is required for prompt/text/print/json modes.\n")
                return 2

            try:
                prepared_turns = CodingDomainApp(cwd=project_root).prepare_turns(
                    CodingDomainRequest(
                        user_input=print_input.user_input,
                        cwd=project_root,
                        method_policy=_method_policy_from_args(args, settings_manager=settings_manager),
                    )
                )
            except ValueError as error:
                stderr.write(f"Error: {_format_method_cli_error(error)}\n")
                return 1

            if args.prompt is not None:
                for turn_index, prepared_turn in enumerate(prepared_turns):
                    is_first_turn = turn_index == 0
                    is_last_turn = turn_index == len(prepared_turns) - 1
                    exit_code = await prompt_runner(
                        runtime=runtime,
                        session=session,
                        prompt=prepared_turn.prepared_prompt,
                        stdout=stdout,
                        stderr=stderr,
                        images=print_input.images if is_first_turn else None,
                        follow_up_messages=print_input.follow_up_messages if is_last_turn else (),
                        verbose=args.verbose,
                        work_event_log=work_event_log,
                        method_id=prepared_turn.method_id,
                        plan_id=prepared_turn.plan_id,
                        step_id=prepared_turn.step_id,
                        step_index=prepared_turn.step_index,
                        step_title=prepared_turn.step_title,
                        dispose=is_last_turn,
                    )
                    if exit_code != 0:
                        if not is_last_turn:
                            await _dispose_runtime_or_session(runtime, session)
                        return exit_code
                return 0

            output_mode = "text" if args.mode == "print" else args.mode
            if print_runner is not run_print_mode:
                for turn_index, prepared_turn in enumerate(prepared_turns):
                    is_first_turn = turn_index == 0
                    is_last_turn = turn_index == len(prepared_turns) - 1
                    exit_code = await print_runner(
                        runtime=runtime,
                        session=session,
                        user_input=prepared_turn.prepared_prompt,
                        stdout=stdout,
                        stderr=stderr,
                        images=print_input.images if is_first_turn else None,
                        follow_up_messages=print_input.follow_up_messages if is_last_turn else (),
                        output_mode=output_mode,
                        render_tool_events=args.render_tool_events,
                        work_event_log=work_event_log,
                        method_id=prepared_turn.method_id,
                        plan_id=prepared_turn.plan_id,
                        step_id=prepared_turn.step_id,
                        step_index=prepared_turn.step_index,
                        step_title=prepared_turn.step_title,
                        dispose=is_last_turn,
                    )
                    if exit_code != 0:
                        if not is_last_turn:
                            await _dispose_runtime_or_session(runtime, session)
                        return exit_code
                return 0

            for turn_index, prepared_turn in enumerate(prepared_turns):
                is_first_turn = turn_index == 0
                is_last_turn = turn_index == len(prepared_turns) - 1
                exit_code = await mode_runner(
                    config=ModeConfig(
                        mode=args.mode,
                        render_tool_events=args.render_tool_events,
                    ),
                    runtime=runtime,
                    session=session,
                    user_input=prepared_turn.prepared_prompt,
                    images=print_input.images if is_first_turn else None,
                    follow_up_messages=print_input.follow_up_messages if is_last_turn else (),
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    work_event_log=work_event_log,
                    method_id=prepared_turn.method_id,
                    plan_id=prepared_turn.plan_id,
                    step_id=prepared_turn.step_id,
                    step_index=prepared_turn.step_index,
                    step_title=prepared_turn.step_title,
                    dispose=is_last_turn,
                )
                if exit_code != 0:
                    if not is_last_turn:
                        await _dispose_runtime_or_session(runtime, session)
                    return exit_code
            return 0


async def _dispose_runtime_or_session(runtime: Any, session: Any) -> None:
    disposer = getattr(runtime, "dispose", None)
    if not callable(disposer):
        disposer = getattr(session, "dispose", None)
    if not callable(disposer):
        return
    result = disposer()
    if inspect.isawaitable(result):
        await result


def _resolve_session_dir(args: CliArgs, project_root: Path, services: Any) -> Path:
    if args.session_dir:
        return Path(args.session_dir).expanduser().resolve()
    settings = services.settings_manager.get_settings()
    configured = getattr(settings, "session_dir", None)
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root / ".loushang" / "sessions"


def _get_image_auto_resize(services: Any) -> bool:
    settings_manager = getattr(services, "settings_manager", None)
    get_image_auto_resize = getattr(settings_manager, "get_image_auto_resize", None)
    if callable(get_image_auto_resize):
        return bool(get_image_auto_resize())
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        return True
    settings = get_settings()
    images = getattr(settings, "images", None)
    if images is None:
        return True
    return bool(getattr(images, "auto_resize", True))


def _apply_offline_mode(args: CliArgs) -> None:
    if args.offline:
        os.environ["LOUSHANG_OFFLINE"] = "1"


def _configure_resource_loader_from_args(resource_loader: object, args: CliArgs) -> None:
    _configure_resource_loader(resource_loader, _resource_loader_options_from_args(args))


def _resource_loader_options_from_args(args: CliArgs) -> dict[str, object]:
    options: dict[str, object] = {
        "additional_extension_paths": list(getattr(args, "extensions", ())),
        "additional_skill_paths": list(getattr(args, "skills", ())),
        "additional_prompt_template_paths": list(getattr(args, "prompt_templates", ())),
        "additional_theme_paths": list(getattr(args, "themes", ())),
        "no_extensions": bool(getattr(args, "no_extensions", False)),
        "no_skills": bool(getattr(args, "no_skills", False)),
        "no_prompt_templates": bool(getattr(args, "no_prompt_templates", False)),
        "no_themes": bool(getattr(args, "no_themes", False)),
        "no_context_files": bool(getattr(args, "no_context_files", False)),
    }
    if hasattr(args, "system_prompt"):
        options["system_prompt"] = getattr(args, "system_prompt")
    if hasattr(args, "append_system_prompt"):
        options["append_system_prompt"] = list(getattr(args, "append_system_prompt"))
    return options


def _configure_resource_loader(resource_loader: object, options: dict[str, object]) -> None:
    setter = getattr(resource_loader, "set_runtime_options", None)
    if not callable(setter):
        return
    setter(**options)


def _cwd_bound_services_factory(services: BootstrapServices, resource_loader_options: dict[str, object]):
    project_base_dir = getattr(getattr(services, "settings_manager", None), "project_base_dir", None)
    if project_base_dir is None:
        return None

    def build_for_cwd(cwd: str) -> BootstrapServices:
        return create_agent_session_services(
            cwd=cwd,
            resource_loader_options=resource_loader_options,
        ).services

    return build_for_cwd


def _help_belongs_on_stderr(args: CliArgs) -> bool:
    return bool(args.prompt is not None or args.prompt_steps is not None or args.mode in {"print", "json", "rpc"})


def _stdout_guard_enabled(args: CliArgs) -> bool:
    if args.prompt is not None or args.prompt_steps is not None or args.mode in {"print", "json", "rpc"}:
        return True
    return bool(
        (args.list_sessions and args.list_sessions_format == "json")
        or (args.list_models is not False and args.list_models_format == "json")
        or (args.list_commands and args.list_commands_format == "json")
        or (args.list_diagnostics and args.list_diagnostics_format == "json")
        or (args.list_skills and args.list_skills_format == "json")
        or (args.list_methods and args.list_methods_format == "json")
        or (args.show_method is not None and args.show_method_format == "json")
        or (args.list_plugins and args.list_plugins_format == "json")
        or (args.list_packages and args.list_packages_format == "json")
        or (args.export is not None and args.export_result_format == "json")
        or (args.command is not None and args.command_result_format == "json")
        or bool(args.materialize_packages)
        or bool(args.update_packages)
        or bool(args.remove_packages)
        or args.update_all_packages
        or args.check_package_updates
    )


@contextmanager
def _stdout_guard_context(args: CliArgs, stdout: TextIO, stderr: TextIO):
    with (stdout_guard(stdout=stdout, stderr=stderr) if _stdout_guard_enabled(args) else nullcontext()):
        yield


async def _run_fake_prompt_steps_workflow_if_requested(
    args: CliArgs,
    *,
    project_root: Path,
    workflow_runner,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if args.prompt_steps is None:
        return None
    try:
        workflow_files = resolve_workflow_files(project_root, args.prompt_steps)
        workflows = [load_workflow(workflow_file) for workflow_file in workflow_files]
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if not workflows or any(workflow.backend != "fake" for workflow in workflows):
        return None
    return await workflow_runner(
        runtime=None,
        session=None,
        workflow_path=Path(args.prompt_steps),
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
        verbose=args.verbose,
        output_mode=_workflow_output_mode(args),
    )


def _workflow_output_mode(args: CliArgs) -> str:
    return "json" if args.mode == "json" else "text"


def _effective_tui(args: CliArgs, *, stdin: TextIO, stdout: TextIO) -> bool:
    if args.tui:
        return True
    if args.no_tui:
        return False
    if not (_stream_is_tty(stdin) and _stream_is_tty(stdout)):
        return False
    if args.mode != "text":
        return False
    if args.prompt is not None or args.prompt_steps is not None:
        return False
    if args.messages or args.file_args or args.message_prompts:
        return False
    return not _has_command_style_operation(args)


def _work_log_static_error(args: CliArgs) -> str | None:
    if args.work_log is None:
        return None
    if args.tui:
        return "--work-log is not supported in TUI mode"
    if args.mode == "rpc":
        return "--work-log is not supported in RPC mode"
    if args.prompt_steps is not None:
        return "--work-log is not supported with --prompt-steps"
    return None


def _work_log_runtime_error(args: CliArgs, *, effective_tui: bool) -> str | None:
    if args.work_log is None:
        return None
    if effective_tui:
        return "--work-log is not supported in TUI mode"
    return None


def _method_static_error(args: CliArgs) -> str | None:
    if args.method is not None and args.no_method:
        return "--method cannot be used with --no-method"
    if args.method is None:
        return None
    if args.tui:
        return "--method is not supported in TUI mode"
    if args.mode == "rpc":
        return "--method is not supported in RPC mode"
    if args.prompt_steps is not None:
        return "--method is not supported with --prompt-steps"
    return None


def _method_runtime_error(args: CliArgs, *, effective_tui: bool) -> str | None:
    if args.method is None:
        return None
    if effective_tui:
        return "--method is not supported in TUI mode"
    return None


def _method_policy_from_args(
    args: CliArgs,
    *,
    settings_manager: object | None = None,
) -> MethodPolicy:
    if args.no_method:
        return MethodPolicy.off()
    if args.method is not None:
        return MethodPolicy.explicit(args.method)
    method_settings = _method_settings_from_settings_manager(settings_manager)
    if method_settings is None:
        return MethodPolicy.explicit(None)
    if getattr(method_settings, "mode", None) == "off":
        return MethodPolicy.off()
    return MethodPolicy(
        mode=getattr(method_settings, "mode", "explicit"),
        selected_method=getattr(method_settings, "selected_method", None),
    )


def _method_settings_from_settings_manager(settings_manager: object | None) -> object | None:
    get_method_settings = getattr(settings_manager, "get_method_settings", None)
    if callable(get_method_settings):
        return get_method_settings()
    get_settings = getattr(settings_manager, "get_settings", None)
    if callable(get_settings):
        return getattr(get_settings(), "method", None)
    return None


def _resolve_work_event_log(raw_path: str | None, project_root: Path) -> JsonlEventLogBackend | None:
    if raw_path is None:
        return None
    return JsonlEventLogBackend(_resolve_work_log_path(raw_path, project_root))


def _run_work_log_inspect(args: CliArgs, project_root: Path, stdout: TextIO, stderr: TextIO) -> int | None:
    if args.work_log_inspect is None:
        return None
    try:
        event_log = JsonlEventLogBackend(_resolve_work_log_path(args.work_log_inspect, project_root))
        entries = event_log.query(run_id=args.work_log_run)[-_WORK_LOG_INSPECT_LIMIT:]
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if args.work_log_inspect_format == "json":
        stdout.write(json.dumps([_work_log_entry_summary(entry) for entry in entries], ensure_ascii=False) + "\n")
    else:
        _write_work_log_text(entries, stdout)
    return 0


def _resolve_work_log_path(raw_path: str, project_root: Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path


def _write_work_log_text(entries: list[Any], stdout: TextIO) -> None:
    stdout.write("sequence\tkind\trun_id\tsession_id\tdelivery_hint\tmethod_id\n")
    for entry in entries:
        stdout.write(
            f"{entry.sequence}\t{_work_log_entry_kind(entry)}\t{entry.run_id}\t"
            f"{entry.session_id}\t{_work_log_entry_delivery_hint(entry)}\t{_work_log_entry_method_id(entry)}\n"
        )


def _work_log_entry_summary(entry: Any) -> dict[str, object]:
    summary: dict[str, object] = {
        "entry_id": entry.entry_id,
        "entry_type": entry.entry_type,
        "sequence": entry.sequence,
        "kind": _work_log_entry_kind(entry),
        "run_id": entry.run_id,
        "session_id": entry.session_id,
        "operation_id": entry.operation_id,
        "event_id": entry.event_id,
        "delivery_hint": _work_log_entry_delivery_hint(entry),
    }
    method_id = _work_log_entry_method_id(entry)
    if method_id:
        summary["method_id"] = method_id
    return summary


def _work_log_entry_kind(entry: Any) -> str:
    kind = entry.payload.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    return str(entry.entry_type)


def _work_log_entry_delivery_hint(entry: Any) -> str:
    delivery_hint = entry.payload.get("delivery_hint")
    if isinstance(delivery_hint, str):
        return delivery_hint
    return ""


def _work_log_entry_method_id(entry: Any) -> str:
    method_id = entry.payload.get("method_id")
    if isinstance(method_id, str):
        return method_id
    nested_payload = entry.payload.get("payload")
    if isinstance(nested_payload, dict):
        nested_method_id = nested_payload.get("method_id")
        if isinstance(nested_method_id, str):
            return nested_method_id
    return ""


def _has_command_style_operation(args: CliArgs) -> bool:
    return bool(
        args.list_sessions
        or args.list_models is not False
        or args.list_commands
        or args.list_diagnostics
        or args.list_skills
        or args.list_methods
        or args.show_method is not None
        or args.list_plugins
        or args.list_packages
        or args.export is not None
        or args.diag_export
        or args.command is not None
        or args.enable_skills
        or args.disable_skills
        or args.add_plugin_sources
        or args.remove_plugin_sources
        or args.enable_plugins
        or args.disable_plugins
        or args.install_packages
        or args.uninstall_packages
        or args.materialize_packages
        or args.update_packages
        or args.remove_packages
        or args.update_all_packages
        or args.check_package_updates
        or args.work_log_inspect is not None
    )


def _observability_mode(args: CliArgs, *, effective_tui: bool) -> str:
    if effective_tui:
        return "tui"
    if args.prompt is not None:
        return "prompt"
    if args.prompt_steps is not None:
        return "workflow"
    return args.mode


def _parse_args_for_cli(
    argv: list[str],
    *,
    stderr: TextIO,
    extension_flags: Mapping[str, ExtensionFlag] | None = None,
    allow_unknown: bool = False,
) -> tuple[CliArgs | None, int]:
    try:
        with redirect_stderr(stderr):
            return (
                parse_args(
                    argv,
                    extension_flags=extension_flags,
                    allow_unknown=allow_unknown,
                ),
                0,
            )
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 2
        return None, code


def _format_cli_error(error: BaseException) -> str:
    filename = getattr(error, "filename", None)
    if isinstance(error, OSError):
        strerror = getattr(error, "strerror", None)
        if filename is not None and strerror:
            return f"{strerror}: {filename}"
    return str(error)


def _format_method_cli_error(error: ValueError) -> str:
    message = _format_cli_error(error)
    if message.startswith("method not found:"):
        return f"{message}\nRun 'loushang method list' to inspect available methods."
    return message


def _runtime_args_for_bootstrap(args: CliArgs) -> CliArgs:
    if (
        args.list_commands
        or args.list_diagnostics
        or args.list_skills
        or args.list_methods
        or args.show_method is not None
        or args.list_plugins
        or args.list_packages
        or args.list_models is not False
        or args.enable_skills
        or args.disable_skills
        or args.add_plugin_sources
        or args.remove_plugin_sources
        or args.enable_plugins
        or args.disable_plugins
    ):
        return replace(args, no_session=True)
    return args


def _report_settings_errors_for_resource_commands(args: CliArgs, services: Any, stderr: TextIO) -> None:
    if not (
        args.list_plugins
        or args.list_packages
        or args.enable_skills
        or args.disable_skills
        or args.add_plugin_sources
        or args.remove_plugin_sources
        or args.enable_plugins
        or args.disable_plugins
    ):
        return
    settings_manager = getattr(services, "settings_manager", None)
    context = "package command" if args.list_packages or args.list_plugins or args.add_plugin_sources or args.remove_plugin_sources else "settings command"
    _report_settings_errors(settings_manager, context=context, stderr=stderr)


def _report_settings_errors(settings_manager: Any, *, context: str, stderr: TextIO) -> None:
    drain_errors = getattr(settings_manager, "drain_errors", None)
    if not callable(drain_errors):
        return
    try:
        errors = drain_errors()
    except Exception:
        return
    if not isinstance(errors, list):
        return
    for error in errors:
        scope = _safe_getattr(error, "scope", "unknown")
        message = _safe_getattr(error, "message", "")
        stderr.write(f"Warning ({context}, {scope} settings): {message}\n")


def _run_resource_toggles(
    args: CliArgs,
    services: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not (
        args.enable_skills
        or args.disable_skills
        or args.add_plugin_sources
        or args.remove_plugin_sources
        or args.enable_plugins
        or args.disable_plugins
    ):
        return None
    settings_manager = getattr(services, "settings_manager", None)
    if settings_manager is None:
        stderr.write("Error: settings manager is not available.\n")
        return 1
    try:
        for name in args.disable_skills:
            settings_manager.disable_skill(name, scope="project")
            stdout.write(f"disabled skill\t{name}\n")
        for name in args.enable_skills:
            settings_manager.enable_skill(name, scope="project")
            stdout.write(f"enabled skill\t{name}\n")
        for source in args.remove_plugin_sources:
            removed = settings_manager.remove_plugin_source(source, scope="project")
            if removed is False:
                stderr.write(f"Error: no matching plugin source found: {source}\n")
                return 1
            stdout.write(f"removed plugin source\t{source}\n")
        for source in args.add_plugin_sources:
            decision = PackageSecurityPolicy().evaluate_package_source(source)
            if decision.disposition == "deny":
                _record_package_policy_diagnostic(services, source=source, reason=decision.reason)
                stderr.write(f"Error: {decision.reason}\n")
                return 1
            added = settings_manager.add_plugin_source(source, scope="project")
            if added is False:
                stderr.write(f"Error: plugin source already exists: {source}\n")
                return 1
            label = "remote plugin source" if is_remote_plugin_source(source) else "plugin source"
            stdout.write(f"added {label}\t{source}\n")
        for name in args.disable_plugins:
            settings_manager.disable_plugin(name, scope="project")
            stdout.write(f"disabled plugin\t{name}\n")
        for name in args.enable_plugins:
            settings_manager.enable_plugin(name, scope="project")
            stdout.write(f"enabled plugin\t{name}\n")
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    return 0


def _record_package_policy_diagnostic(services: Any, *, source: str, reason: str | None) -> None:
    diagnostics = getattr(services, "diagnostics_service", None)
    capture_failure = getattr(diagnostics, "capture_failure", None)
    if not callable(capture_failure):
        return
    capture_failure(
        code="package_source_policy_denied",
        error=reason or "Package source denied by policy.",
        phase="runtime",
        source="policy",
        details={
            "plugin_source": source,
            "policy": "package_security",
            "disposition": "deny",
        },
    )


async def _resolve_session(args: CliArgs, runtime: Any, project_root: Path):
    if isinstance(args.resume, str):
        session = await runtime.restore_session(args.resume)
    elif args.continue_ or args.resume:
        latest_session_file = _resolve_latest_session_file(runtime)
        if latest_session_file is None:
            raise RuntimeError("No existing session found. Use --session or --resume <session> to restore a specific session.")
        session = await runtime.restore_session(latest_session_file)
    elif args.session:
        session = await runtime.restore_session(args.session)
    else:
        session = await runtime.new_session(cwd=str(project_root))

    if args.fork:
        try:
            session = await runtime.fork_session(args.fork)
        except Exception as error:
            raise RuntimeError(f"Failed to fork session: {error}") from error
    return session


def _resolve_latest_session_file(runtime: Any) -> str | None:
    try:
        sessions = runtime.list_sessions()
    except Exception as error:
        raise RuntimeError(f"Failed to list sessions: {error}") from error
    if not isinstance(sessions, list):
        raise RuntimeError("session listing returned an invalid response.")
    if not sessions:
        return None
    for latest_session in sessions:
        session_file = getattr(latest_session, "session_file", None)
        if session_file is not None:
            return str(session_file)
    return None


def _resolve_model_selection(args: CliArgs) -> ModelSelection | None:
    if args.provider is None and args.model is None:
        return None
    if args.provider is not None and args.model is not None:
        return ModelSelection(provider=args.provider, model_id=args.model)
    if args.provider is None and args.model is not None and "/" in args.model:
        provider, model_id = args.model.split("/", 1)
        if provider and model_id:
            return ModelSelection(provider=provider, model_id=model_id)
    raise ValueError("Model selection requires --provider and --model, or --model provider/model_id.")


async def _apply_model_and_thinking_overrides(args: CliArgs, session: Any, stderr: TextIO) -> int | None:
    try:
        explicit_model = _resolve_model_selection(args)
        if explicit_model is not None:
            await session.set_model(explicit_model)
        if args.thinking is not None:
            session.set_thinking_level(args.thinking)
    except (RuntimeError, ValueError) as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    return None


def _run_list_sessions(
    args: CliArgs,
    runtime: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_sessions:
        return None

    try:
        query = _session_query_from_args(args)
    except ValueError as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    use_index = args.session_index or args.refresh_session_index
    if args.refresh_session_index:
        refresher = getattr(runtime, "refresh_all_session_indexes" if args.all_sessions else "refresh_session_index", None)
        if not callable(refresher):
            stderr.write("Error: session index refresh is not available.\n")
            return 1
        try:
            refresher()
        except Exception as error:
            stderr.write(f"Error: {_format_cli_error(error)}\n")
            return 1

    if args.all_sessions and query is not None:
        lister = getattr(runtime, "find_all_indexed_session_summaries" if use_index else "find_all_session_summaries", None)
        if callable(lister):
            def call_lister():
                return lister(query)
        else:
            call_lister = None
    elif query is not None:
        lister = getattr(runtime, "find_indexed_session_summaries" if use_index else "find_session_summaries", None)
        if callable(lister):
            def call_lister():
                return lister(query)
        else:
            call_lister = None
    else:
        if args.all_sessions:
            lister = getattr(runtime, "list_all_indexed_session_summaries" if use_index else "list_all_session_summaries", None)
        else:
            lister = getattr(runtime, "list_indexed_session_summaries" if use_index else "list_session_summaries", None)
        if not callable(lister) and not use_index:
            lister = getattr(runtime, "list_session_summaries", None)
        if not callable(lister) and not use_index:
            lister = getattr(runtime, "list_sessions", None)
        call_lister = lister if callable(lister) else None
    if not callable(call_lister):
        stderr.write("Error: session listing is not available.\n")
        return 1

    try:
        records = call_lister()
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if not isinstance(records, list):
        stderr.write("Error: session listing returned an invalid response.\n")
        return 1

    normalized_sessions = [_try_normalize_session_record(record) for record in records]
    normalized_sessions = [record for record in normalized_sessions if record is not None]

    if args.list_sessions_format == "json":
        stdout.write(json.dumps(normalized_sessions, ensure_ascii=False) + "\n")
        return 0

    for record in normalized_sessions:
        metadata = record["metadata"]
        name = metadata["name"] if isinstance(metadata["name"], str) else ""
        stdout.write(
            f"{record['session_id']}\t{record['session_file']}\t{record['cwd']}\t"
            f"{metadata['updated_at']}\t{name}\n"
        )
    return 0


def _session_query_from_args(args: CliArgs) -> SessionQuery | None:
    if args.session_limit is not None and args.session_limit < 0:
        raise ValueError("Session query limit must be non-negative")
    if (
        args.session_cwd is None
        and args.session_name_filter is None
        and args.session_parent is None
        and args.session_query is None
        and args.session_has_diagnostics is None
        and args.session_limit is None
    ):
        return None
    return SessionQuery(
        cwd=args.session_cwd,
        name=args.session_name_filter,
        parent_session=args.session_parent,
        text=args.session_query,
        has_diagnostics=args.session_has_diagnostics,
        limit=args.session_limit,
    )


def _run_export(
    args: CliArgs,
    session: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if args.export is None:
        return None

    if args.export_format == "jsonl":
        exporter = getattr(session, "export_to_jsonl", None)
    else:
        exporter = getattr(session, "export_to_html", None)
    if not callable(exporter):
        stderr.write(f"Error: {args.export_format} export is not available.\n")
        return 1

    export_target = args.export if args.export != "" else None
    try:
        output_path = exporter(export_target)
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if args.export_result_format == "json":
        stdout.write(
            json.dumps(
                {
                    "path": output_path,
                    "format": args.export_format,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    else:
        stdout.write(f"Exported to: {output_path}\n")
    return 0


def _run_diag_export(
    args: CliArgs,
    project_root: Path,
    session_dir: Path,
    services: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.diag_export:
        return None

    try:
        output_path = export_diagnostics_bundle(
            project_root=project_root,
            session_dir=session_dir,
            output=args.diag_output,
            diagnostics_service=getattr(services, "diagnostics_service", None),
            debug_latest_path=args.debug_file,
            trace_latest_path=args.trace_file,
        )
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1

    stdout.write(f"Exported diagnostics to: {output_path}\n")
    return 0


def _normalize_session_record(record: Any) -> dict[str, object]:
    metadata = _safe_getattr(record, "metadata", None)
    session_file = _safe_getattr(record, "session_file", None)
    if metadata is not None:
        normalized = {
            "session_id": _string_attr(record, "session_id"),
            "cwd": _string_attr(record, "cwd"),
            "session_file": _safe_string(session_file) if session_file is not None else None,
            "parent_session": _nullable_string_attr(record, "parent_session"),
            "leaf_id": _nullable_string_attr(record, "leaf_id"),
            "metadata": {
                "created_at": _string_attr(metadata, "created_at"),
                "updated_at": _string_attr(metadata, "updated_at"),
                "name": _nullable_string_attr(metadata, "name"),
            },
        }
    else:
        normalized = {
            "session_id": _string_attr(record, "session_id"),
            "cwd": _string_attr(record, "cwd"),
            "session_file": _safe_string(session_file) if session_file is not None else None,
            "parent_session": _nullable_string_attr(record, "parent_session"),
            "leaf_id": _nullable_string_attr(record, "leaf_id"),
            "metadata": {
                "created_at": _string_attr(record, "created_at"),
                "updated_at": _string_attr(record, "updated_at"),
                "name": _nullable_string_attr(record, "name"),
            },
        }

    for field_name in (
        "message_count",
        "entry_count",
        "first_message",
        "all_messages_text",
        "last_message_preview",
        "model",
        "has_diagnostics",
        "diagnostic_count",
        "last_diagnostic_code",
        "last_diagnostic_level",
    ):
        value = _safe_getattr(record, field_name, _MISSING)
        if value is not _MISSING:
            normalized[field_name] = _json_safe_value(value)
    return normalized


def _json_safe_value(value: Any) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {_safe_string(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return _safe_string(value)


def _try_normalize_session_record(record: Any) -> dict[str, object] | None:
    try:
        return _normalize_session_record(record)
    except Exception:
        return None


def _string_attr(target: Any, name: str) -> str:
    value = _safe_getattr(target, name, "")
    return value if isinstance(value, str) else _safe_string(value)


def _nullable_string_attr(target: Any, name: str) -> str | None:
    value = _safe_getattr(target, name, None)
    if value is None:
        return None
    return value if isinstance(value, str) else _safe_string(value)


def _safe_getattr(target: Any, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default


def _resolve_print_input_plan(
    args: CliArgs,
    stdin: TextIO,
    cwd: Path,
    *,
    auto_resize_images: bool = True,
) -> PrintInputPlan:
    file_text, images = _process_file_args(
        args.file_args,
        cwd,
        auto_resize_images=auto_resize_images,
    )
    parts: list[str] = []
    stdin_content = _read_stdin_prompt(stdin)
    if stdin_content is not None:
        parts.append(stdin_content)
    if file_text:
        parts.append(file_text)
    if args.prompt is not None:
        parts.append(args.prompt.strip())
    if args.messages:
        parts.append(" ".join(args.messages).strip())

    user_input = "".join(parts).strip() or None
    follow_up_messages = tuple(args.message_prompts)
    if user_input is None and follow_up_messages:
        user_input = follow_up_messages[0]
        follow_up_messages = follow_up_messages[1:]
    return PrintInputPlan(
        user_input=user_input,
        images=images or None,
        follow_up_messages=follow_up_messages,
    )


def _process_file_args(
    file_args: tuple[str, ...],
    cwd: Path,
    *,
    auto_resize_images: bool = True,
) -> tuple[str, list[ImagePart]]:
    text_parts: list[str] = []
    images: list[ImagePart] = []
    for file_arg in file_args:
        path = _resolve_at_file_path(file_arg, cwd)
        payload = path.read_bytes()
        if not payload:
            continue
        mime_type = _detect_supported_image_mime_type(path, payload)
        if mime_type is not None:
            original_dimensions = detect_image_dimensions(mime_type, payload)
            dimensions = original_dimensions
            encoded = base64.b64encode(payload)
            dimension_note: str | None = None
            if auto_resize_images and image_exceeds_inline_limits(encoded, dimensions):
                resize_result = PillowReadImageResizer().resize_image(
                    payload,
                    mime_type=mime_type,
                    dimensions=dimensions,
                )
                if resize_result is None:
                    text_parts.append(
                        f'<file name="{path}">'
                        "[Image omitted: could not be resized below the inline image size limit.]"
                        "</file>\n"
                    )
                    continue
                payload = resize_result.payload
                mime_type = resize_result.mime_type
                dimensions = resize_result.dimensions or detect_image_dimensions(mime_type, payload)
                original_dimensions = resize_result.original_dimensions or original_dimensions
                encoded = base64.b64encode(payload)
                dimension_note = format_image_dimension_note(
                    original_dimensions=original_dimensions,
                    dimensions=dimensions,
                    was_resized=resize_result.was_resized,
                )
            images.append(
                ImagePart(
                    type="image",
                    data=encoded.decode("ascii"),
                    mime_type=mime_type,
                )
            )
            text_parts.append(f'<file name="{path}">{dimension_note or ""}</file>\n')
            continue
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(f"Could not read file {path}: {error}") from error
        text_parts.append(f'<file name="{path}">\n{content}\n</file>\n')
    return "".join(text_parts), images


def _resolve_at_file_path(file_arg: str, cwd: Path) -> Path:
    return resolve_tool_path(file_arg, cwd=str(cwd))


def _detect_supported_image_mime_type(path: Path, payload: bytes) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"} and payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == ".png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix == ".gif" and (payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a")):
        return "image/gif"
    if suffix == ".webp" and len(payload) >= 12 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


def _read_stdin_prompt(stdin: TextIO) -> str | None:
    if _stream_is_tty(stdin):
        return None
    content = stdin.read()
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    return stripped or None


def _stream_is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError:
        return False


def _collect_extension_flags(session: Any) -> dict[str, ResolvedFlag]:
    runner = getattr(session, "extension_runner", None)
    if runner is None:
        return {}
    getter = getattr(runner, "get_flags", None)
    if not callable(getter):
        return {}
    flags = getter()
    collected: dict[str, ResolvedFlag] = {}
    for flag in flags:
        name = getattr(flag, "name", None)
        if isinstance(name, str) and name:
            collected[name] = flag
    return collected


def _apply_extension_flag_values(session: Any, values: dict[str, bool | str]) -> None:
    if not values:
        return
    runner = getattr(session, "extension_runner", None)
    if runner is None:
        return
    setter = getattr(runner, "set_flag_value", None)
    if not callable(setter):
        return
    for name, value in values.items():
        setter(name, value)


def _run_list_models(
    args: CliArgs,
    session: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if args.list_models is False:
        return None

    getter, include_metadata = _model_listing_getter(session)
    if getter is None:
        stderr.write("Error: model registry is not available.\n")
        return 1

    query = ""
    if isinstance(args.list_models, str):
        query = args.list_models.strip().lower()

    try:
        models = getter()
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if not isinstance(models, list):
        stderr.write("Error: model listing returned an invalid response.\n")
        return 1
    sorted_models = _unique_sorted_models(models)
    normalized_models = _normalize_model_entries(sorted_models, include_metadata=include_metadata)
    if query:
        normalized_models = [entry for entry in normalized_models if _model_entry_matches_query(entry, query)]
    if args.list_models_format == "json":
        stdout.write(json.dumps(normalized_models, ensure_ascii=False) + "\n")
        return 0

    if include_metadata:
        _write_model_metadata_table(normalized_models, stdout)
        return 0
    for selection in normalized_models:
        stdout.write(f"{selection['provider']}/{selection['model_id']}\n")
    return 0


def _model_listing_getter(session: Any) -> tuple[Callable[[], object] | None, bool]:
    details_getter = getattr(session, "get_available_model_details", None)
    if callable(details_getter):
        return details_getter, True
    getter = getattr(session, "get_available_models", None)
    if callable(getter):
        return getter, False
    return None, False


def _unique_sorted_models(models: list[Any]) -> list[Any]:
    by_key: dict[tuple[str, str], Any] = {}
    for selection in models:
        provider = _model_provider(selection)
        model_id = _model_id(selection)
        if isinstance(provider, str) and isinstance(model_id, str):
            by_key.setdefault((provider, model_id), selection)
    return [by_key[key] for key in sorted(by_key)]


def _normalize_model_entries(models: list[Any], *, include_metadata: bool = False) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for selection in models:
        provider = _model_provider(selection)
        model_id = _model_id(selection)
        if not isinstance(provider, str) or not isinstance(model_id, str):
            continue
        entry: dict[str, object] = {
            "provider": provider,
            "model_id": model_id,
            "id": f"{provider}/{model_id}",
        }
        if include_metadata:
            entry.update(
                {
                    "context_window": _optional_int_attr(selection, "context_window"),
                    "max_tokens": _optional_int_attr(selection, "max_tokens"),
                    "supports_thinking": _bool_model_attr(selection, "supports_thinking", "reasoning"),
                    "supports_images": _bool_model_attr(selection, "supports_image_input"),
                }
            )
        entries.append(entry)
    return entries


def _model_provider(selection: Any) -> str | None:
    provider = _safe_getattr(selection, "provider", None)
    if isinstance(provider, str):
        return provider
    provider_id = _safe_getattr(selection, "provider_id", None)
    return provider_id if isinstance(provider_id, str) else None


def _model_id(selection: Any) -> str | None:
    model_id = _safe_getattr(selection, "model_id", None)
    if isinstance(model_id, str):
        return model_id
    model_id = _safe_getattr(selection, "id", None)
    return model_id if isinstance(model_id, str) else None


def _optional_int_attr(selection: Any, attr: str) -> int | None:
    value = _safe_getattr(selection, attr, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool_model_attr(selection: Any, *attrs: str) -> bool:
    for attr in attrs:
        value = _safe_getattr(selection, attr, None)
        if isinstance(value, bool):
            return value
    return False


def _model_entry_matches_query(selection: dict[str, object], query: str) -> bool:
    provider = str(selection.get("provider") or "").lower()
    model_id = str(selection.get("model_id") or "").lower()
    if not provider and not model_id:
        return False
    if query in provider:
        return True
    if query in model_id:
        return True
    haystack = f"{provider}/{model_id}"
    return query in haystack or _is_subsequence(query, haystack)


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    haystack_iter = iter(haystack)
    return all(char in haystack_iter for char in needle)


def _write_model_metadata_table(models: list[dict[str, object]], stdout: TextIO) -> None:
    rows = [
        (
            str(model["provider"]),
            str(model["model_id"]),
            _format_context_window(model.get("context_window")),
            _format_optional_int(model.get("max_tokens")),
            _format_bool(model.get("supports_thinking")),
            _format_bool(model.get("supports_images")),
        )
        for model in models
    ]
    headers = ("provider", "model", "context", "max-out", "thinking", "images")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows)) if rows else len(headers[index])
        for index in range(len(headers))
    ]
    stdout.write(_format_model_table_row(headers, widths) + "\n")
    for row in rows:
        stdout.write(_format_model_table_row(row, widths) + "\n")


def _format_model_table_row(row: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()


def _format_context_window(value: object) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "-"
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}M"
    if value >= 1000 and value % 1000 == 0:
        return f"{value // 1000}K"
    return str(value)


def _format_optional_int(value: object) -> str:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else "-"


def _format_bool(value: object) -> str:
    return "yes" if value is True else "no"


def _run_list_commands(
    args: CliArgs,
    session: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_commands:
        return None

    getter = getattr(session, "list_commands", None)
    if not callable(getter):
        stderr.write("Error: command registry is not available.\n")
        return 1

    try:
        commands = getter()
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if not isinstance(commands, list):
        stderr.write("Error: command registry returned an invalid response.\n")
        return 1

    serialized_commands: list[dict[str, object]] = []
    for command in commands:
        serialized = _try_serialize_command_descriptor(command)
        if serialized is not None:
            serialized_commands.append(serialized)
    if args.list_commands_format == "json":
        stdout.write(json.dumps(serialized_commands, ensure_ascii=False) + "\n")
        return 0

    for command in serialized_commands:
        stdout.write(
            f"{command['name']}\t{command['source']}\t{command['source_info']['path']}\t"
            f"{command['description']}\n"
        )
    return 0


def _run_list_diagnostics(
    args: CliArgs,
    session: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_diagnostics:
        return None

    if args.diagnostics_limit <= 0:
        stderr.write("Error: diagnostics limit must be greater than zero.\n")
        return 1

    getter = getattr(session, "get_last_diagnostics", None)
    if not callable(getter):
        stderr.write("Error: diagnostics are not available.\n")
        return 1
    try:
        diagnostics = getter(limit=args.diagnostics_limit)
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if not isinstance(diagnostics, list):
        stderr.write("Error: diagnostics returned an invalid response.\n")
        return 1

    normalized = []
    for record in diagnostics:
        try:
            normalized.append(serialize_diagnostic(record))
        except Exception:
            continue
    if args.list_diagnostics_format == "json":
        stdout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
        return 0

    for record in normalized:
        stdout.write(
            f"{record['type']}\t{record['phase']}\t{record['source']}\t{record['code']}\t"
            f"{record['occurrenceCount']}\t{record['message']}\n"
        )
    return 0


def _run_list_skills(
    args: CliArgs,
    session: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_skills:
        return None

    skills = _session_skills(session)
    if skills is None:
        stderr.write("Error: skill loader is not available.\n")
        return 1
    normalized = [_normalize_skill_entry(skill) for skill in skills if _normalize_skill_entry(skill) is not None]
    if args.list_skills_format == "json":
        stdout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
        return 0
    for skill in normalized:
        stdout.write(f"{skill['name']}\t{skill['source_kind']}\t{skill['path']}\t{skill['enabled']}\n")
    return 0


def _session_skills(session: Any) -> list[Any] | None:
    bundle = getattr(session, "resource_bundle", None)
    skills = getattr(bundle, "skills", None)
    if isinstance(skills, list):
        return skills
    loader = getattr(session, "resource_loader", None)
    getter = getattr(loader, "get_skills", None)
    if callable(getter):
        try:
            loaded = getter()
        except Exception:
            return None
        return loaded if isinstance(loaded, list) else None
    return None


def _normalize_skill_entry(skill: Any) -> dict[str, object] | None:
    name = _safe_getattr(skill, "name", None)
    if not isinstance(name, str) or not name:
        return None
    source_path = _safe_getattr(skill, "source_path", None)
    return {
        "name": name,
        "id": _safe_getattr(skill, "id", "") or "",
        "path": _safe_string(source_path),
        "source_kind": _safe_getattr(skill, "source_kind", "") or "",
        "enabled": bool(_safe_getattr(skill, "enabled", True)),
    }


def _run_method_visibility(
    args: CliArgs,
    project_root: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_methods and args.show_method is None:
        return None

    try:
        methods = MethodLoader().discover_methods(project_root)
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1

    if args.list_methods:
        normalized = [_normalize_method_entry(method) for method in methods]
        if args.list_methods_format == "json":
            stdout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            return 0
        for method in normalized:
            stdout.write(
                f"{method['id']}\t{method['name']}\t{method['kind']}\t"
                f"{method['element_type']}\t{method['path']}\n"
            )
        return 0

    method = _find_method(methods, args.show_method or "")
    if method is None:
        stderr.write(f"Error: method not found: {args.show_method}\n")
        return 1
    payload = _normalize_method_entry(method)
    payload["description"] = _safe_getattr(method, "description", "") or ""
    payload["content"] = _safe_getattr(method, "content", "") or ""
    if args.show_method_format == "json":
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 0
    stdout.write(_format_method_detail(payload))
    return 0


def _find_method(methods: list[Any], id_or_name: str) -> Any | None:
    for method in methods:
        if _safe_getattr(method, "id", None) == id_or_name or _safe_getattr(method, "name", None) == id_or_name:
            return method
    return None


def _normalize_method_entry(method: Any) -> dict[str, object]:
    return {
        "id": _safe_getattr(method, "id", "") or "",
        "name": _safe_getattr(method, "name", "") or "",
        "kind": _safe_getattr(method, "kind", "") or "",
        "element_type": _safe_getattr(method, "element_type", None),
        "domain": _safe_getattr(method, "domain", None),
        "meta_role": _safe_getattr(method, "meta_role", None),
        "phase": _safe_getattr(method, "phase", None),
        "path": _safe_getattr(method, "source_path", "") or "",
        "applicability": _normalize_method_applicability(_safe_getattr(method, "applicability", None)),
    }


def _normalize_method_applicability(applicability: Any) -> dict[str, object]:
    return {
        "domains": _string_list(_safe_getattr(applicability, "domains", ())),
        "task_types": _string_list(_safe_getattr(applicability, "task_types", ())),
        "contexts": _string_list(_safe_getattr(applicability, "contexts", ())),
        "artifact_types": _string_list(_safe_getattr(applicability, "artifact_types", ())),
        "modalities": _string_list(_safe_getattr(applicability, "modalities", ())),
        "toolchains": _string_list(_safe_getattr(applicability, "toolchains", ())),
        "lifecycle": _string_list(_safe_getattr(applicability, "lifecycle", ())),
        "capabilities": _string_list(_safe_getattr(applicability, "capabilities", ())),
        "complexity": _optional_string(_safe_getattr(applicability, "complexity", None)),
        "risk": _optional_string(_safe_getattr(applicability, "risk", None)),
        "tags": _normalize_method_tags(_safe_getattr(applicability, "tags", {})),
    }


def _normalize_method_tags(tags: Any) -> dict[str, list[str]]:
    if not isinstance(tags, Mapping):
        return {}
    return {
        key: _string_list(value)
        for key, value in sorted(tags.items())
        if isinstance(key, str) and key and _string_list(value)
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _format_method_detail(method: Mapping[str, object]) -> str:
    lines = [
        f"id: {method['id']}",
        f"name: {method['name']}",
        f"kind: {method['kind']}",
    ]
    for key in ("element_type", "domain", "meta_role", "phase", "path", "description"):
        value = method.get(key)
        if value:
            lines.append(f"{key}: {value}")
    applicability_lines = _format_method_applicability_lines(method.get("applicability"))
    if applicability_lines:
        lines.append("applicability:")
        lines.extend(applicability_lines)
    lines.append("")
    lines.append(str(method.get("content", "")))
    if not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    return "\n".join(lines)


def _format_method_applicability_lines(applicability: object) -> list[str]:
    if not isinstance(applicability, Mapping):
        return []
    lines: list[str] = []
    for key in (
        "domains",
        "task_types",
        "contexts",
        "artifact_types",
        "modalities",
        "toolchains",
        "lifecycle",
        "capabilities",
    ):
        values = _string_list(applicability.get(key))
        if values:
            lines.append(f"  {key}: {', '.join(values)}")
    for key in ("complexity", "risk"):
        value = applicability.get(key)
        if isinstance(value, str) and value:
            lines.append(f"  {key}: {value}")
    tags = applicability.get("tags")
    if isinstance(tags, Mapping):
        for key, raw_values in sorted(tags.items()):
            values = _string_list(raw_values)
            if isinstance(key, str) and key and values:
                lines.append(f"  tags.{key}: {', '.join(values)}")
    return lines


def _run_list_plugins(
    args: CliArgs,
    services: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_plugins:
        return None

    settings_manager = getattr(services, "settings_manager", None)
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        stderr.write("Error: plugin settings are not available.\n")
        return 1
    try:
        settings = get_settings()
        plugin_sources = getattr(settings, "plugin_sources", ())
        disabled_plugins = getattr(settings, "disabled_plugins", ())
        manager = PluginManager(disabled_plugins=tuple(disabled_plugins))
        for source in plugin_sources:
            manager.add_plugin_source(source)
        plugins = manager.list_plugins()
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1

    normalized = [_normalize_plugin_entry(plugin) for plugin in plugins]
    if args.list_plugins_format == "json":
        stdout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
        return 0
    for plugin in normalized:
        stdout.write(f"{plugin['name']}\t{plugin['version']}\t{plugin['path']}\t{plugin['enabled']}\n")
    return 0


def _normalize_plugin_entry(plugin: Any) -> dict[str, object]:
    manifest = _safe_getattr(plugin, "manifest", None)
    source = _safe_getattr(plugin, "source", None)
    source_kind = _safe_getattr(source, "kind", "local")
    source_value = _safe_getattr(source, "url", None) if source_kind == "remote" else _safe_getattr(source, "path", "")
    return {
        "name": _safe_string(_safe_getattr(manifest, "name", "")),
        "version": _safe_string(_safe_getattr(manifest, "version", "")),
        "path": "" if source_kind == "remote" else _safe_string(source_value),
        "source": _safe_string(source_value),
        "kind": source_kind if isinstance(source_kind, str) else "local",
        "enabled": bool(_safe_getattr(plugin, "enabled", False)),
    }


def _run_list_packages(
    args: CliArgs,
    session: Any,
    services: Any,
    project_root: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not args.list_packages:
        return None

    get_packages = getattr(session, "get_packages", None)
    if not callable(get_packages):
        stderr.write("Error: package listing is not available.\n")
        return 1
    try:
        packages = get_packages(catalog_path=args.package_catalog)
        if not packages:
            settings_manager = getattr(services, "settings_manager", None)
            get_settings = getattr(settings_manager, "get_settings", None)
            if callable(get_settings):
                settings = get_settings()
                packages = collect_package_entries(
                    package_roots=tuple(getattr(settings, "package_roots", ())),
                    plugin_sources=tuple(getattr(settings, "plugin_sources", ())),
                    package_sources=tuple(getattr(settings, "package_sources", ())),
                    disabled_plugins=tuple(getattr(settings, "disabled_plugins", ())),
                    cwd=project_root,
                    settings_manager=settings_manager,
                    catalog_path=Path(args.package_catalog).expanduser().resolve() if args.package_catalog else None,
                    materializer=getattr(session, "_package_materializer", None),
                )
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1

    if args.list_packages_format == "json":
        stdout.write(json.dumps(packages, ensure_ascii=False) + "\n")
        return 0
    if args.list_packages_format == "tsv":
        _write_package_tsv_list(packages, stdout)
        return 0
    _write_package_text_list(packages, stdout)
    return 0


def _write_package_tsv_list(packages: list[dict[str, object]], stdout: TextIO) -> None:
    for package in packages:
        stdout.write(
            f"{package['name']}\t{package['kind']}\t{package['scope']}\t{package['version']}\t"
            f"{package['source']}\t{package['path']}\t{package['enabled']}\t"
            f"{package['prompts']}\t{package['skills']}\t{package['extensions']}\t"
            f"{package['themes']}\t{package['diagnostics']}\n"
        )


def _write_package_text_list(packages: list[dict[str, object]], stdout: TextIO) -> None:
    if not packages:
        stdout.write("No packages.\n")
        return
    scope_order = ("user", "project", "session", "merged", "catalog")
    scopes = {str(package.get("scope", "")) for package in packages}
    ordered_scopes = [scope for scope in scope_order if scope in scopes]
    ordered_scopes.extend(sorted(scope for scope in scopes if scope not in scope_order))
    first_group = True
    for scope in ordered_scopes:
        scoped_packages = [package for package in packages if str(package.get("scope", "")) == scope]
        if not scoped_packages:
            continue
        if not first_group:
            stdout.write("\n")
        first_group = False
        stdout.write(f"{_package_scope_title(scope)}:\n")
        for package in scoped_packages:
            stdout.write(f"  {_format_package_summary_line(package)}\n")
            source = str(package.get("source", ""))
            path = str(package.get("path", ""))
            if source:
                stdout.write(f"    source: {source}\n")
            if path:
                stdout.write(f"    path: {path}\n")
            resources = _format_package_resources(package)
            if resources:
                stdout.write(f"    resources: {resources}\n")


def _package_scope_title(scope: str) -> str:
    labels = {
        "user": "User packages",
        "project": "Project packages",
        "session": "Session packages",
        "merged": "Merged packages",
        "catalog": "Catalog packages",
    }
    return labels.get(scope, f"{scope.title()} packages")


def _format_package_summary_line(package: dict[str, object]) -> str:
    parts = [str(package.get("name", ""))]
    version = str(package.get("version", ""))
    if version:
        parts.append(version)
    kind = str(package.get("kind", ""))
    if kind:
        parts.append(f"[{kind}]")
    status: list[str] = []
    if package.get("enabled") is False:
        status.append("disabled")
    if package.get("filtered") is True:
        status.append("filtered")
    lifecycle = str(package.get("lifecycle", ""))
    if lifecycle and lifecycle not in {"installed", "remote_registered"}:
        status.append(lifecycle)
    if str(package.get("security", "")) == "denied":
        status.append("denied")
    if status:
        parts.append(", ".join(status))
    return " ".join(part for part in parts if part)


def _format_package_resources(package: dict[str, object]) -> str:
    parts: list[str] = []
    for key in ("prompts", "skills", "extensions", "themes", "diagnostics"):
        value = package.get(key)
        if isinstance(value, int) and value > 0:
            parts.append(f"{key}={value}")
    return " ".join(parts)


async def _run_package_lifecycle(args: CliArgs, session: Any, services: Any, stdout: TextIO, stderr: TextIO) -> int | None:
    install_operations: list[tuple[str, str, str]] = [
        ("install_package", "install_package", source) for source in args.install_packages
    ]
    operations: list[tuple[str, str, str]] = []
    operations.extend(
        ("materialize_package", "materialize_package", source) for source in args.materialize_packages
    )
    operations.extend(("update_package", "update_package", source) for source in args.update_packages)
    operations.extend(("remove_package", "remove_package", source) for source in args.remove_packages)
    operations.extend(("uninstall_package", "uninstall_package", source) for source in args.uninstall_packages)
    bulk_operations: list[tuple[str, str]] = []
    if args.check_package_updates:
        bulk_operations.append(("check_package_updates", "check_package_updates"))
    if args.update_all_packages:
        bulk_operations.append(("update_packages", "update_packages"))
    if not operations and not install_operations:
        if not bulk_operations:
            return None
    for command, method_name, source in install_operations:
        decision = PackageSecurityPolicy().evaluate_package_source(source)
        if decision.disposition == "deny":
            _record_package_policy_diagnostic(services, source=source, reason=decision.reason)
            stderr.write(f"Error: {decision.reason}\n")
            return 1
        method = getattr(session, method_name, None)
        if not callable(method):
            stderr.write(f"Error: {command} is not available.\n")
            return 1
        try:
            record = method(source, scope=args.package_scope)
            if inspect.isawaitable(record):
                record = await record
        except Exception as error:
            stderr.write(f"Error: {_format_cli_error(error)}\n")
            return 1
        if failure := _package_lifecycle_failure(record):
            stderr.write(f"Error: {failure}\n")
            return 1
        stdout.write(json.dumps({"command": command, "record": record}, ensure_ascii=False) + "\n")
    for command, method_name in bulk_operations:
        method = getattr(session, method_name, None)
        if not callable(method):
            stderr.write(f"Error: {command} is not available.\n")
            return 1
        try:
            records = method()
            if inspect.isawaitable(records):
                records = await records
        except Exception as error:
            stderr.write(f"Error: {_format_cli_error(error)}\n")
            return 1
        if command == "update_packages" and isinstance(records, list):
            for record in records:
                if failure := _package_lifecycle_failure(record):
                    stderr.write(f"Error: {failure}\n")
                    return 1
        stdout.write(json.dumps({"command": command, "records": records}, ensure_ascii=False) + "\n")
    for command, method_name, source in operations:
        method = getattr(session, method_name, None)
        if not callable(method):
            stderr.write(f"Error: {command} is not available.\n")
            return 1
        try:
            if command == "uninstall_package":
                record = method(source, scope=args.package_scope)
            else:
                record = method(source)
            if inspect.isawaitable(record):
                record = await record
        except Exception as error:
            stderr.write(f"Error: {_format_cli_error(error)}\n")
            return 1
        if failure := _package_lifecycle_failure(record):
            stderr.write(f"Error: {failure}\n")
            return 1
        stdout.write(json.dumps({"command": command, "record": record}, ensure_ascii=False) + "\n")
    return 0


def _package_lifecycle_failure(record: object) -> str | None:
    if not isinstance(record, Mapping):
        return None
    if record.get("lifecycle") != "failed":
        return None
    message = record.get("errorMessage", record.get("error_message"))
    return str(message) if isinstance(message, str) and message else "Package lifecycle failed."


def _serialize_command_descriptor(command: object) -> dict[str, object] | None:
    name = _safe_getattr(command, "name", None)
    if not isinstance(name, str) or not name:
        return None
    description = _safe_getattr(command, "description", None)
    source = _safe_getattr(command, "source", None)
    source_info = _safe_getattr(command, "source_info", None)
    payload: dict[str, object] = {
        "name": name,
        "description": description if isinstance(description, str) else "",
        "source": source if isinstance(source, str) else "",
        "source_info": {"path": _safe_string(_safe_getattr(source_info, "path", ""))},
    }
    argument_hint = _safe_getattr(command, "argument_hint", None)
    if isinstance(argument_hint, str) and argument_hint:
        payload["argument_hint"] = argument_hint
    return payload


def _try_serialize_command_descriptor(command: object) -> dict[str, object] | None:
    try:
        return _serialize_command_descriptor(command)
    except Exception:
        return None


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


async def _collect_extension_flags_for_help(
    *,
    raw_argv: list[str],
    project_root: Path,
    services: BootstrapServices | Any | None = None,
    runtime_builder=default_runtime_builder,
) -> dict[str, ExtensionFlag]:
    bootstrap_args = replace(
        parse_args(raw_argv, allow_unknown=True),
        fork=None,
        no_session=True,
    )
    resolved_services = services or build_default_services(project_root)
    try:
        session_dir = _resolve_session_dir(bootstrap_args, project_root, resolved_services)
        if bootstrap_args.no_builtin_tools:
            tool_registry = ToolRegistry()
        else:
            tool_registry = build_builtin_tool_registry(
                diagnostics_service=getattr(resolved_services, "diagnostics_service", None),
                settings_manager=getattr(resolved_services, "settings_manager", None),
            )
        runtime = runtime_builder(
            args=bootstrap_args,
            cwd=project_root,
            session_dir=session_dir,
            services=resolved_services,
            tool_registry=tool_registry,
        )
        session = await _resolve_session(bootstrap_args, runtime, project_root)
        if session is None:
            return {}
        return _collect_extension_flags(session)
    except Exception:
        return {}


def _help_text(extension_flags: Mapping[str, ExtensionFlag] | None = None) -> str:
    text = help_text().rstrip()
    if text.startswith("usage:"):
        text = "Usage:" + text[len("usage:") :]
    if extension_flags:
        text += "\n\nExtension flags:"
        for flag_name in sorted(extension_flags):
            flag = extension_flags[flag_name]
            line = f"\n  --{flag_name} [{flag.type}]"
            if flag.description:
                line += f": {flag.description}"
            if flag.default is not None:
                line += f" (default={flag.default!r})"
            text += line
    return (
        text
        + "\n\n"
        "Output formats:\n"
        "  --list-models-format text|json controls --list-models output.\n"
        "  --list-sessions-format tsv|json controls --list-sessions output; --all-sessions searches across session dirs.\n"
        "  --list-commands-format tsv|json controls --list-commands output.\n"
        "  --list-skills-format tsv|json controls --list-skills output.\n"
        "  --list-plugins-format tsv|json controls --list-plugins output.\n"
        "  --list-packages-format text|tsv|json controls --list-packages output.\n"
        "  --enable-skill/--disable-skill persist project skill toggles.\n"
        "  --add-plugin-source/--remove-plugin-source persist project plugin sources.\n"
        "  --enable-plugin/--disable-plugin persist project plugin toggles.\n"
        "  --command-result-format raw|json controls --command result output.\n"
        "  --export-format html|jsonl controls exported session file type.\n"
        "  --export-result-format text|json controls --export CLI result output.\n"
        "  diag export --output PATH writes a diagnostics bundle without starting a model session.\n"
        + "\n\n"
        "Note:\n"
        "  Extensions can register additional flags. For extension-specific help, run\n"
        "  the extension docs or check extension output directly.\n"
    )


def _package_version() -> str:
    try:
        return package_version("loushang")
    except PackageNotFoundError:
        return "0.1.0"


async def _run_command(
    args: CliArgs,
    session: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if args.command is None:
        return None

    executor = getattr(session, "execute_command_async", None)
    if not callable(executor):
        stderr.write("Error: command execution is not available.\n")
        return 1

    invocation_name = args.command.strip()
    if invocation_name.startswith("/"):
        invocation_name = invocation_name[1:].strip()
    if not invocation_name:
        stderr.write("Error: --command requires a non-empty command name.\n")
        return 2

    try:
        execution = await executor(invocation_name, args.command_args)
    except Exception as error:
        stderr.write(f"Error: {_format_cli_error(error)}\n")
        return 1
    if execution is None:
        stderr.write(f"Error: command not found: {invocation_name}\n")
        return 1

    result = getattr(execution, "result", None)
    if result is None and not hasattr(execution, "result"):
        result = execution
    if args.command_result_format == "json":
        stdout.write(
            json.dumps(
                {
                    "command": invocation_name,
                    "args": args.command_args,
                    "result": _json_safe_command_result(result),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return 0
    if result is None:
        return 0
    if isinstance(result, (dict, list, tuple)):
        try:
            text = json.dumps(result, ensure_ascii=False)
        except TypeError:
            text = repr(result)
    else:
        text = str(result)
    stdout.write(f"{text}\n")
    return 0


def _json_safe_command_result(result: object) -> object:
    try:
        json.dumps(result, ensure_ascii=False)
        return result
    except TypeError:
        return repr(result)


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    try:
        return asyncio.run(run_cli(sys.argv[1:] if argv is None else argv))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted.\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
