from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loushang.harnesstui.commands.interaction import (
    CommandInteractionPresentationCopy,
    CommandInteractionSnapshot,
    present_command_interaction,
    resolve_command_interaction,
    run_command_interaction,
)
from loushang.harnesstui.commands.presentation import (
    command_completion_item,
    command_completion_provider,
    matching_command_items,
)
from loushang.tui import CommandPalette


@dataclass(frozen=True)
class _Command:
    name: str
    description: str = ""
    source: str = "extension"
    invocation_name: str = ""
    argument_hint: str = ""


def _snapshot() -> tuple[CommandInteractionSnapshot[_Command], tuple[_Command, ...]]:
    commands = (
        _Command(
            name="review",
            invocation_name="review:pr",
            argument_hint="<PR-URL>",
            description="Review a pull request",
        ),
        _Command(name="restart", description="Restart a service"),
        _Command(name="settings", description="Open settings", source="local"),
    )
    return CommandInteractionSnapshot(commands, title="Actions"), commands


def test_command_interaction_lists_projectable_opaque_items() -> None:
    snapshot, commands = _snapshot()
    palette_order = (commands[1], commands[0], commands[2])

    result = resolve_command_interaction(snapshot)

    assert result.kind == "list"
    assert result.query == ""
    assert result.item is None
    assert result.matches == palette_order
    assert result.palette is not None
    assert result.palette.title == "Actions"
    assert tuple(item.value for item in result.palette.items) == (
        "/restart",
        "/review:pr",
        "/settings",
    )
    assert all(
        actual is expected for actual, expected in zip(result.matches, palette_order)
    )


def test_command_interaction_reports_empty_snapshot_or_query() -> None:
    empty = resolve_command_interaction(
        CommandInteractionSnapshot((object(),)),
        query="  absent  ",
    )
    snapshot, _commands = _snapshot()
    missing = resolve_command_interaction(snapshot, query="absent")

    assert empty.kind == "empty"
    assert empty.query == "absent"
    assert empty.matches == ()
    assert empty.palette == CommandPalette((), title="Commands")
    assert missing.kind == "empty"
    assert missing.query == "absent"


def test_command_interaction_resolves_unique_query_to_original_item() -> None:
    snapshot, commands = _snapshot()

    result = resolve_command_interaction(snapshot, query="  /REVIEW:PR  ")

    assert result.kind == "selected"
    assert result.query == "/REVIEW:PR"
    assert result.item is commands[0]
    assert result.matches == (commands[0],)


def test_command_interaction_reports_ambiguous_query_in_palette_order() -> None:
    snapshot, commands = _snapshot()

    result = resolve_command_interaction(snapshot, query="re")

    assert result.kind == "ambiguous"
    assert result.query == "re"
    assert result.item is None
    assert result.matches == (commands[1], commands[0])


def test_command_interaction_matches_canonical_presentation_contracts() -> None:
    snapshot, _commands = _snapshot()

    for local_last in (False, True):
        ordered_snapshot = CommandInteractionSnapshot(
            snapshot.items,
            title=snapshot.title,
            local_last=local_last,
        )
        provider = command_completion_provider(
            ordered_snapshot.items,
            local_last=local_last,
        )
        result = resolve_command_interaction(ordered_snapshot)

        assert result.palette == CommandPalette.from_completion_provider(
            provider,
            title=ordered_snapshot.title,
        )
        projected = tuple(command_completion_item(item) for item in result.matches)
        assert projected == provider.items

    provider = command_completion_provider(snapshot.items)
    for query in ("re", "/review:pr", "service", "missing"):
        result = resolve_command_interaction(snapshot, query=query)

        projected = tuple(command_completion_item(item) for item in result.matches)
        assert projected == matching_command_items(provider, query)


def test_command_interaction_uses_sync_chooser_and_returns_original_item() -> None:
    snapshot, commands = _snapshot()
    seen: list[CommandPalette] = []

    def choose(palette: CommandPalette) -> str:
        seen.append(palette)
        return "/settings"

    result = asyncio.run(run_command_interaction(snapshot, choose=choose))

    assert seen == [result.palette]
    assert result.kind == "selected"
    assert result.item is commands[2]


def test_command_interaction_reports_cancelled_chooser() -> None:
    snapshot, commands = _snapshot()

    result = asyncio.run(
        run_command_interaction(snapshot, choose=lambda _palette: None)
    )

    assert result.kind == "cancelled"
    assert result.item is None
    assert result.matches == (commands[1], commands[0], commands[2])
    assert result.palette is not None


def test_empty_command_interaction_still_invokes_chooser() -> None:
    snapshot = CommandInteractionSnapshot(())
    seen: list[CommandPalette] = []

    def cancel(palette: CommandPalette) -> None:
        seen.append(palette)

    cancelled = asyncio.run(run_command_interaction(snapshot, choose=cancel))
    missing = asyncio.run(
        run_command_interaction(snapshot, choose=lambda _palette: "/missing")
    )

    assert seen == [CommandPalette((), title="Commands")]
    assert cancelled.kind == "cancelled"
    assert missing.kind == "empty"
    assert missing.query == "/missing"


def test_command_interaction_awaits_async_chooser() -> None:
    snapshot, commands = _snapshot()

    async def choose(_palette: CommandPalette) -> str:
        await asyncio.sleep(0)
        return "/restart"

    result = asyncio.run(run_command_interaction(snapshot, choose=choose))

    assert result.kind == "selected"
    assert result.item is commands[1]


def test_command_interaction_query_does_not_invoke_chooser() -> None:
    snapshot, commands = _snapshot()

    def choose(_palette: CommandPalette) -> str:
        raise AssertionError("chooser should only run for an empty query")

    result = asyncio.run(
        run_command_interaction(snapshot, query="settings", choose=choose)
    )

    assert result.kind == "selected"
    assert result.item is commands[2]


def test_command_interaction_presenter_uses_only_product_supplied_copy() -> None:
    snapshot, _commands = _snapshot()
    copy = CommandInteractionPresentationCopy[_Command](
        list_items=lambda items: "list:" + ",".join(item.name for item in items),
        item_text=lambda item: item.name,
        cancelled="cancelled-copy",
        empty="empty-copy",
        no_match=lambda query: f"missing-copy:{query}",
        ambiguous_title="ambiguous-copy",
        ambiguous_hint="hint-copy",
        selected_prefix="selected-copy:",
    )

    listed = resolve_command_interaction(snapshot)
    selected = resolve_command_interaction(snapshot, query="settings")
    ambiguous = resolve_command_interaction(snapshot, query="re")
    missing = resolve_command_interaction(snapshot, query="missing")
    empty = resolve_command_interaction(CommandInteractionSnapshot(()))
    cancelled = asyncio.run(
        run_command_interaction(snapshot, choose=lambda _palette: None)
    )

    assert present_command_interaction(listed, copy=copy).startswith("list:restart")
    assert present_command_interaction(selected, copy=copy) == "selected-copy:settings"
    assert present_command_interaction(ambiguous, copy=copy) == (
        "ambiguous-copy\n  restart\n  review\nhint-copy"
    )
    assert present_command_interaction(missing, copy=copy) == "missing-copy:missing"
    assert present_command_interaction(empty, copy=copy) == "empty-copy"
    assert present_command_interaction(cancelled, copy=copy) == "cancelled-copy"
