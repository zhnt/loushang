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


def test_portable_capture_requests_binary_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    target = root / "small.json"
    target.write_bytes(b"{\r\n}")
    binary_flag = 1 << 29
    real_open = os.open
    opened_flags: list[int] = []

    def recording_open(path, flags, mode=0o777):
        opened_flags.append(flags)
        return real_open(path, flags & ~binary_flag, mode)

    monkeypatch.setattr(os, "supports_dir_fd", set())
    monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)
    monkeypatch.setattr(os, "open", recording_open)

    captured = capture_contained_regular_file(root, "small.json", max_bytes=4)

    assert captured.body == b"{\r\n}"
    assert opened_flags
    assert all(flags & binary_flag for flags in opened_flags)


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
