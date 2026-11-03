import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import TextPart, UserMessage
from loushang.coding.resume_activation_attempt_v2 import (
    prepare_coding_activation_attempt_v2_record,
    validate_coding_activation_attempt_v2_record,
)
from loushang.coding.resume_binding import coding_user_payload_digest
from loushang.coding.resume_binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY,
    CodingRuntimeBindingV2,
    decode_coding_runtime_binding_v2,
    prepare_coding_resume_v2_user_record,
    validate_coding_resume_v2_user_record,
)
from loushang.harness.conversation import (
    ConversationHeader,
    StoreCommitOutcomeUnknown,
    StoreOperationConflictError,
)
from loushang.harness.conversation.stores import file as file_store_module
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from tests.coding.test_resume_activation_attempt_v2 import _intent, _owner


def _binding(message, intent):
    return CodingRuntimeBindingV2(
        attempt_id=intent.attempt_id,
        input_id=intent.request_id,
        record_id="message-1",
        session_id=intent.session_id,
        original_leaf_id=intent.original_leaf_id,
        ancestry_digest=intent.ancestry_digest,
        subject_digest=intent.subject_digest,
        origin_composition=None,
        planned_fingerprint=intent.plan_fingerprint,
        actual_fingerprint=intent.epoch_fingerprint,
        payload_digest=coding_user_payload_digest(message),
        intent_digest=intent.digest,
    )


def _prepared():
    intent = _intent()
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    binding = _binding(message, intent)
    record = prepare_coding_resume_v2_user_record(
        binding,
        message,
        intent=intent,
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
        resource_metadata={"resource.evidence": {"sourceRevision": "revision-1"}},
    )
    return intent, binding, record


def test_binding_v2_user_message_and_resource_evidence_share_one_fixed_record():
    intent, binding, record = _prepared()
    assert record.kind == AGENT_MESSAGE_KIND
    assert type(record.payload) is UserMessage
    assert record.record_id == binding.record_id
    assert record.parent_id == intent.attempt_id
    assert set(record.metadata) == {
        CODING_RUNTIME_BINDING_V2_METADATA_KEY,
        "resource.evidence",
    }
    assert decode_coding_runtime_binding_v2(record.metadata) == binding
    assert validate_coding_resume_v2_user_record(record, intent=intent) == binding
    assert (
        record.metadata[CODING_RUNTIME_BINDING_V2_METADATA_KEY]["intentDigest"]
        == intent.digest
    )


def test_binding_v2_freezes_caller_input_before_record_construction():
    intent = _intent()
    parts = [TextPart(type="text", text="continue")]
    message = UserMessage(role="user", content=parts, timestamp=1.0)
    binding = _binding(message, intent)
    record = prepare_coding_resume_v2_user_record(
        binding,
        message,
        intent=intent,
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    parts.append(TextPart(type="text", text="changed"))
    assert coding_user_payload_digest(record.payload) == binding.payload_digest
    assert validate_coding_resume_v2_user_record(record, intent=intent) == binding


@pytest.mark.parametrize(
    "field",
    [
        "attempt_id",
        "input_id",
        "session_id",
        "ancestry_digest",
        "subject_digest",
        "planned_fingerprint",
        "actual_fingerprint",
        "intent_digest",
    ],
)
def test_binding_v2_requires_exact_frozen_intent_before_record_build(field):
    intent, binding, record = _prepared()
    changed = replace(
        binding, **{field: "other" if field.endswith("_id") else "e" * 64}
    )
    with pytest.raises(ValueError, match="frozen intent"):
        prepare_coding_resume_v2_user_record(
            changed,
            record.payload,
            intent=intent,
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )


def test_owner_obligation_change_cannot_reuse_previous_binding_digest():
    intent, _, record = _prepared()
    changed = replace(intent, effect_owners=(_owner(contract_digest="e" * 64),))
    with pytest.raises(ValueError, match="frozen intent"):
        validate_coding_resume_v2_user_record(record, intent=changed)


@pytest.mark.parametrize(
    "fault",
    [
        "v1_only",
        "v1_version",
        "future_version",
        "bool_version",
        "missing_digest",
        "extra_field",
        "mixed_versions",
    ],
)
def test_v1_and_unsupported_binding_wire_cannot_supply_v2_proof(fault):
    _, binding, _ = _prepared()
    metadata = binding.to_message_metadata()
    raw = metadata[CODING_RUNTIME_BINDING_V2_METADATA_KEY]
    if fault == "v1_only":
        metadata = {"coding.runtimeBindingV1": raw}
    elif fault == "mixed_versions":
        metadata["coding.runtimeBindingV1"] = raw
    elif fault == "missing_digest":
        del raw["intentDigest"]
    elif fault == "extra_field":
        raw["approval"] = True
    else:
        raw["version"] = {"v1_version": 1, "future_version": 3, "bool_version": True}[
            fault
        ]
    with pytest.raises(ValueError):
        decode_coding_runtime_binding_v2(metadata)


@pytest.mark.parametrize("fault", ["record", "parent", "payload"])
def test_stored_binding_v2_rejects_changed_identity_parent_or_payload(fault):
    intent, _, record = _prepared()
    if fault == "record":
        changed = replace(record, record_id="other-record")
    elif fault == "parent":
        changed = replace(record, parent_id="other-parent")
    else:
        changed = replace(
            record, payload=UserMessage(role="user", content="changed", timestamp=1.0)
        )
    with pytest.raises(ValueError):
        validate_coding_resume_v2_user_record(changed, intent=intent)


def test_resource_metadata_cannot_override_a_binding_version():
    intent, binding, record = _prepared()
    with pytest.raises(ValueError, match="conflicts"):
        prepare_coding_resume_v2_user_record(
            binding,
            record.payload,
            intent=intent,
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
            resource_metadata={"coding.runtimeBindingV1": {"version": 1}},
        )


@pytest.mark.parametrize("lost_ack", [False, True])
def test_original_transcript_store_persists_one_v2_message_and_recovers_ack_loss(
    tmp_path, monkeypatch, lost_ack
):
    async def scenario():
        intent, binding, record = _prepared()
        layout = AgentTranscriptFileLayout(root=tmp_path / "transcripts")
        store = create_agent_transcript_file_store(layout)
        key = layout.key(intent.session_id)
        intent_record = prepare_coding_activation_attempt_v2_record(
            intent,
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )
        initial = await store.create(
            key,
            ConversationHeader(
                conversation_id=intent.session_id,
                version=1,
                created_at=record.created_at,
            ),
            (intent_record,),
            operation_id="create-session",
        )
        if lost_ack:
            append = file_store_module._append_unlocked

            def missing_ack(*args, **kwargs):
                append(*args, **kwargs)
                raise OSError("lost durable input acknowledgement")

            with monkeypatch.context() as scope:
                scope.setattr(file_store_module, "_append_unlocked", missing_ack)
                with pytest.raises(StoreCommitOutcomeUnknown):
                    await store.append(
                        key,
                        record,
                        expected_revision=initial.revision,
                        operation_id=binding.record_id,
                    )
        result = await store.append(
            key,
            record,
            expected_revision=initial.revision,
            operation_id=binding.record_id,
        )
        assert result.receipt.record_id == binding.record_id
        changed_binding = dict(record.metadata["coding.runtimeBindingV2"])
        changed_binding["intentDigest"] = "e" * 64
        changed_record = replace(
            record,
            metadata={**record.metadata, "coding.runtimeBindingV2": changed_binding},
        )
        with pytest.raises(StoreOperationConflictError):
            await store.append(
                key,
                changed_record,
                expected_revision=initial.revision,
                operation_id=binding.record_id,
            )
        readonly = create_agent_transcript_file_store(layout, read_only=True)
        loaded = await readonly.load(key)
        assert loaded.snapshot is not None
        assert len(loaded.snapshot.records) == 2
        messages = [
            item
            for item in loaded.snapshot.records
            if type(item.payload) is UserMessage
        ]
        assert len(messages) == 1
        persisted = messages[0]
        assert persisted.record_id == binding.record_id
        assert (
            persisted.metadata["resource.evidence"]
            == record.metadata["resource.evidence"]
        )
        assert (
            validate_coding_resume_v2_user_record(
                persisted,
                intent=validate_coding_activation_attempt_v2_record(
                    loaded.snapshot.records[0]
                ),
            )
            == binding
        )

    asyncio.run(scenario())
