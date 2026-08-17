"""Product-neutral command-line profile contracts.

The CLI profile is deliberately smaller than an application argument object.  It
describes grammar and ownership; a product remains responsible for interpreting
its values and for constructing its runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

CliArgumentOwner = Literal["standard", "product"]
CliArgumentAction = Literal[
    "store",
    "store_true",
    "store_false",
    "append",
    "count",
]
CliNargs = int | Literal["?", "*", "+"] | None
CliValueParser = Callable[[str], object]
UNSET = object()


class CliProfileError(ValueError):
    """Raised when a product attempts an ambiguous CLI composition."""


@dataclass(frozen=True, slots=True)
class CliArgumentSpec:
    """One option in a root command or a product command.

    ``flags`` contains the complete argparse spellings, for example
    ``("--model", "-m")``.  A product must add a new spec instead of silently
    replacing a standard one; explicit behaviour changes belong in a new
    profile/version.
    """

    argument_id: str
    flags: tuple[str, ...]
    dest: str
    owner: CliArgumentOwner = "standard"
    action: CliArgumentAction = "store"
    type: CliValueParser | None = None
    nargs: CliNargs = None
    choices: tuple[object, ...] | None = None
    default: object = UNSET
    const: object = UNSET
    required: bool = False
    help: str | None = None
    metavar: str | None = None

    def __post_init__(self) -> None:
        if not self.argument_id.strip():
            raise CliProfileError("CLI argument id must be non-empty")
        if not self.flags:
            raise CliProfileError(f"CLI argument {self.argument_id!r} has no flags")
        if any(not flag.startswith("-") for flag in self.flags):
            raise CliProfileError(
                f"CLI argument {self.argument_id!r} flags must start with '-'")
        if len(set(self.flags)) != len(self.flags):
            raise CliProfileError(
                f"CLI argument {self.argument_id!r} contains duplicate flags")
        if not self.dest or self.dest.startswith("_"):
            raise CliProfileError(
                f"CLI argument {self.argument_id!r} has an invalid destination")
        if self.action not in {"store", "store_true", "store_false", "append", "count"}:
            raise CliProfileError(f"unsupported CLI action: {self.action!r}")
        if self.action in {"store_true", "store_false", "count"} and self.type is not None:
            raise CliProfileError(
                f"CLI action {self.action!r} cannot define a value parser")

    def argparse_kwargs(self) -> dict[str, object]:
        """Return the argparse keyword arguments for this declarative spec."""

        kwargs: dict[str, object] = {"dest": self.dest, "action": self.action}
        if self.action in {"store", "append"} and self.type is not None:
            kwargs["type"] = self.type
        if self.nargs is not None:
            kwargs["nargs"] = self.nargs
        if self.choices is not None:
            kwargs["choices"] = self.choices
        if self.default is not UNSET:
            kwargs["default"] = self.default
        if self.const is not UNSET:
            kwargs["const"] = self.const
        if self.required:
            kwargs["required"] = True
        if self.help is not None:
            kwargs["help"] = self.help
        if self.metavar is not None:
            kwargs["metavar"] = self.metavar
        return kwargs


@dataclass(frozen=True, slots=True)
class CliCommandSpec:
    """A product command that can extend the shared root grammar."""

    command_id: str
    names: tuple[str, ...]
    arguments: tuple[CliArgumentSpec, ...] = ()
    help: str | None = None

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.names:
            raise CliProfileError("CLI commands require an id and at least one name")
        if any(not name or name.startswith("-") for name in self.names):
            raise CliProfileError(
                f"CLI command {self.command_id!r} has an invalid name")
        if len(set(self.names)) != len(self.names):
            raise CliProfileError(
                f"CLI command {self.command_id!r} contains duplicate names")
        _validate_arguments(self.arguments, context=self.command_id)

    @property
    def canonical_name(self) -> str:
        return self.names[0]


@dataclass(frozen=True, slots=True)
class CliInvocation:
    """Parsed CLI data split by ownership boundary."""

    command_id: str | None
    standard_values: Mapping[str, object]
    product_values: Mapping[str, object]
    positionals: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "standard_values", MappingProxyType(dict(self.standard_values)))
        object.__setattr__(self, "product_values", MappingProxyType(dict(self.product_values)))

    @property
    def values(self) -> Mapping[str, object]:
        """Return both value maps for adapters that do not need ownership."""

        return MappingProxyType({**self.standard_values, **self.product_values})

    def value(self, dest: str, default: object = None) -> object:
        return self.values.get(dest, default)


def _validate_arguments(
    arguments: Sequence[CliArgumentSpec], *, context: str = "root"
) -> None:
    ids: set[str] = set()
    destinations: dict[str, CliArgumentSpec] = {}
    flags: set[str] = set()
    for argument in arguments:
        if argument.argument_id in ids:
            raise CliProfileError(
                f"duplicate CLI argument id {argument.argument_id!r} in {context}")
        previous = destinations.get(argument.dest)
        if previous is not None and {
            previous.action,
            argument.action,
        } != {"store_true", "store_false"}:
            raise CliProfileError(
                f"duplicate CLI destination {argument.dest!r} in {context}")
        duplicate_flags = flags.intersection(argument.flags)
        if duplicate_flags:
            raise CliProfileError(
                f"duplicate CLI flag(s) {sorted(duplicate_flags)!r} in {context}")
        ids.add(argument.argument_id)
        destinations[argument.dest] = argument
        flags.update(argument.flags)


def validate_arguments(arguments: Sequence[CliArgumentSpec]) -> None:
    """Validate a public sequence of argument specs."""

    _validate_arguments(arguments)
