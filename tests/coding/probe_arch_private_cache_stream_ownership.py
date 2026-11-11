"""Real descriptor ownership; Windows opens/ACL are inert platform boundaries."""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack, suppress
from types import SimpleNamespace

import pytest

from loushang.coding import package_arch_private_cache as coding
from loushang.harness.resources.packages import _file_consumption
from loushang.harness.resources.packages.plugin_lifecycle import windows_snapshot_io

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Real POSIX FD proof; not native Windows ACL evidence",
)


@pytest.mark.parametrize("failure", ["early", "late", "late_with_reuse"])
def test_cache_wrapper_failure_keeps_original_error_and_other_fd(
    tmp_path, monkeypatch, failure
):
    destination = tmp_path / "cache.json"
    other_path = tmp_path / "other"
    other_path.write_bytes(b"unrelated")
    fdopen = os.fdopen
    owned, others, temporary = [], [], []
    fault = OSError("cache stream construction failed")

    class ACL:
        security_descriptor = 7

        def __init__(self, *, inherit_children):
            assert inherit_children is True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def validate(self, descriptor):
            os.fstat(descriptor)

    def directory(path, *, read_control):
        assert path == tmp_path and read_control is True
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        owned.append(descriptor)
        return descriptor

    def regular(parent, name, *, create_new, write, security_descriptor, read_control):
        assert create_new and write and read_control
        assert security_descriptor == 7
        descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
        )
        owned.append(descriptor)
        temporary.append(tmp_path / name)
        return descriptor

    def failed_stream(descriptor, mode, *, closefd=True):
        assert mode == "wb"
        if failure != "early":
            stream = fdopen(descriptor, mode, closefd=closefd)
            stream.close()
        if failure == "late_with_reuse":
            others.append(os.open(other_path, os.O_RDONLY))
        raise fault

    namespace = SimpleNamespace(**vars(os))
    namespace.name, namespace.fdopen = "nt", failed_stream
    try:
        with ExitStack() as stack:
            for target in (coding, windows_snapshot_io, _file_consumption):
                patch = stack.enter_context(monkeypatch.context())
                patch.setattr(target, "os", namespace)
                if target is _file_consumption:
                    continue
                if hasattr(target, "WindowsPrivateDirectoryAcl"):
                    patch.setattr(target, "WindowsPrivateDirectoryAcl", ACL)
                if hasattr(target, "open_windows_directory"):
                    patch.setattr(target, "open_windows_directory", directory)
                    patch.setattr(target, "open_windows_regular_file_at", regular)
            with pytest.raises(OSError) as caught:
                coding.write_coding_arch_private_windows_snapshot(destination, b"{}")
        assert caught.value is fault
        for descriptor in others:
            assert os.read(descriptor, 9) == b"unrelated"
        for descriptor in owned:
            with pytest.raises(OSError):
                os.fstat(descriptor)
        assert temporary and all(not path.exists() for path in temporary)
        assert not destination.exists()
    finally:
        for descriptor in set(owned + others):
            with suppress(OSError):
                os.close(descriptor)


@pytest.mark.parametrize(
    "failure",
    [
        "success",
        "parent_acl",
        "create",
        "collision",
        "file_acl",
        "write",
        "flush",
        "fsync",
        "replace",
    ],
)
def test_cache_publication_and_owned_temporary_cleanup(tmp_path, monkeypatch, failure):
    destination = tmp_path / "cache.json"
    destination.write_bytes(b"old")
    temporary = tmp_path / ".cache.json.fixture.tmp"
    owned, trace = [], []
    fault = FileExistsError("collision") if failure == "collision" else OSError(failure)
    fdopen, replace = os.fdopen, os.replace

    def check(stage):
        trace.append(stage)
        if failure == stage:
            raise fault

    class ACL:
        security_descriptor = 7

        def __init__(self, *, inherit_children):
            assert inherit_children

        def __enter__(self):
            check("acl_enter")
            return self

        def __exit__(self, *_args):
            trace.append("acl_exit")

        def validate(self, descriptor):
            os.fstat(descriptor)
            check("parent_acl" if descriptor == owned[0] else "file_acl")

    def directory(path, *, read_control):
        assert path == tmp_path and read_control
        check("parent_open")
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        owned.append(descriptor)
        return descriptor

    def regular(parent, name, *, create_new, write, security_descriptor, read_control):
        assert create_new and write and read_control and security_descriptor == 7
        assert name == temporary.name
        check("create")
        if failure == "collision":
            temporary.write_bytes(b"foreign")
            raise fault
        descriptor = os.open(
            name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=parent
        )
        owned.append(descriptor)
        return descriptor

    class Stream:
        def __init__(self, descriptor, mode, *, closefd=True):
            assert mode == "wb"
            check("stream")
            self.stream = fdopen(descriptor, mode, closefd=closefd)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            trace.append("stream_close")
            self.stream.close()

        def write(self, data):
            check("write")
            return self.stream.write(data)

        def flush(self):
            check("flush")
            self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    def fsync(descriptor):
        os.fstat(descriptor)
        check("fsync")

    def publish(source, target):
        assert source == temporary and target == destination
        # Publication starts only after the owned temporary descriptor closed.
        with pytest.raises(OSError):
            os.fstat(owned[1])
        check("replace")
        replace(source, target)

    namespace = SimpleNamespace(**vars(os))
    namespace.name, namespace.fdopen = "nt", Stream
    namespace.fsync, namespace.replace = fsync, publish
    with ExitStack() as stack:
        for target in (coding, windows_snapshot_io, _file_consumption):
            patch = stack.enter_context(monkeypatch.context())
            patch.setattr(target, "os", namespace)
            if target is _file_consumption:
                continue
            if hasattr(target, "WindowsPrivateDirectoryAcl"):
                patch.setattr(target, "WindowsPrivateDirectoryAcl", ACL)
            if hasattr(target, "open_windows_directory"):
                patch.setattr(target, "open_windows_directory", directory)
                patch.setattr(target, "open_windows_regular_file_at", regular)
            if hasattr(target, "secrets"):
                patch.setattr(target.secrets, "token_hex", lambda size: "fixture")
        if failure == "success":
            coding.write_coding_arch_private_windows_snapshot(destination, b"new")
        else:
            with pytest.raises(OSError) as caught:
                coding.write_coding_arch_private_windows_snapshot(destination, b"new")
            assert caught.value is fault
    stages = [
        "acl_enter",
        "parent_open",
        "parent_acl",
        "create",
        "file_acl",
        "stream",
        "write",
        "flush",
        "fsync",
        "replace",
    ]
    stop = (
        stages.index("create" if failure == "collision" else failure) + 1
        if failure != "success"
        else len(stages)
    )
    assert [stage for stage in trace if stage in stages] == stages[:stop]
    assert trace[-1] == "acl_exit"
    if "stream" in trace:
        assert trace.index("stream_close") > trace.index("stream")
    for descriptor in owned:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert destination.read_bytes() == (b"new" if failure == "success" else b"old")
    if failure == "collision":
        assert temporary.read_bytes() == b"foreign"
    else:
        assert not temporary.exists()
