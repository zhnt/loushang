"""Typed, content-addressed Model Input v2 persistence facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias, cast

from loushang.foundation.json import JSONValue, validate_json_value
from loushang.harness.transcript.model_input_types import (
    canonical_model_input_json,
    freeze_model_input_json,
    hash_model_input_json,
)

MODEL_INPUT_V2_PAYLOAD_VERSION = 2
MODEL_INPUT_V2_SCHEMA_VERSION = 2
MODEL_INPUT_V2_PROJECTION_VERSION = "harness.model-input.v2"
MODEL_INPUT_V2_SEQUENCE_ALGORITHM_VERSION = 1
MODEL_INPUT_V2_CHUNK_CHARACTERS = 48 * 1024
MODEL_INPUT_V2_BUNDLE_TARGET_BYTES = 700 * 1024

ModelInputNodeKind: TypeAlias = Literal[
    "json_chunk",
    "json_value",
    "sequence_tail",
    "mapping_root",
]
ModelInputV2Outcome: TypeAlias = Literal["prepared"]


@dataclass(frozen=True)
class ModelInputNodeReference:
    record_id: str
    ordinal: int
    node_kind: ModelInputNodeKind
    content_hash: str

    def __post_init__(self) -> None:
        _require_text(self.record_id, name="Model Input node record id")
        _require_non_negative_int(self.ordinal, name="Model Input node ordinal")
        _require_node_kind(self.node_kind)
        _require_sha256(self.content_hash, name="Model Input node content hash")


@dataclass(frozen=True)
class ModelInputJsonChunkNode:
    content_hash: str
    text: str = field(repr=False)
    node_kind: Literal["json_chunk"] = field(default="json_chunk", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("Model Input JSON chunk text must be non-empty")
        _require_matching_node_hash(self)


@dataclass(frozen=True)
class ModelInputJsonValueNode:
    content_hash: str
    value_hash: str
    decoded_bytes: int
    inline_json: str | None = field(default=None, repr=False)
    chunk_refs: tuple[ModelInputNodeReference, ...] = ()
    node_kind: Literal["json_value"] = field(default="json_value", init=False)

    def __post_init__(self) -> None:
        _require_sha256(self.value_hash, name="Model Input JSON value hash")
        _require_positive_int(
            self.decoded_bytes,
            name="Model Input JSON value decoded bytes",
        )
        chunks = _require_references(
            self.chunk_refs,
            name="Model Input JSON value chunks",
            node_kind="json_chunk",
        )
        if (self.inline_json is None) == (not chunks):
            raise ValueError(
                "Model Input JSON value must use exactly one inline or chunked form"
            )
        if self.inline_json is not None:
            if not isinstance(self.inline_json, str) or not self.inline_json:
                raise ValueError("Model Input inline JSON must be non-empty")
            encoded = self.inline_json.encode("utf-8")
            if len(encoded) != self.decoded_bytes:
                raise ValueError("Model Input inline JSON byte count changed")
            try:
                decoded = json.loads(self.inline_json)
                validate_json_value(
                    decoded,
                    name="Model Input inline JSON",
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError("Model Input inline JSON is invalid") from exc
            canonical = canonical_model_input_json(
                decoded,
                name="Model Input inline JSON",
            )
            if canonical != self.inline_json:
                raise ValueError("Model Input inline JSON is not canonical")
            if _hash_canonical_json(canonical) != self.value_hash:
                raise ValueError("Model Input inline JSON value hash changed")
        object.__setattr__(self, "chunk_refs", chunks)
        _require_matching_node_hash(self)


@dataclass(frozen=True)
class ModelInputSequenceTailNode:
    content_hash: str
    previous_tail: ModelInputNodeReference | None
    appended_items: tuple[ModelInputNodeReference, ...]
    total_item_count: int
    sequence_hash: str
    algorithm_version: int = MODEL_INPUT_V2_SEQUENCE_ALGORITHM_VERSION
    node_kind: Literal["sequence_tail"] = field(
        default="sequence_tail",
        init=False,
    )

    def __post_init__(self) -> None:
        if self.algorithm_version != MODEL_INPUT_V2_SEQUENCE_ALGORITHM_VERSION:
            raise ValueError(
                "unsupported Model Input sequence algorithm version: "
                f"{self.algorithm_version}"
            )
        if self.previous_tail is not None and (
            not isinstance(self.previous_tail, ModelInputNodeReference)
            or self.previous_tail.node_kind != "sequence_tail"
        ):
            raise TypeError("Model Input previous tail must reference a sequence tail")
        items = _require_references(
            self.appended_items,
            name="Model Input appended sequence items",
            node_kind="json_value",
        )
        _require_non_negative_int(
            self.total_item_count,
            name="Model Input sequence item count",
        )
        _require_sha256(self.sequence_hash, name="Model Input sequence hash")
        if self.previous_tail is None:
            if self.total_item_count != len(items):
                raise ValueError("Model Input root tail item count is inconsistent")
            if not items and self.sequence_hash != model_input_empty_sequence_hash():
                raise ValueError("Model Input empty sequence hash changed")
        elif not items:
            raise ValueError("Model Input incremental sequence tail must append items")
        object.__setattr__(self, "appended_items", items)
        _require_matching_node_hash(self)


@dataclass(frozen=True)
class ModelInputMappingEntry:
    name: str
    value: ModelInputNodeReference

    def __post_init__(self) -> None:
        _require_text(self.name, name="Model Input mapping entry name")
        if not isinstance(self.value, ModelInputNodeReference):
            raise TypeError("Model Input mapping entry must use a node reference")
        if self.value.node_kind not in {"json_value", "sequence_tail"}:
            raise ValueError(
                "Model Input mapping values must reference JSON values or sequences"
            )


@dataclass(frozen=True)
class ModelInputMappingRootNode:
    content_hash: str
    mapping_hash: str
    entries: tuple[ModelInputMappingEntry, ...]
    node_kind: Literal["mapping_root"] = field(
        default="mapping_root",
        init=False,
    )

    def __post_init__(self) -> None:
        _require_sha256(self.mapping_hash, name="Model Input mapping hash")
        if not isinstance(self.entries, tuple | list) or any(
            not isinstance(item, ModelInputMappingEntry) for item in self.entries
        ):
            raise TypeError("Model Input mapping entries are invalid")
        entries = tuple(cast(Sequence[ModelInputMappingEntry], self.entries))
        names = tuple(entry.name for entry in entries)
        if len(names) != len(set(names)):
            raise ValueError("Model Input mapping entry names must be unique")
        object.__setattr__(self, "entries", entries)
        _require_matching_node_hash(self)


ModelInputNode: TypeAlias = (
    ModelInputJsonChunkNode
    | ModelInputJsonValueNode
    | ModelInputSequenceTailNode
    | ModelInputMappingRootNode
)


@dataclass(frozen=True)
class ModelInputNodeBundle:
    nodes: tuple[ModelInputNode, ...]
    schema_version: int = MODEL_INPUT_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_v2_schema(self.schema_version)
        if not isinstance(self.nodes, tuple | list) or not self.nodes:
            raise ValueError("Model Input node bundle must contain nodes")
        nodes = tuple(cast(Sequence[ModelInputNode], self.nodes))
        if any(not isinstance(node, _MODEL_INPUT_NODE_TYPES) for node in nodes):
            raise TypeError("Model Input node bundle contains an invalid node")
        identities = tuple((node.node_kind, node.content_hash) for node in nodes)
        if len(identities) != len(set(identities)):
            raise ValueError("Model Input node bundle identities must be unique")
        object.__setattr__(self, "nodes", nodes)


@dataclass(frozen=True)
class DeferredModelInputSequenceLink:
    """Runtime-only sequence links projected from a verified authority line."""

    previous_tail: ModelInputNodeReference | None
    appended_items: tuple[ModelInputNodeReference, ...]
    total_item_count: int
    sequence_hash: str

    def __post_init__(self) -> None:
        if (
            self.previous_tail is not None
            and self.previous_tail.node_kind != "sequence_tail"
        ):
            raise TypeError("deferred previous tail must reference a sequence tail")
        items = _require_references(
            self.appended_items,
            name="deferred Model Input appended sequence items",
            node_kind="json_value",
        )
        _require_non_negative_int(
            self.total_item_count,
            name="deferred Model Input sequence item count",
        )
        _require_sha256(
            self.sequence_hash,
            name="deferred Model Input sequence hash",
        )
        if self.previous_tail is None and self.total_item_count != len(items):
            raise ValueError("deferred Model Input root tail count is inconsistent")
        if self.previous_tail is not None and not items:
            raise ValueError("deferred incremental sequence tail must append items")
        object.__setattr__(self, "appended_items", items)


@dataclass(frozen=True)
class DeferredModelInputNode:
    """Validated node identity retained by the disposable transcript index."""

    ordinal: int
    node_kind: ModelInputNodeKind
    content_hash: str
    value_hash: str | None = None
    inline_json: str | None = None
    total_item_count: int | None = None
    sequence_hash: str | None = None
    value_hash_verified: bool = False

    def __post_init__(self) -> None:
        _require_non_negative_int(
            self.ordinal,
            name="deferred Model Input node ordinal",
        )
        _require_node_kind(self.node_kind)
        _require_sha256(self.content_hash, name="deferred Model Input node hash")
        if self.value_hash is not None:
            _require_sha256(self.value_hash, name="deferred Model Input value hash")
        if self.inline_json is not None and not isinstance(self.inline_json, str):
            raise TypeError("deferred Model Input inline JSON must be text")
        if self.total_item_count is not None:
            _require_non_negative_int(
                self.total_item_count,
                name="deferred Model Input sequence item count",
            )
        if self.sequence_hash is not None:
            _require_sha256(
                self.sequence_hash,
                name="deferred Model Input sequence hash",
            )
        if not isinstance(self.value_hash_verified, bool):
            raise TypeError("deferred Model Input value verification must be boolean")
        if self.value_hash_verified and self.node_kind != "json_value":
            raise ValueError(
                "only deferred Model Input JSON values can have verified hashes"
            )


class DeferredModelInputNodeSource(Protocol):
    """Resolve node bodies after an authority-bound index has been verified."""

    def load_bundle_nodes(self, record_id: str) -> tuple[ModelInputNode, ...]: ...

    def load_sequence_link(
        self,
        record_id: str,
        ordinal: int,
    ) -> DeferredModelInputSequenceLink: ...


class DeferredModelInputNodeBundle(ModelInputNodeBundle):
    """A node bundle expanded only when replay actually dereferences it.

    It remains a ``ModelInputNodeBundle`` so transcript semantics and wire
    encoders keep one stable payload contract. Construction is restricted to
    an authority-bound, already validated transcript index.
    """

    __slots__ = ("_record_id", "_source", "_indexed_nodes")

    _record_id: str
    _source: DeferredModelInputNodeSource
    _indexed_nodes: tuple[DeferredModelInputNode, ...]

    def __init__(
        self,
        *,
        record_id: str,
        source: DeferredModelInputNodeSource,
        indexed_nodes: Sequence[DeferredModelInputNode],
        schema_version: int = MODEL_INPUT_V2_SCHEMA_VERSION,
    ) -> None:
        _require_text(record_id, name="deferred Model Input bundle record id")
        _require_v2_schema(schema_version)
        durable_index = tuple(indexed_nodes)
        if not durable_index:
            raise ValueError("deferred Model Input bundle must contain indexed nodes")
        if tuple(item.ordinal for item in durable_index) != tuple(
            range(len(durable_index))
        ):
            raise ValueError("deferred Model Input node ordinals must be contiguous")
        object.__setattr__(self, "_record_id", record_id)
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "_indexed_nodes", durable_index)
        object.__setattr__(self, "schema_version", schema_version)

    @property
    def nodes(self) -> tuple[ModelInputNode, ...]:
        nodes = self._source.load_bundle_nodes(self._record_id)
        if len(nodes) != len(self._indexed_nodes):
            raise ValueError("deferred Model Input bundle node count changed")
        return nodes

    @property
    def indexed_nodes(self) -> tuple[DeferredModelInputNode, ...]:
        return self._indexed_nodes

    def node_at(self, ordinal: int) -> ModelInputNode:
        _require_non_negative_int(ordinal, name="Model Input node ordinal")
        if ordinal >= len(self._indexed_nodes):
            raise IndexError("Model Input node ordinal is outside the bundle")
        return self.nodes[ordinal]

    def sequence_link_at(self, ordinal: int) -> DeferredModelInputSequenceLink:
        _require_non_negative_int(ordinal, name="Model Input sequence ordinal")
        if ordinal >= len(self._indexed_nodes):
            raise IndexError("Model Input sequence ordinal is outside the bundle")
        return self._source.load_sequence_link(self._record_id, ordinal)

    def __repr__(self) -> str:
        return (
            "DeferredModelInputNodeBundle("
            f"record_id={self._record_id!r}, node_count={len(self._indexed_nodes)}, "
            f"schema_version={self.schema_version})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModelInputNodeBundle):
            return NotImplemented
        return self.schema_version == other.schema_version and self.nodes == other.nodes


@dataclass(frozen=True)
class ModelInputSnapshotV2:
    snapshot_id: str
    invocation_id: str
    attempt: int
    purpose: str
    product_id: str
    runtime_id: str
    mount_generation: int
    profile_fingerprint: str
    registration_revision: str
    conversation_id: str
    source_leaf_id: str
    source_revision: int
    commit_revision: int
    provider_id: str
    model_id: str
    api_id: str
    endpoint_id: str
    logical_root: ModelInputNodeReference
    prepared_payload_root: ModelInputNodeReference
    model_visible_headers_root: ModelInputNodeReference
    logical_input_hash: str
    prepared_payload_hash: str
    schema_version: int = MODEL_INPUT_V2_SCHEMA_VERSION
    projection_version: str = MODEL_INPUT_V2_PROJECTION_VERSION
    outcome: ModelInputV2Outcome = "prepared"
    binary_projection_version: int = 0

    def __post_init__(self) -> None:
        _require_v2_schema(self.schema_version)
        _require_non_negative_int(
            self.binary_projection_version,
            name="ModelInputSnapshotV2.binary_projection_version",
        )
        if self.binary_projection_version not in {0, 1}:
            raise ValueError(
                "unsupported Model Input binary projection version: "
                f"{self.binary_projection_version}"
            )
        if self.projection_version != MODEL_INPUT_V2_PROJECTION_VERSION:
            raise ValueError(
                "unsupported Model Input v2 projection version: "
                f"{self.projection_version}"
            )
        for attribute in (
            "snapshot_id",
            "invocation_id",
            "purpose",
            "product_id",
            "runtime_id",
            "profile_fingerprint",
            "registration_revision",
            "conversation_id",
            "source_leaf_id",
            "provider_id",
            "model_id",
            "api_id",
            "endpoint_id",
        ):
            _require_text(
                getattr(self, attribute),
                name=f"ModelInputSnapshotV2.{attribute}",
            )
        _require_positive_int(self.attempt, name="ModelInputSnapshotV2.attempt")
        _require_non_negative_int(
            self.mount_generation,
            name="ModelInputSnapshotV2.mount_generation",
        )
        _require_positive_int(
            self.source_revision,
            name="ModelInputSnapshotV2.source_revision",
        )
        _require_positive_int(
            self.commit_revision,
            name="ModelInputSnapshotV2.commit_revision",
        )
        if self.source_revision >= self.commit_revision:
            raise ValueError(
                "ModelInputSnapshotV2 source revision must precede commit revision"
            )
        _require_sha256(
            self.profile_fingerprint,
            name="ModelInputSnapshotV2.profile_fingerprint",
        )
        _require_sha256(
            self.registration_revision,
            name="ModelInputSnapshotV2.registration_revision",
        )
        _require_sha256(
            self.logical_input_hash,
            name="ModelInputSnapshotV2.logical_input_hash",
        )
        _require_sha256(
            self.prepared_payload_hash,
            name="ModelInputSnapshotV2.prepared_payload_hash",
        )
        _require_reference_kind(
            self.logical_root,
            "mapping_root",
            name="Model Input logical root",
        )
        _require_reference_kind(
            self.prepared_payload_root,
            "mapping_root",
            name="Model Input prepared payload root",
        )
        _require_reference_kind(
            self.model_visible_headers_root,
            "json_value",
            name="Model Input model-visible headers root",
        )
        if self.outcome != "prepared":
            raise ValueError("Model Input v2 snapshot outcome must be 'prepared'")


_MODEL_INPUT_NODE_TYPES = (
    ModelInputJsonChunkNode,
    ModelInputJsonValueNode,
    ModelInputSequenceTailNode,
    ModelInputMappingRootNode,
)


def create_model_input_json_chunk(text: str) -> ModelInputJsonChunkNode:
    return ModelInputJsonChunkNode(
        content_hash=_hash_node_basis(_json_chunk_hash_basis(text)),
        text=text,
    )


def create_model_input_json_value(
    value: object,
    *,
    chunk_refs: Sequence[ModelInputNodeReference] = (),
) -> ModelInputJsonValueNode:
    frozen = freeze_model_input_json(value, name="Model Input v2 JSON value")
    canonical = canonical_model_input_json(frozen, name="Model Input v2 JSON value")
    refs = tuple(chunk_refs)
    value_hash = hash_model_input_json(frozen, name="Model Input v2 JSON value")
    decoded_bytes = len(canonical.encode("utf-8"))
    inline_json = None if refs else canonical
    return ModelInputJsonValueNode(
        content_hash=_hash_node_basis(
            _json_value_hash_basis(
                value_hash=value_hash,
                decoded_bytes=decoded_bytes,
                inline_json=inline_json,
                chunk_refs=refs,
            )
        ),
        value_hash=value_hash,
        decoded_bytes=decoded_bytes,
        inline_json=inline_json,
        chunk_refs=refs,
    )


def create_model_input_sequence_tail(
    *,
    previous_tail: ModelInputNodeReference | None,
    appended_items: Sequence[ModelInputNodeReference],
    total_item_count: int,
    sequence_hash: str,
) -> ModelInputSequenceTailNode:
    items = tuple(appended_items)
    return ModelInputSequenceTailNode(
        content_hash=_hash_node_basis(
            _sequence_tail_hash_basis(
                previous_tail=previous_tail,
                appended_items=items,
                total_item_count=total_item_count,
                sequence_hash=sequence_hash,
                algorithm_version=MODEL_INPUT_V2_SEQUENCE_ALGORITHM_VERSION,
            )
        ),
        previous_tail=previous_tail,
        appended_items=items,
        total_item_count=total_item_count,
        sequence_hash=sequence_hash,
    )


def create_model_input_mapping_root(
    value: Mapping[str, object],
    entries: Sequence[ModelInputMappingEntry],
) -> ModelInputMappingRootNode:
    frozen = freeze_model_input_json(value, name="Model Input v2 mapping root")
    if not isinstance(frozen, Mapping):
        raise TypeError("Model Input v2 mapping root must be an object")
    mapping_hash = hash_model_input_json(frozen, name="Model Input v2 mapping root")
    return create_model_input_mapping_root_from_hash(
        mapping_hash=mapping_hash,
        entries=entries,
    )


def create_model_input_mapping_root_from_hash(
    *,
    mapping_hash: str,
    entries: Sequence[ModelInputMappingEntry],
) -> ModelInputMappingRootNode:
    """Create a root from a hash already proven by a streaming planner."""

    _require_sha256(mapping_hash, name="Model Input v2 mapping root hash")
    resolved_entries = tuple(entries)
    return ModelInputMappingRootNode(
        content_hash=_hash_node_basis(
            _mapping_root_hash_basis(
                mapping_hash=mapping_hash,
                entries=resolved_entries,
            )
        ),
        mapping_hash=mapping_hash,
        entries=resolved_entries,
    )


def hash_model_input_node(node: object) -> str:
    return _hash_node_basis(model_input_node_hash_basis(node))


def model_input_node_hash_basis(node: object) -> dict[str, JSONValue]:
    if isinstance(node, ModelInputJsonChunkNode):
        return _json_chunk_hash_basis(node.text)
    if isinstance(node, ModelInputJsonValueNode):
        return _json_value_hash_basis(
            value_hash=node.value_hash,
            decoded_bytes=node.decoded_bytes,
            inline_json=node.inline_json,
            chunk_refs=node.chunk_refs,
        )
    if isinstance(node, ModelInputSequenceTailNode):
        return _sequence_tail_hash_basis(
            previous_tail=node.previous_tail,
            appended_items=node.appended_items,
            total_item_count=node.total_item_count,
            sequence_hash=node.sequence_hash,
            algorithm_version=node.algorithm_version,
        )
    if isinstance(node, ModelInputMappingRootNode):
        return _mapping_root_hash_basis(
            mapping_hash=node.mapping_hash,
            entries=node.entries,
        )
    raise TypeError("unsupported Model Input v2 node")


def model_input_empty_sequence_hash() -> str:
    return _sequence_link_hash("harness.model-input.sequence.v2:empty", None)


def extend_model_input_sequence_hash(
    previous_hash: str,
    item_value_hash: str,
) -> str:
    _require_sha256(previous_hash, name="Model Input previous sequence hash")
    _require_sha256(item_value_hash, name="Model Input sequence item hash")
    return _sequence_link_hash(previous_hash, item_value_hash)


def split_model_input_canonical_json(canonical: str) -> tuple[str, ...]:
    if not isinstance(canonical, str) or not canonical:
        raise ValueError("Model Input canonical JSON must be non-empty")
    chunks: list[str] = []
    buffered = ""

    def append_buffered(fragment: str) -> None:
        nonlocal buffered
        while fragment:
            remaining = MODEL_INPUT_V2_CHUNK_CHARACTERS - len(buffered)
            buffered += fragment[:remaining]
            fragment = fragment[remaining:]
            if len(buffered) == MODEL_INPUT_V2_CHUNK_CHARACTERS:
                chunks.append(buffered)
                buffered = ""

    cursor = 0
    for start, end in _canonical_json_string_ranges(canonical):
        if end - start <= MODEL_INPUT_V2_CHUNK_CHARACTERS:
            continue
        append_buffered(canonical[cursor:start])
        if buffered:
            chunks.append(buffered)
            buffered = ""
        token = canonical[start:end]
        chunks.extend(
            token[index : index + MODEL_INPUT_V2_CHUNK_CHARACTERS]
            for index in range(0, len(token), MODEL_INPUT_V2_CHUNK_CHARACTERS)
        )
        cursor = end
    append_buffered(canonical[cursor:])
    if buffered:
        chunks.append(buffered)
    return tuple(chunks)


def _canonical_json_string_ranges(canonical: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(canonical):
        if canonical[index] != '"':
            index += 1
            continue
        start = index
        index += 1
        escaped = False
        while index < len(canonical):
            character = canonical[index]
            index += 1
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                ranges.append((start, index))
                break
        else:
            raise ValueError("Model Input canonical JSON contains an open string")
    return tuple(ranges)


def estimate_model_input_node_wire_bytes(node: ModelInputNode) -> int:
    payload = model_input_node_to_json(node)
    return len(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def model_input_node_to_json(node: ModelInputNode) -> dict[str, JSONValue]:
    if isinstance(node, ModelInputJsonChunkNode):
        return {
            "nodeKind": node.node_kind,
            "contentHash": node.content_hash,
            "text": node.text,
        }
    if isinstance(node, ModelInputJsonValueNode):
        return {
            "nodeKind": node.node_kind,
            "contentHash": node.content_hash,
            "valueHash": node.value_hash,
            "decodedBytes": node.decoded_bytes,
            "inlineJson": node.inline_json,
            "chunks": [_reference_to_json(item) for item in node.chunk_refs],
        }
    if isinstance(node, ModelInputSequenceTailNode):
        return {
            "nodeKind": node.node_kind,
            "contentHash": node.content_hash,
            "algorithmVersion": node.algorithm_version,
            "previousTail": (
                _reference_to_json(node.previous_tail)
                if node.previous_tail is not None
                else None
            ),
            "appendedItems": [_reference_to_json(item) for item in node.appended_items],
            "totalItemCount": node.total_item_count,
            "sequenceHash": node.sequence_hash,
        }
    if isinstance(node, ModelInputMappingRootNode):
        return {
            "nodeKind": node.node_kind,
            "contentHash": node.content_hash,
            "mappingHash": node.mapping_hash,
            "entries": [
                {"name": entry.name, "value": _reference_to_json(entry.value)}
                for entry in node.entries
            ],
        }
    raise TypeError("unsupported Model Input v2 node")


def _hash_node_basis(basis: Mapping[str, JSONValue]) -> str:
    # Node hash bases are assembled here from already validated exact JSON
    # primitives.  The C encoder is byte-identical to the general canonical
    # encoder for that closed algebra and avoids recursively rebuilding large
    # reference trees in Python during load and index verification.
    canonical = json.dumps(
        basis,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return _hash_canonical_json(canonical)


def _hash_canonical_json(canonical: str) -> str:
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_chunk_hash_basis(text: str) -> dict[str, JSONValue]:
    return {
        "domain": "harness.model-input.node.v2",
        "nodeKind": "json_chunk",
        "text": text,
    }


def _json_value_hash_basis(
    *,
    value_hash: str,
    decoded_bytes: int,
    inline_json: str | None,
    chunk_refs: Sequence[ModelInputNodeReference],
) -> dict[str, JSONValue]:
    return {
        "domain": "harness.model-input.node.v2",
        "nodeKind": "json_value",
        "valueHash": value_hash,
        "decodedBytes": decoded_bytes,
        "inlineJson": inline_json,
        "chunks": [_reference_hash_basis(item) for item in chunk_refs],
    }


def _sequence_tail_hash_basis(
    *,
    previous_tail: ModelInputNodeReference | None,
    appended_items: Sequence[ModelInputNodeReference],
    total_item_count: int,
    sequence_hash: str,
    algorithm_version: int,
) -> dict[str, JSONValue]:
    return {
        "domain": "harness.model-input.node.v2",
        "nodeKind": "sequence_tail",
        "algorithmVersion": algorithm_version,
        "previousTail": (
            _reference_hash_basis(previous_tail) if previous_tail is not None else None
        ),
        "appendedItems": [_reference_hash_basis(item) for item in appended_items],
        "totalItemCount": total_item_count,
        "sequenceHash": sequence_hash,
    }


def _mapping_root_hash_basis(
    *,
    mapping_hash: str,
    entries: Sequence[ModelInputMappingEntry],
) -> dict[str, JSONValue]:
    return {
        "domain": "harness.model-input.node.v2",
        "nodeKind": "mapping_root",
        "mappingHash": mapping_hash,
        "entries": [
            {"name": entry.name, "value": _reference_hash_basis(entry.value)}
            for entry in entries
        ],
    }


def _reference_hash_basis(
    reference: ModelInputNodeReference,
) -> dict[str, JSONValue]:
    return {
        "nodeKind": reference.node_kind,
        "contentHash": reference.content_hash,
    }


def _reference_to_json(
    reference: ModelInputNodeReference,
) -> dict[str, JSONValue]:
    return {
        "recordId": reference.record_id,
        "ordinal": reference.ordinal,
        "nodeKind": reference.node_kind,
        "contentHash": reference.content_hash,
    }


def _sequence_link_hash(previous: str, item: str | None) -> str:
    return _hash_node_basis(
        {
            "domain": "harness.model-input.sequence-link.v2",
            "previous": previous,
            "item": item,
        }
    )


def _require_matching_node_hash(node: ModelInputNode) -> None:
    _require_sha256(node.content_hash, name="Model Input node content hash")
    if hash_model_input_node(node) != node.content_hash:
        raise ValueError("Model Input node hash does not match its content")


def _require_references(
    value: object,
    *,
    name: str,
    node_kind: ModelInputNodeKind,
) -> tuple[ModelInputNodeReference, ...]:
    if not isinstance(value, tuple | list) or any(
        not isinstance(item, ModelInputNodeReference) for item in value
    ):
        raise TypeError(f"{name} must contain ModelInputNodeReference values")
    references = tuple(cast(Sequence[ModelInputNodeReference], value))
    if any(item.node_kind != node_kind for item in references):
        raise ValueError(f"{name} must reference {node_kind} nodes")
    return references


def _require_reference_kind(
    value: object,
    expected: ModelInputNodeKind,
    *,
    name: str,
) -> ModelInputNodeReference:
    if not isinstance(value, ModelInputNodeReference):
        raise TypeError(f"{name} must use a ModelInputNodeReference")
    if value.node_kind != expected:
        raise ValueError(f"{name} must reference a {expected} node")
    return value


def _require_v2_schema(value: object) -> None:
    if value != MODEL_INPUT_V2_SCHEMA_VERSION:
        raise ValueError(f"unsupported Model Input v2 schema version: {value}")


def _require_node_kind(value: object) -> ModelInputNodeKind:
    if value not in {"json_chunk", "json_value", "sequence_tail", "mapping_root"}:
        raise ValueError(f"unsupported Model Input node kind: {value!r}")
    return cast(ModelInputNodeKind, value)


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _require_positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_sha256(value: object, *, name: str) -> str:
    text = _require_text(value, name=name)
    digest = text.removeprefix("sha256:")
    if len(digest) != 64 or digest.strip("0123456789abcdef"):
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint")
    return text


__all__ = [
    "MODEL_INPUT_V2_BUNDLE_TARGET_BYTES",
    "MODEL_INPUT_V2_CHUNK_CHARACTERS",
    "MODEL_INPUT_V2_PAYLOAD_VERSION",
    "MODEL_INPUT_V2_PROJECTION_VERSION",
    "MODEL_INPUT_V2_SCHEMA_VERSION",
    "MODEL_INPUT_V2_SEQUENCE_ALGORITHM_VERSION",
    "DeferredModelInputNode",
    "DeferredModelInputNodeBundle",
    "DeferredModelInputNodeSource",
    "DeferredModelInputSequenceLink",
    "ModelInputJsonChunkNode",
    "ModelInputJsonValueNode",
    "ModelInputMappingEntry",
    "ModelInputMappingRootNode",
    "ModelInputNode",
    "ModelInputNodeBundle",
    "ModelInputNodeKind",
    "ModelInputNodeReference",
    "ModelInputSequenceTailNode",
    "ModelInputSnapshotV2",
    "ModelInputV2Outcome",
    "create_model_input_json_chunk",
    "create_model_input_json_value",
    "create_model_input_mapping_root",
    "create_model_input_mapping_root_from_hash",
    "create_model_input_sequence_tail",
    "estimate_model_input_node_wire_bytes",
    "extend_model_input_sequence_hash",
    "hash_model_input_node",
    "model_input_empty_sequence_hash",
    "model_input_node_hash_basis",
    "model_input_node_to_json",
    "split_model_input_canonical_json",
]
