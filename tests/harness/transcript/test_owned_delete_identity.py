"""The original file-specific delete cannot retire an inode replacement."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.journal import _rooted_io as native

from .test_runtime_profile import _runtime
from .test_writer_runtime import prepare

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted delete")


@pytest.mark.parametrize("prior_retirement", [False, True])
@pytest.mark.parametrize("replace_during_sync", [False, True])
def test_delete_keeps_frozen_inode_through_retirement_sync(
    tmp_path, monkeypatch, prior_retirement, replace_during_sync,
):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        path = tmp_path / "session.jsonl"
        saved = tmp_path / "original-held"
        original = path.read_bytes()
        status = path.stat()
        identity = (status.st_dev, status.st_ino)
        identities = tmp_path / ".conversation-identities"
        identities.mkdir(mode=0o700)
        parent = identities.stat()
        tombstone = store._tombstone_for(key, path)
        if prior_retirement:
            tombstone.write_text(
                '{"revision":0,"deleted_at":"2026-09-13T00:00:00+00:00","operation_id":"abort"}',
                encoding="utf-8",
            )
            tombstone.chmod(0o600)
        sync = native.os.fsync
        replaced = []

        def fsync(fd):
            current = os.fstat(fd)
            if (replace_during_sync and not replaced and tombstone.exists()
                    and (current.st_dev, current.st_ino) == (parent.st_dev, parent.st_ino)):
                path.rename(saved)
                path.write_bytes(original)  # Same key and revision is not authority.
                path.chmod(0o600)
                replaced.append(path.stat().st_ino)
                assert replaced[0] != identity[1]
            return sync(fd)

        async def delete():
            return await store.delete(
                key, expected_revision=0, operation_id="abort", expected_file_identity=identity,
            )

        try:
            with monkeypatch.context() as patch:
                patch.setattr(native.os, "fsync", fsync)
                if replace_during_sync:
                    with pytest.raises(StoreCommitOutcomeUnknown):
                        await delete()
                    assert replaced and path.stat().st_ino == replaced[0]
                    assert path.read_bytes() == original
                    # Reconciliation is the same original op and must still
                    # reject the replacement; it cannot authorize a new inode.
                    with pytest.raises(StoreCommitOutcomeUnknown):
                        await delete()
                    assert path.stat().st_ino == replaced[0]
                else:
                    receipt = await delete()
                    assert receipt.operation_id == "abort" and receipt.revision == 0
                    assert not path.exists()
                    assert await delete() == receipt
            if replace_during_sync:
                # Test-only restoration of the retained original inode lets
                # the exact original operation settle without touching the
                # foreign replacement (which is kept under another name).
                path.rename(tmp_path / "foreign-kept")
                saved.rename(path)
                receipt = await delete()
                assert receipt.operation_id == "abort"
                assert not path.exists()
                assert (tmp_path / "foreign-kept").stat().st_ino == replaced[0]
                assert await delete() == receipt
        finally:
            await owner.dispose()

    asyncio.run(scenario())
