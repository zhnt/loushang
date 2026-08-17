from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar, cast

from loushang.harnesstui.commands.presentation import (
    command_completion_item,
    command_item_matches,
    command_source_priority,
)
from loushang.tui import CommandPalette, CompletionItem, CompletionProvider

CommandInteractionKind = Literal[
    "list",
    "selected",
    "empty",
    "ambiguous",
    "cancelled",
]
CommandPaletteChooser = Callable[
    [CommandPalette],
    Awaitable[str | None] | str | None,
]
_CommandDescriptorT = TypeVar("_CommandDescriptorT")


@dataclass(frozen=True, slots=True)
class CommandInteractionPresentationCopy(Generic[_CommandDescriptorT]):
    """Product wording and item projection for a command resolution."""

    list_items: Callable[[tuple[_CommandDescriptorT, ...]], str]
    item_text: Callable[[_CommandDescriptorT], str]
    cancelled: str
    empty: str
    no_match: Callable[[str], str]
    ambiguous_title: str
    ambiguous_hint: str
    selected_prefix: str


@dataclass(frozen=True, slots=True)
class CommandInteractionSnapshot(Generic[_CommandDescriptorT]):
    """A product-prepared, immutable view of available command descriptors.

    Command descriptors remain opaque to this layer.  Presentation only reads
    the duck-typed fields supported by :mod:`commands.presentation`; the
    selected descriptor is returned unchanged to the product adapter.
    """

    items: tuple[_CommandDescriptorT, ...]
    title: str = "Commands"
    local_last: bool = True


@dataclass(frozen=True, slots=True)
class CommandInteractionResult(Generic[_CommandDescriptorT]):
    """Structural outcome of a command catalog interaction."""

    kind: CommandInteractionKind
    query: str = ""
    item: _CommandDescriptorT | None = None
    matches: tuple[_CommandDescriptorT, ...] = ()
    palette: CommandPalette | None = None


@dataclass(frozen=True, slots=True)
class _CommandEntry(Generic[_CommandDescriptorT]):
    item: _CommandDescriptorT
    completion: CompletionItem
    position: int
    source_priority: int


def resolve_command_interaction(
    snapshot: CommandInteractionSnapshot[_CommandDescriptorT],
    *,
    query: str = "",
) -> CommandInteractionResult[_CommandDescriptorT]:
    """Resolve a command query without acquiring or executing a command."""

    entries = _command_entries(snapshot)
    palette = _command_palette(entries, title=snapshot.title)
    stripped_query = query.strip()
    if not entries:
        return CommandInteractionResult(
            kind="empty",
            query=stripped_query,
            palette=palette,
        )
    if not stripped_query:
        return CommandInteractionResult(
            kind="list",
            matches=tuple(entry.item for entry in entries),
            palette=palette,
        )

    matches = _matching_entries(entries, stripped_query)
    if not matches:
        return CommandInteractionResult(
            kind="empty",
            query=stripped_query,
            palette=palette,
        )
    if len(matches) > 1:
        return CommandInteractionResult(
            kind="ambiguous",
            query=stripped_query,
            matches=tuple(entry.item for entry in matches),
            palette=palette,
        )
    return CommandInteractionResult(
        kind="selected",
        query=stripped_query,
        item=matches[0].item,
        matches=(matches[0].item,),
        palette=palette,
    )


async def run_command_interaction(
    snapshot: CommandInteractionSnapshot[_CommandDescriptorT],
    *,
    query: str = "",
    choose: CommandPaletteChooser | None = None,
) -> CommandInteractionResult[_CommandDescriptorT]:
    """Resolve a query, optionally asking a sync or async palette chooser."""

    initial = resolve_command_interaction(snapshot, query=query)
    if query.strip() or choose is None:
        return initial

    palette = cast(CommandPalette, initial.palette)
    selected = choose(palette)
    if inspect.isawaitable(selected):
        selected = await selected
    if selected is None:
        return CommandInteractionResult(
            kind="cancelled",
            matches=initial.matches,
            palette=palette,
        )
    return resolve_command_interaction(snapshot, query=selected)


def present_command_interaction(
    result: CommandInteractionResult[_CommandDescriptorT],
    *,
    copy: CommandInteractionPresentationCopy[_CommandDescriptorT],
) -> str:
    """Present one structural command resolution using product-owned copy."""

    if result.kind == "list":
        return copy.list_items(result.matches)
    if result.kind == "cancelled":
        return copy.cancelled
    if result.kind == "empty":
        return copy.no_match(result.query) if result.query else copy.empty
    if result.kind == "ambiguous":
        return "\n".join(
            (
                copy.ambiguous_title,
                *(f"  {copy.item_text(item)}" for item in result.matches),
                copy.ambiguous_hint,
            )
        )
    if result.item is not None:
        return f"{copy.selected_prefix}{copy.item_text(result.item)}"
    return copy.empty


def _command_entries(
    snapshot: CommandInteractionSnapshot[_CommandDescriptorT],
) -> tuple[_CommandEntry[_CommandDescriptorT], ...]:
    entries = [
        _CommandEntry(
            item=item,
            completion=completion,
            position=position,
            source_priority=command_source_priority(item),
        )
        for position, item in enumerate(snapshot.items)
        if (completion := command_completion_item(item)) is not None
    ]
    if snapshot.local_last:
        entries.sort(
            key=lambda entry: (
                entry.source_priority,
                entry.completion.value,
                entry.position,
            )
        )
    else:
        entries.sort(key=lambda entry: (entry.completion.value, entry.position))
    return tuple(entries)


def _command_palette(
    entries: tuple[_CommandEntry[_CommandDescriptorT], ...],
    *,
    title: str,
) -> CommandPalette:
    provider = CompletionProvider(tuple(entry.completion for entry in entries))
    return CommandPalette.from_completion_provider(provider, title=title)


def _matching_entries(
    entries: tuple[_CommandEntry[_CommandDescriptorT], ...],
    query: str,
) -> tuple[_CommandEntry[_CommandDescriptorT], ...]:
    needle = query.lower()
    matches = tuple(
        entry for entry in entries if command_item_matches(entry.completion, needle)
    )
    exact = tuple(
        entry
        for entry in matches
        if entry.completion.value.lower() == needle
        or entry.completion.display_label().lower() == needle
    )
    return exact or matches


__all__ = [
    "CommandInteractionKind",
    "CommandInteractionPresentationCopy",
    "CommandInteractionResult",
    "CommandInteractionSnapshot",
    "CommandPaletteChooser",
    "present_command_interaction",
    "resolve_command_interaction",
    "run_command_interaction",
]
