from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from threading import Event

import pytest

from loushang.harness.conversation import (
    ConversationKey,
    FileConversationStore,
    StoreDataError,
)
from loushang.harness.conversation.stores import file as module
from loushang.harness.journal import JournalLoadPolicy, JsonlJournal
from loushang.harness.journal._rooted_io import RootedFileIO

from .test_store_conformance import _Header, _HeaderCodec, _Record, _RecordCodec

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted IO")


@contextmanager
def stores(root):
    root.mkdir(mode=0o700)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, fd)
    key = ConversationKey("test", "one")
    path = root / "one.jsonl"

    def factory():
        return FileConversationStore(
            create_path=lambda _: path,
            resolve_path=lambda _: path,
            scan_paths=lambda _: (path,),
            key_for_path=lambda *_: key,
            journal_factory=lambda target: JsonlJournal(
                target,
                file_io=io,
                header_codec=_HeaderCodec(),
                record_codec=_RecordCodec(),
                load_policy=JournalLoadPolicy(header="required"),
            ),
            record_id=lambda record: record.record_id,
            head_compatibility_token="rooted-advisory-test-v1",
            background_head_updates=True,
            file_io=io,
        )

    try:
        yield factory, key
        assert not io.cleanup_pending
    finally:
        io.cleanup()
        os.close(fd)


def hold_cache_write(monkeypatch):
    entered, release = Event(), Event()
    original = module._try_write_store_head

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release advisory writer"
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_try_write_store_head", held)
    return entered, release


async def start(store, key, entered):
    await store.create(key, _Header("test"), operation_id="create")
    await store.append(
        key, _Record("r1", "first"), expected_revision=0, operation_id="r1"
    )
    assert await asyncio.to_thread(entered.wait, 3)


@pytest.mark.parametrize("operation", ["append", "append_batch", "load"])
def test_own_advisory_lock_does_not_reject_foreground_io(
    tmp_path, monkeypatch, operation
):
    entered, release = hold_cache_write(monkeypatch)

    async def scenario():
        with stores(tmp_path / "root") as (factory, key):
            store = factory()
            pending = None
            try:
                await start(store, key, entered)
                if operation == "append":
                    call = store.append(
                        key,
                        _Record("r2", "second"),
                        expected_revision=1,
                        operation_id="r2",
                    )
                elif operation == "append_batch":
                    call = store.append_batch(
                        key,
                        [_Record("r2", "second")],
                        expected_revision=1,
                        operation_ids=["r2"],
                    )
                else:
                    call = store.load(key)
                pending = asyncio.create_task(call)
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(pending), 0.1)
                release.set()
                await pending
                expected = 1 if operation == "load" else 2
                loaded = await store.load(key)
                assert loaded.snapshot.revision == expected
                assert [r.record_id for r in loaded.snapshot.records] == ["r1", "r2"][
                    :expected
                ]
            finally:
                release.set()
                if pending is not None:
                    await asyncio.gather(pending, return_exceptions=True)
                await store.drain_advisory_head_updates()

    asyncio.run(scenario())


def test_cancelled_foreground_wait_settles_one_append(tmp_path, monkeypatch):
    entered, release = hold_cache_write(monkeypatch)

    async def scenario():
        with stores(tmp_path / "root") as (factory, key):
            store = factory()
            pending = None
            try:
                await start(store, key, entered)
                pending = asyncio.create_task(
                    store.append(
                        key,
                        _Record("r2", "second"),
                        expected_revision=1,
                        operation_id="r2",
                    )
                )
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(pending), 0.1)
                pending.cancel()
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(pending), 0.1)
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                loaded = await store.load(key)
                assert [r.record_id for r in loaded.snapshot.records] == ["r1", "r2"]
            finally:
                release.set()
                if pending is not None:
                    await asyncio.gather(pending, return_exceptions=True)
                await store.drain_advisory_head_updates()

    asyncio.run(scenario())


def test_different_store_still_refuses_busy_rooted_lock(tmp_path, monkeypatch):
    entered, release = hold_cache_write(monkeypatch)

    async def scenario():
        with stores(tmp_path / "root") as (factory, key):
            first, second = factory(), factory()
            try:
                await start(first, key, entered)
                with pytest.raises(StoreDataError) as caught:
                    await second.append(
                        key,
                        _Record("r2", "second"),
                        expected_revision=1,
                        operation_id="r2",
                    )
                assert isinstance(caught.value.__cause__, BlockingIOError)
            finally:
                release.set()
                await first.drain_advisory_head_updates()
                await second.drain_advisory_head_updates()
            assert (await first.load(key)).snapshot.revision == 1

    asyncio.run(scenario())
