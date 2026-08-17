from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from loushang.harnesstui.commands.catalog import (
    snapshot_conversation_command_catalog,
)
from loushang.harnesstui.commands.presentation import command_completion_provider
from loushang.harnesstui.selection.binding import (
    available_session_model_completion_provider,
)
from loushang.tui import (
    CombinedCompletionProvider,
    CompletionItem,
    CompletionProvider,
    PathCompletionProvider,
    SlashCommand,
    SlashCommandCompletionProvider,
)

CompletionProviderSource = Callable[
    [], CompletionProvider | Awaitable[CompletionProvider]
]


@dataclass(frozen=True, slots=True)
class CatalogCompletionProfile:
    """Product policy and wording for prepared catalog completion."""

    model_command_value: str
    model_argument_group: str


@dataclass(frozen=True, slots=True)
class PreparedCatalogCompletionHost:
    """Build slash and inline completion without access to product runtime data."""

    command_provider_source: CompletionProviderSource
    model_provider_source: CompletionProviderSource
    profile: CatalogCompletionProfile

    async def complete(self, text: str) -> tuple[CompletionItem, ...]:
        provider = await self.input_provider(text)
        return tuple(provider.items)

    async def input_provider(self, text: str) -> CompletionProvider:
        if not text.strip().startswith("/"):
            return CompletionProvider(())
        provider = await self.slash_provider()
        return CompletionProvider(provider.complete(text.lstrip()))

    async def inline_provider(
        self,
        *,
        base_path: Path | None = None,
    ) -> SlashCommandCompletionProvider | CombinedCompletionProvider:
        provider = await self.slash_provider()
        if base_path is None:
            return provider
        return CombinedCompletionProvider(
            (
                provider,
                PathCompletionProvider(base_path=base_path, recursive=True),
            )
        )

    async def slash_provider(self) -> SlashCommandCompletionProvider:
        command_provider = await _resolve_provider(self.command_provider_source)
        model_provider = await _resolve_provider(self.model_provider_source)
        commands = [
            SlashCommand(
                name=item.value,
                label=item.display_label(),
                description=item.description,
                argument_provider=(
                    model_provider
                    if item.value == self.profile.model_command_value
                    else None
                ),
                argument_group=(
                    self.profile.model_argument_group
                    if item.value == self.profile.model_command_value
                    else ""
                ),
            )
            for item in command_provider.items
        ]
        return SlashCommandCompletionProvider(tuple(commands))


def build_session_catalog_completion_host(
    session: object,
    *,
    profile: CatalogCompletionProfile,
) -> PreparedCatalogCompletionHost:
    """Bind a standard session command/model catalog to the completion host."""

    return PreparedCatalogCompletionHost(
        command_provider_source=lambda: _session_command_provider(session),
        model_provider_source=lambda: available_session_model_completion_provider(
            session
        ),
        profile=profile,
    )


async def _session_command_provider(session: object) -> CompletionProvider:
    getter = getattr(session, "list_commands", None)
    catalog = await snapshot_conversation_command_catalog(
        getter if callable(getter) else None
    )
    return command_completion_provider(catalog.commands())


async def _resolve_provider(source: CompletionProviderSource) -> CompletionProvider:
    provider = source()
    if inspect.isawaitable(provider):
        return await provider
    return provider


__all__ = [
    "CatalogCompletionProfile",
    "CompletionProviderSource",
    "PreparedCatalogCompletionHost",
    "build_session_catalog_completion_host",
]
