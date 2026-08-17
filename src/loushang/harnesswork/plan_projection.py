from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field

from loushang.harnesswork.event_log import EventLogEntry
from loushang.harnesswork.types import (
    WorkPlanRun,
    WorkRunStatus,
    WorkStepDeviation,
    WorkStepRun,
    WorkStepStatus,
)


def project_work_plan_runs(entries: Iterable[EventLogEntry]) -> tuple[WorkPlanRun, ...]:
    plan_states: list[_PlanState] = []
    active_by_plan_id: dict[str, _PlanState] = {}

    for entry in entries:
        plan_id = _entry_string_payload_value(entry, "plan_id")
        if not plan_id:
            continue

        kind = _entry_kind(entry)
        plan_state = active_by_plan_id.get(plan_id)
        if plan_state is None or _starts_new_plan_attempt(entry, kind, plan_state):
            plan_state = _PlanState(
                plan_id=plan_id,
                method_id=_entry_string_payload_value(entry, "method_id") or None,
                status="accepted",
            )
            active_by_plan_id[plan_id] = plan_state
            plan_states.append(plan_state)

        plan_state.update_from_entry(entry, kind=kind)

    return tuple(plan_state.to_plan_run() for plan_state in plan_states)


def _starts_new_plan_attempt(
    entry: EventLogEntry,
    kind: str,
    plan_state: _PlanState,
) -> bool:
    return plan_state.status in {"completed", "failed", "cancelled"} and (
        entry.entry_type == "operation" or kind == "WorkPlanStarted"
    )


@dataclass
class _PlanState:
    plan_id: str
    status: WorkRunStatus
    method_id: str | None = None
    current_step_id: str | None = None
    error: str | None = None
    plan_facts: dict[str, object] | None = None
    operation_ids: list[str] = field(default_factory=list)
    steps: dict[str, _StepState] = field(default_factory=dict)
    step_order: list[str] = field(default_factory=list)

    def update_from_entry(self, entry: EventLogEntry, *, kind: str) -> None:
        method_id = _entry_string_payload_value(entry, "method_id")
        if method_id:
            self.method_id = method_id
        if entry.operation_id and entry.operation_id not in self.operation_ids:
            self.operation_ids.append(entry.operation_id)
        plan_facts = _entry_mapping_payload_value(entry, "plan_facts")
        if plan_facts is not None:
            self.plan_facts = plan_facts

        if kind == "WorkPlanStarted":
            self.status = "running"
        elif kind == "WorkPlanCompleted":
            self.status = "completed"
        elif kind == "WorkPlanFailed":
            self.status = "failed"
            self.error = _entry_string_payload_value(entry, "error") or self.error
        elif kind == "WorkPlanCancelled":
            self.status = "cancelled"
        elif self.status == "accepted" and entry.entry_type != "operation":
            self.status = "running"

        step_id = _entry_string_payload_value(entry, "step_id")
        if not step_id:
            return
        self.current_step_id = step_id
        step_state = self._step_state(step_id)
        step_state.update_from_entry(entry, kind=kind, method_id=self.method_id, plan_id=self.plan_id)

    def _step_state(self, step_id: str) -> _StepState:
        step_state = self.steps.get(step_id)
        if step_state is not None:
            return step_state
        step_state = _StepState(step_id=step_id)
        self.steps[step_id] = step_state
        self.step_order.append(step_id)
        return step_state

    def to_plan_run(self) -> WorkPlanRun:
        steps = tuple(self.steps[step_id].to_step_run() for step_id in self._ordered_step_ids())
        metadata: dict[str, object] = {"operation_ids": tuple(self.operation_ids)}
        if self.error is not None:
            metadata["error"] = self.error
        if self.plan_facts is not None:
            metadata["plan_facts"] = self.plan_facts
        return WorkPlanRun(
            plan_id=self.plan_id,
            status=self.status,
            method_id=self.method_id,
            current_step_id=self.current_step_id,
            steps=steps,
            step_count=len(steps),
            completed_step_count=sum(1 for step in steps if step.status == "completed"),
            failed_step_count=sum(1 for step in steps if step.status == "failed"),
            metadata=metadata,
        )

    def _ordered_step_ids(self) -> tuple[str, ...]:
        order_index = {step_id: index for index, step_id in enumerate(self.step_order)}
        return tuple(
            sorted(
                self.step_order,
                key=lambda step_id: (
                    self.steps[step_id].step_index is None,
                    self.steps[step_id].step_index if self.steps[step_id].step_index is not None else order_index[step_id],
                    order_index[step_id],
                ),
            )
        )


@dataclass
class _StepState:
    step_id: str
    status: WorkStepStatus = "pending"
    run_id: str | None = None
    plan_id: str | None = None
    method_id: str | None = None
    operation_id: str | None = None
    title: str | None = None
    step_index: int | None = None
    first_sequence: int | None = None
    started_sequence: int | None = None
    completed_sequence: int | None = None
    failed_sequence: int | None = None
    cancelled_sequence: int | None = None
    error: str | None = None
    deviation: WorkStepDeviation | None = None
    planned_constraint: dict[str, object] | None = None
    audit_policy: dict[str, object] | None = None
    step_facts: dict[str, object] | None = None

    def update_from_entry(
        self,
        entry: EventLogEntry,
        *,
        kind: str,
        method_id: str | None,
        plan_id: str,
    ) -> None:
        self.run_id = self.run_id or entry.run_id
        self.operation_id = self.operation_id or entry.operation_id
        self.method_id = method_id or self.method_id
        self.plan_id = plan_id
        self.first_sequence = self.first_sequence if self.first_sequence is not None else entry.sequence

        step_title = _entry_string_payload_value(entry, "step_title")
        if step_title:
            self.title = step_title
        step_index = _entry_step_index(entry)
        if step_index is not None:
            self.step_index = step_index
        deviation = _entry_step_deviation(entry, step_id=self.step_id)
        if deviation is not None:
            self.deviation = deviation
        planned_constraint = _entry_mapping_payload_value(entry, "planned_constraint")
        if planned_constraint is not None:
            self.planned_constraint = planned_constraint
        audit_policy = _entry_mapping_payload_value(entry, "audit_policy")
        if audit_policy is not None:
            self.audit_policy = audit_policy
        step_facts = _entry_mapping_payload_value(entry, "step_facts")
        if step_facts is not None:
            self.step_facts = step_facts

        if kind == "WorkStepStarted":
            self.status = "running"
            self.started_sequence = entry.sequence
        elif kind == "WorkStepCompleted":
            self.status = "completed"
            self.completed_sequence = entry.sequence
        elif kind == "WorkStepFailed":
            self.status = "failed"
            self.failed_sequence = entry.sequence
            self.error = _entry_string_payload_value(entry, "error") or self.error
        elif kind == "WorkStepCancelled":
            self.status = "cancelled"
            self.cancelled_sequence = entry.sequence

    def to_step_run(self) -> WorkStepRun:
        metadata = _without_none(
            {
                "step_index": self.step_index,
                "operation_id": self.operation_id,
                "started_sequence": self.started_sequence,
                "completed_sequence": self.completed_sequence,
                "failed_sequence": self.failed_sequence,
                "cancelled_sequence": self.cancelled_sequence,
                "error": self.error,
                "deviation": asdict(self.deviation) if self.deviation is not None else None,
                "planned_constraint": self.planned_constraint,
                "audit_policy": self.audit_policy,
                "step_facts": self.step_facts,
            }
        )
        return WorkStepRun(
            run_id=self.run_id or "",
            plan_id=self.plan_id or "",
            step_id=self.step_id,
            sequence=self.started_sequence if self.started_sequence is not None else self.first_sequence or 0,
            status=self.status,
            method_id=self.method_id,
            title=self.title,
            deviation=self.deviation,
            metadata=metadata,
        )


def _entry_kind(entry: EventLogEntry) -> str:
    kind = entry.payload.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    return str(entry.entry_type)


def _entry_string_payload_value(entry: EventLogEntry, key: str) -> str:
    value = _entry_payload_value(entry, key)
    if isinstance(value, str):
        return value
    return ""


def _entry_step_index(entry: EventLogEntry) -> int | None:
    value = _entry_payload_value(entry, "step_index")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _entry_step_deviation(entry: EventLogEntry, *, step_id: str) -> WorkStepDeviation | None:
    value = _entry_payload_value(entry, "deviation")
    if not isinstance(value, Mapping):
        return None
    deviation_type = _mapping_string_value(value, "deviation_type") or _mapping_string_value(value, "type")
    if not deviation_type:
        return None
    reason = _mapping_string_value(value, "reason")
    metadata_value = value.get("metadata")
    metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
    return WorkStepDeviation(
        step_id=_mapping_string_value(value, "step_id") or step_id,
        deviation_type=deviation_type,
        reason=reason,
        policy_level=_mapping_string_value(value, "policy_level") or None,
        evidence_refs=_mapping_string_tuple(value.get("evidence_refs")),
        approval_ref=_mapping_string_value(value, "approval_ref") or None,
        risk=_mapping_string_value(value, "risk") or None,
        outcome=_mapping_string_value(value, "outcome") or None,
        metadata=metadata,
    )


def _entry_mapping_payload_value(entry: EventLogEntry, key: str) -> dict[str, object] | None:
    value = _entry_payload_value(entry, key)
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _mapping_string_value(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return ""


def _mapping_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list | tuple):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _entry_payload_value(entry: EventLogEntry, key: str) -> object | None:
    value = entry.payload.get(key)
    if value is not None:
        return value
    nested_payload = entry.payload.get("payload")
    if isinstance(nested_payload, Mapping):
        return nested_payload.get(key)
    return None


def _without_none(values: Mapping[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


__all__ = ["project_work_plan_runs"]
