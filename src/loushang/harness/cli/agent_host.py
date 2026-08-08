"""Composition binding for standard Agent CLI host modes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TextIO, TypeVar, cast

from loushang.harness.cli.agent_args import AgentCliArgs
from loushang.harness.cli.application import CliPhaseResult, CliSessionContext
from loushang.harness.cli.launch import (
    CliLaunchPlan,
    cli_observability_mode,
    cli_runtime_error,
    resolve_effective_tui,
)
from loushang.harness.cli.turns import (
    CliKeywordRunner,
    CliPreparedTurn,
    run_keyword_cli_turns,
)
from loushang.harness.host.mode import ModeConfig, ModeName
from loushang.harness.host.prompt_input import PromptInputPlan

ArgsT = TypeVar("ArgsT", bound=AgentCliArgs)
StateT = TypeVar("StateT")

PrepareHostInput = Callable[
    [],
    "PreparedAgentCliHostInput | CliPhaseResult[PreparedAgentCliHostInput] | "
    "Awaitable[PreparedAgentCliHostInput | "
    "CliPhaseResult[PreparedAgentCliHostInput]]",
]


@dataclass(frozen=True, slots=True)
class PreparedAgentCliHostInput:
    """Product-prepared turns consumed by standard prompt/plain hosts."""

    turns: tuple[CliPreparedTurn, ...]
    images: object | None = None
    follow_up_messages: tuple[str, ...] = ()
    plan_turns: tuple[object, ...] = ()


@dataclass(frozen=True)
class AgentCliHostRequest:
    """Resolved Product state for one shared Agent CLI host dispatch."""

    launch_plan: CliLaunchPlan
    effective_tui: bool
    runtime: object
    session: object
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    project_root: Path
    verbose: bool
    file_input: bool
    workflow_path: Path | None
    workflow_output_mode: str
    work_event_log: object | None
    work_runtime: object | None
    plain_work_port: object | None
    prepare_host_input: PrepareHostInput


@dataclass(frozen=True)
class AgentCliHostRunners:
    """Injected Product adapters around existing shared host components."""

    run_turns: Callable[..., Awaitable[int]]
    mode: CliKeywordRunner
    prompt: CliKeywordRunner
    workflow: Callable[..., object]
    plain: CliKeywordRunner
    rpc: Callable[..., object]
    channel: Callable[..., object]
    tui: Callable[..., object]
    prompt_plan: Callable[..., object]
    plain_plan: Callable[..., object]
    default_mode: CliKeywordRunner
    default_prompt: CliKeywordRunner
    default_plain: CliKeywordRunner
    default_rpc: Callable[..., object]


@dataclass(frozen=True)
class AgentCliSessionHostBinding(Generic[ArgsT, StateT]):
    """Product callbacks around the shared session host composition."""

    stream_is_tty: Callable[[TextIO], bool]
    resolve_work_event_log: Callable[[ArgsT, Path], object | None]
    build_work_runtime: Callable[[object, object], object]
    bind_plain_work_port: Callable[[object], object]
    workflow_path: Callable[[ArgsT], Path | None]
    workflow_output_mode: Callable[[ArgsT], str]
    prepare_host_input: Callable[
        [CliSessionContext[ArgsT, StateT, object, object]],
        PreparedAgentCliHostInput
        | CliPhaseResult[PreparedAgentCliHostInput]
        | Awaitable[
            PreparedAgentCliHostInput | CliPhaseResult[PreparedAgentCliHostInput]
        ],
    ]
    observability_context: Callable[
        [ArgsT, object, Path, str],
        AbstractContextManager[None],
    ]

    def bind(
        self,
        runners: AgentCliHostRunners,
    ) -> Callable[
        [CliSessionContext[ArgsT, StateT, object, object]],
        Awaitable[int],
    ]:
        """Bind Product callbacks to the shared Agent session host."""

        return lambda context: run_agent_cli_session_host(
            context,
            binding=self,
            runners=runners,
        )


async def run_agent_cli_session_host(
    context: CliSessionContext[ArgsT, StateT, object, object],
    *,
    binding: AgentCliSessionHostBinding[ArgsT, StateT],
    runners: AgentCliHostRunners,
) -> int:
    """Bind a Product session to the existing Agent CLI host dispatcher."""

    bootstrap = context.bootstrap
    args = context.args
    effective_tui = resolve_effective_tui(
        context.launch_plan,
        stdin_is_tty=binding.stream_is_tty(bootstrap.stdin),
        stdout_is_tty=binding.stream_is_tty(bootstrap.stdout),
    )
    work_event_log = binding.resolve_work_event_log(
        args,
        bootstrap.project_root,
    )
    work_runtime = (
        binding.build_work_runtime(context.session, work_event_log)
        if work_event_log is not None
        else None
    )
    plain_work_port = (
        binding.bind_plain_work_port(work_runtime) if work_runtime is not None else None
    )
    mode = cli_observability_mode(
        context.launch_plan,
        effective_tui=effective_tui,
    )
    with binding.observability_context(
        args,
        context.session,
        bootstrap.project_root,
        mode,
    ):
        return await run_agent_cli_host(
            AgentCliHostRequest(
                launch_plan=context.launch_plan,
                effective_tui=effective_tui,
                runtime=context.runtime,
                session=context.session,
                stdin=bootstrap.stdin,
                stdout=bootstrap.stdout,
                stderr=bootstrap.stderr,
                project_root=bootstrap.project_root,
                verbose=args.verbose,
                file_input=bool(args.file_args),
                workflow_path=binding.workflow_path(args),
                workflow_output_mode=binding.workflow_output_mode(args),
                work_event_log=work_event_log,
                work_runtime=work_runtime,
                plain_work_port=plain_work_port,
                prepare_host_input=lambda: binding.prepare_host_input(context),
            ),
            runners,
        )


def prepare_agent_cli_host_input(
    *,
    resolve_input: Callable[[], PromptInputPlan],
    prepare_turns: Callable[[str], Sequence[object]],
    project_cli_turns: Callable[[Sequence[object]], tuple[CliPreparedTurn, ...]],
    project_plan_turns: Callable[
        [Sequence[object], object | None, tuple[str, ...]],
        tuple[object, ...],
    ],
    stderr: TextIO,
    format_error: Callable[[BaseException], str],
    format_preparation_error: Callable[[BaseException], str] | None = None,
    missing_prompt_error: str = (
        "prompt is required for prompt/text/print/json modes."
    ),
) -> CliPhaseResult[PreparedAgentCliHostInput]:
    """Prepare standard Agent host input around Product domain callbacks."""

    try:
        prompt_input = resolve_input()
    except (OSError, UnicodeDecodeError, RuntimeError) as error:
        stderr.write(f"Error: {format_error(error)}\n")
        return CliPhaseResult.exit(1)
    if prompt_input.user_input is None:
        stderr.write(f"Error: {missing_prompt_error}\n")
        return CliPhaseResult.exit(2)
    try:
        turns = tuple(prepare_turns(prompt_input.user_input))
    except ValueError as error:
        formatter = format_preparation_error or format_error
        stderr.write(f"Error: {formatter(error)}\n")
        return CliPhaseResult.exit(1)
    return CliPhaseResult.continue_with(
        PreparedAgentCliHostInput(
            turns=project_cli_turns(turns),
            images=prompt_input.images,
            follow_up_messages=prompt_input.follow_up_messages,
            plan_turns=project_plan_turns(
                turns,
                prompt_input.images,
                prompt_input.follow_up_messages,
            ),
        )
    )


async def run_agent_cli_host(
    request: AgentCliHostRequest,
    runners: AgentCliHostRunners,
) -> int:
    """Dispatch one Agent Product host without owning Product preparation."""

    runtime_error = cli_runtime_error(
        request.launch_plan,
        effective_tui=request.effective_tui,
    )
    if runtime_error is not None:
        request.stderr.write(f"Error: {runtime_error}.\n")
        return 2
    if request.effective_tui:
        return await _invoke_with_optional(
            runners.tui,
            required={
                "runtime": request.runtime,
                "session": request.session,
                "stdin": request.stdin,
                "stdout": request.stdout,
                "stderr": request.stderr,
                "verbose": request.verbose,
            },
            optional={},
        )
    mode = request.launch_plan.mode
    if mode == "rpc":
        if request.file_input:
            request.stderr.write(
                "Error: @file arguments are not supported in RPC mode.\n"
            )
            return 2
        if runners.rpc is not runners.default_rpc:
            return await _invoke(
                runners.rpc,
                runtime=request.runtime,
                stdin=request.stdin,
                stdout=request.stdout,
                stderr=request.stderr,
                render_tool_events=request.launch_plan.render_tool_events,
            )
        return await _invoke(
            runners.mode,
            config=ModeConfig(
                mode="rpc",
                render_tool_events=request.launch_plan.render_tool_events,
            ),
            runtime=request.runtime,
            session=request.session,
            user_input=None,
            stdin=request.stdin,
            stdout=request.stdout,
            stderr=request.stderr,
        )
    if mode == "channel":
        return await _invoke(
            runners.channel,
            runtime=request.runtime,
            stdin=request.stdin,
            stdout=request.stdout,
            stderr=request.stderr,
        )
    if request.workflow_path is not None:
        return await _invoke(
            runners.workflow,
            runtime=request.runtime,
            session=request.session,
            workflow_path=request.workflow_path,
            cwd=request.project_root,
            stdout=request.stdout,
            stderr=request.stderr,
            verbose=request.verbose,
            output_mode=request.workflow_output_mode,
        )

    prepared = await _resolve(request.prepare_host_input())
    if isinstance(prepared, CliPhaseResult):
        if prepared.exit_code is not None:
            return prepared.exit_code
        host_input = prepared.value
    else:
        host_input = prepared
    if host_input is None:
        raise RuntimeError("Agent CLI host preparation returned no input")

    if request.launch_plan.prompt_requested:
        if (
            runners.prompt is runners.default_prompt
            and request.work_event_log is not None
            and len(host_input.plan_turns) > 1
        ):
            return await _invoke(
                runners.prompt_plan,
                runtime=request.runtime,
                session=request.session,
                turns=host_input.plan_turns,
                stdout=request.stdout,
                stderr=request.stderr,
                verbose=request.verbose,
                work_event_log=request.work_event_log,
                work_runtime=request.work_runtime,
            )
        return await run_keyword_cli_turns(
            host_input.turns,
            run_turns=runners.run_turns,
            runner=runners.prompt,
            input_argument="prompt",
            fixed_arguments={
                "runtime": request.runtime,
                "session": request.session,
                "stdout": request.stdout,
                "stderr": request.stderr,
                "verbose": request.verbose,
                "work_event_log": request.work_event_log,
                "work_runtime": request.work_runtime,
            },
            images=host_input.images,
            follow_up_messages=host_input.follow_up_messages,
            dispose_candidates=(request.runtime, request.session),
        )

    output_mode = "text" if mode == "print" else mode
    if runners.plain is not runners.default_plain:
        return await run_keyword_cli_turns(
            host_input.turns,
            run_turns=runners.run_turns,
            runner=runners.plain,
            input_argument="user_input",
            fixed_arguments={
                "runtime": request.runtime,
                "session": request.session,
                "stdout": request.stdout,
                "stderr": request.stderr,
                "output_mode": output_mode,
                "render_tool_events": request.launch_plan.render_tool_events,
                "work_event_log": request.work_event_log,
            },
            images=host_input.images,
            follow_up_messages=host_input.follow_up_messages,
            dispose_candidates=(request.runtime, request.session),
        )
    if (
        runners.mode is runners.default_mode
        and request.work_event_log is not None
        and len(host_input.plan_turns) > 1
    ):
        return await _invoke(
            runners.plain_plan,
            runtime=request.runtime,
            session=request.session,
            turns=host_input.plan_turns,
            stdout=request.stdout,
            stderr=request.stderr,
            output_mode=output_mode,
            render_tool_events=request.launch_plan.render_tool_events,
            work_event_log=request.work_event_log,
            work_port=request.plain_work_port,
        )
    return await run_keyword_cli_turns(
        host_input.turns,
        run_turns=runners.run_turns,
        runner=runners.mode,
        input_argument="user_input",
        fixed_arguments={
            "config": ModeConfig(
                mode=cast(ModeName, mode),
                render_tool_events=request.launch_plan.render_tool_events,
            ),
            "runtime": request.runtime,
            "session": request.session,
            "stdin": request.stdin,
            "stdout": request.stdout,
            "stderr": request.stderr,
            "work_event_log": request.work_event_log,
            "work_port": request.plain_work_port,
        },
        images=host_input.images,
        follow_up_messages=host_input.follow_up_messages,
        dispose_candidates=(request.runtime, request.session),
    )


async def _invoke(callback: Callable[..., object], **kwargs: object) -> int:
    result = callback(**kwargs)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, int):
        raise TypeError("Agent CLI host runner must return an integer exit code")
    return result


async def _invoke_with_optional(
    callback: Callable[..., object],
    *,
    required: dict[str, object],
    optional: dict[str, object],
) -> int:
    kwargs = dict(required)
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        signature = None
    accepts_kwargs = bool(
        signature is not None
        and any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
    )
    for name, value in optional.items():
        if value is None:
            continue
        if accepts_kwargs or (signature is not None and name in signature.parameters):
            kwargs[name] = value
    return await _invoke(callback, **kwargs)


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


__all__ = [
    "AgentCliHostRequest",
    "AgentCliHostRunners",
    "AgentCliSessionHostBinding",
    "PreparedAgentCliHostInput",
    "PrepareHostInput",
    "prepare_agent_cli_host_input",
    "run_agent_cli_host",
    "run_agent_cli_session_host",
]
