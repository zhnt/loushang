from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.journal import journal_file_lock
from loushang.harness.transcript import (
    ProductTranscriptSession,
    session_artifacts,
    writer_lifecycle,
)

from .test_lifecycle import _header
from .test_runtime_profile import _runtime
from .test_writer_blobs import blob_busy
from .test_writer_images import message, prepare
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux retained restore")


async def saved(root):
    runtime = _runtime("coding")
    owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned)
    session = ProductTranscriptSession(lifecycle_session=await owner.create())
    try:
        await session.append_message(message())
    finally:
        await owner.dispose()
    return runtime


@pytest.mark.parametrize("swap", [False, True])
def test_actual_owned_restore_health_uses_original_port(tmp_path, monkeypatch, swap):
    async def scenario():
        data = tmp_path / "data"
        data.mkdir(mode=0o700)
        root = data / "sessions"
        root.mkdir(mode=0o700)
        runtime = await saved(root)
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned, defer_materialization=True)
        construct = writer_lifecycle._lifecycle_session
        blob_store = session_artifacts.SessionBlobStore
        calls = []
        untouched = None

        def before_health(*args, **kwargs):
            nonlocal untouched
            assert owner._active_io == 1
            if swap:
                data.rename(tmp_path / "original")
                data.mkdir(mode=0o700)
                (data / "sentinel").write_bytes(b"replacement")
                untouched = tree(data)
            def forbidden(*args, **kwargs):
                raise AssertionError("owned health used pathname IO")

            with monkeypatch.context() as patch:
                for method in ("open", "read_bytes", "write_bytes", "stat", "lstat", "exists", "mkdir", "resolve"):
                    patch.setattr(Path, method, forbidden)
                return construct(*args, **kwargs)

        def retained_store(*args, **kwargs):
            calls.append(kwargs.get("file_io"))
            assert kwargs.get("file_io") is owner.blob_file_io
            return blob_store(*args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(writer_lifecycle, "_lifecycle_session", before_health)
                patch.setattr(session_artifacts, "SessionBlobStore", retained_store)
                result = await owner.restore()
            assert len(calls) == 1
            assert len(result.session_blob_health) == 1
            assert result.session_blob_health[0].state == "available"
            assert owner._active_io == 0
            if swap:
                assert tree(data) == untouched
        finally:
            await owner.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("state", ["missing", "corrupt"])
def test_restore_health_degrades_real_damage_without_rewriting_history(tmp_path, state):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        runtime = await saved(root)
        history = (root / "session.jsonl").read_bytes()
        store = SessionBlobStore(tmp_path, _header().conversation_id)
        target = store.objects_root / store.records[0].blob_id
        if state == "missing":
            target.unlink()
        else:
            target.write_bytes(b"corrupt")
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned, defer_materialization=True)
        try:
            result = await owner.restore()
            assert result.session_blob_health[0].state == state
            assert (root / "session.jsonl").read_bytes() == history
        finally:
            await owner.dispose()

    asyncio.run(scenario())


def test_restore_health_real_short_lock_contention_retains_both_leases(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        runtime = await saved(root)
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned, defer_materialization=True)
        construct = writer_lifecycle._lifecycle_session

        def contended(*args, **kwargs):
            lock = tmp_path / "session-assets/.locks" / _header().conversation_id
            with journal_file_lock(lock, "exclusive"):
                return construct(*args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(writer_lifecycle, "_lifecycle_session", contended)
                with pytest.raises(BlockingIOError):
                    await owner.restore()
            assert owner._session is None and owner._runtime is not None
            assert_busy(root)
            blob_busy(root)
        finally:
            await owner.dispose()
        assert_available(root)

    asyncio.run(scenario())


@pytest.mark.parametrize("where", ["construct", "read"])
def test_health_contention_retains_unpublished_session_owner(tmp_path, monkeypatch, where):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        runtime = await saved(root)
        owner, _ = prepare(root, runtime, runtime.bind_lifecycle_owned, defer_materialization=True)

        def busy(*args, **kwargs):
            raise BlockingIOError("test restore attachment busy")

        try:
            with monkeypatch.context() as patch:
                if where == "construct":
                    patch.setattr(session_artifacts, "SessionBlobStore", busy)
                else:
                    patch.setattr(SessionBlobStore, "read_bytes", busy)
                with pytest.raises(BlockingIOError, match="restore attachment busy"):
                    await owner.restore()
            assert owner._session is None and owner._runtime is not None
            assert owner._active_io == 0 and owner.cleanup_pending
            assert_busy(root)
        finally:
            await owner.dispose()
        assert_available(root)

    asyncio.run(scenario())
