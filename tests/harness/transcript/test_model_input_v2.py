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
from loushang.harness.transcript.model_input_components import (
    ModelInputLogicalComponentReader,
)
from loushang.harness.transcript.model_input_types import (
    ModelInputIntegrityError,
    canonical_model_input_json,
    hash_model_input_json,
)
from loushang.harness.transcript.model_input_v2 import (
    ModelInputV2Resolver,
    _hash_canonical_mapping_fields,
    _hash_canonical_mapping_fields_incremental,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_CHUNK_CHARACTERS,
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


@pytest.mark.parametrize(
    "inline_json",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        "1e309",
        '"\\ud800"',
        '{"\\ud800":1}',
    ],
)
def test_inline_model_input_rejects_nonfinite_and_invalid_utf8_json(inline_json):
    node = create_model_input_json_value(None)
    with pytest.raises(ValueError, match="inline JSON is invalid"):
        replace(node, inline_json=inline_json, decoded_bytes=len(inline_json.encode()))


@pytest.mark.parametrize("inline_json", ['{"b":2,"a":1}', "[1, 2]", '"\\u4e2d"', "1e0"])
def test_inline_model_input_rejects_valid_but_noncanonical_json(inline_json):
    node = create_model_input_json_value(None)
    with pytest.raises(ValueError, match="not canonical"):
        replace(node, inline_json=inline_json, decoded_bytes=len(inline_json.encode()))


def test_inline_model_input_keeps_float_unicode_and_control_canonical_bytes():
    value = {"中文": [1e300, 1e-300, -0.0, True, None, '🚀\n\u0000"']}
    node = create_model_input_json_value(value)
    assert node.inline_json == canonical_model_input_json(value, name="test")
    assert replace(node) == node


def test_mapping_root_hash_streams_sequence_without_changing_canonical_identity():
    messages = [
        {"role": "user", "content": '中\\n"文'},
        {"role": "assistant", "content": [1e300, -0.0, True, None]},
    ]
    mapping = {"messages": messages, "empty": [], "meta": {"z": 2, "a": "🚀"}}
    fields = {
        "messages": tuple(
            canonical_model_input_json(item, name="test message") for item in messages
        ),
        "empty": (),
        "meta": canonical_model_input_json(mapping["meta"], name="test metadata"),
    }

    assert _hash_canonical_mapping_fields(fields) == hash_model_input_json(
        mapping, name="test mapping"
    )


def test_mapping_root_hash_reuses_only_verified_append_prefix() -> None:
    messages = tuple(
        canonical_model_input_json({"role": "user", "content": index}, name="item")
        for index in range(50)
    )
    first_fields = {"messages": messages, "model": '"test"'}
    first_hash, first_cache = _hash_canonical_mapping_fields_incremental(
        first_fields, previous=None, reused_items={}
    )
    assert first_hash == _hash_canonical_mapping_fields(first_fields)
    assert first_cache is not None

    appended_fields = {
        **first_fields,
        "messages": (*messages, '{"content":"tail","role":"user"}'),
    }
    appended_hash, appended_cache = _hash_canonical_mapping_fields_incremental(
        appended_fields,
        previous=first_cache,
        reused_items={"messages": len(messages)},
    )
    assert appended_hash == _hash_canonical_mapping_fields(appended_fields)
    assert appended_cache is not None
    assert appended_cache.reused_item_count == len(messages)

    changed_fields = {
        **appended_fields,
        "messages": ('{"content":"changed","role":"user"}', *messages[1:]),
    }
    changed_hash, changed_cache = _hash_canonical_mapping_fields_incremental(
        changed_fields,
        previous=first_cache,
        reused_items={"messages": 0},
    )
    assert changed_hash == _hash_canonical_mapping_fields(changed_fields)
    assert changed_cache is not None
    assert changed_cache.reused_item_count == 0

    changed_preceding = {
        "api": '"changed"',
        "messages": messages,
        "model": '"test"',
    }
    previous_with_api = {**first_fields, "api": '"original"'}
    _old_hash, previous_cache = _hash_canonical_mapping_fields_incremental(
        previous_with_api, previous=None, reused_items={}
    )
    assert previous_cache is not None
    changed_hash, changed_cache = _hash_canonical_mapping_fields_incremental(
        changed_preceding,
        previous=previous_cache,
        reused_items={"messages": len(messages)},
    )
    assert changed_hash == _hash_canonical_mapping_fields(changed_preceding)
    assert changed_cache is not None
    assert changed_cache.reused_item_count == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("decoded_bytes", 1),
        ("value_hash", "sha256:" + "e" * 64),
        ("content_hash", "sha256:" + "e" * 64),
    ],
)
def test_inline_model_input_still_checks_size_value_hash_and_node_hash(field, value):
    node = create_model_input_json_value({"input": "continue"})
    with pytest.raises(ValueError):
        replace(node, **{field: value})


def _reference(record_id: str, ordinal: int, node) -> ModelInputNodeReference:
    return ModelInputNodeReference(
        record_id=record_id,
        ordinal=ordinal,
        node_kind=node.node_kind,
        content_hash=node.content_hash,
    )


@pytest.mark.parametrize(
    "value",
    [{"role": "user", "content": "short"}, {"output": "中🚀" * 30_000}],
)
def test_planned_value_keeps_exact_inline_and_chunked_node_identity(value) -> None:
    from loushang.harness.transcript.model_input_v2_types import (
        _create_model_input_json_value_from_canonical,
    )

    canonical = canonical_model_input_json(value, name="planned test value")
    chunks = (
        tuple(
            create_model_input_json_chunk(text)
            for text in split_model_input_canonical_json(canonical)
        )
        if len(canonical) > MODEL_INPUT_V2_CHUNK_CHARACTERS
        else ()
    )
    refs = tuple(
        _reference("chunks", index, chunk) for index, chunk in enumerate(chunks)
    )
    expected = create_model_input_json_value(value, chunk_refs=refs)
    actual = _create_model_input_json_value_from_canonical(
        canonical,
        value_hash=hash_model_input_json(value, name="planned test value"),
        decoded_bytes=len(canonical.encode("utf-8")),
        chunk_refs=refs,
    )
    assert actual == expected
    with pytest.raises(ValueError, match="planned Model Input JSON value changed"):
        _create_model_input_json_value_from_canonical(
            canonical,
            value_hash="sha256:" + "0" * 64,
            decoded_bytes=len(canonical.encode("utf-8")),
            chunk_refs=refs,
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


def test_logical_component_lookup_validates_v2_root_reference() -> None:
    bundles, snapshot = _v2_graph()
    factory = AgentTranscriptRecordFactory(
        id_factory=iter(("values", "sequences", "roots", "snapshot-record")).__next__
    )
    parent_id = None
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
    snapshot_record = factory.create(
        MODEL_INPUT_PREPARED_KIND,
        snapshot,
        parent_id=parent_id,
        payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
    )
    records.append(snapshot_record)
    assert (
        ModelInputLogicalComponentReader(records).read(
            snapshot_record, "resource_evidence"
        )
        is None
    )

    corrupt = replace(
        snapshot_record,
        payload=replace(
            snapshot,
            logical_root=replace(snapshot.logical_root, content_hash="0" * 64),
        ),
    )
    with pytest.raises(ModelInputIntegrityError, match="identity changed"):
        ModelInputLogicalComponentReader([*records[:-1], corrupt]).read(
            corrupt, "resource_evidence"
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


def test_v2_chunking_preserves_large_escaped_string_boundaries() -> None:
    content = "x" * (48 * 1024) + '\\"quoted\\" \\\\ slash' + "文" * 1200
    canonical = canonical_model_input_json(
        {"content": content}, name="escaped large value"
    )
    chunks = split_model_input_canonical_json(canonical)
    assert len(chunks) > 1
    assert "".join(chunks) == canonical
    assert max(map(len, chunks)) <= MODEL_INPUT_V2_CHUNK_CHARACTERS


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
        id_factory=iter(
            ("value", *(f"tail-{index}" for index in range(1_100)))
        ).__next__
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


def test_resolver_extension_reuses_ancestry_without_reindexing_old_ids(monkeypatch):
    factory = AgentTranscriptRecordFactory()
    node = create_model_input_json_value({"text": "unchanged"})
    records = []
    for _ in range(1_000):
        records.append(
            factory.create(
                MODEL_INPUT_COMPONENT_KIND,
                ModelInputNodeBundle((node,)),
                parent_id=records[-1].record_id if records else None,
                payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            )
        )
    resolver = ModelInputV2Resolver(records)
    reference = _reference(records[0].record_id, 0, node)
    assert resolver.resolve_value_reference(reference, owner_position=len(records)) == {
        "text": "unchanged"
    }
    suffix = factory.create(
        MODEL_INPUT_COMPONENT_KIND,
        ModelInputNodeBundle((node,)),
        parent_id=records[-1].record_id,
        payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
    )
    record_type = type(records[0])
    original_getattribute = record_type.__getattribute__
    old_records = {id(record) for record in records}
    old_id_reads = []

    def counted_getattribute(record, name):
        if name == "record_id" and id(record) in old_records:
            old_id_reads.append(id(record))
        return original_getattribute(record, name)

    monkeypatch.setattr(record_type, "__getattribute__", counted_getattribute)
    extended = resolver._with_extended_ancestry((*records, suffix))
    assert not old_id_reads
    assert extended._value_cache == {}
    assert extended._sequence_cache == {}
    assert extended._mapping_cache == {}
    assert extended._resolved_nodes == set()
    assert extended._decoded_bytes == 0
    assert extended.position_of(suffix.record_id) == len(records)
    assert resolver.position_of(suffix.record_id) is None
    assert resolver._value_cache
    value = extended.resolve_value_reference(reference, owner_position=len(records) + 1)
    value["text"] = "caller mutation"
    assert resolver.resolve_value_reference(reference, owner_position=len(records)) == {
        "text": "unchanged"
    }


@pytest.mark.parametrize(
    "change", ["shortened", "replaced_prefix", "duplicate_old", "duplicate_suffix"]
)
def test_resolver_extension_rejects_changed_ancestry_atomically(change):
    factory = AgentTranscriptRecordFactory()
    node = create_model_input_json_value("value")
    first = factory.create(
        MODEL_INPUT_COMPONENT_KIND, ModelInputNodeBundle((node,)), parent_id=None
    )
    second = factory.create(
        MODEL_INPUT_COMPONENT_KIND,
        ModelInputNodeBundle((node,)),
        parent_id=first.record_id,
    )
    resolver = ModelInputV2Resolver((first, second))
    if change == "shortened":
        changed = (first,)
    elif change == "replaced_prefix":
        changed = (replace(first), second)
    elif change == "duplicate_old":
        changed = (first, second, first)
    else:
        suffix = replace(second, record_id="suffix")
        changed = (first, second, suffix, suffix)
    with pytest.raises(ModelInputIntegrityError):
        resolver._with_extended_ancestry(changed)
    assert resolver.position_of(first.record_id) == 0
    assert resolver.position_of(second.record_id) == 1
    assert resolver.position_of("suffix") is None
