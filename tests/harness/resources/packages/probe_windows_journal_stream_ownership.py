"""The native descriptor stays with Resources while a Python wrapper is built."""

from __future__ import annotations

import os
from contextlib import suppress

import pytest

from loushang.harness.resources.packages import _windows_journal_file as module


@pytest.mark.parametrize("reuse_descriptor", [False, True])
def test_wrapper_failure_preserves_original_error_and_unrelated_descriptor(
    tmp_path,
    monkeypatch,
    reuse_descriptor,
):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    descriptor = os.open(source, os.O_RDONLY)
    fdopen = os.fdopen
    other_descriptors = []
    fault = OSError("wrapper constructor failed after closing its raw IO")

    def failed_wrapper(fd, mode, *, closefd=True):
        stream = fdopen(fd, mode, closefd=closefd)
        stream.close()
        if reuse_descriptor:
            other_descriptors.append(os.open(source, os.O_RDONLY))
        raise fault

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "fdopen", failed_wrapper)
            with pytest.raises(OSError) as caught:
                with module._owned_stream(descriptor, "rb"):
                    raise AssertionError("failed wrapper cannot deliver a stream")
        assert caught.value is fault
        for other in other_descriptors:
            assert os.read(other, 8) == b"original"
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        for fd in {descriptor, *other_descriptors}:
            with suppress(OSError):
                os.close(fd)
