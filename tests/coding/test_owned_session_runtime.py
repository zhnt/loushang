from __future__ import annotations

import asyncio
import os
import shutil
import sys
from types import SimpleNamespace

import pytest

from loushang.ai.types import UserMessage
from loushang.coding import session_manager as managers
from loushang.coding.bootstrap import create_agent_session, create_agent_session_runtime
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.harness.transcript.writer_lease import TranscriptWriterError
from tests.harness.transcript.test_readonly_store import snapshot
from tests.harness.transcript.test_writer_images import message
from tests.harness.transcript.test_writer_lease import busy, lease

from .test_agent_session_runtime import _model

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Coding runtime")


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_default_bootstrap_selects_owned_store_only_on_supported_platform(tmp_path, monkeypatch, platform):
    from loushang.coding import bootstrap

    monkeypatch.setattr(bootstrap, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    selected = create_agent_session_runtime(session_dir=tmp_path / "sessions", model=_model(), no_tools=True)
    factory = selected._owned_transcript_factory
    if platform == "linux":
        assert factory is not None
        assert factory._store_state_root == tmp_path / "platform/state/session-stores"
    else:
        assert factory is None
    assert not (tmp_path / "platform").exists()
    assert not (tmp_path / "sessions").exists()


def runtime(root, **kwargs):
    def build(manager, *, session_start_event):
        return create_agent_session(
            session_manager=manager, model=_model(), no_tools=True,
            session_start_event=session_start_event,
        )

    return AgentSessionRuntime(
        session_dir=root,
        session_factory=build,
        owned_transcripts=True,
        **kwargs,
    )


def test_default_runtime_creates_new_workspace_beside_unrelated_v1(tmp_path, monkeypatch):
    from loushang.harness.transcript.store_admission import TranscriptStoreAdmission

    platform = tmp_path / "platform"
    monkeypatch.setenv("LOUSHANG_HOME", str(platform))
    state = platform / "state/session-stores"
    old_root = tmp_path / "old-data/sessions"
    old_root.parent.mkdir(mode=0o700)
    old_root.mkdir(mode=0o700)
    old = TranscriptStoreAdmission(old_root, state_root=state)
    try:
        binding = old.open()
        witness = old.witness_root
    finally:
        old.close()
    old_tree, old_evidence = snapshot(old_root.parent), snapshot(witness)

    async def scenario():
        selected = create_agent_session_runtime(
            session_dir=tmp_path / "new-data/sessions", model=_model(),
            persist=True, no_tools=True,
        )
        try:
            session = await selected.create_session(cwd=str(tmp_path))
            await session.session_manager.append_message(
                UserMessage(role="user", content="new workspace", timestamp=1),
            )
            assert snapshot(old_root.parent) == old_tree
            assert snapshot(witness) == old_evidence
        finally:
            await selected.dispose_session_runtime()

    asyncio.run(scenario())
    restored = TranscriptStoreAdmission(old_root, state_root=state)
    try:
        assert restored.open() == binding
    finally:
        restored.close()


def test_default_runtime_enrolls_canonical_legacy_store_with_shared_assets(
    tmp_path, monkeypatch,
):
    platform = tmp_path / "platform"
    monkeypatch.setenv("LOUSHANG_HOME", str(platform))
    tmp_path.chmod(0o700)
    platform.mkdir(mode=0o700)
    (platform / "data").mkdir(mode=0o700)
    session_root = platform / "data/sessions"
    session_root.mkdir(mode=0o700)
    assets = platform / "data/session-assets"
    assets.mkdir(mode=0o700)
    legacy_asset = assets / "legacy-asset"
    legacy_asset.write_bytes(b"preserve me")
    (platform / "state").mkdir(mode=0o700)
    stores = platform / "state/session-stores"
    stores.mkdir(mode=0o700)
    (stores / "unrelated-incomplete").mkdir(mode=0o700)

    async def scenario():
        selected = create_agent_session_runtime(
            session_dir=session_root,
            model=_model(),
            persist=True,
            no_tools=True,
        )
        try:
            session = await selected.create_session(cwd=str(tmp_path))
            await session.session_manager.append_message(
                UserMessage(role="user", content="upgraded store", timestamp=1),
            )
            assert session.session_manager.session_file.parent == session_root
            assert legacy_asset.read_bytes() == b"preserve me"
        finally:
            await selected.dispose_session_runtime()

    asyncio.run(scenario())


def test_default_runtime_does_not_enroll_custom_legacy_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    session_root = tmp_path / "custom-data/sessions"
    session_root.mkdir(parents=True, mode=0o700)
    (session_root.parent / "session-assets").mkdir(mode=0o700)

    async def scenario():
        selected = create_agent_session_runtime(
            session_dir=session_root,
            model=_model(),
            persist=True,
            no_tools=True,
        )
        try:
            with pytest.raises(TranscriptWriterError, match="conflict"):
                await selected.create_session(cwd=str(tmp_path))
        finally:
            await selected.dispose_session_runtime()

    asyncio.run(scenario())


def test_graph_index_unknown_close_keeps_writer_until_original_cleanup_settles(tmp_path, monkeypatch):
    from loushang.harness.journal._rooted_io import RootedFile

    async def scenario():
        root = tmp_path / "data/sessions"
        owner = runtime(root, store_state_root=tmp_path / "state/stores")
        session = await owner.create_session(cwd=str(tmp_path))
        manager = session.session_manager
        await manager.append_message(UserMessage(role="user", content="first", timestamp=1))
        owner.refresh_session_index()
        await manager.append_message(UserMessage(role="user", content="latest", timestamp=2))
        retained, calls = {}, []
        original_lock, original_close = RootedFile.acquire_lock, os.close

        def capture(target, **kwargs):
            before = set(target._operation.lock_fds)
            original_lock(target, **kwargs)
            if target._name == ".session-index.json" and not retained:
                fd, = target._operation.lock_fds - before
                retained.update(fd=fd, operation=target._operation)

        def lose_close(fd):
            if fd == retained.get("fd"):
                assert not calls, "reclosed an unknown index descriptor"
                original_close(fd)
                replacement = os.open(os.devnull, os.O_RDONLY)
                if replacement != fd:
                    os.dup2(replacement, fd)
                    original_close(replacement)
                calls.append(fd)
                raise OSError("test index close receipt lost")
            original_close(fd)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(RootedFile, "acquire_lock", capture)
                patch.setattr(os, "close", lose_close)
                for _ in range(2):
                    with pytest.raises(RuntimeError, match="cleanup remains pending"):
                        await owner.dispose_session_runtime()
                    busy(root, conversation=manager.header.conversation_id)
                    assert manager._lifecycle_session.transcript_file_io.cleanup_pending
                    assert not manager.runtime_disposed
                    assert calls == [retained["fd"]]
                    os.fstat(calls[0])
        finally:
            if calls:
                # Only the injector knows close completed; production must keep
                # the unknown debt rather than guess ownership of a reused fd.
                operation = retained["operation"]
                operation.descriptors.pop(calls[0], None)
                operation.lock_fds.discard(calls[0])
                original_close(calls[0])
            await owner.dispose_session_runtime()
        assert manager.runtime_disposed
        reopened = lease(root, conversation=manager.header.conversation_id)
        try:
            reopened.acquire()
        finally:
            reopened.close()

    asyncio.run(scenario())


def test_actual_coding_runtime_create_restore_and_application_writer(tmp_path):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        first, second = runtime(root), runtime(root)
        try:
            session = await first.create_session(cwd=str(tmp_path))
            manager = session.session_manager
            assert manager._creation_factory is first._owned_transcript_factory
            assert manager._lifecycle_session.ownership_state == "graph_owned"
            await manager.append_message(UserMessage(role="user", content="retained", timestamp=1.0))
            path, identity = manager.session_file, manager.header.conversation_id
            busy(root, conversation=identity)
            with pytest.raises(TranscriptWriterError, match="busy"):
                await second.restore_session(path)
            await first.dispose_session_runtime()
            assert manager.runtime_disposed
            restored = await second.restore_session(path)
            assert restored.session_manager.header.conversation_id == identity
            assert restored.session_manager.entries
            forked = await second.fork_session(restored.session_manager.leaf_id)
            assert forked.session_manager._creation_factory is second._owned_transcript_factory
            assert forked.session_manager._lifecycle_session.ownership_state == "graph_owned"
            assert forked.session_manager.header.conversation_id != identity
            assert restored.session_manager.runtime_disposed
            await second.dispose_session_runtime()
            assert forked.session_manager.runtime_disposed
            reopened = lease(root, conversation=identity)
            try:
                reopened.acquire()
            finally:
                reopened.close()
        finally:
            await first.dispose_session_runtime()
            await second.dispose_session_runtime()

    asyncio.run(scenario())


def test_default_embedded_bootstrap_respects_existing_application_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    async def scenario():
        data = tmp_path / "data"
        data.mkdir(mode=0o700)
        root = data / "sessions"
        root.mkdir(mode=0o700)
        first = runtime(root, store_state_root=tmp_path / "platform/state/session-stores")
        embedded = create_agent_session_runtime(session_dir=root, model=_model(), no_tools=True)
        try:
            session = await first.create_session(cwd=str(tmp_path))
            manager = session.session_manager
            await manager.append_message(UserMessage(role="user", content="retained", timestamp=1.0))
            path = manager.session_file
            assert embedded._owned_transcript_factory is not None
            for operation in (
                lambda: embedded.restore_session(path),
                lambda: embedded.rename_session(path, "renamed"),
                lambda: embedded.delete_session(path),
            ):
                with pytest.raises(TranscriptWriterError, match="busy"):
                    await operation()
            await first.dispose_session_runtime()
            restored = await embedded.restore_session(path)
            assert restored.session_manager.header.conversation_id == manager.header.conversation_id
            busy(root, conversation=manager.header.conversation_id)
        finally:
            await first.dispose_session_runtime()
            await embedded.dispose_session_runtime()

    asyncio.run(scenario())


@pytest.mark.parametrize("index", ["missing", "corrupt"])
def test_preview_uses_readonly_source_and_never_inherits_writer_factory(tmp_path, index):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        owner = runtime(root)
        previews = []
        try:
            current = await owner.create_session(cwd=str(tmp_path))
            manager = current.session_manager
            await manager.append_message(message())
            Bound = type(manager)
            # Copy only the transcript into a source without any sidecars.
            preview_data = tmp_path / "preview-data"
            source = preview_data / "sessions"
            source.mkdir(parents=True)
            path = source / manager.session_file.name
            path.write_bytes(manager.session_file.read_bytes())
            authority = manager.header.conversation_id
            shutil.copytree(tmp_path / "session-assets" / authority, preview_data / "session-assets" / authority)
            if index == "corrupt":
                Bound.index_file(source).write_bytes(b"invalid index")
            before = snapshot(preview_data)
            preview = await Bound.open(path, persist=False)
            previews.append(preview)
            memory = await Bound.in_memory(cwd=tmp_path)
            previews.append(memory)
            recent = await Bound.continue_recent(source, tmp_path, persist=False)
            previews.append(recent)
            assert recent.header.conversation_id == manager.header.conversation_id
            assert recent.entries
            assert not preview.persist and preview._creation_factory is None
            assert preview.entries and not memory.entries
            assert preview._lifecycle_session.session_blob_health
            assert all(item.state == "available" for item in preview._lifecycle_session.session_blob_health)
            await preview.append_message(UserMessage(role="user", content="local only", timestamp=2.0))
            assert snapshot(preview_data) == before
            assert manager._creation_factory is owner._owned_transcript_factory
            busy(root, conversation=manager.header.conversation_id)
            await owner.dispose_session_runtime()
            with pytest.raises(RuntimeError, match="closed"):
                await Bound.in_memory(cwd=tmp_path)
        finally:
            for preview in previews:
                await preview.dispose_runtime_profile()
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_owned_runtime_maintenance_is_fenced_and_preserves_attachments(tmp_path):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        first, second = runtime(root), runtime(root)
        try:
            session = await first.create_session(cwd=str(tmp_path))
            manager = session.session_manager
            await manager.append_message(message())
            path = manager.session_file
            for operation in (
                lambda: second.rename_session(path, "renamed"),
                lambda: second.delete_session(path),
            ):
                with pytest.raises(TranscriptWriterError, match="busy"):
                    await operation()
            assert path.is_file()
            await first.dispose_session_runtime()
            summary = await second.rename_session(path, "renamed")
            assert summary.name == "renamed"
            assets = tmp_path / "session-assets" / manager.header.conversation_id
            before = snapshot(assets)
            assert await second.delete_session(path)
            assert not path.exists() and snapshot(assets) == before
            await second.dispose_session_runtime()
            with pytest.raises(RuntimeError, match="closed"):
                await second._product_runtime_ports.delete_transcript(path, None)
        finally:
            await first.dispose_session_runtime()
            await second.dispose_session_runtime()

    asyncio.run(scenario())


def test_owned_runtime_retains_rename_cleanup_debt(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        first, second = runtime(root), runtime(root)

        async def unavailable(binding):
            raise OSError("rename cleanup unavailable")

        try:
            session = await first.create_session(cwd=str(tmp_path))
            manager = session.session_manager
            await manager.append_message(UserMessage(role="user", content="history", timestamp=1.0))
            path, identity = manager.session_file, manager.header.conversation_id
            await first.dispose_session_runtime()
            with monkeypatch.context() as patch:
                patch.setattr(managers.CODING_TRANSCRIPT_RUNTIME._binder, "dispose", unavailable)
                with pytest.raises(OSError, match="rename cleanup"):
                    await second.rename_session(path, "renamed")
                retained, = second._owned_transcript_factory.pending_preparations
                busy(root, conversation=identity)
                with pytest.raises(OSError, match="rename cleanup"):
                    await second.dispose_session_runtime()
                assert second._owned_transcript_factory.pending_preparations == (retained,)
            await second.dispose_session_runtime()
            assert not second._owned_transcript_factory.pending_preparations
        finally:
            await first.dispose_session_runtime()
            await second.dispose_session_runtime()

    asyncio.run(scenario())


def test_actual_runtime_retains_factory_debt_before_wrapper_delivery(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        owner = runtime(root)
        captured = []

        def fail_wrapper(self, *, lifecycle_session):
            captured.append(lifecycle_session)
            raise ValueError("wrapper construction failed")

        async def unavailable(binding):
            raise OSError("runtime cleanup unavailable")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(managers.SessionManager, "__init__", fail_wrapper)
                patch.setattr(managers.CODING_TRANSCRIPT_RUNTIME._binder, "dispose", unavailable)
                with pytest.raises(ValueError, match="wrapper construction"):
                    await owner.create_session(cwd=str(tmp_path))
                retained, = owner._owned_transcript_factory.pending_preparations
                assert retained._session is captured[0]
                assert not owner._transcript_construction_store.pending_transcripts
                identity = captured[0].context.header.conversation_id
                busy(root, conversation=identity)
                with pytest.raises(OSError, match="cleanup unavailable"):
                    await owner.dispose_session_runtime()
                assert owner._owned_transcript_factory.pending_preparations == (retained,)
            await owner.dispose_session_runtime()
            assert not owner._owned_transcript_factory.pending_preparations
            reopened = lease(root, conversation=identity)
            try:
                reopened.acquire()
            finally:
                reopened.close()
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_actual_runtime_close_fences_inflight_binding_before_join(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        owner = runtime(root)
        selected = owner._owned_transcript_factory
        lifecycle = selected._lifecycle
        original = lifecycle._bind_runtime_owned
        entered, release, closing = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            result = await original(*args)
            entered.set()
            await release.wait()
            return result

        async def close():
            closing.set()
            await owner.dispose_session_runtime()

        monkeypatch.setattr(lifecycle, "_bind_runtime_owned", delayed)
        creation = asyncio.create_task(owner.create_session(cwd=str(tmp_path)))
        shutdown = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            retained, = selected.pending_preparations
            shutdown = asyncio.create_task(close())
            await asyncio.wait_for(closing.wait(), 5)
            assert selected._closing and retained.closing and not shutdown.done()
            release.set()
            with pytest.raises((RuntimeError, TranscriptWriterError)):
                await asyncio.wait_for(creation, 5)
            await asyncio.wait_for(shutdown, 5)
            assert not selected.pending_preparations
            assert not owner._transcript_construction_store.pending_transcripts
            assert owner.current_session is None
        finally:
            release.set()
            await asyncio.gather(creation, *([shutdown] if shutdown else []), return_exceptions=True)
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_owned_runtime_does_not_replace_legacy_global_factory(tmp_path):
    original = managers.SessionManager._session_factory()
    owned = runtime(tmp_path)
    legacy = AgentSessionRuntime(session_dir=tmp_path, session_factory=lambda manager: manager)
    assert legacy._owned_transcript_factory is None
    assert owned._owned_transcript_factory is not original
    assert managers.SessionManager._session_factory() is original is managers._FACTORY
