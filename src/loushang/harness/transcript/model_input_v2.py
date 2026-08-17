"""Bounded indexing and reconstruction for Model Input v2 facts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.transcript.kinds import MODEL_INPUT_COMPONENT_KIND
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
    create_model_input_mapping_root,
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


@dataclass(frozen=True)
class IndexedModelInputNode:
    reference: ModelInputNodeReference
    node: ModelInputNode
    record_position: int


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
    expected_revision: int
    expected_leaf_id: str


@dataclass(frozen=True)
class _ValuePlan:
    value: JSONValue
    canonical: str
    value_hash: str


@dataclass(frozen=True)
class _SequencePlan:
    values: tuple[JSONValue, ...]
    item_plans: tuple[_ValuePlan, ...]
    prefix_hashes: tuple[str, ...]

    @property
    def final_hash(self) -> str:
        return self.prefix_hashes[-1]


class ModelInputV2NodeIndex:
    """Verified-location index over one selected transcript path."""

    def __init__(self, records: Sequence[AgentTranscriptRecord]) -> None:
        self._by_identity: dict[tuple[str, str], IndexedModelInputNode] = {}
        self._sequence_states: dict[tuple[int, str], IndexedModelInputNode] = {}
        self._values: dict[str, IndexedModelInputNode] = {}
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
                identity = (node.node_kind, node.content_hash)
                existing = self._by_identity.get(identity)
                if existing is not None and model_input_node_hash_basis(
                    existing.node
                ) != model_input_node_hash_basis(node):
                    raise ModelInputIntegrityError(
                        "Model Input v2 typed node hash collision"
                    )
                self._by_identity.setdefault(identity, indexed)
                if isinstance(node, ModelInputJsonValueNode):
                    prior_value = self._values.get(node.value_hash)
                    if (
                        prior_value is not None
                        and prior_value.node.content_hash != node.content_hash
                    ):
                        raise ModelInputIntegrityError(
                            "Model Input v2 JSON value hash is ambiguous"
                        )
                    self._values.setdefault(node.value_hash, indexed)
                if isinstance(node, ModelInputSequenceTailNode):
                    state = (node.total_item_count, node.sequence_hash)
                    prior = self._sequence_states.get(state)
                    if (
                        prior is not None
                        and prior.node.content_hash != node.content_hash
                    ):
                        raise ModelInputIntegrityError(
                            "Model Input v2 sequence state is ambiguous"
                        )
                    self._sequence_states.setdefault(state, indexed)

    def find_node(self, node: ModelInputNode) -> IndexedModelInputNode | None:
        indexed = self._by_identity.get((node.node_kind, node.content_hash))
        if indexed is not None and model_input_node_hash_basis(
            indexed.node
        ) != model_input_node_hash_basis(node):
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
            identity = (node.node_kind, node.content_hash)
            existing = self._by_identity.get(identity)
            if existing is not None and model_input_node_hash_basis(
                existing.node
            ) != model_input_node_hash_basis(node):
                raise ModelInputIntegrityError(
                    "Model Input v2 typed node hash collision"
                )
            self._by_identity.setdefault(identity, indexed)
            if isinstance(node, ModelInputJsonValueNode):
                prior_value = self._values.get(node.value_hash)
                if (
                    prior_value is not None
                    and prior_value.node.content_hash != node.content_hash
                ):
                    raise ModelInputIntegrityError(
                        "Model Input v2 JSON value hash is ambiguous"
                    )
                self._values.setdefault(node.value_hash, indexed)
            if isinstance(node, ModelInputSequenceTailNode):
                state = (node.total_item_count, node.sequence_hash)
                prior = self._sequence_states.get(state)
                if prior is not None and prior.node.content_hash != node.content_hash:
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence state is ambiguous"
                    )
                self._sequence_states.setdefault(state, indexed)
            references.append(reference)
        return tuple(references)


class ModelInputV2Writer:
    """Materialize one v2 request using only verified active-path ancestors."""

    def __init__(
        self,
        *,
        transcript: AgentTranscriptUnitOfWork,
        expected_revision: int,
        expected_leaf_id: str,
        max_encoded_record_bytes: int,
    ) -> None:
        self._transcript = transcript
        self._expected_revision = expected_revision
        self._expected_leaf_id = expected_leaf_id
        self._max_encoded_record_bytes = max_encoded_record_bytes
        active_records = transcript.active_path()
        self._index = ModelInputV2NodeIndex(active_records)
        self._existing_resolver = ModelInputV2Resolver(active_records)
        self._existing_owner_position = len(active_records)
        self._value_plans: dict[str, _ValuePlan] = {}
        self._value_references: dict[str, ModelInputNodeReference] = {}

    async def materialize(
        self,
        *,
        logical_input: Mapping[str, JSONValue],
        prepared_payload: Mapping[str, JSONValue],
        model_visible_headers: Mapping[str, str],
    ) -> ModelInputV2Materialization:
        logical = dict(logical_input)
        prepared = dict(prepared_payload)
        headers = dict(model_visible_headers)
        mapping_values = (logical, prepared)
        sequence_plans: dict[tuple[int, str], _SequencePlan] = {}
        mapping_sequences: dict[tuple[int, str], tuple[int, str]] = {}

        for mapping_index, mapping in enumerate(mapping_values):
            for name, value in mapping.items():
                if isinstance(value, list):
                    plan = self._sequence_plan(value)
                    state = (len(plan.values), plan.final_hash)
                    prior_plan = sequence_plans.get(state)
                    if prior_plan is not None and prior_plan.values != plan.values:
                        raise ModelInputIntegrityError(
                            "Model Input v2 sequence hash collision"
                        )
                    sequence_plans.setdefault(state, plan)
                    mapping_sequences[(mapping_index, name)] = state
                else:
                    self._collect_value(value)
        headers_plan = self._collect_value(headers)
        await self._materialize_values()

        sequence_nodes: dict[tuple[int, str], ModelInputSequenceTailNode] = {}
        sequence_refs: dict[tuple[int, str], ModelInputNodeReference] = {}
        for state, plan in sequence_plans.items():
            indexed_sequence = self._index.find_sequence_state(*state)
            if indexed_sequence is not None:
                values, sequence_hash = (
                    self._existing_resolver.resolve_sequence_reference(
                        indexed_sequence.reference,
                        owner_position=self._existing_owner_position,
                    )
                )
                if values != list(plan.values) or sequence_hash != plan.final_hash:
                    raise ModelInputIntegrityError(
                        "Model Input v2 sequence state failed verification"
                    )
                sequence_refs[state] = indexed_sequence.reference
                continue
            prefix_count, previous_ref = self._longest_sequence_prefix(plan)
            if len(plan.values) - prefix_count > MODEL_INPUT_V2_MAX_TAIL_APPEND_ITEMS:
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

        roots: list[ModelInputMappingRootNode] = []
        for mapping_index, mapping in enumerate(mapping_values):
            entries = []
            for name, value in mapping.items():
                field_state = mapping_sequences.get((mapping_index, name))
                reference = (
                    sequence_refs[field_state]
                    if field_state is not None
                    else self._value_references[self._value_plan(value).value_hash]
                )
                entries.append(ModelInputMappingEntry(name, reference))
            roots.append(create_model_input_mapping_root(mapping, entries))
        await self._materialize_nodes(tuple(roots))
        root_refs = []
        for root in roots:
            indexed = self._index.find_node(root)
            if indexed is None:
                raise ModelInputIntegrityError(
                    "Model Input v2 mapping root was not materialized"
                )
            root_refs.append(indexed.reference)
        return ModelInputV2Materialization(
            logical_root=root_refs[0],
            prepared_payload_root=root_refs[1],
            model_visible_headers_root=self._value_references[headers_plan.value_hash],
            expected_revision=self._expected_revision,
            expected_leaf_id=self._expected_leaf_id,
        )

    def _collect_value(self, value: object) -> _ValuePlan:
        plan = self._value_plan(value)
        existing = self._value_plans.get(plan.value_hash)
        if existing is not None and existing.canonical != plan.canonical:
            raise ModelInputIntegrityError("Model Input v2 JSON value hash collision")
        self._value_plans.setdefault(plan.value_hash, plan)
        return plan

    def _sequence_plan(self, values: Sequence[JSONValue]) -> _SequencePlan:
        if len(values) > MODEL_INPUT_V2_MAX_SEQUENCE_ITEMS:
            raise ModelInputRecordSizeError(
                "Model Input v2 sequence exceeds the item budget"
            )
        item_plans = tuple(self._collect_value(value) for value in values)
        prefix_hashes = [model_input_empty_sequence_hash()]
        for plan in item_plans:
            prefix_hashes.append(
                extend_model_input_sequence_hash(prefix_hashes[-1], plan.value_hash)
            )
        return _SequencePlan(tuple(values), item_plans, tuple(prefix_hashes))

    async def _materialize_values(self) -> None:
        total_unique_bytes = sum(
            len(plan.canonical.encode("utf-8")) for plan in self._value_plans.values()
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
            values, sequence_hash = self._existing_resolver.resolve_sequence_reference(
                indexed.reference,
                owner_position=self._existing_owner_position,
            )
            if values != list(plan.values[:item_count]) or (
                sequence_hash != plan.prefix_hashes[item_count]
            ):
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
        self._existing_resolver = ModelInputV2Resolver(active_records)
        self._existing_owner_position = len(active_records)

    @staticmethod
    def _value_plan(value: object) -> _ValuePlan:
        canonical = canonical_model_input_json(value, name="Model Input v2 value")
        encoded_bytes = len(canonical.encode("utf-8"))
        if encoded_bytes > MODEL_INPUT_V2_MAX_DECODED_BYTES:
            raise ModelInputRecordSizeError(
                "Model Input v2 value exceeds the decoded-byte budget"
            )
        decoded = require_json_value(
            json.loads(canonical),
            name="Model Input v2 value",
        )
        return _ValuePlan(
            value=decoded,
            canonical=canonical,
            value_hash=hash_model_input_json(decoded, name="Model Input v2 value"),
        )


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
    "ModelInputV2NodeIndex",
    "ModelInputV2Resolver",
    "ModelInputV2Writer",
    "RebuiltModelInputV2Values",
]
