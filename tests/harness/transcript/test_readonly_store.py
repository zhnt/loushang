from __future__ import annotations

import asyncio
import stat
import sys
from pathlib import Path

import pytest

from loushang.harness.conversation import StoreConflictError
from loushang.harness.transcript import (
    AgentTranscriptDirectoryRuntime,
    AgentTranscriptFileLayout,
    AgentTranscriptSessionCatalog,
    create_agent_transcript_file_store,
    write_agent_transcript_export,
)
from loushang.harness.transcript import jsonl_file as module
from loushang.harness.transcript import model_input_v2_index_file as index_module
from loushang.harness.transcript.model_input_v2_index_file import _projection_cache_path
from loushang.harness.transcript.model_input_v2_types import (
    DeferredModelInputNodeBundle,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterLease

from .test_lifecycle import _header, _record
from .test_model_input_v2_index_file import _model_input_records


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode), path.stat().st_ino,
        )
        for path in (root, *root.rglob("*"))
    }


def seed(root):
    paths = []
    for number in (1, 2):
        path = root / f"session-{number}.jsonl"
        write_agent_transcript_export(path, _header(f"session-{number}"), [_record(f"record-{number}")])
        # Fixture models a historical file without any adjacent lock/cache.
        path.with_name(path.name + ".lock").unlink(missing_ok=True)
        paths.append(path)
    return paths


def test_readonly_catalog_does_not_create_session_lock_or_projection_cache(tmp_path):
    seed(tmp_path)
    before = snapshot(tmp_path)
    summaries = AgentTranscriptSessionCatalog(tmp_path, index_writable=False).list_summaries()
    assert {summary.session_id for summary in summaries} == {"session-1", "session-2"}
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("cache", ["missing", "corrupt", "valid", "tail"])
def test_readonly_scan_page_and_load_never_rewrite_files(tmp_path, monkeypatch, cache):
    async def scenario():
        paths = seed(tmp_path)
        layout = AgentTranscriptFileLayout(tmp_path)
        writable = create_agent_transcript_file_store(layout)
        if cache in {"valid", "tail"}:
            for number in (1, 2):
                await writable.load(layout.key(f"session-{number}"))
        elif cache == "corrupt":
            for path in paths:
                _projection_cache_path(path).write_text("invalid cache", encoding="utf-8")
        if cache == "tail":
            await writable.append(
                layout.key("session-1"), _record("tail", "record-1"),
                expected_revision=1, operation_id="test-tail",
            )
        before = snapshot(tmp_path)
        calls = []
        original = index_module._try_rebuild_manifest

        def rebuild(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(index_module, "_try_rebuild_manifest", rebuild)
        strict_calls = []
        original_decode = module.decode_jsonl

        def decode(*args, **kwargs):
            strict_calls.append(1)
            return original_decode(*args, **kwargs)

        monkeypatch.setattr(module, "decode_jsonl", decode)
        store = create_agent_transcript_file_store(AgentTranscriptFileLayout(tmp_path), read_only=True)
        keys = await store.scan(layout.namespace)
        assert len(keys) == 2
        page = await store.scan_page(layout.namespace)
        assert len(page.heads) == 2 and not page.diagnostics
        for key in keys:
            result = await store.load(key)
            assert result.snapshot.header.conversation_id == key.conversation_id
            if cache == "tail" and key.conversation_id == "session-1":
                assert result.snapshot.records[-1].record_id == "tail"
        assert calls == []
        if cache == "valid":
            assert strict_calls == []
        assert snapshot(tmp_path) == before
    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["create", "append", "append_batch", "delete"])
def test_readonly_mutation_rejected_before_path_callbacks(tmp_path, monkeypatch, method):
    async def scenario():
        seed(tmp_path)
        layout = AgentTranscriptFileLayout(tmp_path)
        store = create_agent_transcript_file_store(layout, read_only=True)
        before = snapshot(tmp_path)
        calls = []

        def path_callback(*_):
            calls.append(1)
            raise AssertionError("readonly mutation reached filesystem mapping")

        monkeypatch.setattr(store, "_create_path", path_callback)
        monkeypatch.setattr(store, "_resolve_path", path_callback)
        monkeypatch.setattr(store, "_journal_factory", path_callback)
        monkeypatch.setattr(store, "_write_journal_factory", path_callback)
        key = layout.key("session-1")
        with pytest.raises(StoreConflictError, match="read.only"):
            if method == "create":
                await store.create(key, _header("new"), operation_id="new")
            elif method == "append":
                await store.append(key, _record("next"), expected_revision=1, operation_id="append")
            elif method == "append_batch":
                await store.append_batch(key, [_record("next")], expected_revision=1, operation_ids=["batch"])
            else:
                await store.delete(key, expected_revision=1, operation_id="delete")
        assert not calls and snapshot(tmp_path) == before
    asyncio.run(scenario())


def test_readonly_partial_tail_preserves_bytes_and_diagnostic(tmp_path):
    async def scenario():
        paths = seed(tmp_path)
        with paths[0].open("ab") as handle:
            handle.write(b'{"partial":')
        before = snapshot(tmp_path)
        layout = AgentTranscriptFileLayout(tmp_path)
        store = create_agent_transcript_file_store(layout, read_only=True)
        result = await store.load(layout.key("session-1"))
        assert len(result.snapshot.records) == 1
        assert result.diagnostics
        assert snapshot(tmp_path) == before
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != "linux", reason="Linux writer")
def test_active_session_writers_do_not_block_readonly_namespace_queries(tmp_path):
    paths = seed(tmp_path)
    writers = [TranscriptWriterLease(tmp_path, "coding", f"session-{number}") for number in (1, 2)]
    try:
        for writer in writers:
            writer.acquire()
        before = snapshot(tmp_path)

        async def scenario():
            layout = AgentTranscriptFileLayout(tmp_path)
            store = create_agent_transcript_file_store(layout)
            assert len(await store.scan(layout.namespace)) == 2
            assert len((await store.scan_page(layout.namespace)).heads) == 2
        asyncio.run(scenario())
        catalog = AgentTranscriptSessionCatalog(tmp_path, index_writable=False)
        assert len(catalog.list_summaries()) == 2
        assert snapshot(tmp_path) == before
        assert all(writer.cleanup_pending for writer in writers)
        assert all(not _projection_cache_path(path).exists() for path in paths)
    finally:
        for writer in writers:
            writer.close()


def test_readonly_source_and_cache_symlinks_are_not_followed(tmp_path, monkeypatch):
    async def scenario():
        paths = seed(tmp_path)
        private = tmp_path / "private.txt"
        private.write_text("not a cache", encoding="utf-8")
        cache = _projection_cache_path(paths[0])
        cache.symlink_to(private)
        link = tmp_path / "linked.jsonl"
        link.symlink_to(paths[0])
        opened = []
        original = module._open_file_no_follow

        def open_file(path, **kwargs):
            opened.append(path)
            return original(path, **kwargs)

        monkeypatch.setattr(module, "_open_file_no_follow", open_file)
        before = snapshot(tmp_path)
        layout = AgentTranscriptFileLayout(tmp_path)
        store = create_agent_transcript_file_store(layout, read_only=True)
        assert len(await store.scan(layout.namespace)) == 2
        assert (await store.load(layout.key("session-1"))).snapshot.header.conversation_id == "session-1"
        with pytest.raises(OSError, match="regular file"):
            module._load_agent_transcript_readonly_snapshot(link)
        assert cache not in opened and link not in opened and private not in opened
        assert snapshot(tmp_path) == before
    asyncio.run(scenario())


def test_readonly_replacement_during_read_is_rejected(tmp_path, monkeypatch):
    paths = seed(tmp_path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(paths[0].read_bytes())
    original = module.os.read
    replaced = False

    def read(fd, count):
        nonlocal replaced
        result = original(fd, count)
        if not replaced:
            replacement.replace(paths[0])
            replaced = True
        return result

    monkeypatch.setattr(module.os, "read", read)
    with pytest.raises(OSError, match="changed"):
        module._load_agent_transcript_readonly_snapshot(paths[0])
    assert replaced


@pytest.mark.parametrize("primary_error", [False, True])
def test_read_descriptor_cleanup_attempts_parent_and_keeps_primary(monkeypatch, primary_error):
    calls = []
    error = ValueError("test read failure") if primary_error else None

    def close(fd):
        calls.append(fd)
        if fd == 101:
            raise OSError("test first close failure")

    monkeypatch.setattr(module.os, "close", close)
    if error is None:
        with pytest.raises(OSError, match="first close failure"):
            module._close_read_descriptors(101, 102)
    else:
        module._close_read_descriptors(101, 102, primary=error)
        assert error.__notes__ == ["transcript reader descriptor cleanup failed"]
    assert calls == [101, 102]


def test_path_discovery_directory_and_collision_queries_leave_files_unchanged(tmp_path):
    paths = seed(tmp_path)
    before = snapshot(tmp_path)
    catalog = AgentTranscriptSessionCatalog(tmp_path, index_writable=False)
    assert len(catalog.list_path_summaries()) == 2
    directory = AgentTranscriptDirectoryRuntime(session_dir=tmp_path)
    assert len(directory.list_discovered_session_summaries()) == 2
    assert snapshot(tmp_path) == before
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_bytes(paths[0].read_bytes())
    before = snapshot(tmp_path)
    assert len(catalog.list_path_collision_summaries()) == 2
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("change", ["delete", "symlink"])
def test_readonly_deferred_payload_uses_verified_bytes_after_source_changes(tmp_path, monkeypatch, change):
    async def scenario():
        path = tmp_path / "session.jsonl"
        records = _model_input_records()
        write_agent_transcript_export(path, _header(), list(records))
        layout = AgentTranscriptFileLayout(tmp_path)
        key = layout.key(_header().conversation_id)
        await create_agent_transcript_file_store(layout).load(key)
        snapshot = (await create_agent_transcript_file_store(layout, read_only=True).load(key)).snapshot
        assert isinstance(snapshot.records[0].payload, DeferredModelInputNodeBundle)
        path.unlink()
        if change == "symlink":
            other = tmp_path / "unrelated.txt"
            other.write_text("must not be read", encoding="utf-8")
            path.symlink_to(other)

        def forbid_open(*_, **__):
            raise AssertionError("readonly deferred payload reopened a path")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", forbid_open)
            assert snapshot.records[0].payload.nodes == records[0].payload.nodes
            assert snapshot.records[1].payload.nodes == records[1].payload.nodes
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX parent-dir open")
@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_leaf_open_failure_survives_parent_close_failure(tmp_path, monkeypatch, error_type):
    failure = error_type("test leaf open")
    opened, closed = [], []

    def open_file(*args, **kwargs):
        opened.append(args)
        if len(opened) == 1:
            return 101
        raise failure

    def close(fd):
        closed.append(fd)
        raise OSError("test parent close")

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "open", open_file)
        patch.setattr(module.os, "close", close)
        with pytest.raises(error_type) as raised:
            module._open_file_no_follow(tmp_path / "leaf", flags=0)
        assert raised.value is failure
    assert closed == [101]
    assert failure.__notes__ == ["transcript reader descriptor cleanup failed"]


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX FIFO replacement")
@pytest.mark.parametrize("prefix", [False, True])
def test_readonly_fifo_replacement_cannot_block_open(tmp_path, monkeypatch, prefix):
    path = tmp_path / "source.jsonl"
    path.write_bytes(b"fixture\n")
    original = module.os.open
    swapped = False

    def open_file(name, flags, *args, **kwargs):
        nonlocal swapped
        if name == path.name and kwargs.get("dir_fd") is not None:
            assert flags & module.os.O_NONBLOCK  # Guard the negative test from hanging.
            path.unlink()
            module.os.mkfifo(path)
            swapped = True
        return original(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", open_file)
    with pytest.raises(OSError, match="identity changed"):
        if prefix:
            module._read_stable_regular_prefix(path, max_bytes=100)
        else:
            module._read_stable_regular_file(path)
    assert swapped


def test_writable_store_namespace_page_is_readonly_but_key_load_can_build_cache(tmp_path):
    async def scenario():
        paths = seed(tmp_path)
        layout = AgentTranscriptFileLayout(tmp_path)
        store = create_agent_transcript_file_store(layout)
        before = snapshot(tmp_path)
        assert len((await store.scan_page(layout.namespace)).heads) == 2
        assert snapshot(tmp_path) == before
        await store.load(layout.key("session-1"))
        assert _projection_cache_path(paths[0]).exists()
        assert not _projection_cache_path(paths[1]).exists()
    asyncio.run(scenario())
