"""Optional compatibility gate for an already-installed gopls Server."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from loushang.coding.lsp import (
    CodingLspRuntime,
    LspServerRuntimeStatus,
    bind_coding_lsp_runtime,
    default_lsp_environment,
    discover_lsp_catalog,
)
from loushang.coding.sandbox import (
    bind_coding_sandbox_runtime,
    coding_workspace_execution_profile,
)
from loushang.harness.sandbox import SandboxSettings
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.workspace.exec import ExecService


def _resolve_gopls() -> str | None:
    configured = os.environ.get("LOUSHANG_TEST_GOPLS")
    if configured is None:
        return shutil.which("gopls")
    candidate = Path(configured).expanduser().resolve()
    return str(candidate) if candidate.is_file() else None


_GOPLS = _resolve_gopls()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        _GOPLS is None,
        reason="gopls is not installed; optional LSP compatibility verification skipped",
    ),
]


class _NoApprovalResolver:
    actor_id = "coding-lsp-gopls-live"

    def resolve(self, request: object) -> object:
        del request
        raise AssertionError("an admitted gopls launch must not request approval")


async def _wait_for_diagnostic_state(
    runtime: CodingLspRuntime,
    predicate: Callable[[LspServerRuntimeStatus], bool],
    *,
    timeout_seconds: float = 20,
) -> LspServerRuntimeStatus:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    last_status: LspServerRuntimeStatus | None = None
    while loop.time() < deadline:
        status = runtime.status()
        if status.servers:
            last_status = status.servers[0]
            if predicate(last_status):
                return last_status
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"gopls diagnostic state did not converge; last status: {last_status!r}"
    )


def test_product_gopls_preset_semantics_diagnostics_and_shutdown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        assert _GOPLS is not None
        project = tmp_path / "go-app"
        library_root = project / "lib"
        library_root.mkdir(parents=True)
        (project / "go.mod").write_text(
            "module example.com/loushang/lspfixture\n\ngo 1.26\n",
            encoding="utf-8",
        )
        library = library_root / "lib.go"
        library.write_text(
            "package lib\n\n"
            "func Target(value int) int {\n"
            "\treturn value\n"
            "}\n\n"
            'var Broken int = "not an int"\n',
            encoding="utf-8",
        )
        main_line = "\t_ = lib.Target(1)"
        main = project / "main.go"
        main.write_text(
            "package main\n\n"
            'import "example.com/loushang/lspfixture/lib"\n\n'
            "func main() {\n"
            f"{main_line}\n"
            "}\n",
            encoding="utf-8",
        )
        baseline_environment = default_lsp_environment()
        baseline_environment["XDG_CACHE_HOME"] = str(project / ".cache")

        catalog = discover_lsp_catalog(
            workspace_root=project,
            baseline_environment=baseline_environment,
            global_config_path=False,
            project_config_path=False,
            executable_resolver=lambda command, _environment: (
                _GOPLS if command == "gopls" else None
            ),
        )
        assert [item.id for item in catalog.definitions] == ["gopls"]
        definition = catalog.definitions[0]
        assert definition.source == "product-default"
        assert definition.command == (_GOPLS, "serve")
        assert definition.root_markers == ("go.work", "go.mod", ".git")

        sandbox_runtime = bind_coding_sandbox_runtime(
            workspace_root=project,
            writable_workspace=True,
            settings=SandboxSettings(enabled=False),
            base_exec_service=ExecService(),
        )
        runtime = bind_coding_lsp_runtime(
            workspace_root=project,
            definitions=catalog.definitions,
            process_launcher_binder=sandbox_runtime,
            execution_scope=ProcessExecutionScope(
                approval_resolver=_NoApprovalResolver(),
                execution_profile_ceiling=coding_workspace_execution_profile(
                    project,
                    writable=True,
                ),
            ),
            read_text=lambda path: path.read_text(encoding="utf-8"),
            baseline_environment=baseline_environment,
        )
        try:
            assert runtime.status().servers == ()
            target_character = main_line.index("Target") + 1
            definition_result = await runtime.inspect_symbol(
                path="main.go",
                line=6,
                character=target_character,
                correlation_id="gopls-live-definition",
            )
            references = await runtime.inspect_symbol(
                path="main.go",
                line=6,
                character=target_character,
                query="references",
                correlation_id="gopls-live-references",
            )
            hover = await runtime.inspect_symbol(
                path="main.go",
                line=6,
                character=target_character,
                query="hover",
                correlation_id="gopls-live-hover",
            )
            outline = await runtime.document_outline(
                path="lib/lib.go",
                correlation_id="gopls-live-outline",
            )

            assert definition_result.server_id == "gopls"
            assert any(item.path == "lib/lib.go" for item in definition_result.items)
            assert references.count >= 2
            assert hover.count >= 1
            assert any(item.name == "Target" for item in outline.items)
            diagnosed = await _wait_for_diagnostic_state(
                runtime,
                lambda server: (
                    server.accepted_diagnostic_publications >= 1
                    and server.current_diagnostic_count >= 1
                ),
            )
            assert diagnosed.workspace_root == str(project.resolve())
            assert diagnosed.open_document_count == 2

            library.write_text(
                "package lib\n\n"
                "func Target(value int) int {\n"
                "\treturn value\n"
                "}\n\n"
                "var Broken int = 1\n",
                encoding="utf-8",
            )
            await runtime.document_outline(
                path="lib/lib.go",
                correlation_id="gopls-live-diagnostic-fix",
            )
            cleared = await _wait_for_diagnostic_state(
                runtime,
                lambda server: (
                    server.accepted_diagnostic_publications
                    > diagnosed.accepted_diagnostic_publications
                    and server.current_diagnostic_count == 0
                ),
            )
            assert cleared.diagnostic_document_count == 0
        finally:
            await runtime.close()
            await sandbox_runtime.close()

        status = runtime.status()
        assert status.disposed is True
        assert status.servers[0].state == "stopped"

    asyncio.run(scenario())
