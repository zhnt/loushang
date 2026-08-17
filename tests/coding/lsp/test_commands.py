from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.coding.lsp.commands import execute_lsp_session_command
from loushang.coding.lsp.status import (
    LspServerRuntimeStatus,
    LspSessionStatus,
)


class _Runtime:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.stop_calls: list[tuple[str, str]] = []
        self.stopped = False

    def status(self) -> LspSessionStatus:
        return LspSessionStatus(
            servers=(
                LspServerRuntimeStatus(
                    definition_id="pyright",
                    workspace_root=str(self.root),
                    state="stopped" if self.stopped else "ready",
                    open_document_count=0 if self.stopped else 1,
                    current_diagnostic_count=0 if self.stopped else 2,
                    request_count=3,
                ),
            )
        )

    async def stop(
        self,
        *,
        definition_id: str,
        workspace_root: str | Path,
    ) -> bool:
        self.stop_calls.append((definition_id, str(workspace_root)))
        self.stopped = True
        return True


def test_lsp_session_command_projects_status_and_explicit_stop(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)

    status = asyncio.run(execute_lsp_session_command(runtime, "status"))
    stopped = asyncio.run(
        execute_lsp_session_command(
            runtime,
            f'stop pyright "{tmp_path}"',
        )
    )

    assert status.result["scope"] == "session"
    assert status.result["ready_count"] == 1
    assert "pyright" in status.result["display"]
    assert "diagnostics=2" in status.result["display"]
    assert runtime.stop_calls == [("pyright", str(tmp_path))]
    assert stopped.result["action"] == "stop"
    assert stopped.result["stopped"] is True
    assert stopped.result["servers"][0]["state"] == "stopped"


def test_lsp_session_command_reports_disabled_and_invalid_usage() -> None:
    disabled = asyncio.run(execute_lsp_session_command(None, "status"))
    invalid = asyncio.run(execute_lsp_session_command(None, "stop pyright"))

    assert disabled.result["enabled"] is False
    assert disabled.result["display"] == "LSP session capability: disabled"
    assert invalid.result["status"] == "error"
    assert invalid.result["message"].startswith("Usage: /lsp")
