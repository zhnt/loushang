from __future__ import annotations

import asyncio

import pytest

from loushang.harness.cli import (
    CommandExecutionError,
    CommandExecutionRequest,
    execute_command,
    format_command_execution_result,
)


class _Session:
    async def execute_command_async(self, name: str, args: str) -> object:
        return type("Execution", (), {"result": {"name": name, "args": args}})()


def test_execute_command_normalizes_leading_slash_and_formats_json() -> None:
    result = asyncio.run(
        execute_command(
            _Session(),
            CommandExecutionRequest(command="/deploy", args="now"),
        )
    )
    assert result.command == "deploy"
    assert format_command_execution_result(result, result_format="json") == (
        '{"command": "deploy", "args": "now", '
        '"result": {"name": "deploy", "args": "now"}}\n'
    )


def test_execute_command_rejects_missing_or_empty_capability() -> None:
    with pytest.raises(CommandExecutionError, match="non-empty"):
        asyncio.run(
            execute_command(_Session(), CommandExecutionRequest(command="/"))
        )

    with pytest.raises(CommandExecutionError, match="not available"):
        asyncio.run(
            execute_command(
                object(), CommandExecutionRequest(command="deploy")
            )
        )
