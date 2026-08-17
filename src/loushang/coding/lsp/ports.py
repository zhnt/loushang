"""Consumer-owned workspace ports and Harness process-contract re-exports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from loushang.harness.workspace.process import (
    AuthorizedProcessLauncher,
    ProcessExit,
    ProcessHandle,
    ProcessLaunchRequest,
    ProcessStderrTail,
)

TextReadResult = str | Awaitable[str]
WorkspaceTextReader = Callable[[Path], TextReadResult]
PathExists = Callable[[Path], bool]


__all__ = [
    "AuthorizedProcessLauncher",
    "PathExists",
    "ProcessExit",
    "ProcessHandle",
    "ProcessLaunchRequest",
    "ProcessStderrTail",
    "TextReadResult",
    "WorkspaceTextReader",
]
