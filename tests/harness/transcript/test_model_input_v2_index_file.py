from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from loushang.ai.types import UserMessage
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.conversation.jsonl_codec import (
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
)
from loushang.harness.journal import JournalFileError, JsonlSnapshot
from loushang.harness.transcript.codecs import (
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    agent_transcript_file_lock,
    agent_transcript_journal,
    create_agent_transcript_file_store,
)
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    MODEL_INPUT_COMPONENT_KIND,
)
from loushang.harness.transcript.model_input_v2 import ModelInputV2NodeIndex
from loushang.harness.transcript.model_input_v2_index_file import (
    _manifest_checksum,
    _projection_cache_path,
    load_agent_transcript_snapshot_with_index,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    DeferredModelInputNodeBundle,
    ModelInputNodeBundle,
    ModelInputNodeReference,
    create_model_input_json_value,
    create_model_input_sequence_tail,
    extend_model_input_sequence_hash,
    model_input_empty_sequence_hash,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

_HEADER_CODEC = ConversationJsonlHeaderCodec()
_RECORD_CODEC = ConversationJsonlRecordCodec(create_agent_transcript_payload_registry())
_COMPATIBILITY_TOKEN = "test:model-input-v2-index:v1"


def _header(*, metadata: dict[str, JSONValue] | None = None) -> ConversationHeader:
    return ConversationHeader(
        conversation_id="conversation-1",
        version=1,
        created_at="2026-08-20T00:00:00Z",
        metadata=metadata or {},
    )


def _model_input_records() -> tuple[AgentTranscriptRecord, ...]:
    shared = create_model_input_json_value(
        {"role": "user", "content": "authority stays in JSONL"}
    )
    return (
        ConversationRecord(
            record_id="model-input-1",
            parent_id=None,
            kind=MODEL_INPUT_COMPONENT_KIND,
            payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            created_at="2026-08-20T00:00:01Z",
            payload=ModelInputNodeBundle((shared,)),
            metadata={},
        ),
        ConversationRecord(
            record_id="model-input-2",
            parent_id="model-input-1",
            kind=MODEL_INPUT_COMPONENT_KIND,
            payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            created_at="2026-08-20T00:00:02Z",
            payload=ModelInputNodeBundle((shared,)),
            metadata={},
        ),
    )


def _message_record(record_id: str, *, parent_id: str) -> AgentTranscriptRecord:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-08-20T00:00:03Z",
        payload=UserMessage(role="user", content="tail", timestamp=1.0),
        metadata={},
    )


def _sequence_records() -> tuple[AgentTranscriptRecord, ...]:
    value = create_model_input_json_value({"role": "user", "content": "one"})
    value_reference = ModelInputNodeReference(
        record_id="value-bundle",
        ordinal=0,
        node_kind=value.node_kind,
        content_hash=value.content_hash,
    )
    sequence = create_model_input_sequence_tail(
        previous_tail=None,
        appended_items=(value_reference,),
        total_item_count=1,
        sequence_hash=extend_model_input_sequence_hash(
            model_input_empty_sequence_hash(),
            value.value_hash,
        ),
    )
    return (
        ConversationRecord(
            record_id="value-bundle",
            parent_id=None,
            kind=MODEL_INPUT_COMPONENT_KIND,
            payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            created_at="2026-08-20T00:00:01Z",
            payload=ModelInputNodeBundle((value,)),
            metadata={},
        ),
        ConversationRecord(
            record_id="sequence-bundle",
            parent_id="value-bundle",
            kind=MODEL_INPUT_COMPONENT_KIND,
            payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
            created_at="2026-08-20T00:00:02Z",
            payload=ModelInputNodeBundle((sequence,)),
            metadata={},
        ),
    )


def _write_transcript(
    path: Path,
    records: tuple[AgentTranscriptRecord, ...],
    *,
    header: ConversationHeader | None = None,
) -> None:
    envelopes = [
        _HEADER_CODEC.encode_header(header or _header()),
        *(_RECORD_CODEC.encode_record(record) for record in records),
    ]
    path.write_text(
        "".join(
            json.dumps(
                envelope,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for envelope in envelopes
        ),
        encoding="utf-8",
    )


def _append_record(path: Path, record: AgentTranscriptRecord) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                _RECORD_CODEC.encode_record(record),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )


def _indexed_loader(
    path: Path,
    *,
    compatibility_token: str = _COMPATIBILITY_TOKEN,
    strict_calls: list[None] | None = None,
) -> Callable[[], JsonlSnapshot[ConversationHeader, AgentTranscriptRecord]]:
    def load() -> JsonlSnapshot[ConversationHeader, AgentTranscriptRecord]:
        def strict_load() -> JsonlSnapshot[
            ConversationHeader,
            AgentTranscriptRecord,
        ]:
            if strict_calls is not None:
                strict_calls.append(None)
            return agent_transcript_journal(path).load()

        return load_agent_transcript_snapshot_with_index(
            path,
            strict_loader=strict_load,
            header_codec=_HEADER_CODEC,
            record_codec=_RECORD_CODEC,
            lock_factory=agent_transcript_file_lock,
            compatibility_token=compatibility_token,
        )

    return load


def _rewrite_manifest(
    path: Path, mutate: Callable[[dict[str, JSONValue]], None]
) -> None:
    cache_path = _projection_cache_path(path)
    manifest = cast(
        dict[str, JSONValue],
        json.loads(cache_path.read_text(encoding="utf-8")),
    )
    mutate(manifest)
    manifest.pop("checksum")
    manifest["checksum"] = _manifest_checksum(manifest)
    cache_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_verified_index_defers_duplicate_model_input_bodies_until_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loushang.harness.transcript.model_input_v2_index_file as index_file

    path = tmp_path / "conversation.jsonl"
    records = _model_input_records()
    _write_transcript(path, records)
    strict_calls: list[None] = []
    load = _indexed_loader(path, strict_calls=strict_calls)

    first = load()
    assert strict_calls == [None]
    assert isinstance(first.records[0].payload, ModelInputNodeBundle)
    assert _projection_cache_path(path).is_file()

    decode_calls = 0
    original_decode = index_file.decode_model_input_node_bundle

    def counting_decode(value: JSONValue) -> ModelInputNodeBundle:
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(value)

    monkeypatch.setattr(index_file, "decode_model_input_node_bundle", counting_decode)
    second = load()
    assert strict_calls == [None]
    assert all(
        isinstance(record.payload, DeferredModelInputNodeBundle)
        for record in second.records
    )
    assert decode_calls == 0

    node_index = ModelInputV2NodeIndex(second.records)
    assert decode_calls == 0
    original_node = records[0].payload.nodes[0]
    assert node_index.value_hash_is_authority_verified(original_node.value_hash)
    assert node_index.find_node(original_node) is not None
    assert decode_calls == 0
    indexed = node_index.find_value(original_node.value_hash)
    assert indexed is not None
    assert indexed.node == original_node
    assert decode_calls == 1


def test_unused_deferred_index_does_not_retain_per_node_references_and_callbacks(
    tmp_path,
):
    import gc
    from functools import partial
    from types import MethodType

    from loushang.harness.transcript.model_input_v2 import IndexedModelInputNode

    path = tmp_path / "conversation.jsonl"
    records = _model_input_records()
    _write_transcript(path, records)
    load = _indexed_loader(path)
    load()
    index = ModelInputV2NodeIndex(load().records)

    def retained():
        stack, seen, references, callbacks = [index], set(), [], []
        while stack:
            value = stack.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            if isinstance(value, ModelInputNodeReference):
                references.append(value)
            if isinstance(value, partial | MethodType):
                callbacks.append(value)
            if isinstance(
                value,
                (
                    dict,
                    list,
                    tuple,
                    set,
                    ModelInputV2NodeIndex,
                    IndexedModelInputNode,
                    partial,
                    MethodType,
                ),
            ):
                stack.extend(gc.get_referents(value))
        return references, callbacks

    assert retained() == ([], []), (
        "unused historical nodes retained speculative references/callbacks"
    )
    node = records[0].payload.nodes[0]
    indexed = index.find_value(node.value_hash)
    assert indexed is not None
    reference = indexed.reference
    assert reference.record_id == records[0].record_id
    assert reference.content_hash == node.content_hash
    assert indexed.reference is reference
    assert retained() == ([reference], [])
    assert indexed.node == node


def test_invalid_or_structurally_tampered_index_falls_back_and_self_heals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conversation.jsonl"
    records = _model_input_records()
    _write_transcript(path, records)
    strict_calls: list[None] = []
    load = _indexed_loader(path, strict_calls=strict_calls)
    load()

    cache_path = _projection_cache_path(path)
    cache_path.write_text("{invalid", encoding="utf-8")
    assert len(load().records) == 2
    assert len(strict_calls) == 2
    json.loads(cache_path.read_text(encoding="utf-8"))

    def reverse_records(manifest: dict[str, JSONValue]) -> None:
        indexed_records = cast(list[JSONValue], manifest["records"])
        indexed_records.reverse()

    _rewrite_manifest(path, reverse_records)
    recovered = load()
    assert tuple(record.record_id for record in recovered.records) == (
        "model-input-1",
        "model-input-2",
    )
    assert len(strict_calls) == 3
    assert len(load().records) == 2
    assert len(strict_calls) == 3

    def change_node_identity(manifest: dict[str, JSONValue]) -> None:
        indexed_records = cast(list[dict[str, JSONValue]], manifest["records"])
        nodes = cast(list[dict[str, JSONValue]], indexed_records[0]["modelInputNodes"])
        nodes[0]["contentHash"] = "sha256:" + "0" * 64

    _rewrite_manifest(path, change_node_identity)
    assert len(load().records) == 2
    assert len(strict_calls) == 4


def test_sequence_chain_verification_uses_authority_bound_link_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loushang.harness.transcript.model_input_v2_index_file as index_file

    path = tmp_path / "conversation.jsonl"
    records = _sequence_records()
    _write_transcript(path, records)
    load = _indexed_loader(path)
    load()

    decode_calls = 0
    original_decode = index_file.decode_model_input_node_bundle

    def counting_decode(value: JSONValue) -> ModelInputNodeBundle:
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(value)

    monkeypatch.setattr(index_file, "decode_model_input_node_bundle", counting_decode)
    indexed_snapshot = load()
    node_index = ModelInputV2NodeIndex(indexed_snapshot.records)
    value = records[0].payload.nodes[0]
    sequence = records[1].payload.nodes[0]
    node_index.mark_value_verified(value.value_hash, value.inline_json)
    indexed_sequence = node_index.find_sequence_state(
        sequence.total_item_count,
        sequence.sequence_hash,
    )
    assert indexed_sequence is not None

    assert node_index.verify_sequence_reference(
        indexed_sequence.reference,
        owner_position=len(records),
    ) == ((value.value_hash,), sequence.sequence_hash)
    assert decode_calls == 0


def test_changed_prefix_and_compatibility_token_force_strict_rebuild(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conversation.jsonl"
    records = _model_input_records()
    _write_transcript(path, records)
    strict_calls: list[None] = []
    _indexed_loader(path, strict_calls=strict_calls)()

    _write_transcript(path, records, header=_header(metadata={"changed": True}))
    changed = _indexed_loader(path, strict_calls=strict_calls)()
    assert changed.header is not None
    assert changed.header.metadata == {"changed": True}
    assert len(strict_calls) == 2

    _indexed_loader(
        path,
        compatibility_token="test:model-input-v2-index:v2",
        strict_calls=strict_calls,
    )()
    assert len(strict_calls) == 3


def test_valid_appended_tail_is_strictly_decoded_without_prefix_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conversation.jsonl"
    records = _model_input_records()
    _write_transcript(path, records)
    strict_calls: list[None] = []
    load = _indexed_loader(path, strict_calls=strict_calls)
    load()

    _append_record(path, _message_record("tail-message", parent_id="model-input-2"))
    extended = load()
    assert tuple(record.record_id for record in extended.records) == (
        "model-input-1",
        "model-input-2",
        "tail-message",
    )
    assert strict_calls == [None]
    manifest = json.loads(_projection_cache_path(path).read_text(encoding="utf-8"))
    assert manifest["projectedSize"] == path.stat().st_size


def test_oversized_index_tail_falls_back_to_strict_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loushang.harness.transcript.model_input_v2_index_file as index_file

    path = tmp_path / "conversation.jsonl"
    records = _model_input_records()
    _write_transcript(path, records)
    strict_calls: list[None] = []
    load = _indexed_loader(path, strict_calls=strict_calls)
    load()
    _append_record(path, _message_record("tail-message", parent_id="model-input-2"))
    monkeypatch.setattr(index_file, "_MAX_INDEXED_TAIL_BYTES", 1)

    loaded = load()
    assert loaded.records[-1].record_id == "tail-message"
    assert len(strict_calls) == 2


def test_deferred_body_rejects_authority_line_changed_after_snapshot_load(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conversation.jsonl"
    _write_transcript(path, _model_input_records())
    load = _indexed_loader(path)
    load()
    indexed_snapshot = load()
    payload = indexed_snapshot.records[0].payload
    assert isinstance(payload, DeferredModelInputNodeBundle)

    raw = path.read_bytes()
    changed = raw.replace(b"authority stays", b"authority moved", 1)
    assert changed != raw
    path.write_bytes(changed)

    with pytest.raises(ValueError, match="journal line changed after load"):
        payload.node_at(0)


def test_partial_tail_diagnostic_and_complete_corruption_preserve_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conversation.jsonl"
    _write_transcript(path, _model_input_records())
    load = _indexed_loader(path)
    load()

    with path.open("ab") as handle:
        handle.write(b'{"type":"record"')
    partial = load()
    assert tuple(item.code for item in partial.diagnostics) == ("partial_journal_tail",)

    path.write_bytes(path.read_bytes()[: -len(b'{"type":"record"')])
    with path.open("ab") as handle:
        handle.write(b'{"bad":true}\n')
    with pytest.raises(JournalFileError, match="Journal record is invalid"):
        load()


def test_product_store_removes_disposable_index_when_deleting_transcript(
    tmp_path: Path,
) -> None:
    layout = AgentTranscriptFileLayout(tmp_path)
    store = create_agent_transcript_file_store(layout)
    key = layout.key("conversation-1")
    records = _model_input_records()
    store._create_sync(
        key,
        _header(),
        records,
        operation_id="create:conversation-1",
    )
    path = layout.resolve_path(key)
    assert path is not None
    store._load_sync(key)
    assert _projection_cache_path(path).is_file()

    store._delete_sync(
        key,
        expected_revision=len(records),
        operation_id="delete:conversation-1",
    )
    assert not _projection_cache_path(path).exists()


@pytest.mark.parametrize("field", ["node_kind", "content_hash"])
def test_index_keeps_published_reference_identity_and_ancestry_checks(tmp_path, field):
    from dataclasses import replace

    from loushang.harness.transcript.model_input_types import ModelInputIntegrityError

    path = tmp_path / "conversation.jsonl"
    records = _sequence_records()
    _write_transcript(path, records)
    load = _indexed_loader(path)
    load()
    index = ModelInputV2NodeIndex(load().records)
    sequence = records[1].payload.nodes[0]
    indexed = index.find_sequence_state(
        sequence.total_item_count, sequence.sequence_hash
    )
    assert indexed is not None
    assert index.find_node(sequence) is indexed
    assert not indexed.body_is_loaded
    reference = indexed.reference
    with pytest.raises(ModelInputIntegrityError, match="outside reference ancestry"):
        index._resolve_indexed_reference(reference, owner_position=1)
    assert index._resolve_indexed_reference(reference, owner_position=2) is indexed
    changed = replace(
        reference,
        **{field: "json_chunk" if field == "node_kind" else "sha256:" + "e" * 64},
    )
    with pytest.raises(ModelInputIntegrityError, match="reference changed"):
        index._resolve_indexed_reference(changed, owner_position=2)
    # A published wrapper remains authoritative to subsequent lookups. An
    # altered identity must not be hidden by reconstructing an old scalar row.
    indexed.reference = changed
    assert (
        index.find_sequence_state(sequence.total_item_count, sequence.sequence_hash)
        is indexed
    )
    with pytest.raises(ModelInputIntegrityError, match="reference changed"):
        index._resolve_indexed_reference(reference, owner_position=2)
    with pytest.raises(ModelInputIntegrityError, match="identity changed"):
        _ = indexed.node


def test_deferred_selected_node_still_validates_unselected_sibling(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from loushang.harness.transcript import model_input_v2_codec as codec

    selected = create_model_input_json_value({"selected": True})
    sibling = create_model_input_json_value({"sibling": True})
    record = replace(
        _model_input_records()[0], payload=ModelInputNodeBundle((selected, sibling))
    )
    path = tmp_path / "conversation.jsonl"
    _write_transcript(path, (record,))
    load = _indexed_loader(path)
    load()
    bundle = load().records[0].payload
    decode = codec._decode_node
    calls = []

    def reject_sibling(raw):
        calls.append(raw["contentHash"])
        if raw["contentHash"] == sibling.content_hash:
            raise ValueError("invalid sibling")
        return decode(raw)

    monkeypatch.setattr(codec, "_decode_node", reject_sibling)
    read = bundle.node_at
    for _ in range(2):
        with pytest.raises(ValueError, match="deferred Model Input bundle is invalid"):
            read(0)
    assert calls == [selected.content_hash, sibling.content_hash] * 2
    monkeypatch.setattr(codec, "_decode_node", decode)
    assert bundle.node_at(0) == selected
