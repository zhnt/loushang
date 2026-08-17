from pathlib import Path

import pytest

from loushang.harness.tools.workspace.path_utils import (
    canonicalize_tool_path,
    expand_path,
    expandPath,
    resolve_read_path,
    resolve_to_cwd,
    resolve_tool_path,
    resolveReadPath,
    resolveToCwd,
)


def test_resolve_tool_path_uses_tool_context_cwd(tmp_path: Path) -> None:
    resolved = resolve_tool_path("notes/todo.md", cwd=str(tmp_path))
    assert resolved == (tmp_path / "notes" / "todo.md").resolve()


def test_resolve_tool_path_preserves_absolute_paths(tmp_path: Path) -> None:
    target = (tmp_path / "todo.md").resolve()
    assert resolve_tool_path(str(target), cwd="/ignored") == target


def test_resolve_tool_path_strips_at_prefix_and_expands_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert (
        resolve_tool_path("@notes/todo.md", cwd=str(tmp_path / "project"))
        == (tmp_path / "project" / "notes" / "todo.md").resolve()
    )
    assert (
        resolve_tool_path("~/notes.txt", cwd="/ignored")
        == (tmp_path / "notes.txt").resolve()
    )


def test_pi_style_path_utility_aliases_match_tool_path_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert expand_path("@file\u00a0name.txt") == "file name.txt"
    assert expandPath("~/notes.txt") == str(tmp_path / "notes.txt")
    assert resolve_to_cwd("notes/todo.md", cwd=str(tmp_path)) == (
        tmp_path / "notes" / "todo.md"
    )
    assert resolveToCwd("/tmp/example.txt", cwd=str(tmp_path)) == Path(
        "/tmp/example.txt"
    )
    assert (
        resolve_read_path("notes/todo.md", cwd=str(tmp_path))
        == (tmp_path / "notes" / "todo.md").resolve()
    )
    assert resolveReadPath("notes/todo.md", cwd=str(tmp_path)) == resolve_tool_path(
        "notes/todo.md", cwd=str(tmp_path)
    )


def test_resolve_tool_path_finds_existing_macos_screenshot_space_variant(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Screen Shot 2026-05-06 at 9.41.37\u202fAM.png"
    target.write_text("image payload", encoding="utf-8")

    resolved = resolve_tool_path(
        "Screen Shot 2026-05-06 at 9.41.37 AM.png", cwd=str(tmp_path)
    )

    assert resolved == target.resolve()


def test_resolve_tool_path_finds_existing_macos_screenshot_lowercase_am_pm_variant(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Screenshot 2026-05-06 at 9.41.37\u202fam.png"
    target.write_text("image payload", encoding="utf-8")

    resolved = resolve_tool_path(
        "Screenshot 2026-05-06 at 9.41.37 am.png", cwd=str(tmp_path)
    )

    assert resolved == target.resolve()


def test_resolve_tool_path_finds_existing_nfd_unicode_variant(tmp_path: Path) -> None:
    import os

    target = tmp_path / "file\u0065\u0301.txt"
    target.write_text("accented payload", encoding="utf-8")

    resolved = resolve_tool_path("file\u00e9.txt", cwd=str(tmp_path))

    # macOS APFS treats NFC/NFD as the same file, so string equality on the
    # normalization form is not portable; compare by file identity.
    assert os.path.samefile(resolved, target)


def test_resolve_tool_path_finds_existing_curly_quote_variant(tmp_path: Path) -> None:
    target = tmp_path / "Capture d\u2019cran.txt"
    target.write_text("quote payload", encoding="utf-8")

    resolved = resolve_tool_path("Capture d'cran.txt", cwd=str(tmp_path))

    assert resolved == target.resolve()


def test_resolve_tool_path_finds_existing_combined_nfd_and_curly_quote_variant(
    tmp_path: Path,
) -> None:
    import os

    target = tmp_path / "Capture d\u2019e\u0301cran.txt"
    target.write_text("combined payload", encoding="utf-8")

    resolved = resolve_tool_path("Capture d'\u00e9cran.txt", cwd=str(tmp_path))

    assert os.path.samefile(resolved, target)


def test_resolve_tool_path_rejects_empty_string() -> None:
    with pytest.raises(TypeError, match="path must be a non-empty string"):
        resolve_tool_path("", cwd=None)


def test_resolve_tool_path_rejects_non_string_path() -> None:
    with pytest.raises(TypeError, match="path must be a non-empty string"):
        resolve_tool_path(None, cwd=None)  # type: ignore[arg-type]


def test_canonicalize_tool_path_returns_stable_absolute_identity(
    tmp_path: Path,
) -> None:
    target = (tmp_path / "a" / ".." / "todo.md").resolve()
    assert canonicalize_tool_path(target) == str((tmp_path / "todo.md").resolve())


def test_canonicalize_tool_path_rejects_relative_paths(tmp_path: Path) -> None:
    relative = Path("a") / ".." / "todo.md"
    with pytest.raises(ValueError, match="path must be absolute"):
        canonicalize_tool_path(relative)
