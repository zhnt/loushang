"""Reusable strict-JSON command host for line-oriented product protocols."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TextIO, cast

from loushang.harness.host._stdio import read_line, stream_supports_fileno
from loushang.protocol import (
    JSONValue,
    JsonValueError,
    require_json_mapping,
    require_json_value,
)

JsonlCommandHostErrorKind = Literal["parse", "invalid", "dispatch"]
JsonlCommandHostErrorReason = Literal[
    "invalid_json",
    "not_object",
    "non_json_value",
    "invalid_id",
    "missing_type",
    "handler_failure",
]
JsonlCommandErrorListener = Callable[["JsonlCommandHostError"], Awaitable[None] | None]


@dataclass(frozen=True)
class JsonlCommand:
    """A validated command received from a line-oriented JSON transport."""

    command_id: str | None
    command_type: str
    payload: Mapping[str, JSONValue]


@dataclass(frozen=True)
class JsonlCommandHostError:
    """A transport-level command error for product-specific wire projection."""

    kind: JsonlCommandHostErrorKind
    reason: JsonlCommandHostErrorReason
    message: str
    command_id: str | None = None
    command_type: str | None = None


class JsonlCommandPort(Protocol):
    """Product command dispatcher used by :class:`JsonlCommandHost`."""

    def handle_jsonl_command(self, command: JsonlCommand) -> Awaitable[None] | None: ...


class JsonlCommandHost:
    """Read strict JSON commands and dispatch them to an injected Product port.

    The host deliberately owns no response schema.  A Product receives precise
    parse, validation, and dispatch errors and can preserve its public wire
    contract while reusing the input-loop and strict-JSON rules.
    """

    def __init__(
        self,
        *,
        port: JsonlCommandPort,
        on_error: JsonlCommandErrorListener,
        stdin: TextIO,
        command_name: str = "jsonl_command",
    ) -> None:
        self._port = port
        self._on_error = on_error
        self._stdin = stdin
        self._command_name = command_name
        self._stdin_uses_thread = stream_supports_fileno(stdin)
        self._running = False

    async def run(self) -> None:
        """Dispatch input until EOF or :meth:`stop`.

        Product handler exceptions are converted into ``dispatch`` errors and
        do not terminate the host.  I/O failures still propagate to the Product
        lifecycle owner, which is responsible for its process exit contract.
        """

        self._running = True
        while self._running:
            line = await self._read_line()
            if line == "":
                return
            if not line.strip():
                continue
            await self.handle_line(line)

    def stop(self) -> None:
        """Stop reading after the current command completes."""

        self._running = False

    async def handle_line(self, line: str) -> None:
        """Validate and dispatch a single JSON command line."""

        command = await self._parse_command(line)
        if command is None:
            return
        try:
            result = self._port.handle_jsonl_command(command)
            if result is not None:
                await result
        except Exception as error:
            await self._emit_error(
                JsonlCommandHostError(
                    kind="dispatch",
                    reason="handler_failure",
                    message=str(error) or type(error).__name__,
                    command_id=command.command_id,
                    command_type=command.command_type,
                )
            )

    async def _parse_command(self, line: str) -> JsonlCommand | None:
        try:
            decoded = json.loads(line, parse_constant=_reject_json_constant)
        except ValueError as error:
            detail = (
                error.msg if isinstance(error, json.JSONDecodeError) else str(error)
            )
            await self._emit_error(
                JsonlCommandHostError(
                    kind="parse",
                    reason="invalid_json",
                    message=detail,
                )
            )
            return None

        if not isinstance(decoded, dict):
            await self._emit_error(
                JsonlCommandHostError(
                    kind="invalid",
                    reason="not_object",
                    message="JSONL commands must be JSON objects",
                )
            )
            return None

        command_id = _usable_command_id(decoded.get("id"), name=self._command_name)
        try:
            payload = require_json_mapping(decoded, name=self._command_name)
        except JsonValueError as error:
            await self._emit_error(
                JsonlCommandHostError(
                    kind="invalid",
                    reason="non_json_value",
                    message=f"JSONL command contains a value outside strict JSON: {error}",
                    command_id=command_id,
                )
            )
            return None

        raw_id = payload.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            await self._emit_error(
                JsonlCommandHostError(
                    kind="invalid",
                    reason="invalid_id",
                    message="command id must be a string",
                )
            )
            return None

        command_type = payload.get("type")
        if not isinstance(command_type, str) or not command_type:
            await self._emit_error(
                JsonlCommandHostError(
                    kind="invalid",
                    reason="missing_type",
                    message="command missing string type",
                    command_id=cast(str | None, raw_id),
                )
            )
            return None
        return JsonlCommand(
            command_id=cast(str | None, raw_id),
            command_type=command_type,
            payload=payload,
        )

    async def _emit_error(self, error: JsonlCommandHostError) -> None:
        result = self._on_error(error)
        if result is not None:
            await result

    async def _read_line(self) -> str:
        return await read_line(self._stdin, use_thread=self._stdin_uses_thread)


def _usable_command_id(value: object, *, name: str) -> str | None:
    if type(value) is not str:
        return None
    try:
        projected = require_json_value(value, name=f"{name}.id")
    except JsonValueError:
        return None
    return projected if isinstance(projected, str) else None


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON numeric constant: {value}")


__all__ = [
    "JsonlCommand",
    "JsonlCommandErrorListener",
    "JsonlCommandHost",
    "JsonlCommandHostError",
    "JsonlCommandHostErrorKind",
    "JsonlCommandHostErrorReason",
    "JsonlCommandPort",
]
