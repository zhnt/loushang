import os

import pytest

from loushang.apphost.managed import _files
from loushang.apphost.managed._files import MAX_RECORD_BYTES, ManagedStorageError

from .test_managed_files import directory as directory
from .test_managed_files import pytestmark as pytestmark


def create(owner, content):
    snapshot = None
    with owner.lock("data.lock", create=True):
        for start in range(0, max(1, len(content)), MAX_RECORD_BYTES):
            snapshot = owner.append_data("stdout", content[start:start + MAX_RECORD_BYTES],
                                         expected=snapshot, capacity=128 * 1024)
    return snapshot


@pytest.mark.parametrize("content", [b"", b"hello", b"x" * (MAX_RECORD_BYTES * 3 + 7)])
def test_sealed_read_checks_exact_length_with_bounded_native_reads(directory, monkeypatch, content):
    _, owner = directory
    snapshot = create(owner, content)
    original = os.pread

    def bounded(fd, length, offset):
        assert length <= MAX_RECORD_BYTES
        return original(fd, length, offset)

    monkeypatch.setattr(_files.os, "pread", bounded)
    assert owner.read_data("stdout", expected=snapshot, capacity=128 * 1024, max_bytes=len(content)) == content


def test_oversize_sealed_read_fails_before_open(directory, monkeypatch):
    _, owner = directory
    snapshot = create(owner, b"hello")

    def unexpected(*args, **kwargs):
        raise AssertionError("oversize read must not open a descriptor")

    monkeypatch.setattr(owner, "_open", unexpected)
    with pytest.raises(ManagedStorageError, match="capacity"):
        owner.read_data("stdout", expected=snapshot, capacity=128 * 1024, max_bytes=4)


@pytest.mark.parametrize("replace_path", [False, True])
def test_sealed_read_rejects_mid_read_change(directory, monkeypatch, replace_path):
    root, owner = directory
    snapshot = create(owner, b"x" * (MAX_RECORD_BYTES * 2))
    original = os.pread
    changed = False

    def mutate(fd, length, offset):
        nonlocal changed
        block = original(fd, length, offset)
        # Initial snapshot reads the tail; offset zero marks the actual body read.
        if offset == 0 and not changed:
            changed = True
            if replace_path:
                os.rename(root / "stdout", root / "old-stdout")
            (root / "stdout").write_bytes(b"y" * snapshot.size)
        return block

    monkeypatch.setattr(_files.os, "pread", mutate)
    with pytest.raises(ManagedStorageError):
        owner.read_data("stdout", expected=snapshot, capacity=128 * 1024, max_bytes=snapshot.size)
    assert changed and (root / "stdout").read_bytes() == b"y" * snapshot.size
