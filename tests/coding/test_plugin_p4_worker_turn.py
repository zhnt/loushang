from __future__ import annotations

import asyncio

import pytest

from loushang.ai.types import ToolCall
from loushang.coding.bootstrap import create_services
from loushang.coding.cli.application import default_runtime_builder
from loushang.coding.cli.args import parse_args
from loushang.coding.package_product_worker_turn_tool import (
    CODING_WORKER_QUERY_TOOL_NAME,
    CodingWorkerTurnToolBinding,
)
from loushang.harness.tools.execution import DirectToolContext
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


def test_worker_turn_tool_uses_only_bound_read_only_query() -> None:
    class Session:
        def __init__(self) -> None:
            self.symbols: list[str] = []

        async def query_worker_symbol(self, symbol: str) -> str:
            self.symbols.append(symbol)
            return "Review symbol"

    binding = CodingWorkerTurnToolBinding("reviewworker")
    assert binding.definition().name == CODING_WORKER_QUERY_TOOL_NAME
    context = DirectToolContext(tool_call_id="query-1")

    async def journey() -> None:
        call = ToolCall(
            type="toolCall",
            id="query-1",
            name=CODING_WORKER_QUERY_TOOL_NAME,
            arguments={"symbol": "review"},
        )
        with pytest.raises(RuntimeError, match="no Session owner"):
            await binding(call, context)
        session = Session()
        binding.bind_session(session)
        result = await binding(call, context)
        assert result.content[0].text == "Review symbol"
        assert result.details == {"pluginId": "reviewworker", "symbol": "review"}
        assert session.symbols == ["review"]
        with pytest.raises(ValueError, match="exactly one symbol"):
            await binding(
                ToolCall(
                    type="toolCall",
                    id="query-2",
                    name=CODING_WORKER_QUERY_TOOL_NAME,
                    arguments={"symbol": "review", "path": "/tmp"},
                ),
                context,
            )
        with pytest.raises(ValueError, match="symbol is invalid"):
            await binding(
                ToolCall(
                    type="toolCall",
                    id="query-3",
                    name=CODING_WORKER_QUERY_TOOL_NAME,
                    arguments={"symbol": "../secret"},
                ),
                context,
            )
        assert session.symbols == ["review"]

    asyncio.run(journey())


def test_cli_worker_query_choice_requires_persisted_standard_session(tmp_path) -> None:
    assert parse_args(["--worker-query-plugin", "reviewworker"]).worker_query_plugin == (
        "reviewworker"
    )
    for extra in (
        ["--composition-set", "coding-minimal"],
        ["--no-session"],
        ["--no-tools"],
        ["--mode", "rpc"],
    ):
        with pytest.raises(ValueError, match="Worker query requires"):
            default_runtime_builder(
                args=parse_args(
                    [
                        "--mode", "print",
                        "--worker-query-plugin", "reviewworker",
                        *extra,
                    ]
                ),
                cwd=tmp_path,
                session_dir=tmp_path / "sessions",
                services=create_services(),
                tool_registry=WorkspaceToolRegistry(),
            )

    runtime = default_runtime_builder(
        args=parse_args(
            [
                "--mode", "print",
                "--cwd", str(tmp_path),
                "--composition-set", "coding-standard",
                "--worker-query-plugin", "reviewworker",
            ]
        ),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=create_services(),
        tool_registry=WorkspaceToolRegistry(),
    )
    asyncio.run(runtime.dispose_session_runtime())
