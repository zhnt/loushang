from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypeVar, cast

from loushang.agent.json_codec import AgentMessageJsonCodec, CustomMessageJsonCodec
from loushang.agent.types import CustomAgentMessage
from loushang.ai.json_codec import (
    deserialize_content_part,
    deserialize_message,
    serialize_content_part,
    serialize_message,
)
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    Message,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from loushang.foundation.json import JSONValue, require_json_mapping, require_json_value
from loushang.harness.conversation.jsonl_codec import (
    ConversationPayloadCodecRegistry,
    FunctionalConversationPayloadCodec,
)
from loushang.harness.conversation.types import CommandExecutionRecord
from loushang.harness.transcript.kinds import (
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
    THINKING_SELECTION_KIND,
)
from loushang.harness.transcript.model_call_codec import (
    decode_model_call_outcome,
    encode_model_call_outcome,
)
from loushang.harness.transcript.model_input_types import (
    FrozenModelInputValue,
    ModelInputComponent,
    ModelInputComponentReference,
    ModelInputSnapshot,
    thaw_model_input_json,
)
from loushang.harness.transcript.model_input_v2_codec import (
    decode_model_input_node_bundle,
    decode_model_input_snapshot_v2,
    encode_model_input_node_bundle,
    encode_model_input_snapshot_v2,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
)
from loushang.harness.transcript.types import (
    AnnotationOperation,
    ApplicationDeliveryMode,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ExtensionData,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
)

PayloadT = TypeVar("PayloadT")
STANDARD_PAYLOAD_VERSION = 1


def create_agent_transcript_payload_registry() -> ConversationPayloadCodecRegistry:
    registry = ConversationPayloadCodecRegistry()
    register_standard_payload_codecs(registry)
    return registry


def create_agent_transcript_message_codec() -> AgentMessageJsonCodec:
    """Compose AI messages with the standard application-message carrier."""

    def serialize(message: CustomAgentMessage) -> dict[str, object]:
        if not isinstance(message, ApplicationMessage):
            raise TypeError("application message codec received an invalid message")
        encoded = _encode_application_message(message)
        if not isinstance(encoded, dict):
            raise TypeError("application message codec must emit a JSON object")
        return {"role": message.role, **encoded}

    def deserialize(value: dict[str, object]) -> ApplicationMessage:
        return _decode_application_message(
            require_json_value(value),
            allow_message_role=True,
        )

    return AgentMessageJsonCodec(
        (
            CustomMessageJsonCodec(
                role="application",
                message_type=ApplicationMessage,
                serialize=serialize,
                deserialize=deserialize,
            ),
        )
    )


def register_standard_payload_codecs(
    registry: ConversationPayloadCodecRegistry,
) -> None:
    _register(
        registry,
        AGENT_MESSAGE_KIND,
        _encode_agent_message,
        _decode_agent_message,
    )
    _register(
        registry,
        THINKING_SELECTION_KIND,
        _encode_thinking_selection,
        _decode_thinking_selection,
    )
    _register(
        registry,
        MODEL_SELECTION_KIND,
        _encode_model_selection,
        _decode_model_selection,
    )
    _register(
        registry,
        COMMAND_EXECUTION_KIND,
        _encode_command_execution,
        _decode_command_execution,
    )
    _register(
        registry,
        CONTEXT_COMPACTION_CHECKPOINT_KIND,
        _encode_compaction_checkpoint,
        _decode_compaction_checkpoint,
    )
    _register(
        registry,
        CONTEXT_BRANCH_SUMMARY_KIND,
        _encode_branch_summary,
        _decode_branch_summary,
    )
    _register(
        registry,
        APPLICATION_MESSAGE_KIND,
        _encode_application_message,
        _decode_application_message,
    )
    _register(
        registry,
        EXTENSION_DATA_KIND,
        _encode_extension_data,
        _decode_extension_data,
    )
    _register(
        registry,
        RECORD_ANNOTATION_PATCH_KIND,
        _encode_annotation_patch,
        _decode_annotation_patch,
    )
    _register(
        registry,
        CONVERSATION_METADATA_PATCH_KIND,
        _encode_metadata_patch,
        _decode_metadata_patch,
    )
    _register(
        registry,
        MODEL_INPUT_COMPONENT_KIND,
        _encode_model_input_component,
        _decode_model_input_component,
    )
    _register(
        registry,
        MODEL_INPUT_PREPARED_KIND,
        _encode_model_input_snapshot,
        _decode_model_input_snapshot,
    )
    _register(
        registry,
        MODEL_CALL_OUTCOME_KIND,
        encode_model_call_outcome,
        decode_model_call_outcome,
    )
    registry.register(
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_V2_PAYLOAD_VERSION,
        FunctionalConversationPayloadCodec(
            encoder=encode_model_input_node_bundle,
            decoder=decode_model_input_node_bundle,
        ),
    )
    registry.register(
        MODEL_INPUT_PREPARED_KIND,
        MODEL_INPUT_V2_PAYLOAD_VERSION,
        FunctionalConversationPayloadCodec(
            encoder=encode_model_input_snapshot_v2,
            decoder=decode_model_input_snapshot_v2,
        ),
    )
    registry.require_known_payload_versions(
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_PREPARED_KIND,
    )


def _register(
    registry: ConversationPayloadCodecRegistry,
    kind: str,
    encoder,
    decoder,
) -> None:
    registry.register(
        kind,
        STANDARD_PAYLOAD_VERSION,
        FunctionalConversationPayloadCodec(encoder=encoder, decoder=decoder),
    )


def _encode_agent_message(payload: object) -> JSONValue:
    if not isinstance(payload, UserMessage | AssistantMessage | ToolResultMessage):
        raise TypeError("agent.message payload must be an AI message")
    return require_json_value(serialize_message(payload), name="agent message")


def _decode_agent_message(value: JSONValue) -> Message:
    return deserialize_message(_object(value, name="agent message"))


def _encode_thinking_selection(payload: object) -> JSONValue:
    selection = _instance(payload, ThinkingSelectionSnapshot)
    return {"level": selection.level}


def _decode_thinking_selection(value: JSONValue) -> ThinkingSelectionSnapshot:
    payload = _payload_object(value, name="thinking selection", fields={"level"})
    return ThinkingSelectionSnapshot(level=_text(payload, "level"))


def _encode_model_selection(payload: object) -> JSONValue:
    selection = _instance(payload, ModelSelectionSnapshot)
    return {
        "provider": selection.provider,
        "modelId": selection.model_id,
        "endpointId": selection.endpoint_id,
    }


def _decode_model_selection(value: JSONValue) -> ModelSelectionSnapshot:
    payload = _payload_object(
        value,
        name="model selection",
        fields={"provider", "modelId", "endpointId"},
    )
    return ModelSelectionSnapshot(
        provider=_text(payload, "provider"),
        endpoint_id=_text(payload, "endpointId"),
        model_id=_text(payload, "modelId"),
    )


def _encode_command_execution(payload: object) -> JSONValue:
    command = _instance(payload, CommandExecutionRecord)
    return {
        "command": command.command,
        "output": command.output,
        "exitCode": command.exit_code,
        "cancelled": command.cancelled,
        "truncated": command.truncated,
        "fullOutputPath": command.full_output_path,
        "excludeFromContext": command.exclude_from_context,
        "metadata": dict(command.metadata),
    }


def _decode_command_execution(value: JSONValue) -> CommandExecutionRecord:
    payload = _payload_object(
        value,
        name="command execution",
        fields={
            "command",
            "output",
            "exitCode",
            "cancelled",
            "truncated",
            "fullOutputPath",
            "excludeFromContext",
            "metadata",
        },
    )
    return CommandExecutionRecord(
        command=_string(payload, "command"),
        output=_string(payload, "output"),
        exit_code=_optional_int(payload, "exitCode"),
        cancelled=_bool(payload, "cancelled"),
        truncated=_bool(payload, "truncated"),
        full_output_path=_optional_string(payload, "fullOutputPath"),
        exclude_from_context=_bool(payload, "excludeFromContext"),
        metadata=_mapping(payload, "metadata"),
    )


def _encode_compaction_checkpoint(payload: object) -> JSONValue:
    checkpoint = _instance(payload, ContextCompactionCheckpoint)
    encoded: dict[str, JSONValue] = {
        "summary": checkpoint.summary,
        "firstKeptRecordId": checkpoint.first_kept_record_id,
        "tokensBefore": checkpoint.tokens_before,
        "details": require_json_value(checkpoint.details),
        "fromHook": checkpoint.from_hook,
    }
    if checkpoint.model_input_snapshot_ids:
        encoded["lineageVersion"] = 2
        encoded["modelInputSnapshotIds"] = list(checkpoint.model_input_snapshot_ids)
    return encoded


def _decode_compaction_checkpoint(
    value: JSONValue,
) -> ContextCompactionCheckpoint:
    payload = _payload_object(
        value,
        name="context compaction checkpoint",
        fields={
            "summary",
            "firstKeptRecordId",
            "tokensBefore",
            "details",
            "fromHook",
            "lineageVersion",
            "modelInputSnapshotIds",
        },
    )
    lineage = _decode_model_input_lineage(payload, name="context compaction checkpoint")
    return ContextCompactionCheckpoint(
        summary=_string(payload, "summary"),
        first_kept_record_id=_text(payload, "firstKeptRecordId"),
        tokens_before=_non_negative_int(payload, "tokensBefore"),
        details=_field(payload, "details"),
        from_hook=_optional_bool(payload, "fromHook"),
        model_input_snapshot_ids=lineage,
    )


def _encode_branch_summary(payload: object) -> JSONValue:
    summary = _instance(payload, BranchContextSummary)
    encoded: dict[str, JSONValue] = {
        "fromRecordId": summary.from_record_id,
        "summary": summary.summary,
        "details": require_json_value(summary.details),
        "fromHook": summary.from_hook,
    }
    if summary.model_input_snapshot_ids:
        encoded["lineageVersion"] = 2
        encoded["modelInputSnapshotIds"] = list(summary.model_input_snapshot_ids)
    return encoded


def _decode_branch_summary(value: JSONValue) -> BranchContextSummary:
    payload = _payload_object(
        value,
        name="branch context summary",
        fields={
            "fromRecordId",
            "summary",
            "details",
            "fromHook",
            "lineageVersion",
            "modelInputSnapshotIds",
        },
    )
    lineage = _decode_model_input_lineage(payload, name="branch context summary")
    return BranchContextSummary(
        from_record_id=_text(payload, "fromRecordId"),
        summary=_string(payload, "summary"),
        details=_field(payload, "details"),
        from_hook=_optional_bool(payload, "fromHook"),
        model_input_snapshot_ids=lineage,
    )


def _encode_application_message(payload: object) -> JSONValue:
    message = _instance(payload, ApplicationMessage)
    content: JSONValue
    if isinstance(message.content, str):
        content = message.content
    else:
        content = [serialize_content_part(part) for part in message.content]
    return {
        "applicationMessageId": message.application_message_id,
        "customType": message.custom_type,
        "content": content,
        "timestamp": message.timestamp,
        "display": message.display,
        "details": require_json_value(message.details),
        "origin": message.origin,
        "deliveryMode": message.delivery_mode,
    }


def _decode_application_message(
    value: JSONValue,
    *,
    allow_message_role: bool = False,
) -> ApplicationMessage:
    fields = {
        "applicationMessageId",
        "customType",
        "content",
        "timestamp",
        "display",
        "details",
        "origin",
        "deliveryMode",
    }
    if allow_message_role:
        fields.add("role")
    payload = _payload_object(
        value,
        name="application message",
        fields=fields,
    )
    if allow_message_role and _text(payload, "role") != "application":
        raise ValueError("application message role is invalid")
    content_value = _field(payload, "content")
    if isinstance(content_value, str):
        content: str | list[TextPart | ImagePart] = content_value
    elif isinstance(content_value, list):
        content = []
        for part_value in content_value:
            part = deserialize_content_part(
                _object(part_value, name="application message content part")
            )
            if not isinstance(part, TextPart | ImagePart):
                raise ValueError(
                    "application message content supports text and image parts only"
                )
            content.append(part)
    else:
        raise TypeError("application message content must be text or an array")
    delivery_mode = _text(payload, "deliveryMode")
    if delivery_mode not in {
        "direct",
        "trigger_turn",
        "steering",
        "follow_up",
        "next_turn",
    }:
        raise ValueError("application message delivery mode is invalid")
    return ApplicationMessage(
        application_message_id=_text(payload, "applicationMessageId"),
        custom_type=_text(payload, "customType"),
        content=content,
        timestamp=_number(payload, "timestamp"),
        display=_bool(payload, "display"),
        details=_field(payload, "details"),
        origin=_text(payload, "origin"),
        delivery_mode=cast(ApplicationDeliveryMode, delivery_mode),
    )


def _encode_extension_data(payload: object) -> JSONValue:
    data = _instance(payload, ExtensionData)
    return {
        "extensionType": data.extension_type,
        "data": require_json_value(data.data),
    }


def _decode_extension_data(value: JSONValue) -> ExtensionData:
    payload = _payload_object(
        value,
        name="extension data",
        fields={"extensionType", "data"},
    )
    return ExtensionData(
        extension_type=_text(payload, "extensionType"),
        data=_field(payload, "data"),
    )


def _encode_annotation_patch(payload: object) -> JSONValue:
    patch = _instance(payload, RecordAnnotationPatch)
    return {
        "targetRecordId": patch.target_record_id,
        "namespace": patch.namespace,
        "operation": patch.operation,
        "value": require_json_value(patch.value),
    }


def _decode_annotation_patch(value: JSONValue) -> RecordAnnotationPatch:
    payload = _payload_object(
        value,
        name="record annotation patch",
        fields={"targetRecordId", "namespace", "operation", "value"},
    )
    operation = _text(payload, "operation")
    if operation not in {"set", "remove"}:
        raise ValueError("record annotation operation is invalid")
    return RecordAnnotationPatch(
        target_record_id=_text(payload, "targetRecordId"),
        namespace=_text(payload, "namespace"),
        operation=cast(AnnotationOperation, operation),
        value=_field(payload, "value"),
    )


def _encode_metadata_patch(payload: object) -> JSONValue:
    patch = _instance(payload, ConversationMetadataPatch)
    return {
        "values": dict(patch.values),
        "removedKeys": list(patch.removed_keys),
    }


def _decode_metadata_patch(value: JSONValue) -> ConversationMetadataPatch:
    payload = _payload_object(
        value,
        name="conversation metadata patch",
        fields={"values", "removedKeys"},
    )
    removed = _field(payload, "removedKeys")
    if not isinstance(removed, list) or not all(
        isinstance(item, str) for item in removed
    ):
        raise TypeError("conversation metadata removedKeys must be strings")
    return ConversationMetadataPatch(
        values=_mapping(payload, "values"),
        removed_keys=tuple(cast(list[str], removed)),
    )


def _encode_model_input_component(payload: object) -> JSONValue:
    component = _instance(payload, ModelInputComponent)
    return {
        "schemaVersion": component.schema_version,
        "contentHash": component.content_hash,
        "content": thaw_model_input_json(component.content),
    }


def _decode_model_input_component(value: JSONValue) -> ModelInputComponent:
    payload = _payload_object(
        value,
        name="model input component",
        fields={"schemaVersion", "contentHash", "content"},
    )
    return ModelInputComponent(
        schema_version=_positive_int(payload, "schemaVersion"),
        content_hash=_text(payload, "contentHash"),
        content=cast(FrozenModelInputValue, _field(payload, "content")),
    )


def _encode_model_input_snapshot(payload: object) -> JSONValue:
    snapshot = _instance(payload, ModelInputSnapshot)
    return {
        "schemaVersion": snapshot.schema_version,
        "projectionVersion": snapshot.projection_version,
        "snapshotId": snapshot.snapshot_id,
        "invocationId": snapshot.invocation_id,
        "attempt": snapshot.attempt,
        "purpose": snapshot.purpose,
        "productId": snapshot.product_id,
        "runtimeId": snapshot.runtime_id,
        "mountGeneration": snapshot.mount_generation,
        "profileFingerprint": snapshot.profile_fingerprint,
        "registrationRevision": snapshot.registration_revision,
        "conversationId": snapshot.conversation_id,
        "sourceLeafId": snapshot.source_leaf_id,
        "sourceRevision": snapshot.source_revision,
        "commitRevision": snapshot.commit_revision,
        "providerId": snapshot.provider_id,
        "modelId": snapshot.model_id,
        "apiId": snapshot.api_id,
        "endpointId": snapshot.endpoint_id,
        "logicalComponents": [
            _encode_model_input_reference(reference)
            for reference in snapshot.logical_components
        ],
        "preparedPayloadComponents": [
            _encode_model_input_reference(reference)
            for reference in snapshot.prepared_payload_components
        ],
        "modelVisibleHeadersComponent": _encode_model_input_reference(
            snapshot.model_visible_headers_component
        ),
        "logicalInputHash": snapshot.logical_input_hash,
        "preparedPayloadHash": snapshot.prepared_payload_hash,
        "outcome": snapshot.outcome,
    }


def _decode_model_input_snapshot(value: JSONValue) -> ModelInputSnapshot:
    fields = {
        "schemaVersion",
        "projectionVersion",
        "snapshotId",
        "invocationId",
        "attempt",
        "purpose",
        "productId",
        "runtimeId",
        "mountGeneration",
        "profileFingerprint",
        "registrationRevision",
        "conversationId",
        "sourceLeafId",
        "sourceRevision",
        "commitRevision",
        "providerId",
        "modelId",
        "apiId",
        "endpointId",
        "logicalComponents",
        "preparedPayloadComponents",
        "modelVisibleHeadersComponent",
        "logicalInputHash",
        "preparedPayloadHash",
        "outcome",
    }
    payload = _payload_object(value, name="model input snapshot", fields=fields)
    outcome = _text(payload, "outcome")
    if outcome != "prepared":
        raise ValueError("model input snapshot outcome is invalid")
    return ModelInputSnapshot(
        schema_version=_positive_int(payload, "schemaVersion"),
        projection_version=_text(payload, "projectionVersion"),
        snapshot_id=_text(payload, "snapshotId"),
        invocation_id=_text(payload, "invocationId"),
        attempt=_positive_int(payload, "attempt"),
        purpose=_text(payload, "purpose"),
        product_id=_text(payload, "productId"),
        runtime_id=_text(payload, "runtimeId"),
        mount_generation=_non_negative_int(payload, "mountGeneration"),
        profile_fingerprint=_text(payload, "profileFingerprint"),
        registration_revision=_text(payload, "registrationRevision"),
        conversation_id=_text(payload, "conversationId"),
        source_leaf_id=_text(payload, "sourceLeafId"),
        source_revision=_non_negative_int(payload, "sourceRevision"),
        commit_revision=_positive_int(payload, "commitRevision"),
        provider_id=_text(payload, "providerId"),
        model_id=_text(payload, "modelId"),
        api_id=_text(payload, "apiId"),
        endpoint_id=_text(payload, "endpointId"),
        logical_components=_decode_model_input_references(
            payload,
            "logicalComponents",
        ),
        prepared_payload_components=_decode_model_input_references(
            payload,
            "preparedPayloadComponents",
        ),
        model_visible_headers_component=_decode_model_input_reference(
            _field(payload, "modelVisibleHeadersComponent")
        ),
        logical_input_hash=_text(payload, "logicalInputHash"),
        prepared_payload_hash=_text(payload, "preparedPayloadHash"),
        outcome=cast(Literal["prepared"], outcome),
    )


def _encode_model_input_reference(
    reference: ModelInputComponentReference,
) -> dict[str, JSONValue]:
    return {
        "name": reference.name,
        "recordId": reference.record_id,
        "contentHash": reference.content_hash,
    }


def _decode_model_input_references(
    value: Mapping[str, JSONValue],
    key: str,
) -> tuple[ModelInputComponentReference, ...]:
    field = _field(value, key)
    if not isinstance(field, list):
        raise TypeError(f"payload field {key!r} must be an array")
    return tuple(_decode_model_input_reference(item) for item in field)


def _decode_model_input_reference(value: object) -> ModelInputComponentReference:
    payload = _payload_object(
        value,
        name="model input component reference",
        fields={"name", "recordId", "contentHash"},
    )
    return ModelInputComponentReference(
        name=_text(payload, "name"),
        record_id=_text(payload, "recordId"),
        content_hash=_text(payload, "contentHash"),
    )


def _instance(value: object, expected: type[PayloadT]) -> PayloadT:
    if not isinstance(value, expected):
        raise TypeError(f"payload must be {expected.__name__}")
    return value


def _object(value: object, *, name: str) -> dict[str, JSONValue]:
    return require_json_mapping(value, name=name)


def _payload_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, JSONValue]:
    payload = _object(value, name=name)
    unexpected = set(payload).difference(fields)
    if unexpected:
        raise ValueError(
            f"{name} contains unknown fields: {', '.join(sorted(unexpected))}"
        )
    return payload


def _decode_model_input_lineage(
    payload: Mapping[str, JSONValue],
    *,
    name: str,
) -> tuple[str, ...]:
    has_version = "lineageVersion" in payload
    has_snapshots = "modelInputSnapshotIds" in payload
    if not has_version and not has_snapshots:
        return ()
    if not has_version or not has_snapshots:
        raise ValueError(f"{name} Model Input lineage fields must appear together")
    if payload["lineageVersion"] != 2:
        raise ValueError(f"{name} Model Input lineage version is unsupported")
    raw_ids = payload["modelInputSnapshotIds"]
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError(f"{name} Model Input lineage must be a non-empty list")
    snapshot_ids = tuple(raw_ids)
    if any(not isinstance(item, str) or not item.strip() for item in snapshot_ids):
        raise ValueError(f"{name} Model Input lineage ids must be non-empty strings")
    if len(set(snapshot_ids)) != len(snapshot_ids):
        raise ValueError(f"{name} Model Input lineage ids must be unique")
    return cast(tuple[str, ...], snapshot_ids)


def _field(value: Mapping[str, JSONValue], key: str) -> JSONValue:
    if key not in value:
        raise KeyError(f"missing payload field {key!r}")
    return value[key]


def _string(value: Mapping[str, JSONValue], key: str) -> str:
    field = _field(value, key)
    if not isinstance(field, str):
        raise TypeError(f"payload field {key!r} must be a string")
    return field


def _text(value: Mapping[str, JSONValue], key: str) -> str:
    field = _string(value, key)
    if not field.strip():
        raise ValueError(f"payload field {key!r} must not be empty")
    return field


def _optional_text(value: Mapping[str, JSONValue], key: str) -> str | None:
    field = _field(value, key)
    if field is None:
        return None
    if not isinstance(field, str) or not field.strip():
        raise TypeError(f"payload field {key!r} must be text or null")
    return field


def _optional_string(value: Mapping[str, JSONValue], key: str) -> str | None:
    field = _field(value, key)
    if field is None:
        return None
    if not isinstance(field, str):
        raise TypeError(f"payload field {key!r} must be a string or null")
    return field


def _bool(value: Mapping[str, JSONValue], key: str) -> bool:
    field = _field(value, key)
    if type(field) is not bool:
        raise TypeError(f"payload field {key!r} must be a boolean")
    return field


def _optional_bool(value: Mapping[str, JSONValue], key: str) -> bool | None:
    field = _field(value, key)
    if field is not None and type(field) is not bool:
        raise TypeError(f"payload field {key!r} must be a boolean or null")
    return cast(bool | None, field)


def _optional_int(value: Mapping[str, JSONValue], key: str) -> int | None:
    field = _field(value, key)
    if field is None:
        return None
    if isinstance(field, bool) or not isinstance(field, int):
        raise TypeError(f"payload field {key!r} must be an integer or null")
    return field


def _non_negative_int(value: Mapping[str, JSONValue], key: str) -> int:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int) or field < 0:
        raise TypeError(f"payload field {key!r} must be a non-negative integer")
    return field


def _positive_int(value: Mapping[str, JSONValue], key: str) -> int:
    field = _non_negative_int(value, key)
    if field < 1:
        raise ValueError(f"payload field {key!r} must be positive")
    return field


def _number(value: Mapping[str, JSONValue], key: str) -> float:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int | float):
        raise TypeError(f"payload field {key!r} must be a number")
    return float(field)


def _mapping(value: Mapping[str, JSONValue], key: str) -> dict[str, JSONValue]:
    return require_json_mapping(_field(value, key), name=f"payload.{key}")


__all__ = [
    "STANDARD_PAYLOAD_VERSION",
    "create_agent_transcript_message_codec",
    "create_agent_transcript_payload_registry",
    "register_standard_payload_codecs",
]
