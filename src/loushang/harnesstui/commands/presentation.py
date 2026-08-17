from __future__ import annotations

from collections.abc import Iterable

from loushang.tui import (
    CommandPalette,
    CompletionItem,
    CompletionProvider,
    SelectItem,
)


def format_commands(raw_commands: Iterable[object], *, query: str = "") -> str:
    """Render command descriptors without acquiring or executing commands."""

    lines = [format_command(command) for command in raw_commands]
    lines = [line for line in lines if line]
    stripped_query = query.strip()
    if stripped_query:
        needle = stripped_query.lower()
        lines = [line for line in lines if needle in line.lower()]

    if not lines:
        if stripped_query:
            return f"No commands match: {stripped_query}"
        return "No commands available."

    return "\n".join(["Commands:", *sorted(lines)])


def command_completion_provider(
    raw_commands: Iterable[object],
    *,
    local_last: bool = True,
) -> CompletionProvider:
    """Project duck-typed command descriptors into completion items."""

    items = [
        (item, command_source_priority(command))
        for command in raw_commands
        if (item := command_completion_item(command)) is not None
    ]
    if local_last:
        items.sort(key=lambda pair: (pair[1], pair[0].value))
    else:
        items.sort(key=lambda pair: pair[0].value)
    return CompletionProvider(tuple(item for item, _priority in items))


def command_palette(
    raw_commands: Iterable[object],
    *,
    title: str = "Commands",
) -> CommandPalette:
    provider = command_completion_provider(raw_commands)
    return CommandPalette.from_completion_provider(provider, title=title)


def command_palette_select_items(palette: CommandPalette) -> list[SelectItem]:
    """Project a command palette into the generic selection-surface model."""

    return [
        SelectItem(
            label=item.display_label(),
            value=item.value,
            description=item.description,
        )
        for item in palette.items
    ]


def format_command(command: object) -> str:
    name = _string_attr(command, "invocation_name") or _string_attr(command, "name")
    if name is None:
        return ""
    label = command_label(name, _string_attr(command, "argument_hint"))
    description = _string_attr(command, "description")
    source = _string_attr(command, "source")
    if description:
        label = f"{label} - {description}"
    if source:
        label = f"{label} ({source})"
    return label


def command_completion_item(command: object) -> CompletionItem | None:
    name = _string_attr(command, "invocation_name") or _string_attr(command, "name")
    if name is None:
        return None
    argument_hint = _string_attr(command, "argument_hint")
    description = _string_attr(command, "description") or ""
    source = _string_attr(command, "source")
    if source:
        description = f"{description} ({source})" if description else f"({source})"
    value = f"/{name}"
    return CompletionItem(
        value=value,
        label=command_label(name, argument_hint),
        description=description,
    )


def command_source_priority(command: object) -> int:
    return 1 if _string_attr(command, "source") == "local" else 0


def command_label(name: str, argument_hint: str | None) -> str:
    if argument_hint:
        return f"/{name} {argument_hint}"
    return f"/{name}"


def matching_command_items(
    provider: CompletionProvider,
    query: str,
) -> tuple[CompletionItem, ...]:
    needle = query.lower()
    matches = tuple(
        item for item in provider.items if command_item_matches(item, needle)
    )
    exact = tuple(
        item
        for item in matches
        if item.value.lower() == needle or item.display_label().lower() == needle
    )
    return exact or matches


def command_item_matches(item: CompletionItem, query: str) -> bool:
    needle = query.lower()
    haystacks = (item.value, item.display_label(), item.description)
    for haystack in haystacks:
        lowered = haystack.lower()
        if needle in lowered:
            return True
        if not needle.startswith("/") and needle in lowered.removeprefix("/"):
            return True
    return False


def _string_attr(value: object, name: str) -> str | None:
    raw = getattr(value, name, None)
    return raw if isinstance(raw, str) and raw else None


__all__ = [
    "command_completion_item",
    "command_completion_provider",
    "command_item_matches",
    "command_label",
    "command_palette",
    "command_palette_select_items",
    "command_source_priority",
    "format_command",
    "format_commands",
    "matching_command_items",
]
