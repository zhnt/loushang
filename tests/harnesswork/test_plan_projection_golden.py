from __future__ import annotations

import json
from pathlib import Path

_FIXTURES = Path(__file__).with_name("fixtures")


def test_legacy_coding_log_replays_without_coding_semantics() -> None:
    from loushang.harnesswork import JsonlEventLogBackend, project_work_plan_runs

    event_log = JsonlEventLogBackend(_FIXTURES / "legacy_coding_plan.jsonl")

    actual = [
        {
            "plan_id": plan.plan_id,
            "method_id": plan.method_id,
            "status": plan.status,
            "operation_ids": list(plan.metadata["operation_ids"]),
            "steps": [
                {
                    "run_id": step.run_id,
                    "step_id": step.step_id,
                    "status": step.status,
                    "step_index": step.metadata["step_index"],
                    "title": step.title,
                }
                for step in plan.steps
            ],
        }
        for plan in project_work_plan_runs(event_log.query())
    ]
    expected = json.loads(
        (_FIXTURES / "legacy_coding_plan_projection.json").read_text(
            encoding="utf-8"
        )
    )

    assert actual == expected
