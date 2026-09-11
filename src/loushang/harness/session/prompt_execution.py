"""Explicit prompt disposition using the same command/preflight/Agent pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from loushang.harness.capabilities.prompt_preflight import PromptPreflightResult
from loushang.harness.commands import CommandDispatchOutcome
from loushang.harness.session.prompt_controller import PromptController
from loushang.harness.transcript import CompactionResult


@dataclass(frozen=True, slots=True)
class PromptExecutionResult:
    """Input handling evidence; the Product separately evaluates Agent outcomes."""

    accepted: bool
    model_started: bool
    failure_code: str | None = None


async def execute_prompt(
    controller: PromptController,
    dispatch_command: Callable[[str, str], Awaitable[CommandDispatchOutcome[object]]],
    text: str,
    *,
    source: str,
    check_cancelled: Callable[[], None] | None = None,
) -> PromptExecutionResult:
    accepted = False
    model_started = False
    failure_code: str | None = None

    def checkpoint() -> None:
        if check_cancelled is not None:
            check_cancelled()

    def on_preflight(value: bool) -> None:
        nonlocal accepted
        accepted = value

    async def command(name: str, args: str) -> object | None:
        nonlocal failure_code
        checkpoint()
        outcome = await dispatch_command(name, args)
        failure_code = outcome.failure_code
        if not outcome.handled:
            failure_code = "command_unavailable"
        return outcome.result

    async def run(messages: list[object]) -> None:
        nonlocal model_started
        checkpoint()
        model_started = True
        await (controller.run_prompt or controller.agent.prompt)(messages)

    async def preflight(text: str, **kwargs: object) -> PromptPreflightResult:
        nonlocal failure_code
        checkpoint()
        result = await controller.preflight_user_input_async(text, **kwargs)
        checkpoint()
        if not isinstance(result, PromptPreflightResult):
            raise TypeError("execution requires a typed prompt preflight result")
        if result.consumed and result.diagnostics:
            failure_code = "input_preflight_failed"
        return result

    async def compact() -> CompactionResult | None:
        checkpoint()
        assert controller.compact_before_prompt_async is not None
        result = await controller.compact_before_prompt_async()
        checkpoint()
        return result

    # One invocation-local copy: no mutation of the Session's live callbacks and
    # no duplicate implementation of input transformations or prompt ordering.
    invocation = replace(
        controller,
        execute_command_async=command,
        run_prompt=run,
        preflight_user_input_async=preflight,
        compact_before_prompt_async=(
            compact if controller.compact_before_prompt_async is not None else None
        ),
    )
    checkpoint()
    await invocation.prompt(text, source=source, preflight_result=on_preflight)
    return PromptExecutionResult(accepted, model_started, failure_code)
