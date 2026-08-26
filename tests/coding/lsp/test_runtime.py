from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.coding.lsp import (
    CodingLspRuntime,
    LspServerDefinition,
    ProcessLaunchRequest,
    bind_coding_lsp_runtime,
)
from loushang.harness.tools.process_hosting import ProcessExecutionScope
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
