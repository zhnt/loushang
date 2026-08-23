from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loushang.tui.core import RenderConstraints, RenderResult
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets.tree import TreeNode, TreeView

DirectoryTreeRealKind = Literal["directory", "file"]
DirectoryTreeEntryKind = Literal["directory", "file", "empty", "error", "sentinel"]

PathFilter = Callable[[Path], bool]
PathSortKey = Callable[[Path], object]

__all__ = [
    "DirectoryTree",
    "DirectoryTreeEntry",
    "DirectoryTreeEntryKind",
    "DirectoryTreeRealKind",
    "DirectoryTreeSelect",
    "PathFilter",
    "PathSortKey",
]


@dataclass(frozen=True, slots=True)
class DirectoryTreeEntry:
    path: Path | None
    kind: DirectoryTreeEntryKind
    label: str
    disabled: bool = False
    message: str = ""


@dataclass(frozen=True, slots=True)
class DirectoryTreeSelect:
    path: Path
    kind: DirectoryTreeRealKind


@dataclass(frozen=True, slots=True)
class _DirectoryModelNode:
    entry: DirectoryTreeEntry
    tree_value: str
    children: tuple["_DirectoryModelNode", ...] = ()
    traversable_directory: bool = False


@dataclass(slots=True)
class _ScanBudget:
    remaining: int


class _RootScanError(Exception):
    pass


_THEME_TOKENS_BY_KIND: dict[DirectoryTreeEntryKind, str] = {
    "directory": "widget.directoryTree.directory",
    "file": "widget.directoryTree.file",
    "empty": "widget.directoryTree.empty",
    "error": "widget.directoryTree.error",
    "sentinel": "widget.directoryTree.sentinel",
}


@dataclass(init=False, slots=True)
class DirectoryTree:
    root: str | Path
    show_hidden: bool = False
    path_filter: PathFilter | None = None
    ignore_matcher: PathFilter | None = None
    sort_key: PathSortKey | None = None
    empty_text: str | None = "No files"
    max_entries: int = 2000
    wrap: bool = True
    theme: ThemeResolver | None = None
    focused: bool = False
    _root_path: Path = field(init=False, repr=False)
    _active_path: Path | None = field(default=None, init=False, repr=False)
    _initial_expanded_paths: tuple[Path, ...] = field(default=(), init=False, repr=False)
    _value_to_entry: dict[str, DirectoryTreeEntry] = field(default_factory=dict, init=False, repr=False)
    _path_to_value: dict[Path, str] = field(default_factory=dict, init=False, repr=False)
    _traversable_paths: set[Path] = field(default_factory=set, init=False, repr=False)
    _tree: TreeView = field(init=False, repr=False)

    def __init__(
        self,
        root: str | Path,
        active_path: str | Path | None = None,
        expanded_paths: Sequence[str | Path] = (),
        show_hidden: bool = False,
        path_filter: PathFilter | None = None,
        ignore_matcher: PathFilter | None = None,
        sort_key: PathSortKey | None = None,
        empty_text: str | None = "No files",
        max_entries: int = 2000,
        wrap: bool = True,
        theme: ThemeResolver | None = None,
        focused: bool = False,
    ) -> None:
        self.root = root
        self.show_hidden = show_hidden
        self.path_filter = path_filter
        self.ignore_matcher = ignore_matcher
        self.sort_key = sort_key
        self.empty_text = empty_text
        self.max_entries = max(1, max_entries)
        self.wrap = wrap
        self.theme = theme
        self.focused = focused
        self._root_path = _normalize_absolute_lexical(Path(root), label="root")
        if not self._root_path.exists():
            raise ValueError(f"DirectoryTree root is missing: {self._root_path}")
        if not self._root_path.is_dir():
            raise ValueError(f"DirectoryTree root is not a directory: {self._root_path}")
        self._active_path = (
            None if active_path is None else self._normalize_under_root(Path(active_path), label="active_path")
        )
        self._initial_expanded_paths = tuple(
            self._normalize_under_root(Path(path), label="expanded_paths") for path in expanded_paths
        )
        self._rebuild_tree(preferred_active=self._active_path, preferred_expanded=self._initial_expanded_paths)

    @property
    def root_path(self) -> Path:
        return self._root_path

    @property
    def active_path(self) -> Path | None:
        return self._active_path

    @property
    def expanded_path_set(self) -> frozenset[Path]:
        return frozenset(
            entry.path
            for value in self._tree.expanded_value_set
            if (entry := self._value_to_entry.get(value)) is not None and entry.path is not None
        )

    @property
    def visible_entries(self) -> tuple[DirectoryTreeEntry, ...]:
        return tuple(
            entry
            for value in self._tree.visible_values
            if (entry := self._value_to_entry.get(value)) is not None
        )

    @property
    def visible_paths(self) -> tuple[Path, ...]:
        return tuple(
            entry.path
            for entry in self.visible_entries
            if entry.path is not None and entry.kind in ("directory", "file")
        )

    def focus(self) -> None:
        self.focused = True
        self._tree.focus()

    def blur(self) -> None:
        self.focused = False
        self._tree.blur()

    def reload(self) -> None:
        self._rebuild_tree(preferred_active=self._active_path, preferred_expanded=self.expanded_path_set)

    def expand_path(self, path: str | Path) -> bool:
        value = self._expandable_value(path)
        if value is None:
            return False
        changed = self._tree.expand(value)
        self._sync_public_state_from_tree()
        return changed

    def collapse_path(self, path: str | Path) -> bool:
        value = self._expandable_value(path)
        if value is None:
            return False
        changed = self._tree.collapse(value)
        self._sync_public_state_from_tree()
        return changed

    def toggle_path(self, path: str | Path) -> bool:
        value = self._expandable_value(path)
        if value is None:
            return False
        changed = self._tree.toggle(value)
        self._sync_public_state_from_tree()
        return changed

    def is_expanded(self, path: str | Path) -> bool:
        value = self._expandable_value(path)
        return False if value is None else self._tree.is_expanded(value)

    def handle_input(self, event: object) -> DirectoryTreeSelect | bool | None:
        result = self._tree.handle_input(event)
        self._sync_public_state_from_tree()
        if getattr(result, "kind", "") == "select":
            entry = self._value_to_entry.get(getattr(result, "text", ""))
            if entry is None or entry.disabled or entry.path is None or entry.kind not in ("directory", "file"):
                return None
            return DirectoryTreeSelect(path=entry.path, kind=entry.kind)
        return result if result in (True, False, None) else None

    def _normalize_under_root(self, path: Path, *, label: str) -> Path:
        normalized = _normalize_absolute_lexical(path, label=label)
        try:
            normalized.relative_to(self._root_path)
        except ValueError as exc:
            raise ValueError(f"{label} must be under DirectoryTree root") from exc
        return normalized

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self._tree.render(constraints)

    def _expandable_value(self, path: str | Path) -> str | None:
        normalized = self._normalize_under_root(Path(path), label="path")
        if normalized not in self._traversable_paths:
            return None
        return self._path_to_value.get(normalized)

    def _rebuild_tree(self, *, preferred_active: Path | None, preferred_expanded: Iterable[Path]) -> None:
        self._value_to_entry = {}
        self._path_to_value = {}
        self._traversable_paths = set()
        if not self._root_path.exists() or not self._root_path.is_dir():
            self._set_root_error_model(f"DirectoryTree root is unavailable: {self._root_path}")
            return
        try:
            model = self._build_model()
        except _RootScanError as exc:
            self._set_root_error_model(str(exc))
            return
        root_node = self._tree_node(model)
        expanded_values = [
            self._path_to_value[path]
            for path in (self._root_path, *preferred_expanded)
            if path in self._traversable_paths and path in self._path_to_value
        ]
        active_value = ""
        if preferred_active is not None and preferred_active in self._path_to_value:
            active_value = self._path_to_value[preferred_active]
        self._tree = TreeView(
            (root_node,),
            active_value=active_value,
            expanded_values=tuple(dict.fromkeys(expanded_values)),
            empty_text=self.empty_text or "",
            wrap=self.wrap,
            theme=self.theme,
            focused=self.focused,
        )
        self._sync_public_state_from_tree()

    def _build_model(self) -> _DirectoryModelNode:
        root_entry = DirectoryTreeEntry(
            path=self._root_path,
            kind="directory",
            label=self._root_path.name or str(self._root_path),
        )
        root_value = _real_value(self._root_path)
        children = self._scan_children(self._root_path, _ScanBudget(self.max_entries), is_root=True)
        return _DirectoryModelNode(
            entry=root_entry,
            tree_value=root_value,
            children=children,
            traversable_directory=True,
        )

    def _scan_children(
        self,
        parent: Path,
        budget: _ScanBudget,
        *,
        is_root: bool = False,
    ) -> tuple[_DirectoryModelNode, ...]:
        try:
            candidates = tuple(parent.iterdir())
        except (FileNotFoundError, OSError, PermissionError) as exc:
            if is_root:
                raise _RootScanError(str(exc)) from exc
            message = str(exc)
            return (self._synthetic_node(parent, "error", f"! {message}", index=0, path=parent, message=message),)
        visible = [path for path in candidates if self._passes_filters(path)]
        if not visible:
            if not self.empty_text:
                return ()
            return (self._synthetic_node(parent, "empty", f"· {self.empty_text}", index=0),)
        directories = [path for path in visible if path.is_dir()]
        files = [path for path in visible if not path.is_dir()]
        nodes: list[_DirectoryModelNode] = []
        for child in (*sorted(directories, key=self._sort_tuple), *sorted(files, key=self._sort_tuple)):
            if budget.remaining <= 0:
                nodes.append(self._synthetic_node(parent, "sentinel", "· more entries omitted", index=len(nodes)))
                break
            budget.remaining -= 1
            kind = self._entry_kind(child)
            traversable = kind == "directory" and not self._is_descendant_symlink_directory(child)
            children = self._scan_children(child, budget) if traversable else ()
            nodes.append(
                _DirectoryModelNode(
                    entry=DirectoryTreeEntry(path=child, kind=kind, label=child.name),
                    tree_value=_real_value(child),
                    children=children,
                    traversable_directory=traversable,
                )
            )
        return tuple(nodes)

    def _passes_filters(self, path: Path) -> bool:
        if not self.show_hidden and path.name.startswith("."):
            return False
        if self.path_filter is not None and not self.path_filter(path):
            return False
        return not (self.ignore_matcher is not None and self.ignore_matcher(path))

    def _sort_tuple(self, path: Path) -> tuple[Any, ...]:
        if self.sort_key is not None:
            return (self.sort_key(path), path.name.casefold(), path.name)
        return (path.name.casefold(), path.name)

    def _entry_kind(self, path: Path) -> DirectoryTreeRealKind:
        return "directory" if path.is_dir() else "file"

    def _is_descendant_symlink_directory(self, path: Path) -> bool:
        return path != self._root_path and path.is_symlink() and path.is_dir()

    def _synthetic_node(
        self,
        parent: Path,
        kind: Literal["empty", "error", "sentinel"],
        label: str,
        *,
        index: int,
        path: Path | None = None,
        message: str | None = None,
    ) -> _DirectoryModelNode:
        return _DirectoryModelNode(
            entry=DirectoryTreeEntry(path=path, kind=kind, label=label, disabled=True, message=label if message is None else message),
            tree_value=_synthetic_value(parent, kind, index),
        )

    def _tree_node(self, node: _DirectoryModelNode) -> TreeNode:
        self._value_to_entry[node.tree_value] = node.entry
        if node.entry.path is not None and node.entry.kind in ("directory", "file"):
            self._path_to_value[node.entry.path] = node.tree_value
            if node.traversable_directory:
                self._traversable_paths.add(node.entry.path)
        return TreeNode(
            value=node.tree_value,
            label=node.entry.label,
            children=tuple(self._tree_node(child) for child in node.children),
            disabled=node.entry.disabled,
            theme_token=_THEME_TOKENS_BY_KIND[node.entry.kind],
        )

    def _sync_public_state_from_tree(self) -> None:
        entry = self._value_to_entry.get(self._tree.active_value)
        if entry is None or entry.disabled or entry.path is None:
            self._active_path = None
        else:
            self._active_path = entry.path

    def _set_root_error_model(self, message: str) -> None:
        value = _real_value(self._root_path)
        entry = DirectoryTreeEntry(path=self._root_path, kind="error", label=message, disabled=True, message=message)
        self._value_to_entry = {value: entry}
        self._path_to_value = {}
        self._traversable_paths = set()
        self._tree = TreeView(
            (TreeNode(value=value, label=message, disabled=True, theme_token=_THEME_TOKENS_BY_KIND["error"]),),
            empty_text=self.empty_text or "",
            wrap=self.wrap,
            theme=self.theme,
            focused=self.focused,
        )
        self._active_path = None


def _normalize_absolute_lexical(path: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if ".." in path.parts:
        raise ValueError(f"{label} must not contain '..' path segments")
    return Path(*path.parts)


def _real_value(path: Path) -> str:
    return f"\0real:{path.as_posix()}"


def _synthetic_value(parent: Path, kind: str, index: int) -> str:
    return f"\0synthetic:{parent.as_posix()}:{kind}:{index}"
