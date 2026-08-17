"""Reusable CLI host operations over injected Product capabilities."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TextIO

from loushang.harness.cli.agent_args import AgentCliArgs
from loushang.harness.cli.command_execution import (
    CommandExecutionError,
    CommandExecutionRequest,
    execute_command,
    format_command_execution_result,
)
from loushang.harness.cli.command_listing import (
    CommandListingError,
    format_command_records,
    list_command_records,
)
from loushang.harness.cli.diagnostics_listing import (
    DiagnosticsListingError,
    DiagnosticsListingRequest,
    format_diagnostic_records,
    list_diagnostic_records,
)
from loushang.harness.cli.export import (
    ExportOperationError,
    ExportRequest,
    ExportResultFormat,
    export_session,
    format_export_result,
)
from loushang.harness.cli.launch import (
    CliLaunchPlan,
    cli_help_belongs_on_stderr,
    cli_output_guard_enabled,
)
from loushang.harness.cli.model_listing import (
    ModelListingError,
    ModelListingRequest,
    list_model_entries,
)
from loushang.harness.cli.package_lifecycle import (
    PackageLifecycleError,
    PackageLifecycleRequest,
    run_package_lifecycle,
)
from loushang.harness.cli.plugin_listing import (
    PluginListingError,
    format_plugin_records,
    list_plugin_records,
)
from loushang.harness.cli.resource_toggles import (
    ResourceToggleError,
    ResourceToggleRequest,
    apply_resource_toggles,
)
from loushang.harness.cli.runtime import (
    CliOperationInsertion,
    CliOperationSequence,
    CliOperationStage,
    compose_cli_operation_stages,
)
from loushang.harness.cli.session_listing import (
    SessionListingError,
    SessionListingFormat,
    SessionListingRequest,
    build_session_query,
    format_session_records,
    list_session_records,
)
from loushang.harness.cli.skill_listing import (
    SkillListingError,
    format_skill_records,
    list_skill_records,
)
from loushang.harness.diagnostics import export_diagnostics_bundle
from loushang.harness.session.model_selection import format_model_metadata_table
from loushang.harness.transcript.session_catalog import try_project_session_record

CliErrorFormatter = Callable[[BaseException], str]
PolicyEvaluator = Callable[[str], str | None]
PolicyDeniedHandler = Callable[[str, str | None], None]
RemoteSourcePredicate = Callable[[str], bool]


def distribution_version(
    distribution: str,
    *,
    fallback: str = "0.1.0",
) -> str:
    """Resolve an installed distribution version with a source-tree fallback."""

    try:
        return version(distribution)
    except PackageNotFoundError:
        return fallback


@dataclass(frozen=True)
class AgentCliEarlyOperationPorts:
    """Product bindings for standard help, version, and source-info exits."""

    collect_help_flags: Callable[
        [Sequence[str], Path],
        Mapping[str, object] | Awaitable[Mapping[str, object]],
    ]
    format_help: Callable[[Mapping[str, object]], str]
    package_version: Callable[[], str]
    runtime_identity: Callable[[Path], Mapping[str, object]]
    format_runtime_identity: Callable[[Mapping[str, object]], str]
    output_guard: Callable[[bool], AbstractContextManager[None]]


async def run_agent_cli_early_operation(
    args: AgentCliArgs,
    *,
    raw_argv: Sequence[str],
    launch_plan: CliLaunchPlan,
    project_root: Path,
    stdout: TextIO,
    stderr: TextIO,
    ports: AgentCliEarlyOperationPorts,
) -> int | None:
    """Run standard pre-bootstrap informational operations."""

    if args.help:
        with ports.output_guard(cli_output_guard_enabled(launch_plan)):
            extension_flags = ports.collect_help_flags(raw_argv, project_root)
            if inspect.isawaitable(extension_flags):
                extension_flags = await extension_flags
        output = stderr if cli_help_belongs_on_stderr(launch_plan) else stdout
        output.write(ports.format_help(extension_flags))
        return 0
    if args.version:
        stdout.write(f"{ports.package_version()}\n")
        return 0
    if args.source_info:
        source_identity = ports.runtime_identity(project_root)
        if args.source_info_format == "json":
            stdout.write(json.dumps(source_identity, ensure_ascii=False) + "\n")
        else:
            stdout.write(ports.format_runtime_identity(source_identity) + "\n")
        return 0
    return None


def run_diagnostics_export_operation(
    *,
    requested: bool,
    project_root: Path,
    session_dir: Path,
    output: str | None,
    diagnostics_service: object | None,
    debug_latest_path: str | None,
    trace_latest_path: str | None,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
    success_prefix: str = "Exported diagnostics to:",
) -> int | None:
    """Export diagnostics through the shared archive engine."""

    if not requested:
        return None
    try:
        output_path = export_diagnostics_bundle(
            project_root=project_root,
            session_dir=session_dir,
            output=output,
            diagnostics_service=diagnostics_service,
            debug_latest_path=debug_latest_path,
            trace_latest_path=trace_latest_path,
        )
    except Exception as error:
        stderr.write(f"Error: {format_error(error)}\n")
        return 1
    stdout.write(f"{success_prefix} {output_path}\n")
    return 0


@dataclass(frozen=True, slots=True)
class SessionListingOperationRequest:
    """CLI-facing session query fields resolved inside the operation boundary."""

    output_format: SessionListingFormat = "tsv"
    cwd: str | None = None
    name: str | None = None
    parent_session: str | None = None
    text: str | None = None
    has_diagnostics: bool | None = None
    limit: int | None = None
    all_sessions: bool = False
    indexed: bool = False
    refresh_index: bool = False


@dataclass(frozen=True, slots=True)
class StandardCliOperationRequest:
    """Product-selected requests for the standard Agent CLI operation pack."""

    export: ExportRequest | None = None
    export_result_format: ExportResultFormat = "text"
    command_listing_format: str | None = None
    diagnostics: DiagnosticsListingRequest | None = None
    diagnostics_output_format: str = "tsv"
    skill_listing_format: str | None = None
    plugin_listing_format: str | None = None
    package_lifecycle: PackageLifecycleRequest | None = None
    command: CommandExecutionRequest | None = None
    model_listing: ModelListingRequest | None = None
    model_listing_output_format: str = "text"


def agent_session_listing_request(
    args: AgentCliArgs,
) -> SessionListingOperationRequest | None:
    if not args.list_sessions:
        return None
    return SessionListingOperationRequest(
        output_format=args.list_sessions_format,
        cwd=args.session_cwd,
        name=args.session_name_filter,
        parent_session=args.session_parent,
        text=args.session_query,
        has_diagnostics=args.session_has_diagnostics,
        limit=args.session_limit,
        all_sessions=args.all_sessions,
        indexed=args.session_index or args.refresh_session_index,
        refresh_index=args.refresh_session_index,
    )


def run_agent_cli_session_listing(
    args: AgentCliArgs,
    runtime: object,
    *,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    """Run the session listing selected by standard Agent CLI arguments."""

    return run_session_listing_operation(
        runtime,
        agent_session_listing_request(args),
        stdout=stdout,
        stderr=stderr,
        format_error=format_error,
    )


def agent_standard_cli_operation_request(
    args: AgentCliArgs,
) -> StandardCliOperationRequest:
    package_request = PackageLifecycleRequest(
        install=tuple(args.install_packages),
        materialize=tuple(args.materialize_packages),
        update=tuple(args.update_packages),
        remove=tuple(args.remove_packages),
        uninstall=tuple(args.uninstall_packages),
        check_updates=args.check_package_updates,
        update_all=args.update_all_packages,
        scope=args.package_scope,
    )
    model_request = (
        ModelListingRequest(
            query=args.list_models.strip().lower()
            if isinstance(args.list_models, str)
            else ""
        )
        if args.list_models is not False
        else None
    )
    return StandardCliOperationRequest(
        export=ExportRequest(format=args.export_format, output=args.export)
        if args.export is not None
        else None,
        export_result_format=args.export_result_format,
        command_listing_format=args.list_commands_format
        if args.list_commands
        else None,
        diagnostics=DiagnosticsListingRequest(limit=args.diagnostics_limit)
        if args.list_diagnostics
        else None,
        diagnostics_output_format=args.list_diagnostics_format,
        skill_listing_format=args.list_skills_format if args.list_skills else None,
        plugin_listing_format=args.list_plugins_format
        if args.list_plugins
        else None,
        package_lifecycle=package_request if package_request.has_operations else None,
        command=CommandExecutionRequest(
            command=args.command,
            args=args.command_args,
            result_format=args.command_result_format,
        )
        if args.command is not None
        else None,
        model_listing=model_request,
        model_listing_output_format=args.list_models_format,
    )


async def run_standard_cli_operations(
    session: object,
    settings_manager: object | None,
    request: StandardCliOperationRequest,
    *,
    stdout: TextIO,
    stderr: TextIO,
    insertions: Sequence[CliOperationInsertion] = (),
    evaluate_install_source: PolicyEvaluator | None = None,
    on_policy_denied: PolicyDeniedHandler | None = None,
    format_error: CliErrorFormatter = str,
) -> int | None:
    """Run the standard Agent CLI operation pack in stable precedence order."""

    stages = (
        CliOperationStage(
            "export",
            lambda: run_export_operation(
                session,
                request.export,
                result_format=request.export_result_format,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "list_commands",
            lambda: run_command_listing_operation(
                session,
                request.command_listing_format,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "list_diagnostics",
            lambda: run_diagnostics_listing_operation(
                session,
                request.diagnostics,
                output_format=request.diagnostics_output_format,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "list_skills",
            lambda: run_skill_listing_operation(
                session,
                request.skill_listing_format,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "list_plugins",
            lambda: run_plugin_listing_operation(
                settings_manager,
                request.plugin_listing_format,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "package_lifecycle",
            lambda: run_package_lifecycle_operation(
                session,
                request.package_lifecycle,
                stdout=stdout,
                stderr=stderr,
                evaluate_install_source=evaluate_install_source,
                on_policy_denied=on_policy_denied,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "command",
            lambda: run_command_operation(
                session,
                request.command,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
        CliOperationStage(
            "list_models",
            lambda: run_model_listing_operation(
                session,
                request.model_listing,
                output_format=request.model_listing_output_format,
                stdout=stdout,
                stderr=stderr,
                format_error=format_error,
            ),
        ),
    )
    return await CliOperationSequence(
        compose_cli_operation_stages(stages, insertions)
    ).run()


def run_session_listing_operation(
    runtime: object,
    request: SessionListingOperationRequest | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None:
        return None
    try:
        query = build_session_query(
            cwd=request.cwd,
            name=request.name,
            parent_session=request.parent_session,
            text=request.text,
            has_diagnostics=request.has_diagnostics,
            limit=request.limit,
        )
        records = list_session_records(
            runtime,
            SessionListingRequest(
                query=query,
                all_sessions=request.all_sessions,
                indexed=request.indexed,
                refresh_index=request.refresh_index,
            ),
            record_projector=try_project_session_record,
        )
    except (SessionListingError, ValueError) as error:
        return _write_error(stderr, error, format_error=format_error)
    stdout.write(format_session_records(records, request.output_format))
    return 0


def run_export_operation(
    session: object,
    request: ExportRequest | None,
    *,
    result_format: ExportResultFormat,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None:
        return None
    try:
        result = export_session(session, request)
    except ExportOperationError as error:
        return _write_error(stderr, error, format_error=format_error)
    stdout.write(format_export_result(result, result_format))
    return 0


def run_model_listing_operation(
    session: object,
    request: ModelListingRequest | None,
    *,
    output_format: str,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None:
        return None
    try:
        result = list_model_entries(session, request)
    except ModelListingError as error:
        return _write_error(stderr, error, format_error=format_error)
    entries = list(result.entries)
    if output_format == "json":
        stdout.write(json.dumps(entries, ensure_ascii=False) + "\n")
    elif result.includes_metadata:
        stdout.write(format_model_metadata_table(entries))
    else:
        for selection in entries:
            stdout.write(f"{selection['id']}\n")
    return 0


def run_command_listing_operation(
    session: object,
    output_format: str | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if output_format is None:
        return None
    try:
        records = list_command_records(session)
    except CommandListingError as error:
        return _write_error(stderr, error, format_error=format_error)
    stdout.write(format_command_records(records, output_format))
    return 0


def run_diagnostics_listing_operation(
    session: object,
    request: DiagnosticsListingRequest | None,
    *,
    output_format: str,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None:
        return None
    try:
        records = list_diagnostic_records(session, request)
    except DiagnosticsListingError as error:
        return _write_error(stderr, error, format_error=format_error)
    stdout.write(format_diagnostic_records(records, output_format))
    return 0


def run_skill_listing_operation(
    session: object,
    output_format: str | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if output_format is None:
        return None
    try:
        records = list_skill_records(session)
    except SkillListingError as error:
        return _write_error(stderr, error, format_error=format_error)
    stdout.write(format_skill_records(records, output_format))
    return 0


def run_plugin_listing_operation(
    settings_manager: object | None,
    output_format: str | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if output_format is None:
        return None
    try:
        records = list_plugin_records(settings_manager)
    except PluginListingError as error:
        return _write_error(stderr, error, format_error=format_error)
    stdout.write(format_plugin_records(records, output_format))
    return 0


def run_resource_toggle_operation(
    settings_manager: object | None,
    request: ResourceToggleRequest | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    evaluate_plugin_source: PolicyEvaluator | None = None,
    is_remote_plugin_source: RemoteSourcePredicate | None = None,
    on_policy_denied: PolicyDeniedHandler | None = None,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None or not request.has_operations:
        return None
    if settings_manager is None:
        stderr.write("Error: settings manager is not available.\n")
        return 1
    try:
        result = apply_resource_toggles(
            settings_manager,
            request,
            evaluate_plugin_source=evaluate_plugin_source,
            is_remote_plugin_source=is_remote_plugin_source,
            on_policy_denied=on_policy_denied,
        )
    except ResourceToggleError as error:
        for message in error.messages:
            stdout.write(f"{message}\n")
        return _write_error(stderr, error, format_error=format_error)
    except Exception as error:
        return _write_error(stderr, error, format_error=format_error)
    for message in result.messages:
        stdout.write(f"{message}\n")
    return 0


async def run_package_lifecycle_operation(
    session: object,
    request: PackageLifecycleRequest | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    evaluate_install_source: PolicyEvaluator | None = None,
    on_policy_denied: PolicyDeniedHandler | None = None,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None or not request.has_operations:
        return None
    try:
        result = await run_package_lifecycle(
            session,
            request,
            evaluate_install_source=evaluate_install_source,
            on_policy_denied=on_policy_denied,
        )
    except PackageLifecycleError as error:
        _write_json_records(stdout, error.outputs)
        return _write_error(stderr, error, format_error=format_error)
    _write_json_records(stdout, result.outputs)
    return 0


async def run_command_operation(
    session: object,
    request: CommandExecutionRequest | None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    format_error: CliErrorFormatter = str,
) -> int | None:
    if request is None:
        return None
    try:
        result = await execute_command(session, request)
    except CommandExecutionError as error:
        exit_code = 2 if "requires a non-empty" in str(error) else 1
        return _write_error(
            stderr,
            error,
            format_error=format_error,
            exit_code=exit_code,
        )
    stdout.write(
        format_command_execution_result(result, result_format=request.result_format)
    )
    return 0


def _write_error(
    stderr: TextIO,
    error: BaseException,
    *,
    format_error: CliErrorFormatter,
    exit_code: int = 1,
) -> int:
    stderr.write(f"Error: {format_error(error)}\n")
    return exit_code


def _write_json_records(
    stdout: TextIO,
    records: tuple[Mapping[str, object], ...],
) -> None:
    for record in records:
        stdout.write(json.dumps(record, ensure_ascii=False) + "\n")


__all__ = [
    "AgentCliEarlyOperationPorts",
    "CliErrorFormatter",
    "SessionListingOperationRequest",
    "StandardCliOperationRequest",
    "agent_session_listing_request",
    "agent_standard_cli_operation_request",
    "distribution_version",
    "run_agent_cli_early_operation",
    "run_agent_cli_session_listing",
    "run_command_listing_operation",
    "run_command_operation",
    "run_diagnostics_listing_operation",
    "run_diagnostics_export_operation",
    "run_export_operation",
    "run_model_listing_operation",
    "run_package_lifecycle_operation",
    "run_plugin_listing_operation",
    "run_resource_toggle_operation",
    "run_session_listing_operation",
    "run_skill_listing_operation",
    "run_standard_cli_operations",
]
