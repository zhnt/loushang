from __future__ import annotations

import hashlib

import pytest

from loushang.harness.artifacts import SessionBlobRef, SessionBlobStore
from tests.harness.transcript.test_readonly_store import snapshot


def test_readonly_missing_store_never_creates_directories_and_rejects_writes(tmp_path):
    before = snapshot(tmp_path)
    reader = SessionBlobStore(tmp_path / "missing", "one", read_only=True)
    digest = hashlib.sha256(b"bytes").hexdigest()
    reference = SessionBlobRef(
        session_id="one", blob_id=digest, logical_name="output", kind="command-output",
        media_type="text/plain", disclosure="private", size_bytes=5, sha256=digest, created_at=1.0,
    )
    assert reader.records == () and reader.inspect() == ()
    for operation in (
        lambda: reader.put_bytes(b"bytes", logical_name="output", kind="command-output", media_type="text/plain"),
        lambda: reader.import_blobs(((reference, b"bytes"),)),
        reader.delete,
    ):
        with pytest.raises(ValueError, match="read-only"):
            operation()
        assert snapshot(tmp_path) == before


def test_readonly_existing_store_reuses_integrity_checks_without_locks(tmp_path):
    writer = SessionBlobStore(tmp_path, "one")
    reference = writer.put_bytes(b"hello", logical_name="output", kind="command-output", media_type="text/plain")
    # Remove only the known test lock, so accidental recreation is observable.
    lock = tmp_path / "session-assets" / ".locks" / "one.lock"
    lock.unlink()
    lock.parent.rmdir()
    before = snapshot(tmp_path)
    reader = SessionBlobStore(tmp_path, "one", read_only=True)
    assert reader.read_bytes(reference) == b"hello"
    assert reader.inspect((reference,))[0].state == "available"
    assert reader.inspect_metadata((reference,))[0].state == "available"
    assert snapshot(tmp_path) == before
    writer.objects_root.joinpath(reference.blob_id).write_bytes(b"wrong")
    corrupt = snapshot(tmp_path)
    assert reader.inspect((reference,))[0].state == "corrupt"
    assert snapshot(tmp_path) == corrupt
