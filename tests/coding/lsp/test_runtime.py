from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.coding.lsp import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
    CodingLspRuntime,
    DeferredCodingLspRuntime,
    LspServerDefinition,
    ProcessLaunchRequest,
    bind_coding_lsp_runtime,
    register_coding_lsp_tools,
)
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.process import (
    ProcessLaunchRequest as HarnessProcessLaunchRequest,
)


class _NeverLauncher:
    async def start(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("binding must remain lazy")


class _ProcessLauncherBinder:
    def __init__(self) -> None:
        self.scope: ProcessExecutionScope | None = None

    def bind_process_launcher(self, scope: ProcessExecutionScope) -> _NeverLauncher:
        self.scope = scope
        return _NeverLauncher()


def _definition() -> LspServerDefinition:
    return LspServerDefinition(
        id="python-test",
        command=("python-language-server", "--stdio"),
        language_extensions={"python": (".py",)},
    )


def test_runtime_binds_the_harness_contract_without_starting_a_process(
    tmp_path: Path,
) -> None:
    binder = _ProcessLauncherBinder()
    scope = ProcessExecutionScope()

    runtime = bind_coding_lsp_runtime(
        workspace_root=tmp_path,
        definitions=(_definition(),),
        process_launcher_binder=binder,
        execution_scope=scope,
        read_text=lambda path: path.read_text(encoding="utf-8"),
        baseline_environment={"PATH": "/admitted/bin"},
    )

    assert isinstance(runtime, CodingLspRuntime)
    assert binder.scope is scope
    assert ProcessLaunchRequest is HarnessProcessLaunchRequest
    assert runtime.status().servers == ()
    asyncio.run(runtime.close())
    assert runtime.status().disposed is True


def test_deferred_runtime_and_tool_pack_preserve_mount_policy() -> None:
    on_demand = WorkspaceToolRegistry()
    slot = DeferredCodingLspRuntime()
    register_coding_lsp_tools(on_demand, runtime=slot, mode="on_demand")

    assert [item.name for item in on_demand.list_definitions()] == [
        INSPECT_SYMBOL_TOOL_NAME,
        DOCUMENT_OUTLINE_TOOL_NAME,
    ]
    assert on_demand.list_enabled_definitions() == []

    always = WorkspaceToolRegistry()
    register_coding_lsp_tools(always, runtime=slot, mode="always")
    assert [item.name for item in always.list_enabled_definitions()] == [
        INSPECT_SYMBOL_TOOL_NAME,
        DOCUMENT_OUTLINE_TOOL_NAME,
    ]

    with pytest.raises(RuntimeError, match="not bound"):
        asyncio.run(
            slot.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                correlation_id="before-session",
            )
        )

    with pytest.raises(RuntimeError, match="not bound"):
        asyncio.run(
            slot.document_outline(
                path="main.py",
                correlation_id="before-session",
            )
        )
