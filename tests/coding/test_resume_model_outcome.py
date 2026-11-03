from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import Usage, UserMessage
from loushang.coding.resume_binding import (
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    inspect_coding_runtime_binding,
    prepare_coding_resume_user_record,
    project_coding_runtime_binding_path,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    coding_resume_input_record_digest,
)
from loushang.coding.resume_model_outcome import observe_coding_resume_model_outcome
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationRecord,
    OpaquePayload,
)
from loushang.harness.transcript.jsonl_file import write_agent_transcript_export
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_call_types import (
    ModelCallFailureInfo,
    ModelCallOutcome,
)
from loushang.harness.transcript.model_input_v2_types import (
    ModelInputNodeReference,
    ModelInputSnapshotV2,
)


@pytest.mark.parametrize("case", [
    "completed", "failed", "cancelled", "prepared_only", "input_only",
    "wrong_digest", "wrong_input", "duplicate_input", "duplicate_snapshot",
    "wrong_outcome_reference", "future_outcome", "future_snapshot",
    "wrong_conversation", "wrong_purpose", "other_user", "other_branch",
    "outcome_before_snapshot", "replayed_after_other_user",
])
def test_resume_model_observation_reopens_exact_selected_input_without_authority(tmp_path, case):
    created = "2026-10-12T00:00:00Z"
    header = ConversationHeader(conversation_id="session-1", version=1, created_at=created)
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    ancestry = project_coding_runtime_binding_path((), current_session_id="session-1").ancestry_digest
    bound = prepare_coding_resume_user_record(
        CodingRuntimeBindingV1(
            attempt_id="attempt-1", input_id="input-1", record_id="input-record",
            session_id="session-1", original_leaf_id=None, ancestry_digest=ancestry,
            subject_digest="a" * 64, origin_composition=None,
            planned_fingerprint="b" * 64, actual_fingerprint="c" * 64,
            payload_digest=coding_user_payload_digest(message),
        ), message, commit_parent_id=None, created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    records = [bound]

    def append(record_id, kind, payload, *, version=1):
        record = ConversationRecord(
            record_id=record_id, parent_id=records[-1].record_id,
            kind=kind, payload_version=version, created_at=created, payload=payload,
        )
        records.append(record)
        return record

    reference = ModelInputNodeReference("bundle", 0, "mapping_root", "a" * 64)
    snapshot = ModelInputSnapshotV2(
        snapshot_id="snapshot-1", invocation_id="invocation-1", attempt=1,
        purpose="main", product_id="coding", runtime_id="runtime-1",
        mount_generation=1, profile_fingerprint="a" * 64, registration_revision="b" * 64,
        conversation_id="session-1", source_leaf_id="input-record",
        source_revision=1, commit_revision=2, provider_id="test", model_id="test",
        api_id="test", endpoint_id="test", logical_root=reference,
        prepared_payload_root=reference,
        model_visible_headers_root=ModelInputNodeReference("bundle", 1, "json_value", "b" * 64),
        logical_input_hash="c" * 64, prepared_payload_hash="d" * 64,
    )
    if case == "wrong_conversation":
        snapshot = replace(snapshot, conversation_id="other-session")
    elif case == "wrong_purpose":
        snapshot = replace(snapshot, purpose="compaction")
    elif case == "other_user":
        append("other-user", AGENT_MESSAGE_KIND, UserMessage(role="user", content="other", timestamp=2.0))
    if case not in ("input_only", "duplicate_input"):
        append("snapshot-record", MODEL_INPUT_PREPARED_KIND, snapshot, version=2)
    if case == "duplicate_snapshot":
        append("duplicate-snapshot", MODEL_INPUT_PREPARED_KIND, snapshot, version=2)
    if case not in ("prepared_only", "input_only", "duplicate_input"):
        disposition = case if case in ("failed", "cancelled") else "completed"
        outcome = ModelCallOutcome(
            invocation_id="invocation-1",
            model_input_snapshot_ids=("wrong-snapshot" if case == "wrong_outcome_reference" else "snapshot-1",),
            disposition=disposition,
            stop_reason={"completed": "stop", "failed": "error", "cancelled": "aborted"}[disposition],
            usage=Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost=None),
            failure=ModelCallFailureInfo("failed", "test", False) if disposition == "failed" else None,
        )
        append("outcome-record", MODEL_CALL_OUTCOME_KIND,
               OpaquePayload({"future": True}) if case == "future_outcome" else outcome,
               version=99 if case == "future_outcome" else 1)
    if case == "duplicate_input":
        duplicate = replace(bound, record_id="duplicate-input", parent_id=bound.record_id)
        # Use a valid second Binding rather than only corrupting its record id.
        original_binding = inspect_coding_runtime_binding(bound.metadata).binding
        assert original_binding is not None
        second_binding = replace(
            original_binding, record_id=duplicate.record_id,
            attempt_id="attempt-2", original_leaf_id=bound.record_id,
            ancestry_digest=project_coding_runtime_binding_path(
                (bound,), current_session_id="session-1",
            ).ancestry_digest,
        )
        duplicate = prepare_coding_resume_user_record(
            second_binding, message, commit_parent_id=bound.record_id,
            created_at=datetime(2026, 10, 12, tzinfo=UTC),
        )
        records.append(duplicate)
    if case == "other_branch":
        records.append(ConversationRecord(
            record_id="branch", parent_id=bound.record_id, kind=AGENT_MESSAGE_KIND,
            payload_version=1, created_at=created,
            payload=UserMessage(role="user", content="branch", timestamp=2.0),
        ))
    if case == "outcome_before_snapshot":
        records = [
            bound, replace(records[2], parent_id=bound.record_id),
            replace(records[1], parent_id=records[2].record_id),
        ]
    elif case == "replayed_after_other_user":
        append("next-user", AGENT_MESSAGE_KIND, UserMessage(role="user", content="next", timestamp=2.0))
        append("replayed-snapshot", MODEL_INPUT_PREPARED_KIND,
               replace(snapshot, snapshot_id="snapshot-2", invocation_id="invocation-2"), version=2)
        append("replayed-outcome", MODEL_CALL_OUTCOME_KIND,
               replace(outcome, invocation_id="invocation-2", model_input_snapshot_ids=("snapshot-2",)))
    path = tmp_path / "history.jsonl"
    write_agent_transcript_export(path, header, records)
    before = path.read_bytes()
    # A fresh reader supplies all evidence; no process-local dispatch state survives.
    history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    if case == "future_snapshot":
        # Required unknown Model Input versions are rejected by the native file
        # codec. Exercise defensive projection without weakening that codec.
        changed = tuple(
            replace(record, payload=OpaquePayload({"future": True}), payload_version=99)
            if record.kind == MODEL_INPUT_PREPARED_KIND else record
            for record in history.records
        )
        history = replace(history, records=changed, selected_records=changed)
    query = CodingResumeInputLookupQueryV1(
        "missing" if case == "wrong_input" else "input-1",
        "e" * 64 if case == "wrong_digest" else coding_resume_input_record_digest(bound),
    )
    observed = observe_coding_resume_model_outcome(history, query)
    expected = (
        "observed_" + case if case in ("completed", "failed", "cancelled")
        else "conflict" if case in ("wrong_digest", "duplicate_input", "duplicate_snapshot", "replayed_after_other_user")
        else "unknown"
    )
    assert observed.status == expected
    assert path.read_bytes() == before
    assert "continue" not in repr(observed)
