"""Owned cache publication reuses the existing index format and root ledger."""

import asyncio
import json
import os
import select
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.harness.conversation import (
    ConversationKey,
    ConversationLocator,
    FunctionalProjectionCodec,
    IndexedProjection,
    JsonConversationIndex,
)

from ..journal.test_rooted_io import borrowed

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted cache")


def index_for(path):
    return JsonConversationIndex(
        path, version=1,
        codec=FunctionalProjectionCodec(encoder=lambda value: {"value": value},
                                        decoder=lambda data: data["value"]),
        query_items=lambda _query, items: tuple(items),
    )


def item(revision, value):
    return IndexedProjection(ConversationLocator("local", ConversationKey("root", "one")), revision, value)


def test_rooted_upsert_preserves_format_revision_and_tombstones(tmp_path):
    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        asyncio.run(index.upsert(item(1, "first")))
        assert stat.S_IMODE(index.path.stat().st_mode) == 0o600
        with io.bind(index.path) as target:
            assert index.upsert_rooted(item(2, "latest"), target)
        assert asyncio.run(index.get(item(2, "latest").locator)) == item(2, "latest")
        with io.bind(index.path) as target:
            assert not index.upsert_rooted(item(1, "stale"), target)
        asyncio.run(index.delete(item(2, "latest").locator, through_revision=2))
        assert stat.S_IMODE(index.path.stat().st_mode) == 0o600
        with io.bind(index.path) as target:
            assert not index.upsert_rooted(item(2, "latest"), target)


@pytest.mark.parametrize("content", [None, b"{corrupt"])
def test_rooted_upsert_does_not_create_or_repair_cache(tmp_path, content):
    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        if content is not None:
            index.path.write_bytes(content)
            index.path.chmod(0o600)
        with io.bind(index.path) as target:
            assert not index.upsert_rooted(item(1, "first"), target)
        if content is None:
            assert not index.path.exists()
        else:
            assert index.path.read_bytes() == content
        assert not list(io.root.glob("*.corrupt-*"))


def test_rooted_upsert_rejects_group_writable_cache_without_modifying_it(tmp_path):
    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        index.path.write_bytes(b"unsafe cache")
        index.path.chmod(0o660)
        with io.bind(index.path) as target:
            with pytest.raises(OSError, match="owned single-link"):
                index.upsert_rooted(item(1, "first"), target)
        assert index.path.read_bytes() == b"unsafe cache"
        assert not (io.root / "index.json.lock").exists()


def test_index_creation_does_not_follow_predictable_temporary_symlink(tmp_path):
    index = index_for(tmp_path / "index.json")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"must stay unchanged")
    legacy_temp = index.path.with_suffix(".json.tmp")
    legacy_temp.symlink_to(unrelated)

    asyncio.run(index.upsert(item(1, "first")))

    assert unrelated.read_bytes() == b"must stay unchanged"
    assert legacy_temp.is_symlink()
    assert stat.S_IMODE(index.path.stat().st_mode) == 0o600
    assert asyncio.run(index.get(item(1, "first").locator)) == item(1, "first")


def test_index_failed_publication_preserves_cache_and_cleans_own_temp(tmp_path, monkeypatch):
    index = index_for(tmp_path / "index.json")
    asyncio.run(index.upsert(item(1, "first")))
    before = index.path.read_bytes()
    unrelated = tmp_path / "index.json.tmp"
    unrelated.write_bytes(b"not ours")

    def fail_replace(source, target, *, src_dir_fd=None, dst_dir_fd=None):
        assert target == index.path.name
        assert source != unrelated.name
        assert src_dir_fd == dst_dir_fd and src_dir_fd is not None
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected publication failure"):
        asyncio.run(index.upsert(item(2, "latest")))
    assert index.path.read_bytes() == before
    assert unrelated.read_bytes() == b"not ours"
    assert not list(tmp_path.glob(".index.json.*.tmp"))


@pytest.mark.parametrize("operation", ["upsert", "delete", "replace"])
def test_legacy_mutations_respect_owned_index_transaction(tmp_path, operation):
    from loushang.harness.journal.jsonl import JournalLockUnavailable

    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        original = item(1, "first")
        asyncio.run(index.upsert(original))
        before = index.path.read_bytes()

        def mutate():
            if operation == "upsert":
                return asyncio.run(index.upsert(item(2, "latest")))
            if operation == "delete":
                return asyncio.run(index.delete(original.locator, through_revision=2))
            return asyncio.run(index.replace((item(2, "latest"),)))

        with io.bind(index.path) as target:
            target.acquire_lock(exclusive=True, blocking=False, suffix=".lock")
            with pytest.raises(JournalLockUnavailable):
                mutate()
            assert index.path.read_bytes() == before
        mutate()


def test_owned_mutation_respects_legacy_transaction(tmp_path):
    from loushang.harness.journal.jsonl import journal_file_lock

    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        asyncio.run(index.upsert(item(1, "first")))
        before = index.path.read_bytes()
        with journal_file_lock(index.path, "exclusive", blocking=False):
            with io.bind(index.path) as target:
                with pytest.raises(BlockingIOError):
                    index.upsert_rooted(item(2, "latest"), target)
            assert index.path.read_bytes() == before
        with io.bind(index.path) as target:
            assert index.upsert_rooted(item(2, "latest"), target)


@pytest.mark.parametrize("operation", ["upsert", "delete", "replace"])
def test_readonly_mutation_rejects_before_creating_lock_or_parent(tmp_path, operation):
    index = index_for(tmp_path / "absent" / "index.json")
    readonly = JsonConversationIndex(
        index.path, version=1, codec=index.codec,
        query_items=lambda _query, items: tuple(items), writable=False,
    )
    original = item(1, "first")
    with pytest.raises(RuntimeError, match="read-only"):
        if operation == "upsert":
            asyncio.run(readonly.upsert(original))
        elif operation == "delete":
            asyncio.run(readonly.delete(original.locator, through_revision=1))
        else:
            asyncio.run(readonly.replace((original,)))
    assert not index.path.parent.exists()


def test_corrupt_index_read_does_not_quarantine_under_owned_writer(tmp_path):
    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        index.path.write_bytes(b"{corrupt")
        index.path.chmod(0o600)
        with io.bind(index.path) as target:
            target.acquire_lock(exclusive=True, blocking=False, suffix=".lock")
            assert asyncio.run(index.get(item(1, "first").locator)) is None
            assert asyncio.run(index.query_snapshot(None)).index_state == "stale"
            assert index.path.read_bytes() == b"{corrupt"
            assert not list(io.root.glob("*.corrupt-*"))
        # Explicit mutation, not read, still preserves the damaged cache.
        asyncio.run(index.upsert(item(1, "first")))
        assert len(list(io.root.glob("*.corrupt-*"))) == 1


def test_independent_process_respects_rooted_transaction_and_preserves_both_items(tmp_path):
    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        asyncio.run(index.upsert(item(1, "first")))
        child = None
        try:
            with io.bind(index.path) as target:
                assert index.upsert_rooted(item(2, "latest"), target)
                child = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name("_index_child.py")), str(index.path)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                assert select.select([child.stdout], [], [], 15)[0], "child did not report lock contention"
                assert child.stdout.readline() == b"busy\n"
                assert asyncio.run(index.get(item(2, "latest").locator)) == item(2, "latest")
            output, errors = child.communicate(b"continue\n", timeout=15)
            assert child.returncode == 0, errors.decode(errors="replace")
            assert output == b"published\n"
            assert not errors
            rows = asyncio.run(index.query(None))
            assert {row.locator.key.conversation_id: row.projection for row in rows} == {
                "one": "latest", "two": "second",
            }
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)


def test_publication_receipt_invalidates_only_its_exact_version(tmp_path):
    index = index_for(tmp_path / "index.json")
    rows, receipt = asyncio.run(index.replace_with_receipt((item(1, "first"),)))
    assert rows == (item(1, "first"),)
    assert asyncio.run(index.invalidate_if_current(receipt))
    assert not index.path.exists()
    assert not asyncio.run(index.invalidate_if_current(receipt))


@pytest.mark.parametrize("successor", ["upsert", "replace", "rooted", "physical_copy"])
def test_publication_receipt_cannot_delete_a_successor(tmp_path, successor):
    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        _, receipt = asyncio.run(index.replace_with_receipt((item(1, "first"),)))
        if successor == "upsert":
            asyncio.run(index.upsert(item(2, "newer")))
        elif successor == "replace":
            asyncio.run(index.replace((item(2, "newer"),)))
        elif successor == "rooted":
            with io.bind(index.path) as target:
                assert index.upsert_rooted(item(2, "newer"), target)
        else:
            original = index.path.with_name("retained-old-index")
            index.path.rename(original)
            index.path.write_bytes(original.read_bytes())
            index.path.chmod(0o600)
        before = index.path.read_bytes()
        assert not asyncio.run(index.invalidate_if_current(receipt))
        assert index.path.read_bytes() == before


def test_publication_invalidation_reports_busy_without_touching_cache(tmp_path):
    from loushang.harness.journal.jsonl import JournalLockUnavailable

    with borrowed(tmp_path / "root") as io:
        index = index_for(io.root / "index.json")
        _, receipt = asyncio.run(index.replace_with_receipt((item(1, "first"),)))
        before = index.path.read_bytes()
        with io.bind(index.path) as target:
            target.acquire_lock(exclusive=True, blocking=False, suffix=".lock")
            with pytest.raises(JournalLockUnavailable):
                asyncio.run(index.invalidate_if_current(receipt))
            assert index.path.read_bytes() == before


def test_invalidation_rechecks_same_open_file_after_in_place_version_change(tmp_path, monkeypatch):
    index = index_for(tmp_path / "index.json")
    _, receipt = asyncio.run(index.replace_with_receipt((item(1, "first"),)))
    original = index._decode_state
    successor = json.loads(index.path.read_bytes())
    successor["index_generation"] = "independent-successor"
    encoded = json.dumps(successor).encode()

    def decode_then_change(content, **kwargs):
        state = original(content, **kwargs)
        # Deliberately bypass the cooperative lock to exercise the final
        # descriptor/status check, preserving this exact inode.
        index.path.write_bytes(encoded)
        assert (index.path.stat().st_dev, index.path.stat().st_ino) == receipt.identity
        return state

    monkeypatch.setattr(index, "_decode_state", decode_then_change)
    assert not asyncio.run(index.invalidate_if_current(receipt))
    assert index.path.read_bytes() == encoded


def test_old_receipt_cannot_delete_original_inode_moved_into_replacement_parent(tmp_path):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    index = index_for(root / "index.json")
    _, receipt = asyncio.run(index.replace_with_receipt((item(1, "first"),)))
    moved = tmp_path / "retained-root"
    root.rename(moved)
    root.mkdir(mode=0o700)
    (moved / "index.json").rename(index.path)
    (root / "index.json.lock").touch(mode=0o600)
    before = index.path.read_bytes()
    assert not asyncio.run(index.invalidate_if_current(receipt))
    assert index.path.read_bytes() == before


def test_publication_keeps_original_parent_if_path_changes_after_read(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    index = index_for(root / "index.json")
    asyncio.run(index.upsert(item(1, "first")))
    original = index._read_state
    moved = tmp_path / "retained-root"

    def read_then_replace_parent(**kwargs):
        state = original(**kwargs)
        root.rename(moved)
        root.mkdir(mode=0o700)
        index.path.write_bytes(b"replacement remains untouched")
        index.path.chmod(0o600)
        return state

    monkeypatch.setattr(index, "_read_state", read_then_replace_parent)
    _, receipt = asyncio.run(index.replace_with_receipt((item(2, "latest"),)))
    assert receipt.parent_identity == (moved.stat().st_dev, moved.stat().st_ino)
    assert index.path.read_bytes() == b"replacement remains untouched"
    assert {path.name for path in root.iterdir()} == {"index.json"}
    assert asyncio.run(index_for(moved / "index.json").get(item(2, "latest").locator)) == item(2, "latest")
