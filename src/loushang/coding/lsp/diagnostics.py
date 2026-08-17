"""Bounded, version-aware passive diagnostic state for one Coding session."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Protocol

from loushang.coding.lsp.model import CodeDiagnostic, LspProtocolError
from loushang.coding.lsp.positions import parse_lsp_range, to_public_range

DEFAULT_MAX_DIAGNOSTIC_DOCUMENTS = 128
DEFAULT_MAX_DIAGNOSTICS_PER_DOCUMENT = 100
DEFAULT_MAX_TOTAL_DIAGNOSTICS = 2_048
DEFAULT_MAX_DIAGNOSTIC_CHARACTERS = 256 * 1024
DEFAULT_MAX_RAW_DIAGNOSTICS_PER_PUBLICATION = 512
MAX_DIAGNOSTIC_MESSAGE_CHARACTERS = 2_000
MAX_DIAGNOSTIC_CODE_CHARACTERS = 256
MAX_DIAGNOSTIC_SOURCE_CHARACTERS = 128

_SEVERITIES = {
    1: "error",
    2: "warning",
    3: "information",
    4: "hint",
}
_SEVERITY_ORDER = {
    "error": 0,
    "warning": 1,
    "information": 2,
    "hint": 3,
    "unknown": 4,
}
_TAGS = {1: "unnecessary", 2: "deprecated"}


class DiagnosticDocumentState(Protocol):
    path: Path
    uri: str
    version: int
    content: str


DiagnosticDocumentLookup = Callable[
    [int, str],
    DiagnosticDocumentState | None,
]


@dataclass(frozen=True, slots=True)
class DiagnosticInboxSnapshot:
    document_count: int
    diagnostic_count: int
    total_characters: int
    publication_count: int
    malformed_publication_count: int
    unknown_document_publication_count: int
    stale_publication_count: int
    future_publication_count: int
    omitted_diagnostic_count: int
    truncated_value_count: int
    evicted_document_count: int


@dataclass(frozen=True, slots=True)
class _DiagnosticPublication:
    runtime_id: int
    uri: str
    document_version: int
    diagnostics: tuple[CodeDiagnostic, ...]
    characters: int


class DiagnosticInbox:
    """Retain only current, bounded diagnostic replacement sets."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        document_lookup: DiagnosticDocumentLookup,
        max_documents: int = DEFAULT_MAX_DIAGNOSTIC_DOCUMENTS,
        max_diagnostics_per_document: int = DEFAULT_MAX_DIAGNOSTICS_PER_DOCUMENT,
        max_total_diagnostics: int = DEFAULT_MAX_TOTAL_DIAGNOSTICS,
        max_total_characters: int = DEFAULT_MAX_DIAGNOSTIC_CHARACTERS,
        max_raw_diagnostics_per_publication: int = (
            DEFAULT_MAX_RAW_DIAGNOSTICS_PER_PUBLICATION
        ),
        clock: Callable[[], float] = time,
    ) -> None:
        limits = {
            "max_documents": max_documents,
            "max_diagnostics_per_document": max_diagnostics_per_document,
            "max_total_diagnostics": max_total_diagnostics,
            "max_total_characters": max_total_characters,
            "max_raw_diagnostics_per_publication": (
                max_raw_diagnostics_per_publication
            ),
        }
        for name, value in limits.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._workspace_root = workspace_root.resolve()
        self._document_lookup = document_lookup
        self._max_documents = max_documents
        self._max_diagnostics_per_document = max_diagnostics_per_document
        self._max_total_diagnostics = max_total_diagnostics
        self._max_total_characters = max_total_characters
        self._max_raw_diagnostics_per_publication = max_raw_diagnostics_per_publication
        self._clock = clock
        self._entries: OrderedDict[
            tuple[int, str],
            _DiagnosticPublication,
        ] = OrderedDict()
        self._diagnostic_count = 0
        self._total_characters = 0
        self._publication_count = 0
        self._malformed_publication_count = 0
        self._unknown_document_publication_count = 0
        self._stale_publication_count = 0
        self._future_publication_count = 0
        self._omitted_diagnostic_count = 0
        self._truncated_value_count = 0
        self._evicted_document_count = 0

    def replace_publication(
        self,
        *,
        runtime_id: int,
        server_id: str,
        uri: object,
        version: object,
        diagnostics: object,
    ) -> bool:
        """Replace one complete Server/document set; return whether it was accepted."""

        self._publication_count += 1
        if (
            not isinstance(runtime_id, int)
            or isinstance(runtime_id, bool)
            or runtime_id < 1
            or not isinstance(server_id, str)
            or not server_id
            or not isinstance(uri, str)
            or not uri
            or not isinstance(diagnostics, list)
        ):
            self._malformed_publication_count += 1
            return False
        if version is not None and (
            not isinstance(version, int) or isinstance(version, bool) or version < 0
        ):
            self._malformed_publication_count += 1
            return False

        document = self._document_lookup(runtime_id, uri)
        if document is None or document.uri != uri:
            self._unknown_document_publication_count += 1
            return False
        key = (runtime_id, uri)
        previous = self._entries.get(key)
        if previous is not None and previous.document_version != document.version:
            self._remove(key)
        if isinstance(version, int):
            if version < document.version:
                self._stale_publication_count += 1
                return False
            if version > document.version:
                self._future_publication_count += 1
                return False

        raw_items = diagnostics[: self._max_raw_diagnostics_per_publication]
        self._omitted_diagnostic_count += max(len(diagnostics) - len(raw_items), 0)
        received_at = self._clock()
        normalized: dict[tuple[object, ...], CodeDiagnostic] = {}
        for item in raw_items:
            diagnostic, truncated_values = self._normalize_diagnostic(
                item,
                server_id=server_id,
                document=document,
                version=version,
                received_at=received_at,
            )
            self._truncated_value_count += truncated_values
            if diagnostic is None:
                self._omitted_diagnostic_count += 1
                continue
            normalized.setdefault(_diagnostic_key(diagnostic), diagnostic)

        candidates = sorted(normalized.values(), key=_diagnostic_sort_key)
        retained: list[CodeDiagnostic] = []
        path = _workspace_relative_path(document.path, self._workspace_root)
        characters = len(uri) + (len(path) if path is not None else 0)
        item_limit = min(
            self._max_diagnostics_per_document,
            self._max_total_diagnostics,
        )
        for diagnostic in candidates:
            item_characters = _diagnostic_characters(diagnostic)
            if (
                len(retained) >= item_limit
                or characters + item_characters > self._max_total_characters
            ):
                self._omitted_diagnostic_count += 1
                continue
            retained.append(diagnostic)
            characters += item_characters

        self._remove(key)
        if retained:
            publication = _DiagnosticPublication(
                runtime_id=runtime_id,
                uri=uri,
                document_version=document.version,
                diagnostics=tuple(retained),
                characters=characters,
            )
            self._entries[key] = publication
            self._diagnostic_count += len(publication.diagnostics)
            self._total_characters += publication.characters
            self._enforce_total_limits()
        return True

    def current(self, *, runtime_id: int | None = None) -> tuple[CodeDiagnostic, ...]:
        self._prune_obsolete(runtime_id)
        return tuple(
            diagnostic
            for publication in self._entries.values()
            if runtime_id is None or publication.runtime_id == runtime_id
            for diagnostic in publication.diagnostics
        )

    def counts(self, runtime_id: int) -> tuple[int, int]:
        self._prune_obsolete(runtime_id)
        publications = tuple(
            publication
            for publication in self._entries.values()
            if publication.runtime_id == runtime_id
        )
        return len(publications), sum(
            len(publication.diagnostics) for publication in publications
        )

    def release_runtime(self, runtime_id: int) -> None:
        for key in tuple(self._entries):
            if key[0] == runtime_id:
                self._remove(key)

    def snapshot(self) -> DiagnosticInboxSnapshot:
        self._prune_obsolete()
        return DiagnosticInboxSnapshot(
            document_count=len(self._entries),
            diagnostic_count=self._diagnostic_count,
            total_characters=self._total_characters,
            publication_count=self._publication_count,
            malformed_publication_count=self._malformed_publication_count,
            unknown_document_publication_count=(
                self._unknown_document_publication_count
            ),
            stale_publication_count=self._stale_publication_count,
            future_publication_count=self._future_publication_count,
            omitted_diagnostic_count=self._omitted_diagnostic_count,
            truncated_value_count=self._truncated_value_count,
            evicted_document_count=self._evicted_document_count,
        )

    def _normalize_diagnostic(
        self,
        value: object,
        *,
        server_id: str,
        document: DiagnosticDocumentState,
        version: int | None,
        received_at: float,
    ) -> tuple[CodeDiagnostic | None, int]:
        if not isinstance(value, Mapping):
            return None, 0
        raw_message = value.get("message")
        raw_range = value.get("range")
        if (
            not isinstance(raw_message, str)
            or not raw_message.strip()
            or not isinstance(raw_range, Mapping)
        ):
            return None, 0
        try:
            code_range = to_public_range(
                document.content,
                parse_lsp_range(raw_range),
            )
        except LspProtocolError:
            return None, 0

        message, message_truncated = _bounded_text(
            raw_message.strip(),
            MAX_DIAGNOSTIC_MESSAGE_CHARACTERS,
        )
        code = value.get("code")
        if isinstance(code, int) and not isinstance(code, bool):
            code = str(code)
        if not isinstance(code, str):
            code = None
        code, code_truncated = _bounded_optional_text(
            code,
            MAX_DIAGNOSTIC_CODE_CHARACTERS,
        )
        source, source_truncated = _bounded_optional_text(
            value.get("source") if isinstance(value.get("source"), str) else None,
            MAX_DIAGNOSTIC_SOURCE_CHARACTERS,
        )
        raw_tags = value.get("tags")
        tags_truncated = isinstance(raw_tags, list) and len(raw_tags) > 8
        tags = (
            tuple(
                tag
                for item in raw_tags[:8]
                if isinstance(item, int)
                and not isinstance(item, bool)
                and (tag := _TAGS.get(item)) is not None
            )
            if isinstance(raw_tags, list)
            else ()
        )
        severity_value = value.get("severity")
        severity = (
            _SEVERITIES.get(severity_value, "unknown")
            if isinstance(severity_value, int) and not isinstance(severity_value, bool)
            else "unknown"
        )
        return (
            CodeDiagnostic(
                server_id=server_id,
                uri=document.uri,
                path=_workspace_relative_path(document.path, self._workspace_root),
                version=version,
                severity=severity,
                message=message,
                range=code_range,
                code=code,
                source=source,
                tags=tags,
                received_at=received_at,
            ),
            sum(
                (
                    message_truncated,
                    code_truncated,
                    source_truncated,
                    tags_truncated,
                )
            ),
        )

    def _enforce_total_limits(self) -> None:
        while (
            len(self._entries) > self._max_documents
            or self._diagnostic_count > self._max_total_diagnostics
            or self._total_characters > self._max_total_characters
        ):
            _key, publication = self._entries.popitem(last=False)
            self._diagnostic_count -= len(publication.diagnostics)
            self._total_characters -= publication.characters
            self._omitted_diagnostic_count += len(publication.diagnostics)
            self._evicted_document_count += 1

    def _remove(self, key: tuple[int, str]) -> None:
        publication = self._entries.pop(key, None)
        if publication is None:
            return
        self._diagnostic_count -= len(publication.diagnostics)
        self._total_characters -= publication.characters

    def _prune_obsolete(self, runtime_id: int | None = None) -> None:
        for key, publication in tuple(self._entries.items()):
            if runtime_id is not None and publication.runtime_id != runtime_id:
                continue
            document = self._document_lookup(publication.runtime_id, publication.uri)
            if document is None or document.version != publication.document_version:
                self._remove(key)


def _workspace_relative_path(path: Path, workspace_root: Path) -> str | None:
    try:
        return path.resolve().relative_to(workspace_root).as_posix()
    except (OSError, ValueError):
        return None


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    return (value, False) if len(value) <= limit else (value[:limit], True)


def _bounded_optional_text(
    value: str | None,
    limit: int,
) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    bounded, truncated = _bounded_text(value, limit)
    return bounded, truncated


def _diagnostic_key(diagnostic: CodeDiagnostic) -> tuple[object, ...]:
    return (
        diagnostic.range.start.line,
        diagnostic.range.start.character,
        diagnostic.range.end.line,
        diagnostic.range.end.character,
        diagnostic.severity,
        diagnostic.code,
        diagnostic.source,
        diagnostic.message,
        diagnostic.tags,
    )


def _diagnostic_sort_key(diagnostic: CodeDiagnostic) -> tuple[object, ...]:
    return (
        _SEVERITY_ORDER[diagnostic.severity],
        diagnostic.range.start.line,
        diagnostic.range.start.character,
        diagnostic.message,
        diagnostic.code or "",
    )


def _diagnostic_characters(diagnostic: CodeDiagnostic) -> int:
    return (
        len(diagnostic.server_id)
        + len(diagnostic.uri)
        + len(diagnostic.path or "")
        + len(diagnostic.message)
        + len(diagnostic.code or "")
        + len(diagnostic.source or "")
        + sum(len(tag) for tag in diagnostic.tags)
        + 64
    )


__all__ = [
    "DEFAULT_MAX_DIAGNOSTIC_CHARACTERS",
    "DEFAULT_MAX_DIAGNOSTIC_DOCUMENTS",
    "DEFAULT_MAX_DIAGNOSTICS_PER_DOCUMENT",
    "DEFAULT_MAX_RAW_DIAGNOSTICS_PER_PUBLICATION",
    "DEFAULT_MAX_TOTAL_DIAGNOSTICS",
    "DiagnosticDocumentLookup",
    "DiagnosticDocumentState",
    "DiagnosticInbox",
    "DiagnosticInboxSnapshot",
    "MAX_DIAGNOSTIC_CODE_CHARACTERS",
    "MAX_DIAGNOSTIC_MESSAGE_CHARACTERS",
    "MAX_DIAGNOSTIC_SOURCE_CHARACTERS",
]
