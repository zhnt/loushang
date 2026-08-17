"""JSON codecs for Model Input v2 node bundles and prepared snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.transcript.model_input_v2_types import (
    ModelInputJsonChunkNode,
    ModelInputJsonValueNode,
    ModelInputMappingEntry,
    ModelInputMappingRootNode,
    ModelInputNode,
    ModelInputNodeBundle,
    ModelInputNodeKind,
    ModelInputNodeReference,
    ModelInputSequenceTailNode,
    ModelInputSnapshotV2,
    model_input_node_to_json,
)


def encode_model_input_node_bundle(payload: object) -> JSONValue:
    if not isinstance(payload, ModelInputNodeBundle):
        raise TypeError("payload must be ModelInputNodeBundle")
    return {
        "schemaVersion": payload.schema_version,
        "nodes": [model_input_node_to_json(node) for node in payload.nodes],
    }


def decode_model_input_node_bundle(value: JSONValue) -> ModelInputNodeBundle:
    payload = _object(
        value,
        name="Model Input v2 node bundle",
        fields={"schemaVersion", "nodes"},
    )
    raw_nodes = _field(payload, "nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise TypeError("Model Input v2 node bundle nodes must be a non-empty array")
    return ModelInputNodeBundle(
        schema_version=_positive_int(payload, "schemaVersion"),
        nodes=tuple(_decode_node(item) for item in raw_nodes),
    )


def encode_model_input_snapshot_v2(payload: object) -> JSONValue:
    if not isinstance(payload, ModelInputSnapshotV2):
        raise TypeError("payload must be ModelInputSnapshotV2")
    return {
        "schemaVersion": payload.schema_version,
        "projectionVersion": payload.projection_version,
        "snapshotId": payload.snapshot_id,
        "invocationId": payload.invocation_id,
        "attempt": payload.attempt,
        "purpose": payload.purpose,
        "productId": payload.product_id,
        "runtimeId": payload.runtime_id,
        "mountGeneration": payload.mount_generation,
        "profileFingerprint": payload.profile_fingerprint,
        "registrationRevision": payload.registration_revision,
        "conversationId": payload.conversation_id,
        "sourceLeafId": payload.source_leaf_id,
        "sourceRevision": payload.source_revision,
        "commitRevision": payload.commit_revision,
        "providerId": payload.provider_id,
        "modelId": payload.model_id,
        "apiId": payload.api_id,
        "endpointId": payload.endpoint_id,
        "logicalRoot": _encode_reference(payload.logical_root),
        "preparedPayloadRoot": _encode_reference(payload.prepared_payload_root),
        "modelVisibleHeadersRoot": _encode_reference(
            payload.model_visible_headers_root
        ),
        "logicalInputHash": payload.logical_input_hash,
        "preparedPayloadHash": payload.prepared_payload_hash,
        "outcome": payload.outcome,
    }


def decode_model_input_snapshot_v2(value: JSONValue) -> ModelInputSnapshotV2:
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
        "logicalRoot",
        "preparedPayloadRoot",
        "modelVisibleHeadersRoot",
        "logicalInputHash",
        "preparedPayloadHash",
        "outcome",
    }
    payload = _object(value, name="Model Input v2 snapshot", fields=fields)
    outcome = _text(payload, "outcome")
    if outcome != "prepared":
        raise ValueError("Model Input v2 snapshot outcome is invalid")
    return ModelInputSnapshotV2(
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
        source_revision=_positive_int(payload, "sourceRevision"),
        commit_revision=_positive_int(payload, "commitRevision"),
        provider_id=_text(payload, "providerId"),
        model_id=_text(payload, "modelId"),
        api_id=_text(payload, "apiId"),
        endpoint_id=_text(payload, "endpointId"),
        logical_root=_decode_reference(_field(payload, "logicalRoot")),
        prepared_payload_root=_decode_reference(_field(payload, "preparedPayloadRoot")),
        model_visible_headers_root=_decode_reference(
            _field(payload, "modelVisibleHeadersRoot")
        ),
        logical_input_hash=_text(payload, "logicalInputHash"),
        prepared_payload_hash=_text(payload, "preparedPayloadHash"),
        outcome=cast(Literal["prepared"], outcome),
    )


def _decode_node(value: object) -> ModelInputNode:
    raw = require_json_mapping(value, name="Model Input v2 node")
    node_kind = raw.get("nodeKind")
    if node_kind == "json_chunk":
        payload = _object(
            raw,
            name="Model Input JSON chunk node",
            fields={"nodeKind", "contentHash", "text"},
        )
        return ModelInputJsonChunkNode(
            content_hash=_text(payload, "contentHash"),
            text=_string(payload, "text"),
        )
    if node_kind == "json_value":
        payload = _object(
            raw,
            name="Model Input JSON value node",
            fields={
                "nodeKind",
                "contentHash",
                "valueHash",
                "decodedBytes",
                "inlineJson",
                "chunks",
            },
        )
        return ModelInputJsonValueNode(
            content_hash=_text(payload, "contentHash"),
            value_hash=_text(payload, "valueHash"),
            decoded_bytes=_positive_int(payload, "decodedBytes"),
            inline_json=_optional_string(payload, "inlineJson"),
            chunk_refs=_decode_references(payload, "chunks"),
        )
    if node_kind == "sequence_tail":
        payload = _object(
            raw,
            name="Model Input sequence tail node",
            fields={
                "nodeKind",
                "contentHash",
                "algorithmVersion",
                "previousTail",
                "appendedItems",
                "totalItemCount",
                "sequenceHash",
            },
        )
        previous = _field(payload, "previousTail")
        return ModelInputSequenceTailNode(
            content_hash=_text(payload, "contentHash"),
            algorithm_version=_positive_int(payload, "algorithmVersion"),
            previous_tail=(None if previous is None else _decode_reference(previous)),
            appended_items=_decode_references(payload, "appendedItems"),
            total_item_count=_non_negative_int(payload, "totalItemCount"),
            sequence_hash=_text(payload, "sequenceHash"),
        )
    if node_kind == "mapping_root":
        payload = _object(
            raw,
            name="Model Input mapping root node",
            fields={
                "nodeKind",
                "contentHash",
                "mappingHash",
                "entries",
            },
        )
        raw_entries = _field(payload, "entries")
        if not isinstance(raw_entries, list):
            raise TypeError("Model Input mapping root entries must be an array")
        return ModelInputMappingRootNode(
            content_hash=_text(payload, "contentHash"),
            mapping_hash=_text(payload, "mappingHash"),
            entries=tuple(_decode_mapping_entry(item) for item in raw_entries),
        )
    raise ValueError(f"unsupported Model Input v2 node kind: {node_kind!r}")


def _encode_reference(reference: ModelInputNodeReference) -> dict[str, JSONValue]:
    return {
        "recordId": reference.record_id,
        "ordinal": reference.ordinal,
        "nodeKind": reference.node_kind,
        "contentHash": reference.content_hash,
    }


def _decode_references(
    value: Mapping[str, JSONValue],
    key: str,
) -> tuple[ModelInputNodeReference, ...]:
    raw = _field(value, key)
    if not isinstance(raw, list):
        raise TypeError(f"Model Input field {key!r} must be an array")
    return tuple(_decode_reference(item) for item in raw)


def _decode_reference(value: object) -> ModelInputNodeReference:
    payload = _object(
        value,
        name="Model Input v2 node reference",
        fields={"recordId", "ordinal", "nodeKind", "contentHash"},
    )
    return ModelInputNodeReference(
        record_id=_text(payload, "recordId"),
        ordinal=_non_negative_int(payload, "ordinal"),
        node_kind=cast(ModelInputNodeKind, _text(payload, "nodeKind")),
        content_hash=_text(payload, "contentHash"),
    )


def _decode_mapping_entry(value: object) -> ModelInputMappingEntry:
    payload = _object(
        value,
        name="Model Input mapping entry",
        fields={"name", "value"},
    )
    return ModelInputMappingEntry(
        name=_text(payload, "name"),
        value=_decode_reference(_field(payload, "value")),
    )


def _object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, JSONValue]:
    payload = require_json_mapping(value, name=name)
    unexpected = set(payload).difference(fields)
    if unexpected:
        raise ValueError(
            f"{name} contains unknown fields: {', '.join(sorted(unexpected))}"
        )
    missing = fields.difference(payload)
    if missing:
        raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing))}")
    return payload


def _field(value: Mapping[str, JSONValue], key: str) -> JSONValue:
    try:
        return value[key]
    except KeyError as exc:
        raise ValueError(f"Model Input payload is missing {key!r}") from exc


def _text(value: Mapping[str, JSONValue], key: str) -> str:
    field = _field(value, key)
    if not isinstance(field, str) or not field.strip():
        raise TypeError(f"Model Input field {key!r} must be non-empty text")
    return field


def _string(value: Mapping[str, JSONValue], key: str) -> str:
    field = _field(value, key)
    if not isinstance(field, str):
        raise TypeError(f"Model Input field {key!r} must be text")
    return field


def _optional_string(value: Mapping[str, JSONValue], key: str) -> str | None:
    field = _field(value, key)
    if field is None or isinstance(field, str):
        return field
    raise TypeError(f"Model Input field {key!r} must be text or null")


def _positive_int(value: Mapping[str, JSONValue], key: str) -> int:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int) or field < 1:
        raise TypeError(f"Model Input field {key!r} must be a positive integer")
    return field


def _non_negative_int(value: Mapping[str, JSONValue], key: str) -> int:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int) or field < 0:
        raise TypeError(f"Model Input field {key!r} must be non-negative")
    return field


__all__ = [
    "decode_model_input_node_bundle",
    "decode_model_input_snapshot_v2",
    "encode_model_input_node_bundle",
    "encode_model_input_snapshot_v2",
]
