from __future__ import annotations

import ast
import inspect
import runpy
import shutil
from pathlib import Path
from typing import Any

import pytest

from loushang.tui import (
    CursorDeclaration,
    DirectoryTree,
    DirectoryTreeEntry,
    DirectoryTreeEntryKind,
    DirectoryTreeRealKind,
    DirectoryTreeSelect,
    InputEvent,
    PathFilter,
    PathSortKey,
    RenderConstraints,
    ThemeResolver,
    strip_control_sequences,
)
from loushang.tui.ui_parts import DirectoryTree as UiDirectoryTree
from loushang.tui.ui_parts.widgets import DirectoryTree as WidgetDirectoryTree
from tests.tui.widget_example_playback import play_example


def render_plain(part: Any, *, width: int = 50, height: int = 10) -> tuple[str, ...]:
    result = part.render(RenderConstraints(width=width, max_height=height))
    return tuple(strip_control_sequences(line.text).rstrip() for line in result.lines)


def test_directory_tree_is_reexported_from_public_modules(tmp_path: Path) -> None:
    tree = DirectoryTree(root=tmp_path)

    assert DirectoryTree is UiDirectoryTree
    assert DirectoryTree is WidgetDirectoryTree
    assert DirectoryTreeEntry(path=tmp_path, kind="directory", label=tmp_path.name).path == tmp_path
    assert DirectoryTreeSelect(path=tmp_path, kind="directory").kind == "directory"
    assert DirectoryTreeRealKind is not None
    assert DirectoryTreeEntryKind is not None
    assert PathFilter is not None
    assert PathSortKey is not None
    assert tree.root_path == tmp_path


def test_directory_tree_requires_explicit_absolute_root(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        DirectoryTree()  # type: ignore[call-arg]

    with pytest.raises(ValueError, match="absolute"):
        DirectoryTree(root=Path("relative"))

    with pytest.raises(ValueError, match=r"\.\."):
        DirectoryTree(root=tmp_path / ".." / tmp_path.name)


def test_directory_tree_rejects_missing_and_file_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing"):
        DirectoryTree(root=tmp_path / "missing")

    file_root = tmp_path / "file.txt"
    file_root.write_text("data", encoding="utf-8")

    with pytest.raises(ValueError, match="directory"):
        DirectoryTree(root=file_root)


def test_directory_tree_rejects_relative_outside_and_dotdot_public_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ValueError):
        DirectoryTree(root=root, active_path=Path("relative"))
    with pytest.raises(ValueError):
        DirectoryTree(root=root, active_path=tmp_path / "outside")
    with pytest.raises(ValueError):
        DirectoryTree(root=root, active_path=root / ".." / "root")
    with pytest.raises(ValueError):
        DirectoryTree(root=root, expanded_paths=(Path("relative"),))


def test_directory_tree_tui_widget_has_no_coding_imports() -> None:
    import loushang.tui.ui_parts.widgets.directory_tree as module

    source = ast.parse(inspect.getsource(module))
    imports: list[str] = []
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    assert not any(name == "loushang.coding" or name.startswith("loushang.coding.") for name in imports)


def build_tree_fixture(root: Path) -> None:
    (root / "src" / "widgets").mkdir(parents=True)
    (root / "src" / "main.py").write_text("", encoding="utf-8")
    (root / "README.md").write_text("", encoding="utf-8")
    (root / ".env").write_text("", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "artifact.bin").write_text("", encoding="utf-8")
    (root / "empty").mkdir()


def _create_directory_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip(
                "Windows directory symlinks require Developer Mode or elevation"
            )
        raise


def test_directory_tree_scans_root_directory_first_and_exposes_visible_entries(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)

    tree = DirectoryTree(root=tmp_path, expanded_paths=(tmp_path / "src", tmp_path / "empty"))

    assert [entry.label for entry in tree.visible_entries] == [
        tmp_path.name,
        "build",
        "empty",
        "· No files",
        "src",
        "widgets",
        "main.py",
        "README.md",
    ]
    assert tree.visible_paths == (
        tmp_path,
        tmp_path / "build",
        tmp_path / "empty",
        tmp_path / "src",
        tmp_path / "src" / "widgets",
        tmp_path / "src" / "main.py",
        tmp_path / "README.md",
    )


def test_directory_tree_hides_hidden_paths_by_default_and_can_show_them(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)

    hidden = DirectoryTree(root=tmp_path)
    shown = DirectoryTree(root=tmp_path, show_hidden=True)

    assert tmp_path / ".env" not in hidden.visible_paths
    assert tmp_path / ".env" in shown.visible_paths


def test_directory_tree_filter_ignore_and_sort_callbacks_receive_absolute_lexical_paths(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    seen_filter: list[Path] = []
    seen_ignore: list[Path] = []
    seen_sort: list[Path] = []

    def include(path: Path) -> bool:
        seen_filter.append(path)
        return path.name != "build"

    def ignore(path: Path) -> bool:
        seen_ignore.append(path)
        return path.name == "README.md"

    def sort_key(path: Path) -> object:
        seen_sort.append(path)
        return path.name

    tree = DirectoryTree(root=tmp_path, path_filter=include, ignore_matcher=ignore, sort_key=sort_key)

    assert tmp_path / "build" not in tree.visible_paths
    assert tmp_path / "README.md" not in tree.visible_paths
    assert all(path.is_absolute() and path.is_relative_to(tmp_path) for path in seen_filter)
    assert all(path.is_absolute() and path.is_relative_to(tmp_path) for path in seen_ignore)
    assert all(path.is_absolute() and path.is_relative_to(tmp_path) for path in seen_sort)


def test_directory_tree_does_not_descend_into_filtered_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_tree_fixture(tmp_path)
    original_iterdir = Path.iterdir

    def fail_if_build_is_traversed(path: Path):
        if path == tmp_path / "build":
            raise AssertionError("filtered directory was traversed")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_if_build_is_traversed)

    tree = DirectoryTree(root=tmp_path, path_filter=lambda path: path.name != "build")

    assert tmp_path / "build" not in tree.visible_paths


def assert_root_error_model(tree: DirectoryTree, root: Path) -> None:
    assert len(tree.visible_entries) == 1
    assert tree.visible_entries[0].kind == "error"
    assert tree.visible_entries[0].path == root
    assert tree.visible_entries[0].disabled is True
    assert tree.visible_paths == ()
    assert tree.active_path is None
    assert tree.expanded_path_set == frozenset()


def test_directory_tree_initial_active_and_expanded_paths_repair(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)

    tree = DirectoryTree(
        root=tmp_path,
        active_path=tmp_path / "missing.py",
        expanded_paths=(tmp_path / "src", tmp_path / "README.md", tmp_path / "missing"),
    )

    assert tree.active_path == tmp_path
    assert tree.expanded_path_set == frozenset({tmp_path, tmp_path / "src"})


def test_directory_tree_expansion_methods_validate_paths_and_repair_active(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(
        root=tmp_path,
        active_path=tmp_path / "src" / "widgets",
        expanded_paths=(tmp_path / "src",),
    )

    assert tree.is_expanded(tmp_path / "src") is True
    assert tree.expand_path(tmp_path / "src") is False
    assert tree.collapse_path(tmp_path / "src") is True
    assert tree.active_path == tmp_path / "src"
    assert tree.toggle_path(tmp_path / "src") is True
    assert tree.toggle_path(tmp_path / "src") is True
    assert tree.expand_path(tmp_path / "README.md") is False

    for method_name in ("expand_path", "collapse_path", "toggle_path", "is_expanded"):
        method = getattr(tree, method_name)
        with pytest.raises(ValueError):
            method(Path("relative"))
        with pytest.raises(ValueError):
            method(tmp_path.parent / "outside")
        with pytest.raises(ValueError):
            method(tmp_path / ".." / tmp_path.name)


def test_directory_tree_reload_preserves_valid_state_and_repairs_removed_paths(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path, active_path=tmp_path / "src" / "main.py", expanded_paths=(tmp_path / "src",))

    assert tree.active_path == tmp_path / "src" / "main.py"
    (tmp_path / "src" / "main.py").unlink()
    tree.reload()

    assert tree.active_path in tree.visible_paths
    assert tmp_path / "src" in tree.expanded_path_set
    assert tmp_path / "src" / "main.py" not in tree.visible_paths


def test_directory_tree_reload_root_invalidation_uses_disabled_error_model(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path)

    shutil.rmtree(tmp_path)
    tree.reload()

    assert_root_error_model(tree, tmp_path)


def test_directory_tree_reload_root_becomes_file_uses_disabled_error_model(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path)

    shutil.rmtree(tmp_path)
    tmp_path.write_text("now a file", encoding="utf-8")
    tree.reload()

    assert_root_error_model(tree, tmp_path)


def test_directory_tree_reload_unreadable_root_uses_disabled_error_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path)
    original_iterdir = Path.iterdir

    def fail_root(path: Path):
        if path == tmp_path:
            raise PermissionError("blocked")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_root)

    tree.reload()

    assert_root_error_model(tree, tmp_path)


def test_directory_tree_unreadable_root_construction_uses_disabled_error_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_iterdir = Path.iterdir

    def fail_root(path: Path):
        if path == tmp_path:
            raise PermissionError("blocked")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_root)

    tree = DirectoryTree(root=tmp_path)

    assert_root_error_model(tree, tmp_path)


def test_directory_tree_activation_returns_structured_file_and_directory_selection(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path, expanded_paths=(tmp_path / "src",), active_path=tmp_path / "src")
    tree.focus()

    assert tree.handle_input(InputEvent(kind="key", key="enter")) == DirectoryTreeSelect(
        path=tmp_path / "src",
        kind="directory",
    )
    assert tree.handle_input(InputEvent(kind="key", key="down")) is True
    assert tree.handle_input(InputEvent(kind="key", key="down")) is True
    assert tree.handle_input(InputEvent(kind="key", key="space")) == DirectoryTreeSelect(
        path=tmp_path / "src" / "main.py",
        kind="file",
    )
    assert tree.handle_input(InputEvent(kind="text", text=" ")) == DirectoryTreeSelect(
        path=tmp_path / "src" / "main.py",
        kind="file",
    )


def test_directory_tree_does_not_leak_treeview_input_intent(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path)
    tree.focus()

    result = tree.handle_input(InputEvent(kind="key", key="enter"))

    assert isinstance(result, DirectoryTreeSelect)
    assert getattr(result, "kind", "") == "directory"


def test_directory_tree_renders_through_treeview_and_declares_cursor(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    tree = DirectoryTree(root=tmp_path, active_path=tmp_path / "src")
    tree.focus()

    lines = render_plain(tree, width=40, height=5)
    result = tree.render(RenderConstraints(width=40, max_height=5))

    assert lines[0].startswith("  - ")
    assert any("> " in line and "src" in line for line in lines)
    assert result.cursor == CursorDeclaration(row=3, column=0)


def test_directory_tree_reuses_tree_theme_tokens(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    theme = ThemeResolver(
        defaults={
            "widget.tree.row": {"color": "white"},
            "widget.tree.focus": {"bold": True, "color": "green"},
            "widget.tree.disabled": {"dim": True},
        }
    )
    tree = DirectoryTree(root=tmp_path, expanded_paths=(tmp_path / "empty",), active_path=tmp_path / "empty", theme=theme)
    tree.focus()

    raw = tuple(line.text for line in tree.render(RenderConstraints(width=60, max_height=8)).lines)

    assert any(line.startswith("\x1b[1;32m> ") and "empty" in line for line in raw)
    assert any(line.startswith("\x1b[2m") and "No files" in line for line in raw)


def test_directory_tree_can_hide_empty_rows_with_empty_text_none(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)

    tree = DirectoryTree(root=tmp_path, expanded_paths=(tmp_path / "empty",), empty_text=None)

    assert all(entry.kind != "empty" for entry in tree.visible_entries)
    assert tmp_path / "empty" in tree.visible_paths


def test_directory_tree_applies_semantic_theme_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_tree_fixture(tmp_path)
    original_iterdir = Path.iterdir

    def fail_src(path: Path):
        if path == tmp_path / "src":
            raise PermissionError("blocked")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_src)
    theme = ThemeResolver(
        defaults={
            "widget.tree.row": {"color": "white"},
            "widget.tree.focus": {"bold": True, "color": "green"},
            "widget.tree.disabled": {"dim": True},
            "widget.directoryTree.directory": {"color": "cyan"},
            "widget.directoryTree.file": {"color": "white"},
            "widget.directoryTree.empty": {"color": "bright_black", "dim": True},
            "widget.directoryTree.error": {"color": "red", "dim": True},
        }
    )
    tree = DirectoryTree(
        root=tmp_path,
        expanded_paths=(tmp_path / "empty", tmp_path / "src"),
        theme=theme,
    )

    raw = tuple(line.text for line in tree.render(RenderConstraints(width=80, max_height=20)).lines)

    assert any(line.startswith("\x1b[36m") and "empty" in line for line in raw)
    assert any(line.startswith("\x1b[37m") and "README.md" in line for line in raw)
    assert any(line.startswith("\x1b[2;90m") and "· No files" in line for line in raw)
    assert any(line.startswith("\x1b[2;31m") and "! blocked" in line for line in raw)


def test_directory_tree_applies_sentinel_theme_token(tmp_path: Path) -> None:
    build_tree_fixture(tmp_path)
    theme = ThemeResolver(
        defaults={
            "widget.tree.disabled": {"dim": True},
            "widget.directoryTree.sentinel": {"color": "yellow", "dim": True},
        }
    )
    tree = DirectoryTree(root=tmp_path, max_entries=1, theme=theme)

    raw = tuple(line.text for line in tree.render(RenderConstraints(width=80, max_height=20)).lines)

    assert any(line.startswith("\x1b[2;33m") and "· more entries omitted" in line for line in raw)


def test_directory_tree_max_entries_inserts_sentinels_and_counts_collapsed_descendants(tmp_path: Path) -> None:
    (tmp_path / "alpha" / "nested").mkdir(parents=True)
    (tmp_path / "alpha" / "nested" / "deep.txt").write_text("", encoding="utf-8")
    (tmp_path / "beta").mkdir()
    (tmp_path / "gamma.txt").write_text("", encoding="utf-8")

    tree = DirectoryTree(
        root=tmp_path,
        expanded_paths=(tmp_path / "alpha", tmp_path / "alpha" / "nested"),
        max_entries=2,
    )

    assert tmp_path in tree.visible_paths
    assert tmp_path / "alpha" in tree.visible_paths
    assert tmp_path / "alpha" / "nested" in tree.visible_paths
    assert tmp_path / "alpha" / "nested" / "deep.txt" not in tree.visible_paths
    assert any(entry.kind == "sentinel" and entry.disabled for entry in tree.visible_entries)


def test_directory_tree_max_entries_below_one_normalizes_to_one(tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()

    tree = DirectoryTree(root=tmp_path, max_entries=0)

    assert tmp_path in tree.visible_paths
    assert tmp_path / "alpha" in tree.visible_paths
    assert tmp_path / "beta" not in tree.visible_paths
    assert any(entry.kind == "sentinel" for entry in tree.visible_entries)


def test_directory_tree_nested_sentinel_can_exist_with_parent_sentinel(tmp_path: Path) -> None:
    (tmp_path / "alpha" / "a").mkdir(parents=True)
    (tmp_path / "alpha" / "b").mkdir()
    (tmp_path / "omega").mkdir()

    tree = DirectoryTree(root=tmp_path, expanded_paths=(tmp_path / "alpha",), max_entries=2)

    sentinels = [entry for entry in tree.visible_entries if entry.kind == "sentinel"]
    assert len(sentinels) == 2
    assert all(entry.path is None for entry in sentinels)
    assert all(entry.disabled for entry in sentinels)
    assert all(entry.path not in tree.visible_paths for entry in sentinels)


def test_directory_tree_root_symlink_is_traversed_but_public_paths_stay_lexical(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "child.txt").write_text("", encoding="utf-8")
    link = tmp_path / "link-root"
    _create_directory_symlink(link, target)

    tree = DirectoryTree(root=link)

    assert tree.root_path == link
    assert link / "child.txt" in tree.visible_paths
    assert target / "child.txt" not in tree.visible_paths


def test_directory_tree_descendant_symlink_directory_is_selectable_leaf(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "inside.txt").write_text("", encoding="utf-8")
    link = tmp_path / "linked"
    _create_directory_symlink(link, real)

    tree = DirectoryTree(root=tmp_path, expanded_paths=(link,), active_path=link)
    tree.focus()

    assert link in tree.visible_paths
    assert link / "inside.txt" not in tree.visible_paths
    assert tree.expand_path(link) is False
    assert tree.handle_input(InputEvent(kind="key", key="enter")) == DirectoryTreeSelect(path=link, kind="directory")


def test_directory_tree_runtime_scan_error_renders_disabled_error_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_tree_fixture(tmp_path)
    original_iterdir = Path.iterdir

    def fail_src(path: Path):
        if path == tmp_path / "src":
            raise PermissionError("blocked")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_src)

    tree = DirectoryTree(root=tmp_path, expanded_paths=(tmp_path / "src",))

    assert any(entry.kind == "error" and entry.disabled and entry.path == tmp_path / "src" for entry in tree.visible_entries)


def test_widgets_directory_tree_example_imports() -> None:
    namespace = runpy.run_path("examples/tui/57_widgets_directory_tree.py", run_name="__test__")

    build_app = namespace["build_app"]
    app = build_app()
    result = app.render(RenderConstraints(width=90, max_height=24))

    assert callable(build_app)
    assert result.lines


def test_widgets_directory_tree_example_applies_theme_colors() -> None:
    namespace = runpy.run_path("examples/tui/57_widgets_directory_tree.py", run_name="__test__")

    app = namespace["build_app"]()
    raw = tuple(line.text for line in app.render(RenderConstraints(width=90, max_height=24)).lines)

    assert raw[0].startswith("\x1b[1;36mDirectory Tree")
    assert raw[1].startswith("\x1b[90mRoot ")
    assert any(line.startswith("\x1b[1;36m> - ") for line in raw)
    assert raw[-1].startswith("\x1b[90m[up/down]")


def test_widgets_directory_tree_example_playback_selects_and_toggles_hidden_files() -> None:
    frames = play_example(
        "examples/tui/57_widgets_directory_tree.py",
        events=(
            ("down", InputEvent(kind="key", key="down")),
            ("enter select", InputEvent(kind="key", key="enter")),
            ("hidden toggle", InputEvent(kind="text", text="h")),
            ("reload", InputEvent(kind="text", text="r")),
        ),
        width=90,
        height=24,
    )

    assert "Directory Tree" in frames[0].lines[0]
    assert any("Selected:" in line for line in frames[2].lines)
    assert any(".env" in line for line in frames[3].lines)
    assert any("Reloaded" in line for line in frames[4].lines)
