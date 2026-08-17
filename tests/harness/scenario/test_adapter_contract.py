from __future__ import annotations

import asyncio

from loushang.harness.scenario import (
    PromptStep,
    StepExpectation,
    Workflow,
    run_workflow,
)


def test_scenario_runner_accepts_product_owned_minimal_adapter(tmp_path) -> None:
    """The core contract requires only Product-defined prompt submission."""

    class OemAdapter:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def run_prompt(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return f"OEM completed: {prompt}"

    adapter = OemAdapter()
    workflow = Workflow(
        name="oem contract",
        steps=(
            PromptStep(
                prompt="prepare brief",
                expect=StepExpectation(assistant_contains=("OEM completed",)),
            ),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is True
    assert adapter.prompts == ["prepare brief"]
    assert result.step_results[0].assistant_text == "OEM completed: prepare brief"
