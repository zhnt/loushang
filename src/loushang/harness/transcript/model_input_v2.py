"""Bounded indexing and reconstruction for Model Input v2 facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from functools import partial
from typing import Literal, cast
from weakref import WeakKeyDictionary

from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.transcript.kinds import (
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_input_timing import (
    PhaseTimer,
    PhaseTimingSnapshot,
)
from loushang.harness.transcript.model_input_types import (
    ModelInputIntegrityError,
    ModelInputRecordSizeError,
    canonical_model_input_json,
    hash_model_input_json,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_BUNDLE_TARGET_BYTES,
    MODEL_INPUT_V2_CHUNK_CHARACTERS,
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    MODEL_INPUT_V2_PROJECTION_VERSION,
    MODEL_INPUT_V2_SCHEMA_VERSION,
    DeferredModelInputNodeBundle,
    DeferredModelInputSequenceLink,
    ModelInputJsonChunkNode,
    ModelInputJsonValueNode,
    ModelInputMappingEntry,
    ModelInputMappingRootNode,
    ModelInputNode,
    ModelInputNodeBundle,
    ModelInputNodeReference,
    ModelInputSequenceTailNode,
    ModelInputSnapshotV2,
    create_model_input_json_chunk,
    create_model_input_json_value,
    create_model_input_mapping_root_from_hash,
    create_model_input_sequence_tail,
    estimate_model_input_node_wire_bytes,
    extend_model_input_sequence_hash,
    hash_model_input_node,
    model_input_empty_sequence_hash,
    model_input_node_hash_basis,
    split_model_input_canonical_json,
)
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork

MODEL_INPUT_V2_MAX_RESOLVED_NODES = 32_768
MODEL_INPUT_V2_MAX_REFERENCE_DEPTH = 4_096
MODEL_INPUT_V2_MAX_DECODED_BYTES = 128 * 1024 * 1024
MODEL_INPUT_V2_MAX_SEQUENCE_ITEMS = 100_000
MODEL_INPUT_V2_MAX_TAIL_APPEND_ITEMS = 1_024
MODEL_INPUT_V2_INDEX_COMPATIBILITY_TOKEN = (
    f"{MODEL_INPUT_V2_PROJECTION_VERSION}:schema-{MODEL_INPUT_V2_SCHEMA_VERSION}:"
    "node-index-v1"
)

ModelInputV2IndexCacheStatus = Literal["hit", "extended", "rebuilt"]


class IndexedModelInputNode:
    """One indexed node whose validated body may remain off-heap until needed."""

    __slots__ = ("reference", "record_position", "_node", "_node_loader")

    def __init__(
        self,
        reference: ModelInputNodeReference,
        node: ModelInputNode | None,
        record_position: int,
        *,
        node_loader: Callable[[], ModelInputNode] | None = None,
    ) -> None:
        if node is None and node_loader is None:
            raise ValueError("indexed Model Input node requires a body or loader")
        self.reference = reference
        self.record_position = record_position
        self._node = node
        self._node_loader = node_loader

    @property
    def node(self) -> ModelInputNode:
        node = self._node
        if node is None:
            loader = self._node_loader
            if loader is None:  # pragma: no cover - guarded by construction
                raise RuntimeError("indexed Model Input node loader is unavailable")
            node = loader()
            if (
                node.node_kind != self.reference.node_kind
                or node.content_hash != self.reference.content_hash
                or hash_model_input_node(node) != node.content_hash
            ):
                raise ModelInputIntegrityError(
                    "deferred Model Input node identity changed"
                )
            self._node = node
        return node

    @property
    def body_is_loaded(self) -> bool:
        return self._node is not None


@dataclass(frozen=True)
class RebuiltModelInputV2Values:
    logical_input: dict[str, JSONValue]
    prepared_payload: dict[str, JSONValue]
    model_visible_headers: dict[str, str]


@dataclass(frozen=True)
class ModelInputV2Materialization:
    logical_root: ModelInputNodeReference
    prepared_payload_root: ModelInputNodeReference
    model_visible_headers_root: ModelInputNodeReference
    logical_input_hash: str
    prepared_payload_mapping_hash: str
    model_visible_headers_hash: str
    expected_revision: int
    expected_leaf_id: str


@dataclass(frozen=True)
class _ValuePlan:
    value: JSONValue
    canonical: str
    value_hash: str
    encoded_bytes: int


@dataclass(frozen=True)
class _SequencePlan:
    values: tuple[JSONValue, ...]
    item_plans: tuple[_ValuePlan, ...]
    prefix_hashes: tuple[str, ...]

    @property
    def final_hash(self) -> str:
        return self.prefix_hashes[-1]


@dataclass(frozen=True)
class ModelInputV2MaterializationStats:
    sequence_count: int
    sequence_item_count: int
    reused_prefix_item_count: int
    planned_item_count: int


class ModelInputV2NodeIndex:
    """Verified-location index over one selected transcript path."""

    def __init__(self, records: Sequence[AgentTranscriptRecord]) -> None:
        self._by_identity: dict[tuple[str, str], IndexedModelInputNode] = {}
        self._by_location: dict[tuple[str, int], IndexedModelInputNode] = {}
        self._sequence_states: dict[tuple[int, str], IndexedModelInputNode] = {}
        self._values: dict[str, IndexedModelInputNode] = {}
        self._value_hashes_by_location: dict[tuple[str, int], str] = {}
        self._sequence_nodes_by_location: dict[
            tuple[str, int],
            ModelInputSequenceTailNode | DeferredModelInputSequenceLink,
        ] = {}
        self._sequence_link_loaders_by_location: dict[
            tuple[str, int],
            Callable[[], DeferredModelInputSequenceLink],
        ] = {}
        self._verified_value_canonicals: dict[str, str] = {}
        self._authority_verified_value_hashes: set[str] = set()
        self._verified_sequence_states: set[tuple[int, str]] = set()
        self._verified_sequence_references: dict[
            tuple[str, int],
            tuple[tuple[str, ...], str],
        ] = {}
        self._records = tuple(records)
        for position, record in enumerate(self._records):
            if record.kind != MODEL_INPUT_COMPONENT_KIND or not isinstance(
                record.payload,
                ModelInputNodeBundle,
            ):
                continue
            if record.payload_version != MODEL_INPUT_V2_PAYLOAD_VERSION:
                raise ModelInputIntegrityError(
                    "Model Input v2 bundle uses the wrong payload version"
                )
            if isinstance(record.payload, DeferredModelInputNodeBundle):
                for item in record.payload.indexed_nodes:
                    reference = ModelInputNodeReference(
                        record_id=record.record_id,
                        ordinal=item.ordinal,
                        node_kind=item.node_kind,
                        content_hash=item.content_hash,
                    )
                    indexed = IndexedModelInputNode(
                        reference,
                        None,
                        position,
                        node_loader=partial(record.payload.node_at, item.ordinal),
                    )
                    self._add_indexed_node(
                        indexed,
                        value_hash=item.value_hash,
                        inline_json=item.inline_json,
                        sequence_state=(
                            (item.total_item_count, item.sequence_hash)
                            if item.total_item_count is not None
                            and item.sequence_hash is not None
                            else None
                        ),
                        sequence_node=None,
                        sequence_link_loader=(
                            partial(record.payload.sequence_link_at, item.ordinal)
                            if item.node_kind == "sequence_tail"
                            else None
                        ),
                    )
                    if item.value_hash is not None and item.value_hash_verified:
                        self._authority_verified_value_hashes.add(item.value_hash)
                continue
            for ordinal, node in enumerate(record.payload.nodes):
                if hash_model_input_node(node) != node.content_hash:
                    raise ModelInputIntegrityError("Model Input v2 node hash changed")
                reference = ModelInputNodeReference(
                    record_id=record.record_id,
                    ordinal=ordinal,
                    node_kind=node.node_kind,
                    content_hash=node.content_hash,
                )
                indexed = IndexedModelInputNode(reference, node, position)
                self._add_indexed_node(
                    indexed,
                    value_hash=(
                        node.value_hash
                        if isinstance(node, ModelInputJsonValueNode)
                        else None
                    ),
                    inline_json=(
                        node.inline_json
                        if isinstance(node, ModelInputJsonValueNode)
                        else None
                    ),
                    sequence_state=(
                        (node.total_item_count, node.sequence_hash)
                        if isinstance(node, ModelInputSequenceTailNode)
                        else None
                    ),
                    sequence_node=(
                        node if isinstance(node, ModelInputSequenceTailNode) else None
                    ),
                    sequence_link_loader=None,
                )

    def _add_indexed_node(
        self,
        indexed: IndexedModelInputNode,
        *,
        value_hash: str | None,
        inline_json: str | None,
        sequence_state: tuple[int, str] | None,
        sequence_node: ModelInputSequenceTailNode
        | DeferredModelInputSequenceLink
        | None,
        sequence_link_loader: Callable[[], DeferredModelInputSequenceLink] | None,
    ) -> None:
        reference = indexed.reference
        identity = (reference.node_kind, reference.content_hash)
        existing = self._by_identity.get(identity)
        if (
            existing is not None
            and existing.body_is_loaded
            and indexed.body_is_loaded
            and model_input_node_hash_basis(existing.node)
            != model_input_node_hash_basis(indexed.node)
        ):
            raise ModelInputIntegrityError("Model Input v2 typed node hash collision")
        self._by_identity.setdefault(identity, indexed)
        if value_hash is not None:
            self._value_hashes_by_location[(reference.record_id, reference.ordinal)] = (
                value_hash
            )
            prior_value = self._values.get(value_hash)
            if (
                prior_value is not None
                and prior_value.reference.content_hash != reference.content_hash
            ):
                raise ModelInputIntegrityError(
                    "Model Input v2 JSON value hash is ambiguous"
                )
            self._values.setdefault(value_hash, indexed)
            if inline_json is not None:
                self.mark_value_verified(value_hash, inline_json)
        if sequence_state is not None:
            prior = self._sequence_states.get(sequence_state)
            if (
                prior is not None
                and prior.reference.content_hash != reference.content_hash
            ):
                raise ModelInputIntegrityError(
                    "Model Input v2 sequence state is ambiguous"
                )
            self._sequence_states.setdefault(sequence_state, indexed)
        if sequence_node is not None:
            self._sequence_nodes_by_location[
                (reference.record_id, reference.ordinal)
            ] = sequence_node
        if sequence_link_loader is not None:
            self._sequence_link_loaders_by_location[
                (reference.record_id, reference.ordinal)
            ] = sequence_link_loader
        self._by_location[(reference.record_id, reference.ordinal)] = indexed

    def find_node(self, node: ModelInputNode) -> IndexedModelInputNode | None:
        indexed = self._by_identity.get((node.node_kind, node.content_hash))
        if (
            indexed is not None
            and indexed.body_is_loaded
            and model_input_node_hash_basis(indexed.node)
            != model_input_node_hash_basis(node)
        ):
            raise ModelInputIntegrityError("Model Input v2 typed node hash collision")
        return indexed

    def find_sequence_state(
        self,
        item_count: int,
        sequence_hash: str,
    ) -> IndexedModelInputNode | None:
        return self._sequence_states.get((item_count, sequence_hash))

    def find_value(self, value_hash: str) -> IndexedModelInputNode | None:
        return self._values.get(value_hash)

    def verified_value_canonical(self, value_hash: str) -> str | None:
        return self._verified_value_canonicals.get(value_hash)

    def value_hash_is_authority_verified(self, value_hash: str) -> bool:
        return value_hash in self._authority_verified_value_hashes

    def mark_value_verified(self, value_hash: str, canonical: str) -> None:
        if value_hash not in self._values:
            raise ModelInputIntegrityError(
                "Model Input v2 verified value is outside the node index"
            )
        prior = self._verified_value_canonicals.get(value_hash)
        if prior is not None and prior != canonical:
            raise ModelInputIntegrityError(
                "Model Input v2 verified value hash is ambiguous"
            )
        self._verified_value_canonicals[value_hash] = canonical

    def sequence_state_is_verified(
        self,
        item_count: int,
        sequence_hash: str,
    ) -> bool:
        return (item_count, sequence_hash) in self._verified_sequence_states

    def mark_sequence_state_verified(
        self,
        item_count: int,
        sequence_hash: str,
    ) -> None:
        state = (item_count, sequence_hash)
        if state not in self._sequence_states:
            raise ModelInputIntegrityError(
                "Model Input v2 verified sequence is outside the node index"
            )
        self._verified_sequence_states.add(state)

    def add_bundle_record(
        self,
        record: AgentTranscriptRecord,
        *,
        record_position: int,
    ) -> tuple[ModelInputNodeReference, ...]:
        if record.kind != MODEL_INPUT_COMPONENT_KIND or not isinstance(
            record.payload,
            ModelInputNodeBundle,
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 materialization did not commit a node bundle"
            )
        if record.payload_version != MODEL_INPUT_V2_PAYLOAD_VERSION:
            raise ModelInputIntegrityError(
                "Model Input v2 materialization used the wrong payload version"
            )
        references: list[ModelInputNodeReference] = []
        for ordinal, node in enumerate(record.payload.nodes):
            if hash_model_input_node(node) != node.content_hash:
                raise ModelInputIntegrityError("Model Input v2 node hash changed")
            reference = ModelInputNodeReference(
                record_id=record.record_id,
                ordinal=ordinal,
                node_kind=node.node_kind,
                content_hash=node.content_hash,
            )
            indexed = IndexedModelInputNode(reference, node, record_position)
            self._add_indexed_node(
                indexed,
                value_hash=(
                    node.value_hash
                    if isinstance(node, ModelInputJsonValueNode)
                    else None
                ),
                inline_json=(
                    node.inline_json
                    if isinstance(node, ModelInputJsonValueNode)
                    else None
                ),
                sequence_state=(
                    (node.total_item_count, node.sequence_hash)
                    if isinstance(node, ModelInputSequenceTailNode)
                    else None
                ),
                sequence_node=(
                    node if isinstance(node, ModelInputSequenceTailNode) else None
                ),
                sequence_link_loader=None,
            )
            references.append(reference)
        return tuple(references)

    def verify_sequence_reference(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
    ) -> tuple[tuple[str, ...], str]:
        requested_key = (reference.record_id, reference.ordinal)
        cached = self._verified_sequence_references.get(requested_key)
        if cached is not None:
            return cached

        chain: list[
            tuple[ModelInputSequenceTailNode | DeferredModelInputSequenceLink, int]
        ] = []
        current_reference = reference
        current_owner_position = owner_position
        while True:
            if len(chain) > MODEL_INPUT_V2_MAX_REFERENCE_DEPTH:
                raise ModelInputIntegrityError(
                    "Model Input v2 reference depth budget exceeded"
                )
            indexed = self._resolve_indexed_reference(
                current_reference,
                owner_position=current_owner_position,
            )
            sequence_node = self._sequence_node(indexed)
            key = (current_reference.record_id, current_reference.ordinal)
            cached = self._verified_sequence_references.get(key)
            if cached is not None:
                value_hashes = list(cached[0])
                sequence_hash = cached[1]
                break
            chain.append((sequence_node, indexed.record_position))
            if sequence_node.previous_tail is None:
                value_hashes = []
                sequence_hash = model_input_empty_sequence_hash()
                break
            current_reference = sequence_node.previous_tail
            current_owner_position = indexed.record_position

        for node, position in reversed(chain):
            for item_reference in node.appended_items:
                item = self._resolve_indexed_reference(
                    item_reference,
                    owner_position=position,
                )
                item_value_hash = self._verified_value_hash(item)
                value_hashes.append(item_value_hash)
                if len(value_hashes) > MODEL_INPUT_V2_MAX_SEQUENCE_ITEMS:
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence item budget exceeded"
                    )
                sequence_hash = extend_model_input_sequence_hash(
                    sequence_hash,
                    item_value_hash,
                )
            if len(value_hashes) != node.total_item_count:
                raise ModelInputIntegrityError("Model Input v2 sequence count changed")
            if sequence_hash != node.sequence_hash:
                raise ModelInputIntegrityError("Model Input v2 sequence hash changed")

        verified = (tuple(value_hashes), sequence_hash)
        self._verified_sequence_references[requested_key] = verified
        self.mark_sequence_state_verified(len(value_hashes), sequence_hash)
        return verified

    def _sequence_node(
        self,
        indexed: IndexedModelInputNode,
    ) -> ModelInputSequenceTailNode | DeferredModelInputSequenceLink:
        key = (indexed.reference.record_id, indexed.reference.ordinal)
        projected = self._sequence_nodes_by_location.get(key)
        if projected is not None:
            return projected
        loader = self._sequence_link_loaders_by_location.get(key)
        if loader is not None:
            projected = loader()
            self._sequence_nodes_by_location[key] = projected
            return projected
        node = indexed.node
        if not isinstance(node, ModelInputSequenceTailNode):
            raise ModelInputIntegrityError(
                "Model Input v2 sequence reference targets the wrong node"
            )
        return node

    def _verified_value_hash(self, indexed: IndexedModelInputNode) -> str:
        key = (indexed.reference.record_id, indexed.reference.ordinal)
        projected = self._value_hashes_by_location.get(key)
        if projected is not None and (
            projected in self._authority_verified_value_hashes
            or projected in self._verified_value_canonicals
        ):
            return projected
        node = indexed.node
        if not isinstance(node, ModelInputJsonValueNode):
            raise ModelInputIntegrityError(
                "Model Input v2 sequence item targets the wrong node"
            )
        return node.value_hash

    def _resolve_indexed_reference(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
    ) -> IndexedModelInputNode:
        indexed = self._by_location.get((reference.record_id, reference.ordinal))
        if indexed is None or indexed.record_position >= owner_position:
            raise ModelInputIntegrityError(
                "Model Input v2 node is outside reference ancestry"
            )
        if (
            indexed.reference.node_kind != reference.node_kind
            or indexed.reference.content_hash != reference.content_hash
        ):
            raise ModelInputIntegrityError("Model Input v2 node reference changed")
        return indexed


@dataclass
class _ModelInputV2IndexCache:
    """One ancestry-bound index that can advance along the selected path."""

    compatibility_token: str
    records: tuple[AgentTranscriptRecord, ...]
    index: ModelInputV2NodeIndex
    sequence_plans: dict[tuple[int, str], _SequencePlan]

    def resolve(
        self,
        records: tuple[AgentTranscriptRecord, ...],
        *,
        compatibility_token: str,
    ) -> tuple[ModelInputV2NodeIndex, ModelInputV2IndexCacheStatus]:
        if self.compatibility_token != compatibility_token or not _path_extends(
            self.records, records
        ):
            self.compatibility_token = compatibility_token
            self.records = records
            self.index = ModelInputV2NodeIndex(records)
            self.sequence_plans.clear()
            return self.index, "rebuilt"

        previous_count = len(self.records)
        if previous_count == len(records):
            return self.index, "hit"
        for position, record in enumerate(
            records[previous_count:],
            start=previous_count,
        ):
            if record.kind == MODEL_INPUT_COMPONENT_KIND and isinstance(
                record.payload,
                ModelInputNodeBundle,
            ):
                self.index.add_bundle_record(record, record_position=position)
        self.records = records
        return self.index, "extended"

    def mark_writer_extension(
        self,
        records: tuple[AgentTranscriptRecord, ...],
    ) -> None:
        """Advance the path after the writer already indexed its own commits."""

        if not _path_extends(self.records, records):
            raise ModelInputIntegrityError(
                "Model Input v2 index cache left its selected ancestry"
            )
        self.records = records


_MODEL_INPUT_V2_INDEX_CACHES: WeakKeyDictionary[
    AgentTranscriptUnitOfWork,
    _ModelInputV2IndexCache,
] = WeakKeyDictionary()


def _cached_node_index(
    transcript: AgentTranscriptUnitOfWork,
    records: tuple[AgentTranscriptRecord, ...],
) -> tuple[
    ModelInputV2NodeIndex,
    _ModelInputV2IndexCache,
    ModelInputV2IndexCacheStatus,
]:
    cached = _MODEL_INPUT_V2_INDEX_CACHES.get(transcript)
    if cached is None:
        index = ModelInputV2NodeIndex(records)
        cached = _ModelInputV2IndexCache(
            compatibility_token=MODEL_INPUT_V2_INDEX_COMPATIBILITY_TOKEN,
            records=records,
            index=index,
            sequence_plans={},
        )
        _MODEL_INPUT_V2_INDEX_CACHES[transcript] = cached
        return index, cached, "rebuilt"
    index, status = cached.resolve(
        records,
        compatibility_token=MODEL_INPUT_V2_INDEX_COMPATIBILITY_TOKEN,
    )
    return index, cached, status


def _path_extends(
    previous: tuple[AgentTranscriptRecord, ...],
    current: tuple[AgentTranscriptRecord, ...],
) -> bool:
    if len(previous) > len(current):
        return False
    if not previous:
        return True
    return previous[-1].record_id == current[len(previous) - 1].record_id


def _same_model_input_json(left: object, right: object) -> bool:
    """Compare normalized JSON without Python's bool/int coercion."""

    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_mapping = cast(dict[str, object], left)
        right_mapping = cast(dict[str, object], right)
        return left_mapping.keys() == right_mapping.keys() and all(
            _same_model_input_json(value, right_mapping[name])
            for name, value in left_mapping.items()
        )
    if type(left) is list:
        left_items = cast(list[object], left)
        right_items = cast(list[object], right)
        return len(left_items) == len(right_items) and all(
            _same_model_input_json(left_item, right_item)
            for left_item, right_item in zip(left_items, right_items, strict=True)
        )
    return left == right


def _optional_phase(
    timer: PhaseTimer | None,
    name: str,
) -> AbstractContextManager[None]:
    return timer.phase(name) if timer is not None else nullcontext()


class ModelInputV2Writer:
    """Materialize one v2 request using only verified active-path ancestors."""

    def __init__(
        self,
        *,
        transcript: AgentTranscriptUnitOfWork,
        expected_revision: int,
        expected_leaf_id: str,
        max_encoded_record_bytes: int,
        phase_timer: PhaseTimer | None = None,
    ) -> None:
        self._transcript = transcript
        self._expected_revision = expected_revision
        self._expected_leaf_id = expected_leaf_id
        self._max_encoded_record_bytes = max_encoded_record_bytes
        with _optional_phase(phase_timer, "active_path"):
            active_records = transcript.active_path()
        with _optional_phase(phase_timer, "node_index_build"):
            (
                self._index,
                self._index_cache,
                self._index_cache_status,
            ) = _cached_node_index(transcript, active_records)
        with _optional_phase(phase_timer, "resolver_build"):
            self._existing_resolver = ModelInputV2Resolver(active_records)
        self._existing_owner_position = len(active_records)
        self._value_plans: dict[str, _ValuePlan] = {}
        self._value_references: dict[str, ModelInputNodeReference] = {}
        self._materialization_timing: PhaseTimingSnapshot | None = None
        self._sequence_plan_updates: dict[tuple[int, str], _SequencePlan] = {}
        self._sequence_count = 0
        self._sequence_item_count = 0
        self._reused_prefix_item_count = 0
        self._planned_item_count = 0

    @property
    def index_cache_status(self) -> ModelInputV2IndexCacheStatus:
        return self._index_cache_status

    @property
    def materialization_timing(self) -> PhaseTimingSnapshot | None:
        return self._materialization_timing

    @property
    def materialization_stats(self) -> ModelInputV2MaterializationStats:
        return ModelInputV2MaterializationStats(
            sequence_count=self._sequence_count,
            sequence_item_count=self._sequence_item_count,
            reused_prefix_item_count=self._reused_prefix_item_count,
            planned_item_count=self._planned_item_count,
        )

    async def materialize(
        self,
        *,
        logical_input: Mapping[str, JSONValue],
        prepared_payload: Mapping[str, JSONValue],
        model_visible_headers: Mapping[str, str],
    ) -> ModelInputV2Materialization:
        timing = PhaseTimer()
        with timing.phase("plan"):
            logical = dict(logical_input)
            prepared = dict(prepared_payload)
            headers = dict(model_visible_headers)
            mapping_values = (logical, prepared)
            sequence_plans: dict[tuple[int, str], _SequencePlan] = {}
            mapping_sequences: dict[tuple[int, str], tuple[int, str]] = {}
            mapping_value_hashes: dict[tuple[int, str], str] = {}

            for mapping_index, mapping in enumerate(mapping_values):
                for name, value in mapping.items():
                    if isinstance(value, list):
                        cache_key = (mapping_index, name)
                        plan = self._sequence_plan(value, cache_key=cache_key)
                        state = (len(plan.values), plan.final_hash)
                        prior_plan = sequence_plans.get(state)
                        if prior_plan is not None and (
                            len(prior_plan.values) != len(plan.values)
                            or any(
                                not _same_model_input_json(left, right)
                                for left, right in zip(
                                    prior_plan.values,
                                    plan.values,
                                    strict=True,
                                )
                            )
                        ):
                            raise ModelInputIntegrityError(
                                "Model Input v2 sequence hash collision"
                            )
                        sequence_plans.setdefault(state, plan)
                        mapping_sequences[(mapping_index, name)] = state
                    else:
                        mapping_value_hashes[(mapping_index, name)] = (
                            self._collect_value(value).value_hash
                        )
            headers_plan = self._collect_value(headers)

        with timing.phase("values"):
            await self._materialize_values()

        with timing.phase("sequences"):
            sequence_nodes: dict[tuple[int, str], ModelInputSequenceTailNode] = {}
            sequence_refs: dict[tuple[int, str], ModelInputNodeReference] = {}
            for state, plan in sequence_plans.items():
                indexed_sequence = self._index.find_sequence_state(*state)
                if indexed_sequence is not None:
                    if not self._index.sequence_state_is_verified(*state):
                        value_hashes, sequence_hash = (
                            self._index.verify_sequence_reference(
                                indexed_sequence.reference,
                                owner_position=self._existing_owner_position,
                            )
                        )
                        if (
                            value_hashes
                            != tuple(item.value_hash for item in plan.item_plans)
                            or sequence_hash != plan.final_hash
                        ):
                            raise ModelInputIntegrityError(
                                "Model Input v2 sequence state failed verification"
                            )
                    sequence_refs[state] = indexed_sequence.reference
                    continue
                prefix_count, previous_ref = self._longest_sequence_prefix(plan)
                if (
                    len(plan.values) - prefix_count
                    > MODEL_INPUT_V2_MAX_TAIL_APPEND_ITEMS
                ):
                    while prefix_count < len(plan.values):
                        next_count = min(
                            prefix_count + MODEL_INPUT_V2_MAX_TAIL_APPEND_ITEMS,
                            len(plan.values),
                        )
                        node = create_model_input_sequence_tail(
                            previous_tail=previous_ref,
                            appended_items=tuple(
                                self._value_references[item.value_hash]
                                for item in plan.item_plans[prefix_count:next_count]
                            ),
                            total_item_count=next_count,
                            sequence_hash=plan.prefix_hashes[next_count],
                        )
                        await self._materialize_nodes((node,))
                        indexed = self._index.find_node(node)
                        if indexed is None:
                            raise ModelInputIntegrityError(
                                "Model Input v2 sequence segment was not materialized"
                            )
                        previous_ref = indexed.reference
                        prefix_count = next_count
                    if previous_ref is None:
                        raise ModelInputIntegrityError(
                            "Model Input v2 sequence segments have no final tail"
                        )
                    self._index.mark_sequence_state_verified(*state)
                    sequence_refs[state] = previous_ref
                    continue
                item_refs = tuple(
                    self._value_references[item.value_hash]
                    for item in plan.item_plans[prefix_count:]
                )
                node = create_model_input_sequence_tail(
                    previous_tail=previous_ref,
                    appended_items=item_refs,
                    total_item_count=len(plan.values),
                    sequence_hash=plan.final_hash,
                )
                sequence_nodes[state] = node
            await self._materialize_nodes(tuple(sequence_nodes.values()))
            for state, node in sequence_nodes.items():
                indexed = self._index.find_node(node)
                if indexed is None:
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence tail was not materialized"
                    )
                sequence_refs[state] = indexed.reference
                self._index.mark_sequence_state_verified(*state)

        with timing.phase("roots"):
            roots: list[ModelInputMappingRootNode] = []
            for mapping_index, mapping in enumerate(mapping_values):
                entries = []
                canonical_fields: dict[str, str] = {}
                for name in mapping:
                    field_state = mapping_sequences.get((mapping_index, name))
                    if field_state is not None:
                        reference = sequence_refs[field_state]
                        canonical_fields[name] = (
                            "["
                            + ",".join(
                                item.canonical
                                for item in sequence_plans[field_state].item_plans
                            )
                            + "]"
                        )
                    else:
                        value_hash = mapping_value_hashes[(mapping_index, name)]
                        reference = self._value_references[value_hash]
                        canonical_fields[name] = self._value_plans[value_hash].canonical
                    entries.append(ModelInputMappingEntry(name, reference))
                roots.append(
                    create_model_input_mapping_root_from_hash(
                        mapping_hash=_hash_canonical_mapping_fields(canonical_fields),
                        entries=entries,
                    )
                )
            await self._materialize_nodes(tuple(roots))
            root_refs = []
            for root in roots:
                indexed = self._index.find_node(root)
                if indexed is None:
                    raise ModelInputIntegrityError(
                        "Model Input v2 mapping root was not materialized"
                    )
                root_refs.append(indexed.reference)

        self._materialization_timing = timing.snapshot()
        self._index_cache.sequence_plans.update(self._sequence_plan_updates)
        return ModelInputV2Materialization(
            logical_root=root_refs[0],
            prepared_payload_root=root_refs[1],
            model_visible_headers_root=self._value_references[headers_plan.value_hash],
            logical_input_hash=roots[0].mapping_hash,
            prepared_payload_mapping_hash=roots[1].mapping_hash,
            model_visible_headers_hash=headers_plan.value_hash,
            expected_revision=self._expected_revision,
            expected_leaf_id=self._expected_leaf_id,
        )

    def verify_snapshot_commit(
        self,
        record: AgentTranscriptRecord,
        snapshot: ModelInputSnapshotV2,
        materialization: ModelInputV2Materialization,
        *,
        logical_input_hash: str,
        prepared_payload_hash: str,
    ) -> None:
        """Prove the just-written snapshot from writer-verified graph roots."""

        if (
            record.kind != MODEL_INPUT_PREPARED_KIND
            or record.payload_version != MODEL_INPUT_V2_PAYLOAD_VERSION
            or record.payload != snapshot
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 snapshot commit changed its payload"
            )
        if record.parent_id != materialization.expected_leaf_id:
            raise ModelInputIntegrityError(
                "Model Input v2 snapshot commit changed its graph parent"
            )
        if snapshot.commit_revision != materialization.expected_revision + 1:
            raise ModelInputIntegrityError(
                "Model Input v2 snapshot commit changed its revision"
            )
        if (
            snapshot.logical_root != materialization.logical_root
            or snapshot.prepared_payload_root != materialization.prepared_payload_root
            or snapshot.model_visible_headers_root
            != materialization.model_visible_headers_root
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 snapshot changed its materialized roots"
            )
        if snapshot.logical_input_hash != logical_input_hash:
            raise ModelInputIntegrityError("Model Input v2 logical input hash changed")
        if snapshot.prepared_payload_hash != prepared_payload_hash:
            raise ModelInputIntegrityError(
                "Model Input v2 prepared request hash changed"
            )

        logical = self._existing_resolver.validate_reference(
            snapshot.logical_root,
            owner_position=self._existing_owner_position,
        ).node
        prepared = self._existing_resolver.validate_reference(
            snapshot.prepared_payload_root,
            owner_position=self._existing_owner_position,
        ).node
        headers = self._existing_resolver.validate_reference(
            snapshot.model_visible_headers_root,
            owner_position=self._existing_owner_position,
        ).node
        if (
            not isinstance(logical, ModelInputMappingRootNode)
            or logical.mapping_hash != materialization.logical_input_hash
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 logical root failed incremental verification"
            )
        if (
            not isinstance(prepared, ModelInputMappingRootNode)
            or prepared.mapping_hash != materialization.prepared_payload_mapping_hash
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 prepared root failed incremental verification"
            )
        if (
            not isinstance(headers, ModelInputJsonValueNode)
            or headers.value_hash != materialization.model_visible_headers_hash
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 headers root failed incremental verification"
            )

    def _collect_value(self, value: object) -> _ValuePlan:
        plan = self._value_plan(value)
        existing = self._value_plans.get(plan.value_hash)
        if existing is not None and existing.canonical != plan.canonical:
            raise ModelInputIntegrityError("Model Input v2 JSON value hash collision")
        if existing is not None:
            return existing
        self._value_plans[plan.value_hash] = plan
        return plan

    def _sequence_plan(
        self,
        values: Sequence[JSONValue],
        *,
        cache_key: tuple[int, str],
    ) -> _SequencePlan:
        if len(values) > MODEL_INPUT_V2_MAX_SEQUENCE_ITEMS:
            raise ModelInputRecordSizeError(
                "Model Input v2 sequence exceeds the item budget"
            )
        cached = self._index_cache.sequence_plans.get(cache_key)
        reused_count = 0
        if cached is not None:
            reusable_count = min(len(values), len(cached.item_plans))
            while reused_count < reusable_count and _same_model_input_json(
                values[reused_count],
                cached.item_plans[reused_count].value,
            ):
                reused_count += 1

        item_plans = [
            self._reuse_value_plan(plan)
            for plan in (() if cached is None else cached.item_plans[:reused_count])
        ]
        prefix_hashes = (
            [model_input_empty_sequence_hash()]
            if cached is None
            else list(cached.prefix_hashes[: reused_count + 1])
        )
        for value in values[reused_count:]:
            plan = self._collect_value(value)
            item_plans.append(plan)
            prefix_hashes.append(
                extend_model_input_sequence_hash(prefix_hashes[-1], plan.value_hash)
            )
        resolved_item_plans = tuple(item_plans)
        sequence_plan = _SequencePlan(
            tuple(item.value for item in resolved_item_plans),
            resolved_item_plans,
            tuple(prefix_hashes),
        )
        self._sequence_plan_updates[cache_key] = sequence_plan
        self._sequence_count += 1
        self._sequence_item_count += len(values)
        self._reused_prefix_item_count += reused_count
        self._planned_item_count += len(values) - reused_count
        return sequence_plan

    def _reuse_value_plan(self, plan: _ValuePlan) -> _ValuePlan:
        existing = self._value_plans.get(plan.value_hash)
        if existing is not None and existing.canonical != plan.canonical:
            raise ModelInputIntegrityError("Model Input v2 JSON value hash collision")
        if existing is not None:
            return existing
        self._value_plans[plan.value_hash] = plan
        return plan

    async def _materialize_values(self) -> None:
        total_unique_bytes = sum(
            plan.encoded_bytes for plan in self._value_plans.values()
        )
        if total_unique_bytes > MODEL_INPUT_V2_MAX_DECODED_BYTES:
            raise ModelInputRecordSizeError(
                "Model Input v2 request exceeds the decoded-byte budget"
            )
        missing_plans: list[_ValuePlan] = []
        for plan in self._value_plans.values():
            existing = self._index.find_value(plan.value_hash)
            if existing is None:
                missing_plans.append(plan)
                continue
            verified = self._index.verified_value_canonical(plan.value_hash)
            if verified is not None:
                if verified != plan.canonical:
                    raise ModelInputIntegrityError(
                        "Model Input v2 JSON value hash is ambiguous"
                    )
                self._value_references[plan.value_hash] = existing.reference
                continue
            if self._index.value_hash_is_authority_verified(plan.value_hash):
                # The projection re-hashed canonical inline JSON from the
                # authority line during this load.  Matching content addresses
                # prove the current plan reuses that value without copying it.
                self._value_references[plan.value_hash] = existing.reference
                self._index.mark_value_verified(plan.value_hash, plan.canonical)
                continue
            rebuilt = self._existing_resolver.resolve_value_reference(
                existing.reference,
                owner_position=self._existing_owner_position,
            )
            if (
                canonical_model_input_json(
                    rebuilt,
                    name="existing Model Input v2 value",
                )
                != plan.canonical
            ):
                raise ModelInputIntegrityError(
                    "Model Input v2 JSON value failed verification"
                )
            self._value_references[plan.value_hash] = existing.reference
            self._index.mark_value_verified(plan.value_hash, plan.canonical)

        chunks_by_plan: dict[str, tuple[ModelInputJsonChunkNode, ...]] = {}
        chunk_nodes: dict[tuple[str, str], ModelInputJsonChunkNode] = {}
        for plan in missing_plans:
            if len(plan.canonical) <= MODEL_INPUT_V2_CHUNK_CHARACTERS:
                continue
            chunks = tuple(
                create_model_input_json_chunk(text)
                for text in split_model_input_canonical_json(plan.canonical)
            )
            chunks_by_plan[plan.value_hash] = chunks
            for chunk in chunks:
                chunk_nodes.setdefault(
                    (chunk.node_kind, chunk.content_hash),
                    chunk,
                )
        await self._materialize_nodes(tuple(chunk_nodes.values()))

        value_nodes: dict[str, ModelInputJsonValueNode] = {}
        for plan in missing_plans:
            chunks = chunks_by_plan.get(plan.value_hash, ())
            chunk_refs = []
            for chunk in chunks:
                indexed = self._index.find_node(chunk)
                if indexed is None:
                    raise ModelInputIntegrityError(
                        "Model Input v2 JSON chunk was not materialized"
                    )
                chunk_refs.append(indexed.reference)
            node = create_model_input_json_value(
                plan.value,
                chunk_refs=chunk_refs,
            )
            value_nodes[plan.value_hash] = node
        await self._materialize_nodes(tuple(value_nodes.values()))
        for value_hash, node in value_nodes.items():
            indexed = self._index.find_node(node)
            if indexed is None:
                raise ModelInputIntegrityError(
                    "Model Input v2 JSON value was not materialized"
                )
            self._value_references[value_hash] = indexed.reference
            self._index.mark_value_verified(
                value_hash,
                self._value_plans[value_hash].canonical,
            )

    def _longest_sequence_prefix(
        self,
        plan: _SequencePlan,
    ) -> tuple[int, ModelInputNodeReference | None]:
        for item_count in range(len(plan.values), -1, -1):
            indexed = self._index.find_sequence_state(
                item_count,
                plan.prefix_hashes[item_count],
            )
            if indexed is None:
                continue
            state = (item_count, plan.prefix_hashes[item_count])
            if not self._index.sequence_state_is_verified(*state):
                value_hashes, sequence_hash = self._index.verify_sequence_reference(
                    indexed.reference,
                    owner_position=self._existing_owner_position,
                )
                if value_hashes != tuple(
                    item.value_hash for item in plan.item_plans[:item_count]
                ) or (sequence_hash != plan.prefix_hashes[item_count]):
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence prefix failed verification"
                    )
            return item_count, indexed.reference
        return 0, None

    async def _materialize_nodes(self, nodes: Sequence[ModelInputNode]) -> None:
        missing: dict[tuple[str, str], ModelInputNode] = {}
        for node in nodes:
            if self._index.find_node(node) is None:
                missing.setdefault((node.node_kind, node.content_hash), node)
        if not missing:
            return
        bundles = _bundle_model_input_nodes(tuple(missing.values()))
        commits = await self._transcript.append_model_input_node_bundles(
            bundles,
            max_encoded_record_bytes=self._max_encoded_record_bytes,
            expected_revision=self._expected_revision,
            expected_leaf_id=self._expected_leaf_id,
        )
        if len(commits) != len(bundles):
            raise ModelInputIntegrityError(
                "Model Input v2 bundle batch returned an invalid commit count"
            )
        first_position = len(self._transcript.active_path()) - len(commits)
        for offset, commit in enumerate(commits):
            receipt = commit.receipt
            if receipt is None:
                raise ModelInputIntegrityError(
                    "Model Input v2 bundle did not reach the authoritative Store"
                )
            self._index.add_bundle_record(
                commit.record,
                record_position=first_position + offset,
            )
            self._expected_revision = receipt.revision
            self._expected_leaf_id = commit.record.record_id
        active_records = self._transcript.active_path()
        self._index_cache.mark_writer_extension(active_records)
        self._existing_resolver = ModelInputV2Resolver(active_records)
        self._existing_owner_position = len(active_records)

    @staticmethod
    def _value_plan(value: object) -> _ValuePlan:
        canonical = canonical_model_input_json(value, name="Model Input v2 value")
        encoded = canonical.encode("utf-8")
        encoded_bytes = len(encoded)
        if encoded_bytes > MODEL_INPUT_V2_MAX_DECODED_BYTES:
            raise ModelInputRecordSizeError(
                "Model Input v2 value exceeds the decoded-byte budget"
            )
        decoded = cast(JSONValue, json.loads(canonical))
        return _ValuePlan(
            value=decoded,
            canonical=canonical,
            value_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
            encoded_bytes=encoded_bytes,
        )


def _hash_canonical_mapping_fields(fields: Mapping[str, str]) -> str:
    canonical = (
        "{"
        + ",".join(
            canonical_model_input_json(name, name="Model Input v2 mapping field")
            + ":"
            + fields[name]
            for name in sorted(fields)
        )
        + "}"
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bundle_model_input_nodes(
    nodes: Sequence[ModelInputNode],
) -> tuple[ModelInputNodeBundle, ...]:
    bundles: list[ModelInputNodeBundle] = []
    selected: list[ModelInputNode] = []
    selected_bytes = 0
    for node in nodes:
        node_bytes = estimate_model_input_node_wire_bytes(node)
        if selected and selected_bytes + node_bytes > (
            MODEL_INPUT_V2_BUNDLE_TARGET_BYTES
        ):
            bundles.append(ModelInputNodeBundle(tuple(selected)))
            selected = []
            selected_bytes = 0
        selected.append(node)
        selected_bytes += node_bytes
    if selected:
        bundles.append(ModelInputNodeBundle(tuple(selected)))
    return tuple(bundles)


class ModelInputV2Resolver:
    def __init__(self, records: Sequence[AgentTranscriptRecord]) -> None:
        self._records = tuple(records)
        self._positions = {
            record.record_id: position for position, record in enumerate(self._records)
        }
        if len(self._positions) != len(self._records):
            raise ModelInputIntegrityError(
                "Model Input v2 ancestry contains duplicate record ids"
            )
        self._value_cache: dict[tuple[str, int], JSONValue] = {}
        self._sequence_cache: dict[
            tuple[str, int],
            tuple[list[JSONValue], str],
        ] = {}
        self._mapping_cache: dict[tuple[str, int], dict[str, JSONValue]] = {}
        self._resolved_nodes: set[tuple[str, int]] = set()
        self._decoded_bytes = 0

    def rebuild_snapshot(
        self,
        snapshot_record: AgentTranscriptRecord,
        snapshot: ModelInputSnapshotV2,
    ) -> RebuiltModelInputV2Values:
        snapshot_position = self._positions.get(snapshot_record.record_id)
        if snapshot_position is None:
            raise ModelInputIntegrityError(
                "Model Input v2 snapshot is outside selected ancestry"
            )
        logical = self._resolve_mapping(
            snapshot.logical_root,
            owner_position=snapshot_position,
            depth=0,
        )
        prepared = self._resolve_mapping(
            snapshot.prepared_payload_root,
            owner_position=snapshot_position,
            depth=0,
        )
        headers_value = self._resolve_value(
            snapshot.model_visible_headers_root,
            owner_position=snapshot_position,
            depth=0,
        )
        if not isinstance(headers_value, dict) or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in headers_value.items()
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 model-visible headers are not string pairs"
            )
        return RebuiltModelInputV2Values(
            logical_input=logical,
            prepared_payload=prepared,
            model_visible_headers=cast(dict[str, str], headers_value),
        )

    def validate_reference(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
    ) -> IndexedModelInputNode:
        node, position = self._node(reference, owner_position=owner_position)
        return IndexedModelInputNode(reference, node, position)

    def resolve_value_reference(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
    ) -> JSONValue:
        return self._resolve_value(
            reference,
            owner_position=owner_position,
            depth=0,
        )

    def resolve_sequence_reference(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
    ) -> tuple[list[JSONValue], str]:
        return self._resolve_sequence(
            reference,
            owner_position=owner_position,
            depth=0,
        )

    def _resolve_mapping(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
        depth: int,
    ) -> dict[str, JSONValue]:
        self._require_depth(depth)
        node, position = self._node(reference, owner_position=owner_position)
        if not isinstance(node, ModelInputMappingRootNode):
            raise ModelInputIntegrityError(
                "Model Input v2 mapping reference targets the wrong node"
            )
        key = (reference.record_id, reference.ordinal)
        cached = self._mapping_cache.get(key)
        if cached is not None:
            return dict(cached)
        rebuilt: dict[str, JSONValue] = {}
        for entry in node.entries:
            if entry.value.node_kind == "sequence_tail":
                sequence, _ = self._resolve_sequence(
                    entry.value,
                    owner_position=position,
                    depth=depth + 1,
                )
                rebuilt[entry.name] = sequence
            else:
                rebuilt[entry.name] = self._resolve_value(
                    entry.value,
                    owner_position=position,
                    depth=depth + 1,
                )
        if hash_model_input_json(rebuilt, name="rebuilt Model Input v2 mapping") != (
            node.mapping_hash
        ):
            raise ModelInputIntegrityError("Model Input v2 mapping hash changed")
        self._mapping_cache[key] = dict(rebuilt)
        return rebuilt

    def _resolve_sequence(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
        depth: int,
    ) -> tuple[list[JSONValue], str]:
        requested_key = (reference.record_id, reference.ordinal)
        requested_cached = self._sequence_cache.get(requested_key)
        if requested_cached is not None:
            return list(requested_cached[0]), requested_cached[1]
        chain: list[tuple[ModelInputSequenceTailNode, int]] = []
        current_reference = reference
        current_owner_position = owner_position
        while True:
            self._require_depth(depth + len(chain))
            node, position = self._node(
                current_reference,
                owner_position=current_owner_position,
            )
            if not isinstance(node, ModelInputSequenceTailNode):
                raise ModelInputIntegrityError(
                    "Model Input v2 sequence reference targets the wrong node"
                )
            key = (current_reference.record_id, current_reference.ordinal)
            cached = self._sequence_cache.get(key)
            if cached is not None:
                items = list(cached[0])
                sequence_hash = cached[1]
                break
            chain.append((node, position))
            if node.previous_tail is None:
                items = []
                sequence_hash = model_input_empty_sequence_hash()
                break
            current_reference = node.previous_tail
            current_owner_position = position

        item_depth = depth + len(chain)
        for node, position in reversed(chain):
            for item_ref in node.appended_items:
                item_node, _ = self._node(item_ref, owner_position=position)
                if not isinstance(item_node, ModelInputJsonValueNode):
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence item targets the wrong node"
                    )
                items.append(
                    self._resolve_value(
                        item_ref,
                        owner_position=position,
                        depth=item_depth,
                    )
                )
                sequence_hash = extend_model_input_sequence_hash(
                    sequence_hash,
                    item_node.value_hash,
                )
                if len(items) > MODEL_INPUT_V2_MAX_SEQUENCE_ITEMS:
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence item budget exceeded"
                    )
            if len(items) != node.total_item_count:
                raise ModelInputIntegrityError("Model Input v2 sequence count changed")
            if sequence_hash != node.sequence_hash:
                raise ModelInputIntegrityError("Model Input v2 sequence hash changed")
        self._sequence_cache[requested_key] = (list(items), sequence_hash)
        return items, sequence_hash

    def _resolve_value(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
        depth: int,
    ) -> JSONValue:
        self._require_depth(depth)
        node, position = self._node(reference, owner_position=owner_position)
        if not isinstance(node, ModelInputJsonValueNode):
            raise ModelInputIntegrityError(
                "Model Input v2 value reference targets the wrong node"
            )
        key = (reference.record_id, reference.ordinal)
        if key in self._value_cache:
            return self._value_cache[key]
        if node.inline_json is not None:
            canonical = node.inline_json
        else:
            chunks: list[str] = []
            for chunk_ref in node.chunk_refs:
                chunk, _ = self._node(chunk_ref, owner_position=position)
                if not isinstance(chunk, ModelInputJsonChunkNode):
                    raise ModelInputIntegrityError(
                        "Model Input v2 chunk reference targets the wrong node"
                    )
                chunks.append(chunk.text)
            canonical = "".join(chunks)
        encoded = canonical.encode("utf-8")
        if len(encoded) != node.decoded_bytes:
            raise ModelInputIntegrityError("Model Input v2 value byte count changed")
        self._decoded_bytes += len(encoded)
        if self._decoded_bytes > MODEL_INPUT_V2_MAX_DECODED_BYTES:
            raise ModelInputIntegrityError(
                "Model Input v2 decoded byte budget exceeded"
            )
        try:
            value = require_json_value(
                json.loads(canonical),
                name="rebuilt Model Input v2 JSON value",
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ModelInputIntegrityError(
                "Model Input v2 JSON value is invalid"
            ) from exc
        if (
            canonical_model_input_json(
                value,
                name="rebuilt Model Input v2 JSON value",
            )
            != canonical
        ):
            raise ModelInputIntegrityError("Model Input v2 JSON value is not canonical")
        if (
            hash_model_input_json(
                value,
                name="rebuilt Model Input v2 JSON value",
            )
            != node.value_hash
        ):
            raise ModelInputIntegrityError("Model Input v2 JSON value hash changed")
        self._value_cache[key] = value
        return value

    def _node(
        self,
        reference: ModelInputNodeReference,
        *,
        owner_position: int,
    ) -> tuple[ModelInputNode, int]:
        position = self._positions.get(reference.record_id)
        if position is None or position >= owner_position:
            raise ModelInputIntegrityError(
                "Model Input v2 node is outside reference ancestry"
            )
        record = self._records[position]
        if record.kind != MODEL_INPUT_COMPONENT_KIND or not isinstance(
            record.payload,
            ModelInputNodeBundle,
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 reference does not target a node bundle"
            )
        if record.payload_version != MODEL_INPUT_V2_PAYLOAD_VERSION:
            raise ModelInputIntegrityError(
                "Model Input v2 reference targets the wrong payload version"
            )
        if reference.ordinal >= len(record.payload.nodes):
            raise ModelInputIntegrityError("Model Input v2 node ordinal is invalid")
        node = record.payload.nodes[reference.ordinal]
        if (
            node.node_kind != reference.node_kind
            or node.content_hash != reference.content_hash
        ):
            raise ModelInputIntegrityError(
                "Model Input v2 node reference identity changed"
            )
        if hash_model_input_node(node) != node.content_hash:
            raise ModelInputIntegrityError("Model Input v2 node hash changed")
        key = (reference.record_id, reference.ordinal)
        self._resolved_nodes.add(key)
        if len(self._resolved_nodes) > MODEL_INPUT_V2_MAX_RESOLVED_NODES:
            raise ModelInputIntegrityError("Model Input v2 node budget exceeded")
        return node, position

    @staticmethod
    def _require_depth(depth: int) -> None:
        if depth > MODEL_INPUT_V2_MAX_REFERENCE_DEPTH:
            raise ModelInputIntegrityError(
                "Model Input v2 reference depth budget exceeded"
            )


__all__ = [
    "MODEL_INPUT_V2_MAX_DECODED_BYTES",
    "MODEL_INPUT_V2_MAX_REFERENCE_DEPTH",
    "MODEL_INPUT_V2_MAX_RESOLVED_NODES",
    "MODEL_INPUT_V2_MAX_SEQUENCE_ITEMS",
    "MODEL_INPUT_V2_MAX_TAIL_APPEND_ITEMS",
    "IndexedModelInputNode",
    "ModelInputV2Materialization",
    "ModelInputV2MaterializationStats",
    "ModelInputV2NodeIndex",
    "ModelInputV2Resolver",
    "ModelInputV2Writer",
    "RebuiltModelInputV2Values",
]
