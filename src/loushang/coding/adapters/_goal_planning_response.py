"""Bind a planning reply to its original committed Session invocation.

This deliberately supports one logical call in an exclusive planning Work, not
arbitrary prompt histories. Work completion alone is never response evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from loushang.ai.types import AssistantMessage, TextPart, ThinkingPart, UserMessage
from loushang.harness.events import RuntimeEvent
from loushang.harness.transcript.model_call import project_model_call_invocations
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_types import (
    ModelInputComponent,
    ModelInputIntegrityError,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import (
    ModelInputNodeBundle,
    ModelInputSnapshotV2,
)
from loushang.harness.transcript.model_usage_types import ModelCallAttemptUsage
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harnesswork.goal.records import plain

from ._goal_driver import digest
from ._goal_proposal import ProposalRejected

_SNAPSHOTS = (ModelInputSnapshot, ModelInputSnapshotV2)
_ALLOWED = (
    UserMessage,
    AssistantMessage,
    ModelInputComponent,
    ModelInputSnapshot,
    ModelInputNodeBundle,
    ModelInputSnapshotV2,
    ModelCallOutcome,
    ModelCallAttemptUsage,
)


def _invocations(records):
    try:
        return project_model_call_invocations(records)
    except ModelInputIntegrityError as error:
        raise ProposalRejected("planning invocation history inconsistent") from error


@dataclass(frozen=True)
class ResponseBoundary:
    record_ids: tuple[str, ...]
    invocation_ids: tuple[str, ...]

    @classmethod
    def capture(cls, manager) -> ResponseBoundary:
        return cls(
            tuple(record.record_id for record in manager.get_active_entries()),
            tuple(item.invocation_id for item in manager.get_model_call_invocations()),
        )


def _message_text(message) -> str:
    if isinstance(message, UserMessage) and isinstance(message.content, str):
        return message.content
    if not isinstance(message.content, list) or any(
        not isinstance(part, (TextPart, ThinkingPart)) for part in message.content
    ):
        raise ProposalRejected("planning message contains non-text or tool content")
    return "".join(part.text for part in message.content if isinstance(part, TextPart))


def _validate_segment(
    records: Sequence[AgentTranscriptRecord],
    boundary: ResponseBoundary,
    *,
    session_id: str,
    prompt: str,
) -> tuple[bytes, dict[str, object]]:
    ids = tuple(record.record_id for record in records)
    size = len(boundary.record_ids)
    if len(set(ids)) != len(ids) or ids[:size] != boundary.record_ids:
        raise ProposalRejected("planning Transcript path changed")
    suffix = records[size:]
    previous = boundary.record_ids[-1] if boundary.record_ids else None
    for record in suffix:
        if record.parent_id != previous or not isinstance(record.payload, _ALLOWED):
            raise ProposalRejected(
                "planning contains unrelated or non-append-only records"
            )
        previous = record.record_id
    users = [record for record in suffix if isinstance(record.payload, UserMessage)]
    assistants = [
        record for record in suffix if isinstance(record.payload, AssistantMessage)
    ]
    if len(users) != 1 or len(assistants) != 1:
        raise ProposalRejected(
            "planning requires exactly one user and assistant record"
        )
    user, assistant = users[0], assistants[0]
    assert isinstance(assistant.payload, AssistantMessage)
    if _message_text(user.payload) != prompt:
        raise ProposalRejected("planning prompt differs from trusted input")
    if (
        assistant.payload.stop_reason != "stop"
        or assistant.payload.error_message is not None
    ):
        raise ProposalRejected("planning assistant did not finish successfully")
    raw = _message_text(assistant.payload).encode("utf-8")
    invocations = _invocations(records)
    current = tuple(item.invocation_id for item in invocations)
    if current[: len(boundary.invocation_ids)] != boundary.invocation_ids:
        raise ProposalRejected("planning invocation history changed")
    added = invocations[len(boundary.invocation_ids) :]
    if len(added) != 1:
        raise ProposalRejected("planning requires exactly one new invocation")
    invocation = added[0]
    outcome = invocation.outcome
    if (
        invocation.state != "completed"
        or outcome is None
        or outcome.stop_reason != "stop"
    ):
        raise ProposalRejected("planning invocation outcome missing or unsuccessful")
    snapshots = [
        (record, record.payload)
        for record in suffix
        if isinstance(record.payload, (ModelInputSnapshot, ModelInputSnapshotV2))
    ]
    if (
        not 1 <= len(snapshots) <= 3
        or tuple(snapshot.snapshot_id for _, snapshot in snapshots)
        != invocation.model_input_snapshot_ids
        or [snapshot.attempt for _, snapshot in snapshots]
        != list(range(1, len(snapshots) + 1))
    ):
        raise ProposalRejected("planning snapshot attempts do not match invocation")
    positions = {record.record_id: index for index, record in enumerate(records)}
    for record, snapshot in snapshots:
        leaf_position = positions.get(snapshot.source_leaf_id, -1)
        if (
            snapshot.invocation_id != invocation.invocation_id
            or snapshot.conversation_id != session_id
            or not positions[user.record_id]
            <= leaf_position
            < positions[record.record_id]
            < positions[assistant.record_id]
        ):
            raise ProposalRejected("planning snapshot lacks trusted user ancestry")
    if any(
        isinstance(record.payload, (ModelCallOutcome, ModelCallAttemptUsage))
        and record.payload.invocation_id != invocation.invocation_id
        for record in suffix
    ):
        raise ProposalRejected("planning contains foreign invocation facts")
    proof: dict[str, object] = {
        "before_leaf_id": boundary.record_ids[-1] if boundary.record_ids else None,
        "after_leaf_id": records[-1].record_id,
        "user_record_id": user.record_id,
        "assistant_record_id": assistant.record_id,
        "invocation_id": invocation.invocation_id,
        "snapshot_ids": list(invocation.model_input_snapshot_ids),
        "prompt_sha256": digest(prompt.encode("utf-8")),
        "response_sha256": digest(raw),
    }
    return raw, proof


def capture_response(
    manager,
    boundary: ResponseBoundary,
    *,
    session_id: str,
    prompt: str,
    events: Sequence[RuntimeEvent],
) -> tuple[bytes, dict[str, object]]:
    """Call only after prompt and original wait_for_idle have both settled."""
    records = manager.get_active_entries()
    raw, proof = _validate_segment(
        records, boundary, session_id=session_id, prompt=prompt
    )
    _verify_inputs(manager, proof, prompt)
    messages = {
        record.record_id: record.payload
        for record in records[len(boundary.record_ids) :]
        if isinstance(record.payload, (UserMessage, AssistantMessage))
    }
    if len(events) != 2 or len({event.stream_id for event in events}) != 1:
        raise ProposalRejected("planning committed message events missing or ambiguous")
    if len({event.source_record_id for event in events}) != 2:
        raise ProposalRejected("planning message events are duplicated")
    for event in events:
        if (
            event.kind != "agent.message_end"
            or event.session_id != session_id
            or event.source_record_id not in messages
            or not isinstance(event.payload, Mapping)
            or event.payload.get("message") != messages[event.source_record_id]
        ):
            raise ProposalRejected("planning event is not the committed message")
    return raw, proof


def verify_response(
    manager, proof: Mapping[str, object], *, session_id: str, prompt: str, raw: bytes
) -> None:
    """Recheck persisted original records when consuming a report or cold reading it."""
    before_leaf = proof.get("before_leaf_id")
    after_leaf = proof.get("after_leaf_id")
    if not isinstance(after_leaf, str) or (
        before_leaf is not None and not isinstance(before_leaf, str)
    ):
        raise ProposalRejected("planning response boundary missing")
    before = manager.get_branch(before_leaf) if before_leaf is not None else []
    records = manager.get_branch(after_leaf)
    boundary = ResponseBoundary(
        tuple(record.record_id for record in before),
        tuple(item.invocation_id for item in _invocations(before)),
    )
    actual_raw, actual_proof = _validate_segment(
        records, boundary, session_id=session_id, prompt=prompt
    )
    if actual_raw != raw or actual_proof != plain(proof):
        raise ProposalRejected("planning response provenance mismatch")
    _verify_inputs(manager, actual_proof, prompt)


def _verify_inputs(manager, proof, prompt):
    for snapshot_id in proof["snapshot_ids"]:
        try:
            logical = manager.rebuild_model_input(snapshot_id).logical_input
        except (ValueError, OSError, KeyError, ModelInputIntegrityError) as error:
            raise ProposalRejected("planning input reconstruction failed") from error
        messages = logical["messages"]
        user = messages[-1] if messages else {}
        content = user.get("content")
        if isinstance(content, list) and all(
            isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            for part in content
        ):
            content = "".join(part.get("text", "") for part in content)
        if user.get("role") != "user" or content != prompt or logical["tools"]:
            raise ProposalRejected(
                "planning model input differs from trusted prompt/scope"
            )
