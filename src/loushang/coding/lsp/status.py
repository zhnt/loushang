"""Bounded, source-free status values for one Coding LSP session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LspServerRuntimeState = Literal["starting", "ready", "failed", "stopped"]


@dataclass(frozen=True, slots=True)
class LspServerRuntimeStatus:
    """One known session-local Server runtime without process or source data."""

    definition_id: str
    workspace_root: str
    state: LspServerRuntimeState
    runtime_id: int | None = None
    open_document_count: int = 0
    request_count: int = 0
    timeout_count: int = 0
    replacement_count: int = 0
    accepted_diagnostic_publications: int = 0
    discarded_diagnostic_publications: int = 0
    diagnostic_document_count: int = 0
    current_diagnostic_count: int = 0
    last_request_duration_ms: float | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class LspSessionStatus:
    """Read-only status for the LSP capability bound to one Coding session."""

    scope: Literal["session"] = "session"
    enabled: bool = True
    disposed: bool = False
    servers: tuple[LspServerRuntimeStatus, ...] = ()

    @property
    def starting_count(self) -> int:
        return sum(server.state == "starting" for server in self.servers)

    @property
    def ready_count(self) -> int:
        return sum(server.state == "ready" for server in self.servers)

    @property
    def failed_count(self) -> int:
        return sum(server.state == "failed" for server in self.servers)


def disabled_lsp_session_status() -> LspSessionStatus:
    return LspSessionStatus(enabled=False)


__all__ = [
    "LspServerRuntimeState",
    "LspServerRuntimeStatus",
    "LspSessionStatus",
    "disabled_lsp_session_status",
]
