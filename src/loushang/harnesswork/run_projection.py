from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from loushang.harnesswork.event_log import EventLogEntry
from loushang.harnesswork.types import WorkRun, WorkRunStatus

_TERMINAL_KINDS: dict[str, WorkRunStatus] = {
    "WorkRunCompleted": "completed",
    "WorkRunFailed": "failed",
    "WorkRunCancelled": "cancelled",
}


class WorkRunReplayError(ValueError):
    """The persisted log cannot represent a valid Work run."""


@dataclass
class _ReplayState:
    run: WorkRun
    last_sequence: int
    terminal: bool = False


def project_work_runs(
    entries: Iterable[EventLogEntry],
    *,
    mark_incomplete_orphaned: bool = False,
) -> tuple[WorkRun, ...]:
    """Rebuild WorkRun read models while validating lifecycle invariants."""

    states: dict[str, _ReplayState] = {}
    order: list[str] = []
    operation_ids: dict[str, str] = {}

    for entry in entries:
        state = states.get(entry.run_id)
        if state is None:
            if entry.entry_type != "operation":
                raise WorkRunReplayError(
                    f"run {entry.run_id} starts without an operation entry"
                )
            if entry.sequence != 0:
                raise WorkRunReplayError(
                    f"run {entry.run_id} operation sequence must be 0"
                )
            prior_run_id = operation_ids.get(entry.operation_id)
            if prior_run_id is not None:
                raise WorkRunReplayError(
                    f"operation {entry.operation_id} belongs to multiple runs"
                )
            operation_ids[entry.operation_id] = entry.run_id
            run = _run_from_operation(entry)
            states[entry.run_id] = _ReplayState(run=run, last_sequence=0)
            order.append(entry.run_id)
            continue

        if entry.entry_type == "operation":
            raise WorkRunReplayError(f"run {entry.run_id} has duplicate operation entry")
        if entry.operation_id != state.run.operation_id:
            raise WorkRunReplayError(f"run {entry.run_id} changes operation_id")
        if entry.session_id != state.run.session_id:
            raise WorkRunReplayError(f"run {entry.run_id} changes session_id")
        if entry.sequence <= state.last_sequence:
            raise WorkRunReplayError(
                f"run {entry.run_id} sequence is not strictly increasing"
            )
        if state.terminal:
            raise WorkRunReplayError(f"run {entry.run_id} has an event after terminal")
        state.last_sequence = entry.sequence
        _apply_event(state, entry)

    runs = tuple(states[run_id].run for run_id in order)
    if not mark_incomplete_orphaned:
        return runs
    return tuple(
        replace(run, status="orphaned")
        if run.status in {"accepted", "running", "cancelling"}
        else run
        for run in runs
    )


def _run_from_operation(entry: EventLogEntry) -> WorkRun:
    domain = entry.payload.get("domain")
    if not isinstance(domain, str) or not domain:
        raise WorkRunReplayError(f"run {entry.run_id} operation has no domain")
    payload = entry.payload.get("payload")
    nested = payload if isinstance(payload, Mapping) else {}
    return WorkRun(
        run_id=entry.run_id,
        operation_id=entry.operation_id,
        session_id=entry.session_id,
        domain=domain,
        status="accepted",
        method_id=_optional_string(nested.get("method_id")),
        plan_id=_optional_string(nested.get("plan_id")),
        current_step_id=_optional_string(nested.get("step_id")),
    )


def _apply_event(state: _ReplayState, entry: EventLogEntry) -> None:
    kind = entry.payload.get("kind")
    if not isinstance(kind, str) or not kind:
        raise WorkRunReplayError(f"run {entry.run_id} event has no kind")
    payload = entry.payload.get("payload")
    nested = payload if isinstance(payload, Mapping) else {}
    run = state.run
    method_id = _optional_string(nested.get("method_id")) or run.method_id
    plan_id = _optional_string(nested.get("plan_id")) or run.plan_id
    step_id = _optional_string(nested.get("step_id")) or run.current_step_id

    status: WorkRunStatus = run.status
    if kind == "WorkRunStarted":
        _require_status(entry, status, {"accepted"})
        status = "running"
    elif kind == "WorkRunCancelling":
        _require_status(entry, status, {"running"})
        status = "cancelling"
    elif kind in _TERMINAL_KINDS:
        allowed = (
            {"cancelling"}
            if kind == "WorkRunCancelled"
            else {"running", "cancelling"}
        )
        _require_status(entry, status, allowed)
        status = _TERMINAL_KINDS[kind]
        state.terminal = True
    elif status == "accepted":
        raise WorkRunReplayError(
            f"run {entry.run_id} emits {kind} before WorkRunStarted"
        )

    state.run = WorkRun(
        run_id=run.run_id,
        operation_id=run.operation_id,
        session_id=run.session_id,
        domain=run.domain,
        status=status,
        method_id=method_id,
        plan_id=plan_id,
        current_step_id=step_id,
    )


def _require_status(
    entry: EventLogEntry, status: WorkRunStatus, allowed: set[str]
) -> None:
    if status not in allowed:
        expected = ", ".join(sorted(allowed))
        raise WorkRunReplayError(
            f"run {entry.run_id} cannot apply {entry.payload.get('kind')} "
            f"from {status}; expected {expected}"
        )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["WorkRunReplayError", "project_work_runs"]
