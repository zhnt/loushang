from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.ai.types import UserMessage
from loushang.coding import session_manager as managers
from loushang.harness.session import lifecycle as lifecycle_module
from loushang.harness.transcript import session_factory as factory_module
from loushang.harness.transcript.export import export_agent_transcript_bundle
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint,
)
from tests.harness.transcript.test_writer_lease import busy, lease

from .test_owned_session_runtime import runtime

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned import")


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("entry", ["import", "prepared_import", "restore", "prepared_restore", "abort_import"])
def test_owned_import_uses_original_candidate_without_path_staging(tmp_path, monkeypatch, archive, entry):
    async def scenario():
        source_root, target_root = tmp_path / "source" / "sessions", tmp_path / "target" / "sessions"
        source_root.parent.mkdir(mode=0o700)
        target_root.parent.mkdir(mode=0o700)
        source_root.mkdir(mode=0o700)
        target_root.mkdir(mode=0o700)
        source_owner, target_owner = runtime(source_root), runtime(target_root)
        candidate = None
        try:
            source = await source_owner.create_session(cwd=str(tmp_path))
            manager = source.session_manager
            await manager.append_message(UserMessage(role="user", content="frozen import", timestamp=1.0))
            path = manager.session_file
            identity = manager.header.conversation_id
            if archive:
                path = tmp_path / "portable.zip"
                export_agent_transcript_bundle(
                    manager.header, manager.entries, session_dir=source_root,
                    output_path=path, allow_private=True,
                )
            await source_owner.dispose_session_runtime()
            fingerprint = session_file_authority_fingerprint(path)

            def forbidden(*args, **kwargs):
                raise AssertionError("owned import must not stage a pathname copy")

            monkeypatch.setattr(lifecycle_module, "stage_file_import", forbidden)
            if entry.startswith("prepared") or entry == "abort_import":
                if entry in {"prepared_import", "abort_import"}:
                    candidate = await target_owner.lifecycle.prepare_import_file(
                        path, destination_dir=target_root, expected_source_fingerprint=fingerprint,
                    )
                else:
                    candidate = await target_owner.prepare_restore_session_operation(path)
                assert target_owner.current_session is None
                if entry == "abort_import":
                    assert len(list(target_root.glob("*.jsonl"))) == 1
                    await candidate.abort()
                    assert not list(target_root.glob("*.jsonl"))
                    assert target_owner.current_session is None
                    return
                result = await candidate.consume()
            elif entry == "restore":
                result = await target_owner.restore_session_operation(path)
            else:
                result = await target_owner.import_session_operation(
                    path, expected_source_fingerprint=fingerprint,
                )
            assert not result.cancelled
            imported = target_owner.current_session.session_manager
            assert imported.header.conversation_id == identity
            assert imported.session_file.parent == target_root
            assert imported._creation_factory is target_owner._owned_transcript_factory
            assert imported._lifecycle_session.ownership_state == "graph_owned"
            assert len(list(target_root.glob("*.jsonl"))) == 1
            assert not list(target_root.glob("*.zip"))
        finally:
            if candidate is not None:
                await candidate.close()
            await source_owner.dispose_session_runtime()
            await target_owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_owned_restore_checks_discovery_fingerprint_at_real_source_read(tmp_path, monkeypatch):
    async def scenario():
        source_root, target_root = tmp_path / "source", tmp_path / "target"
        source_root.mkdir(mode=0o700)
        target_root.mkdir(mode=0o700)
        source_owner, target_owner = runtime(source_root), runtime(target_root)
        try:
            source = await source_owner.create_session(cwd=str(tmp_path))
            await source.session_manager.append_message(UserMessage(role="user", content="selected source", timestamp=1.0))
            path = source.session_manager.session_file
            await source_owner.dispose_session_runtime()
            selected = target_owner.resolve_discovered_session_source(path)
            monkeypatch.setattr(target_owner, "resolve_discovered_session_source", lambda _: selected)
            read = factory_module._read_stable_regular_file
            calls = []

            def replaced(path, **kwargs):
                assert kwargs["expected_source_fingerprint"] == selected.authority_fingerprint
                calls.append(True)
                with path.open("ab") as handle:
                    handle.write(b" \n")
                return read(path, **kwargs)

            monkeypatch.setattr(factory_module, "_read_stable_regular_file", replaced)
            with pytest.raises(OSError, match="identity changed"):
                await target_owner.restore_session_operation(path)
            assert calls == [True]
            assert target_owner.current_session is None
            assert not target_owner._owned_transcript_factory.pending_preparations
            assert tuple(target_root.iterdir()) == ()
        finally:
            await source_owner.dispose_session_runtime()
            await target_owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_owned_import_rejects_foreign_destination_before_source_io(tmp_path):
    async def scenario():
        root, other = tmp_path / "sessions", tmp_path / "other"
        owner = runtime(root)
        try:
            with pytest.raises(ValueError, match="bound Session root"):
                await owner.lifecycle.import_file(tmp_path / "missing.jsonl", destination_dir=other)
            assert not root.exists() and not other.exists()
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["wrapper", "product"])
def test_owned_import_retains_original_cleanup_owner_before_product_delivery(tmp_path, monkeypatch, failure):
    async def scenario():
        source_root, target_root = tmp_path / "source", tmp_path / "target"
        source_root.mkdir(mode=0o700)
        target_root.mkdir(mode=0o700)
        source_owner, target_owner = runtime(source_root), runtime(target_root)
        try:
            source = await source_owner.create_session(cwd=str(tmp_path))
            await source.session_manager.append_message(UserMessage(role="user", content="persist import source", timestamp=1.0))
            path = source.session_manager.session_file
            identity = source.session_manager.header.conversation_id
            await source_owner.dispose_session_runtime()

            def fail_delivery(*args, **kwargs):
                raise ValueError("original imported delivery failed")

            async def fail_cleanup(*args, **kwargs):
                raise OSError("imported cleanup unavailable")

            with monkeypatch.context() as patch:
                if failure == "wrapper":
                    patch.setattr(managers.SessionManager, "__init__", fail_delivery)
                else:
                    patch.setattr(target_owner._transcript_construction_store, "_build_session", fail_delivery)
                patch.setattr(managers.CODING_TRANSCRIPT_RUNTIME._binder, "dispose", fail_cleanup)
                with pytest.raises(ValueError, match="original imported delivery"):
                    await target_owner.import_session_operation(path)
                assert target_owner.current_session is None
                factory_pending = target_owner._owned_transcript_factory.pending_preparations
                store_pending = target_owner._transcript_construction_store.pending_transcripts
                assert (len(factory_pending), len(store_pending)) == ((1, 0) if failure == "wrapper" else (0, 1))
                busy(target_root, conversation=identity)
                with pytest.raises(OSError, match="cleanup unavailable"):
                    await target_owner.dispose_session_runtime()
                busy(target_root, conversation=identity)
            await target_owner.dispose_session_runtime()
            reopened = lease(target_root, conversation=identity)
            try:
                reopened.acquire()
            finally:
                reopened.close()
        finally:
            await source_owner.dispose_session_runtime()
            await target_owner.dispose_session_runtime()

    asyncio.run(scenario())
