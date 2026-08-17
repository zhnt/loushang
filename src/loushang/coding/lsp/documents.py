"""Ordered full-text document synchronization before active LSP queries."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.lsp.model import LspInvalidInputError
from loushang.coding.lsp.ports import WorkspaceTextReader
from loushang.coding.lsp.supervisor import LspRuntimeHandle

_DEFAULT_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    path: Path
    uri: str
    language_id: str
    version: int
    content: str
    content_hash: str


class LspDocumentManager:
    def __init__(
        self,
        *,
        workspace_root: Path,
        read_text: WorkspaceTextReader,
        max_document_bytes: int = _DEFAULT_MAX_DOCUMENT_BYTES,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._read_text = read_text
        self._max_document_bytes = max_document_bytes
        self._snapshots: dict[tuple[int, str], DocumentSnapshot] = {}
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}

    async def ensure_document(
        self,
        runtime: LspRuntimeHandle,
        path: Path,
        *,
        language_id: str,
    ) -> DocumentSnapshot:
        canonical = self.canonical_path(path)
        uri = canonical.as_uri()
        key = (runtime.runtime_id, uri)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            content = await self.read_path(canonical)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            current = self._snapshots.get(key)
            if current is None:
                snapshot = DocumentSnapshot(
                    path=canonical,
                    uri=uri,
                    language_id=language_id,
                    version=1,
                    content=content,
                    content_hash=content_hash,
                )
                self._snapshots[key] = snapshot
                try:
                    await runtime.client.notify(
                        "textDocument/didOpen",
                        {
                            "textDocument": {
                                "uri": uri,
                                "languageId": language_id,
                                "version": 1,
                                "text": content,
                            }
                        },
                    )
                except BaseException:
                    if self._snapshots.get(key) is snapshot:
                        self._snapshots.pop(key, None)
                    raise
                return snapshot
            if current.content_hash == content_hash:
                return current

            snapshot = DocumentSnapshot(
                path=canonical,
                uri=uri,
                language_id=language_id,
                version=current.version + 1,
                content=content,
                content_hash=content_hash,
            )
            self._snapshots[key] = snapshot
            try:
                await runtime.client.notify(
                    "textDocument/didChange",
                    {
                        "textDocument": {
                            "uri": uri,
                            "version": snapshot.version,
                        },
                        "contentChanges": [{"text": content}],
                    },
                )
            except BaseException:
                if self._snapshots.get(key) is snapshot:
                    self._snapshots[key] = current
                raise
            return snapshot

    def canonical_path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace_root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._workspace_root):
            raise LspInvalidInputError("LSP document must stay within the workspace")
        return resolved

    async def read_path(self, path: str | Path) -> str:
        canonical = self.canonical_path(path)
        result = self._read_text(canonical)
        content = await result if inspect.isawaitable(result) else result
        if not isinstance(content, str):
            raise TypeError("workspace text reader must return str")
        if len(content.encode("utf-8")) > self._max_document_bytes:
            raise LspInvalidInputError(
                f"LSP document exceeds {self._max_document_bytes} bytes"
            )
        return content

    def open_document_count(self, runtime_id: int | None = None) -> int:
        if runtime_id is None:
            return len(self._snapshots)
        return sum(key[0] == runtime_id for key in self._snapshots)

    def snapshot_for_uri(
        self,
        runtime_id: int,
        uri: str,
    ) -> DocumentSnapshot | None:
        """Return the current runtime-local snapshot without opening a document."""

        return self._snapshots.get((runtime_id, uri))

    def release_runtime(self, runtime_id: int) -> None:
        snapshot_keys = [key for key in self._snapshots if key[0] == runtime_id]
        for key in snapshot_keys:
            self._snapshots.pop(key, None)
        lock_keys = [key for key in self._locks if key[0] == runtime_id]
        for key in lock_keys:
            self._locks.pop(key, None)


__all__ = ["DocumentSnapshot", "LspDocumentManager"]
