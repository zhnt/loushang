"""Summary publication borrows the original writer lifetime and frozen state."""

import asyncio
import sys
import threading
from functools import partial

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript.jsonl_file import publish_owned_transcript_projection
from loushang.harness.transcript.session_catalog import (
    _MAX_PATH_SUMMARY_TOTAL_BYTES,
    AgentTranscriptSessionCatalog,
    _status_fingerprint,
)

from .test_owned_session_factory import factory, new
from .test_writer_io import wait_until

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned index")


def test_owned_index_rejects_old_snapshot_then_publishes_latest(tmp_path):
    async def scenario():
        selected = factory(store_state_root=tmp_path / "state")
        session = await new(selected, tmp_path / "data/sessions")
        manager = ProductTranscriptSession(lifecycle_session=session)
        try:
            await manager.append_message(UserMessage(role="user", content="first", timestamp=1))
            catalog = AgentTranscriptSessionCatalog(manager.session_dir)
            catalog.refresh_index()
            frozen = tuple(manager.entries)
            await manager.append_message(UserMessage(role="user", content="latest", timestamp=2))
            before = catalog.index_path.read_bytes()
            async with session.operation_scope():
                assert not catalog.publish_owned_summary(
                    publication=partial(
                        publish_owned_transcript_projection,
                        file_io=session.transcript_file_io, root=catalog.session_dir,
                        key=session.runtime_binding.key, source_path=manager.session_file,
                        header=manager.header, records=frozen,
                        max_bytes=_MAX_PATH_SUMMARY_TOTAL_BYTES, fingerprint=_status_fingerprint,
                    ),
                    key=session.runtime_binding.key, source_path=manager.session_file,
                    header=manager.header, records=frozen, leaf_id=manager.leaf_id,
                )
            assert catalog.index_path.read_bytes() == before
            await manager.publish_index_summary()
            summaries = catalog.load_index()
            assert len(summaries) == 1
            assert summaries[0].last_message_preview == "latest"
            assert summaries[0].entry_count == 2
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_owned_publication_does_not_create_absent_index(tmp_path):
    async def scenario():
        selected = factory(store_state_root=tmp_path / "state")
        session = await new(selected, tmp_path / "data/sessions")
        manager = ProductTranscriptSession(lifecycle_session=session)
        try:
            await manager.append_message(UserMessage(role="user", content="first", timestamp=1))
            await manager.publish_index_summary()
            assert not (manager.session_dir / ".session-index.json").exists()
            assert not (manager.session_dir / ".session-index.json.lock").exists()
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_cancelled_publication_waits_for_original_native_operation(tmp_path, monkeypatch):
    async def scenario():
        selected = factory(store_state_root=tmp_path / "state")
        session = await new(selected, tmp_path / "data/sessions")
        manager = ProductTranscriptSession(lifecycle_session=session)
        entered, release = threading.Event(), threading.Event()
        original = AgentTranscriptSessionCatalog.publish_owned_summary

        def held(catalog, **kwargs):
            entered.set()
            assert release.wait(10), "test did not release publication"
            return original(catalog, **kwargs)

        task = None
        try:
            await manager.append_message(UserMessage(role="user", content="first", timestamp=1))
            AgentTranscriptSessionCatalog(manager.session_dir).refresh_index()
            monkeypatch.setattr(AgentTranscriptSessionCatalog, "publish_owned_summary", held)
            task = asyncio.create_task(manager.publish_index_summary())
            await wait_until(entered.is_set)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert session.ownership_state != "disposed"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not session.transcript_file_io.cleanup_pending
        finally:
            release.set()
            if task is not None and not task.done():
                await asyncio.gather(task, return_exceptions=True)
            monkeypatch.setattr(AgentTranscriptSessionCatalog, "publish_owned_summary", original)
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_owned_publication_never_updates_replacement_directory(tmp_path):
    async def scenario():
        selected = factory(store_state_root=tmp_path / "state")
        root = tmp_path / "data/sessions"
        session = await new(selected, root)
        manager = ProductTranscriptSession(lifecycle_session=session)
        try:
            await manager.append_message(UserMessage(role="user", content="first", timestamp=1))
            AgentTranscriptSessionCatalog(root).refresh_index()
            await manager.append_message(UserMessage(role="user", content="latest", timestamp=2))
            root.rename(root.with_name("retained-sessions"))
            root.mkdir(mode=0o700)
            replacement = root / ".session-index.json"
            replacement.write_bytes(b"replacement directory must remain untouched")
            replacement.chmod(0o600)
            await manager.publish_index_summary()
            assert replacement.read_bytes() == b"replacement directory must remain untouched"
            assert {path.name for path in root.iterdir()} == {".session-index.json"}
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_legacy_catalog_busy_does_not_delete_owned_cache(tmp_path):
    from loushang.harness.journal.jsonl import JournalLockUnavailable

    async def scenario():
        selected = factory(store_state_root=tmp_path / "state")
        session = await new(selected, tmp_path / "data/sessions")
        manager = ProductTranscriptSession(lifecycle_session=session)
        try:
            await manager.append_message(UserMessage(role="user", content="first", timestamp=1))
            catalog = AgentTranscriptSessionCatalog(manager.session_dir)
            catalog.refresh_index()
            before = catalog.index_path.read_bytes()
            async with session.operation_scope():
                with session.transcript_file_io.bind(catalog.index_path) as target:
                    target.acquire_lock(exclusive=True, blocking=False, suffix=".lock")
                    with pytest.raises(JournalLockUnavailable):
                        await catalog.upsert_summary(
                            manager._get_session_index_summary(), source_revision=1,
                        )
                    assert catalog.index_path.read_bytes() == before
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())
