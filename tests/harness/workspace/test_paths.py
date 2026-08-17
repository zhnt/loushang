from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_expand_user_path_and_resolve_path_from_cwd(tmp_path, monkeypatch) -> None:
    from loushang.harness.workspace.paths import expand_user_path, resolve_path_from_cwd

    monkeypatch.setenv("HOME", str(tmp_path))

    assert expand_user_path("~/notes.txt") == tmp_path / "notes.txt"
    assert expand_user_path("notes.txt") == Path("notes.txt")
    assert resolve_path_from_cwd("notes/todo.md", cwd=tmp_path) == tmp_path / "notes" / "todo.md"
    assert resolve_path_from_cwd(tmp_path / "absolute.txt", cwd="/ignored") == tmp_path / "absolute.txt"


def test_resolve_workspace_path_applies_selected_normalizers_and_variants(tmp_path) -> None:
    from loushang.harness.workspace.paths import resolve_workspace_path

    variant = tmp_path / "actual.txt"
    variant.write_text("actual", encoding="utf-8")

    resolved = resolve_workspace_path(
        "ref:missing.txt",
        cwd=tmp_path,
        normalizers=(lambda value: value.removeprefix("ref:"),),
        variant_providers=(lambda path: (variant,) if path.name == "missing.txt" else (),),
    )

    assert resolved == variant.resolve()


def test_resolve_workspace_path_prefers_selected_candidate_before_variants(tmp_path) -> None:
    from loushang.harness.workspace.paths import resolve_workspace_path

    selected = tmp_path / "selected.txt"
    selected.write_text("selected", encoding="utf-8")
    fallback = tmp_path / "fallback.txt"
    fallback.write_text("fallback", encoding="utf-8")

    resolved = resolve_workspace_path(
        selected.name,
        cwd=tmp_path,
        variant_providers=(lambda path: (fallback,),),
    )

    assert resolved == selected.resolve()


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="expected platform path variants do not exist on macOS/APFS",
)
def test_optional_user_input_helpers_find_unicode_and_platform_variants(tmp_path) -> None:
    from loushang.harness.workspace.paths import (
        normalize_unicode_spaces,
        resolve_workspace_path,
        user_input_path_variants,
    )

    screenshot = tmp_path / "Screen Shot at 9.41.37\u202fAM.png"
    screenshot.write_text("image", encoding="utf-8")
    combined = tmp_path / "Capture d\u2019e\u0301cran.txt"
    combined.write_text("text", encoding="utf-8")

    assert normalize_unicode_spaces("file\u00a0name.txt") == "file name.txt"
    assert resolve_workspace_path(
        "Screen Shot at 9.41.37 AM.png",
        cwd=tmp_path,
        variant_providers=(user_input_path_variants,),
    ) == screenshot.resolve()
    assert resolve_workspace_path(
        "Capture d'\u00e9cran.txt",
        cwd=tmp_path,
        variant_providers=(user_input_path_variants,),
    ) == combined.resolve()


def test_canonicalize_workspace_path_requires_absolute_input(tmp_path) -> None:
    from loushang.harness.workspace.paths import canonicalize_workspace_path

    target = tmp_path / "a" / ".." / "todo.md"

    assert canonicalize_workspace_path(target) == (tmp_path / "todo.md").resolve()
    with pytest.raises(ValueError, match="path must be absolute"):
        canonicalize_workspace_path(Path("relative.txt"))
