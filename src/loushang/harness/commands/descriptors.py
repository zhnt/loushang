from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Generic, Literal, TypeVar, cast

from loushang.harness.resources.source import SourceInfo

SourceInfoT = TypeVar("SourceInfoT")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class CommandDescriptor(Generic[SourceInfoT]):
    """Product-neutral metadata for one command contribution."""

    name: str
    description: str | None
    source: str
    source_info: SourceInfoT | None = None
    invocation_name: str | None = None
    conflict_group: str | None = None
    argument_hint: str | None = None
    aliases: tuple[str, ...] = ()
    precedence: int = 0

    @property
    def effective_invocation_name(self) -> str:
        return normalize_command_name(self.invocation_name or self.name)


SlashCommandSource = Literal["builtin", "extension", "prompt", "skill"]
"""Common origins for commands surfaced by an Agent product session."""


CommandSourceInfo = SourceInfo


@dataclass(frozen=True)
class SessionCommandDescriptor(CommandDescriptor[SourceInfo[str]]):
    """A command descriptor backed by a standard resource source reference."""

    source: SlashCommandSource
    source_info: SourceInfo[str] = field()


@dataclass(frozen=True)
class SlashCommandInfo:
    """Compact display metadata for a session command."""

    name: str
    description: str | None
    source: SlashCommandSource
    source_info: SourceInfo[str]


@dataclass(frozen=True)
class CommandConflict(Generic[SourceInfoT]):
    invocation_name: str
    winner: CommandDescriptor[SourceInfoT]
    candidates: tuple[CommandDescriptor[SourceInfoT], ...]


class CommandCatalog(Generic[SourceInfoT]):
    """Resolve command names without imposing Product source semantics."""

    def __init__(self, commands: Iterable[CommandDescriptor[SourceInfoT]] = ()) -> None:
        self._descriptors = tuple(commands)
        candidates: dict[str, list[int]] = {}
        for index, descriptor in enumerate(self._descriptors):
            claimed_names = dict.fromkeys(
                (
                    descriptor.effective_invocation_name,
                    *(normalize_command_name(alias) for alias in descriptor.aliases),
                )
            )
            for name in claimed_names:
                if not name:
                    continue
                candidates.setdefault(name, []).append(index)
        self._candidates = {
            name: tuple(indexes) for name, indexes in candidates.items()
        }
        provisional_winners = {
            name: max(
                indexes, key=lambda index: (self._descriptors[index].precedence, -index)
            )
            for name, indexes in self._candidates.items()
        }
        active_indexes = {
            index
            for index, descriptor in enumerate(self._descriptors)
            if provisional_winners.get(descriptor.effective_invocation_name) == index
        }
        self._winners = {
            name: max(
                (index for index in indexes if index in active_indexes),
                key=lambda index: (self._descriptors[index].precedence, -index),
            )
            for name, indexes in self._candidates.items()
            if any(index in active_indexes for index in indexes)
        }

    def commands(self) -> tuple[CommandDescriptor[SourceInfoT], ...]:
        return tuple(
            descriptor
            for index, descriptor in enumerate(self._descriptors)
            if self._winners.get(descriptor.effective_invocation_name) == index
        )

    def lookup(self, invocation_name: str) -> CommandDescriptor[SourceInfoT] | None:
        winner = self._winners.get(normalize_command_name(invocation_name))
        return self._descriptors[winner] if winner is not None else None

    def conflicts(self) -> tuple[CommandConflict[SourceInfoT], ...]:
        conflicts: list[CommandConflict[SourceInfoT]] = []
        for invocation_name, indexes in self._candidates.items():
            if len(indexes) < 2:
                continue
            winner_index = self._winners.get(invocation_name)
            if winner_index is None:
                continue
            conflicts.append(
                CommandConflict(
                    invocation_name=invocation_name,
                    winner=self._descriptors[winner_index],
                    candidates=tuple(self._descriptors[index] for index in indexes),
                )
            )
        return tuple(conflicts)


@dataclass(frozen=True)
class ParsedSlashCommand:
    name: str
    args: str
    is_mcp: bool = False


def parse_slash_command(text: str) -> ParsedSlashCommand | None:
    if not text.startswith("/"):
        return None
    without_slash = text[1:].strip()
    parts = without_slash.split()
    if not parts:
        return None

    command_name = parts[0]
    is_mcp = len(parts) > 1 and parts[1] == "(MCP)"
    args_start = 2 if is_mcp else 1
    if is_mcp:
        command_name = f"{command_name} (MCP)"
    return ParsedSlashCommand(
        name=command_name,
        args=" ".join(parts[args_start:]),
        is_mcp=is_mcp,
    )


def split_slash_command(text: str) -> tuple[str, str] | None:
    parsed = parse_slash_command(text)
    if parsed is None:
        return None
    return parsed.name, parsed.args


def complete_slash_commands(
    prefix: str,
    commands: Iterable[CommandDescriptor[SourceInfoT]],
) -> list[dict[str, object]]:
    normalized_prefix = normalize_command_name(prefix)
    completions: list[dict[str, object]] = []
    for command in commands:
        invocation_names = dict.fromkeys(
            (
                command.effective_invocation_name,
                *(normalize_command_name(alias) for alias in command.aliases),
            )
        )
        for invocation_name in invocation_names:
            if not invocation_name:
                continue
            if normalized_prefix and not invocation_name.startswith(normalized_prefix):
                continue
            completion: dict[str, object] = {
                "value": f"/{invocation_name}",
                "label": f"/{invocation_name}",
                "description": command.description,
                "source": command.source,
                "kind": "command",
            }
            if command.conflict_group:
                completion["conflictGroup"] = command.conflict_group
            if command.argument_hint:
                completion["argumentHint"] = command.argument_hint
            completions.append(completion)
    return completions


def project_command_descriptor(
    command: object,
) -> dict[str, object] | None:
    """Project command metadata for generic CLI/resource listings.

    This is deliberately a transport-neutral, snake_case projection.  RPC and
    product-specific serializers may add their own wire fields, but a command
    listing should not need to know which product supplied the descriptor.
    Malformed or partially unavailable descriptors are ignored, matching the
    existing best-effort listing behavior.
    """

    name = _safe_command_getattr(command, "name", None)
    if not isinstance(name, str) or not name:
        return None
    description = _safe_command_getattr(command, "description", None)
    source = _safe_command_getattr(command, "source", None)
    source_info = _safe_command_getattr(command, "source_info", None)
    payload: dict[str, object] = {
        "name": name,
        "description": description if isinstance(description, str) else "",
        "source": source if isinstance(source, str) else "",
        "source_info": {
            "path": _safe_command_string(
                _safe_command_getattr(source_info, "path", "")
            )
        },
    }
    argument_hint = _safe_command_getattr(command, "argument_hint", None)
    if isinstance(argument_hint, str) and argument_hint:
        payload["argument_hint"] = argument_hint
    return payload


def _safe_command_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name)
    except Exception:
        return default


def _safe_command_string(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


@dataclass(frozen=True)
class CommandDispatchOutcome(Generic[ResultT]):
    handled: bool
    result: ResultT | None = None
    handler_name: str | None = None

    @classmethod
    def unhandled(cls) -> CommandDispatchOutcome[ResultT]:
        return cls(handled=False)

    @classmethod
    def handled_result(
        cls, result: ResultT | None = None
    ) -> CommandDispatchOutcome[ResultT]:
        return cls(handled=True, result=result)


CommandHandler = Callable[
    [ParsedSlashCommand],
    CommandDispatchOutcome[ResultT] | Awaitable[CommandDispatchOutcome[ResultT]],
]


@dataclass(frozen=True)
class CommandHandlerBinding(Generic[ResultT]):
    name: str
    handler: CommandHandler[ResultT]


def dispatch_command(
    invocation: ParsedSlashCommand,
    handlers: Iterable[CommandHandlerBinding[ResultT]],
) -> CommandDispatchOutcome[ResultT]:
    """Dispatch through synchronous handlers until one claims the invocation."""

    for binding in handlers:
        outcome = binding.handler(invocation)
        if inspect.isawaitable(outcome):
            if inspect.iscoroutine(outcome):
                outcome.close()
            raise TypeError(
                f'Command handler "{binding.name}" returned an awaitable; '
                "use dispatch_command_async()."
            )
        validated = cast(
            CommandDispatchOutcome[ResultT],
            _validated_outcome(outcome, binding.name),
        )
        if validated.handled:
            return _with_handler_name(validated, binding.name)
    return CommandDispatchOutcome.unhandled()


async def dispatch_command_async(
    invocation: ParsedSlashCommand,
    handlers: Iterable[CommandHandlerBinding[ResultT]],
) -> CommandDispatchOutcome[ResultT]:
    """Dispatch through synchronous or asynchronous handlers in caller order."""

    for binding in handlers:
        outcome = binding.handler(invocation)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        validated = cast(
            CommandDispatchOutcome[ResultT],
            _validated_outcome(outcome, binding.name),
        )
        if validated.handled:
            return _with_handler_name(validated, binding.name)
    return CommandDispatchOutcome.unhandled()


def normalize_command_name(value: str) -> str:
    return value.strip().removeprefix("/")


def _validated_outcome(
    value: object, handler_name: str
) -> CommandDispatchOutcome[object]:
    if not isinstance(value, CommandDispatchOutcome):
        raise TypeError(
            f'Command handler "{handler_name}" must return CommandDispatchOutcome.'
        )
    return cast(CommandDispatchOutcome[object], value)


def _with_handler_name(
    outcome: CommandDispatchOutcome[ResultT],
    handler_name: str,
) -> CommandDispatchOutcome[ResultT]:
    if outcome.handler_name is not None:
        return outcome
    return replace(outcome, handler_name=handler_name)


__all__ = [
    "CommandCatalog",
    "CommandConflict",
    "CommandDescriptor",
    "CommandDispatchOutcome",
    "CommandHandler",
    "CommandHandlerBinding",
    "CommandSourceInfo",
    "ParsedSlashCommand",
    "SessionCommandDescriptor",
    "SlashCommandInfo",
    "SlashCommandSource",
    "complete_slash_commands",
    "dispatch_command",
    "dispatch_command_async",
    "normalize_command_name",
    "parse_slash_command",
    "split_slash_command",
]
