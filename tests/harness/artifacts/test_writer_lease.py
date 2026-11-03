from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.harness.artifacts import SessionBlobStore, resolve_session_blob_data_root
from loushang.harness.artifacts._writer_lease import (
    SessionBlobWriterError,
    SessionBlobWriterLease,
)
from loushang.harness.artifacts.references import session_blob_authority_id
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux lifetime writer")


def busy(root, product, session_id):
    writer = SessionBlobWriterLease(root, product, session_id)
    try:
        with pytest.raises(SessionBlobWriterError, match="busy"):
            writer.acquire()
        with pytest.raises(SessionBlobWriterError, match="closed"):
            writer.acquire()
    finally:
        writer.close()
    assert not writer.cleanup_pending


def test_sibling_roots_products_and_normalized_aliases_share_blob_writer(tmp_path):
    roots = [tmp_path / "sessions", tmp_path / "other-sessions"]
    for root in roots:
        root.mkdir(mode=0o700)
    logical = "historical/session"
    normalized = session_blob_authority_id(logical)
    data = resolve_session_blob_data_root(roots[0])
    alias = tmp_path / "alias"
    alias.symlink_to(data, target_is_directory=True)
    writer = SessionBlobWriterLease(data, "coding", logical)
    other = SessionBlobWriterLease(data, "coding", "another")
    try:
        writer.acquire()
        writer.check(owner_id="coding", session_id=logical)
        writer.check(owner_id="coding", session_id=normalized)
        for root in (resolve_session_blob_data_root(roots[1]), alias):
            busy(root, "work", normalized)
        with pytest.raises(SessionBlobWriterError, match="conflict"):
            writer.check(owner_id="work", session_id=logical)
        other.acquire()
    finally:
        writer.close()
        other.close()
    again = SessionBlobWriterLease(data, "work", normalized)
    try:
        again.acquire()
    finally:
        again.close()


def test_different_data_roots_do_not_share_authority(tmp_path):
    leases = []
    try:
        for name in ("left", "right"):
            root = tmp_path / name
            root.mkdir(mode=0o700)
            lease = SessionBlobWriterLease(root, "coding", "same")
            leases.append(lease)
            lease.acquire()
    finally:
        for lease in leases:
            lease.close()


def test_constructor_is_pure_and_missing_data_root_is_not_created(tmp_path, monkeypatch):
    missing = tmp_path / "missing"

    def forbidden(*args, **kwargs):
        raise AssertionError("constructor performed filesystem IO")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", forbidden)
        patch.setattr(Path, "resolve", forbidden)
        writer = SessionBlobWriterLease(missing, "coding", "session")
    assert not writer.cleanup_pending and not missing.exists()
    try:
        with pytest.raises(SessionBlobWriterError, match="unavailable"):
            writer.acquire()
    finally:
        writer.close()
    assert not missing.exists() and not writer.cleanup_pending


def test_blob_operations_and_delete_do_not_remove_or_reacquire_lifetime_lock(tmp_path):
    writer = SessionBlobWriterLease(tmp_path, "coding", "session")
    try:
        writer.acquire()
        lock = tmp_path / ".session-blob-writers" / writer._name
        identity = lock.stat().st_ino
        store = SessionBlobStore(tmp_path, "session")
        reference = store.put_bytes(b"image", logical_name="one.png", kind="image", media_type="image/png")
        assert store.read_bytes(reference) == b"image"
        publication = store.import_blobs([(reference, b"image")])
        assert publication.rollback()
        assert store.delete()
        assert lock.stat().st_ino == identity
        busy(tmp_path, "work", "session")
    finally:
        writer.close()


@pytest.mark.parametrize("replacement", ["root", "directory", "lock"])
def test_blob_lease_rejects_replaced_binding(tmp_path, replacement):
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    writer = SessionBlobWriterLease(root, "coding", "session")
    try:
        writer.acquire()
        selected = {"root": root, "directory": root / ".session-blob-writers",
                    "lock": root / ".session-blob-writers" / writer._name}[replacement]
        selected.rename(selected.with_name(selected.name + ".saved"))
        if replacement == "lock":
            selected.touch(mode=0o600)
        else:
            selected.mkdir(mode=0o700)
        with pytest.raises(SessionBlobWriterError, match="conflict|unavailable"):
            writer.check(owner_id="coding", session_id="session")
    finally:
        writer.close()


def test_extracted_transcript_lease_conflicts_with_original_hash_lock(tmp_path):
    import fcntl

    directory = tmp_path / ".transcript-writers"
    directory.mkdir(mode=0o700)
    name = hashlib.sha256(json.dumps(["transcript-writer/v1", "one"], ensure_ascii=True).encode()).hexdigest() + ".lock"
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)
    writer = TranscriptWriterLease(tmp_path, "coding", "one")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert writer._name == name
        with pytest.raises(TranscriptWriterError, match="transcript_writer:busy"):
            writer.acquire()
    finally:
        writer.close()
        os.close(fd)


def test_independent_process_contends_for_normalized_blob_authority(tmp_path):
    script = """
import sys
from pathlib import Path
from loushang.harness.artifacts._writer_lease import SessionBlobWriterLease, SessionBlobWriterError
writer = SessionBlobWriterLease(Path(sys.argv[1]), 'work', sys.argv[2])
try:
    try:
        writer.acquire()
    except SessionBlobWriterError as error:
        print(error.code)
    else:
        print('held')
finally:
    writer.close()
"""
    logical = "historical/session"
    writer = SessionBlobWriterLease(tmp_path, "coding", logical)

    def probe():
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), session_blob_authority_id(logical)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0 and not result.stderr
        return result.stdout.strip()

    try:
        writer.acquire()
        assert probe() == "busy"
    finally:
        writer.close()
    assert probe() == "held"
