"""Values for the optional, Session-scoped command capability."""

from __future__ import annotations

import json
from dataclasses import dataclass

MAX_COMMAND_RESULT_BYTES = 16 * 1024


def _bounded_text(value: str, limit: int) -> None:
    if type(value) is not str or len(value.encode("utf-8")) > limit or "\x00" in value:
        raise ValueError("invalid Session command text")


@dataclass(frozen=True, slots=True)
class SessionCommandInvocationV1:
    name: str
    args: str = ""

    def __post_init__(self) -> None:
        _bounded_text(self.name, 256)
        _bounded_text(self.args, 8192)
        if (
            not self.name
            or self.name != self.name.strip()
            or self.name.startswith("/")
            or any(ord(char) < 32 for char in self.name)
        ):
            raise ValueError("invalid Session command name")


@dataclass(frozen=True, slots=True)
class SessionCommandChoiceV1:
    name: str
    description: str
    source: str
    aliases: tuple[str, ...]
    argument_hint: str
    unavailable_reason: str | None
    read_only: bool = False

    def __post_init__(self) -> None:
        SessionCommandInvocationV1(self.name)
        _bounded_text(self.description, 512)
        _bounded_text(self.source, 64)
        _bounded_text(self.argument_hint, 256)
        if self.unavailable_reason is not None:
            _bounded_text(self.unavailable_reason, 256)
        if type(self.read_only) is not bool:
            raise ValueError("invalid Session command access mode")
        if type(self.aliases) is not tuple or len(self.aliases) > 8:
            raise ValueError("invalid Session command aliases")
        for alias in self.aliases:
            _bounded_text(alias, 128)
            SessionCommandInvocationV1(alias)


@dataclass(frozen=True, slots=True)
class SessionCommandCatalogV1:
    commands: tuple[SessionCommandChoiceV1, ...]
    completions: tuple[str, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.commands) is not tuple
            or len(self.commands) > 128
            or any(type(entry) is not SessionCommandChoiceV1 for entry in self.commands)
            or type(self.completions) is not tuple
            or len(self.completions) > 256
            or type(self.truncated) is not bool
        ):
            raise ValueError("invalid Session command catalog")
        for item in self.completions:
            _bounded_text(item, 256)


@dataclass(frozen=True, slots=True)
class SessionCommandResultV1:
    """Bounded command-specific JSON object, carried only by the result lookup."""

    data_json: str

    def __post_init__(self) -> None:
        _bounded_text(self.data_json, MAX_COMMAND_RESULT_BYTES)
        if type(self.data) is not dict:
            raise ValueError("Session command result must be an object")

    @property
    def data(self) -> dict[str, object]:
        return json.loads(self.data_json)

    @classmethod
    def from_data(cls, data: dict[str, object]) -> SessionCommandResultV1:
        return cls(
            json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        )
