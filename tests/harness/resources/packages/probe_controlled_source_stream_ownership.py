"""Source readers retain native FD ownership through Python wrapper failures."""

from __future__ import annotations

import os
from contextlib import suppress
from hashlib import sha256

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    _controlled_source_io as module,
)


@pytest.mark.parametrize("failure", ["early", "late", "late_with_other_fd"])
def test_wrapper_failure_closes_owned_fd_and_preserves_other_fd(
    tmp_path, monkeypatch, failure
):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    descriptor = os.open(source, os.O_RDONLY)
    fdopen = os.fdopen
    others = []
    fault = OSError("injected wrapper construction failure")

    def failed_wrapper(fd, mode, *, closefd=True):
        if failure != "early":
            stream = fdopen(fd, mode, closefd=closefd)
            stream.close()
        if failure == "late_with_other_fd":
            others.append(os.open(source, os.O_RDONLY))
        raise fault

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "open_regular_no_follow", lambda _: descriptor)
            patch.setattr(module.os, "fdopen", failed_wrapper)
            with pytest.raises(OSError) as caught:
                module.read_controlled_source(
                    source,
                    digest=sha256(b"original").hexdigest(),
                    max_bytes=64,
                    label="Source",
                    error_factory=ValueError,
                )
        assert caught.value is fault
        for other in others:
            assert os.read(other, 8) == b"original"
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        for fd in {descriptor, *others}:
            with suppress(OSError):
                os.close(fd)
