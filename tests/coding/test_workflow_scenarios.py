from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

SCENARIO_PATHS = sorted(Path("scenarios/coding/workflows").glob("*.workflow.yaml"))
STRESS_SCENARIO_PATH = Path(
    "scenarios/coding/workflows/repeated-control-mix.workflow.yaml"
)


@pytest.mark.parametrize("path", SCENARIO_PATHS, ids=lambda path: path.name)
def test_workflow_scenario_matrix(path: Path, tmp_path) -> None:
    from loushang.harness.scenario import (
        format_workflow_report,
        load_workflow,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    workflow = load_workflow(path)

    assert workflow.backend == "fake"
    result = asyncio.run(
        run_workflow(workflow, adapter=FakeWorkflowAdapter(), cwd=tmp_path)
    )
    assert result.ok, format_workflow_report(result)


def test_repeated_control_mix_scenario_exists_and_passes(tmp_path) -> None:
    from loushang.harness.scenario import (
        format_workflow_report,
        load_workflow,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    workflow = load_workflow(STRESS_SCENARIO_PATH)

    assert workflow.backend == "fake"
    result = asyncio.run(
        run_workflow(workflow, adapter=FakeWorkflowAdapter(), cwd=tmp_path)
    )
    assert result.ok, format_workflow_report(result)
