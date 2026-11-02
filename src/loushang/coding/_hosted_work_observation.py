"""Shared safe projection of an original Work; no second index or state owner."""
from loushang.appserver.method_work import (
    MethodWorkObservationV1,
    WorkCancellationObservationV1,
    WorkRecordingObservationV1,
    WorkRunObservationV1,
    WorkStepObservationV1,
)
from loushang.harnesswork.plan_projection import project_work_plan_runs


def observe_work_run(runtime, run, *, max_steps=64) -> MethodWorkObservationV1:
    errors: list[str] = []
    steps: tuple[WorkStepObservationV1, ...] = ()
    try:
        plans = project_work_plan_runs(runtime.query(run_id=run.run_id))
        if len(plans) == 1:
            steps = tuple(WorkStepObservationV1(step.step_id, step.status) for step in plans[0].steps)
        if len(steps) > max_steps:
            raise ValueError("unexpected step count")
    except Exception:
        steps = ()
        errors.append("work_plan_unavailable")
    work = WorkRunObservationV1(
        run.operation_id, run.run_id, run.session_id, run.method_id, run.plan_id,
        run.status, run.current_step_id, steps,
    )
    recording = None
    try:
        record = runtime.get_recording(run.run_id)
        contract = record.contract
        if contract is None:
            raise ValueError("missing recording contract")
        recording = WorkRecordingObservationV1(
            contract.version, contract.capture, contract.retention, contract.require_persistence,
            record.run.status, record.basis, record.observed_sequence, record.source_event_id,
        )
    except Exception:
        errors.append("work_recording_unavailable")
    cancellation = None
    try:
        cancel = runtime.get_cancellation(run.run_id)
        cancellation = WorkCancellationObservationV1(
            cancel.status, cancel.reason_code, cancel.reported_status, cancel.basis,
            cancel.observed_sequence, cancel.source_event_id,
        )
    except Exception:
        errors.append("work_cancellation_unavailable")
    return MethodWorkObservationV1("present", work, recording, cancellation, tuple(errors))

