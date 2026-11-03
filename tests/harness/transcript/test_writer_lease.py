from __future__ import annotations

import os
import stat
import sys

import pytest

from loushang.harness.journal import _directory_lease as module
from loushang.harness.journal import journal_file_lock
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux optional writer lease")


def lease(root, product="coding", conversation="one"):
    return TranscriptWriterLease(root, product, conversation)


def busy(root, product="coding", conversation="one"):
    owner = lease(root, product, conversation)
    try:
        with pytest.raises(TranscriptWriterError, match="busy"):
            owner.acquire()
        with pytest.raises(TranscriptWriterError, match="closed"):
            owner.acquire()
    finally:
        owner.close()


def test_identity_aliases_and_other_products_share_physical_lock(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o755)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    owner, other = lease(root), lease(root, conversation="two")
    assert not owner.cleanup_pending and not (root / ".transcript-writers").exists()
    try:
        owner.acquire()
        owner.check(product_id="coding", conversation_id="one")
        assert stat.S_IMODE(root.stat().st_mode) == 0o755
        assert all(not os.get_inheritable(fd) for fd in owner._fds.values())
        for selected, product in ((root, "coding"), (alias, "coding"), (root, "work")):
            busy(selected, product)
        other.acquire()
        with pytest.raises(TranscriptWriterError, match="conflict"):
            owner.check(product_id="work", conversation_id="one")
        # Runtime writer ownership is independent of the journal snapshot lock.
        with journal_file_lock(root / "unmodified.jsonl", "shared", blocking=False):
            assert not (root / "unmodified.jsonl").exists()
    finally:
        owner.close()
        other.close()
    stable = root / ".transcript-writers" / owner._name
    inode = stable.stat().st_ino
    reopened = lease(root)
    try:
        reopened.acquire()
        assert stable.stat().st_ino == inode and stat.S_IMODE(stable.stat().st_mode) == 0o600
        assert stat.S_IMODE(stable.parent.stat().st_mode) == 0o700
    finally:
        reopened.close()
    owner.close()
    assert not owner.cleanup_pending
    with pytest.raises(TranscriptWriterError, match="closed"):
        owner.check(product_id="coding", conversation_id="one")


@pytest.mark.parametrize("kind", ["root_mode", "directory_mode", "directory_link", "lock_mode", "lock_link", "lock_hardlink", "lock_fifo"])
def test_unsafe_files_rejected_without_repair_or_native_block(tmp_path, kind):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    owner = lease(root)
    directory = root / ".transcript-writers"
    if kind == "directory_link":
        directory.symlink_to(tmp_path, target_is_directory=True)
    else:
        directory.mkdir(mode=0o700)
    target = directory / owner._name
    if kind == "root_mode":
        root.chmod(0o777)
    elif kind == "directory_mode":
        directory.chmod(0o755)
    elif kind == "lock_mode":
        target.touch(mode=0o644)
    elif kind in {"lock_link", "lock_hardlink"}:
        source = tmp_path / "private"
        source.write_bytes(b"untouched")
        source.chmod(0o600)
        if kind == "lock_link":
            target.symlink_to(source)
        else:
            os.link(source, target)
    elif kind == "lock_fifo":
        os.mkfifo(target, 0o600)
    before = target.stat().st_mode if target.exists() else None
    try:
        with pytest.raises(TranscriptWriterError, match="unsafe|unavailable"):
            owner.acquire()
        with pytest.raises(TranscriptWriterError, match="closed"):
            owner.check(product_id="coding", conversation_id="one")
        if before is not None:
            assert target.stat().st_mode == before
    finally:
        owner.close()


@pytest.mark.parametrize("kind", ["root", "directory", "lock", "alias"])
def test_replaced_path_invalidates_retained_binding(tmp_path, kind):
    root, alternate = tmp_path / "root", tmp_path / "alternate"
    root.mkdir(mode=0o700)
    alternate.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    owner = lease(alias if kind == "alias" else root)
    try:
        owner.acquire()
        path = {"root": root, "directory": root / ".transcript-writers",
                "lock": root / ".transcript-writers" / owner._name, "alias": alias}[kind]
        path.rename(path.with_name(path.name + ".saved"))
        if kind == "alias":
            path.symlink_to(alternate, target_is_directory=True)
        elif kind == "lock":
            path.touch(mode=0o600)
        else:
            path.mkdir(mode=0o700)
        with pytest.raises(TranscriptWriterError, match="conflict"):
            owner.check(product_id="coding", conversation_id="one")
    finally:
        owner.close()


def test_unknown_close_never_closes_reused_descriptor(tmp_path, monkeypatch):
    owner = lease(tmp_path)
    owner.acquire()
    fd = owner._fds["lock"]
    original, replacement, calls = os.close, [], []

    def fail_after_close(descriptor):
        calls.append(descriptor)
        original(descriptor)
        if descriptor == fd:
            new = os.open("/dev/null", os.O_RDONLY)
            assert new == fd
            replacement.append(new)
            raise OSError("native effect completed but receipt failed")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "close", fail_after_close)
            for _ in range(2):
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    owner.close()
            assert calls.count(fd) == 1 and owner.cleanup_pending
            os.fstat(replacement[0])
        with pytest.raises(TranscriptWriterError, match="closed"):
            owner.check(product_id="coding", conversation_id="one")
    finally:
        for descriptor in replacement:
            original(descriptor)


def test_missing_root_and_non_linux_reject_without_creating_storage(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    owner = lease(missing)
    with pytest.raises(TranscriptWriterError, match="unavailable"):
        owner.acquire()
    owner.close()
    assert not missing.exists()
    other = lease(tmp_path)
    monkeypatch.setattr(module.sys, "platform", "win32")
    with pytest.raises(TranscriptWriterError, match="unsupported"):
        other.acquire()
    assert not other.cleanup_pending


def test_post_flock_validation_failure_keeps_native_ownership_until_close(tmp_path, monkeypatch):
    owner = lease(tmp_path)
    original, calls = owner._validate_binding, []

    def validate():
        calls.append(1)
        original()
        if len(calls) == 2:
            raise TranscriptWriterError("conflict")

    monkeypatch.setattr(owner, "_validate_binding", validate)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            owner.acquire()
        assert owner.cleanup_pending
        with pytest.raises(TranscriptWriterError, match="closed"):
            owner.check(product_id="coding", conversation_id="one")
        busy(tmp_path)
    finally:
        owner.close()
    fresh = lease(tmp_path)
    try:
        fresh.acquire()
    finally:
        fresh.close()
