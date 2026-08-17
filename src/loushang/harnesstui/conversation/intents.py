"""Standard conversation intents shared by Agent-style Product UIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class PromptIntent:
    text: str
    images: tuple[object, ...] | None = None


@dataclass(frozen=True)
class BashIntent:
    command: str


@dataclass(frozen=True)
class FollowUpIntent:
    text: str


@dataclass(frozen=True)
class AbortIntent:
    pass


@dataclass(frozen=True)
class DebugIntent:
    enabled: bool = True
    scopes: tuple[str, ...] = ("all",)


@dataclass(frozen=True)
class TerminalDiagnosticsIntent:
    pass


@dataclass(frozen=True)
class SettingsIntent:
    pass


@dataclass(frozen=True)
class ModelsIntent:
    query: str = ""


@dataclass(frozen=True)
class ModelSelectIntent:
    query: str = ""


@dataclass(frozen=True)
class HotkeysIntent:
    pass


@dataclass(frozen=True)
class CommandsIntent:
    query: str = ""


@dataclass(frozen=True)
class CommandSelectIntent:
    query: str = ""


@dataclass(frozen=True)
class QuitIntent:
    pass


ConversationIntent: TypeAlias = (
    PromptIntent
    | BashIntent
    | FollowUpIntent
    | AbortIntent
    | DebugIntent
    | TerminalDiagnosticsIntent
    | SettingsIntent
    | ModelsIntent
    | ModelSelectIntent
    | HotkeysIntent
    | CommandsIntent
    | CommandSelectIntent
    | QuitIntent
)


def parse_conversation_intent(text: str) -> ConversationIntent | None:
    """Parse the standard local commands understood by Agent Product UIs."""

    stripped = text.strip()
    if not stripped:
        return None
    if stripped in {"/quit", "/exit"}:
        return QuitIntent()
    if stripped == "/abort":
        return AbortIntent()
    if stripped == "/debug" or stripped.startswith("/debug "):
        return _parse_debug_intent(stripped)
    if stripped == "/terminal":
        return TerminalDiagnosticsIntent()
    if stripped in {"/settings", "/config"}:
        return SettingsIntent()
    if stripped == "/model" or stripped.startswith("/model "):
        return ModelSelectIntent(query=stripped[len("/model") :].strip())
    if stripped == "/models" or stripped.startswith("/models "):
        return ModelsIntent(query=stripped[len("/models") :].strip())
    if stripped == "/hotkeys":
        return HotkeysIntent()
    if stripped == "/command" or stripped.startswith("/command "):
        return CommandSelectIntent(query=stripped[len("/command") :].strip())
    if stripped == "/commands" or stripped.startswith("/commands "):
        return CommandsIntent(query=stripped[len("/commands") :].strip())
    if stripped == "/follow" or stripped.startswith("/follow "):
        follow_text = stripped[len("/follow") :].strip()
        return FollowUpIntent(text=follow_text) if follow_text else None
    if stripped.startswith("!!"):
        command = stripped[2:].strip()
        if command:
            return BashIntent(command=command)
    return PromptIntent(text=stripped)


def _parse_debug_intent(stripped: str) -> DebugIntent:
    args = stripped[len("/debug") :].strip()
    if not args:
        return DebugIntent()

    tokens = [token for group in args.split() for token in group.split(",") if token]
    if not tokens:
        return DebugIntent()
    first = tokens[0].lower()
    if first in {"off", "disable", "disabled"}:
        return DebugIntent(enabled=False, scopes=())
    if first in {"on", "enable", "enabled"}:
        tokens = tokens[1:]
    return DebugIntent(scopes=tuple(tokens) if tokens else ("all",))


__all__ = [
    "AbortIntent",
    "BashIntent",
    "CommandSelectIntent",
    "CommandsIntent",
    "ConversationIntent",
    "DebugIntent",
    "FollowUpIntent",
    "HotkeysIntent",
    "ModelSelectIntent",
    "ModelsIntent",
    "PromptIntent",
    "QuitIntent",
    "SettingsIntent",
    "TerminalDiagnosticsIntent",
    "parse_conversation_intent",
]
