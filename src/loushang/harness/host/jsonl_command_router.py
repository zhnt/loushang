"""Explicit command routing for line-oriented JSON product protocols."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from loushang.harness.host.jsonl_command_host import JsonlCommand, JsonlCommandPort

JsonlCommandHandler = Callable[[JsonlCommand], Awaitable[None] | None]
JsonlUnsupportedCommandHandler = Callable[[JsonlCommand], Awaitable[None] | None]


@dataclass(frozen=True)
class JsonlCommandRoute:
    """A named command handler owned by an injected Product protocol."""

    command_type: str
    handler: JsonlCommandHandler


class JsonlCommandRouter(JsonlCommandPort):
    """Dispatch validated JSONL commands through an explicit immutable registry.

    The router deliberately has no request validation or response schema.  It
    only makes a Product's supported command surface explicit and delegates an
    unknown command to the Product's compatibility projection.
    """

    def __init__(
        self,
        *,
        routes: Iterable[JsonlCommandRoute],
        on_unsupported: JsonlUnsupportedCommandHandler,
    ) -> None:
        handlers: dict[str, JsonlCommandHandler] = {}
        for route in routes:
            if not route.command_type:
                raise ValueError("JSONL command route type must be non-empty")
            if route.command_type in handlers:
                raise ValueError(
                    f"duplicate JSONL command route: {route.command_type!r}"
                )
            handlers[route.command_type] = route.handler
        self._handlers = handlers
        self._on_unsupported = on_unsupported

    @property
    def command_types(self) -> frozenset[str]:
        """Return the fixed set of registered command types."""

        return frozenset(self._handlers)

    async def handle_jsonl_command(self, command: JsonlCommand) -> None:
        """Dispatch one validated command or delegate its fallback projection."""

        handler = self._handlers.get(command.command_type)
        if handler is None:
            result = self._on_unsupported(command)
        else:
            result = handler(command)
        if result is not None:
            await result


__all__ = [
    "JsonlCommandHandler",
    "JsonlCommandRoute",
    "JsonlCommandRouter",
    "JsonlUnsupportedCommandHandler",
]
