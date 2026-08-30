from __future__ import annotations

import os
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.safe_files import (
    ContainedFileCaptureError,
    capture_contained_regular_file,
)


def test_contained_capture_is_bounded_and_returns_exact_regular_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    (root / "small.json").write_bytes(b"{}")
    (root / "large.json").write_bytes(b"x" * 17)

    captured = capture_contained_regular_file(root, "small.json", max_bytes=2)

    assert captured.body == b"{}"
    assert captured.relative_path == "small.json"
    with pytest.raises(ContainedFileCaptureError) as caught:
        capture_contained_regular_file(root, "large.json", max_bytes=16)
    assert caught.value.code == "contained_file_too_large"


def test_contained_capture_rejects_link_traversal(tmp_path: Path) -> None:
    root = tmp_path / "package"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_bytes(b"not package data")
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContainedFileCaptureError) as caught:
        capture_contained_regular_file(root, "linked/secret", max_bytes=1024)

    assert caught.value.code in {
        "contained_file_link_rejected",
        "contained_file_unreadable",
    }


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_contained_capture_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    fifo = root / "plugin.json"
    os.mkfifo(fifo)

    with pytest.raises(ContainedFileCaptureError) as caught:
        capture_contained_regular_file(root, "plugin.json", max_bytes=1024)

    assert caught.value.code == "contained_file_not_regular"
