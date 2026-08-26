"""Production composition boundary for one session-owned Coding LSP runtime."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.coding.lsp.binding import CodingLspBinding
from loushang.coding.lsp.diagnostics import DiagnosticInboxSnapshot
from loushang.coding.lsp.model import (
    CodeDiagnostic,
    CodeQueryResult,
    DocumentOutlineResult,
    LspServerDefinition,
)
from loushang.coding.lsp.ports import PathExists, WorkspaceTextReader
from loushang.coding.lsp.status import LspSessionStatus
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.workspace.process import AuthorizedProcessLauncher


class ProcessLauncherBinder(Protocol):
    """Narrow Sandbox-runtime shape needed by Coding's composition root."""

    def bind_process_launcher(
        self,
        scope: ProcessExecutionScope,
    ) -> AuthorizedProcessLauncher: ...


class CodingLspSessionAccess(Protocol):
    """Non-owning status and control view retained by a Product Session."""

    def status(self) -> LspSessionStatus: ...

    async def stop(
        self,
        *,
        definition_id: str,
        workspace_root: str | Path,
    ) -> bool: ...


@dataclass(slots=True)
class CodingLspRuntime:
    """Own the Product binding while exposing only its semantic query surface."""

    _binding: CodingLspBinding

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
        return await self._binding.inspect_symbol(
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
        return await self._binding.document_outline(
            path=path,
            depth=depth,
            limit=limit,
            correlation_id=correlation_id,
            signal=signal,
        )

    def status(self) -> LspSessionStatus:
        return self._binding.status()

    def current_diagnostics(self) -> tuple[CodeDiagnostic, ...]:
        return self._binding.current_diagnostics()

    def diagnostics_snapshot(self) -> DiagnosticInboxSnapshot:
        return self._binding.diagnostics_snapshot()

    async def stop(
        self,
        *,
        definition_id: str,
        workspace_root: str | Path,
    ) -> bool:
        return await self._binding.stop(
            definition_id=definition_id,
            workspace_root=workspace_root,
        )

    async def close(self) -> None:
        await self._binding.dispose()


class DeferredCodingLspRuntime:
    """Construction-time slot used before the session Sandbox is available."""

    def __init__(self) -> None:
        self._runtime: CodingLspRuntime | None = None

    def bind(self, runtime: CodingLspRuntime) -> None:
        if self._runtime is not None:
            raise RuntimeError("Coding LSP runtime is already bound")
        self._runtime = runtime

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
        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("Coding LSP runtime is not bound")
        return await runtime.inspect_symbol(
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
        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("Coding LSP runtime is not bound")
        return await runtime.document_outline(
            path=path,
            depth=depth,
            limit=limit,
            correlation_id=correlation_id,
            signal=signal,
        )


def bind_coding_lsp_runtime(
    *,
    workspace_root: str | Path,
    definitions: Iterable[LspServerDefinition],
    process_launcher_binder: ProcessLauncherBinder,
    execution_scope: ProcessExecutionScope,
    read_text: WorkspaceTextReader,
    baseline_environment: Mapping[str, str],
) -> CodingLspRuntime:
    """Bind Coding semantics to the sole Product-visible Harness launch port."""

    launcher = process_launcher_binder.bind_process_launcher(execution_scope)
    return _bind_coding_lsp_runtime_from_launcher(
        workspace_root=workspace_root,
        definitions=definitions,
        process_launcher=launcher,
        read_text=read_text,
        baseline_environment=baseline_environment,
    )


def _bind_coding_lsp_runtime_from_launcher(
    *,
    workspace_root: str | Path,
    definitions: Iterable[LspServerDefinition],
    process_launcher: AuthorizedProcessLauncher,
    read_text: WorkspaceTextReader,
    baseline_environment: Mapping[str, str],
    path_exists: PathExists | None = None,
) -> CodingLspRuntime:
    """Bind LSP semantics to an already-authorized process launch facet."""

    return CodingLspRuntime(
        CodingLspBinding(
            workspace_root=workspace_root,
            definitions=definitions,
            launcher=process_launcher,
            read_text=read_text,
            baseline_environment=baseline_environment,
            path_exists=path_exists,
        )
    )


__all__ = [
    "CodingLspRuntime",
    "CodingLspSessionAccess",
    "DeferredCodingLspRuntime",
    "ProcessLauncherBinder",
    "bind_coding_lsp_runtime",
]
