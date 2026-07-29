"""Product-neutral application coordinator for standard Agent CLI hosts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractContextManager, redirect_stderr
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from typing import Generic, TextIO, TypeAlias, TypeVar, cast

from loushang.harness.cli.agent_args import (
    AgentCliArgs,
    agent_cli_bootstrap_args,
    apply_agent_offline_mode,
    resolve_agent_session_dir,
)
from loushang.harness.cli.extension_flags import collect_extension_flags
from loushang.harness.cli.host_operations import (
    AgentCliEarlyOperationPorts,
    run_agent_cli_early_operation,
    run_agent_cli_session_listing,
)
from loushang.harness.cli.launch import (
    CliLaunchPlan,
    cli_output_guard_enabled,
    cli_static_error,
)
from loushang.harness.cli.resource_toggles import (
    agent_resource_toggle_request,
    report_agent_resource_settings_errors,
)
from loushang.harness.cli.session_resolution import resolve_agent_cli_session
from loushang.harness.host.product_host import ProductHostLifecycle
from loushang.harness.tools.workspace import (
    WorkspaceToolRuntimeSettings,
    workspace_tool_runtime_settings,
)

ArgsT = TypeVar("ArgsT")
StateT = TypeVar("StateT")
RuntimeT = TypeVar("RuntimeT")
SessionT = TypeVar("SessionT")
ResultT = TypeVar("ResultT")
AgentArgsT = TypeVar("AgentArgsT", bound=AgentCliArgs)

CliMaybeAsync: TypeAlias = ResultT | Awaitable[ResultT]


@dataclass(frozen=True, slots=True)
class CliParseResult(Generic[ArgsT]):
    args: ArgsT | None
    exit_code: int = 2


@dataclass(frozen=True, slots=True)
class CliPhaseResult(Generic[ResultT]):
    """A phase either continues with a value or exits with a code."""

    value: ResultT | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.exit_code is None):
            raise ValueError("CLI phase result must contain one value or exit code")

    @classmethod
    def continue_with(cls, value: ResultT) -> "CliPhaseResult[ResultT]":
        return cls(value=value)

    @classmethod
    def exit(cls, exit_code: int) -> "CliPhaseResult[ResultT]":
        return cls(exit_code=exit_code)


@dataclass(frozen=True, slots=True)
class CliBootstrapContext(Generic[ArgsT]):
    raw_argv: tuple[str, ...]
    args: ArgsT
    launch_plan: CliLaunchPlan
    project_root: Path
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO


@dataclass(frozen=True, slots=True)
class CliRuntimeContext(Generic[ArgsT, StateT, RuntimeT]):
    bootstrap: CliBootstrapContext[ArgsT]
    state: StateT
    runtime: RuntimeT


@dataclass(frozen=True, slots=True)
class CliSessionContext(Generic[ArgsT, StateT, RuntimeT, SessionT]):
    bootstrap: CliBootstrapContext[ArgsT]
    args: ArgsT
    launch_plan: CliLaunchPlan
    state: StateT
    runtime: RuntimeT
    session: SessionT


CliOutputGuard: TypeAlias = Callable[[bool], AbstractContextManager[None]]


def format_cli_error(error: BaseException) -> str:
    filename = getattr(error, "filename", None)
    if isinstance(error, OSError):
        strerror = getattr(error, "strerror", None)
        if filename is not None and strerror:
            return f"{strerror}: {filename}"
    return str(error)


@dataclass(frozen=True)
class AgentCliApplicationState(Generic[AgentArgsT]):
    """Standard state prepared before constructing an Agent Product runtime."""

    args: AgentArgsT
    services: object
    session_dir: Path
    settings_manager: object | None
    tool_registry: object
    approval_resolver: object | None
    tool_policy_evaluator: object | None = None


@dataclass(frozen=True)
class AgentCliStatePreparationContext(Generic[AgentArgsT]):
    args: AgentArgsT
    project_root: Path
    session_dir: Path
    services: object
    stdout: TextIO
    stderr: TextIO


@dataclass(frozen=True)
class AgentCliStatePreparationPorts(Generic[AgentArgsT]):
    """Product ports for the standard Agent CLI bootstrap preparation."""

    build_services: Callable[[Path], object]
    product_catalog_operation: Callable[[AgentArgsT], bool]
    pre_runtime_operation: Callable[
        [AgentCliStatePreparationContext[AgentArgsT]],
        CliMaybeAsync[int | None],
    ]
    build_empty_tool_registry: Callable[[], object]
    build_tool_registry: Callable[
        [object, WorkspaceToolRuntimeSettings, object],
        object,
    ]
    policy_factory: Callable[..., object]
    build_interactive_approval_resolver: Callable[[], object]
    run_resource_toggle: Callable[..., int | None]
    evaluate_plugin_source: Callable[[str], str | None] | None = None
    is_remote_plugin_source: Callable[[str], bool] | None = None
    on_policy_denied: Callable[[object, str, str | None], None] | None = None
    format_error: Callable[[BaseException], str] = str


async def prepare_agent_cli_application_state(
    context: CliBootstrapContext[AgentArgsT],
    *,
    ports: AgentCliStatePreparationPorts[AgentArgsT],
    services: object | None = None,
) -> CliPhaseResult[AgentCliApplicationState[AgentArgsT]]:
    """Prepare shared resource, session-path, approval, and tool state."""

    args = context.args
    resolved_services = services or ports.build_services(context.project_root)
    settings_manager = getattr(resolved_services, "settings_manager", None)
    report_agent_resource_settings_errors(
        args,
        settings_manager,
        stderr=context.stderr,
    )
    toggle_result = ports.run_resource_toggle(
        settings_manager,
        agent_resource_toggle_request(args),
        stdout=context.stdout,
        stderr=context.stderr,
        evaluate_plugin_source=ports.evaluate_plugin_source,
        is_remote_plugin_source=ports.is_remote_plugin_source,
        on_policy_denied=(
            (
                lambda source, reason: ports.on_policy_denied(
                    resolved_services,
                    source,
                    reason,
                )
            )
            if ports.on_policy_denied is not None
            else None
        ),
        format_error=ports.format_error,
    )
    if toggle_result is not None:
        return CliPhaseResult.exit(toggle_result)

    runtime_args = agent_cli_bootstrap_args(
        args,
        product_catalog_operation=ports.product_catalog_operation(args),
    )
    session_dir = resolve_agent_session_dir(
        runtime_args,
        project_root=context.project_root,
        settings_manager=settings_manager,
    )
    pre_runtime_result = await _resolve(
        ports.pre_runtime_operation(
            AgentCliStatePreparationContext(
                args=runtime_args,
                project_root=context.project_root,
                session_dir=session_dir,
                services=resolved_services,
                stdout=context.stdout,
                stderr=context.stderr,
            )
        )
    )
    if pre_runtime_result is not None:
        return CliPhaseResult.exit(pre_runtime_result)

    tool_settings = workspace_tool_runtime_settings(
        settings_manager,
        policy_factory=ports.policy_factory,
    )
    configured_resolver = tool_settings.approval_resolver
    interactive_resolver = (
        ports.build_interactive_approval_resolver()
        if configured_resolver is None
        else None
    )
    approval_resolver = configured_resolver or interactive_resolver
    tool_registry = (
        ports.build_empty_tool_registry()
        if runtime_args.no_builtin_tools
        else ports.build_tool_registry(
            resolved_services,
            tool_settings,
            approval_resolver,
        )
    )
    return CliPhaseResult.continue_with(
        AgentCliApplicationState(
            args=runtime_args,
            services=resolved_services,
            session_dir=session_dir,
            settings_manager=settings_manager,
            tool_registry=tool_registry,
            approval_resolver=interactive_resolver,
            tool_policy_evaluator=tool_settings.policy_engine,
        )
    )


async def collect_agent_cli_help_extension_flags(
    raw_argv: Sequence[str],
    *,
    project_root: Path,
    parse_args: Callable[[Sequence[str]], AgentArgsT],
    state_ports: AgentCliStatePreparationPorts[AgentArgsT],
    build_runtime: Callable[
        [AgentArgsT, Path, Path, object, object],
        object,
    ],
    resolve_session: Callable[
        [AgentArgsT, object, Path],
        CliMaybeAsync[object | None],
    ],
    services: object | None = None,
) -> dict[str, object]:
    """Discover extension flags using the Product's standard CLI bindings."""

    args = replace(
        parse_args(raw_argv),
        fork=None,
        no_session=True,
    )
    resolved_services = services or state_ports.build_services(project_root)
    try:
        session_dir = resolve_agent_session_dir(
            args,
            project_root=project_root,
            settings_manager=getattr(resolved_services, "settings_manager"),
        )
        tool_settings = workspace_tool_runtime_settings(
            getattr(resolved_services, "settings_manager"),
            policy_factory=state_ports.policy_factory,
        )
        tool_registry = (
            state_ports.build_empty_tool_registry()
            if args.no_builtin_tools
            else state_ports.build_tool_registry(
                resolved_services,
                tool_settings,
                tool_settings.approval_resolver,
            )
        )
        runtime = build_runtime(
            args,
            project_root,
            session_dir,
            resolved_services,
            tool_registry,
        )
        session = await _resolve(resolve_session(args, runtime, project_root))
        return collect_extension_flags(session) if session is not None else {}
    except Exception:
        return {}


@dataclass(frozen=True)
class CliApplicationPorts(Generic[ArgsT, StateT, RuntimeT, SessionT]):
    """Product bindings for the shared CLI application phase order."""

    parse_args: Callable[
        [Sequence[str], TextIO, Mapping[str, object] | None, bool],
        CliParseResult[ArgsT],
    ]
    initialize_args: Callable[[ArgsT], None]
    launch_plan: Callable[[ArgsT], CliLaunchPlan]
    args_cwd: Callable[[ArgsT], str | None]
    early_operation: Callable[[CliBootstrapContext[ArgsT]], CliMaybeAsync[int | None]]
    validated_operation: Callable[
        [CliBootstrapContext[ArgsT]], CliMaybeAsync[int | None]
    ]
    prepare_state: Callable[
        [CliBootstrapContext[ArgsT]], CliMaybeAsync[CliPhaseResult[StateT]]
    ]
    startup_context: Callable[
        [CliBootstrapContext[ArgsT], StateT], AbstractContextManager[None]
    ]
    build_runtime: Callable[
        [CliBootstrapContext[ArgsT], StateT], CliMaybeAsync[RuntimeT]
    ]
    runtime_operation: Callable[
        [CliRuntimeContext[ArgsT, StateT, RuntimeT]],
        CliMaybeAsync[int | None],
    ]
    resolve_session: Callable[
        [CliRuntimeContext[ArgsT, StateT, RuntimeT]],
        CliMaybeAsync[SessionT | None],
    ]
    collect_extension_flags: Callable[[SessionT], Mapping[str, object]]
    configure_session: Callable[
        [CliSessionContext[ArgsT, StateT, RuntimeT, SessionT]],
        CliMaybeAsync[int | None],
    ]
    session_operations: Callable[
        [CliSessionContext[ArgsT, StateT, RuntimeT, SessionT]],
        CliMaybeAsync[int | None],
    ]
    run_host: Callable[
        [CliSessionContext[ArgsT, StateT, RuntimeT, SessionT]],
        CliMaybeAsync[int],
    ]
    output_guard: CliOutputGuard
    pre_session_bootstrap: Callable[
        [CliRuntimeContext[ArgsT, StateT, RuntimeT]],
        CliMaybeAsync[CliPhaseResult[SessionT] | None],
    ] = lambda _context: None
    format_error: Callable[[BaseException], str] = str


@dataclass(frozen=True)
class AgentCliApplicationBinding(Generic[AgentArgsT]):
    """Product callbacks compiled onto the standard Agent CLI phase runtime."""

    parse_args: Callable[
        [Sequence[str], TextIO, Mapping[str, object] | None, bool],
        CliParseResult[AgentArgsT],
    ]
    launch_plan: Callable[[AgentArgsT], CliLaunchPlan]
    state_ports: AgentCliStatePreparationPorts[AgentArgsT]
    runtime_builder: Callable[..., object]
    format_help: Callable[[Mapping[str, object]], str]
    package_version: Callable[[], str]
    runtime_identity: Callable[[Path], Mapping[str, object]]
    format_runtime_identity: Callable[[Mapping[str, object]], str]
    validated_operation: Callable[
        [CliBootstrapContext[AgentArgsT]], CliMaybeAsync[int | None]
    ]
    startup_context: Callable[
        [
            CliBootstrapContext[AgentArgsT],
            AgentCliApplicationState[AgentArgsT],
        ],
        AbstractContextManager[None],
    ]
    configure_session: Callable[
        [
            CliSessionContext[
                AgentArgsT,
                AgentCliApplicationState[AgentArgsT],
                object,
                object,
            ]
        ],
        CliMaybeAsync[int | None],
    ]
    session_operations: Callable[
        [
            CliSessionContext[
                AgentArgsT,
                AgentCliApplicationState[AgentArgsT],
                object,
                object,
            ]
        ],
        CliMaybeAsync[int | None],
    ]
    run_host: Callable[
        [
            CliSessionContext[
                AgentArgsT,
                AgentCliApplicationState[AgentArgsT],
                object,
                object,
            ]
        ],
        CliMaybeAsync[int],
    ]
    host_lifecycle: ProductHostLifecycle
    services: object | None = None
    format_error: Callable[[BaseException], str] = format_cli_error
    session_resolution_error: (
        Callable[
            [
                CliRuntimeContext[
                    AgentArgsT, AgentCliApplicationState[AgentArgsT], object
                ]
            ],
            str | None,
        ]
        | None
    ) = None
    pre_session_bootstrap: (
        Callable[
            [
                CliRuntimeContext[
                    AgentArgsT,
                    AgentCliApplicationState[AgentArgsT],
                    object,
                ]
            ],
            CliMaybeAsync[CliPhaseResult[object] | None],
        ]
        | None
    ) = None


def build_agent_cli_application_ports(
    binding: AgentCliApplicationBinding[AgentArgsT],
) -> CliApplicationPorts[
    AgentArgsT,
    AgentCliApplicationState[AgentArgsT],
    object,
    object,
]:
    """Compile Product callbacks without duplicating the CLI phase sequence."""

    early_ports = AgentCliEarlyOperationPorts(
        collect_help_flags=lambda raw_argv, project_root: (
            collect_agent_cli_help_extension_flags(
                raw_argv,
                project_root=project_root,
                parse_args=lambda values: cast(
                    AgentArgsT,
                    binding.parse_args(values, StringIO(), None, True).args,
                ),
                state_ports=binding.state_ports,
                build_runtime=lambda args, cwd, session_dir, services, registry: (
                    invoke_agent_cli_runtime_builder(
                        binding.runtime_builder,
                        args=args,
                        cwd=cwd,
                        session_dir=session_dir,
                        services=services,
                        tool_registry=registry,
                        approval_resolver=None,
                        tool_policy_evaluator=None,
                    )
                ),
                resolve_session=resolve_agent_cli_session,
                services=binding.services,
            )
        ),
        format_help=binding.format_help,
        package_version=binding.package_version,
        runtime_identity=binding.runtime_identity,
        format_runtime_identity=binding.format_runtime_identity,
        output_guard=lambda enabled: binding.host_lifecycle.output_guard(
            enabled=enabled
        ),
    )
    return CliApplicationPorts(
        parse_args=binding.parse_args,
        initialize_args=apply_agent_offline_mode,
        launch_plan=binding.launch_plan,
        args_cwd=lambda args: args.cwd,
        early_operation=lambda context: run_agent_cli_early_operation(
            context.args,
            raw_argv=context.raw_argv,
            launch_plan=context.launch_plan,
            project_root=context.project_root,
            stdout=context.stdout,
            stderr=context.stderr,
            ports=early_ports,
        ),
        validated_operation=binding.validated_operation,
        prepare_state=lambda context: prepare_agent_cli_application_state(
            context,
            ports=binding.state_ports,
            services=binding.services,
        ),
        startup_context=binding.startup_context,
        build_runtime=lambda context, state: invoke_agent_cli_runtime_builder(
            binding.runtime_builder,
            args=state.args,
            cwd=context.project_root,
            session_dir=state.session_dir,
            services=state.services,
            tool_registry=state.tool_registry,
            approval_resolver=state.approval_resolver,
            tool_policy_evaluator=state.tool_policy_evaluator,
        ),
        runtime_operation=lambda context: run_agent_cli_session_listing(
            context.state.args,
            context.runtime,
            stdout=context.bootstrap.stdout,
            stderr=context.bootstrap.stderr,
            format_error=binding.format_error,
        ),
        pre_session_bootstrap=(
            binding.pre_session_bootstrap
            if binding.pre_session_bootstrap is not None
            else lambda _context: None
        ),
        resolve_session=lambda context: _resolve_bound_agent_cli_session(
            context,
            session_resolution_error=binding.session_resolution_error,
        ),
        collect_extension_flags=collect_extension_flags,
        configure_session=binding.configure_session,
        session_operations=binding.session_operations,
        run_host=binding.run_host,
        output_guard=lambda enabled: binding.host_lifecycle.output_guard(
            enabled=enabled
        ),
        format_error=binding.format_error,
    )


async def run_agent_cli_application(
    argv: Sequence[str],
    *,
    binding: AgentCliApplicationBinding[AgentArgsT],
    cwd: str | Path | None = None,
) -> int:
    """Run one Product binding through the canonical Agent CLI application."""

    application = CliApplicationRuntime(build_agent_cli_application_ports(binding))
    streams = binding.host_lifecycle.streams
    return await application.run(
        argv,
        stdin=streams.stdin,
        stdout=streams.stdout,
        stderr=streams.stderr,
        cwd=cwd,
    )


async def _resolve_bound_agent_cli_session(
    context: CliRuntimeContext[
        AgentArgsT,
        AgentCliApplicationState[AgentArgsT],
        object,
    ],
    *,
    session_resolution_error: (
        Callable[
            [
                CliRuntimeContext[
                    AgentArgsT, AgentCliApplicationState[AgentArgsT], object
                ]
            ],
            str | None,
        ]
        | None
    ),
) -> object:
    if session_resolution_error is not None:
        message = session_resolution_error(context)
        if message is not None:
            raise RuntimeError(message)
    return await resolve_agent_cli_session(
        context.state.args,
        context.runtime,
        context.bootstrap.project_root,
    )


class CliApplicationRuntime(Generic[ArgsT, StateT, RuntimeT, SessionT]):
    """Run the standard two-pass Agent CLI application lifecycle."""

    def __init__(
        self,
        ports: CliApplicationPorts[ArgsT, StateT, RuntimeT, SessionT],
    ) -> None:
        self._ports = ports

    async def run(
        self,
        argv: Sequence[str],
        *,
        stdin: TextIO,
        stdout: TextIO,
        stderr: TextIO,
        cwd: str | Path | None = None,
    ) -> int:
        raw_argv = tuple(argv)
        parsed = self._ports.parse_args(raw_argv, stderr, None, True)
        if parsed.args is None:
            return parsed.exit_code
        bootstrap_args = parsed.args
        self._ports.initialize_args(bootstrap_args)
        project_root = Path(
            cwd or self._ports.args_cwd(bootstrap_args) or Path.cwd()
        ).resolve()
        bootstrap = CliBootstrapContext(
            raw_argv=raw_argv,
            args=bootstrap_args,
            launch_plan=self._ports.launch_plan(bootstrap_args),
            project_root=project_root,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

        early_result = await _resolve(self._ports.early_operation(bootstrap))
        if early_result is not None:
            return early_result
        static_error = cli_static_error(bootstrap.launch_plan)
        if static_error is not None:
            stderr.write(f"Error: {static_error}.\n")
            return 2
        validated_result = await _resolve(self._ports.validated_operation(bootstrap))
        if validated_result is not None:
            return validated_result

        with self._ports.output_guard(cli_output_guard_enabled(bootstrap.launch_plan)):
            prepared = await _resolve(self._ports.prepare_state(bootstrap))
        if prepared.exit_code is not None:
            return prepared.exit_code
        state = cast(StateT, prepared.value)

        with self._ports.startup_context(bootstrap, state):
            with self._ports.output_guard(
                cli_output_guard_enabled(bootstrap.launch_plan)
            ):
                runtime = await _resolve(self._ports.build_runtime(bootstrap, state))
            runtime_context = CliRuntimeContext(
                bootstrap=bootstrap,
                state=state,
                runtime=runtime,
            )
            with self._ports.output_guard(
                cli_output_guard_enabled(self._ports.launch_plan(bootstrap_args))
            ):
                runtime_result = await _resolve(
                    self._ports.runtime_operation(runtime_context)
                )
            if runtime_result is not None:
                return runtime_result
            try:
                with self._ports.output_guard(
                    cli_output_guard_enabled(bootstrap.launch_plan)
                ):
                    pre_session = await _resolve(
                        self._ports.pre_session_bootstrap(runtime_context)
                    )
                    if pre_session is not None:
                        if pre_session.exit_code is not None:
                            return pre_session.exit_code
                        session = cast(SessionT, pre_session.value)
                    else:
                        session = await _resolve(
                            self._ports.resolve_session(runtime_context)
                        )
            except (
                FileNotFoundError,
                NotADirectoryError,
                RuntimeError,
                ValueError,
            ) as error:
                stderr.write(f"Error: {self._ports.format_error(error)}\n")
                return 1
        if session is None:
            return 2

        extension_flags = self._ports.collect_extension_flags(session)
        parsed = self._ports.parse_args(
            raw_argv,
            stderr,
            extension_flags,
            False,
        )
        if parsed.args is None:
            return parsed.exit_code
        args = parsed.args
        session_context = CliSessionContext(
            bootstrap=bootstrap,
            args=args,
            launch_plan=self._ports.launch_plan(args),
            state=state,
            runtime=runtime,
            session=session,
        )
        with self._ports.output_guard(
            cli_output_guard_enabled(session_context.launch_plan)
        ):
            configure_result = await _resolve(
                self._ports.configure_session(session_context)
            )
            if configure_result is not None:
                return configure_result
            operation_result = await _resolve(
                self._ports.session_operations(session_context)
            )
            if operation_result is not None:
                return operation_result
            return await _resolve(self._ports.run_host(session_context))


def capture_cli_parse(
    parser: Callable[..., ArgsT],
    argv: Sequence[str],
    stderr: TextIO,
    extension_flags: Mapping[str, object] | None,
    allow_unknown: bool,
) -> CliParseResult[ArgsT]:
    """Run a Product argparse adapter without taking ownership of process stderr."""

    try:
        with redirect_stderr(stderr):
            return CliParseResult(
                parser(
                    argv,
                    extension_flags=extension_flags,
                    allow_unknown=allow_unknown,
                )
            )
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 2
        return CliParseResult(args=None, exit_code=code)


def invoke_cli_builder(
    builder: Callable[..., ResultT],
    *,
    required: Mapping[str, object],
    optional: Mapping[str, object] | None = None,
) -> ResultT:
    """Invoke a Product builder with only supported additive keywords."""

    kwargs = dict(required)
    for name, value in (optional or {}).items():
        if _accepts_keyword(builder, name):
            kwargs[name] = value
    return builder(**kwargs)


def invoke_agent_cli_runtime_builder(
    builder: Callable[..., ResultT],
    *,
    args: AgentCliArgs,
    cwd: Path,
    session_dir: Path,
    services: object,
    tool_registry: object,
    approval_resolver: object | None,
    tool_policy_evaluator: object | None = None,
) -> ResultT:
    """Invoke an Agent runtime builder with the standard CLI arguments."""

    return invoke_cli_builder(
        builder,
        required={
            "args": args,
            "cwd": cwd,
            "session_dir": session_dir,
            "services": services,
            "tool_registry": tool_registry,
        },
        optional={
            "approval_resolver": approval_resolver,
            "tool_policy_evaluator": tool_policy_evaluator,
        },
    )


def _accepts_keyword(callback: Callable[..., object], name: str) -> bool:
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
        candidate.kind is inspect.Parameter.VAR_KEYWORD
        for candidate in parameters.values()
    )


async def _resolve(value: CliMaybeAsync[ResultT]) -> ResultT:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "AgentCliApplicationBinding",
    "AgentCliApplicationState",
    "AgentCliStatePreparationContext",
    "AgentCliStatePreparationPorts",
    "CliApplicationPorts",
    "CliApplicationRuntime",
    "CliBootstrapContext",
    "CliOutputGuard",
    "CliParseResult",
    "CliPhaseResult",
    "CliRuntimeContext",
    "CliSessionContext",
    "build_agent_cli_application_ports",
    "capture_cli_parse",
    "collect_agent_cli_help_extension_flags",
    "format_cli_error",
    "invoke_cli_builder",
    "invoke_agent_cli_runtime_builder",
    "prepare_agent_cli_application_state",
    "run_agent_cli_application",
]
