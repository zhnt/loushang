from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.resources import _safe_files
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


def test_portable_capture_binds_distinct_path_and_descriptor_metadata_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    target = root / "small.json"
    target.write_bytes(b"{}")
    real_path_metadata = _safe_files._portable_path_metadata

    def path_metadata_with_distinct_ctime(*args, **kwargs):
        metadata = real_path_metadata(*args, **kwargs)
        return SimpleNamespace(
            st_mode=metadata.st_mode,
            st_dev=metadata.st_dev + 1,
            st_ino=metadata.st_ino + 1,
            st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns,
            st_ctime_ns=metadata.st_ctime_ns + 1,
            st_file_attributes=getattr(metadata, "st_file_attributes", 0),
        )

    monkeypatch.setattr(os, "supports_dir_fd", set())
    monkeypatch.setattr(
        _safe_files,
        "_portable_path_metadata",
        path_metadata_with_distinct_ctime,
    )

    captured = capture_contained_regular_file(root, "small.json", max_bytes=2)

    assert captured.body == b"{}"


def test_portable_capture_rejects_path_replacement_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    target = root / "small.json"
    replacement = root / "replacement.json"
    target.write_bytes(b"inside")
    replacement.write_bytes(b"outside")
    real_path_metadata = _safe_files._portable_path_metadata
    inspections = 0

    def replacing_path_metadata(*args, **kwargs):
        nonlocal inspections
        metadata = real_path_metadata(*args, **kwargs)
        inspections += 1
        if inspections == 1:
            target.unlink()
            replacement.rename(target)
        return metadata

    monkeypatch.setattr(os, "supports_dir_fd", set())
    monkeypatch.setattr(
        _safe_files,
        "_portable_path_metadata",
        replacing_path_metadata,
    )

    with pytest.raises(ContainedFileCaptureError) as caught:
        capture_contained_regular_file(root, "small.json", max_bytes=7)

    assert caught.value.code == "contained_file_path_changed_while_opening"


def test_contained_capture_rejects_link_traversal(tmp_path: Path) -> None:
    root = tmp_path / "package"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_bytes(b"not package data")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ContainedFileCaptureError) as caught:
        capture_contained_regular_file(root, "linked/secret", max_bytes=1024)

    assert caught.value.code in {
        "contained_file_link_rejected",
        "contained_file_unreadable",
    }


def test_descriptor_relative_capture_resists_ancestor_link_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("descriptor-relative no-follow capture is unavailable")
    root = tmp_path / "package"
    review = root / "skills" / "review"
    outside = tmp_path / "outside"
    review.mkdir(parents=True)
    outside.mkdir()
    (review / "actions.json").write_bytes(b"inside")
    (outside / "actions.json").write_bytes(b"outside")
    real_open = os.open
    swapped = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "actions.json" and dir_fd is not None and not swapped:
            swapped = True
            retired = root / "retired-review"
            review.rename(retired)
            try:
                review.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"directory symlinks are unavailable: {exc}")
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)
    monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, racing_open})

    captured = capture_contained_regular_file(
        root,
        "skills/review/actions.json",
        max_bytes=1024,
    )

    assert swapped is True
    assert captured.body == b"inside"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_contained_capture_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    fifo = root / "plugin.json"
    os.mkfifo(fifo)

    with pytest.raises(ContainedFileCaptureError) as caught:
        capture_contained_regular_file(root, "plugin.json", max_bytes=1024)

    assert caught.value.code == "contained_file_not_regular"
