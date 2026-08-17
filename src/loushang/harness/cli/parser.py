"""Argparse adapter for :mod:`loushang.harness.cli` profiles."""

from __future__ import annotations

from argparse import ArgumentParser, RawTextHelpFormatter
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from loushang.harness.cli.profile import CliProfile
from loushang.harness.cli.types import (
    CliArgumentSpec,
    CliInvocation,
    CliProfileError,
)


def build_parser(
    profile: CliProfile,
    *,
    prog: str = "loushang",
    command_id: str | None = None,
    add_help: bool = False,
) -> ArgumentParser:
    """Build a standard argparse parser from a profile.

    The parser is an implementation detail; Products should consume the
    ownership-separated :class:`CliInvocation` returned by ``parse_args``.
    """

    parser = ArgumentParser(
        prog=prog,
        add_help=add_help,
        formatter_class=RawTextHelpFormatter,
    )
    arguments = list(profile.root_arguments)
    command = profile.command(command_id) if command_id else None
    if command_id and command is None:
        raise CliProfileError(f"unknown CLI command: {command_id!r}")
    if command is not None:
        arguments.extend(command.arguments)
    register_profile_arguments(parser, arguments)
    parser.add_argument("__positionals", nargs="*")
    return parser


def register_profile_arguments(
    parser: ArgumentParser,
    profile_or_arguments: CliProfile | Sequence[CliArgumentSpec],
    *,
    command_id: str | None = None,
) -> None:
    """Register profile options on an existing application parser.

    This is the incremental migration hook for Products that still have
    product-specific positional or legacy options in their parser.  It adds
    only the declared profile arguments and never creates a second parser.
    """

    if isinstance(profile_or_arguments, CliProfile):
        arguments = list(profile_or_arguments.root_arguments)
        command = profile_or_arguments.command(command_id) if command_id else None
        if command_id and command is None:
            raise CliProfileError(f"unknown CLI command: {command_id!r}")
        if command is not None:
            arguments.extend(command.arguments)
    else:
        arguments = list(profile_or_arguments)
    add_argument = cast(Callable[..., Any], parser.add_argument)
    for spec in arguments:
        add_argument(*spec.flags, **spec.argparse_kwargs())


def parse_args(
    argv: Sequence[str],
    profile: CliProfile,
    *,
    prog: str = "loushang",
    allow_unknown: bool = False,
) -> CliInvocation:
    """Parse argv and split standard/product values by profile ownership."""

    values = list(argv)
    command_id: str | None = None
    command = None
    if values and not values[0].startswith("-"):
        command = profile.command(values[0])
        if command is not None:
            command_id = command.command_id
            values = values[1:]
    parser = build_parser(profile, prog=prog, command_id=command_id)
    if allow_unknown:
        namespace, unknown = parser.parse_known_args(values)
    else:
        namespace = parser.parse_args(values)
        unknown = []
    specs = list(profile.root_arguments)
    if command is not None:
        specs.extend(command.arguments)
    standard_dests = {spec.dest for spec in specs if spec.owner == "standard"}
    product_dests = {spec.dest for spec in specs if spec.owner == "product"}
    parsed = vars(namespace)
    positionals = tuple(parsed.pop("__positionals", ()))
    standard = {key: parsed[key] for key in standard_dests if key in parsed}
    product = {key: parsed[key] for key in product_dests if key in parsed}
    return CliInvocation(
        command_id=command_id,
        standard_values=standard,
        product_values=product,
        positionals=positionals,
        unknown=tuple(unknown),
    )


def format_agent_cli_help(
    base_help: str,
    *,
    extension_flags: Mapping[str, object] | None = None,
) -> str:
    """Append the standard Agent CLI output and extension flag guidance."""

    text = base_help.rstrip()
    if text.startswith("usage:"):
        text = "Usage:" + text[len("usage:") :]
    if extension_flags:
        text += "\n\nExtension flags:"
        for flag_name in sorted(extension_flags):
            flag = extension_flags[flag_name]
            flag_type = getattr(flag, "type", "string")
            line = f"\n  --{flag_name} [{flag_type}]"
            description = getattr(flag, "description", None)
            if description:
                line += f": {description}"
            default = getattr(flag, "default", None)
            if default is not None:
                line += f" (default={default!r})"
            text += line
    return (
        text + "\n\n"
        "Output formats:\n"
        "  --list-models-format text|json controls --list-models output.\n"
        "  --list-sessions-format tsv|json controls --list-sessions output; "
        "--all-sessions searches across session dirs.\n"
        "  --list-commands-format tsv|json controls --list-commands output.\n"
        "  --list-skills-format tsv|json controls --list-skills output.\n"
        "  --list-plugins-format tsv|json controls --list-plugins output.\n"
        "  --list-packages-format text|tsv|json controls --list-packages output.\n"
        "  --enable-skill/--disable-skill persist project skill toggles.\n"
        "  --add-plugin-source/--remove-plugin-source persist project plugin "
        "sources.\n"
        "  --enable-plugin/--disable-plugin persist project plugin toggles.\n"
        "  --command-result-format raw|json controls --command result output.\n"
        "  --export-format html|jsonl controls exported session file type.\n"
        "  --export-result-format text|json controls --export CLI result output.\n"
        "  diag export --output PATH writes a diagnostics bundle without starting "
        "a model session.\n"
        "\n\n"
        "Note:\n"
        "  Extensions can register additional flags. For extension-specific help, "
        "run\n"
        "  the extension docs or check extension output directly.\n"
    )


__all__ = [
    "build_parser",
    "format_agent_cli_help",
    "parse_args",
    "register_profile_arguments",
]
