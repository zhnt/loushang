"""Deterministic language-server selection within one Coding workspace."""

from __future__ import annotations

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

        for definition in self._catalog.definitions():
            matched_language = normalized_language
            if normalized_language is not None:
                if normalized_language not in definition.languages:
                    continue
            else:
                matched_language = definition.language_for_filename(file_path.name)
                if matched_language is None:
                    continue
            assert matched_language is not None

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

        if not candidates:
            requested = normalized_language or extension or "unknown"
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
            if any(self._path_exists(current / marker) for marker in markers):
                return current
            if current == self._workspace_root:
                break
            current = current.parent
        return None


__all__ = ["LspSelector"]
