"""Conformance tests for neutral conversation Store providers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from loushang.harness.conversation import (
    ConversationBatchStore,
    ConversationKey,
    ConversationStore,
    FileConversationStore,
    MemoryConversationStore,
    StoreAlreadyExistsError,
    StoreCommitOutcomeUnknown,
    StoreConflictError,
    StoreDataError,
    StoreNotFoundError,
    StoreOperationConflictError,
)
from loushang.harness.journal import JournalLoadPolicy, JsonlJournal


@dataclass(frozen=True)
class _Header:
    title: str


@dataclass(frozen=True)
class _Record:
    record_id: str
    text: str


class _HeaderCodec:
    def encode_header(self, header: _Header):
        return {"type": "conversation", "title": header.title}

    def decode_header(self, value):
        if value.get("type") != "conversation":
            raise ValueError("invalid header")
        return _Header(title=str(value["title"]))


class _RecordCodec:
    def encode_record(self, record: _Record):
        return {"recordId": record.record_id, "text": record.text}

    def decode_record(self, value):
        return _Record(record_id=str(value["recordId"]), text=str(value["text"]))


_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
_StoreFactory = Callable[[], ConversationStore[_Header, _Record]]


def _record_id(record: _Record) -> str:
    return record.record_id


def _operation(action: str, key: ConversationKey, suffix: str = "") -> str:
    return f"{action}:{key.namespace}:{key.conversation_id}:{suffix}"


def _memory_factory(
    *,
    record_id: Callable[[_Record], str | None] = _record_id,
) -> _StoreFactory:
    def create() -> ConversationStore[_Header, _Record]:
        return MemoryConversationStore(
            clock=lambda: _NOW,
            record_id=record_id,
        )

    return create


def _file_factory(
    tmp_path: Path,
    *,
    record_id: Callable[[_Record], str | None] = _record_id,
) -> _StoreFactory:
    root = tmp_path / "conversations"

    def path_for(key: ConversationKey) -> Path:
        return root / key.namespace / f"{key.conversation_id}.jsonl"

    def journal_factory(path: Path) -> JsonlJournal[_Header, _Record]:
        return JsonlJournal(
            path,
            header_codec=_HeaderCodec(),
            record_codec=_RecordCodec(),
            load_policy=JournalLoadPolicy(header="required"),
        )

    def create() -> ConversationStore[_Header, _Record]:
        return FileConversationStore(
            create_path=path_for,
            resolve_path=lambda key: path_for(key),
            scan_paths=lambda namespace: (root / namespace).glob("*.jsonl"),
            key_for_path=lambda namespace, path: ConversationKey(
                namespace,
                path.stem,
            ),
            journal_factory=journal_factory,
            clock=lambda: _NOW,
            record_id=record_id,
        )

    return create


@pytest.fixture(params=("memory", "file"))
def store_factory(request: pytest.FixtureRequest, tmp_path: Path) -> _StoreFactory:
    if request.param == "memory":
        return _memory_factory()
    return _file_factory(tmp_path)


def test_store_implements_protocol_and_round_trips_initial_records(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        key = ConversationKey("coding", "session-1")
        records = (_Record("record-1", "first"), _Record("record-2", "second"))

        assert isinstance(store, ConversationStore)
        created = await store.create(
            key,
            _Header("Original"),
            records,
            operation_id=_operation("create", key),
        )
        load_result = await store.load(key)
        loaded = load_result.snapshot

        assert created == loaded
        assert load_result.diagnostics == ()
        assert loaded.header == _Header("Original")
        assert loaded.records == records
        assert loaded.revision == 2

    asyncio.run(scenario())


def test_append_checks_revision_before_mutation(store_factory: _StoreFactory) -> None:
    async def scenario() -> None:
        store = store_factory()
        key = ConversationKey("coding", "session-1")
        await store.create(
            key,
            _Header("Immutable"),
            operation_id=_operation("create", key),
        )

        commit_result = await store.append(
            key,
            _Record("record-1", "first"),
            expected_revision=0,
            operation_id="record-1",
        )
        receipt = commit_result.receipt
        assert receipt.revision == 1
        assert receipt.record_id == "record-1"
        assert receipt.committed_at == _NOW
        assert commit_result.diagnostics == ()

        with pytest.raises(StoreConflictError):
            await store.append(
                key,
                _Record("record-2", "stale"),
                expected_revision=0,
                operation_id="record-2",
            )

        loaded = (await store.load(key)).snapshot
        assert loaded.header == _Header("Immutable")
        assert loaded.records == (_Record("record-1", "first"),)
        assert loaded.revision == 1

    asyncio.run(scenario())


def test_batch_append_is_contiguous_idempotent_and_single_append_compatible(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        assert isinstance(store, ConversationBatchStore)
        key = ConversationKey("coding", "batch")
        await store.create(
            key,
            _Header("Batch"),
            operation_id=_operation("create", key),
        )
        with pytest.raises(StoreOperationConflictError, match="must be unique"):
            await store.append_batch(
                key,
                (_Record("duplicate", "first"), _Record("duplicate", "second")),
                expected_revision=0,
                operation_ids=("duplicate", "duplicate"),
            )
        records = (
            _Record("record-1", "first"),
            _Record("record-2", "second"),
            _Record("record-3", "third"),
        )

        result = await store.append_batch(
            key,
            records,
            expected_revision=0,
            operation_ids=tuple(record.record_id for record in records),
        )
        repeated = await store.append_batch(
            key,
            records,
            expected_revision=0,
            operation_ids=tuple(record.record_id for record in records),
        )

        assert [receipt.revision for receipt in result.receipts] == [1, 2, 3]
        assert [receipt.record_id for receipt in repeated.receipts] == [
            "record-1",
            "record-2",
            "record-3",
        ]
        assert (await store.load(key)).snapshot.records == records

        await store.append(
            key,
            _Record("record-4", "fourth"),
            expected_revision=3,
            operation_id="record-4",
        )
        before = (await store.load(key)).snapshot
        with pytest.raises(StoreConflictError):
            await store.append_batch(
                key,
                (_Record("record-5", "stale"),),
                expected_revision=0,
                operation_ids=("record-5",),
            )
        assert (await store.load(key)).snapshot == before

    asyncio.run(scenario())


def test_create_existing_key_fails_without_replacing_data(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        key = ConversationKey("coding", "session-1")
        await store.create(
            key,
            _Header("Original"),
            (_Record("one", "kept"),),
            operation_id=_operation("create", key),
        )

        with pytest.raises(StoreAlreadyExistsError):
            await store.create(
                key,
                _Header("Replacement"),
                operation_id=_operation("replacement", key),
            )

        loaded = (await store.load(key)).snapshot
        assert loaded.header == _Header("Original")
        assert loaded.records == (_Record("one", "kept"),)

    asyncio.run(scenario())


def test_missing_load_append_and_delete_share_not_found_error(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        key = ConversationKey("coding", "missing")

        with pytest.raises(StoreNotFoundError):
            await store.load(key)
        with pytest.raises(StoreNotFoundError):
            await store.append(
                key,
                _Record("record-1", "missing"),
                expected_revision=0,
                operation_id="record-1",
            )
        with pytest.raises(StoreNotFoundError):
            await store.delete(
                key,
                expected_revision=0,
                operation_id=_operation("delete", key),
            )

    asyncio.run(scenario())


def test_scan_is_namespace_scoped_and_delete_removes_key(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        coding_b = ConversationKey("coding", "b")
        coding_a = ConversationKey("coding", "a")
        research = ConversationKey("research", "a")
        await store.create(
            coding_b,
            _Header("B"),
            operation_id=_operation("create", coding_b),
        )
        await store.create(
            research,
            _Header("Research"),
            operation_id=_operation("create", research),
        )
        await store.create(
            coding_a,
            _Header("A"),
            operation_id=_operation("create", coding_a),
        )

        assert await store.scan("coding") == (coding_a, coding_b)
        assert await store.scan("research") == (research,)

        await store.delete(
            coding_a,
            expected_revision=0,
            operation_id=_operation("delete", coding_a),
        )
        assert await store.scan("coding") == (coding_b,)

    asyncio.run(scenario())


def test_file_delete_preserves_default_lock_artifact(tmp_path: Path) -> None:
    store = _file_factory(tmp_path)()
    key = ConversationKey("coding", "conversation-1")

    async def scenario() -> None:
        await store.create(
            key,
            _Header("conversation-1"),
            operation_id=_operation("create", key),
        )
        path = tmp_path / "conversations" / "coding" / "conversation-1.jsonl"
        assert path.with_name(f"{path.name}.lock").exists()

        await store.delete(
            key,
            expected_revision=0,
            operation_id=_operation("delete", key),
        )

        assert not path.exists()
        assert path.with_name(f"{path.name}.lock").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("revision", [-1, True, 1.5])
def test_invalid_expected_revision_is_rejected(
    store_factory: _StoreFactory,
    revision: Any,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        key = ConversationKey("coding", "session-1")
        await store.create(
            key,
            _Header("Header"),
            operation_id=_operation("create", key),
        )
        with pytest.raises((TypeError, ValueError)):
            await store.append(
                key,
                _Record("record-1", "invalid revision"),
                expected_revision=revision,
                operation_id="record-1",
            )
        assert (await store.load(key)).snapshot.revision == 0

    asyncio.run(scenario())


def test_file_append_loads_counts_and_appends_inside_one_exclusive_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    lock_depth = 0
    lock_entries: list[str] = []

    @contextmanager
    def lock_factory(target: Path, mode: str):
        nonlocal lock_depth
        assert target == path
        assert mode == "exclusive"
        lock_entries.append(mode)
        lock_depth += 1
        try:
            yield
        finally:
            lock_depth -= 1

    class LockCheckingCodec(_RecordCodec):
        def encode_record(self, record: _Record):
            assert lock_depth == 1
            return super().encode_record(record)

        def decode_record(self, value):
            assert lock_depth == 1
            return super().decode_record(value)

    def journal_factory(target: Path):
        return JsonlJournal(
            target,
            header_codec=_HeaderCodec(),
            record_codec=LockCheckingCodec(),
            load_policy=JournalLoadPolicy(header="required"),
            lock_factory=lock_factory,
        )

    key = ConversationKey("coding", "session-1")
    store = FileConversationStore(
        create_path=lambda ignored: path,
        resolve_path=lambda ignored: path,
        scan_paths=lambda ignored: (path,),
        key_for_path=lambda namespace, ignored: key,
        journal_factory=journal_factory,
    )

    async def scenario() -> None:
        await store.create(
            key,
            _Header("Header"),
            operation_id=_operation("create", key),
        )
        lock_entries.clear()
        await store.append(
            key,
            _Record("record-1", "atomic"),
            expected_revision=0,
            operation_id="record-1",
        )

    asyncio.run(scenario())
    assert lock_entries == ["exclusive"]


def test_file_batch_append_loads_and_writes_inside_one_exclusive_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    path = tmp_path / "session.jsonl"
    lock_depth = 0
    lock_entries: list[str] = []

    @contextmanager
    def lock_factory(target: Path, mode: str):
        nonlocal lock_depth
        assert target == path
        assert mode == "exclusive"
        lock_entries.append(mode)
        lock_depth += 1
        try:
            yield
        finally:
            lock_depth -= 1

    class LockCheckingCodec(_RecordCodec):
        def encode_record(self, record: _Record):
            assert lock_depth == 1
            return super().encode_record(record)

        def decode_record(self, value):
            assert lock_depth == 1
            return super().decode_record(value)

    key = ConversationKey("coding", "session-1")
    store = FileConversationStore(
        create_path=lambda ignored: path,
        resolve_path=lambda ignored: path,
        scan_paths=lambda ignored: (path,),
        key_for_path=lambda namespace, ignored: key,
        journal_factory=lambda target: JsonlJournal(
            target,
            header_codec=_HeaderCodec(),
            record_codec=LockCheckingCodec(),
            load_policy=JournalLoadPolicy(header="required"),
            lock_factory=lock_factory,
        ),
        record_id=_record_id,
    )

    store._create_sync(
        key,
        _Header("Header"),
        operation_id=_operation("create", key),
    )
    lock_entries.clear()
    load_unlocked = file_store_module._load_unlocked
    append_many = file_store_module.append_jsonl_records
    load_calls = 0
    append_calls = 0

    def count_load(journal):
        nonlocal load_calls
        load_calls += 1
        return load_unlocked(journal)

    def count_append(*args, **kwargs):
        nonlocal append_calls
        append_calls += 1
        return append_many(*args, **kwargs)

    monkeypatch.setattr(file_store_module, "_load_unlocked", count_load)
    monkeypatch.setattr(file_store_module, "append_jsonl_records", count_append)
    records = (_Record("record-1", "first"), _Record("record-2", "second"))
    store._append_batch_sync(
        key,
        records,
        expected_revision=0,
        operation_ids=("record-1", "record-2"),
    )

    assert lock_entries == ["exclusive"]
    assert load_calls == 1
    assert append_calls == 1


def test_file_maps_corrupted_persistence_to_data_error(tmp_path: Path) -> None:
    factory = _file_factory(tmp_path)

    async def scenario() -> None:
        store = factory()
        key = ConversationKey("coding", "session-1")
        await store.create(
            key,
            _Header("Header"),
            operation_id=_operation("create", key),
        )
        path = tmp_path / "conversations" / "coding" / "session-1.jsonl"
        path.write_text("not-json\n", encoding="utf-8")

        with pytest.raises(StoreDataError):
            await store.load(key)
        with pytest.raises(StoreDataError):
            await store.append(
                key,
                _Record("record-1", "blocked"),
                expected_revision=0,
                operation_id="record-1",
            )

    asyncio.run(scenario())


def test_file_create_with_initial_records_is_atomic_on_codec_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"

    class FailingRecordCodec(_RecordCodec):
        def encode_record(self, record: _Record):
            if record.record_id == "broken":
                raise ValueError("cannot encode record")
            return super().encode_record(record)

    store = FileConversationStore(
        create_path=lambda ignored: path,
        resolve_path=lambda ignored: path,
        scan_paths=lambda ignored: (),
        key_for_path=lambda namespace, ignored: ConversationKey(
            namespace,
            "session-1",
        ),
        journal_factory=lambda target: JsonlJournal(
            target,
            header_codec=_HeaderCodec(),
            record_codec=FailingRecordCodec(),
            load_policy=JournalLoadPolicy(header="required"),
        ),
    )

    async def scenario() -> None:
        with pytest.raises(StoreDataError):
            await store.create(
                ConversationKey("coding", "session-1"),
                _Header("Header"),
                (_Record("kept", "first"), _Record("broken", "second")),
                operation_id="create:broken",
            )

    asyncio.run(scenario())
    assert not path.exists()


def test_receipt_projection_failure_does_not_commit(tmp_path: Path) -> None:
    factories = (
        _memory_factory(record_id=lambda record: ""),
        _file_factory(tmp_path, record_id=lambda record: ""),
    )

    async def scenario(factory: _StoreFactory) -> None:
        base_store = factory()
        key = ConversationKey("coding", "session-1")
        await base_store.create(
            key,
            _Header("Header"),
            operation_id=_operation("create", key),
        )

        with pytest.raises((StoreDataError, ValueError)):
            await base_store.append(
                key,
                _Record("record-1", "must not commit"),
                expected_revision=0,
                operation_id="record-1",
            )
        assert (await base_store.load(key)).snapshot.revision == 0

    for factory in factories:
        asyncio.run(scenario(factory))


def test_operations_are_idempotent_and_deleted_keys_are_retired(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        key = ConversationKey("coding", "idempotent")
        create_operation = _operation("create", key)
        first = await store.create(
            key,
            _Header("Header"),
            operation_id=create_operation,
        )
        repeated = await store.create(
            key,
            _Header("Header"),
            operation_id=create_operation,
        )
        assert repeated == first

        append = await store.append(
            key,
            _Record("record-1", "once"),
            expected_revision=0,
            operation_id="record-1",
        )
        repeated_append = await store.append(
            key,
            _Record("record-1", "once"),
            expected_revision=0,
            operation_id="record-1",
        )
        assert repeated_append.receipt.revision == append.receipt.revision == 1
        assert (await store.load(key)).snapshot.records == (
            _Record("record-1", "once"),
        )

        with pytest.raises(StoreOperationConflictError):
            await store.append(
                key,
                _Record("record-1", "different"),
                expected_revision=1,
                operation_id="record-1",
            )
        with pytest.raises(StoreConflictError):
            await store.delete(
                key,
                expected_revision=0,
                operation_id=_operation("delete", key, "stale"),
            )

        delete_operation = _operation("delete", key, "1")
        deleted = await store.delete(
            key,
            expected_revision=1,
            operation_id=delete_operation,
        )
        repeated_delete = await store.delete(
            key,
            expected_revision=1,
            operation_id=delete_operation,
        )
        assert repeated_delete == deleted
        with pytest.raises(StoreAlreadyExistsError):
            await store.create(
                key,
                _Header("Reused"),
                operation_id=_operation("create", key, "again"),
            )

    asyncio.run(scenario())


def test_scan_page_is_paginated_and_content_ordered(
    store_factory: _StoreFactory,
) -> None:
    async def scenario() -> None:
        store = store_factory()
        keys = tuple(ConversationKey("coding", value) for value in ("c", "a", "b"))
        for key in keys:
            await store.create(
                key,
                _Header(key.conversation_id),
                operation_id=_operation("create", key),
            )

        first = await store.scan_page("coding", limit=2)
        second = await store.scan_page(
            "coding",
            cursor=first.next_cursor,
            limit=2,
        )

        assert [head.key.conversation_id for head in first.heads] == ["a", "b"]
        assert first.next_cursor == "2"
        assert [head.key.conversation_id for head in second.heads] == ["c"]
        assert second.next_cursor is None
        assert all(head.revision == 0 for head in (*first.heads, *second.heads))

    asyncio.run(scenario())


def test_file_append_reconciles_a_lost_success_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = _file_factory(tmp_path)()
    key = ConversationKey("coding", "lost-response")
    append_once = file_store_module.append_jsonl_record

    def append_then_lose_response(*args, **kwargs):
        append_once(*args, **kwargs)
        raise OSError("response lost after fsync")

    async def scenario() -> None:
        await store.create(
            key,
            _Header("Header"),
            operation_id=_operation("create", key),
        )
        monkeypatch.setattr(
            file_store_module,
            "append_jsonl_record",
            append_then_lose_response,
        )
        record = _Record("record-1", "committed once")
        with pytest.raises(StoreCommitOutcomeUnknown):
            await store.append(
                key,
                record,
                expected_revision=0,
                operation_id=record.record_id,
            )

        assert (await store.load(key)).snapshot.records == (record,)
        reconciled = await store.append(
            key,
            record,
            expected_revision=0,
            operation_id=record.record_id,
        )
        assert reconciled.receipt.revision == 1
        assert (await store.load(key)).snapshot.records == (record,)

    asyncio.run(scenario())


def test_file_batch_append_reconciles_a_durable_prefix_after_unknown_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "lost-batch-response")
    store._create_sync(
        key,
        _Header("Header"),
        operation_id=_operation("create", key),
    )
    append_many = file_store_module.append_jsonl_records

    def append_prefix_then_lose_response(path, records, **kwargs):
        append_many(path, records[:1], **kwargs)
        raise OSError("response lost after durable prefix")

    records = (_Record("record-1", "first"), _Record("record-2", "second"))
    monkeypatch.setattr(
        file_store_module,
        "append_jsonl_records",
        append_prefix_then_lose_response,
    )
    with pytest.raises(StoreCommitOutcomeUnknown):
        store._append_batch_sync(
            key,
            records,
            expected_revision=0,
            operation_ids=("record-1", "record-2"),
        )

    monkeypatch.setattr(file_store_module, "append_jsonl_records", append_many)
    reconciled = store._append_batch_sync(
        key,
        records,
        expected_revision=0,
        operation_ids=("record-1", "record-2"),
    )

    assert [receipt.revision for receipt in reconciled.receipts] == [1, 2]
    assert store._load_sync(key).snapshot.records == records
