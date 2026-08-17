"""Composition root for one session/workspace Coding LSP capability."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from loushang.coding.lsp.catalog import LspCatalog
from loushang.coding.lsp.diagnostics import DiagnosticInbox
from loushang.coding.lsp.documents import LspDocumentManager
from loushang.coding.lsp.model import (
    CodeQueryResult,
    DocumentOutlineResult,
    LspInvalidInputError,
    LspServerDefinition,
    LspServerKey,
)
from loushang.coding.lsp.ports import (
    AuthorizedProcessLauncher,
    PathExists,
    WorkspaceTextReader,
)
from loushang.coding.lsp.selector import LspSelector
from loushang.coding.lsp.status import LspSessionStatus
from loushang.coding.lsp.supervisor import LspServerSupervisor
from loushang.coding.lsp.tools import CodingLspTools


class CodingLspBinding:
    """Own and dispose the complete first active LSP vertical slice."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        definitions: Iterable[LspServerDefinition],
        launcher: AuthorizedProcessLauncher,
        read_text: WorkspaceTextReader,
        baseline_environment: Mapping[str, str],
        path_exists: PathExists | None = None,
    ) -> None:
        root = Path(workspace_root).expanduser().resolve()
        catalog = LspCatalog(definitions)
        selector = LspSelector(
            workspace_root=root,
            catalog=catalog,
            path_exists=path_exists,
        )
        documents = LspDocumentManager(
            workspace_root=root,
            read_text=read_text,
        )
        diagnostics = DiagnosticInbox(
            workspace_root=root,
            document_lookup=documents.snapshot_for_uri,
        )
        supervisor = LspServerSupervisor(
            catalog=catalog,
            launcher=launcher,
            baseline_environment=baseline_environment,
            open_document_count=documents.open_document_count,
            release_runtime_documents=documents.release_runtime,
            diagnostics=diagnostics,
        )
        self._workspace_root = root
        self._catalog = catalog
        self._diagnostics = diagnostics
        self._supervisor = supervisor
        self._tools = CodingLspTools(
            selector=selector,
            supervisor=supervisor,
            documents=documents,
        )

    async def inspect_symbol(
        self,
        *,
        path: str,
        line: int,
        character: int,
        query: str = "definition",
        include_declaration: bool = True,
        limit: int = 50,
        correlation_id: str,
        signal: object | None = None,
    ) -> CodeQueryResult:
        return await self._tools.inspect_symbol(
            path=path,
            line=line,
            character=character,
            query=query,
            include_declaration=include_declaration,
            limit=limit,
            correlation_id=correlation_id,
            signal=signal,
        )

    async def document_outline(
        self,
        *,
        path: str,
        depth: int = 4,
        limit: int = 200,
        correlation_id: str,
        signal: object | None = None,
    ) -> DocumentOutlineResult:
        return await self._tools.document_outline(
            path=path,
            depth=depth,
            limit=limit,
            correlation_id=correlation_id,
            signal=signal,
        )

    def status(self) -> LspSessionStatus:
        return self._supervisor.status()

    async def stop(
        self,
        *,
        definition_id: str,
        workspace_root: str | Path,
    ) -> bool:
        try:
            self._catalog.definition(definition_id)
        except KeyError as exc:
            raise LspInvalidInputError(
                f"unknown LSP server definition: {definition_id!r}"
            ) from exc
        root = Path(workspace_root).expanduser()
        if not root.is_absolute():
            root = self._workspace_root / root
        root = root.resolve()
        if not root.is_relative_to(self._workspace_root):
            raise LspInvalidInputError(
                "LSP Server root must stay within the Coding workspace"
            )
        return await self._supervisor.stop(LspServerKey(definition_id, root))

    async def dispose(self) -> None:
        await self._supervisor.dispose()

    async def __aenter__(self) -> CodingLspBinding:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.dispose()


__all__ = ["CodingLspBinding"]
