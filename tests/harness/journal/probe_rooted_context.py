"""Lexical IO custody releases witnesses and retains retryable native debt."""

from __future__ import annotations

import asyncio
import os
import stat
import sys

import pytest

from loushang.harness.journal import _rooted_io as module
from loushang.harness.journal._rooted_io import RootedFileIO

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted IO")


@pytest.mark.parametrize("failure_type", [None, ValueError, asyncio.CancelledError])
def test_scope_releases_publication_witness_without_consuming_root(
    tmp_path, failure_type
):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    port = RootedFileIO(root, descriptor)
    failure = None if failure_type is None else failure_type("body failed")
    try:
        witness = port.retain_next_publication(root / "receipt")
        try:
            with port as borrowed:
                assert borrowed is port
                with borrowed.bind(root / "receipt") as target:
                    target.atomic_write(b"committed", exclusive=True)
                published = (root / "receipt").stat()
                assert witness.identity == (published.st_dev, published.st_ino)
                if failure is not None:
                    raise failure
        except BaseException as caught:
            assert failure is not None and caught is failure
        else:
            assert failure is None
        assert not port.cleanup_pending
        assert (root / "receipt").read_bytes() == b"committed"
        with pytest.raises(OSError, match="no retained completion witness"):
            _ = witness.identity
        assert stat.S_ISDIR(os.fstat(descriptor).st_mode)
    finally:
        port.cleanup()
        os.close(descriptor)


@pytest.mark.parametrize("cancel_body", [False, True])
def test_cleanup_failure_preserves_committed_bytes_and_retry_custody(
    tmp_path, monkeypatch, cancel_body
):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    port = RootedFileIO(root, descriptor)
    original_sync = os.fsync
    cancelled = asyncio.CancelledError("body cancelled")

    def fail_directory_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory sync failed")
        original_sync(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "fsync", fail_directory_sync)
            with pytest.raises(OSError, match="directory sync failed") as raised:
                with port:
                    with pytest.raises(OSError, match="directory sync failed"):
                        port.atomic_write(root / "value", b"committed")
                    if cancel_body:
                        raise cancelled
            if cancel_body:
                assert raised.value.__context__ is cancelled
        assert port.cleanup_pending
        assert (root / "value").read_bytes() == b"committed"
        assert stat.S_ISDIR(os.fstat(descriptor).st_mode)
        moved = tmp_path / "original-root"
        root.rename(moved)
        root.mkdir(mode=0o700)
        (root / "sentinel").write_bytes(b"unrelated")
        port.cleanup()
        assert not port.cleanup_pending
        assert (moved / "value").read_bytes() == b"committed"
        assert tuple(path.name for path in root.iterdir()) == ("sentinel",)
        assert (root / "sentinel").read_bytes() == b"unrelated"
    finally:
        port.cleanup()
        os.close(descriptor)
