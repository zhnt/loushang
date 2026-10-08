"""A single opt-in publication witness stays in the original root ledger."""

from __future__ import annotations

import os
import sys

import pytest

from loushang.harness.journal import _rooted_io as native

from .test_rooted_io import borrowed

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux pinned publication")


def test_publication_pin_survives_unlink_and_is_not_a_per_write_fd_leak(tmp_path):
    with borrowed(tmp_path / "root") as io:
        path = io.root / "data"
        witness = io.retain_next_publication(path)
        assert not io.cleanup_pending and not witness.operation.descriptors
        with pytest.raises(OSError, match="already registered"):
            io.retain_next_publication(path)
        io.atomic_write(path, b"original")
        fd, = witness.operation.descriptors
        identity = witness.identity
        assert (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == identity
        path.unlink()
        assert os.fstat(fd).st_nlink == 0
        for index in range(8):
            io.atomic_write(path, f"replacement-{index}".encode())
            assert witness.identity == identity
            assert tuple(witness.operation.descriptors) == (fd,)
            assert path.stat().st_ino != identity[1]
        assert os.fstat(fd).st_nlink == 0 and io.cleanup_pending
        io.cleanup()
        with pytest.raises(OSError):
            os.fstat(fd)
        with pytest.raises(OSError, match="no retained completion"):
            _ = witness.identity
        assert path.read_bytes() == b"replacement-7"


def test_normal_atomic_writes_never_retain_publication_descriptors(tmp_path):
    with borrowed(tmp_path / "root") as io:
        for _ in range(8):
            io.atomic_write(io.root / "data", b"ordinary")
            assert io._publication is None and not io.cleanup_pending


def test_failed_publication_cannot_mint_completed_identity(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        witness = io.retain_next_publication(io.root / "data")

        def refused(*args, **kwargs):
            raise OSError("test refused publication")

        with monkeypatch.context() as patch:
            patch.setattr(native.os, "replace", refused)
            with pytest.raises(OSError, match="refused publication"):
                io.atomic_write(io.root / "data", b"not published")
        assert not (io.root / "data").exists()
        fd, = witness.operation.descriptors
        assert os.fstat(fd).st_nlink == 0 and not witness.published
        with pytest.raises(OSError, match="no retained completion"):
            _ = witness.identity
        io.cleanup()


def test_publication_unknown_close_keeps_original_debt_without_reclosing_fd(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        witness = io.retain_next_publication(io.root / "data")
        io.atomic_write(io.root / "data", b"original")
        fd, = witness.operation.descriptors
        close = native.os.close
        calls = []

        def lost(value):
            assert value == fd
            calls.append(value)
            close(value)
            raise OSError("test lost actual close receipt")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(native.os, "close", lost)
                with pytest.raises(OSError, match="lost actual close"):
                    io.cleanup()
                with pytest.raises(OSError, match="cleanup outcome unknown"):
                    io.cleanup()
                assert calls == [fd] and io.cleanup_pending
                with pytest.raises(OSError, match="unsettled cleanup debt"):
                    io.read_bytes(io.root / "data")
                with pytest.raises(OSError, match="no retained completion"):
                    _ = witness.identity
        finally:
            # Only this injector observed the real close complete. It removes
            # its synthetic unknown marker; production cannot do this.
            witness.operation.descriptors.clear()
            io.cleanup()
