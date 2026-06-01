from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from loushang.coding.commands.slash import split_slash_command
from loushang.runtime.commands import (
    CommandDef,
    CommandEffect,
    CommandEffectKind,
    CommandKind,
)

SessionCommandsProvider = Callable[[], Iterable[object]]


class CodingCommandCatalog:
    def __init__(self, *, session_commands: SessionCommandsProvider | None = None) -> None:
        self._session_commands = session_commands

    def commands(self) -> tuple[CommandDef, ...]:
        session_commands: list[CommandDef] = []
        session_names: set[str] = set()
        if self._session_commands is None:
            return tuple(_LOCAL_COMMANDS_BY_NAME.values())
        raw_commands = self._session_commands()
        if isinstance(raw_commands, Iterable):
            for raw_command in raw_commands:
                command = _session_command_def(raw_command)
                if command is not None and command.name not in session_names:
                    session_commands.append(command)
                    session_names.add(command.name)
        local_commands = tuple(
            command for name, command in _LOCAL_COMMANDS_BY_NAME.items() if name not in session_names
        )
        return (*session_commands, *local_commands)

    def effect_for_route(self, route: object, intent: object) -> CommandEffect | None:
        route_value = _route_value(route)
        command = _LOCAL_COMMANDS_BY_ROUTE_VALUE.get(route_value)
        if command is not None:
            return CommandEffect(kind=CommandEffectKind.LOCAL_UI, command=command)
        if route_value == "dispatch":
            text = _string_attr(intent, "text")
            if text is not None:
                return self._session_effect_for_text(text)
        return None

    def lookup(self, text: str) -> CommandDef | None:
        local_command = _local_command_for_text(text)
        if local_command is not None:
            return local_command
        session_effect = self._session_effect_for_text(text)
        if session_effect is None:
            return None
        return session_effect.command

    def _session_effect_for_text(self, text: str) -> CommandEffect | None:
        parsed = split_slash_command(text.strip())
        if parsed is None or self._session_commands is None:
            return None
        invocation_name, args = parsed
        command = self._session_command(invocation_name)
        if command is None:
            return None
        return CommandEffect(
            kind=CommandEffectKind.SESSION,
            command=command,
            payload={"invocation_name": invocation_name, "args": args},
        )

    def _session_command(self, invocation_name: str) -> CommandDef | None:
        normalized = invocation_name.removeprefix("/")
        raw_commands = self._session_commands()
        if not isinstance(raw_commands, Iterable):
            return None
        for raw_command in raw_commands:
            command = _session_command_def(raw_command)
            if command is None or command.name.removeprefix("/") != normalized:
                continue
            return command
        return None


def _local_command_for_text(text: str) -> CommandDef | None:
    parsed = split_slash_command(text.strip())
    if parsed is None:
        return None
    invocation_name, args = parsed
    name = invocation_name.removeprefix("/")
    command = _LOCAL_COMMANDS_BY_NAME.get(name)
    if command is None:
        return None
    if args and name not in _LOCAL_COMMANDS_ACCEPT_ARGS:
        return None
    return command


def _route_value(route: object) -> str:
    value = getattr(route, "value", route)
    return value if isinstance(value, str) else str(value)


def _string_attr(value: Any, name: str) -> str | None:
    raw = getattr(value, name, None)
    return raw if isinstance(raw, str) and raw else None


def _session_command_def(raw_command: object) -> CommandDef | None:
    name = _string_attr(raw_command, "invocation_name") or _string_attr(raw_command, "name")
    if name is None:
        return None
    normalized = name.removeprefix("/")
    return CommandDef(
        id=f"coding.session.{normalized}",
        name=normalized,
        kind=CommandKind.SESSION,
        description=_string_attr(raw_command, "description"),
        source=_string_attr(raw_command, "source"),
        argument_hint=_string_attr(raw_command, "argument_hint"),
    )


_LOCAL_COMMANDS_BY_ROUTE_VALUE: dict[str, CommandDef] = {
    "status": CommandDef(
        id="coding.ui.status",
        name="status",
        kind=CommandKind.LOCAL_UI,
        description="Show current status",
        source="local",
    ),
    "model_select": CommandDef(
        id="coding.ui.model",
        name="model",
        kind=CommandKind.LOCAL_UI,
        description="Select model",
        source="local",
    ),
    "models": CommandDef(
        id="coding.ui.models",
        name="models",
        kind=CommandKind.LOCAL_UI,
        description="Show available models",
        source="local",
    ),
    "command_select": CommandDef(
        id="coding.ui.command",
        name="command",
        kind=CommandKind.LOCAL_UI,
        description="Select command",
        source="local",
    ),
    "commands": CommandDef(
        id="coding.ui.commands",
        name="commands",
        kind=CommandKind.LOCAL_UI,
        description="Show commands",
        source="local",
    ),
    "hotkeys": CommandDef(
        id="coding.ui.hotkeys",
        name="hotkeys",
        kind=CommandKind.LOCAL_UI,
        description="Show keyboard shortcuts",
        source="local",
    ),
    "settings": CommandDef(
        id="coding.ui.settings",
        name="settings",
        kind=CommandKind.LOCAL_UI,
        description="Open settings",
        source="local",
    ),
    "statusline": CommandDef(
        id="coding.ui.statusline",
        name="statusline",
        kind=CommandKind.LOCAL_UI,
        description="Configure status line visibility",
        source="local",
    ),
    "terminal": CommandDef(
        id="coding.ui.terminal",
        name="terminal",
        kind=CommandKind.LOCAL_UI,
        description="Show terminal diagnostics",
        source="local",
    ),
}
_LOCAL_COMMANDS_BY_NAME: dict[str, CommandDef] = {
    command.name: command for command in _LOCAL_COMMANDS_BY_ROUTE_VALUE.values()
}
_LOCAL_COMMANDS_ACCEPT_ARGS = frozenset({"command", "commands", "model", "models", "statusline"})


__all__ = ["CodingCommandCatalog", "SessionCommandsProvider"]
