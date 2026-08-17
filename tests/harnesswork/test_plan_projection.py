from __future__ import annotations

from datetime import UTC, datetime


def _entry(
    entry_id: str,
    *,
    kind: str,
    run_id: str,
    sequence: int,
    operation_id: str | None = None,
    entry_type: str = "event",
    method_id: str | None = "method:task:review",
    plan_id: str | None = "plan:method:task:review",
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    error: str | None = None,
    deviation: dict[str, object] | None = None,
    planned_constraint: dict[str, object] | None = None,
    audit_policy: dict[str, object] | None = None,
    plan_facts: dict[str, object] | None = None,
    step_facts: dict[str, object] | None = None,
) -> object:
    from loushang.harnesswork import EventLogEntry

    payload: dict[str, object] = {"kind": kind}
    nested_payload: dict[str, object] = {}
    if method_id is not None:
        nested_payload["method_id"] = method_id
    if plan_id is not None:
        nested_payload["plan_id"] = plan_id
    if step_id is not None:
        nested_payload["step_id"] = step_id
    if step_index is not None:
        nested_payload["step_index"] = step_index
    if step_title is not None:
        nested_payload["step_title"] = step_title
    if error is not None:
        nested_payload["error"] = error
    if deviation is not None:
        nested_payload["deviation"] = deviation
    if planned_constraint is not None:
        nested_payload["planned_constraint"] = planned_constraint
    if audit_policy is not None:
        nested_payload["audit_policy"] = audit_policy
    if plan_facts is not None:
        nested_payload["plan_facts"] = plan_facts
    if step_facts is not None:
        nested_payload["step_facts"] = step_facts
    if nested_payload:
        payload["payload"] = nested_payload

    return EventLogEntry(
        entry_id=entry_id,
        entry_type=entry_type,
        operation_id=operation_id or f"op-{run_id}",
        event_id=None if entry_type == "operation" else f"event-{entry_id}",
        run_id=run_id,
        session_id="session-1",
        sequence=sequence,
        payload=payload,
        created_at=datetime(2026, 6, 1, 10, 30, sequence, tzinfo=UTC),
    )


def _step_entries(
    *,
    run_id: str,
    step_id: str,
    step_index: int,
    step_title: str,
    first: bool = False,
    last: bool = False,
    failed: bool = False,
) -> list[object]:
    entries = [
        _entry(
            f"{run_id}-operation",
            kind="ExecuteTestOperation",
            run_id=run_id,
            sequence=0,
            entry_type="operation",
            step_id=step_id,
            step_index=step_index,
            step_title=step_title,
        ),
        _entry(f"{run_id}-run-started", kind="WorkRunStarted", run_id=run_id, sequence=1, step_id=step_id),
    ]
    if first:
        entries.append(
            _entry(
                f"{run_id}-plan-started",
                kind="WorkPlanStarted",
                run_id=run_id,
                sequence=2,
                step_id=step_id,
                step_index=step_index,
                step_title=step_title,
            )
        )
    entries.append(
        _entry(
            f"{run_id}-step-started",
            kind="WorkStepStarted",
            run_id=run_id,
            sequence=3,
            step_id=step_id,
            step_index=step_index,
            step_title=step_title,
        )
    )
    if failed:
        entries.extend(
            [
                _entry(
                    f"{run_id}-step-failed",
                    kind="WorkStepFailed",
                    run_id=run_id,
                    sequence=4,
                    step_id=step_id,
                    step_index=step_index,
                    step_title=step_title,
                    error="step failed",
                ),
                _entry(
                    f"{run_id}-plan-failed",
                    kind="WorkPlanFailed",
                    run_id=run_id,
                    sequence=5,
                    step_id=step_id,
                    step_index=step_index,
                    step_title=step_title,
                    error="step failed",
                ),
            ]
        )
    else:
        entries.append(
            _entry(
                f"{run_id}-step-completed",
                kind="WorkStepCompleted",
                run_id=run_id,
                sequence=4,
                step_id=step_id,
                step_index=step_index,
                step_title=step_title,
            )
        )
        if last:
            entries.append(
                _entry(
                    f"{run_id}-plan-completed",
                    kind="WorkPlanCompleted",
                    run_id=run_id,
                    sequence=5,
                    step_id=step_id,
                    step_index=step_index,
                    step_title=step_title,
                )
            )
    entries.append(_entry(f"{run_id}-run-completed", kind="WorkRunCompleted", run_id=run_id, sequence=6, step_id=step_id))
    return entries


def test_project_work_plan_runs_replays_completed_steps_across_turn_runs() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plans = project_work_plan_runs(
        [
            *_step_entries(
                run_id="run-inspect",
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
                first=True,
            ),
            *_step_entries(
                run_id="run-verify",
                step_id="verify",
                step_index=1,
                step_title="Run focused checks",
                last=True,
            ),
        ]
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.plan_id == "plan:method:task:review"
    assert plan.method_id == "method:task:review"
    assert plan.status == "completed"
    assert plan.step_count == 2
    assert plan.completed_step_count == 2
    assert plan.failed_step_count == 0
    assert plan.current_step_id == "verify"
    assert plan.metadata["operation_ids"] == ("op-run-inspect", "op-run-verify")

    assert [(step.step_id, step.status, step.run_id, step.title) for step in plan.steps] == [
        ("inspect", "completed", "run-inspect", "Inspect current changes"),
        ("verify", "completed", "run-verify", "Run focused checks"),
    ]
    assert plan.steps[0].metadata == {
        "step_index": 0,
        "operation_id": "op-run-inspect",
        "started_sequence": 3,
        "completed_sequence": 4,
    }


def test_project_work_plan_runs_replays_failed_step_and_plan_error() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plans = project_work_plan_runs(
        _step_entries(
            run_id="run-verify",
            step_id="verify",
            step_index=1,
            step_title="Run focused checks",
            first=True,
            failed=True,
        )
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.status == "failed"
    assert plan.completed_step_count == 0
    assert plan.failed_step_count == 1
    assert plan.current_step_id == "verify"
    assert plan.metadata["error"] == "step failed"
    assert plan.steps[0].status == "failed"
    assert plan.steps[0].metadata["error"] == "step failed"
    assert plan.steps[0].metadata["failed_sequence"] == 4


def test_project_work_plan_runs_replays_cancelled_step_and_plan() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plans = project_work_plan_runs(
        [
            _entry(
                "run-verify-plan-started",
                kind="WorkPlanStarted",
                run_id="run-verify",
                sequence=1,
                step_id="verify",
                step_index=1,
            ),
            _entry(
                "run-verify-step-started",
                kind="WorkStepStarted",
                run_id="run-verify",
                sequence=2,
                step_id="verify",
                step_index=1,
            ),
            _entry(
                "run-verify-step-cancelled",
                kind="WorkStepCancelled",
                run_id="run-verify",
                sequence=3,
                step_id="verify",
                step_index=1,
            ),
            _entry(
                "run-verify-plan-cancelled",
                kind="WorkPlanCancelled",
                run_id="run-verify",
                sequence=4,
                step_id="verify",
                step_index=1,
            ),
            _entry(
                "run-verify-run-cancelled",
                kind="WorkRunCancelled",
                run_id="run-verify",
                sequence=5,
                step_id="verify",
                step_index=1,
            ),
        ]
    )

    assert len(plans) == 1
    assert plans[0].status == "cancelled"
    assert plans[0].steps[0].status == "cancelled"
    assert plans[0].steps[0].metadata["cancelled_sequence"] == 3


def test_project_work_plan_runs_replays_step_deviation_metadata() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plans = project_work_plan_runs(
        [
            _entry(
                "run-inspect-step-started",
                kind="WorkStepStarted",
                run_id="run-inspect",
                sequence=1,
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
            ),
            _entry(
                "run-inspect-step-completed",
                kind="WorkStepCompleted",
                run_id="run-inspect",
                sequence=2,
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
                deviation={
                    "deviation_type": "adapted",
                    "reason": "Only documentation files changed.",
                    "policy_level": "reasoned",
                    "evidence_refs": ["git-diff"],
                    "risk": "low",
                    "outcome": "accepted",
                },
            ),
        ]
    )

    deviation = plans[0].steps[0].deviation
    assert deviation is not None
    assert deviation.step_id == "inspect"
    assert deviation.deviation_type == "adapted"
    assert deviation.reason == "Only documentation files changed."
    assert deviation.policy_level == "reasoned"
    assert deviation.evidence_refs == ("git-diff",)
    assert deviation.risk == "low"
    assert deviation.outcome == "accepted"
    assert plans[0].steps[0].metadata["deviation"] == {
        "step_id": "inspect",
        "deviation_type": "adapted",
        "reason": "Only documentation files changed.",
        "policy_level": "reasoned",
        "evidence_refs": ("git-diff",),
        "approval_ref": None,
        "risk": "low",
        "outcome": "accepted",
        "metadata": {},
    }


def test_project_work_plan_runs_replays_planned_step_policy_metadata() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plans = project_work_plan_runs(
        [
            _entry(
                "run-inspect-step-started",
                kind="WorkStepStarted",
                run_id="run-inspect",
                sequence=1,
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
                planned_constraint={
                    "level": "reasoned",
                    "requires_reason": True,
                },
                audit_policy={"record": ["status", "reason"]},
            ),
            _entry(
                "run-inspect-step-completed",
                kind="WorkStepCompleted",
                run_id="run-inspect",
                sequence=2,
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
            ),
        ]
    )

    metadata = plans[0].steps[0].metadata
    assert metadata["planned_constraint"] == {
        "level": "reasoned",
        "requires_reason": True,
    }
    assert metadata["audit_policy"] == {"record": ["status", "reason"]}


def test_project_work_plan_runs_replays_plan_and_step_facts() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plan_facts = {
        "plan_id": "plan:method:task:review",
        "method_id": "method:task:review",
        "mode": "fixed",
        "phase": "VERIFY",
    }
    step_facts = {
        "step_id": "inspect",
        "title": "Inspect current changes",
        "executor": "current_agent",
        "step_index": 0,
        "step_count": 2,
    }

    plans = project_work_plan_runs(
        [
            _entry(
                "run-inspect-plan-started",
                kind="WorkPlanStarted",
                run_id="run-inspect",
                sequence=1,
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
                plan_facts=plan_facts,
                step_facts=step_facts,
            ),
            _entry(
                "run-inspect-step-completed",
                kind="WorkStepCompleted",
                run_id="run-inspect",
                sequence=2,
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
            ),
        ]
    )

    assert plans[0].metadata["plan_facts"] == plan_facts
    assert plans[0].steps[0].metadata["step_facts"] == step_facts


def test_project_work_plan_runs_ignores_entries_without_plan_id() -> None:
    from loushang.harnesswork import project_work_plan_runs

    plans = project_work_plan_runs(
        [
            _entry(
                "run-1-operation",
                kind="ExecuteTestOperation",
                run_id="run-1",
                sequence=0,
                entry_type="operation",
                method_id=None,
                plan_id=None,
            ),
            _entry("run-1-started", kind="WorkRunStarted", run_id="run-1", sequence=1, method_id=None, plan_id=None),
        ]
    )

    assert plans == ()
