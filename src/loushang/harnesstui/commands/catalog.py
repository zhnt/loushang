"""Conversation-host binding over the shared mixed command catalog."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
from typing import Any

from loushang.harness.commands import (
    DEFAULT_LOCAL_COMMANDS_PROFILE,
    CommandCatalog,
    CommandDef,
    CommandEffect,
    CommandEffectKind,
    LocalCommandCatalogProfile,
    MixedCommandCatalog,
    MixedCommandCatalogPorts,
    coerce_command_descriptor,
    command_def_from_descriptor,
)
from loushang.harnesstui.commands.source import materialize_command_items

SessionCommandsProvider = Callable[[], Iterable[object]]


class ConversationCommandCatalog:
    """Bind local and typed session commands to conversation host effects."""

    def __init__(
        self,
        *,
        profile: LocalCommandCatalogProfile = DEFAULT_LOCAL_COMMANDS_PROFILE,
        session_commands: SessionCommandsProvider | None = None,
        session_command_id_prefix: str = "harness.session",
        dispatch_route: str = "dispatch",
    ) -> None:
        self._session_commands = session_commands
        self._dispatch_route = dispatch_route
        self._catalog = MixedCommandCatalog(
            profile=profile,
            ports=MixedCommandCatalogPorts(
                session_catalog=(
                    self._session_catalog if session_commands is not None else None
                ),
                session_command=(
                    partial(
                        command_def_from_descriptor,
                        id_prefix=session_command_id_prefix,
                    )
                    if session_commands is not None
                    else None
                ),
            ),
        )

    def commands(self) -> tuple[CommandDef, ...]:
        return self._catalog.commands()

    def effect_for_route(
        self,
        route: object,
        intent: object,
    ) -> CommandEffect | None:
        route_value = getattr(route, "value", route)
        normalized_route = (
            route_value if isinstance(route_value, str) else str(route_value)
        )
        command = self._catalog.local_for_route(normalized_route)
        if command is not None:
            return CommandEffect(kind=CommandEffectKind.LOCAL_UI, command=command)
        if normalized_route != self._dispatch_route:
            return None
        text = getattr(intent, "text", None)
        if not isinstance(text, str) or not text:
            return None
        match = self._catalog.session_match(text)
        if match is None:
            return None
        return CommandEffect(
            kind=CommandEffectKind.SESSION,
            command=match.command,
            payload={
                "invocation_name": match.invocation_name,
                "args": match.args,
            },
        )

    def lookup(self, text: str) -> CommandDef | None:
        return self._catalog.lookup(text)

    def _session_catalog(self) -> CommandCatalog[Any]:
        if self._session_commands is None:
            return CommandCatalog()
        return CommandCatalog(
            descriptor
            for item in self._session_commands()
            if (descriptor := coerce_command_descriptor(item)) is not None
        )


async def snapshot_conversation_command_catalog(
    source: Callable[[], object] | None,
    *,
    profile: LocalCommandCatalogProfile = DEFAULT_LOCAL_COMMANDS_PROFILE,
    session_command_id_prefix: str = "harness.session",
) -> ConversationCommandCatalog:
    """Materialize a sync or async session source into an immutable catalog."""

    items = await materialize_command_items(source)
    descriptors = tuple(
        descriptor
        for item in items
        if (descriptor := coerce_command_descriptor(item)) is not None
    )
    return ConversationCommandCatalog(
        profile=profile,
        session_commands=lambda: descriptors,
        session_command_id_prefix=session_command_id_prefix,
    )


__all__ = [
    "ConversationCommandCatalog",
    "SessionCommandsProvider",
    "snapshot_conversation_command_catalog",
]
