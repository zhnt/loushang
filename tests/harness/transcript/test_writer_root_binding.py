"""End-to-end regressions for retained-root Store IO and cleanup."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

import pytest

from loushang.harness.journal import _rooted_io as native
from loushang.harness.transcript import load_agent_transcript_file
from loushang.harness.transcript import model_input_v2_index_file as index
from loushang.harness.transcript.model_input_v2_index_file import (
    _projection_cache_path,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterLease

from .test_lifecycle import _header, _record
from .test_runtime_profile import _runtime
from .test_writer_io import invoke, wait_until
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_runtime import prepare

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux writer")


def tree(root):
    return {
        str(path.relative_to(root)): (
            path.lstat().st_mode, path.lstat().st_ino, path.lstat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
        for path in (root, *root.rglob("*"))
    }


@pytest.mark.parametrize("method", ["append", "delete"])
def test_admitted_io_cannot_mutate_replacement_root(tmp_path, monkeypatch, method):
    async def scenario():
        root, moved = tmp_path / "sessions", tmp_path / "original"
        root.mkdir(mode=0o700)
        runtime = _runtime("coding")
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        before = (root / "session.jsonl").read_bytes()
        entered, release = threading.Event(), threading.Event()
        original = getattr(store, f"_{method}_sync")
        replacement_writer = None

        def blocked(*args, **kwargs):
            entered.set()  # The independent writer.check has already settled.
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(store, f"_{method}_sync", blocked)
        operation = asyncio.create_task(
            store.append(key, _record("one"), expected_revision=0, operation_id="one")
            if method == "append" else
            store.delete(key, expected_revision=0, operation_id="delete")
        )
        try:
            await wait_until(entered.is_set)
            root.rename(moved)
            root.mkdir(mode=0o700)
            replacement = root / "session.jsonl"
            replacement.write_bytes(before)
            replacement_writer = TranscriptWriterLease(root, "coding", _header().conversation_id)
            replacement_writer.acquire()
            untouched = tree(root)
            release.set()
            result = await operation
            assert tree(root) == untouched
            if method == "append":
                assert result.receipt.revision == 1
                _, records = load_agent_transcript_file(moved / "session.jsonl", read_only=True)
                assert records == [_record("one")]
            else:
                assert result.revision == 0 and not (moved / "session.jsonl").exists()
        finally:
            release.set()
            await asyncio.gather(operation, return_exceptions=True)
            await owner.dispose()
            if replacement_writer is not None:
                replacement_writer.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["create", "load", "append", "append_batch", "delete", "scan", "scan_page"])
def test_all_owned_entries_use_original_tree_without_pathname_fallback(tmp_path, monkeypatch, method):
    async def scenario():
        root, moved = tmp_path / "sessions", tmp_path / "original"
        root.mkdir(mode=0o700)
        runtime = _runtime("coding")
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned, defer_materialization=method == "create")
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        entered, release = threading.Event(), threading.Event()
        original = getattr(store, f"_{method}_sync")
        replacement_writer = None

        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(store, f"_{method}_sync", blocked)
        operation = asyncio.create_task(invoke(store, key, method))
        try:
            await wait_until(entered.is_set)
            root.rename(moved)
            root.mkdir(mode=0o700)
            (root / "session.jsonl").write_bytes(b"this replacement must not be parsed or changed")
            replacement_writer = TranscriptWriterLease(root, "coding", _header().conversation_id)
            replacement_writer.acquire()
            before = tree(root)

            def forbid(original_method):
                def guarded(path, *args, **kwargs):
                    if path.is_relative_to(root) or path.is_relative_to(moved):
                        raise AssertionError("owned Store fell back to pathname IO")
                    return original_method(path, *args, **kwargs)
                return guarded

            with monkeypatch.context() as patch:
                for name in ("open", "stat", "lstat", "mkdir", "unlink", "replace", "resolve"):
                    patch.setattr(Path, name, forbid(getattr(Path, name)))
                release.set()
                result = await operation
            assert tree(root) == before
            if method == "load":
                assert result.snapshot.header == _header()
            elif method == "scan":
                assert result == (key,)
            elif method == "scan_page":
                assert len(result.heads) == 1 and not result.diagnostics
            elif method == "delete":
                assert result.revision == 0 and not (moved / "session.jsonl").exists()
            elif method == "create":
                assert result.revision == 0
                header, records = load_agent_transcript_file(moved / "session.jsonl", read_only=True)
                assert header == _header() and records == []
            else:
                assert (result.receipt.revision if method == "append" else result.receipts[0].revision) == 1
                _, records = load_agent_transcript_file(moved / "session.jsonl", read_only=True)
                assert records == [_record("one")]
        finally:
            release.set()
            await asyncio.gather(operation, return_exceptions=True)
            await owner.dispose()
            if replacement_writer is not None:
                replacement_writer.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("cache", ["missing", "corrupt", "valid", "tail"])
def test_owned_index_paths_remain_in_original_root(tmp_path, monkeypatch, cache):
    async def scenario():
        root, moved = tmp_path / "sessions", tmp_path / "original"
        root.mkdir(mode=0o700)
        runtime = _runtime("coding")
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        if cache in {"valid", "tail"}:
            await store.load(key)
        elif cache == "corrupt":
            _projection_cache_path(root / "session.jsonl").write_bytes(b"corrupt")
        if cache == "tail":
            await store.append(key, _record("one"), expected_revision=0, operation_id="one")
        original = store._load_sync
        untouched, rebuilds = [], []
        rebuild = index._try_rebuild_manifest

        def rebuilding(*args, **kwargs):
            rebuilds.append(1)
            return rebuild(*args, **kwargs)

        monkeypatch.setattr(index, "_try_rebuild_manifest", rebuilding)

        def load(*args, **kwargs):
            root.rename(moved)
            root.mkdir(mode=0o700)
            (root / "session.jsonl").write_bytes(b"unrelated replacement")
            untouched.append(tree(root))
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "_load_sync", load)
        result = await store.load(key)
        assert result.snapshot.header == _header()
        assert len(result.snapshot.records) == (1 if cache == "tail" else 0)
        assert result.snapshot.records == ((_record("one"),) if cache == "tail" else ())
        assert tree(root) == untouched[0]
        assert rebuilds == ([] if cache == "valid" else [1])
        assert _projection_cache_path(moved / "session.jsonl").is_file()
        await owner.dispose()
    asyncio.run(scenario())


@pytest.mark.parametrize("fail_sync", [False, True])
@pytest.mark.parametrize("prior_retirement", [False, True])
def test_tombstone_is_durable_before_jsonl_unlink(tmp_path, monkeypatch, fail_sync, prior_retirement):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        identities = tmp_path / ".conversation-identities"
        identities.mkdir(mode=0o700)
        identity = identities.stat()
        if prior_retirement:
            # Visible retirement + remaining JSONL is the observable state after
            # a previous process stopped between replace and directory fsync.
            tombstone = store._tombstone_for(key, tmp_path / "session.jsonl")
            tombstone.write_text(
                '{"revision":0,"deleted_at":"2026-09-13T00:00:00+00:00","operation_id":"delete"}',
                encoding="utf-8",
            )
            tombstone.chmod(0o600)
        events = []
        sync, unlink = native.os.fsync, native.os.unlink

        def fsync(fd):
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                if fail_sync:
                    raise OSError("test retirement sync failed")
                events.append("retirement-durable")
            return sync(fd)

        def remove(name, *args, **kwargs):
            if name == "session.jsonl":
                assert "retirement-durable" in events
                events.append("content-unlink")
            return unlink(name, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(native.os, "fsync", fsync)
            patch.setattr(native.os, "unlink", remove)
            if fail_sync:
                from loushang.harness.conversation import StoreCommitOutcomeUnknown

                with pytest.raises(StoreCommitOutcomeUnknown):
                    await store.delete(key, expected_revision=0, operation_id="delete")
                assert events == [] and (tmp_path / "session.jsonl").is_file()
                assert owner._file_io.cleanup_pending
                assert_busy(tmp_path)
            else:
                result = await store.delete(key, expected_revision=0, operation_id="delete")
                assert result.revision == 0
                assert events.index("retirement-durable") < events.index("content-unlink")
                assert await store.delete(key, expected_revision=0, operation_id="delete") == result
        await owner.dispose()
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_scandir_unknown_close_is_retained_and_prevents_writer_release(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        owner, writer = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        primary = ValueError("test traversal failed")
        close_calls = []

        class Entries:
            def __iter__(self):
                raise primary

            def close(self):
                close_calls.append(1)
                raise OSError("test iterator close unknown")

        iterator = Entries()
        with monkeypatch.context() as patch:
            patch.setattr(native.os, "scandir", lambda *_: iterator)
            from loushang.harness.conversation import StoreDataError

            with pytest.raises(StoreDataError) as raised:
                await session.runtime_binding.store.scan(session.runtime_binding.key.namespace)
            assert raised.value.__cause__ is primary
        assert primary.__notes__ == ["rooted IO cleanup debt retained"]
        assert close_calls == [1] and owner._file_io.cleanup_pending
        for _ in range(2):
            with pytest.raises(OSError, match="unknown"):
                await owner.dispose()
            assert_busy(tmp_path)
        assert close_calls == [1]
        # The test owns the fake iterator, which has no native descriptor.
        for operation in owner._file_io._operations:
            assert operation.iterators == [(iterator, True)] and not operation.descriptors
            operation.iterators.clear()
        await owner.dispose()
        assert not owner.cleanup_pending and not writer.cleanup_pending
    asyncio.run(scenario())


@pytest.mark.parametrize("replace_during_header", [False, True])
def test_standard_owned_restore_reads_header_from_retained_root(tmp_path, monkeypatch, replace_during_header):
    from loushang.harness.transcript import writer_lifecycle as lifecycle_module
    from loushang.harness.transcript.writer_lease import TranscriptWriterError

    async def scenario():
        root, moved = tmp_path / "sessions", tmp_path / "original"
        root.mkdir(mode=0o700)
        runtime = _runtime("coding")
        first, _ = prepare(root, runtime, runtime.bind_lifecycle_owned)
        session = await first.create()
        await session.runtime_binding.store.append(
            session.runtime_binding.key, _record("one"), expected_revision=0, operation_id="one",
        )
        await first.dispose()
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned, defer_materialization=True)
        original_header = lifecycle_module.load_agent_transcript_header
        snapshots = []

        def header(path, **kwargs):
            assert kwargs["read_only"] and kwargs["file_io"] is owner._file_io
            if replace_during_header:
                root.rename(moved)
                root.mkdir(mode=0o700)
                (root / "session.jsonl").write_bytes(b"unrelated replacement")
                snapshots.append(tree(root))
            result = original_header(path, **kwargs)
            assert result == _header()
            return result

        monkeypatch.setattr(lifecycle_module, "load_agent_transcript_header", header)
        if replace_during_header:
            # Header IO stays pinned. Subsequent Store admission detects the
            # invalidated logical path and refuses to continue the restoration.
            with pytest.raises(TranscriptWriterError, match="conflict"):
                await owner.restore()
            assert tree(root) == snapshots[0]
            assert_busy(moved)
        else:
            restored = await owner.restore()
            snapshot = await restored.runtime_binding.store.load(restored.runtime_binding.key)
            assert snapshot.snapshot.records == (_record("one"),)
        await owner.dispose()
        assert_available(moved if replace_during_header else root)
        if replace_during_header:
            assert tree(root) == snapshots[0]
    asyncio.run(scenario())


def test_owned_cleanup_debt_prevents_writer_release_and_rejoins_same_port(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        port = owner._file_io
        assert port is not None

        def fail_write(*_):
            raise ValueError("test index write failed")

        def fail_unlink(*_, **__):
            raise OSError("test temporary unlink failed")

        with monkeypatch.context() as patch:
            patch.setattr(native, "_write_all", fail_write)
            patch.setattr(native.os, "unlink", fail_unlink)
            with pytest.raises(Exception):
                await store.load(key)
            assert port.cleanup_pending
            with pytest.raises(OSError, match="unlink failed"):
                await owner.dispose()
            assert owner.cleanup_pending and owner._file_io is port
            assert_busy(tmp_path)
        entered, release = threading.Event(), threading.Event()
        original = port.cleanup

        def cleanup():
            entered.set()
            assert release.wait(5)
            original()

        monkeypatch.setattr(port, "cleanup", cleanup)
        closing = asyncio.create_task(owner.dispose())
        try:
            await wait_until(entered.is_set)
            retained_task = owner._io_cleanup_task
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert_busy(tmp_path)
            rejoin = asyncio.create_task(owner.dispose())
            await asyncio.sleep(0)
            assert owner._io_cleanup_task is retained_task and not rejoin.done()
            release.set()
            await rejoin
            assert not port.cleanup_pending and not owner.cleanup_pending
            assert not tuple(tmp_path.glob("*.tmp"))
            assert_available(tmp_path)
        finally:
            release.set()
    asyncio.run(scenario())
