from __future__ import annotations

from pathlib import Path
from typing import Any

from loushang.coding.ui.command_list import coding_command_completion_provider
from loushang.coding.ui.model_list import available_model_completion_provider
from loushang.tui import (
    CombinedCompletionProvider,
    CompletionItem,
    CompletionProvider,
    PathCompletionProvider,
    SlashCommand,
    SlashCommandCompletionProvider,
)


async def complete_coding_input(session: Any, text: str) -> tuple[CompletionItem, ...]:
    provider = await coding_input_completion_provider(session, text)
    return tuple(provider.items)


async def coding_input_completion_provider(session: Any, text: str) -> CompletionProvider:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return CompletionProvider(())

    provider = await _slash_command_completion_provider(session)
    return CompletionProvider(provider.complete(text.lstrip()))


async def coding_inline_completion_provider(session: Any) -> Any:
    provider = await _slash_command_completion_provider(session)
    base_path = _session_completion_base_path(session)
    if base_path is None:
        return provider
    return CombinedCompletionProvider((provider, PathCompletionProvider(base_path=base_path, recursive=True)))


async def _slash_command_completion_provider(session: Any) -> SlashCommandCompletionProvider:
    command_provider = await coding_command_completion_provider(session)
    provider = await available_model_completion_provider(session)
    commands = [
        SlashCommand(
            name=item.value,
            label=item.display_label(),
            description=item.description,
            argument_provider=provider if item.value == "/model" else None,
            argument_group="Models" if item.value == "/model" else "",
        )
        for item in command_provider.items
    ]
    if any(command.name == "/quit" for command in commands) and not any(command.name == "/exit" for command in commands):
        commands.append(SlashCommand(name="exit", label="/exit", description="Quit loushang"))
    return SlashCommandCompletionProvider(tuple(commands))


def _session_completion_base_path(session: Any) -> Path | None:
    for manager_name in ("session_manager", "sessionManager"):
        manager = getattr(session, manager_name, None)
        get_cwd = getattr(manager, "get_cwd", None)
        if not callable(get_cwd):
            continue
        try:
            cwd = get_cwd()
        except Exception:
            continue
        if not cwd:
            continue
        path = Path(str(cwd)).expanduser()
        if path.is_dir():
            return path
    return None


__all__ = [
    "coding_inline_completion_provider",
    "coding_input_completion_provider",
    "complete_coding_input",
]
