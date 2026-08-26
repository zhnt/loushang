"""Deterministic language-server selection within one Coding workspace."""

from __future__ import annotations

import inspect
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


@dataclass(frozen=True, slots=True)
class _Candidate:
    definition: LspServerDefinition
    language_id: str
    root: Path
    marker_matched: bool


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
        file_path = self._canonical_file(path)
        normalized_language = language_id.strip().lower() if language_id else None
        extension = file_path.suffix.lower()
        candidates: list[_Candidate] = []

        for definition, matched_language in self._matching_definitions(
            file_path,
            language_id=normalized_language,
        ):
            root = self._find_root(file_path.parent, definition.root_markers)
            if root is None:
                continue
            candidates.append(
                _Candidate(
                    definition=definition,
                    language_id=matched_language,
                    root=root,
                    marker_matched=bool(definition.root_markers),
                )
            )

        return self._select_candidate(
            candidates,
            file_path=file_path,
            requested=normalized_language or extension or "unknown",
        )

    async def select_async(
        self,
        path: str | Path,
        *,
        language_id: str | None = None,
    ) -> LspServerSelection:
        """Select through a workspace facet that may implement async reads."""

        file_path = self._canonical_file(path)
        normalized_language = language_id.strip().lower() if language_id else None
        extension = file_path.suffix.lower()
        candidates: list[_Candidate] = []

        for definition, matched_language in self._matching_definitions(
            file_path,
            language_id=normalized_language,
        ):
            root = await self._find_root_async(
                file_path.parent,
                definition.root_markers,
            )
            if root is None:
                continue
            candidates.append(
                _Candidate(
                    definition=definition,
                    language_id=matched_language,
                    root=root,
                    marker_matched=bool(definition.root_markers),
                )
            )

        return self._select_candidate(
            candidates,
            file_path=file_path,
            requested=normalized_language or extension or "unknown",
        )

    def _canonical_file(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace_root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._workspace_root):
            raise LspInvalidInputError("LSP path must stay within the Coding workspace")
        return resolved

    def _find_root(self, start: Path, markers: tuple[str, ...]) -> Path | None:
        if not markers:
            return self._workspace_root
        current = start
        while current.is_relative_to(self._workspace_root):
            for marker in markers:
                result = self._path_exists(current / marker)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError(
                        "async LSP path existence checks require select_async()"
                    )
                if not isinstance(result, bool):
                    raise TypeError("LSP path existence check must return bool")
                if result:
                    return current
            if current == self._workspace_root:
                break
            current = current.parent
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
        current = start
        while current.is_relative_to(self._workspace_root):
            for marker in markers:
                result = self._path_exists(current / marker)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, bool):
                    raise TypeError("LSP path existence check must return bool")
                if result:
                    return current
            if current == self._workspace_root:
                break
            current = current.parent
        return None

    @staticmethod
    def _select_candidate(
        candidates: list[_Candidate],
        *,
        file_path: Path,
        requested: str,
    ) -> LspServerSelection:
        if not candidates:
            raise LspUnavailableError(f"no admitted LSP server matches {requested!r}")
        candidates.sort(
            key=lambda candidate: (
                -candidate.definition.priority,
                -len(candidate.root.parts),
                candidate.definition.id,
            )
        )
        selected = candidates[0]
        reason_code = (
            "nearest_root"
            if selected.marker_matched
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
