from __future__ import annotations

import asyncio
from io import StringIO

from loushang.harness.host.jsonl_command_host import (
    JsonlCommand,
    JsonlCommandHost,
    JsonlCommandHostError,
)


class _Port:
    def __init__(self) -> None:
        self.commands: list[JsonlCommand] = []
        self.raise_for: str | None = None

    async def handle_jsonl_command(self, command: JsonlCommand) -> None:
        self.commands.append(command)
        if command.command_type == self.raise_for:
            raise RuntimeError("product command failed")


def test_jsonl_command_host_validates_and_dispatches_strict_json_commands() -> None:
    port = _Port()
    errors: list[JsonlCommandHostError] = []
    host = JsonlCommandHost(
        port=port,
        on_error=errors.append,
        stdin=StringIO('{"id":"cmd-1","type":"prompt","message":"hello"}\n'),
    )

    asyncio.run(host.run())

    assert errors == []
    assert port.commands == [
        JsonlCommand(
            command_id="cmd-1",
            command_type="prompt",
            payload={"id": "cmd-1", "type": "prompt", "message": "hello"},
        )
    ]


def test_jsonl_command_host_reports_parse_validation_and_dispatch_errors() -> None:
    port = _Port()
    port.raise_for = "explode"
    errors: list[JsonlCommandHostError] = []
    host = JsonlCommandHost(port=port, on_error=errors.append, stdin=StringIO())

    async def scenario() -> None:
        await host.handle_line("{bad json}")
        await host.handle_line("[]")
        await host.handle_line('{"id":"cmd-2","type":"prompt","value":NaN}')
        await host.handle_line('{"id":2,"type":"prompt"}')
        await host.handle_line('{"id":"cmd-3"}')
        await host.handle_line('{"id":"cmd-4","type":"explode"}')

    asyncio.run(scenario())

    assert [
        (error.kind, error.reason, error.command_id, error.command_type)
        for error in errors
    ] == [
        ("parse", "invalid_json", None, None),
        ("invalid", "not_object", None, None),
        ("parse", "invalid_json", None, None),
        ("invalid", "invalid_id", None, None),
        ("invalid", "missing_type", "cmd-3", None),
        ("dispatch", "handler_failure", "cmd-4", "explode"),
    ]
    assert errors[-1].message == "product command failed"


def test_jsonl_command_host_stop_finishes_after_current_command() -> None:
    port = _Port()
    errors: list[JsonlCommandHostError] = []
    host = JsonlCommandHost(
        port=port,
        on_error=errors.append,
        stdin=StringIO('{"type":"first"}\n{"type":"second"}\n'),
    )

    original = port.handle_jsonl_command

    async def stop_after_first(command: JsonlCommand) -> None:
        await original(command)
        host.stop()

    port.handle_jsonl_command = stop_after_first  # type: ignore[method-assign]

    asyncio.run(host.run())

    assert [command.command_type for command in port.commands] == ["first"]
    assert errors == []
