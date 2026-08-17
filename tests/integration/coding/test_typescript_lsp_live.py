"""Optional compatibility gate for an already-installed TypeScript Server."""

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


def _resolve_typescript_language_server() -> str | None:
    configured = os.environ.get("LOUSHANG_TEST_TYPESCRIPT_LANGSERVER")
    if configured is None:
        return shutil.which("typescript-language-server")
    candidate = Path(configured).expanduser().resolve()
    return str(candidate) if candidate.is_file() else None


_TYPESCRIPT_LANGUAGE_SERVER = _resolve_typescript_language_server()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        _TYPESCRIPT_LANGUAGE_SERVER is None,
        reason=(
            "typescript-language-server is not installed; optional LSP "
            "compatibility verification skipped"
        ),
    ),
]


class _NoApprovalResolver:
    actor_id = "coding-lsp-typescript-live"

    def resolve(self, request: object) -> object:
        del request
        raise AssertionError(
            "an admitted TypeScript Server launch must not request approval"
        )


async def _wait_for_diagnostic_state(
    runtime: CodingLspRuntime,
    predicate: Callable[[LspServerRuntimeStatus], bool],
    *,
    timeout_seconds: float = 15,
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
        f"TypeScript diagnostic state did not converge; last status: {last_status!r}"
    )


def test_product_typescript_preset_semantics_diagnostics_and_shutdown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        assert _TYPESCRIPT_LANGUAGE_SERVER is not None
        project = tmp_path / "web-app"
        source_root = project / "src"
        source_root.mkdir(parents=True)
        (project / "package.json").write_text(
            '{"name":"lsp-typescript-live","private":true}',
            encoding="utf-8",
        )
        (project / "tsconfig.json").write_text(
            "{"
            '"compilerOptions":{'
            '"target":"ES2022",'
            '"module":"ESNext",'
            '"moduleResolution":"Bundler",'
            '"strict":true,'
            '"noEmit":true'
            "},"
            '"include":["src/**/*.ts"]'
            "}",
            encoding="utf-8",
        )
        library = source_root / "lib.ts"
        library.write_text(
            "export function target(value: number): number {\n"
            "  return value;\n"
            "}\n\n"
            'export const broken: number = "not a number";\n',
            encoding="utf-8",
        )
        main_line = 'export const label = "😀"; export const result = target(1);'
        main = source_root / "main.ts"
        main.write_text(
            'import { target } from "./lib";\n' + main_line + "\n",
            encoding="utf-8",
        )

        catalog = discover_lsp_catalog(
            workspace_root=project,
            baseline_environment=default_lsp_environment(),
            global_config_path=False,
            project_config_path=False,
            executable_resolver=lambda command, _environment: (
                _TYPESCRIPT_LANGUAGE_SERVER
                if command == "typescript-language-server"
                else None
            ),
        )
        assert [item.id for item in catalog.definitions] == [
            "typescript-language-server"
        ]
        definition = catalog.definitions[0]
        assert definition.source == "product-default"
        assert definition.root_markers == (
            "tsconfig.json",
            "jsconfig.json",
            "package.json",
            ".git",
        )

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
            baseline_environment=default_lsp_environment(),
        )
        try:
            # Public positions count Unicode code points; the Server receives UTF-16.
            # A missing conversion would land on the space before ``target``.
            target_character = main_line.index("target") + 1
            definition_result = await runtime.inspect_symbol(
                path="src/main.ts",
                line=2,
                character=target_character,
                correlation_id="typescript-live-definition",
            )
            references = await runtime.inspect_symbol(
                path="src/main.ts",
                line=2,
                character=target_character,
                query="references",
                correlation_id="typescript-live-references",
            )
            hover = await runtime.inspect_symbol(
                path="src/main.ts",
                line=2,
                character=target_character,
                query="hover",
                correlation_id="typescript-live-hover",
            )
            outline = await runtime.document_outline(
                path="src/lib.ts",
                correlation_id="typescript-live-outline",
            )

            assert definition_result.server_id == "typescript-language-server"
            assert definition_result.count >= 1
            assert all(item.readable for item in definition_result.items)
            assert references.count >= 2
            assert hover.count >= 1
            assert any(item.name == "target" for item in outline.items)
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
                "export function target(value: number): number {\n"
                "  return value;\n"
                "}\n\n"
                "export const broken: number = 1;\n",
                encoding="utf-8",
            )
            await runtime.document_outline(
                path="src/lib.ts",
                correlation_id="typescript-live-diagnostic-fix",
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
