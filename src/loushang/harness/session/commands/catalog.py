"""Catalog and Product selection for standard session commands."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from loushang.harness.commands import SessionCommandDescriptor, normalize_command_name
from loushang.harness.resources.source import create_source_info


class StandardSessionCommandId(str, Enum):
    """Stable identifiers for shared session command mechanics."""

    SESSION = "session"
    RENAME = "rename"
    EXPORT = "export"
    IMPORT = "import"
    COMPACT = "compact"
    RELOAD = "reload"
    NEW = "new"
    RESUME = "resume"
    DELETE = "delete"
    FORK = "fork"
    CLONE = "clone"
    TREE = "tree"
    TOOLS = "tools"
    EXTENSIONS = "extensions"
    COPY = "copy"
    CHANGELOG = "changelog"


@dataclass(frozen=True)
class StandardSessionCommandDefinition:
    """Shared slash-command metadata for one standard session operation."""

    command_id: StandardSessionCommandId
    description: str
    argument_hint: str | None = None

    @property
    def name(self) -> str:
        return self.command_id.value


STANDARD_SESSION_COMMANDS: tuple[StandardSessionCommandDefinition, ...] = (
    StandardSessionCommandDefinition(
        StandardSessionCommandId.EXPORT,
        "Export session (HTML default, or specify path: .html/.jsonl)",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.IMPORT,
        "Import and resume a session from a JSONL file",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.COPY,
        "Copy an assistant message to clipboard",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.RENAME,
        "Rename the current session",
        "<name>",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.SESSION,
        "Show session info and stats",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.CHANGELOG,
        "Show changelog entries",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.FORK,
        "Create a new fork from a previous user message",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.CLONE,
        "Duplicate the current session at the current position",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.TREE,
        "Navigate session tree (switch branches)",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.TOOLS,
        "Show or update active tools for this session",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.EXTENSIONS,
        "Show loaded extensions and diagnostics",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.NEW,
        "Start a new session in the current context",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.COMPACT,
        "Manually compact the session context",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.RESUME,
        "Resume a different session",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.DELETE,
        "Delete a previous session",
    ),
    StandardSessionCommandDefinition(
        StandardSessionCommandId.RELOAD,
        "Reload keybindings, extensions, skills, prompts, and themes",
    ),
)


def list_standard_session_command_descriptors() -> list[SessionCommandDescriptor]:
    source_info = create_source_info(
        "<builtin>",
        source="builtin",
        scope="project",
        origin="top-level",
    )
    return [
        SessionCommandDescriptor(
            name=definition.name,
            description=definition.description,
            source="builtin",
            source_info=source_info,
            argument_hint=definition.argument_hint,
        )
        for definition in STANDARD_SESSION_COMMANDS
    ]


@dataclass(frozen=True)
class StandardSessionCommandProfile:
    """Immutable Product selection of standard session command identifiers."""

    enabled_command_ids: frozenset[StandardSessionCommandId]

    @classmethod
    def standard(cls) -> StandardSessionCommandProfile:
        return cls(frozenset(StandardSessionCommandId))

    def select(
        self,
        command_ids: Iterable[StandardSessionCommandId | str],
    ) -> StandardSessionCommandProfile:
        selected = _command_ids(command_ids)
        return StandardSessionCommandProfile(self.enabled_command_ids & selected)

    def without(
        self,
        command_ids: Iterable[StandardSessionCommandId | str],
    ) -> StandardSessionCommandProfile:
        return StandardSessionCommandProfile(
            self.enabled_command_ids - _command_ids(command_ids)
        )

    def includes(self, command_id: StandardSessionCommandId) -> bool:
        return command_id in self.enabled_command_ids


STANDARD_SESSION_COMMAND_PROFILE = StandardSessionCommandProfile.standard()


def is_standard_session_command(
    invocation_name: str,
    *,
    profile: StandardSessionCommandProfile = STANDARD_SESSION_COMMAND_PROFILE,
) -> bool:
    """Return whether an invocation is selected by a standard profile."""

    command_id = resolve_standard_session_command_id(invocation_name)
    return command_id is not None and profile.includes(command_id)


def resolve_standard_session_command_id(
    invocation_name: str,
) -> StandardSessionCommandId | None:
    if not isinstance(invocation_name, str):
        return None
    try:
        return StandardSessionCommandId(normalize_command_name(invocation_name))
    except ValueError:
        return None


def _command_ids(
    command_ids: Iterable[StandardSessionCommandId | str],
) -> frozenset[StandardSessionCommandId]:
    if isinstance(command_ids, str):
        raise TypeError("command ids must be an iterable, not a string")
    ids: set[StandardSessionCommandId] = set()
    for command_id in command_ids:
        try:
            ids.add(StandardSessionCommandId(command_id))
        except ValueError as exc:
            raise ValueError(
                f"unknown standard session command: {command_id!r}"
            ) from exc
    return frozenset(ids)


__all__ = [
    "STANDARD_SESSION_COMMANDS",
    "STANDARD_SESSION_COMMAND_PROFILE",
    "StandardSessionCommandDefinition",
    "StandardSessionCommandId",
    "StandardSessionCommandProfile",
    "is_standard_session_command",
    "list_standard_session_command_descriptors",
]
