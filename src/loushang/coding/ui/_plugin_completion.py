"""Coding-local Plugin command completion and conflict explanation."""

from __future__ import annotations

import inspect
from dataclasses import replace

from loushang.harnesstui.completion.host import PreparedCatalogCompletionHost
from loushang.tui import CompletionItem, CompletionProvider


def with_plugin_management_completion(
    host: PreparedCatalogCompletionHost, *, session: object
) -> PreparedCatalogCompletionHost:
    """Add one local `/plugins` preview without changing the shared catalog."""

    async def commands_with_local_preview() -> CompletionProvider:
        candidate = host.command_provider_source()
        provider = await candidate if inspect.isawaitable(candidate) else candidate
        if not isinstance(provider, CompletionProvider):
            raise TypeError("Coding command completion provider is invalid")
        list_commands = getattr(session, "list_commands", None)
        commands = list_commands() if callable(list_commands) else ()
        if inspect.isawaitable(commands):
            commands = await commands
        conflicts = any(
            getattr(command, "name", None) == "plugins" for command in commands
        )
        return CompletionProvider(
            tuple(item for item in provider.items if item.value != "/plugins")
            + (
                CompletionItem(
                    value="/plugins",
                    label="/plugins",
                    description=(
                        "Unavailable: Session command conflicts; use CLI"
                        if conflicts
                        else "Preview and manage Plugins (local)"
                    ),
                ),
            )
        )

    return replace(host, command_provider_source=commands_with_local_preview)
