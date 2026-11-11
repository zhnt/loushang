"""Consumer-owned workspace ports and Harness process-contract re-exports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from loushang.coding.lsp.model import CodeQueryResult, DocumentOutlineResult
from loushang.harness.workspace.process import (
    AuthorizedProcessLauncher,
    ProcessExit,
    ProcessHandle,
    ProcessLaunchRequest,
    ProcessStderrTail,
)

TextReadResult = str | Awaitable[str]
WorkspaceTextReader = Callable[[Path], TextReadResult]
PathExistsResult = bool | Awaitable[bool]
PathExists = Callable[[Path], PathExistsResult]


class InspectSymbolRuntime(Protocol):
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
    ) -> CodeQueryResult: ...

    async def document_outline(
        self,
        *,
        path: str,
        depth: int = 4,
        limit: int = 200,
        correlation_id: str,
        signal: object | None = None,
    ) -> DocumentOutlineResult: ...


__all__ = [
    "AuthorizedProcessLauncher",
    "InspectSymbolRuntime",
    "PathExists",
    "PathExistsResult",
    "ProcessExit",
    "ProcessHandle",
    "ProcessLaunchRequest",
    "ProcessStderrTail",
    "TextReadResult",
    "WorkspaceTextReader",
]
