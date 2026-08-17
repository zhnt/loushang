"""Product-neutral composition of local and session command catalogs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from loushang.harness.commands.descriptors import (
    CommandCatalog,
    CommandDescriptor,
    split_slash_command,
)
from loushang.harness.commands.types import CommandDef, CommandKind

SourceInfoT = TypeVar("SourceInfoT")


@dataclass(frozen=True, slots=True)
class LocalCommandCatalogProfile:
    """Immutable Product-selected local command definitions and routes."""

    local_commands_by_name: Mapping[str, CommandDef] = field(default_factory=dict)
    local_command_names_by_route: Mapping[str, str] = field(default_factory=dict)
    local_commands_accepting_args: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.local_commands_by_name, Mapping):
            raise TypeError("local_commands_by_name must be a mapping")
        if not isinstance(self.local_command_names_by_route, Mapping):
            raise TypeError("local_command_names_by_route must be a mapping")

        commands: dict[str, CommandDef] = {}
        for name, command in self.local_commands_by_name.items():
            if not isinstance(name, str) or not name.strip():
                raise TypeError("local command names must be non-empty strings")
            if not isinstance(command, CommandDef):
                raise TypeError("local command definitions must be CommandDef values")
            if command.name != name:
                raise ValueError(
                    "local command mapping keys must match CommandDef.name values"
                )
            commands[name] = command

        routes: dict[str, str] = {}
        for route, command_name in self.local_command_names_by_route.items():
            if not isinstance(route, str) or not route.strip():
                raise TypeError("local command routes must be non-empty strings")
            if not isinstance(command_name, str) or command_name not in commands:
                raise ValueError(
                    "local command routes must reference a declared command name"
                )
            routes[route] = command_name

        accepting_args = frozenset(self.local_commands_accepting_args)
        if not accepting_args <= commands.keys():
            raise ValueError(
                "local commands accepting arguments must be declared command names"
            )

        object.__setattr__(
            self,
            "local_commands_by_name",
            MappingProxyType(commands),
        )
        object.__setattr__(
            self,
            "local_command_names_by_route",
            MappingProxyType(routes),
        )
        object.__setattr__(
            self,
            "local_commands_accepting_args",
            accepting_args,
        )

    def select(self, names: Iterable[str]) -> LocalCommandCatalogProfile:
        """Return a profile containing exactly the selected command names."""

        selected = _known_command_names(names, self.local_commands_by_name)
        return LocalCommandCatalogProfile(
            local_commands_by_name={
                name: command
                for name, command in self.local_commands_by_name.items()
                if name in selected
            },
            local_command_names_by_route={
                route: command_name
                for route, command_name in self.local_command_names_by_route.items()
                if command_name in selected
            },
            local_commands_accepting_args=(
                self.local_commands_accepting_args & selected
            ),
        )

    def without(self, names: Iterable[str]) -> LocalCommandCatalogProfile:
        """Return a profile with the selected command names removed."""

        removed = _known_command_names(names, self.local_commands_by_name)
        return LocalCommandCatalogProfile(
            local_commands_by_name={
                name: command
                for name, command in self.local_commands_by_name.items()
                if name not in removed
            },
            local_command_names_by_route={
                route: command_name
                for route, command_name in self.local_command_names_by_route.items()
                if command_name not in removed
            },
            local_commands_accepting_args=(
                self.local_commands_accepting_args - removed
            ),
        )

    def with_additions(
        self,
        commands: Mapping[str, CommandDef],
        *,
        routes: Mapping[str, str] | None = None,
        accepting_args: Iterable[str] = (),
    ) -> LocalCommandCatalogProfile:
        """Return a profile with non-conflicting Product command additions."""

        command_names = set(commands)
        route_names = set((routes or {}))
        if command_names & self.local_commands_by_name.keys():
            raise ValueError(
                "local command additions must not replace existing commands"
            )
        if route_names & self.local_command_names_by_route.keys():
            raise ValueError("local command additions must not replace existing routes")
        return LocalCommandCatalogProfile(
            local_commands_by_name={**self.local_commands_by_name, **commands},
            local_command_names_by_route={
                **self.local_command_names_by_route,
                **(routes or {}),
            },
            local_commands_accepting_args=(
                self.local_commands_accepting_args | frozenset(accepting_args)
            ),
        )

    def with_replacements(
        self,
        commands: Mapping[str, CommandDef],
        *,
        routes: Mapping[str, str] | None = None,
        accepting_args: Iterable[str] | None = None,
    ) -> LocalCommandCatalogProfile:
        """Return a profile with explicit replacements of selected commands."""

        command_names = set(commands)
        route_names = set((routes or {}))
        if not command_names <= self.local_commands_by_name.keys():
            raise ValueError("local command replacements must target existing commands")
        if not route_names <= self.local_command_names_by_route.keys():
            raise ValueError(
                "local command route replacements must target existing routes"
            )
        return LocalCommandCatalogProfile(
            local_commands_by_name={**self.local_commands_by_name, **commands},
            local_command_names_by_route={
                **self.local_command_names_by_route,
                **(routes or {}),
            },
            local_commands_accepting_args=(
                self.local_commands_accepting_args
                if accepting_args is None
                else frozenset(accepting_args)
            ),
        )

    def command_for_route(self, route_value: str) -> CommandDef | None:
        command_name = self.local_command_names_by_route.get(route_value)
        if command_name is None:
            return None
        return self.local_commands_by_name[command_name]


EMPTY_LOCAL_COMMAND_CATALOG_PROFILE = LocalCommandCatalogProfile()


# These commands are host/session controls shared by Agent products.  Products
# can select a subset or add domain commands without copying the definitions.
DEFAULT_LOCAL_COMMANDS_PROFILE = LocalCommandCatalogProfile(
    local_commands_by_name={
        "model": CommandDef(
            id="harness.ui.model",
            name="model",
            kind=CommandKind.LOCAL_UI,
            description="Select model",
            source="local",
        ),
        "models": CommandDef(
            id="harness.ui.models",
            name="models",
            kind=CommandKind.LOCAL_UI,
            description="Show available models",
            source="local",
        ),
        "command": CommandDef(
            id="harness.ui.command",
            name="command",
            kind=CommandKind.LOCAL_UI,
            description="Select command",
            source="local",
        ),
        "commands": CommandDef(
            id="harness.ui.commands",
            name="commands",
            kind=CommandKind.LOCAL_UI,
            description="Show commands",
            source="local",
        ),
        "hotkeys": CommandDef(
            id="harness.ui.hotkeys",
            name="hotkeys",
            kind=CommandKind.LOCAL_UI,
            description="Show keyboard shortcuts",
            source="local",
        ),
        "settings": CommandDef(
            id="harness.ui.settings",
            name="settings",
            kind=CommandKind.LOCAL_UI,
            description="Open settings",
            source="local",
        ),
        "config": CommandDef(
            id="harness.ui.config",
            name="config",
            kind=CommandKind.LOCAL_UI,
            description="Open settings",
            source="local",
        ),
        "terminal": CommandDef(
            id="harness.ui.terminal",
            name="terminal",
            kind=CommandKind.LOCAL_UI,
            description="Show terminal diagnostics",
            source="local",
        ),
        "agents": CommandDef(
            id="harness.ui.agents",
            name="agents",
            kind=CommandKind.LOCAL_UI,
            description="Show live agent collaboration",
            source="local",
        ),
        "permissions": CommandDef(
            id="harness.ui.permissions",
            name="permissions",
            kind=CommandKind.LOCAL_UI,
            description="Manage pending approvals and session grants",
            source="local",
        ),
        "btw": CommandDef(
            id="harness.ui.btw",
            name="btw",
            kind=CommandKind.LOCAL_UI,
            description="Ask a quick side question without interrupting the main task",
            source="local",
            argument_hint="<question>",
        ),
        # Quit/exit are conversation-host controls (QuitIntent), not session
        # operations, so they declare no routes: listing and completion pick
        # them up here while dispatch keeps handling them as exits.
        "quit": CommandDef(
            id="harness.ui.quit",
            name="quit",
            kind=CommandKind.LOCAL_UI,
            description="Quit the conversation",
            source="local",
        ),
        "exit": CommandDef(
            id="harness.ui.exit",
            name="exit",
            kind=CommandKind.LOCAL_UI,
            description="Quit the conversation",
            source="local",
        ),
    },
    local_command_names_by_route={
        "model_select": "model",
        "models": "models",
        "command_select": "command",
        "commands": "commands",
        "hotkeys": "hotkeys",
        "settings": "settings",
        "config": "config",
        "terminal": "terminal",
    },
    local_commands_accepting_args=frozenset(
        {"btw", "command", "commands", "model", "models"}
    ),
)


@dataclass(frozen=True, slots=True)
class MixedCommandCatalogPorts(Generic[SourceInfoT]):
    """Product adapters for acquiring and projecting session commands."""

    session_catalog: Callable[[], CommandCatalog[SourceInfoT]] | None = None
    session_command: Callable[[CommandDescriptor[SourceInfoT]], CommandDef] | None = (
        None
    )


@dataclass(frozen=True, slots=True)
class MixedCommandMatch:
    command: CommandDef
    invocation_name: str
    args: str


class MixedCommandCatalog(Generic[SourceInfoT]):
    """Compose selected local definitions with an optional session catalog."""

    def __init__(
        self,
        *,
        profile: LocalCommandCatalogProfile,
        ports: MixedCommandCatalogPorts[SourceInfoT] | None = None,
    ) -> None:
        self._profile = profile
        self._ports = ports or MixedCommandCatalogPorts()

    @property
    def profile(self) -> LocalCommandCatalogProfile:
        return self._profile

    def commands(self) -> tuple[CommandDef, ...]:
        session_commands = tuple(
            self._project_session_command(descriptor)
            for descriptor in self._session_catalog().commands()
        )
        session_names = {command.name for command in session_commands}
        local_commands = tuple(
            command
            for name, command in self._profile.local_commands_by_name.items()
            if name not in session_names
        )
        return (*session_commands, *local_commands)

    def local_for_route(self, route_value: str) -> CommandDef | None:
        return self._profile.command_for_route(route_value)

    def lookup(self, text: str) -> CommandDef | None:
        local_command = self.local_for_text(text)
        if local_command is not None:
            return local_command
        match = self.session_match(text)
        return match.command if match is not None else None

    def local_for_text(self, text: str) -> CommandDef | None:
        parsed = split_slash_command(text.strip())
        if parsed is None:
            return None
        invocation_name, args = parsed
        name = invocation_name.removeprefix("/")
        command = self._profile.local_commands_by_name.get(name)
        if command is None:
            return None
        if args and name not in self._profile.local_commands_accepting_args:
            return None
        return command

    def session_match(self, text: str) -> MixedCommandMatch | None:
        parsed = split_slash_command(text.strip())
        if parsed is None or self._ports.session_catalog is None:
            return None
        invocation_name, args = parsed
        descriptor = self._session_catalog().lookup(invocation_name)
        if descriptor is None:
            return None
        return MixedCommandMatch(
            command=self._project_session_command(descriptor),
            invocation_name=invocation_name,
            args=args,
        )

    def _session_catalog(self) -> CommandCatalog[SourceInfoT]:
        if self._ports.session_catalog is None:
            return CommandCatalog()
        return self._ports.session_catalog()

    def _project_session_command(
        self,
        descriptor: CommandDescriptor[SourceInfoT],
    ) -> CommandDef:
        if self._ports.session_command is None:
            raise TypeError("Session command projection port is required")
        return self._ports.session_command(descriptor)


def _known_command_names(
    names: Iterable[str],
    available: Mapping[str, CommandDef],
) -> frozenset[str]:
    if isinstance(names, str):
        raise TypeError("local command names must be an iterable of strings")
    selected = frozenset(names)
    if not all(isinstance(name, str) for name in selected):
        raise TypeError("local command names must be strings")
    unknown = selected - available.keys()
    if unknown:
        raise ValueError(
            "local command profile references unknown commands: "
            + ", ".join(sorted(unknown))
        )
    return selected


def command_def_from_descriptor(
    descriptor: CommandDescriptor[SourceInfoT],
    *,
    id_prefix: str = "harness.session",
) -> CommandDef:
    """Project a typed session descriptor into the shared host command shape."""

    normalized = descriptor.effective_invocation_name
    return CommandDef(
        id=f"{id_prefix}.{normalized}",
        name=normalized,
        kind=CommandKind.SESSION,
        description=descriptor.description,
        source=descriptor.source,
        aliases=descriptor.aliases,
        argument_hint=descriptor.argument_hint,
    )


def coerce_command_descriptor(value: object) -> CommandDescriptor[Any] | None:
    """Normalize a structural Product command into the shared descriptor."""

    if isinstance(value, CommandDescriptor):
        return value
    name = _non_empty_string_attr(value, "name")
    invocation_name = _non_empty_string_attr(value, "invocation_name") or name
    if invocation_name is None:
        return None
    precedence = getattr(value, "precedence", 0)
    if not isinstance(precedence, int) or isinstance(precedence, bool):
        precedence = 0
    aliases = getattr(value, "aliases", ())
    if not isinstance(aliases, (tuple, list)):
        aliases = ()
    return CommandDescriptor(
        name=name or invocation_name,
        description=_non_empty_string_attr(value, "description"),
        source=_non_empty_string_attr(value, "source") or "session",
        source_info=getattr(value, "source_info", None),
        invocation_name=invocation_name,
        aliases=tuple(
            alias for alias in aliases if isinstance(alias, str) and alias
        ),
        conflict_group=_non_empty_string_attr(value, "conflict_group"),
        argument_hint=_non_empty_string_attr(value, "argument_hint"),
        precedence=precedence,
    )


def _non_empty_string_attr(value: object, name: str) -> str | None:
    raw = getattr(value, name, None)
    return raw if isinstance(raw, str) and raw else None


__all__ = [
    "DEFAULT_LOCAL_COMMANDS_PROFILE",
    "EMPTY_LOCAL_COMMAND_CATALOG_PROFILE",
    "LocalCommandCatalogProfile",
    "MixedCommandCatalog",
    "MixedCommandCatalogPorts",
    "MixedCommandMatch",
    "command_def_from_descriptor",
    "coerce_command_descriptor",
]
