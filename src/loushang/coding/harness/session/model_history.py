"""Read the exact initial Model Call anchored to a selected input."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from loushang.ai.types import UserMessage
from loushang.harness.transcript.kinds import (
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_call import (
    ModelCallInvocationProjection,
    project_model_call_invocations,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_types import (
    ModelInputIntegrityError,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2
from loushang.harness.transcript.types import AgentTranscriptRecord


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
