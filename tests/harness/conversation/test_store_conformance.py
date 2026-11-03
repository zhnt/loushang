"""Conformance tests for neutral conversation Store providers."""

from __future__ import annotations

import asyncio
import json
import math
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
    head_compatibility_token: str = "test-conversation-store-v1",
    background_head_updates: bool = False,
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
            head_compatibility_token=head_compatibility_token,
            background_head_updates=background_head_updates,
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


def test_file_append_uses_current_head_inside_one_exclusive_lock_without_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    lock_depth = 0
    lock_entries: list[str] = []
    decode_calls = 0

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
            nonlocal decode_calls
            assert lock_depth == 1
            decode_calls += 1
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
        head_compatibility_token="test-locking-store-v1",
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
    assert decode_calls == 0


def test_file_batch_append_uses_current_head_and_one_write_inside_one_lock(
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
        head_compatibility_token="test-batch-store-v1",
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
    assert load_calls == 0
    assert append_calls == 1


def test_file_append_cost_does_not_scale_with_existing_record_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    decode_calls = 0

    class CountingCodec(_RecordCodec):
        def decode_record(self, value):
            nonlocal decode_calls
            decode_calls += 1
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
            record_codec=CountingCodec(),
            load_policy=JournalLoadPolicy(header="required"),
        ),
        record_id=_record_id,
        head_compatibility_token="test-large-store-v1",
    )
    existing = tuple(_Record(f"record-{index}", "x" * 256) for index in range(2_000))
    store._create_sync(
        key,
        _Header("Header"),
        existing,
        operation_id=_operation("create", key),
    )

    store._append_sync(
        key,
        _Record("record-2000", "new"),
        expected_revision=len(existing),
        operation_id="record-2000",
    )

    assert decode_calls == 0


def test_file_head_compatibility_change_forces_authoritative_replay(
    tmp_path: Path,
) -> None:
    key = ConversationKey("coding", "compatibility-change")
    first = cast(
        FileConversationStore[_Header, _Record],
        _file_factory(
            tmp_path,
            record_id=lambda record: record.record_id,
            head_compatibility_token="record-id-field-v1",
        )(),
    )
    first._create_sync(
        key,
        _Header("Header"),
        (_Record("record-1", "shared-operation"),),
        operation_id=_operation("create", key),
    )
    reopened = cast(
        FileConversationStore[_Header, _Record],
        _file_factory(
            tmp_path,
            record_id=lambda record: record.text,
            head_compatibility_token="record-text-v2",
        )(),
    )

    with pytest.raises(StoreOperationConflictError):
        reopened._append_sync(
            key,
            _Record("record-2", "shared-operation"),
            expected_revision=1,
            operation_id="shared-operation",
        )

    assert reopened._load_sync(key).snapshot.records == (
        _Record("record-1", "shared-operation"),
    )


def test_file_head_operation_filter_has_a_global_false_positive_budget() -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    builder = file_store_module._OperationFilterBuilder(
        file_store_module._OperationFilter.empty()
    )
    for index in range(100_000):
        builder.add(f"record-{index}")
    operation_filter = builder.freeze()

    assert len(operation_filter.segments) == 4
    assert [segment.insertions for segment in operation_filter.segments[:3]] == [
        10_000,
        20_000,
        40_000,
    ]
    assert 29_995 <= operation_filter.segments[3].insertions <= 30_000
    assert sum(len(segment.payload) for segment in operation_filter.segments) < 600_000
    assert all(
        operation_filter.might_contain(f"record-{index}")
        for index in range(0, 100_000, 100)
    )
    false_positives = sum(
        operation_filter.might_contain(f"unseen-{index}") for index in range(100_000)
    )
    assert false_positives <= 5

    survival_probability = 1.0
    for index in range(file_store_module._OPERATION_FILTER_MAX_SEGMENTS):
        capacity, bits, hashes = file_store_module._operation_filter_segment_shape(
            index
        )
        segment_false_positive_rate = (
            1 - math.exp(-hashes * capacity / bits)
        ) ** hashes
        survival_probability *= 1 - segment_false_positive_rate
    assert 1 - survival_probability <= (
        file_store_module._OPERATION_FILTER_FALSE_POSITIVE_BUDGET
    )


def test_file_append_still_rejects_an_old_reused_operation_from_before_recent_head(
    tmp_path: Path,
) -> None:
    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "old-operation")
    existing = tuple(
        _Record(f"record-{index}", f"value-{index}") for index in range(200)
    )
    store._create_sync(
        key,
        _Header("Header"),
        existing,
        operation_id=_operation("create", key),
    )

    with pytest.raises(StoreOperationConflictError):
        store._append_sync(
            key,
            _Record("record-0", "different"),
            expected_revision=len(existing),
            operation_id="record-0",
        )

    assert store._load_sync(key).snapshot.records == existing


def test_file_append_does_not_fast_reconcile_a_non_unique_recent_operation(
    tmp_path: Path,
) -> None:
    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "duplicate-operation")
    existing = (
        _Record("duplicate", "older value"),
        *(_Record(f"record-{index}", f"value-{index}") for index in range(1, 199)),
        _Record("duplicate", "recent value"),
    )
    store._create_sync(
        key,
        _Header("Header"),
        existing,
        operation_id=_operation("create", key),
    )

    with pytest.raises(StoreOperationConflictError):
        store._append_sync(
            key,
            _Record("duplicate", "recent value"),
            expected_revision=len(existing),
            operation_id="duplicate",
        )

    assert store._load_sync(key).snapshot.records == existing


def test_file_append_bootstraps_a_missing_head_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "legacy-metadata")
    store._create_sync(
        key,
        _Header("Header"),
        operation_id=_operation("create", key),
    )
    path = tmp_path / "conversations" / "coding" / "legacy-metadata.jsonl"
    metadata_path = path.with_name(f"{path.name}.store.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("head")
    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    load_unlocked = file_store_module._load_unlocked
    load_calls = 0

    def count_load(journal):
        nonlocal load_calls
        load_calls += 1
        return load_unlocked(journal)

    monkeypatch.setattr(file_store_module, "_load_unlocked", count_load)
    store._append_sync(
        key,
        _Record("record-1", "first"),
        expected_revision=0,
        operation_id="record-1",
    )
    store._append_sync(
        key,
        _Record("record-2", "second"),
        expected_revision=1,
        operation_id="record-2",
    )

    assert load_calls == 1


def test_file_append_reuses_unchanged_writer_head_without_decoding_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "cached-writer-head")
    store._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    store._append_sync(
        key, _Record("record-1", "first"), expected_revision=0, operation_id="record-1"
    )
    original = file_store_module._try_load_store_head
    loads = 0

    def count_load(*args, **kwargs):
        nonlocal loads
        loads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(file_store_module, "_try_load_store_head", count_load)
    store._append_sync(
        key, _Record("record-2", "second"), expected_revision=1, operation_id="record-2"
    )

    assert loads == 0
    assert store._load_sync(key).snapshot.revision == 2


def test_file_background_head_write_does_not_delay_durable_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(
        FileConversationStore[_Header, _Record],
        _file_factory(tmp_path, background_head_updates=True)(),
    )
    key = ConversationKey("coding", "background-head")
    store._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    entered = Event()
    release = Event()
    original = file_store_module._try_write_store_head

    def held_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(file_store_module, "_try_write_store_head", held_write)

    async def scenario() -> None:
        try:
            receipt = await asyncio.wait_for(
                store.append(
                    key,
                    _Record("record-1", "first"),
                    expected_revision=0,
                    operation_id="record-1",
                ),
                timeout=1,
            )
            assert receipt.receipt.revision == 1
            assert await asyncio.to_thread(entered.wait, 1)
        finally:
            release.set()
        await store.drain_advisory_head_updates()
        original_load = file_store_module._try_load_store_head
        loads = 0

        def count_load(*args, **kwargs):
            nonlocal loads
            loads += 1
            return original_load(*args, **kwargs)

        monkeypatch.setattr(file_store_module, "_try_load_store_head", count_load)
        await store.append(
            key,
            _Record("record-2", "second"),
            expected_revision=1,
            operation_id="record-2",
        )
        assert loads == 0
        await store.drain_advisory_head_updates()
        reopened = cast(
            FileConversationStore[_Header, _Record], _file_factory(tmp_path)()
        )
        assert (await reopened.load(key)).snapshot.revision == 2

    asyncio.run(scenario())


def test_file_background_head_writes_coalesce_and_drain_without_delay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = cast(
        FileConversationStore[_Header, _Record],
        _file_factory(tmp_path, background_head_updates=True)(),
    )
    key = ConversationKey("coding", "coalesced-head")
    store._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    writes: list[int] = []
    original = store._write_head_if_current

    def count_write(key, path, head):
        writes.append(head.revision)
        return original(key, path, head)

    monkeypatch.setattr(store, "_write_head_if_current", count_write)

    async def scenario() -> None:
        await store.append(
            key,
            _Record("record-1", "first"),
            expected_revision=0,
            operation_id="record-1",
        )
        await store.append(
            key,
            _Record("record-2", "second"),
            expected_revision=1,
            operation_id="record-2",
        )
        assert writes == []
        await asyncio.wait_for(store.drain_advisory_head_updates(), timeout=1)
        assert writes == [2]
        reopened = cast(
            FileConversationStore[_Header, _Record], _file_factory(tmp_path)()
        )
        assert (await reopened.load(key)).snapshot.revision == 2

    asyncio.run(scenario())


def test_file_background_head_write_does_not_delay_durable_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(
        FileConversationStore[_Header, _Record],
        _file_factory(tmp_path, background_head_updates=True)(),
    )
    key = ConversationKey("coding", "background-batch-head")
    store._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    entered = Event()
    release = Event()
    original = file_store_module._try_write_store_head

    def held_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(file_store_module, "_try_write_store_head", held_write)

    async def scenario() -> None:
        records = (_Record("record-1", "first"), _Record("record-2", "second"))
        try:
            result = await asyncio.wait_for(
                store.append_batch(
                    key,
                    records,
                    expected_revision=0,
                    operation_ids=("record-1", "record-2"),
                ),
                timeout=1,
            )
            assert tuple(item.revision for item in result.receipts) == (1, 2)
            assert await asyncio.to_thread(entered.wait, 1)
        finally:
            release.set()
        await store.drain_advisory_head_updates()
        reopened = cast(
            FileConversationStore[_Header, _Record], _file_factory(tmp_path)()
        )
        assert (await reopened.load(key)).snapshot.records == records

    asyncio.run(scenario())


def test_file_background_head_write_cannot_replace_newer_writer_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from loushang.harness.conversation.stores import file as file_store_module

    factory = _file_factory(tmp_path, background_head_updates=True)
    first = cast(FileConversationStore[_Header, _Record], factory())
    key = ConversationKey("coding", "stale-background-head")
    first._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    entered = Event()
    release = Event()
    original = first._write_head_if_current

    def held_update(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(first, "_write_head_if_current", held_update)

    async def scenario() -> None:
        try:
            await first.append(
                key,
                _Record("record-1", "first"),
                expected_revision=0,
                operation_id="record-1",
            )
            assert await asyncio.to_thread(entered.wait, 1)
            second = cast(
                FileConversationStore[_Header, _Record], _file_factory(tmp_path)()
            )
            second._append_sync(
                key,
                _Record("record-2", "second"),
                expected_revision=1,
                operation_id="record-2",
            )
        finally:
            release.set()
        await first.drain_advisory_head_updates()
        path = tmp_path / "conversations" / "coding" / "stale-background-head.jsonl"
        head = file_store_module._try_load_store_head(
            path, compatibility_token="test-conversation-store-v1"
        )
        assert head is not None and head.revision == 2

    asyncio.run(scenario())


def test_file_writer_head_cache_replays_after_sidecar_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "changed-writer-head")
    store._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    store._append_sync(
        key, _Record("record-1", "first"), expected_revision=0, operation_id="record-1"
    )
    path = tmp_path / "conversations" / "coding" / "changed-writer-head.jsonl"
    path.with_name(f"{path.name}.store.json").write_text("{", encoding="utf-8")
    original = file_store_module._load_unlocked
    replays = 0

    def count_replay(*args, **kwargs):
        nonlocal replays
        replays += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(file_store_module, "_load_unlocked", count_replay)
    store._append_sync(
        key, _Record("record-2", "second"), expected_revision=1, operation_id="record-2"
    )

    assert replays == 1
    assert store._load_sync(key).snapshot.revision == 2


def test_file_writer_head_cache_rechecks_a_second_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    factory = _file_factory(tmp_path)
    first = cast(FileConversationStore[_Header, _Record], factory())
    key = ConversationKey("coding", "two-writers")
    first._create_sync(key, _Header("Header"), operation_id=_operation("create", key))
    first._append_sync(
        key, _Record("record-1", "first"), expected_revision=0, operation_id="record-1"
    )
    second = cast(FileConversationStore[_Header, _Record], factory())
    second._append_sync(
        key, _Record("record-2", "second"), expected_revision=1, operation_id="record-2"
    )
    original = file_store_module._try_load_store_head
    loads = 0

    def count_load(*args, **kwargs):
        nonlocal loads
        loads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(file_store_module, "_try_load_store_head", count_load)
    first._append_sync(
        key, _Record("record-3", "third"), expected_revision=2, operation_id="record-3"
    )

    assert loads == 1
    assert first._load_sync(key).snapshot.revision == 3


def test_file_append_head_only_metadata_preserves_unknown_create_outcome(
    tmp_path: Path,
) -> None:
    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "legacy-create-outcome")
    header = _Header("Header")
    store._create_sync(
        key,
        header,
        operation_id=_operation("create", key),
    )
    path = tmp_path / "conversations" / "coding" / "legacy-create-outcome.jsonl"
    path.with_name(f"{path.name}.store.json").unlink()
    record = _Record("record-1", "existing")
    store._append_sync(
        key,
        record,
        expected_revision=0,
        operation_id="record-1",
    )

    with pytest.raises(StoreCommitOutcomeUnknown):
        store._create_sync(
            key,
            header,
            (record,),
            operation_id="retry-create",
        )
    with pytest.raises(StoreAlreadyExistsError):
        store._create_sync(
            key,
            _Header("Different"),
            operation_id="different-create",
        )


def test_file_append_rebuilds_a_head_with_a_bad_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "tampered-head")
    store._create_sync(
        key,
        _Header("Header"),
        (_Record("record-0", "existing"),),
        operation_id=_operation("create", key),
    )
    path = tmp_path / "conversations" / "coding" / "tampered-head.jsonl"
    metadata_path = path.with_name(f"{path.name}.store.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["head"]["revision"] = 0
    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    load_unlocked = file_store_module._load_unlocked
    load_calls = 0

    def count_load(journal):
        nonlocal load_calls
        load_calls += 1
        return load_unlocked(journal)

    monkeypatch.setattr(file_store_module, "_load_unlocked", count_load)
    result = store._append_sync(
        key,
        _Record("record-1", "new"),
        expected_revision=1,
        operation_id="record-1",
    )

    assert result.receipt.revision == 2
    assert load_calls == 1


def test_file_append_replaces_invalid_json_metadata_after_authoritative_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "invalid-metadata")
    store._create_sync(
        key,
        _Header("Header"),
        operation_id=_operation("create", key),
    )
    path = tmp_path / "conversations" / "coding" / "invalid-metadata.jsonl"
    metadata_path = path.with_name(f"{path.name}.store.json")
    metadata_path.write_text("{", encoding="utf-8")
    load_unlocked = file_store_module._load_unlocked
    load_calls = 0

    def count_load(journal):
        nonlocal load_calls
        load_calls += 1
        return load_unlocked(journal)

    monkeypatch.setattr(file_store_module, "_load_unlocked", count_load)
    store._append_sync(
        key,
        _Record("record-1", "first"),
        expected_revision=0,
        operation_id="record-1",
    )
    store._append_sync(
        key,
        _Record("record-2", "second"),
        expected_revision=1,
        operation_id="record-2",
    )

    assert load_calls == 1


def test_file_append_success_does_not_depend_on_the_advisory_head_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "head-write-failure")
    store._create_sync(
        key,
        _Header("Header"),
        operation_id=_operation("create", key),
    )

    def fail_head_write(*args, **kwargs):
        raise RuntimeError("metadata device unavailable")

    monkeypatch.setattr(file_store_module, "_write_json_sidecar", fail_head_write)
    record = _Record("record-1", "durable")
    result = store._append_sync(
        key,
        record,
        expected_revision=0,
        operation_id="record-1",
    )

    assert result.receipt.revision == 1
    assert store._load_sync(key).snapshot.records == (record,)


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


def test_file_fully_reconciled_batch_repairs_head_for_the_next_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.conversation.stores import file as file_store_module

    store = cast(FileConversationStore[_Header, _Record], _file_factory(tmp_path)())
    key = ConversationKey("coding", "lost-complete-batch-response")
    store._create_sync(
        key,
        _Header("Header"),
        operation_id=_operation("create", key),
    )
    append_many = file_store_module.append_jsonl_records

    def append_all_then_lose_response(path, records, **kwargs):
        append_many(path, records, **kwargs)
        raise OSError("response lost after durable batch")

    records = (_Record("record-1", "first"), _Record("record-2", "second"))
    monkeypatch.setattr(
        file_store_module,
        "append_jsonl_records",
        append_all_then_lose_response,
    )
    with pytest.raises(StoreCommitOutcomeUnknown):
        store._append_batch_sync(
            key,
            records,
            expected_revision=0,
            operation_ids=("record-1", "record-2"),
        )

    monkeypatch.setattr(file_store_module, "append_jsonl_records", append_many)
    load_unlocked = file_store_module._load_unlocked
    load_calls = 0

    def count_load(journal):
        nonlocal load_calls
        load_calls += 1
        return load_unlocked(journal)

    monkeypatch.setattr(file_store_module, "_load_unlocked", count_load)
    reconciled = store._append_batch_sync(
        key,
        records,
        expected_revision=0,
        operation_ids=("record-1", "record-2"),
    )
    appended = store._append_sync(
        key,
        _Record("record-3", "third"),
        expected_revision=2,
        operation_id="record-3",
    )

    assert [receipt.revision for receipt in reconciled.receipts] == [1, 2]
    assert appended.receipt.revision == 3
    assert load_calls == 1
