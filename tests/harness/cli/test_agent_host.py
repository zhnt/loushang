from __future__ import annotations

import asyncio
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from loushang.harness.cli import (
    AgentCliHostRequest,
    AgentCliHostRunners,
    AgentCliSessionHostBinding,
    CliBootstrapContext,
    CliLaunchPlan,
    CliPreparedTurn,
    CliSessionContext,
    PreparedAgentCliHostInput,
    prepare_agent_cli_host_input,
    run_agent_cli_host,
    run_agent_cli_session_host,
)
from loushang.harness.host.prompt_input import PromptInputPlan


def test_agent_cli_host_runs_product_prepared_turns_through_mode_binding() -> None:
    calls: list[dict[str, object]] = []

    async def mode_runner(**kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    async def run_turns(turns, *, run_turn, dispose_candidates) -> int:
        del dispose_candidates
        return await run_turn(turns[0], True, True)

    async def unused(**kwargs: object) -> int:
        raise AssertionError(f"unexpected host runner: {kwargs!r}")

    request = AgentCliHostRequest(
        launch_plan=CliLaunchPlan(mode="json"),
        effective_tui=False,
        runtime="runtime",
        session="session",
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
        project_root=Path("/workspace"),
        verbose=False,
        file_input=False,
        workflow_path=None,
        workflow_output_mode="json",
        work_event_log=None,
        work_runtime=None,
        plain_work_port=None,
        prepare_host_input=lambda: PreparedAgentCliHostInput(
            turns=(CliPreparedTurn("summarize"),),
        ),
    )
    runners = AgentCliHostRunners(
        run_turns=run_turns,
        mode=mode_runner,
        prompt=unused,
        workflow=unused,
        plain=unused,
        rpc=unused,
        channel=unused,
        tui=unused,
        prompt_plan=unused,
        plain_plan=unused,
        default_mode=mode_runner,
        default_prompt=unused,
        default_plain=unused,
        default_rpc=unused,
    )

    assert asyncio.run(run_agent_cli_host(request, runners)) == 0
    assert calls[0]["user_input"] == "summarize"
    assert calls[0]["runtime"] == "runtime"
    assert calls[0]["work_port"] is None
    assert calls[0]["config"].mode == "json"


def test_agent_cli_host_selects_tui_before_product_input_preparation() -> None:
    prepare_calls = 0
    tui_calls: list[dict[str, object]] = []

    def prepare() -> PreparedAgentCliHostInput:
        nonlocal prepare_calls
        prepare_calls += 1
        raise AssertionError("TUI must not prepare prompt input")

    async def tui(**kwargs: object) -> int:
        tui_calls.append(kwargs)
        return 7

    async def unused(**kwargs: object) -> int:
        raise AssertionError(f"unexpected host runner: {kwargs!r}")

    request = AgentCliHostRequest(
        launch_plan=CliLaunchPlan(),
        effective_tui=True,
        runtime="runtime",
        session="session",
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
        project_root=Path("/workspace"),
        verbose=True,
        file_input=False,
        workflow_path=None,
        workflow_output_mode="text",
        work_event_log=None,
        work_runtime=None,
        plain_work_port=None,
        prepare_host_input=prepare,
    )
    runners = AgentCliHostRunners(
        run_turns=unused,
        mode=unused,
        prompt=unused,
        workflow=unused,
        plain=unused,
        rpc=unused,
        channel=unused,
        tui=tui,
        prompt_plan=unused,
        plain_plan=unused,
        default_mode=unused,
        default_prompt=unused,
        default_plain=unused,
        default_rpc=unused,
    )

    assert asyncio.run(run_agent_cli_host(request, runners)) == 7
    assert prepare_calls == 0
    assert tui_calls[0]["verbose"] is True


def test_agent_cli_host_input_preparation_uses_product_domain_callbacks() -> None:
    stderr = StringIO()

    result = prepare_agent_cli_host_input(
        resolve_input=lambda: PromptInputPlan(
            user_input="research topic",
            images=None,
            follow_up_messages=("verify sources",),
        ),
        prepare_turns=lambda text: (f"prepared:{text}",),
        project_cli_turns=lambda turns: (
            CliPreparedTurn(str(turns[0])),
        ),
        project_plan_turns=lambda turns, images, follow_up: (
            turns[0],
            images,
            follow_up,
        ),
        stderr=stderr,
        format_error=str,
    )

    assert result.exit_code is None
    assert result.value is not None
    assert result.value.turns == (CliPreparedTurn("prepared:research topic"),)
    assert result.value.follow_up_messages == ("verify sources",)
    assert result.value.plan_turns == (
        "prepared:research topic",
        None,
        ("verify sources",),
    )
    assert stderr.getvalue() == ""


def test_agent_session_host_binding_composes_work_and_observability() -> None:
    calls: list[object] = []
    stdin = StringIO()
    stdout = StringIO()
    stderr = StringIO()
    args = SimpleNamespace(verbose=False, file_args=(), mode="json")
    bootstrap = CliBootstrapContext(
        raw_argv=(),
        args=args,
        launch_plan=CliLaunchPlan(mode="json"),
        project_root=Path("/workspace"),
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
    context = CliSessionContext(
        bootstrap=bootstrap,
        args=args,
        launch_plan=bootstrap.launch_plan,
        state="state",
        runtime="runtime",
        session="session",
    )

    async def mode_runner(**kwargs: object) -> int:
        calls.append(("mode", kwargs["work_port"]))
        return 0

    async def run_turns(turns, *, run_turn, dispose_candidates) -> int:
        del dispose_candidates
        return await run_turn(turns[0], True, True)

    async def unused(**kwargs: object) -> int:
        raise AssertionError(f"unexpected host runner: {kwargs!r}")

    @contextmanager
    def observability(_args, session, cwd, mode):
        calls.append(("observability", session, cwd, mode))
        yield

    binding = AgentCliSessionHostBinding(
        stream_is_tty=lambda _stream: False,
        resolve_work_event_log=lambda _args, root: ("log", root),
        build_work_runtime=lambda session, event_log: (
            session,
            event_log,
        ),
        bind_plain_work_port=lambda runtime: ("port", runtime),
        workflow_path=lambda _args: None,
        workflow_output_mode=lambda _args: "json",
        prepare_host_input=lambda _context: PreparedAgentCliHostInput(
            turns=(CliPreparedTurn("analyze"),)
        ),
        observability_context=observability,
    )
    runners = AgentCliHostRunners(
        run_turns=run_turns,
        mode=mode_runner,
        prompt=unused,
        workflow=unused,
        plain=unused,
        rpc=unused,
        channel=unused,
        tui=unused,
        prompt_plan=unused,
        plain_plan=unused,
        default_mode=mode_runner,
        default_prompt=unused,
        default_plain=unused,
        default_rpc=unused,
    )

    assert (
        asyncio.run(
            run_agent_cli_session_host(
                context,
                binding=binding,
                runners=runners,
            )
        )
        == 0
    )
    assert calls == [
        ("observability", "session", Path("/workspace"), "json"),
        ("mode", ("port", ("session", ("log", Path("/workspace"))))),
    ]
