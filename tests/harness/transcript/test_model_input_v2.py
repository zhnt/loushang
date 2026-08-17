from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.journal import JournalCodecError
from loushang.harness.transcript.codecs import (
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import (
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_input import rebuild_model_input
from loushang.harness.transcript.model_input_types import (
    canonical_model_input_json,
    hash_model_input_json,
)
from loushang.harness.transcript.model_input_v2 import ModelInputV2Resolver
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    ModelInputMappingEntry,
    ModelInputNodeBundle,
    ModelInputNodeReference,
    ModelInputSnapshotV2,
    create_model_input_json_chunk,
    create_model_input_json_value,
    create_model_input_mapping_root,
    create_model_input_sequence_tail,
    estimate_model_input_node_wire_bytes,
    extend_model_input_sequence_hash,
    model_input_empty_sequence_hash,
    split_model_input_canonical_json,
)
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory


def _reference(record_id: str, ordinal: int, node) -> ModelInputNodeReference:
    return ModelInputNodeReference(
        record_id=record_id,
        ordinal=ordinal,
        node_kind=node.node_kind,
        content_hash=node.content_hash,
    )


def _v2_graph():
    message = {"role": "user", "content": "hello"}
    message_node = create_model_input_json_value(message)
    message_ref = _reference("values", 0, message_node)
    sequence_hash = extend_model_input_sequence_hash(
        model_input_empty_sequence_hash(),
        message_node.value_hash,
    )
    messages = create_model_input_sequence_tail(
        previous_tail=None,
        appended_items=(message_ref,),
        total_item_count=1,
        sequence_hash=sequence_hash,
    )
    messages_ref = _reference("sequences", 0, messages)
    options_node = create_model_input_json_value({})
    options_ref = _reference("values", 1, options_node)
    logical = {
        "system_prompt": None,
        "messages": [message],
        "tools": [],
        "request_options": {},
    }
    system_node = create_model_input_json_value(None)
    empty_sequence = create_model_input_sequence_tail(
        previous_tail=None,
        appended_items=(),
        total_item_count=0,
        sequence_hash=model_input_empty_sequence_hash(),
    )
    logical_root = create_model_input_mapping_root(
        logical,
        (
            ModelInputMappingEntry(
                "system_prompt",
                _reference("values", 2, system_node),
            ),
            ModelInputMappingEntry("messages", messages_ref),
            ModelInputMappingEntry(
                "tools",
                _reference("sequences", 1, empty_sequence),
            ),
            ModelInputMappingEntry("request_options", options_ref),
        ),
    )
    prepared = {"messages": [message], "model": "model-1"}
    model_node = create_model_input_json_value("model-1")
    prepared_root = create_model_input_mapping_root(
        prepared,
        (
            ModelInputMappingEntry("messages", messages_ref),
            ModelInputMappingEntry(
                "model",
                _reference("values", 3, model_node),
            ),
        ),
    )
    bundles = (
        ModelInputNodeBundle((message_node, options_node, system_node, model_node)),
        ModelInputNodeBundle((messages, empty_sequence)),
        ModelInputNodeBundle((logical_root, prepared_root)),
    )
    snapshot = ModelInputSnapshotV2(
        snapshot_id="snapshot-v2",
        invocation_id="invocation-v2",
        attempt=1,
        purpose="main_turn",
        product_id="coding",
        runtime_id="runtime-1",
        mount_generation=3,
        profile_fingerprint="a" * 64,
        registration_revision="b" * 64,
        conversation_id="conversation-1",
        source_leaf_id="source-record",
        source_revision=1,
        commit_revision=5,
        provider_id="provider-1",
        model_id="model-1",
        api_id="api-1",
        endpoint_id="endpoint-1",
        logical_root=_reference("roots", 0, logical_root),
        prepared_payload_root=_reference("roots", 1, prepared_root),
        model_visible_headers_root=options_ref,
        logical_input_hash=hash_model_input_json(
            logical,
            name="v2 logical input",
        ),
        prepared_payload_hash=hash_model_input_json(
            {"model_visible_headers": {}, "payload": prepared},
            name="v2 prepared input",
        ),
    )
    return bundles, snapshot


def test_v2_node_bundles_and_snapshot_round_trip_through_payload_version_two() -> None:
    registry = create_agent_transcript_payload_registry()
    bundles, snapshot = _v2_graph()

    for bundle in bundles:
        encoded = registry.encode(
            MODEL_INPUT_COMPONENT_KIND,
            MODEL_INPUT_V2_PAYLOAD_VERSION,
            bundle,
        )
        assert (
            registry.decode(
                MODEL_INPUT_COMPONENT_KIND,
                MODEL_INPUT_V2_PAYLOAD_VERSION,
                encoded,
            )
            == bundle
        )
    encoded_snapshot = registry.encode(
        MODEL_INPUT_PREPARED_KIND,
        MODEL_INPUT_V2_PAYLOAD_VERSION,
        snapshot,
    )
    assert (
        registry.decode(
            MODEL_INPUT_PREPARED_KIND,
            MODEL_INPUT_V2_PAYLOAD_VERSION,
            encoded_snapshot,
        )
        == snapshot
    )


def test_v2_snapshot_rebuilds_from_parent_linked_bundle_ancestors() -> None:
    async def scenario() -> None:
        bundles, snapshot = _v2_graph()
        store = MemoryConversationStore(record_id=lambda record: record.record_id)
        transcript = await AgentTranscriptUnitOfWork.create(
            store,
            ConversationKey("test", "conversation-1"),
            ConversationHeader(
                conversation_id="conversation-1",
                version=1,
                created_at="2026-08-16T00:00:00Z",
            ),
            id_factory=iter(("source-record",)).__next__,
        )
        source = await transcript.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        factory = AgentTranscriptRecordFactory(
            id_factory=iter(
                ("values", "sequences", "roots", "snapshot-record")
            ).__next__,
        )
        parent_id = source.record.record_id
        records = []
        for bundle in bundles:
            record = factory.create(
                MODEL_INPUT_COMPONENT_KIND,
                bundle,
                parent_id=parent_id,
                payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            )
            records.append(record)
            parent_id = record.record_id
        records.append(
            factory.create(
                MODEL_INPUT_PREPARED_KIND,
                snapshot,
                parent_id=parent_id,
                payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            )
        )
        await transcript.commit_batch(records)

        rebuilt = rebuild_model_input(transcript, snapshot.snapshot_id)

        assert rebuilt.logical_input == {
            "system_prompt": None,
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [],
            "request_options": {},
        }
        assert rebuilt.prepared_payload == {
            "messages": [{"role": "user", "content": "hello"}],
            "model": "model-1",
        }
        assert rebuilt.model_visible_headers == {}

    asyncio.run(scenario())


def test_v2_large_canonical_json_splits_into_record_safe_unicode_chunks() -> None:
    value = {"image": "图" * 200_000}
    canonical = canonical_model_input_json(value, name="large v2 value")
    chunks = tuple(
        create_model_input_json_chunk(text)
        for text in split_model_input_canonical_json(canonical)
    )

    assert len(chunks) > 1
    assert "".join(chunk.text for chunk in chunks) == canonical
    assert max(estimate_model_input_node_wire_bytes(chunk) for chunk in chunks) < (
        1024 * 1024
    )


def test_v2_chunking_aligns_identical_large_json_strings_across_shapes() -> None:
    image = "A" * 200_000
    first = canonical_model_input_json(
        {"logical": {"data": image}},
        name="logical image",
    )
    second = canonical_model_input_json(
        {"prepared": [{"source": {"data": image}}]},
        name="prepared image",
    )
    first_chunks = split_model_input_canonical_json(first)
    second_chunks = split_model_input_canonical_json(second)

    assert first_chunks[1:-1] == second_chunks[1:-1]
    assert sum(len(chunk) for chunk in first_chunks[1:-1]) >= len(image)
    assert "".join(first_chunks) == first
    assert "".join(second_chunks) == second


def test_v2_node_hash_is_stable_across_bundle_locations() -> None:
    item = create_model_input_json_value({"value": 1})
    first_ref = _reference("bundle-a", 0, item)
    second_ref = _reference("bundle-b", 7, item)
    sequence_hash = extend_model_input_sequence_hash(
        model_input_empty_sequence_hash(),
        item.value_hash,
    )

    first = create_model_input_sequence_tail(
        previous_tail=None,
        appended_items=(first_ref,),
        total_item_count=1,
        sequence_hash=sequence_hash,
    )
    second = create_model_input_sequence_tail(
        previous_tail=None,
        appended_items=(second_ref,),
        total_item_count=1,
        sequence_hash=sequence_hash,
    )

    assert first.content_hash == second.content_hash


def test_v2_known_node_tampering_fails_instead_of_becoming_opaque() -> None:
    registry = create_agent_transcript_payload_registry()
    chunk = create_model_input_json_chunk("original")
    encoded = registry.encode(
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_V2_PAYLOAD_VERSION,
        ModelInputNodeBundle((chunk,)),
    )
    encoded["nodes"][0]["text"] = "tampered"  # type: ignore[index,union-attr]

    with pytest.raises(JournalCodecError) as error:
        registry.decode(
            MODEL_INPUT_COMPONENT_KIND,
            MODEL_INPUT_V2_PAYLOAD_VERSION,
            encoded,
        )

    assert error.value.code == "invalid_known_payload"


def test_v2_snapshot_rejects_wrong_typed_roots() -> None:
    _, snapshot = _v2_graph()

    with pytest.raises(ValueError, match="mapping_root"):
        replace(
            snapshot,
            logical_root=replace(
                snapshot.logical_root,
                node_kind="json_value",
            ),
        )


def test_v2_resolver_rebuilds_a_tail_chain_beyond_python_recursion_depth() -> None:
    item = create_model_input_json_value({"role": "user", "content": "same"})
    factory = AgentTranscriptRecordFactory(
        id_factory=iter(("value", *(f"tail-{index}" for index in range(1_100)))).__next__
    )
    value_record = factory.create(
        MODEL_INPUT_COMPONENT_KIND,
        ModelInputNodeBundle((item,)),
        parent_id=None,
        payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
    )
    item_ref = _reference(value_record.record_id, 0, item)
    records = [value_record]
    previous = None
    sequence_hash = model_input_empty_sequence_hash()
    for item_count in range(1, 1_101):
        sequence_hash = extend_model_input_sequence_hash(
            sequence_hash,
            item.value_hash,
        )
        tail = create_model_input_sequence_tail(
            previous_tail=previous,
            appended_items=(item_ref,),
            total_item_count=item_count,
            sequence_hash=sequence_hash,
        )
        record = factory.create(
            MODEL_INPUT_COMPONENT_KIND,
            ModelInputNodeBundle((tail,)),
            parent_id=records[-1].record_id,
            payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
        )
        records.append(record)
        previous = _reference(record.record_id, 0, tail)

    assert previous is not None
    values, rebuilt_hash = ModelInputV2Resolver(records).resolve_sequence_reference(
        previous,
        owner_position=len(records),
    )
    assert len(values) == 1_100
    assert rebuilt_hash == sequence_hash
