from __future__ import annotations

import asyncio
import os
import stat
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
    LocalRecordScopeV1,
    encode_connection_record,
)
from loushang.appserver.protocol import SessionScopeV1


def _publish(lease):
    return lease.publish(application_id="application", product_id="coding", port=12345,
                         scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),))


def _path(root, extension="json"):
    return root / (sha256(b"workspace").hexdigest() + "." + extension)


def _private_file(directory, name, payload):
    files = directory._files
    descriptor = files.open(name, "new")
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        files.close_descriptor(descriptor)
    return directory._root / name


def _replace_held_file(source, target):
    # Windows rejects overwriting a destination that still has open handles.
    # Move that exact object aside first, then install a different object at
    # its old name. This really changes identity on every supported platform;
    # a native veto is not mistaken for a completed fault injection.
    retained = target.with_name("retained-" + target.name)
    target.rename(retained)
    os.replace(source, target)
    return retained


def test_G16_PRIVATE_RECORD_created_files_are_private_and_non_inheritable(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    original_write = os.write
    checked = []

    def before_secret_write(descriptor, data):
        assert not os.get_inheritable(descriptor)
        if os.name == "posix":
            assert stat.S_IMODE(root.stat().st_mode) == 0o700
            assert stat.S_IMODE(os.fstat(descriptor).st_mode) == 0o600
        # On Windows this validates the actual created handle's protected DACL,
        # owner, type, reparse flags and identity before any credential write.
        assert directory._files.identity(descriptor)
        checked.append(descriptor)
        return original_write(descriptor, data)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "write", before_secret_write)
            _publish(lease)
        assert checked
        assert all(not os.get_inheritable(fd) for fd in directory._files._descriptors)
        assert set(path.suffix for path in root.iterdir()) == {".lock", ".json"}
    finally:
        directory.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode admission; Windows has native DACL tests")
@pytest.mark.parametrize("target", ["root", "record", "lock"])
def test_G16_PRIVATE_RECORD_rejects_insecure_modes_without_repair(tmp_path, target):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    _publish(lease)
    path = root if target == "root" else _path(root, "json" if target == "record" else "lock")
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(original | 0o040)
    reader = LocalConnectionDirectoryV1(root)
    try:
        with pytest.raises(LocalRecordError) as error:
            if target == "lock":
                reader.acquire("workspace")
            else:
                reader.read("workspace")
        assert error.value.code is LocalRecordErrorCodeV1.UNAVAILABLE
        assert stat.S_IMODE(path.stat().st_mode) == original | 0o040
    finally:
        path.chmod(original)
        reader.close()
        directory.close()


def test_G16_PRIVATE_RECORD_hard_links_are_rejected_before_read(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    _publish(lease)
    link = root / "extra-link"
    os.link(_path(root), link)
    reader = LocalConnectionDirectoryV1(root)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "read", lambda *_: pytest.fail("read hard-linked credentials"))
            with pytest.raises(LocalRecordError) as error:
                reader.read("workspace")
        assert error.value.code is LocalRecordErrorCodeV1.UNAVAILABLE
    finally:
        link.unlink()
        reader.close()
        directory.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink admission; Windows has a junction test")
def test_G16_PRIVATE_RECORD_symlink_is_not_followed(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    record = _publish(lease)
    path = _path(root)
    retained = root / "retained"
    path.rename(retained)
    path.symlink_to(retained)
    reader = LocalConnectionDirectoryV1(root)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "read", lambda *_: pytest.fail("followed credential symlink"))
            with pytest.raises(LocalRecordError):
                reader.read("workspace")
        assert retained.read_bytes() == encode_connection_record(record)
    finally:
        path.unlink()
        retained.rename(path)
        reader.close()
        directory.close()


def test_G16_PRIVATE_RECORD_oversize_is_rejected_before_read(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    _publish(lease)
    path = _path(root)
    with path.open("r+b") as stream:
        stream.truncate(8193)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "read", lambda *_: pytest.fail("read oversize credentials"))
            with pytest.raises(LocalRecordError) as error:
                directory.read("workspace")
        assert error.value.code is LocalRecordErrorCodeV1.CORRUPT
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_retire_preserves_identical_foreign_replacement(tmp_path):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    record = _publish(lease)
    payload = encode_connection_record(record)
    foreign = _private_file(directory, "foreign", payload)
    os.replace(foreign, _path(root))
    try:
        lease.close()
        assert _path(root).read_bytes() == payload
        assert directory.read("workspace") == record
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_read_replacement_race_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    record = _publish(lease)
    foreign = _private_file(directory, "foreign", encode_connection_record(record))
    original = os.read

    def read_and_replace(descriptor, count):
        data = original(descriptor, count)
        if foreign.exists():
            _replace_held_file(foreign, _path(root))
        return data

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "read", read_and_replace)
            with pytest.raises(LocalRecordError) as error:
                directory.read("workspace")
        assert error.value.code is LocalRecordErrorCodeV1.CONFLICT
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_lock_replacement_fences_publication(tmp_path):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    foreign = _private_file(directory, "foreign", b"")
    try:
        _replace_held_file(foreign, _path(root, "lock"))
        with pytest.raises(LocalRecordError) as error:
            _publish(lease)
        assert error.value.code is LocalRecordErrorCodeV1.CONFLICT
        assert not _path(root).exists()
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_cleanup_debt_retains_lock_until_retry(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    _publish(lease)
    original = directory._files.remove

    def failed_remove(*args):
        raise OSError("injected cleanup failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(directory._files, "remove", failed_remove)
            with pytest.raises(LocalRecordError) as error:
                directory.close()
            assert error.value.code is LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE
            assert directory._leases["workspace"] is lease
            assert lease._files._locked
            contender = LocalConnectionDirectoryV1(root)
            try:
                with pytest.raises(LocalRecordError) as locked:
                    contender.acquire("workspace")
                assert locked.value.code is LocalRecordErrorCodeV1.LOCKED
            finally:
                contender.close()
        assert directory._files.remove == original
        directory.close()
        assert not _path(root).exists()
        with pytest.raises(LocalRecordError) as closed:
            directory.acquire("workspace")
        assert closed.value.code is LocalRecordErrorCodeV1.CLOSED
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_temporary_name_collision_never_adopts_foreign_file(tmp_path, monkeypatch):
    from loushang.appserver import _local_record_files

    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    foreign = _private_file(directory, "." + "a" * 32 + ".tmp", b"foreign")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(_local_record_files, "token_hex", lambda _: "a" * 32)
            with pytest.raises(LocalRecordError):
                _publish(lease)
        lease.close()
        assert foreign.read_bytes() == b"foreign"
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_uncertain_descriptor_close_is_not_retried(tmp_path, monkeypatch):
    directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
    directory.acquire("workspace")
    files = directory._files
    descriptor = files.open("probe", "new")
    original = os.close

    def uncertain_close(value):
        original(value)
        if value == descriptor:
            raise OSError("injected lost close acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(os, "close", uncertain_close)
        with pytest.raises(LocalRecordError) as uncertain:
            files.close_descriptor(descriptor)
        assert uncertain.value.code is LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE
    replacement = os.open(tmp_path / "unrelated", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        for _ in range(2):
            with pytest.raises(LocalRecordError) as debt:
                directory.close()
            assert debt.value.code is LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE
            assert directory._files is files
            assert os.fstat(replacement).st_size == 0
    finally:
        os.close(replacement)


def test_G16_PRIVATE_RECORD_native_process_crash_releases_lock_and_rotates_credentials(tmp_path):
    asyncio.run(_native_crash(tmp_path))


async def _native_crash(tmp_path):
    root = tmp_path / "runtime"
    child = """
import sys
from pathlib import Path
from loushang.appserver.local_record import LocalConnectionDirectoryV1, LocalRecordScopeV1
from loushang.appserver.protocol import SessionScopeV1
directory = LocalConnectionDirectoryV1(Path(sys.argv[1]))
lease = directory.acquire("workspace")
lease.publish(application_id="application", product_id="coding", port=12345,
              scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),))
print("ready", flush=True)
sys.stdin.read(1)
directory.close()
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-c", child, str(root), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
    )
    directory = LocalConnectionDirectoryV1(root)
    try:
        assert (await asyncio.wait_for(process.stdout.readline(), 10)).rstrip(b"\r\n") == b"ready"
        old = directory.read("workspace")
        with pytest.raises(LocalRecordError) as locked:
            directory.acquire("workspace")
        assert locked.value.code is LocalRecordErrorCodeV1.LOCKED
        # This exact spawned process handle grants termination authority, never
        # an integer found in a stale endpoint record.
        process.kill()
        await asyncio.wait_for(process.wait(), 10)
        assert process.returncode != 0
        assert directory.read("workspace") == old
        fresh = _publish(directory.acquire("workspace"))
        assert fresh.instance != old.instance and fresh.key != old.key
        assert directory.read("workspace") == fresh
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.wait_for(process.communicate(), 10)
        directory.close()
