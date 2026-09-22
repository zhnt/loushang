from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from dataclasses import replace

import pytest

from loushang.ai.types import ImagePart, UserMessage
from loushang.appserver.protocol import SessionAvailabilityV1, SessionCompatibilityV1
from loushang.appservice.discovery_ports import HostedSessionDiscoveryScopeV1
from loushang.coding.hosted_catalog import (
    CodingHostedCatalogError,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.managed_catalog import CodingManagedSessionCatalogV1
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.conversation.stores import file as file_module
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file,
    write_agent_transcript_export,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_hosted_catalog import _intent

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned managed catalog")


def catalog(tmp_path, *, workspace=None):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700, exist_ok=True)
    return CodingManagedSessionCatalogV1(session_root=root, workspace=workspace or tmp_path)


def tree(root):
    # Same complete oracle as test_writer_root_binding; callers include the
    # Session root's parent so sibling attachment/index trees are covered.
    return {str(path.relative_to(root)): (
        path.lstat().st_mode, path.lstat().st_ino, path.lstat().st_mtime_ns,
        path.read_bytes() if path.is_file() else None,
    ) for path in (root, *root.rglob("*"))}


@pytest.mark.parametrize("grant", [False, True])
def test_missing_root_discovery_readonly_and_creation_requires_grant(tmp_path, grant):
    async def scenario():
        root = tmp_path / "new" / "sessions"
        owner = CodingManagedSessionCatalogV1(
            session_root=root, workspace=tmp_path, initialize_session_root=grant,
        )
        try:
            before = tree(tmp_path)
            for scope in owner.scopes:
                assert not (await discovery(owner, scope)).candidates
            assert not await owner.list_identities(tuple(s.discovery_scope for s in owner.scopes), limit=256)
            assert tree(tmp_path) == before
            if not grant:
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await owner.create_candidate(_intent(owner.scopes[0]))
                assert tree(tmp_path) == before
            else:
                active = await owner.create_candidate(_intent(owner.scopes[0]))
                try:
                    assert len(tuple(root.glob("*.jsonl"))) == 1
                    assert root.stat().st_mode & 0o777 == 0o700
                    assert not owner._root_initialization
                finally:
                    await active.close()
        finally:
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("observe_existing", [False, True])
def test_missing_old_root_never_gets_a_second_initialization_grant(tmp_path, observe_existing):
    async def scenario():
        root = tmp_path / "sessions"
        owner = CodingManagedSessionCatalogV1(
            session_root=root, workspace=tmp_path, initialize_session_root=True,
        )
        active = None
        try:
            if observe_existing:
                root.mkdir(mode=0o700)
                await discovery(owner, owner.scopes[0])
            else:
                active = await owner.create_candidate(_intent(owner.scopes[0]))
            assert not owner._root_initialization
            saved = tmp_path / "saved-sessions"
            root.rename(saved)
            with pytest.raises(TranscriptWriterError, match="unavailable"):
                await owner.create_candidate(_intent(owner.scopes[1]))
            assert not root.exists() and saved.is_dir()
            fresh = CodingManagedSessionCatalogV1(session_root=root, workspace=tmp_path)
            try:
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await fresh.create_candidate(_intent(fresh.scopes[0]))
                assert not root.exists()
            finally:
                await fresh.close()
        finally:
            if active is not None:
                await active.close()
            await owner.close()

    asyncio.run(scenario())


def test_failed_initialization_keeps_sync_owner_without_reissuing_grant(tmp_path, monkeypatch):
    from loushang.harness.journal import _directory_lease as directory_module

    async def scenario():
        root = tmp_path / "new" / "sessions"
        owner = CodingManagedSessionCatalogV1(
            session_root=root, workspace=tmp_path, initialize_session_root=True,
        )
        sync = os.fsync
        identity = tmp_path.stat()

        def fail_sync(fd):
            if os.path.samestat(os.fstat(fd), identity):
                raise OSError("sync unavailable")
            return sync(fd)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(directory_module.os, "fsync", fail_sync)
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await owner.create_candidate(_intent(owner.scopes[0]))
                retained, = owner._owned_factory.pending_preparations
                assert retained.cleanup_pending and not owner._root_initialization
                assert root.parent.exists() and not root.exists()
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await owner.create_candidate(_intent(owner.scopes[0]))
                assert owner._owned_factory.pending_preparations == (retained,)
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await owner.close()
                assert not root.exists()
            await owner.close()
            assert not retained.cleanup_pending and not root.exists()
            assert root.parent.is_dir()
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_discovery_observation_revokes_grant_even_if_root_disappears_before_return(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "sessions"
        owner = CodingManagedSessionCatalogV1(
            session_root=root, workspace=tmp_path, initialize_session_root=True,
        )
        read = owner._read_discovery

        def appear_read_disappear(*args, **kwargs):
            root.mkdir(mode=0o700)
            result = read(*args, **kwargs)
            root.rename(tmp_path / "saved-sessions")
            return result

        monkeypatch.setattr(owner, "_read_discovery", appear_read_disappear)
        try:
            result = await discovery(owner, owner.scopes[0])
            assert result.complete and not result.candidates
            assert not root.exists() and not owner._root_initialization
            with pytest.raises(TranscriptWriterError, match="unavailable"):
                await owner.create_candidate(_intent(owner.scopes[0]))
            assert not root.exists()
        finally:
            await owner.close()

    asyncio.run(scenario())


async def ordinary(owner, *, metadata=None, image=False):
    scope = owner.scopes[0]
    mask = os.umask(0o077)
    try:
        manager = await SessionManager.new(
            session_dir=scope.session_dir, cwd=str(scope.cwd),
            additional_header_metadata=metadata, defer_materialization=False,
        )
        try:
            await manager.append_message(UserMessage(
                role="user", timestamp=1.0,
                content=[ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")] if image else "original",
            ))
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()
    finally:
        os.umask(mask)


async def discovery(owner, scope):
    return await owner.discover_sessions(
        HostedSessionDiscoveryScopeV1("coding", scope.scope, scope.fingerprint), stop=lambda: False,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_ordinary_history_two_views_same_identity_readonly_and_same_writer(tmp_path, reverse):
    async def scenario():
        first, second = catalog(tmp_path), catalog(tmp_path)
        path = await ordinary(first, image=True)
        original = path.read_bytes()
        header, _ = load_agent_transcript_file(path)
        expected = hashlib.sha256("\0".join((
            "coding.managed.continuity/v1", "coding", str(path.parent), header.conversation_id,
        )).encode()).hexdigest()
        scopes = first.scopes[::-1] if reverse else first.scopes
        before = tree(tmp_path)
        rows = await first.list_identities(tuple(s.discovery_scope for s in scopes), limit=256)
        assert len(rows) == 2 and rows[0].envelope == rows[1].envelope
        assert rows[0].envelope.continuity_id == expected
        assert rows[0].reference != rows[1].reference
        for scope in scopes:
            snapshot = await discovery(first, scope)
            assert snapshot.complete and len(snapshot.candidates) == 1
            assert snapshot.candidates[0].identity.scope is scope.scope
        assert tree(tmp_path) == before
        active = await first.open_candidate(rows[0].reference)
        try:
            other_rows = await second.list_identities((rows[1].scope,), limit=256)
            with pytest.raises(TranscriptWriterError, match="busy"):
                await second.open_candidate(other_rows[0].reference)
            manager = active._binding.manager_for_construction()
            assert manager.build_session_context().messages[0].content[0].data == "aGVsbG8="
            assert path.read_bytes() == original
        finally:
            await active.close()
        reopened = await second.open_candidate(other_rows[0].reference)
        try:
            await reopened._binding.manager_for_construction().append_message(
                UserMessage(role="user", content="continued", timestamp=2.0)
            )
            assert path.read_bytes().startswith(original)
        finally:
            await reopened.close()
            await first.close()
            await second.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("created_scope", [0, 1])
def test_managed_create_preserves_v1_identity_across_views_and_retry(tmp_path, created_scope):
    async def scenario():
        first = catalog(tmp_path)
        scope = first.scopes[created_scope]
        candidate = await first.create_candidate(_intent(scope))
        envelope = candidate.projection.envelope
        await candidate.close()
        await first.close()
        fresh = catalog(tmp_path)
        retry = await fresh.find_created_candidate(_intent(scope).request)
        assert retry.projection.envelope == envelope
        await retry.close()
        rows = await fresh.list_identities(tuple(s.discovery_scope for s in fresh.scopes), limit=256)
        assert len(rows) == 2 and all(row.envelope == envelope for row in rows)
        active = await fresh.open_candidate(rows[1 - created_scope].reference)
        assert active._binding.record.identity.scope is scope.scope
        await active.close()
        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1
        await fresh.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("raw", [None, {}, {"version": 2}, {"scope": "invalid"}])
def test_invalid_hosted_metadata_never_falls_back_to_ordinary(tmp_path, raw):
    async def scenario():
        owner = catalog(tmp_path)
        await ordinary(owner, metadata={"coding.hosted": raw})
        before = tree(tmp_path)
        with pytest.raises(CodingHostedCatalogError):
            await owner.list_identities((owner.scopes[1].discovery_scope,), limit=256)
        assert tree(tmp_path) == before
        await owner.close()

    asyncio.run(scenario())


def test_cross_workspace_is_visible_only_globally_and_cannot_open(tmp_path):
    async def scenario():
        source = catalog(tmp_path)
        await ordinary(source)
        other = tmp_path / "other"
        other.mkdir()
        owner = catalog(tmp_path, workspace=other)
        before = tree(tmp_path)
        cwd, home = owner.scopes
        assert not (await discovery(owner, cwd)).candidates
        snapshot = await discovery(owner, home)
        assert snapshot.candidates[0].availability is SessionAvailabilityV1.UNAVAILABLE
        rows = await owner.list_identities((home.discovery_scope,), limit=256)
        with pytest.raises(CodingHostedCatalogError):
            await owner.open_candidate(rows[0].reference)
        assert tree(tmp_path) == before and not owner._owned_factory.pending_preparations
        await owner.close()
        await source.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("hidden_workspace", [False, True])
def test_different_files_with_same_identity_are_not_deduplicated(tmp_path, hidden_workspace):
    async def scenario():
        owner = catalog(tmp_path)
        path = await ordinary(owner)
        duplicate = path.parent / ("duplicate-" + path.name)
        header, records = load_agent_transcript_file(path)
        if hidden_workspace:
            header = replace(header, metadata={**header.metadata, "cwd": "/another-workspace"})
        write_agent_transcript_export(duplicate, header, records)
        for scopes in (owner.scopes, owner.scopes[::-1], (owner.scopes[0],)):
            with pytest.raises(CodingHostedCatalogError):
                await owner.list_identities(tuple(s.discovery_scope for s in scopes), limit=256)
        await owner.close()

    asyncio.run(scenario())


def test_changed_header_after_discovery_is_rejected_without_owned_admission(tmp_path):
    async def scenario():
        owner = catalog(tmp_path)
        path = await ordinary(owner)
        rows = await owner.list_identities((owner.scopes[0].discovery_scope,), limit=256)
        header, records = load_agent_transcript_file(path)
        write_agent_transcript_export(path, replace(header, metadata={**header.metadata, "cwd": "/elsewhere"}), records)
        before = tree(tmp_path)
        with pytest.raises(CodingHostedCatalogError):
            await owner.open_candidate(rows[0].reference)
        assert tree(tmp_path) == before
        await owner.close()

    asyncio.run(scenario())


def test_unsupported_runtime_is_observed_but_not_bound(tmp_path, monkeypatch):
    async def scenario():
        owner = catalog(tmp_path)
        path = await ordinary(owner)
        from loushang.coding.product_plan import CODING_TRANSCRIPT_RUNTIME

        header, records = load_agent_transcript_file(path)
        key = CODING_TRANSCRIPT_RUNTIME.spec.metadata_key
        runtime = dict(header.metadata[key])
        runtime["productId"] = "another-product"
        write_agent_transcript_export(path, replace(header, metadata={**header.metadata, key: runtime}), records)

        async def forbidden(*args):
            raise AssertionError("unsupported catalog called runtime binder")

        monkeypatch.setattr(owner._owned_factory._lifecycle, "_bind_runtime_owned", forbidden)
        before = tree(tmp_path)
        scope = owner.scopes[1]
        snapshot = await discovery(owner, scope)
        assert snapshot.candidates[0].compatibility is SessionCompatibilityV1.UNSUPPORTED
        assert snapshot.candidates[0].availability is SessionAvailabilityV1.UNAVAILABLE
        rows = await owner.list_identities((scope.discovery_scope,), limit=256)
        with pytest.raises(CodingHostedCatalogError):
            await owner.open_candidate(rows[0].reference)
        assert tree(tmp_path) == before and not owner._owned_factory.pending_preparations
        await owner.close()

    asyncio.run(scenario())


def test_old_catalog_still_rejects_same_root_views(tmp_path):
    owner = catalog(tmp_path)
    with pytest.raises(ValueError, match="distinct Session roots"):
        CodingHostedSessionCatalogV1(owner.scopes)


def test_committed_create_lost_receipt_recovers_same_canonical_file(tmp_path, monkeypatch):
    async def scenario():
        owner = catalog(tmp_path)
        scope = owner.scopes[0]
        write = file_module._write_unlocked

        def committed_then_failed(*args, **kwargs):
            write(*args, **kwargs)
            raise OSError("managed create receipt lost")

        with monkeypatch.context() as patch:
            patch.setattr(file_module, "_write_unlocked", committed_then_failed)
            with pytest.raises(StoreCommitOutcomeUnknown):
                await owner.create_candidate(_intent(scope))
        await owner.close()
        fresh = catalog(tmp_path)
        found = await fresh.find_created_candidate(_intent(scope).request)
        assert found is not None
        envelope = found.projection.envelope
        await found.close()
        repeated = await fresh.create_candidate(_intent(scope))
        assert repeated.projection.envelope == envelope
        await repeated.close()
        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1
        await fresh.close()

    asyncio.run(scenario())


def test_post_restore_rejection_retains_original_session_on_cleanup_failure(tmp_path, monkeypatch):
    async def scenario():
        owner = catalog(tmp_path)
        await ordinary(owner)
        scope = owner.scopes[0]
        rows = await owner.list_identities((scope.discovery_scope,), limit=256)
        restore = owner._owned_factory.restore_context
        from loushang.coding import managed_catalog as module

        def unsupported(*args):
            raise ValueError("runtime changed after restore")

        async def failed_cleanup():
            raise OSError("retained original Session cleanup")

        retained = []
        with monkeypatch.context() as patch:
            async def restore_then_reject(*args):
                session = await restore(*args)
                retained.append(session)
                patch.setattr(module, "_validate_coding_restored_header", unsupported)
                patch.setattr(session, "dispose", failed_cleanup)
                return session

            patch.setattr(owner._owned_factory, "restore_context", restore_then_reject)
            with pytest.raises(CodingHostedCatalogError):
                await owner.open_candidate(rows[0].reference)
            assert owner.pending_sessions == tuple(retained)
            # Use the already-captured canonical record to test actual leases;
            # the injected new validator intentionally rejects fresh discovery.
            contender = catalog(tmp_path)
            with pytest.raises(TranscriptWriterError, match="busy"):
                await contender._owned_factory.restore_context(retained[0].context)
            await contender.close()
            with pytest.raises(OSError, match="retained original"):
                await owner.close()
            assert owner.pending_sessions == tuple(retained)
        await owner.close()
        fresh = catalog(tmp_path)
        current = await fresh.list_identities((scope.discovery_scope,), limit=256)
        opened = await fresh.open_candidate(current[0].reference)
        await opened.close()
        await fresh.close()

    asyncio.run(scenario())
