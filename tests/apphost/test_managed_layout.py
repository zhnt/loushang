from __future__ import annotations

import os
import stat
import subprocess
import sys
from time import monotonic

import pytest

from loushang.apphost.managed import _files as native
from loushang.apphost.managed import layout
from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.apphost.managed.contracts import (
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.layout import ManagedLayoutPreparationV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed initialization")


def preparation(root, **kwargs):
    namespace = ManagedNamespaceV1(str(root / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(root))
    instance = ManagedInstanceRefV1(namespace.namespace_key, service.service_id, "b" * 32)
    return ManagedLayoutPreparationV1(namespace, service, instance, runtime_root=str(root / "runtime"), **kwargs)


@pytest.mark.parametrize("mask", [0o002, 0o022, 0o077])
def test_fresh_layout_is_pure_until_open_and_creates_private_ancestors(tmp_path, mask):
    owner = preparation(tmp_path)
    assert not tuple(tmp_path.iterdir())
    assert len(owner._directories) == 9 and not owner.initialized
    old_mask = os.umask(mask)
    try:
        owner.open(deadline=monotonic() + 5)
        assert owner.initialized
        assert not (tmp_path / "platform/data/sessions").exists()
        before = {path: (path.stat().st_ino, stat.S_IMODE(path.stat().st_mode)) for path in tmp_path.rglob("*")}
        assert before and all(mode == 0o700 for _, mode in before.values())
    finally:
        os.umask(old_mask)
        owner.close()
    assert not owner.cleanup_pending and not owner.initialized
    assert {path: (path.stat().st_ino, stat.S_IMODE(path.stat().st_mode)) for path in before} == before


def test_parent_creation_is_explicit_and_existing_permissions_are_not_changed(tmp_path):
    root = tmp_path / "ancestor" / "leaf"
    with pytest.raises(ManagedStorageError):
        PrivateManagedDirectory(root, create=True)
    assert not root.parent.exists()
    with pytest.raises(ManagedStorageError):
        PrivateManagedDirectory(root, create_parents=True)
    assert not root.parent.exists()
    root.parent.mkdir(mode=0o755)
    root.parent.chmod(0o755)
    before = root.parent.stat()
    owner = PrivateManagedDirectory(root, create=True, create_parents=True)
    owner.close()
    assert root.parent.stat().st_mode == before.st_mode
    assert root.parent.stat().st_ino == before.st_ino


@pytest.mark.parametrize("kind", ["symlink", "file", "writable"])
def test_bad_parent_never_creates_descendants(tmp_path, kind):
    parent = tmp_path / "bad"
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    if kind == "symlink":
        parent.symlink_to(outside, target_is_directory=True)
    elif kind == "file":
        parent.write_bytes(b"unchanged")
    else:
        parent.mkdir(mode=0o700)
        parent.chmod(0o777)
    owner = PrivateManagedDirectory(parent / "more/leaf", create=True, create_parents=True, defer_open=True)
    try:
        with pytest.raises(ManagedStorageError):
            owner.open()
    finally:
        owner.close()
    assert not tuple(outside.iterdir())
    if kind == "writable":
        assert parent.stat().st_mode & 0o777 == 0o777
        assert not tuple(parent.iterdir())


def test_mkdir_sync_debt_retains_original_parent_and_new_owner_syncs_eexist(tmp_path, monkeypatch):
    target = tmp_path / "first" / "second" / "leaf"
    owner = PrivateManagedDirectory(target, create=True, create_parents=True, defer_open=True)
    fsync = native.os.fsync
    parent_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    synced = []

    def observe(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == parent_identity:
            synced.append(fd)
        return fsync(fd)

    def fail(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == parent_identity and target.parents[1].exists():
            raise OSError("parent sync unavailable")
        return fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "fsync", fail)
        with pytest.raises(ManagedStorageError):
            owner.open()
        retained, = owner._sync_pending
        assert owner.cleanup_pending and os.fstat(retained).st_ino == parent_identity[1]
        with pytest.raises(ManagedStorageError):
            owner.close()
        assert owner._sync_pending == {retained}
    with monkeypatch.context() as patch:
        patch.setattr(native.os, "fsync", observe)
        other = PrivateManagedDirectory(target, create=True, create_parents=True)
        assert synced, "EEXIST did not bypass the parent's durability check"
        other.close()
        synced.clear()
        owner.close()
        assert synced == [retained]
    assert not owner.cleanup_pending and target.is_dir()


def test_layout_partial_failure_closes_all_original_owners_and_retries_only_debt(tmp_path, monkeypatch):
    owner = preparation(tmp_path)
    directories = owner._directories
    open_third, close_first = directories[2].open, directories[0].close
    calls = []

    def fail_open(**kwargs):
        raise ManagedStorageError("unavailable")

    def fail_close():
        calls.append("failed")
        raise ManagedStorageError("unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(directories[2], "open", fail_open)
        with pytest.raises(ManagedStorageError):
            owner.open(deadline=monotonic() + 5)
        assert not owner.initialized and owner._directories == directories
        patch.setattr(directories[0], "close", fail_close)
        with pytest.raises(ManagedStorageError):
            owner.close()
        assert owner._closed == set(range(1, 9)) and owner.cleanup_pending
    assert directories[2].open == open_third and directories[0].close == close_first
    owner.close()
    assert not owner.cleanup_pending and calls == ["failed"]
    with pytest.raises(ManagedStorageError, match="closed"):
        owner.open(deadline=monotonic() + 5)


def test_layout_capacity_and_expired_deadline_do_no_native_io(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight performed IO")

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "open", forbidden)
        with pytest.raises(ManagedStorageError, match="capacity"):
            preparation(tmp_path.joinpath(*(["deep"] * 64)))
        owner = preparation(tmp_path)
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.open(deadline=monotonic() - 1)
        owner.close()
    assert not tuple(tmp_path.iterdir())


def test_layout_deadline_expiring_during_final_check_cannot_report_initialized(tmp_path, monkeypatch):
    owner = preparation(tmp_path)
    clock = [100.0]
    final = owner._directories[-1]
    original_check = final._check
    checks = 0

    def expire_on_layout_check():
        nonlocal checks
        result = original_check()
        checks += 1
        # Two checks in the leaf open, then the final layout-wide check.
        if checks == 3:
            clock[0] = 102.0
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(native, "monotonic", lambda: clock[0])
            patch.setattr(layout, "monotonic", lambda: clock[0])
            patch.setattr(final, "_check", expire_on_layout_check)
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.open(deadline=101.0)
        assert checks == 3 and not owner.initialized
    finally:
        owner.close()


@pytest.mark.parametrize("replace_leaf", [False, True])
def test_entry_replacement_during_parent_sync_is_rejected(tmp_path, monkeypatch, replace_leaf):
    target = tmp_path / "ancestor" / "leaf"
    entry = target if replace_leaf else target.parent
    displaced = tmp_path / "displaced"
    owner = PrivateManagedDirectory(target, create=True, create_parents=True, defer_open=True)
    original_sync = os.fsync
    replaced = False

    def replace_during_sync(fd):
        nonlocal replaced
        if not replaced and entry.exists() and os.fstat(fd).st_ino == entry.parent.stat().st_ino:
            entry.rename(displaced)
            entry.mkdir(mode=0o700)
            replaced = True
        return original_sync(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(native.os, "fsync", replace_during_sync)
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.open()
        assert replaced and not owner._opened
        assert not tuple(entry.iterdir())
    finally:
        owner.close()
    assert displaced.is_dir() and entry.is_dir()


def test_deadline_after_mkdir_retains_sync_debt_without_creating_descendants(tmp_path, monkeypatch):
    target = tmp_path / "first" / "leaf"
    owner = PrivateManagedDirectory(target, create=True, create_parents=True, defer_open=True)
    clock = [100.0]
    original_mkdir = os.mkdir

    def expire_after_mkdir(name, mode=0o777, *, dir_fd=None):
        result = original_mkdir(name, mode=mode, dir_fd=dir_fd)
        if name == "first":
            clock[0] = 102.0
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(native, "monotonic", lambda: clock[0])
            patch.setattr(native.os, "mkdir", expire_after_mkdir)
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.open(deadline=101.0)
        retained, = owner._sync_pending
        assert os.fstat(retained).st_ino == tmp_path.stat().st_ino
        assert target.parent.is_dir() and not target.exists()
    finally:
        owner.close()
    assert not owner.cleanup_pending and target.parent.is_dir()


def test_interrupted_close_retains_unknown_fd_and_closes_other_originals(tmp_path, monkeypatch):
    owner = PrivateManagedDirectory(tmp_path / "leaf", create=True, create_parents=True)
    original_fds = {owner._anchor, owner._fd, *(item[2] for item in owner._parents)}
    original_close = os.close
    attempted = []
    replacement = None

    def close_then_interrupt(fd):
        nonlocal replacement
        attempted.append(fd)
        original_close(fd)
        if replacement is None:
            replacement = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
            assert replacement == fd, "fault must reproduce actual fd reuse"
            raise KeyboardInterrupt("close receipt interrupted")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(native.os, "close", close_then_interrupt)
            with pytest.raises(KeyboardInterrupt):
                owner.close()
            assert set(attempted) == original_fds
            assert owner._close_pending == owner._uncertain_closes == {replacement}
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
            assert len(attempted) == len(original_fds)
            assert os.fstat(replacement).st_ino == tmp_path.stat().st_ino
        for fd in original_fds - {replacement}:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        # Only the injector knows the replacement's receipt; production must
        # never retry the unknown numeric descriptor.
        if replacement is not None:
            original_close(replacement)


def test_layout_interrupt_does_not_skip_independent_directory_cleanup(tmp_path, monkeypatch):
    owner = preparation(tmp_path)
    owner.open(deadline=monotonic() + 5)

    def interrupt():
        raise KeyboardInterrupt("injected close interruption")

    with monkeypatch.context() as patch:
        patch.setattr(owner._directories[0], "close", interrupt)
        with pytest.raises(KeyboardInterrupt):
            owner.close()
        assert owner._closed == set(range(1, 9))
    owner.close()
    assert not owner.cleanup_pending


def test_two_native_processes_initialize_the_same_fixed_layout(tmp_path):
    script = """
import os, sys
from pathlib import Path
from time import monotonic
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1, ManagedInstanceRefV1
from loushang.apphost.managed.layout import ManagedLayoutPreparationV1
root = Path(sys.argv[1])
ns = ManagedNamespaceV1(str(root / 'platform'), os.geteuid(), 'a' * 32)
service = ManagedServiceKeyV1('coding', str(root))
instance = ManagedInstanceRefV1(ns.namespace_key, service.service_id, 'b' * 32)
owner = ManagedLayoutPreparationV1(ns, service, instance, runtime_root=str(root / 'runtime'))
try:
    sys.stdin.buffer.read(1)
    owner.open(deadline=monotonic() + 10)
    print(Path(owner.paths.registry).stat().st_ino)
finally:
    owner.close()
"""
    children = [subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) for _ in range(2)]
    try:
        for child in children:
            child.stdin.write(b"G")
            child.stdin.flush()
        outputs = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), outputs
        assert outputs[0][0] == outputs[1][0] and outputs[0][0].strip().isdigit()
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.communicate(timeout=5)
