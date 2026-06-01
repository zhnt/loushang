from __future__ import annotations

import asyncio
from types import SimpleNamespace


class _Session:
    def list_commands(self) -> list[object]:
        return [
            SimpleNamespace(name="hotkeys", description="Show all keyboard shortcuts", source="builtin"),
            SimpleNamespace(
                name="deploy",
                invocation_name="deploy:1",
                description="Deploy app",
                source="extension",
            ),
        ]


class _ArgumentHintSession:
    def list_commands(self) -> list[object]:
        return [
            SimpleNamespace(
                name="review",
                description="Review pull request",
                source="prompt",
                argument_hint="<PR-URL>",
            ),
        ]


class _BuiltinSession:
    def list_commands(self) -> list[object]:
        from loushang.coding.session.builtin_commands import (
            list_builtin_command_descriptors,
        )

        return list_builtin_command_descriptors()


def test_format_session_commands_lists_sorted_commands() -> None:
    from loushang.coding.ui.command_list import format_session_commands

    text = asyncio.run(format_session_commands(_Session()))

    assert text == (
        "Commands:\n"
        "/deploy:1 - Deploy app (extension)\n"
        "/hotkeys - Show all keyboard shortcuts (builtin)"
    )


def test_format_session_commands_filters_by_query() -> None:
    from loushang.coding.ui.command_list import format_session_commands

    text = asyncio.run(format_session_commands(_Session(), query="hot"))

    assert text == "Commands:\n/hotkeys - Show all keyboard shortcuts (builtin)"


def test_format_session_commands_reports_empty_matches() -> None:
    from loushang.coding.ui.command_list import format_session_commands

    text = asyncio.run(format_session_commands(_Session(), query="missing"))

    assert text == "No commands match: missing"


def test_format_session_commands_includes_argument_hint() -> None:
    from loushang.coding.ui.command_list import format_session_commands

    text = asyncio.run(format_session_commands(_ArgumentHintSession()))

    assert text == "Commands:\n/review <PR-URL> - Review pull request (prompt)"


def test_session_command_completion_provider_exposes_structured_items() -> None:
    from loushang.coding.ui.command_list import session_command_completion_provider
    from loushang.tui import CompletionItem, CompletionProvider

    provider = asyncio.run(session_command_completion_provider(_Session()))

    assert provider == CompletionProvider(
        (
            CompletionItem(value="/deploy:1", label="/deploy:1", description="Deploy app (extension)"),
            CompletionItem(
                value="/hotkeys",
                label="/hotkeys",
                description="Show all keyboard shortcuts (builtin)",
            ),
        )
    )


def test_session_command_completion_provider_uses_argument_hint_in_label() -> None:
    from loushang.coding.ui.command_list import session_command_completion_provider
    from loushang.tui import CompletionItem, CompletionProvider

    provider = asyncio.run(session_command_completion_provider(_ArgumentHintSession()))

    assert provider == CompletionProvider(
        (
            CompletionItem(
                value="/review",
                label="/review <PR-URL>",
                description="Review pull request (prompt)",
            ),
        )
    )


def test_format_coding_commands_includes_local_and_session_commands() -> None:
    from loushang.coding.ui.command_list import format_coding_commands

    text = asyncio.run(format_coding_commands(_Session(), query="terminal"))

    assert text == "Commands:\n/terminal - Show terminal diagnostics (local)"


def test_coding_command_completion_provider_includes_local_commands() -> None:
    from loushang.coding.ui.command_list import coding_command_completion_provider
    from loushang.tui import CompletionItem

    provider = asyncio.run(coding_command_completion_provider(_Session()))

    assert CompletionItem(
        value="/settings",
        label="/settings",
        description="Open settings (local)",
    ) in provider.items
    assert len([item for item in provider.items if item.value == "/hotkeys"]) == 1


def test_builtin_terminal_command_is_visible_in_command_completion_and_list() -> None:
    from loushang.coding.ui.command_list import (
        format_session_commands,
        session_command_completion_provider,
    )
    from loushang.tui import CompletionItem

    text = asyncio.run(format_session_commands(_BuiltinSession(), query="terminal"))
    provider = asyncio.run(session_command_completion_provider(_BuiltinSession()))

    assert text == "Commands:\n/terminal - Show terminal capabilities and protocol diagnostics (builtin)"
    assert CompletionItem(
        value="/terminal",
        label="/terminal",
        description="Show terminal capabilities and protocol diagnostics (builtin)",
    ) in provider.items


def test_session_command_palette_reuses_structured_command_items() -> None:
    from loushang.coding.ui.command_list import session_command_palette
    from loushang.tui import CommandPalette, CommandPaletteItem

    palette = asyncio.run(session_command_palette(_Session(), title="Commands"))

    assert palette == CommandPalette(
        items=(
            CommandPaletteItem(value="/deploy:1", label="/deploy:1", description="Deploy app (extension)"),
            CommandPaletteItem(
                value="/hotkeys",
                label="/hotkeys",
                description="Show all keyboard shortcuts (builtin)",
            ),
        ),
        title="Commands",
    )


def test_select_session_command_uses_palette_when_query_is_empty() -> None:
    from loushang.coding.ui.command_list import select_session_command
    from loushang.tui import CommandPalette

    seen: list[CommandPalette] = []

    async def choose(palette: CommandPalette) -> str:
        seen.append(palette)
        return "/hotkeys"

    result = asyncio.run(select_session_command(_Session(), choose=choose))

    assert result == "Command selected: /hotkeys"
    assert seen and seen[0].title == "Commands"


def test_select_session_command_filters_unique_match() -> None:
    from loushang.coding.ui.command_list import select_session_command

    result = asyncio.run(select_session_command(_Session(), query="hot"))

    assert result == "Command selected: /hotkeys"


def test_select_session_command_reports_multiple_matches() -> None:
    from loushang.coding.ui.command_list import select_session_command

    result = asyncio.run(select_session_command(_Session(), query="/"))

    assert result == "Multiple commands match:\n  /deploy:1\n  /hotkeys\nUse /command <full command> to select one."


def test_select_session_command_reports_cancelled_palette() -> None:
    from loushang.coding.ui.command_list import select_session_command

    result = asyncio.run(select_session_command(_Session(), choose=lambda _palette: None))

    assert result == "Command selection cancelled."
