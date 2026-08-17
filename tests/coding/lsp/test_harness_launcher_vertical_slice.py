from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from loushang.coding.lsp import LspServerDefinition, bind_coding_lsp_runtime
from loushang.coding.sandbox import (
    bind_coding_sandbox_runtime,
    coding_workspace_execution_profile,
)
from loushang.harness.sandbox import SandboxSettings
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.workspace.exec import ExecService

_FAKE_LSP_SERVER = Path(__file__).parent / "fixtures" / "fake_lsp_server.py"


class _NoApprovalResolver:
    actor_id = "coding-lsp-integration"

    def resolve(self, request: object) -> object:
        del request
        raise AssertionError("an admitted Coding LSP launch must not request approval")


def test_real_harness_launcher_drives_lsp_query_and_graceful_cleanup(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / "pyproject.toml").touch()
        source = project / "main.py"
        source.write_text("target = 1\nprint(target)\n", encoding="utf-8")
        method_log = project / "lsp-methods.log"
        secret = "must-not-appear-in-audit"
        audit_events: list[dict[str, object]] = []

        sandbox_runtime = bind_coding_sandbox_runtime(
            workspace_root=project,
            writable_workspace=True,
            settings=SandboxSettings(enabled=False),
            base_exec_service=ExecService(),
        )
        lsp_runtime = None
        result = None
        references = None
        implementation = None
        hover = None
        outline = None
        try:
            lsp_runtime = bind_coding_lsp_runtime(
                workspace_root=project,
                definitions=(
                    LspServerDefinition(
                        id="repository-fake-python",
                        command=(sys.executable, str(_FAKE_LSP_SERVER)),
                        language_extensions={"python": (".py",)},
                        root_markers=("pyproject.toml",),
                        environment={
                            "LOUSHANG_FAKE_LSP_LOG": str(method_log),
                            "LOUSHANG_FAKE_LSP_SECRET": secret,
                        },
                        startup_timeout_seconds=3,
                        request_timeout_seconds=3,
                        shutdown_timeout_seconds=3,
                    ),
                ),
                process_launcher_binder=sandbox_runtime,
                execution_scope=ProcessExecutionScope(
                    approval_resolver=_NoApprovalResolver(),
                    audit_sink=audit_events.append,
                    execution_profile_ceiling=coding_workspace_execution_profile(
                        project,
                        writable=True,
                    ),
                ),
                read_text=lambda path: path.read_text(encoding="utf-8"),
                baseline_environment={},
            )
            result = await lsp_runtime.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                correlation_id="real-lsp-query-1",
            )
            references = await lsp_runtime.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                query="references",
                include_declaration=False,
                correlation_id="real-lsp-query-2",
            )
            implementation = await lsp_runtime.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                query="implementation",
                correlation_id="real-lsp-query-3",
            )
            hover = await lsp_runtime.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                query="hover",
                correlation_id="real-lsp-query-4",
            )
            outline = await lsp_runtime.document_outline(
                path="main.py",
                correlation_id="real-lsp-query-5",
            )
        finally:
            if lsp_runtime is not None:
                await lsp_runtime.close()
            await sandbox_runtime.close()

        assert result is not None
        assert result.server_id == "repository-fake-python"
        assert result.count == 1
        assert result.items[0].path == "main.py"
        assert result.items[0].range.start.line == 1
        assert result.items[0].range.start.character == 1
        assert references is not None
        assert references.count == 1
        assert references.items[0].path == "main.py"
        assert implementation is not None
        assert implementation.count == 1
        assert implementation.items[0].path == "main.py"
        assert hover is not None
        assert hover.items[0].contents == "`target: int`"
        assert hover.items[0].kind == "markdown"
        assert outline is not None
        assert outline.count == 1
        assert outline.items[0].name == "target"
        assert outline.items[0].kind_name == "variable"
        assert method_log.read_text(encoding="utf-8").splitlines() == [
            "initialize",
            "initialized",
            "textDocument/didOpen",
            "textDocument/definition",
            "textDocument/references",
            "textDocument/implementation",
            "textDocument/hover",
            "textDocument/documentSymbol",
            "shutdown",
            "exit",
        ]

        assert not any(
            event.get("type") == "tool_approval_requested" for event in audit_events
        )
        frozen = [
            event for event in audit_events if event.get("type") == "tool_action_frozen"
        ]
        assert len(frozen) == 1
        assert frozen[0]["tool_call_id"] == "real-lsp-query-1"
        assert frozen[0]["actor_id"] == "coding-lsp-integration"
        assert secret not in json.dumps(audit_events, sort_keys=True)

    asyncio.run(scenario())
