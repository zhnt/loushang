"""Deterministic language-server selection within one Coding workspace."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.lsp.catalog import LspCatalog
from loushang.coding.lsp.model import (
    LspInvalidInputError,
    LspServerDefinition,
    LspServerSelection,
    LspUnavailableError,
)
from loushang.coding.lsp.ports import PathExists
from loushang.harness.workspace.paths import resolve_path_inside_workspace


@dataclass(frozen=True, slots=True)
class _Candidate:
    definition: LspServerDefinition
    language_id: str
    root: Path


class LspSelector:
    def __init__(
        self,
        *,
        workspace_root: Path,
        catalog: LspCatalog,
        path_exists: PathExists | None = None,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._catalog = catalog
        self._path_exists = path_exists or Path.exists

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def select(
        self,
        path: str | Path,
        *,
        language_id: str | None = None,
    ) -> LspServerSelection:
        file_path, requested, matches = self._selection_request(path, language_id)
        roots = (
            (
                definition,
                language,
                self._find_root(file_path.parent, definition.root_markers),
            )
            for definition, language in matches
        )
        return self._select_candidate(roots, file_path=file_path, requested=requested)

    async def select_async(
        self,
        path: str | Path,
        *,
        language_id: str | None = None,
    ) -> LspServerSelection:
        """Select through a workspace facet that may implement async reads."""

        file_path, requested, matches = self._selection_request(path, language_id)
        roots = [
            (
                definition,
                language,
                await self._find_root_async(file_path.parent, definition.root_markers),
            )
            for definition, language in matches
        ]
        return self._select_candidate(roots, file_path=file_path, requested=requested)

    def _selection_request(
        self, path: str | Path, language_id: str | None
    ) -> tuple[Path, str, tuple[tuple[LspServerDefinition, str], ...]]:
        file_path = resolve_path_inside_workspace(
            path,
            self._workspace_root,
            error_type=LspInvalidInputError,
            message="LSP path must stay within the Coding workspace",
        )
        normalized = language_id.strip().lower() if language_id else None
        requested = normalized or file_path.suffix.lower() or "unknown"
        return (
            file_path,
            requested,
            self._matching_definitions(file_path, language_id=normalized),
        )

    def _find_root(self, start: Path, markers: tuple[str, ...]) -> Path | None:
        if not markers:
            return self._workspace_root
        for root, path in self._marker_paths(start, markers):
            result = self._path_exists(path)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError(
                    "async LSP path existence checks require select_async()"
                )
            if not isinstance(result, bool):
                raise TypeError("LSP path existence check must return bool")
            if result:
                return root
        return None

    def _matching_definitions(
        self,
        file_path: Path,
        *,
        language_id: str | None,
    ) -> tuple[tuple[LspServerDefinition, str], ...]:
        matches: list[tuple[LspServerDefinition, str]] = []
        for definition in self._catalog.definitions():
            if language_id is not None:
                if language_id in definition.languages:
                    matches.append((definition, language_id))
                continue
            matched_language = definition.language_for_filename(file_path.name)
            if matched_language is not None:
                matches.append((definition, matched_language))
        return tuple(matches)

    async def _find_root_async(
        self,
        start: Path,
        markers: tuple[str, ...],
    ) -> Path | None:
        if not markers:
            return self._workspace_root
        for root, path in self._marker_paths(start, markers):
            result = self._path_exists(path)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, bool):
                raise TypeError("LSP path existence check must return bool")
            if result:
                return root
        return None

    def _marker_paths(
        self, start: Path, markers: tuple[str, ...]
    ) -> Iterator[tuple[Path, Path]]:
        current = start
        while current.is_relative_to(self._workspace_root):
            for marker in markers:
                yield current, current / marker
            if current == self._workspace_root:
                break
            current = current.parent

    @staticmethod
    def _select_candidate(
        roots: Iterable[tuple[LspServerDefinition, str, Path | None]],
        *,
        file_path: Path,
        requested: str,
    ) -> LspServerSelection:
        candidates = [
            _Candidate(definition, language, root)
            for definition, language, root in roots
            if root is not None
        ]
        if not candidates:
            raise LspUnavailableError(f"no admitted LSP server matches {requested!r}")
        selected = min(
            candidates,
            key=lambda candidate: (
                -candidate.definition.priority,
                -len(candidate.root.parts),
                candidate.definition.id,
            ),
        )
        reason_code = (
            "nearest_root"
            if selected.definition.root_markers
            else "priority"
            if len(candidates) > 1
            else "language_match"
        )
        return LspServerSelection(
            definition_id=selected.definition.id,
            language_id=selected.language_id,
            workspace_root=selected.root,
            file_path=file_path,
            reason_code=reason_code,
        )


__all__ = ["LspSelector"]
