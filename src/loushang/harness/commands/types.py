from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum


class CommandKind(Enum):
    LOCAL_UI = "local_ui"
    SESSION = "session"


class CommandEffectKind(Enum):
    LOCAL_UI = "local_ui"
    SESSION = "session"


@dataclass(frozen=True)
class CommandDef:
    id: str
    name: str
    kind: CommandKind
    description: str | None = None
    source: str | None = None
    aliases: tuple[str, ...] = ()
    argument_hint: str | None = None


@dataclass(frozen=True)
class CommandEffect:
    kind: CommandEffectKind
    command: CommandDef
    payload: Mapping[str, object] = field(default_factory=dict)


__all__ = ["CommandDef", "CommandEffect", "CommandEffectKind", "CommandKind"]
