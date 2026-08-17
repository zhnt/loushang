from __future__ import annotations

from pathlib import Path

import pytest

from loushang.foundation.json import JSONValue
from loushang.harness.conversation import (
    CommandExecutionRecord,
    ConversationHeader,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationPayloadCodecRegistry,
    ConversationRecord,
    ConversationRepository,
    FunctionalConversationPayloadCodec,
    OpaquePayload,
)
from loushang.harness.journal import (
    JournalCodecError,
    JournalLoadPolicy,
    JsonlJournal,
)


def _decode_text(value: JSONValue) -> str:
    if not isinstance(value, dict) or type(value.get("text")) is not str:
        raise ValueError("text payload must contain text")
    text = value["text"]
    assert isinstance(text, str)
    return text


def _registry() -> ConversationPayloadCodecRegistry:
    registry = ConversationPayloadCodecRegistry()
    registry.register(
        "test.message",
        1,
        FunctionalConversationPayloadCodec[str](
            encoder=lambda payload: {"text": payload},
            decoder=_decode_text,
        ),
    )
    return registry


def _header(conversation_id: str = "conversation-1") -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-16T00:00:00Z",
        metadata={"source": "test"},
    )


def _record(
    record_id: str,
    parent_id: str | None,
    *,
    kind: str,
    payload_version: int,
    payload: object,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=kind,
        payload_version=payload_version,
        created_at="2026-07-16T00:00:00Z",
        payload=payload,
        metadata={"position": record_id},
    )


def _journal(
    path: Path,
    registry: ConversationPayloadCodecRegistry,
) -> JsonlJournal[ConversationHeader, ConversationRecord[object]]:
    return JsonlJournal(
        path,
        header_codec=ConversationJsonlHeaderCodec(),
        record_codec=ConversationJsonlRecordCodec(registry),
        load_policy=JournalLoadPolicy(header="required"),
    )


def test_conversation_jsonl_codecs_use_stable_discriminators_and_versions() -> None:
    header = _header()
    record = _record(
        "record-1",
        None,
        kind="test.message",
        payload_version=1,
        payload="hello",
    )
    header_codec = ConversationJsonlHeaderCodec()
    record_codec = ConversationJsonlRecordCodec(_registry())

    encoded_header = header_codec.encode_header(header)
    encoded_record = record_codec.encode_record(record)

    assert encoded_header == {
        "type": "conversation",
        "conversationId": "conversation-1",
        "version": 1,
        "createdAt": "2026-07-16T00:00:00Z",
        "parentConversationId": None,
        "metadata": {"source": "test"},
    }
    assert encoded_record == {
        "type": "record",
        "recordId": "record-1",
        "parentId": None,
        "kind": "test.message",
        "payloadVersion": 1,
        "createdAt": "2026-07-16T00:00:00Z",
        "payload": {"text": "hello"},
        "metadata": {"position": "record-1"},
    }
    assert header_codec.decode_header(encoded_header) == header
    assert record_codec.decode_record(encoded_record) == record


def test_conversation_jsonl_decoder_defaults_omitted_optional_fields() -> None:
    header = ConversationJsonlHeaderCodec().decode_header(
        {
            "type": "conversation",
            "conversationId": "conversation-1",
            "version": 1,
            "createdAt": "2026-07-16T00:00:00Z",
            "futureOptionalField": {"ignored": True},
        }
    )
    record = ConversationJsonlRecordCodec(_registry()).decode_record(
        {
            "type": "record",
            "recordId": "record-1",
            "kind": "test.message",
            "payloadVersion": 1,
            "createdAt": "2026-07-16T00:00:01Z",
            "payload": {"text": "hello"},
            "futureOptionalField": {"ignored": True},
        }
    )

    assert header.parent_conversation_id is None
    assert header.metadata == {}
    assert record.parent_id is None
    assert record.metadata == {}


def test_conversation_jsonl_codec_rejects_unreleased_versions() -> None:
    with pytest.raises(
        JournalCodecError,
        match="Conversation JSONL version is unsupported",
    ):
        ConversationJsonlHeaderCodec().decode_header(
            {
                "type": "conversation",
                "conversationId": "future",
                "version": 2,
                "createdAt": "2026-07-16T00:00:00Z",
            }
        )


def test_unknown_kind_and_version_decode_as_defensive_opaque_payloads() -> None:
    registry = _registry()
    codec = ConversationJsonlRecordCodec(registry)
    encoded = {
        "type": "record",
        "recordId": "future",
        "parentId": None,
        "kind": "test.message",
        "payloadVersion": 2,
        "createdAt": "2026-07-16T00:00:00Z",
        "payload": {"nested": ["original"]},
        "metadata": {},
    }

    decoded = codec.decode_record(encoded)

    assert isinstance(decoded.payload, OpaquePayload)
    encoded["payload"]["nested"].append("source-mutated")  # type: ignore[index,union-attr]
    assert decoded.payload.value == {"nested": ["original"]}
    projected = decoded.payload.value
    assert isinstance(projected, dict)
    projected["nested"].append("result-mutated")  # type: ignore[union-attr]
    assert decoded.payload.value == {"nested": ["original"]}
    assert codec.encode_record(decoded)["payload"] == {"nested": ["original"]}

    unknown_kind = dict(encoded)
    unknown_kind["recordId"] = "other-future"
    unknown_kind["kind"] = "future.product_record"
    unknown_kind["payloadVersion"] = 1
    unknown_kind["payload"] = [1, {"still": "opaque"}]
    assert isinstance(codec.decode_record(unknown_kind).payload, OpaquePayload)


def test_required_payload_kind_rejects_an_unknown_version_instead_of_opaque() -> None:
    registry = _registry()
    registry.require_known_payload_versions("test.message")
    codec = ConversationJsonlRecordCodec(registry)
    encoded = {
        "type": "record",
        "recordId": "future",
        "parentId": None,
        "kind": "test.message",
        "payloadVersion": 2,
        "createdAt": "2026-07-16T00:00:00Z",
        "payload": {"future": True},
        "metadata": {},
    }

    with pytest.raises(JournalCodecError) as decode_error:
        codec.decode_record(encoded)
    with pytest.raises(JournalCodecError) as encode_error:
        codec.encode_record(
            _record(
                "future",
                None,
                kind="test.message",
                payload_version=2,
                payload=OpaquePayload({"future": True}),
            )
        )

    assert registry.required_kinds == ("test.message",)
    assert decode_error.value.code == "unsupported_required_payload_version"
    assert encode_error.value.code == "unsupported_required_payload_version"

    unknown_kind = dict(encoded)
    unknown_kind["kind"] = "extension.future"
    assert isinstance(codec.decode_record(unknown_kind).payload, OpaquePayload)


def test_known_corrupt_payload_fails_instead_of_becoming_opaque() -> None:
    codec = ConversationJsonlRecordCodec(_registry())

    with pytest.raises(JournalCodecError) as error:
        codec.decode_record(
            {
                "type": "record",
                "recordId": "bad",
                "parentId": None,
                "kind": "test.message",
                "payloadVersion": 1,
                "createdAt": "2026-07-16T00:00:00Z",
                "payload": {"wrong": "shape"},
                "metadata": {},
            }
        )

    assert error.value.code == "invalid_known_payload"


def test_opaque_records_survive_repository_load_rewrite_and_selected_fork(
    tmp_path: Path,
) -> None:
    registry = _registry()
    source_journal = _journal(tmp_path / "source.jsonl", registry)
    source = ConversationRepository.create(
        header=_header(),
        records=(
            _record(
                "opaque-root",
                None,
                kind="future.root",
                payload_version=1,
                payload=OpaquePayload({"future": {"root": True}}),
            ),
            _record(
                "known-child",
                "opaque-root",
                kind="test.message",
                payload_version=1,
                payload="known",
            ),
            _record(
                "opaque-side",
                "opaque-root",
                kind="future.side",
                payload_version=3,
                payload=OpaquePayload(["side"]),
            ),
            _record(
                "opaque-leaf",
                "known-child",
                kind="test.message",
                payload_version=2,
                payload=OpaquePayload({"futureVersion": 2}),
            ),
        ),
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )
    source_journal.rewrite(source.records, header=source.header)

    loaded_snapshot = source_journal.load()
    assert loaded_snapshot.header is not None
    loaded = ConversationRepository.create(
        header=loaded_snapshot.header,
        records=loaded_snapshot.records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )
    assert loaded.records == source.records
    assert isinstance(loaded.get("opaque-root").payload, OpaquePayload)  # type: ignore[union-attr]
    assert isinstance(loaded.get("opaque-side").payload, OpaquePayload)  # type: ignore[union-attr]
    assert isinstance(loaded.get("opaque-leaf").payload, OpaquePayload)  # type: ignore[union-attr]

    source_journal.rewrite(loaded.records, header=loaded.header)
    rewritten_snapshot = source_journal.load()
    assert rewritten_snapshot.header is not None
    rewritten = ConversationRepository.create(
        header=rewritten_snapshot.header,
        records=rewritten_snapshot.records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )
    assert rewritten.records == loaded.records

    fork_journal = _journal(tmp_path / "fork.jsonl", registry)
    forked = loaded.fork(
        header=_header("conversation-fork"),
        leaf_id="opaque-leaf",
    )
    fork_journal.rewrite(forked.records, header=forked.header)
    assert [record.record_id for record in forked.records] == [
        "opaque-root",
        "known-child",
        "opaque-leaf",
    ]
    fork_snapshot = fork_journal.load()
    assert fork_snapshot.header is not None
    reloaded_fork = ConversationRepository.create(
        header=fork_snapshot.header,
        records=fork_snapshot.records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )
    assert reloaded_fork.records == forked.records
    assert isinstance(reloaded_fork.records[0].payload, OpaquePayload)
    assert isinstance(reloaded_fork.records[-1].payload, OpaquePayload)


def test_payload_registry_rejects_duplicate_keys_and_unregistered_known_values() -> (
    None
):
    registry = _registry()
    codec = FunctionalConversationPayloadCodec[str](
        encoder=lambda payload: payload,
        decoder=lambda value: str(value),
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register("test.message", 1, codec)
    with pytest.raises(JournalCodecError) as error:
        registry.encode("future.kind", 1, {"not": "opaque"})

    assert error.value.code == "unregistered_payload_codec"


@pytest.mark.parametrize("payload_version", [True, 0, -1, 1.5])
def test_conversation_record_requires_positive_integer_payload_version(
    payload_version: object,
) -> None:
    error = TypeError if payload_version in {True, 1.5} else ValueError
    with pytest.raises(error):
        ConversationRecord(
            record_id="record-1",
            parent_id=None,
            kind="test.message",
            payload_version=payload_version,  # type: ignore[arg-type]
            created_at="2026-07-16T00:00:00Z",
            payload="hello",
        )


def test_conversation_metadata_requires_strict_json() -> None:
    with pytest.raises(TypeError, match="JSON-safe"):
        ConversationHeader(
            conversation_id="conversation-1",
            version=1,
            created_at="2026-07-16T00:00:00Z",
            metadata={"path": Path("not-json")},  # type: ignore[dict-item]
        )
    with pytest.raises(TypeError, match="JSON-safe"):
        ConversationRecord(
            record_id="record-1",
            parent_id=None,
            kind="test.message",
            payload_version=1,
            created_at="2026-07-16T00:00:00Z",
            payload="hello",
            metadata={"path": Path("not-json")},  # type: ignore[dict-item]
        )
    with pytest.raises(TypeError, match="JSON-safe"):
        CommandExecutionRecord(
            command="pwd",
            output="/workspace",
            exit_code=0,
            metadata={"path": Path("not-json")},  # type: ignore[dict-item]
        )
