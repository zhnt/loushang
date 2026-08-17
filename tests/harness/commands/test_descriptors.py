from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.harness.commands import (
    CommandCatalog,
    CommandDescriptor,
    CommandDispatchOutcome,
    CommandHandlerBinding,
    CommandSourceInfo,
    SessionCommandDescriptor,
    complete_slash_commands,
    dispatch_command,
    dispatch_command_async,
    parse_slash_command,
)


def _command(
    name: str,
    *,
    source: str,
    precedence: int = 0,
    aliases: tuple[str, ...] = (),
    invocation_name: str | None = None,
    conflict_group: str | None = None,
    argument_hint: str | None = None,
) -> CommandDescriptor[str]:
    return CommandDescriptor(
        name=name,
        description=f"{source} {name}",
        source=source,
        source_info=f"{source}:{name}",
        precedence=precedence,
        aliases=aliases,
        invocation_name=invocation_name,
        conflict_group=conflict_group,
        argument_hint=argument_hint,
    )


def test_command_catalog_resolves_alias_conflict_and_precedence() -> None:
    resource = _command("report", source="resource", precedence=10)
    builtin = _command(
        "report",
        source="builtin",
        precedence=20,
        aliases=("summary",),
    )
    extension = _command(
        "deploy",
        source="extension",
        precedence=30,
        invocation_name="deploy:1",
        conflict_group="deploy",
    )

    catalog = CommandCatalog((resource, builtin, extension))

    assert catalog.commands() == (builtin, extension)
    assert catalog.lookup("/report") is builtin
    assert catalog.lookup("summary") is builtin
    assert catalog.lookup("deploy:1") is extension
    assert catalog.lookup("missing") is None
    conflicts = catalog.conflicts()
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.invocation_name == "report"
    assert conflict.winner is builtin
    assert conflict.candidates == (resource, builtin)


def test_command_catalog_uses_registration_order_as_equal_precedence_tiebreak() -> None:
    first = _command("review", source="first")
    second = _command("review", source="second")

    catalog = CommandCatalog((first, second))

    assert catalog.commands() == (first,)
    assert catalog.lookup("review") is first


def test_command_catalog_deactivates_aliases_when_primary_command_loses() -> None:
    shadowed = _command("review", source="resource", aliases=("inspect",))
    winner = _command("review", source="builtin", precedence=10)

    catalog = CommandCatalog((shadowed, winner))

    assert catalog.commands() == (winner,)
    assert catalog.lookup("review") is winner
    assert catalog.lookup("inspect") is None


def test_slash_parser_preserves_mcp_marker_compatibility() -> None:
    parsed = parse_slash_command("/mcp__ide__diagnostics (MCP) current file")

    assert parsed is not None
    assert (parsed.name, parsed.args, parsed.is_mcp) == (
        "mcp__ide__diagnostics (MCP)",
        "current file",
        True,
    )
    assert parse_slash_command("plain text") is None
    assert parse_slash_command("/") is None


def test_completion_projects_descriptor_metadata() -> None:
    commands = (
        _command(
            "review",
            source="prompt",
            conflict_group="review",
            argument_hint="<PR-URL>",
        ),
        _command("deploy", source="extension"),
    )

    assert complete_slash_commands("/re", commands) == [
        {
            "value": "/review",
            "label": "/review",
            "description": "prompt review",
            "source": "prompt",
            "kind": "command",
            "conflictGroup": "review",
            "argumentHint": "<PR-URL>",
        }
    ]
    assert complete_slash_commands(
        "/inspect", (_command("review", source="prompt", aliases=("inspect",)),)
    ) == [
        {
            "value": "/inspect",
            "label": "/inspect",
            "description": "prompt review",
            "source": "prompt",
            "kind": "command",
        }
    ]


def test_session_command_descriptor_is_a_neutral_resource_backed_contract() -> None:
    descriptor = SessionCommandDescriptor(
        name="review",
        description="Review the current draft",
        source="prompt",
        source_info=CommandSourceInfo(path="/tmp/prompts/review.md"),
    )

    assert isinstance(descriptor, CommandDescriptor)
    assert descriptor.source_info.path == "/tmp/prompts/review.md"

    module_path = (
        Path(__file__).parents[3] / "src/loushang/harness/commands/descriptors.py"
    )
    assert "loushang.coding" not in module_path.read_text(encoding="utf-8")


def test_sync_dispatch_stops_at_first_handled_outcome() -> None:
    calls: list[tuple[str, str]] = []
    invocation = parse_slash_command("/research semiconductors")
    assert invocation is not None

    def extension(command):
        calls.append(("extension", command.args))
        return CommandDispatchOutcome.unhandled()

    def builtin(command):
        calls.append(("builtin", command.args))
        return CommandDispatchOutcome.handled_result({"report": command.args})

    def resource(command):
        calls.append(("resource", command.args))
        return CommandDispatchOutcome.handled_result("not reached")

    outcome = dispatch_command(
        invocation,
        (
            CommandHandlerBinding("extension", extension),
            CommandHandlerBinding("builtin", builtin),
            CommandHandlerBinding("resource", resource),
        ),
    )

    assert outcome.handled is True
    assert outcome.handler_name == "builtin"
    assert outcome.result == {"report": "semiconductors"}
    assert calls == [("extension", "semiconductors"), ("builtin", "semiconductors")]


def test_async_dispatch_accepts_sync_and_async_opaque_handlers_in_order() -> None:
    calls: list[str] = []
    invocation = parse_slash_command("/design landing-page")
    assert invocation is not None

    def extension(_command):
        calls.append("extension")
        return CommandDispatchOutcome.unhandled()

    async def product(command):
        await asyncio.sleep(0)
        calls.append("product")
        return CommandDispatchOutcome.handled_result((command.name, command.args))

    outcome = asyncio.run(
        dispatch_command_async(
            invocation,
            (
                CommandHandlerBinding("extension", extension),
                CommandHandlerBinding("product", product),
            ),
        )
    )

    assert outcome == CommandDispatchOutcome(
        handled=True,
        result=("design", "landing-page"),
        handler_name="product",
    )
    assert calls == ["extension", "product"]
