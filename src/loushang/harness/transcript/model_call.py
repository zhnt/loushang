"""Project durable model-call attempts and terminal outcomes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from loushang.ai.types import UserMessage
from loushang.harness.transcript.kinds import (
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_types import (
    ModelInputIntegrityError,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2
from loushang.harness.transcript.types import AgentTranscriptRecord

ModelCallInvocationState: TypeAlias = Literal[
    "completed",
    "failed",
    "cancelled",
    "unknown",
]


@dataclass(frozen=True)
class ModelCallInvocationProjection:
    """Selected-path view of one logical invocation's durable closure."""

    invocation_id: str
    model_input_snapshot_ids: tuple[str, ...]
    state: ModelCallInvocationState
    outcome: ModelCallOutcome | None = field(default=None, repr=False)

    @property
    def terminal(self) -> bool:
        return self.outcome is not None


def project_model_call_invocations(
    records: Sequence[AgentTranscriptRecord],
) -> tuple[ModelCallInvocationProjection, ...]:
    """Group prepared attempts and outcomes without inventing missing facts."""

    invocation_order: list[str] = []
    snapshots_by_invocation: dict[str, list[str]] = {}
    outcomes_by_invocation: dict[str, ModelCallOutcome] = {}
    for record in records:
        payload = record.payload
        if isinstance(payload, ModelInputSnapshot | ModelInputSnapshotV2):
            snapshot_ids = snapshots_by_invocation.get(payload.invocation_id)
            if snapshot_ids is None:
                invocation_order.append(payload.invocation_id)
                snapshot_ids = []
                snapshots_by_invocation[payload.invocation_id] = snapshot_ids
            if payload.snapshot_id in snapshot_ids:
                raise ModelInputIntegrityError(
                    "model call invocation contains a duplicate Model Input snapshot"
                )
            snapshot_ids.append(payload.snapshot_id)
            continue
        if not isinstance(payload, ModelCallOutcome):
            continue
        if payload.invocation_id in outcomes_by_invocation:
            raise ModelInputIntegrityError(
                "model call invocation has more than one terminal outcome"
            )
        if payload.invocation_id not in snapshots_by_invocation:
            invocation_order.append(payload.invocation_id)
            snapshots_by_invocation[payload.invocation_id] = []
        outcomes_by_invocation[payload.invocation_id] = payload

    projected: list[ModelCallInvocationProjection] = []
    for invocation_id in invocation_order:
        ordered_snapshot_ids = tuple(snapshots_by_invocation[invocation_id])
        outcome = outcomes_by_invocation.get(invocation_id)
        if (
            outcome is not None
            and outcome.model_input_snapshot_ids != ordered_snapshot_ids
        ):
            raise ModelInputIntegrityError(
                "model call outcome does not match its selected-path attempt sequence"
            )
        projected.append(
            ModelCallInvocationProjection(
                invocation_id=invocation_id,
                model_input_snapshot_ids=ordered_snapshot_ids,
                state=(outcome.disposition if outcome is not None else "unknown"),
                outcome=outcome,
            )
        )
    return tuple(projected)


def find_initial_model_invocation(
    path: Sequence[AgentTranscriptRecord],
    *,
    index: int,
    session_id: str,
    product_id: str,
) -> ModelCallInvocationProjection | Literal["conflict"] | None:
    """Correlate one input and one main invocation before the next user input."""
    input_record_id = path[index].record_id
    later_records = path[index + 1 :]
    later_inputs = (
        position
        for position, record in enumerate(later_records, start=index + 1)
        if isinstance(record.payload, UserMessage)
    )
    end = next(later_inputs, len(path))
    candidates = []
    for position, record in enumerate(later_records, start=index + 1):
        payload = record.payload
        is_prepared = record.kind == MODEL_INPUT_PREPARED_KIND
        if not isinstance(payload, ModelInputSnapshot | ModelInputSnapshotV2):
            if is_prepared:
                return None
            continue
        if (
            payload.source_leaf_id == input_record_id
            and payload.conversation_id == session_id
            and payload.product_id == product_id
            and payload.purpose == "main"
        ):
            candidates.append((position, payload))
    if not candidates:
        return None
    # Repeated consumption or replay is not collapsed into the latest success.
    if len(candidates) != 1:
        return "conflict"
    position, snapshot = candidates[0]
    if position >= end:
        return None
    if len(snapshot.invocation_id) > 256 or len(snapshot.snapshot_id) > 256:
        return None
    for record in later_records:
        if record.kind == MODEL_CALL_OUTCOME_KIND and not isinstance(
            record.payload, ModelCallOutcome
        ):
            return None
    if any(
        isinstance(record.payload, ModelCallOutcome)
        and record.payload.invocation_id == snapshot.invocation_id
        for record in path[:position]
    ):
        return None
    try:
        invocations = project_model_call_invocations(path)
    except ModelInputIntegrityError:
        return None
    invocation = next(
        (item for item in invocations if item.invocation_id == snapshot.invocation_id),
        None,
    )
    if invocation is None or invocation.model_input_snapshot_ids != (
        snapshot.snapshot_id,
    ):
        return None
    return invocation


__all__ = [
    "ModelCallInvocationProjection",
    "ModelCallInvocationState",
    "project_model_call_invocations",
]
