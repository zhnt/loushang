"""Offline compatibility probe against the fixed pre-recording Git baseline.

Run with PYTHONPATH=src and the project Python. This is a manual probe, not a
new CI route. Baseline modules are loaded in memory; all journals are temporary.
"""

import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from loushang.harnesswork import (
    JsonlEventLogBackend,
    WorkEventFact,
    WorkOperation,
    WorkRunSpec,
    WorkRuntime,
    WorkStepSpec,
    project_work_cancellations,
    project_work_plan_runs,
    project_work_runs,
)

BASELINE = "5eadeb91ccee4e69618d99cf531f94739c76a453"
ROOT = Path(__file__).resolve().parents[2]


def baseline(name):
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:src/loushang/harnesswork/{name}.py"],
        cwd=ROOT,
        text=True,
    )
    spec = importlib.util.spec_from_loader("baseline_" + name, loader=None)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(source, f"{BASELINE}/{name}.py", "exec"), module.__dict__)
    return module


class Executor:
    async def execute(self, operation, context):
        context.publish(WorkEventFact("CustomResult", {"step": context.step_id}))


async def probe(path):
    for name, version in [("legacy", None), ("v1", 1), ("rollback", None)]:
        runtime = WorkRuntime(
            event_log=JsonlEventLogBackend(path),
            executor=Executor(),
            recording_version=version,
        )
        operation = WorkOperation(name, "Execute", None, "probe", {})
        run = await runtime.accept(
            operation,
            spec=WorkRunSpec(
                run_id=name,
                method_id="m",
                plan_id="p",
                steps=(WorkStepSpec("inspect"), WorkStepSpec("verify")),
            ),
        )
        await runtime.wait(run.run_id)
        if version:
            record = runtime.get_recording(run.run_id)
            assert record.run == runtime.get_run(run.run_id)
            assert record.contract.capture == "published_facts"
    old_entries = baseline("event_log").JsonlEventLogBackend(path).query()
    new_entries = JsonlEventLogBackend(path).query()
    assert [asdict(entry) for entry in old_entries] == [
        asdict(entry) for entry in new_entries
    ]
    for name, function in [
        ("run_projection", project_work_runs),
        ("plan_projection", project_work_plan_runs),
        ("cancellation_projection", project_work_cancellations),
    ]:
        old = getattr(baseline(name), function.__name__)(old_entries)
        assert old == function(new_entries), name
    print(
        "baseline reader: 3 mixed runs, 2 steps each; run/plan/cancellation projections equal; no executor replay"
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(
        prefix="work-recording-compatibility-"
    ) as directory:
        asyncio.run(probe(Path(directory) / "mixed.jsonl"))
