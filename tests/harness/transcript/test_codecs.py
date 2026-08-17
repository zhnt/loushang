from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.ai.types import TextPart, Usage, UserMessage
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.journal import JournalCodecError
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    STANDARD_AGENT_TRANSCRIPT_KINDS,
    STANDARD_PAYLOAD_VERSION,
    THINKING_SELECTION_KIND,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ExtensionData,
    ModelCallFailureInfo,
    ModelCallOutcome,
    ModelInputComponent,
    ModelInputComponentReference,
    ModelInputSnapshot,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
    create_agent_transcript_message_codec,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.model_input_types import hash_model_input_json
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
)


def _payloads():
    component_content = {"role": "user", "content": "question"}
    component_hash = hash_model_input_json(
        component_content,
        name="codec Model Input component",
    )
    component = ModelInputComponent(
        content_hash=component_hash,
        content=component_content,
    )
    reference = ModelInputComponentReference(
        name="messages",
        record_id="component-record",
        content_hash=component_hash,
    )
    return {
        AGENT_MESSAGE_KIND: UserMessage(
            role="user",
            content=[TextPart(type="text", text="question")],
            timestamp=1.0,
        ),
        THINKING_SELECTION_KIND: ThinkingSelectionSnapshot(level="high"),
        MODEL_SELECTION_KIND: ModelSelectionSnapshot(
            provider="provider",
            model_id="model",
            endpoint_id="endpoint",
        ),
        COMMAND_EXECUTION_KIND: CommandExecutionRecord(
            command="printf hello",
            output="hello",
            exit_code=0,
            truncated=True,
            full_output_path="/tmp/output",
            metadata={"shell": "bash"},
        ),
        CONTEXT_COMPACTION_CHECKPOINT_KIND: ContextCompactionCheckpoint(
            summary="Earlier work",
            first_kept_record_id="kept",
            tokens_before=123,
            details={"source": "automatic"},
            from_hook=False,
        ),
        CONTEXT_BRANCH_SUMMARY_KIND: BranchContextSummary(
            from_record_id="branch-leaf",
            summary="Alternative path",
            details=["one", 2],
            from_hook=True,
        ),
        APPLICATION_MESSAGE_KIND: ApplicationMessage(
            application_message_id="application-1",
            custom_type="notice",
            content=[TextPart(type="text", text="Check this")],
            timestamp=2.5,
            details={"priority": 1},
            origin="extension.alpha",
            delivery_mode="follow_up",
        ),
        EXTENSION_DATA_KIND: ExtensionData(
            extension_type="extension.alpha.state",
            data={"enabled": True},
        ),
        RECORD_ANNOTATION_PATCH_KIND: RecordAnnotationPatch(
            target_record_id="target",
            namespace="display.label",
            operation="set",
            value="Important",
        ),
        CONVERSATION_METADATA_PATCH_KIND: ConversationMetadataPatch(
            values={"title": "Investigation", "count": 2},
            removed_keys=("oldTitle",),
        ),
        MODEL_CALL_OUTCOME_KIND: ModelCallOutcome(
            invocation_id="invocation-1",
            model_input_snapshot_ids=("snapshot-1",),
            disposition="completed",
            stop_reason="stop",
            usage=Usage(
                input=12,
                output=4,
                cache_read=2,
                cache_write=1,
                total_tokens=19,
                cost=None,
            ),
        ),
        MODEL_INPUT_COMPONENT_KIND: component,
        MODEL_INPUT_PREPARED_KIND: ModelInputSnapshot(
            snapshot_id="snapshot-1",
            invocation_id="invocation-1",
            attempt=1,
            purpose="main_turn",
            product_id="coding",
            runtime_id="runtime-1",
            mount_generation=3,
            profile_fingerprint="a" * 64,
            registration_revision="b" * 64,
            conversation_id="conversation-1",
            source_leaf_id="source-record",
            source_revision=4,
            commit_revision=9,
            provider_id="provider-1",
            model_id="model-1",
            api_id="api-1",
            endpoint_id="endpoint-1",
            logical_components=tuple(
                replace(reference, name=name)
                for name in (
                    "system_prompt",
                    "messages",
                    "tools",
                    "request_options",
                )
            ),
            prepared_payload_components=(reference,),
            model_visible_headers_component=replace(
                reference,
                name="model_visible_headers",
            ),
            logical_input_hash="c" * 64,
            prepared_payload_hash="d" * 64,
        ),
    }


def test_all_standard_payloads_round_trip_through_versioned_registry() -> None:
    registry = create_agent_transcript_payload_registry()

    assert registry.required_kinds == (
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_PREPARED_KIND,
    )
    assert registry.registered_keys == tuple(
        sorted(
            (
                *(
                    (kind, STANDARD_PAYLOAD_VERSION)
                    for kind in STANDARD_AGENT_TRANSCRIPT_KINDS
                ),
                (MODEL_INPUT_COMPONENT_KIND, MODEL_INPUT_V2_PAYLOAD_VERSION),
                (MODEL_INPUT_PREPARED_KIND, MODEL_INPUT_V2_PAYLOAD_VERSION),
            )
        )
    )
    for kind, payload in _payloads().items():
        encoded = registry.encode(kind, STANDARD_PAYLOAD_VERSION, payload)
        decoded = registry.decode(kind, STANDARD_PAYLOAD_VERSION, encoded)
        assert decoded == payload


def test_model_call_failure_codec_round_trips_only_safe_typed_fields() -> None:
    registry = create_agent_transcript_payload_registry()
    outcome = ModelCallOutcome(
        invocation_id="invocation-failed",
        model_input_snapshot_ids=("snapshot-failed",),
        disposition="failed",
        stop_reason="error",
        usage=Usage(12, 0, 0, 0, 12, None),
        failure=ModelCallFailureInfo(
            code="provider",
            source="openai-responses",
            retryable=False,
            status_code=400,
            request_id="request-400",
            details={
                "exceptionType": "ProviderHTTPError",
                "providerErrorType": "invalid_request_error",
                "providerErrorCode": "request_too_large",
                "providerResponseSummary": "private prompt",
            },
        ),
    )

    encoded = registry.encode(
        MODEL_CALL_OUTCOME_KIND,
        STANDARD_PAYLOAD_VERSION,
        outcome,
    )

    assert registry.decode(
        MODEL_CALL_OUTCOME_KIND,
        STANDARD_PAYLOAD_VERSION,
        encoded,
    ) == outcome
    assert encoded["failure"]["details"] == {
        "exceptionType": "ProviderHTTPError",
        "providerErrorType": "invalid_request_error",
        "providerErrorCode": "request_too_large",
    }
    assert "private prompt" not in repr(encoded)


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (
            CONTEXT_COMPACTION_CHECKPOINT_KIND,
            ContextCompactionCheckpoint(
                summary="summary",
                first_kept_record_id="kept",
                tokens_before=3,
                model_input_snapshot_ids=("snapshot-history", "snapshot-prefix"),
            ),
        ),
        (
            CONTEXT_BRANCH_SUMMARY_KIND,
            BranchContextSummary(
                from_record_id="branch",
                summary="summary",
                model_input_snapshot_ids=("snapshot-branch",),
            ),
        ),
    ],
)
def test_summary_v2_lineage_round_trips_without_rewriting_v1(kind, payload) -> None:
    registry = create_agent_transcript_payload_registry()

    encoded = registry.encode(kind, STANDARD_PAYLOAD_VERSION, payload)

    assert encoded["lineageVersion"] == 2
    assert registry.decode(kind, STANDARD_PAYLOAD_VERSION, encoded) == payload
    legacy = _payloads()[kind]
    legacy_encoded = registry.encode(kind, STANDARD_PAYLOAD_VERSION, legacy)
    assert "lineageVersion" not in legacy_encoded
    assert legacy.derivation_verifiable is False


def test_registered_codec_rejects_corrupted_known_payload() -> None:
    registry = create_agent_transcript_payload_registry()

    with pytest.raises(JournalCodecError) as error:
        registry.decode(
            MODEL_SELECTION_KIND,
            STANDARD_PAYLOAD_VERSION,
            {"provider": "provider", "modelId": 3, "endpointId": None},
        )

    assert error.value.code == "invalid_known_payload"


def test_registered_codec_rejects_unknown_fields_in_known_payload() -> None:
    registry = create_agent_transcript_payload_registry()

    with pytest.raises(JournalCodecError) as error:
        registry.decode(
            MODEL_SELECTION_KIND,
            STANDARD_PAYLOAD_VERSION,
            {
                "provider": "provider",
                "modelId": "model",
                "endpointId": None,
                "futurePolicy": "must not be dropped",
            },
        )

    assert error.value.code == "invalid_known_payload"


def test_agent_message_codec_preserves_application_message_identity() -> None:
    message = _payloads()[APPLICATION_MESSAGE_KIND]
    assert isinstance(message, ApplicationMessage)
    codec = create_agent_transcript_message_codec()

    encoded = codec.serialize(message)

    assert encoded["role"] == "application"
    assert codec.deserialize(encoded) == message


def test_patch_contracts_distinguish_remove_from_setting_json_null() -> None:
    set_null = RecordAnnotationPatch(
        target_record_id="target",
        namespace="display.label",
        operation="set",
        value=None,
    )
    assert set_null.operation == "set"

    with pytest.raises(ValueError, match="must not include a value"):
        RecordAnnotationPatch(
            target_record_id="target",
            namespace="display.label",
            operation="remove",
            value="not allowed",
        )

    with pytest.raises(ValueError, match="set and removed together"):
        ConversationMetadataPatch(
            values={"title": "new"},
            removed_keys=("title",),
        )
