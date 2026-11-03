"""Bounded historical Model Outcome observation for one exact Resume input.

Observed facts never authorize retry, transport, activation or current effects.
Missing snapshots or outcomes remain unknown, including after a restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.ai.types import UserMessage
from loushang.harness.transcript.kinds import (
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_call import (
    ModelCallInvocationState,
    project_model_call_invocations,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_types import (
    ModelInputIntegrityError,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2

from .resume_binding import (
    inspect_coding_runtime_binding,
    validate_coding_runtime_binding_record,
)
from .resume_history import CodingResumeHistoryPreview
from .resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    coding_resume_input_record_digest,
)

CodingResumeModelOutcomeStatus: TypeAlias = Literal[
    "unknown", "conflict", "observed_completed", "observed_failed", "observed_cancelled",
]

_OBSERVED_STATUS: dict[ModelCallInvocationState, CodingResumeModelOutcomeStatus] = {
    "completed": "observed_completed", "failed": "observed_failed",
    "cancelled": "observed_cancelled", "unknown": "unknown",
}


@dataclass(frozen=True, slots=True)
class CodingResumeModelOutcomeObservationV1:
    input_id: str
    input_record_id: str | None = None
    invocation_id: str | None = None
    model_input_snapshot_ids: tuple[str, ...] = ()
    status: CodingResumeModelOutcomeStatus = "unknown"


def observe_coding_resume_model_outcome(
    history: CodingResumeHistoryPreview, query: CodingResumeInputLookupQueryV1,
) -> CodingResumeModelOutcomeObservationV1:
    """Use original selected-path Model Input/Outcome facts, without a ledger.

    Only the first main invocation anchored to the exact bound UserMessage is
    observed. Compaction, other users, copied fork evidence and later tool-loop
    invocations cannot stand in for that initial invocation's terminal fact.
    Content, provider responses and failure details do not leave this projection.
    """

    if type(history) is not CodingResumeHistoryPreview or type(query) is not CodingResumeInputLookupQueryV1:
        raise TypeError("invalid Coding Resume outcome observation input")
    unknown = CodingResumeModelOutcomeObservationV1(query.input_id)
    if len(history.records) > 65536 or history.binding_status in ("invalid", "unknown_version"):
        return unknown
    path = history.selected_records
    session_id = history.header_preview.header.conversation_id
    matches = []
    try:
        for index, record in enumerate(path):
            binding = inspect_coding_runtime_binding(record.metadata).binding
            if binding is None or binding.session_id != session_id or binding.input_id != query.input_id:
                continue
            validate_coding_runtime_binding_record(record, expected_session_id=session_id)
            matches.append((index, record))
    except ValueError:
        return unknown
    if not matches:
        return unknown
    if len(matches) != 1 or coding_resume_input_record_digest(matches[0][1]) != query.record_digest:
        return CodingResumeModelOutcomeObservationV1(query.input_id, status="conflict")
    index, input_record = matches[0]
    unknown = CodingResumeModelOutcomeObservationV1(query.input_id, input_record.record_id)
    end = next((i for i in range(index + 1, len(path)) if isinstance(path[i].payload, UserMessage)), len(path))
    candidates = []
    for position, record in enumerate(path[index + 1:], start=index + 1):
        payload = record.payload
        if record.kind == MODEL_INPUT_PREPARED_KIND and not isinstance(payload, ModelInputSnapshot | ModelInputSnapshotV2):
            return unknown
        if not isinstance(payload, ModelInputSnapshot | ModelInputSnapshotV2):
            continue
        if (
            payload.source_leaf_id == input_record.record_id
            and payload.conversation_id == session_id
            and payload.product_id == "coding" and payload.purpose == "main"
        ):
            candidates.append((position, payload))
    if not candidates:
        return unknown
    # Repeated consumption or replay is not collapsed into the latest success.
    if len(candidates) != 1:
        return CodingResumeModelOutcomeObservationV1(query.input_id, input_record.record_id, status="conflict")
    position, snapshot = candidates[0]
    if position >= end:
        return unknown
    if len(snapshot.invocation_id) > 256 or len(snapshot.snapshot_id) > 256:
        return unknown
    for record in path[index + 1:]:
        if record.kind == MODEL_CALL_OUTCOME_KIND and not isinstance(record.payload, ModelCallOutcome):
            return unknown
    if any(
        isinstance(record.payload, ModelCallOutcome)
        and record.payload.invocation_id == snapshot.invocation_id
        for record in path[:position]
    ):
        return unknown
    try:
        invocations = project_model_call_invocations(path)
    except ModelInputIntegrityError:
        return unknown
    invocation = next((item for item in invocations if item.invocation_id == snapshot.invocation_id), None)
    if invocation is None or invocation.model_input_snapshot_ids != (snapshot.snapshot_id,):
        return unknown
    return CodingResumeModelOutcomeObservationV1(
        query.input_id, input_record.record_id, invocation.invocation_id,
        invocation.model_input_snapshot_ids, _OBSERVED_STATUS[invocation.state],
    )
