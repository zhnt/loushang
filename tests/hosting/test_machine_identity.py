from __future__ import annotations

import os
import sys

import pytest

from loushang.hosting import machine_identity as module
from loushang.hosting.errors import HostingError, HostingFailureCategory

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux OS identity")
RAW = b"0123456789abcdef0123456789abcdef"


@pytest.fixture
def identity(tmp_path, monkeypatch):
    root = tmp_path / "etc"
    root.mkdir(mode=0o755)
    path = root / "machine-id"
    path.write_bytes(RAW + b"\n")
    path.chmod(0o444)
    monkeypatch.setattr(module, "_ETC", str(root))
    monkeypatch.setattr(module, "_ROOT_UID", os.geteuid())
    return root, path


def test_stable_domain_separated_private_key(identity, monkeypatch):
    root, path = identity
    before = path.read_bytes()
    value = module.linux_machine_key(domain="loushang.managed.machine/v1")
    monkeypatch.chdir(root)
    assert module.linux_machine_key(domain="loushang.managed.machine/v1") == value
    assert module.linux_machine_key(domain="another.application/v1") != value
    assert len(value) == 32 and int(value, 16) > 0
    assert value != RAW.decode() and path.read_bytes() == before
    assert list(root.iterdir()) == [path]


@pytest.mark.parametrize("content", [b"", b"uninitialized\n", b"0" * 32, RAW.upper(), RAW + b"\n\n", RAW + b"x", b"a" * 10000])
def test_rejects_invalid_or_oversized_identity(identity, content):
    _, path = identity
    path.chmod(0o644)
    path.write_bytes(content)
    with pytest.raises(HostingError) as caught:
        module.linux_machine_key(domain="test/v1")
    assert caught.value.category == HostingFailureCategory.PREPARATION_REJECTED
    assert RAW.decode() not in str(caught.value)


@pytest.mark.parametrize("kind", ["link", "fifo", "directory", "writable_file", "writable_parent", "owner", "missing"])
def test_rejects_untrusted_native_source(identity, monkeypatch, kind):
    root, path = identity
    if kind in ("link", "fifo", "directory", "missing"):
        path.unlink()
        if kind == "link":
            target = root / "target"
            target.write_bytes(RAW)
            path.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "directory":
            path.mkdir()
    elif kind == "writable_file":
        path.chmod(0o666)
    elif kind == "writable_parent":
        root.chmod(0o777)
    else:
        monkeypatch.setattr(module, "_ROOT_UID", os.geteuid() + 1)
    with pytest.raises(HostingError):
        module.linux_machine_key(domain="test/v1")


def test_invalid_domain_and_platform_fail_before_io(monkeypatch):
    monkeypatch.setattr(module.os, "open", lambda *a, **k: pytest.fail("opened identity"))
    for domain in (None, "", "a" * 129, "secret\n", "中文"):
        with pytest.raises(HostingError) as caught:
            module.linux_machine_key(domain=domain)
        assert caught.value.category == HostingFailureCategory.INVALID_REQUEST
    monkeypatch.setattr(module.sys, "platform", "win32")
    with pytest.raises(HostingError) as caught:
        module.linux_machine_key(domain="test/v1")
    assert caught.value.category == HostingFailureCategory.PLATFORM_UNSUPPORTED


def test_short_native_reads_and_metadata_change(identity, monkeypatch):
    original_read = os.read
    _, path = identity
    changed = False

    def read(fd, size):
        nonlocal changed
        value = original_read(fd, min(size, 3))
        if not changed:
            changed = True
            path.chmod(0o600)
        return value

    monkeypatch.setattr(module.os, "read", read)
    with pytest.raises(HostingError) as caught:
        module.linux_machine_key(domain="test/v1")
    assert caught.value.category == HostingFailureCategory.PREPARATION_STALE


def test_primary_read_error_survives_both_close_errors(identity, monkeypatch):
    original = os.close
    closed = []

    def close(fd):
        closed.append(fd)
        original(fd)
        raise OSError("private close detail")

    def read(fd, size):
        raise OSError("private read detail")

    monkeypatch.setattr(module.os, "close", close)
    monkeypatch.setattr(module.os, "read", read)
    with pytest.raises(HostingError) as caught:
        module.linux_machine_key(domain="test/v1")
    assert caught.value.category == HostingFailureCategory.PREPARATION_FAILED
    assert len(set(closed)) == len(closed) == 2
    assert caught.value.__notes__ == ["machine_identity_cleanup_failed"] * 2


@pytest.mark.parametrize("outer_exception", [False, True])
def test_close_error_is_bounded_and_descriptor_not_retried(identity, monkeypatch, outer_exception):
    original = os.close
    closed = []

    def close(fd):
        closed.append(fd)
        original(fd)
        if len(closed) == 1:
            raise OSError("private native close details")

    monkeypatch.setattr(module.os, "close", close)
    def read():
        with pytest.raises(HostingError) as caught:
            module.linux_machine_key(domain="test/v1")
        return caught

    if outer_exception:
        try:
            raise ValueError("unrelated caller exception")
        except ValueError as outer:
            caught = read()
            assert not hasattr(outer, "__notes__")
    else:
        caught = read()
    assert caught.value.category == HostingFailureCategory.CLEANUP_FAILED
    assert len(closed) == len(set(closed)) == 2
    assert "private" not in str(caught.value)
