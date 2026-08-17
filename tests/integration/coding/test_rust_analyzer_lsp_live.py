"""Optional compatibility gate for an already-installed rust-analyzer Server."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from loushang.coding.lsp import (
    CodeQueryResult,
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


def _resolve_rust_analyzer() -> str | None:
    configured = os.environ.get("LOUSHANG_TEST_RUST_ANALYZER")
    if configured is None:
        return shutil.which("rust-analyzer")
    candidate = Path(configured).expanduser().resolve()
    return str(candidate) if candidate.is_file() else None


_RUST_ANALYZER = _resolve_rust_analyzer()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        _RUST_ANALYZER is None,
        reason=(
            "rust-analyzer is not installed; optional LSP compatibility "
            "verification skipped"
        ),
    ),
]


class _NoApprovalResolver:
    actor_id = "coding-lsp-rust-analyzer-live"

    def resolve(self, request: object) -> object:
        del request
        raise AssertionError(
            "an admitted rust-analyzer launch must not request approval"
        )


async def _wait_for_diagnostic_state(
    runtime: CodingLspRuntime,
    predicate: Callable[[LspServerRuntimeStatus], bool],
    *,
    timeout_seconds: float = 30,
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
        f"rust-analyzer diagnostic state did not converge; last status: {last_status!r}"
    )


async def _wait_for_definition(
    runtime: CodingLspRuntime,
    *,
    path: str,
    line: int,
    character: int,
    timeout_seconds: float = 20,
) -> CodeQueryResult:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    attempt = 0
    last_result: CodeQueryResult | None = None
    while loop.time() < deadline:
        attempt += 1
        last_result = await runtime.inspect_symbol(
            path=path,
            line=line,
            character=character,
            correlation_id=f"rust-analyzer-live-definition-{attempt}",
        )
        if last_result.count >= 1:
            return last_result
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"rust-analyzer definition did not become ready; last result: {last_result!r}"
    )


def test_product_rust_analyzer_preset_semantics_diagnostics_and_shutdown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        assert _RUST_ANALYZER is not None
        project = tmp_path / "rust-app"
        source_root = project / "src"
        source_root.mkdir(parents=True)
        (project / "Cargo.toml").write_text(
            '[package]\nname = "lsp-fixture"\nversion = "0.1.0"\nedition = "2024"\n',
            encoding="utf-8",
        )
        library = source_root / "lib.rs"
        library.write_text(
            "pub fn target(value: i32) -> i32 {\n"
            "    value\n"
            "}\n\n"
            'pub const BROKEN: i32 = "not an integer";\n',
            encoding="utf-8",
        )
        main_line = "    let _ = target(1);"
        main = source_root / "main.rs"
        main.write_text(
            f"use lsp_fixture::target;\n\nfn main() {{\n{main_line}\n}}\n",
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
                _RUST_ANALYZER if command == "rust-analyzer" else None
            ),
        )
        assert [item.id for item in catalog.definitions] == ["rust-analyzer"]
        definition = catalog.definitions[0]
        assert definition.source == "product-default"
        assert definition.command == (_RUST_ANALYZER,)
        assert definition.root_markers == ("rust-project.json", "Cargo.toml", ".git")

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
            target_character = main_line.index("target") + 1
            outline = await runtime.document_outline(
                path="src/lib.rs",
                correlation_id="rust-analyzer-live-outline",
            )
            definition_result = await _wait_for_definition(
                runtime,
                path="src/main.rs",
                line=4,
                character=target_character,
            )
            references = await runtime.inspect_symbol(
                path="src/main.rs",
                line=4,
                character=target_character,
                query="references",
                correlation_id="rust-analyzer-live-references",
            )
            hover = await runtime.inspect_symbol(
                path="src/main.rs",
                line=4,
                character=target_character,
                query="hover",
                correlation_id="rust-analyzer-live-hover",
            )
            assert definition_result.server_id == "rust-analyzer"
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
                "pub fn target(value: i32) -> i32 {\n"
                "    value\n"
                "}\n\n"
                "pub const BROKEN: i32 = 1;\n",
                encoding="utf-8",
            )
            await runtime.document_outline(
                path="src/lib.rs",
                correlation_id="rust-analyzer-live-diagnostic-fix",
            )
            # rust-analyzer need not publish an extra empty replacement: advancing
            # the document version must already retire the stale diagnostic set.
            cleared = await _wait_for_diagnostic_state(
                runtime,
                lambda server: (
                    server.accepted_diagnostic_publications
                    >= diagnosed.accepted_diagnostic_publications
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
