from __future__ import annotations

import asyncio
from argparse import ArgumentParser
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from types import SimpleNamespace

from loushang.harness.cli import (
    AgentCliApplicationBinding,
    AgentCliStatePreparationPorts,
    CliApplicationPorts,
    CliApplicationRuntime,
    CliBootstrapContext,
    CliLaunchPlan,
    CliParseResult,
    CliPhaseResult,
    capture_cli_parse,
    collect_agent_cli_help_extension_flags,
    format_cli_error,
    invoke_agent_cli_runtime_builder,
    invoke_cli_builder,
    prepare_agent_cli_application_state,
    report_agent_resource_settings_errors,
    run_agent_cli_application,
)
from loushang.harness.host.product_host import ProductHostLifecycle
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.tools.workspace import WorkspaceToolRuntimeSettings


@dataclass(frozen=True)
class _Args:
    cwd: str | None = None
    invalid_launch: bool = False


@dataclass(frozen=True)
class _ApplicationArgs:
    no_session: bool = False
    session_dir: str | None = None
    no_builtin_tools: bool = False
    list_commands: bool = False
    list_diagnostics: bool = False
    list_skills: bool = False
    list_plugins: bool = False
    list_packages: bool = False
    list_models: str | bool = False
    enable_skills: tuple[str, ...] = ()
    disable_skills: tuple[str, ...] = ()
    add_plugin_sources: tuple[str, ...] = ()
    remove_plugin_sources: tuple[str, ...] = ()
    enable_plugins: tuple[str, ...] = ()
    disable_plugins: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ResearchArgs(_ApplicationArgs):
    offline: bool = False
    help: bool = False
    version: bool = False
    source_info: bool = False
    source_info_format: str = "text"
    cwd: str | None = None
    list_sessions: bool = False
    list_sessions_format: str = "tsv"
    all_sessions: bool = False
    session_index: bool = False
    refresh_session_index: bool = False
    session_cwd: str | None = None
    session_name_filter: str | None = None
    session_parent: str | None = None
    session_query: str | None = None
    session_has_diagnostics: bool | None = None
    session_limit: int | None = None
    session: str | None = None
    continue_: bool = False
    resume: bool | str = False
    fork: str | None = None


def test_application_runtime_owns_two_pass_session_phase_order(tmp_path) -> None:
    calls: list[object] = []
    runtime = object()
    session = object()
    extension_flag = object()
    stdin = StringIO()
    stdout = StringIO()
    stderr = StringIO()

    def parse_args(argv, output, flags, allow_unknown):
        assert output is stderr
        calls.append(("parse", tuple(argv), flags, allow_unknown))
        return CliParseResult(_Args())

    @contextmanager
    def startup_context(_context, _state):
        calls.append("startup_enter")
        try:
            yield
        finally:
            calls.append("startup_exit")

    application = CliApplicationRuntime(
        CliApplicationPorts[
            _Args,
            str,
            object,
            object,
        ](
            parse_args=parse_args,
            initialize_args=lambda _args: calls.append("initialize"),
            launch_plan=lambda _args: CliLaunchPlan(),
            args_cwd=lambda args: args.cwd,
            early_operation=lambda _context: calls.append("early"),
            validated_operation=lambda _context: calls.append("validated"),
            prepare_state=lambda _context: (
                calls.append("prepare") or CliPhaseResult.continue_with("state")
            ),
            startup_context=startup_context,
            build_runtime=lambda _context, _state: (
                calls.append("build_runtime") or runtime
            ),
            runtime_operation=lambda _context: calls.append("runtime_operation"),
            resolve_session=lambda _context: calls.append("resolve_session") or session,
            collect_extension_flags=lambda value: (
                calls.append(("collect_flags", value)) or {"example": extension_flag}
            ),
            configure_session=lambda _context: calls.append("configure"),
            session_operations=lambda _context: calls.append("operations"),
            run_host=lambda _context: calls.append("host") or 7,
            output_guard=lambda enabled: (
                calls.append(("guard", enabled)) or _null_context()
            ),
        )
    )

    result = asyncio.run(
        application.run(
            ("--example",),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
        )
    )

    assert result == 7
    assert calls == [
        ("parse", ("--example",), None, True),
        "initialize",
        "early",
        "validated",
        ("guard", False),
        "prepare",
        "startup_enter",
        ("guard", False),
        "build_runtime",
        ("guard", False),
        "runtime_operation",
        ("guard", False),
        "resolve_session",
        "startup_exit",
        ("collect_flags", session),
        ("parse", ("--example",), {"example": extension_flag}, False),
        ("guard", False),
        "configure",
        "operations",
        "host",
    ]
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_application_pre_session_bootstrap_bypasses_default_resolution(
    tmp_path,
) -> None:
    selected_session = object()
    hosted: list[object] = []
    application = CliApplicationRuntime(
        CliApplicationPorts[
            _Args,
            str,
            object,
            object,
        ](
            parse_args=lambda *_args: CliParseResult(_Args()),
            initialize_args=lambda _args: None,
            launch_plan=lambda _args: CliLaunchPlan(),
            args_cwd=lambda args: args.cwd,
            early_operation=lambda _context: None,
            validated_operation=lambda _context: None,
            prepare_state=lambda _context: CliPhaseResult.continue_with("state"),
            startup_context=lambda _context, _state: _null_context(),
            build_runtime=lambda _context, _state: object(),
            runtime_operation=lambda _context: None,
            pre_session_bootstrap=lambda _context: CliPhaseResult.continue_with(
                selected_session
            ),
            resolve_session=lambda _context: (_ for _ in ()).throw(
                AssertionError("default resolution must not create a placeholder")
            ),
            collect_extension_flags=lambda _session: {},
            configure_session=lambda _context: None,
            session_operations=lambda _context: None,
            run_host=lambda context: hosted.append(context.session) or 0,
            output_guard=lambda _enabled: _null_context(),
        )
    )

    result = asyncio.run(
        application.run(
            ("--resume",),
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
        )
    )

    assert result == 0
    assert hosted == [selected_session]


def test_application_runtime_rejects_static_launch_conflict_before_prepare(
    tmp_path,
) -> None:
    stderr = StringIO()
    application = CliApplicationRuntime(
        CliApplicationPorts[
            _Args,
            str,
            object,
            object,
        ](
            parse_args=lambda *_args: CliParseResult(_Args(invalid_launch=True)),
            initialize_args=lambda _args: None,
            launch_plan=lambda args: CliLaunchPlan(
                force_tui=args.invalid_launch,
                disable_tui=args.invalid_launch,
            ),
            args_cwd=lambda args: args.cwd,
            early_operation=lambda _context: None,
            validated_operation=lambda _context: None,
            prepare_state=lambda _context: (_ for _ in ()).throw(
                AssertionError("prepare must not run")
            ),
            startup_context=lambda _context, _state: _null_context(),
            build_runtime=lambda _context, _state: object(),
            runtime_operation=lambda _context: None,
            resolve_session=lambda _context: object(),
            collect_extension_flags=lambda _session: {},
            configure_session=lambda _context: None,
            session_operations=lambda _context: None,
            run_host=lambda _context: 0,
            output_guard=lambda _enabled: _null_context(),
        )
    )

    result = asyncio.run(
        application.run(
            (),
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
        )
    )

    assert result == 2
    assert stderr.getvalue() == "Error: --tui and --no-tui cannot be used together.\n"


def test_application_helpers_preserve_parser_and_builder_boundaries() -> None:
    parser = ArgumentParser(add_help=False)
    parser.add_argument("--name", required=True)
    stderr = StringIO()

    parsed = capture_cli_parse(
        lambda argv, **_kwargs: parser.parse_args(argv),
        (),
        stderr,
        None,
        False,
    )
    captured: dict[str, object] = {}

    def builder(*, required: object, optional: object = None) -> object:
        captured.update(required=required, optional=optional)
        return object()

    result = invoke_cli_builder(
        builder,
        required={"required": "value"},
        optional={"optional": "extra", "unsupported": True},
    )

    assert parsed.args is None
    assert parsed.exit_code == 2
    assert "required" in stderr.getvalue()
    assert result is not None
    assert captured == {"required": "value", "optional": "extra"}
    assert (
        format_cli_error(FileNotFoundError(2, "missing", "/tmp/example"))
        == "missing: /tmp/example"
    )


def test_agent_runtime_builder_receives_standard_binding_values(tmp_path) -> None:
    captured: dict[str, object] = {}

    def builder(
        *,
        args: object,
        cwd: object,
        session_dir: object,
        services: object,
        tool_registry: object,
        approval_resolver: object,
    ) -> str:
        captured.update(
            args=args,
            cwd=cwd,
            session_dir=session_dir,
            services=services,
            tool_registry=tool_registry,
            approval_resolver=approval_resolver,
        )
        return "runtime"

    args = _ApplicationArgs()
    result = invoke_agent_cli_runtime_builder(
        builder,
        args=args,
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services="services",
        tool_registry="tools",
        approval_resolver="approval",
    )

    assert result == "runtime"
    assert captured == {
        "args": args,
        "cwd": tmp_path,
        "session_dir": tmp_path / "sessions",
        "services": "services",
        "tool_registry": "tools",
        "approval_resolver": "approval",
    }


def test_resource_settings_errors_are_reported_for_standard_operations() -> None:
    stderr = StringIO()
    args = type(
        "Args",
        (),
        {
            "list_plugins": True,
            "list_packages": False,
            "enable_skills": (),
            "disable_skills": (),
            "add_plugin_sources": (),
            "remove_plugin_sources": (),
            "enable_plugins": (),
            "disable_plugins": (),
        },
    )()
    manager = type(
        "Settings",
        (),
        {
            "drain_errors": lambda _self: [
                type("Error", (), {"scope": "project", "message": "invalid"})()
            ]
        },
    )()

    report_agent_resource_settings_errors(args, manager, stderr=stderr)

    assert stderr.getvalue() == "Warning (package command, project settings): invalid\n"


def test_agent_application_state_preparation_binds_product_tools_and_approval(
    tmp_path,
) -> None:
    calls: list[object] = []
    policy_engine = object()
    args = _ApplicationArgs()
    manager = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(session_dir=None),
        get_tool_settings=lambda: None,
    )
    services = SimpleNamespace(settings_manager=manager)
    stdout = StringIO()
    stderr = StringIO()
    context = CliBootstrapContext(
        raw_argv=(),
        args=args,
        launch_plan=CliLaunchPlan(),
        project_root=tmp_path,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )
    ports = AgentCliStatePreparationPorts(
        build_services=lambda _root: services,
        product_catalog_operation=lambda _args: False,
        pre_runtime_operation=lambda value: calls.append(
            ("pre_runtime", value.session_dir)
        ),
        build_empty_tool_registry=lambda: "empty",
        build_tool_registry=lambda _services, runtime_settings, approval: (
            calls.append(("tools", runtime_settings, approval)) or "registry"
        ),
        policy_factory=lambda **_kwargs: policy_engine,
        build_interactive_approval_resolver=lambda: "interactive",
        run_resource_toggle=lambda *_args, **_kwargs: None,
    )

    result = asyncio.run(prepare_agent_cli_application_state(context, ports=ports))

    assert result.exit_code is None
    assert result.value is not None
    assert result.value.session_dir == tmp_path / ".loushang" / "sessions"
    assert result.value.tool_registry == "registry"
    assert result.value.approval_resolver == "interactive"
    assert calls == [
        ("pre_runtime", tmp_path / ".loushang" / "sessions"),
        (
            "tools",
            WorkspaceToolRuntimeSettings(policy_engine=policy_engine),
            "interactive",
        ),
    ]
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_agent_application_state_preparation_resolves_tool_settings_once(
    tmp_path,
) -> None:
    policy_engine = object()
    policy_calls: list[dict[str, object]] = []
    captured: dict[str, object] = {}
    manager = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(session_dir=None),
        get_tool_settings=lambda: SimpleNamespace(blocked_tools=("bash",)),
    )
    services = SimpleNamespace(settings_manager=manager)
    context = CliBootstrapContext(
        raw_argv=(),
        args=_ApplicationArgs(),
        launch_plan=CliLaunchPlan(),
        project_root=tmp_path,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    def policy_factory(**kwargs: object) -> object:
        policy_calls.append(kwargs)
        return policy_engine

    def build_tool_registry(
        _services: object,
        runtime_settings: WorkspaceToolRuntimeSettings,
        approval_resolver: object,
    ) -> str:
        captured["runtime_settings"] = runtime_settings
        captured["approval_resolver"] = approval_resolver
        return "registry"

    ports = AgentCliStatePreparationPorts(
        build_services=lambda _root: services,
        product_catalog_operation=lambda _args: False,
        pre_runtime_operation=lambda _context: None,
        build_empty_tool_registry=lambda: "empty",
        build_tool_registry=build_tool_registry,
        policy_factory=policy_factory,
        build_interactive_approval_resolver=lambda: "interactive",
        run_resource_toggle=lambda *_args, **_kwargs: None,
    )

    result = asyncio.run(prepare_agent_cli_application_state(context, ports=ports))

    assert result.value is not None
    assert result.value.tool_registry == "registry"
    assert policy_calls == [
        {
                "blocked_tools": ("bash",),
                "ask_tools": (),
                "blocked_capabilities": ("workspace.command",),
                "ask_capabilities": (),
                "blocked_substrings": (),
            "ask_substrings": (),
            "blocked_path_substrings": (),
            "ask_path_substrings": (),
        }
    ]
    runtime_settings = captured["runtime_settings"]
    assert isinstance(runtime_settings, WorkspaceToolRuntimeSettings)
    assert runtime_settings.policy_engine is policy_engine
    assert captured["approval_resolver"] == "interactive"


@dataclass(frozen=True)
class _HelpArgs:
    fork: str | None = "source"
    no_session: bool = False
    no_builtin_tools: bool = False
    session_dir: str | None = None


def test_help_extension_discovery_reuses_agent_state_ports(tmp_path) -> None:
    captured: list[_HelpArgs] = []
    flag = SimpleNamespace(name="research-mode")
    session = SimpleNamespace(
        extension_runner=SimpleNamespace(get_flags=lambda: [flag])
    )
    manager = SimpleNamespace(get_settings=lambda: SimpleNamespace(session_dir=None))
    services = SimpleNamespace(settings_manager=manager)
    state_ports = AgentCliStatePreparationPorts(
        build_services=lambda _root: services,
        product_catalog_operation=lambda _args: False,
        pre_runtime_operation=lambda _context: None,
        build_empty_tool_registry=lambda: "empty",
        build_tool_registry=lambda _services, _runtime_settings, _approval: "registry",
        policy_factory=lambda **_kwargs: object(),
        build_interactive_approval_resolver=lambda: object(),
        run_resource_toggle=lambda *_args, **_kwargs: None,
    )

    result = asyncio.run(
        collect_agent_cli_help_extension_flags(
            ("--help",),
            project_root=tmp_path,
            parse_args=lambda _argv: _HelpArgs(),
            state_ports=state_ports,
            build_runtime=lambda args, *_rest: captured.append(args) or "runtime",
            resolve_session=lambda *_args: session,
        )
    )

    assert result == {"research-mode": flag}
    assert captured == [
        _HelpArgs(
            fork=None,
            no_session=True,
        )
    ]


def test_agent_application_binding_runs_non_coding_product(tmp_path) -> None:
    calls: list[object] = []
    args = _ResearchArgs()
    session = SimpleNamespace(extension_runner=None)
    manager = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(session_dir=None),
        get_tool_settings=lambda: None,
    )
    services = SimpleNamespace(settings_manager=manager)

    class _Runtime:
        async def new_session_operation(self, *, cwd):
            calls.append(("new_session", cwd))
            return SessionOperationResult(None, session, None, False)

    runtime = _Runtime()
    state_ports = AgentCliStatePreparationPorts(
        build_services=lambda _root: services,
        product_catalog_operation=lambda _args: False,
        pre_runtime_operation=lambda _context: calls.append("pre_runtime"),
        build_empty_tool_registry=lambda: "empty",
        build_tool_registry=lambda _services, _runtime_settings, approval: (
            calls.append(("tools", approval)) or "research-tools"
        ),
        policy_factory=lambda **_kwargs: object(),
        build_interactive_approval_resolver=lambda: "research-approval",
        run_resource_toggle=lambda *_args, **_kwargs: None,
    )

    @contextmanager
    def startup_context(_context, _state):
        calls.append("startup_enter")
        try:
            yield
        finally:
            calls.append("startup_exit")

    binding = AgentCliApplicationBinding(
        parse_args=lambda _argv, _stderr, flags, allow_unknown: (
            calls.append(("parse", flags, allow_unknown)) or CliParseResult(args)
        ),
        launch_plan=lambda _args: CliLaunchPlan(),
        state_ports=state_ports,
        runtime_builder=lambda **kwargs: (
            calls.append(
                (
                    "runtime",
                    kwargs["tool_registry"],
                    kwargs["approval_resolver"],
                )
            )
            or runtime
        ),
        format_help=lambda _flags: "research help\n",
        package_version=lambda: "1.0",
        runtime_identity=lambda _root: {"product": "research"},
        format_runtime_identity=lambda value: str(value),
        validated_operation=lambda _context: calls.append("validated"),
        startup_context=startup_context,
        configure_session=lambda _context: calls.append("configure"),
        session_operations=lambda _context: calls.append("operations"),
        run_host=lambda _context: calls.append("host") or 9,
        host_lifecycle=ProductHostLifecycle.resolve(
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=StringIO(),
        ),
        services=services,
    )

    result = asyncio.run(
        run_agent_cli_application(
            (),
            binding=binding,
            cwd=tmp_path,
        )
    )

    assert result == 9
    assert calls == [
        ("parse", None, True),
        "validated",
        "pre_runtime",
        ("tools", "research-approval"),
        "startup_enter",
        ("runtime", "research-tools", "research-approval"),
        ("new_session", str(tmp_path)),
        "startup_exit",
        ("parse", {}, False),
        "configure",
        "operations",
        "host",
    ]


@contextmanager
def _null_context():
    yield
