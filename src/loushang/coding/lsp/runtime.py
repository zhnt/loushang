"""Production composition boundary for one session-owned Coding LSP runtime."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.coding.lsp.binding import CodingLspBinding, _CodingLspQueries
from loushang.coding.lsp.diagnostics import DiagnosticInboxSnapshot
from loushang.coding.lsp.model import (
    CodeDiagnostic,
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
class CodingLspRuntime(_CodingLspQueries):
    """Own the Product binding while exposing only its semantic query surface."""

    _binding: CodingLspBinding

    def _query_target(self) -> CodingLspBinding:
        return self._binding

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
    "ProcessLauncherBinder",
    "bind_coding_lsp_runtime",
]
