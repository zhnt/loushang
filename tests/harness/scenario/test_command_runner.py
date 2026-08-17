from __future__ import annotations

import asyncio

from loushang.harness.scenario import (
    CommandExpectation,
    CommandRunResult,
    PromptStep,
    StepExpectation,
    Workflow,
    run_workflow,
)
from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter


def test_command_expectation_requires_product_supplied_runner(tmp_path) -> None:
    workflow = Workflow(
        name="command",
        steps=(
            PromptStep(
                prompt="check",
                expect=StepExpectation(command=CommandExpectation(run="check")),
            ),
        ),
    )

    result = asyncio.run(
        run_workflow(workflow, adapter=FakeWorkflowAdapter(), cwd=tmp_path)
    )

    assert result.ok is False
    assert result.step_results[0].checks[-1].detail == (
        "no command runner was supplied by the Product"
    )


def test_command_expectation_uses_injected_runner(tmp_path) -> None:
    calls = []
    workflow = Workflow(
        name="command",
        steps=(
            PromptStep(
                prompt="check",
                expect=StepExpectation(
                    command=CommandExpectation(
                        run="check",
                        stdout_contains=("ready",),
                    )
                ),
            ),
        ),
    )

    def run_command(command, *, cwd, timeout_s):
        calls.append((command, cwd, timeout_s))
        return CommandRunResult(exit_code=0, stdout="ready", stderr="")

    result = asyncio.run(
        run_workflow(
            workflow,
            adapter=FakeWorkflowAdapter(),
            cwd=tmp_path,
            command_runner=run_command,
        )
    )

    assert result.ok is True
    assert calls == [("check", tmp_path.resolve(), None)]
