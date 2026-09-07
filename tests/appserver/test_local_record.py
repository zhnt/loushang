from __future__ import annotations

import json
import os
from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalConnectionRecordV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
    LocalRecordScopeV1,
    decode_connection_record,
    encode_connection_record,
)
from loushang.appserver.protocol import SessionScopeV1


def _scopes():
    return (LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),
            LocalRecordScopeV1(SessionScopeV1.USER_HOME, "b" * 64))


def _record():
    return LocalConnectionRecordV1(
        endpoint="workspace", application_id="application", product_id="coding",
        instance="c" * 32, port=12345, scopes=_scopes(), key=b"k" * 32,
    )


def test_G16_PRIVATE_RECORD_closed_round_trip_and_public_digest() -> None:
    record = _record()
    payload = encode_connection_record(record)
    assert decode_connection_record(payload) == record
    public = json.loads(payload)
    public.pop("key")
    canonical = json.dumps(public, sort_keys=True, separators=(",", ":")).encode()
    assert record.authentication.record_digest == sha256(canonical).digest()
    assert record.authentication.key == record.key
    assert record.key.hex() not in repr(record)
    assert record.key.decode() not in repr(record)
    for changed in (
        replace(record, port=12346), replace(record, endpoint="other"),
        replace(record, application_id="other"), replace(record, instance="d" * 32),
        replace(record, scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "e" * 64),)),
    ):
        assert changed.authentication.record_digest != record.authentication.record_digest


@pytest.mark.parametrize("field,value", [
    ("key", "k" * 64), ("key", "0" * 63), ("port", True), ("port", 0),
    ("port", 65536), ("endpoint", "../escape"), ("instance", "A" * 32),
    ("profile", "foreground-stdio/v1"), ("extra", "untrusted"),
    ("scopes", []), ("scopes", [{"scope": "global", "fingerprint": "a" * 64}]),
])
def test_G16_PRIVATE_RECORD_malformed_values_fail_without_echoing_input(field, value):
    raw = json.loads(encode_connection_record(_record()))
    raw[field] = value
    with pytest.raises(LocalRecordError) as error:
        decode_connection_record(json.dumps(raw).encode())
    assert error.value.code is LocalRecordErrorCodeV1.CORRUPT
    assert str(error.value) == "local_record_corrupt"


@pytest.mark.parametrize("payload", [
    b"x" * 8193, b"[]", b"null", b'{"key":"a","key":"b"}', b"\xff",
])
def test_G16_PRIVATE_RECORD_size_and_json_are_bounded(payload):
    with pytest.raises(LocalRecordError):
        decode_connection_record(payload)


def test_G16_PRIVATE_RECORD_publish_lock_retire_and_rotation(tmp_path) -> None:
    root = tmp_path / "runtime"
    writer = LocalConnectionDirectoryV1(root)
    reader = LocalConnectionDirectoryV1(root)
    lease = writer.acquire("workspace")
    try:
        first = lease.publish(
            application_id="application", product_id="coding", port=12345,
            scopes=_scopes(),
        )
        assert reader.read("workspace") == first
        contender = LocalConnectionDirectoryV1(root)
        try:
            with pytest.raises(LocalRecordError) as locked:
                contender.acquire("workspace")
            assert locked.value.code is LocalRecordErrorCodeV1.LOCKED
        finally:
            contender.close()
        lock_path = root / (sha256(b"workspace").hexdigest() + ".lock")
        lock_identity = os.stat(lock_path).st_ino
        lease.close()
        assert lock_path.exists() and os.stat(lock_path).st_ino == lock_identity
        with pytest.raises(LocalRecordError) as gone:
            reader.read("workspace")
        assert gone.value.code is LocalRecordErrorCodeV1.NOT_FOUND
        second_lease = writer.acquire("workspace")
        second = second_lease.publish(
            application_id="application", product_id="coding", port=12346,
            scopes=_scopes(),
        )
        assert second.instance != first.instance and second.key != first.key
        assert reader.read("workspace") == second
        second_lease.close()
    finally:
        writer.close()
        reader.close()


def test_G16_PRIVATE_RECORD_reader_does_not_create_missing_directory(tmp_path) -> None:
    root = tmp_path / "absent"
    reader = LocalConnectionDirectoryV1(root)
    try:
        with pytest.raises(LocalRecordError) as missing:
            reader.read("workspace")
        assert missing.value.code is LocalRecordErrorCodeV1.NOT_FOUND
        assert not root.exists()
    finally:
        reader.close()


@pytest.mark.parametrize("failure", ["inheritance", "identity", "write", "flush", "rename_before", "rename_after"])
def test_G16_PRIVATE_RECORD_failed_publication_retains_and_reclaims_exact_attempt(tmp_path, monkeypatch, failure):
    directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
    lease = directory.acquire("workspace")
    files = directory._files
    assert files is not None
    original_open = files._open
    temporary_descriptors = []

    def opened(name, mode):
        descriptor = original_open(name, mode)
        if mode == "new":
            temporary_descriptors.append(descriptor)
        return descriptor

    original_identity = files.identity
    original_inheritance = os.set_inheritable
    original_replace = files.replace

    def identity(descriptor):
        if descriptor in temporary_descriptors and failure == "identity":
            raise OSError("injected identity failure")
        return original_identity(descriptor)

    def inheritance(descriptor, inherited):
        if descriptor in temporary_descriptors and failure == "inheritance":
            raise OSError("injected inheritance failure")
        return original_inheritance(descriptor, inherited)

    def broken(*args):
        raise OSError("injected publication failure")

    def rename(source, target):
        if failure == "rename_before":
            broken()
        original_replace(source, target)
        if failure == "rename_after":
            broken()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(files, "_open", opened)
            patch.setattr(files, "identity", identity)
            patch.setattr(os, "set_inheritable", inheritance)
            patch.setattr(files, "replace", rename)
            if failure == "write":
                patch.setattr(os, "write", broken)
            if failure == "flush":
                patch.setattr(os, "fsync", broken)
            with pytest.raises(LocalRecordError) as error:
                lease.publish(application_id="application", product_id="coding", port=12345, scopes=_scopes())
            assert error.value.code is LocalRecordErrorCodeV1.UNAVAILABLE
        lease.close()
        assert list((tmp_path / "runtime").glob("*.tmp")) == []
        assert list((tmp_path / "runtime").glob("*.json")) == []
        assert len(list((tmp_path / "runtime").glob("*.lock"))) == 1
        for descriptor in temporary_descriptors:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        directory.close()
