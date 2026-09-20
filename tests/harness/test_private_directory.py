"""Contract tests for the shared private-directory chain primitive.

These cover the creation rule itself: mode, symlink refusal, non-directory
entries, the concurrent-creator branch and the absence of symlink following.
Callers that wrap this primitive test only their own entry contract.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from loushang.harness.private_directory import create_private_directory_chain

_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix", reason="POSIX directory permission contract"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


@_POSIX_ONLY
def test_creates_every_missing_level_private_under_group_writable_umask(
    tmp_path: Path,
) -> None:
    target = tmp_path / "one" / "two" / "three"
    previous = os.umask(0o002)
    try:
        result = create_private_directory_chain(target)
    finally:
        os.umask(previous)

    assert result == target
    for level in (tmp_path / "one", tmp_path / "one" / "two", target):
        assert level.is_dir(), level
        assert _mode(level) == 0o700, level


def test_returns_the_given_path_without_resolving_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "one" / "two"
    assert create_private_directory_chain(target) == target
    assert create_private_directory_chain(target) == target


@_POSIX_ONLY
def test_never_rewrites_an_existing_level(tmp_path: Path) -> None:
    existing = tmp_path / "shared"
    existing.mkdir()
    os.chmod(existing, 0o2775)

    create_private_directory_chain(existing / "child")

    assert _mode(existing) == 0o2775
    assert _mode(existing / "child") == 0o700


@_POSIX_ONLY
def test_rejects_directory_symlink_without_following_it(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    assert link.is_dir(), "a directory symlink satisfies is_dir(); this is the trap"

    with pytest.raises(NotADirectoryError):
        create_private_directory_chain(link / "child")

    assert not (outside / "child").exists(), "a symlink must never be followed"


@_POSIX_ONLY
def test_rejects_symlink_when_it_is_the_final_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "leaflink"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(NotADirectoryError):
        create_private_directory_chain(link)


@_POSIX_ONLY
def test_rejects_dangling_symlink(tmp_path: Path) -> None:
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "missing", target_is_directory=True)

    with pytest.raises(NotADirectoryError):
        create_private_directory_chain(link / "child")


@_POSIX_ONLY
def test_rejects_regular_file_at_any_level(tmp_path: Path) -> None:
    entry = tmp_path / "file"
    entry.write_text("occupied", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        create_private_directory_chain(entry / "child")
    with pytest.raises(NotADirectoryError):
        create_private_directory_chain(entry)

    assert entry.read_text(encoding="utf-8") == "occupied"


@_POSIX_ONLY
def test_rejects_symlink_created_by_a_concurrent_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FileExistsError branch must reclassify instead of trusting is_dir()."""

    outside = tmp_path / "outside"
    outside.mkdir()
    level = tmp_path / "raced"
    real_mkdir = os.mkdir

    def racing_mkdir(path, mode=0o777, **kwargs):
        # A concurrent creator wins the race with a symlink.
        Path(path).symlink_to(outside, target_is_directory=True)
        raise FileExistsError(17, "File exists", str(path))

    monkeypatch.setattr(os, "mkdir", racing_mkdir)
    try:
        with pytest.raises(NotADirectoryError):
            create_private_directory_chain(level)
    finally:
        monkeypatch.setattr(os, "mkdir", real_mkdir)

    assert not (outside / "child").exists()


@_POSIX_ONLY
def test_accepts_level_created_by_a_concurrent_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    level = tmp_path / "raced"
    real_mkdir = os.mkdir

    def racing_mkdir(path, mode=0o777, **kwargs):
        real_mkdir(path, 0o700)
        raise FileExistsError(17, "File exists", str(path))

    monkeypatch.setattr(os, "mkdir", racing_mkdir)
    try:
        assert create_private_directory_chain(level) == level
    finally:
        monkeypatch.setattr(os, "mkdir", real_mkdir)

    assert _mode(level) == 0o700


@_POSIX_ONLY
def test_created_level_drops_inherited_setgid_bit(tmp_path: Path) -> None:
    """mkdir copies an inherited setgid bit, which admission then rejects.

    Under a setgid parent ``mkdir(mode=0o700)`` yields ``0o2700``; a directory that
    must be exactly ``0o700`` would refuse the level this call just created.
    """

    parent = tmp_path / "storage"
    parent.mkdir()
    os.chmod(parent, 0o2775)

    target = parent / "sessions"
    create_private_directory_chain(target)

    assert _mode(target) == 0o700, "a created level must end up exactly 0o700"
    assert not stat.S_IMODE(target.lstat().st_mode) & stat.S_ISGID


def test_rejects_relative_target() -> None:
    with pytest.raises(ValueError):
        create_private_directory_chain("relative/child")


def test_expands_user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = create_private_directory_chain("~/expanded/child")
    assert result == tmp_path / "expanded" / "child"
    assert result.is_dir()
