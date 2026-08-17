"""Coding CLI grammar adapter over the standard Agent-product values."""

from __future__ import annotations

from argparse import ArgumentParser, RawTextHelpFormatter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.coding.cli.profile import CODING_CLI_PROFILE
from loushang.harness.cli import (
    extract_unknown_long_options,
    project_extension_flag_values,
    register_extension_flag_arguments,
    register_profile_arguments,
)
from loushang.harness.cli.agent_args import (
    AgentCliArgs,
    agent_cli_argument_values,
    normalize_agent_cli_argv,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.extensions.types import RegisteredFlag, ResolvedFlag

MethodListFormat = Literal["tsv", "json"]
MethodShowFormat = Literal["text", "json"]
MethodPlanShowFormat = Literal["text", "json"]
WorkLogInspectFormat = Literal["text", "json", "plans", "plans-json"]
ExtensionFlag: TypeAlias = RegisteredFlag | ResolvedFlag
_BUILTIN_FLAG_NAMES = CODING_CLI_PROFILE.option_names


@dataclass(frozen=True)
class CliArgs(AgentCliArgs):
    """Standard Agent CLI values plus Coding's Method/Work additions."""

    capability_modes: tuple[tuple[str, CapabilityMountMode], ...]
    method: str | None
    no_method: bool
    prompt_steps: str | None
    list_methods: bool
    list_methods_format: MethodListFormat
    show_method: str | None
    show_method_format: MethodShowFormat
    show_method_plan: str | None
    show_method_plan_format: MethodPlanShowFormat
    work_log: str | None
    work_log_inspect: str | None
    work_log_run: str | None
    work_log_inspect_format: WorkLogInspectFormat


def build_parser() -> ArgumentParser:
    return _build_parser()


def help_text() -> str:
    return _build_parser().format_help()


def parse_args(
    argv: list[str] | tuple[str, ...],
    *,
    extension_flags: Mapping[str, ExtensionFlag] | None = None,
    allow_unknown: bool = False,
) -> CliArgs:
    parser = _build_parser()
    registered_extension_flags = register_extension_flag_arguments(
        parser,
        dict(extension_flags or {}),
        reserved_names=_BUILTIN_FLAG_NAMES,
    )
    raw_argv = normalize_agent_cli_argv(
        _rewrite_method_subcommands(list(argv))
    )
    if allow_unknown:
        filtered_argv, unknown_flags = extract_unknown_long_options(
            raw_argv,
            known_names=_BUILTIN_FLAG_NAMES
            | frozenset(registered_extension_flags),
        )
        namespace = parser.parse_intermixed_args(filtered_argv)
    else:
        namespace = parser.parse_intermixed_args(raw_argv)
        unknown_flags = {}

    extension_flag_values = project_extension_flag_values(
        namespace,
        registered_extension_flags,
    )

    return CliArgs(
        **agent_cli_argument_values(
            namespace,
            unknown_flags=unknown_flags,
            extension_flag_values=extension_flag_values,
        ),
        capability_modes=tuple(namespace.capability),
        method=namespace.method,
        no_method=namespace.no_method,
        prompt_steps=namespace.prompt_steps,
        list_methods=namespace.list_methods,
        list_methods_format=namespace.list_methods_format,
        show_method=namespace.show_method,
        show_method_format=namespace.show_method_format,
        show_method_plan=namespace.show_method_plan,
        show_method_plan_format=namespace.show_method_plan_format,
        work_log=namespace.work_log,
        work_log_inspect=namespace.work_log_inspect,
        work_log_run=namespace.work_log_run,
        work_log_inspect_format=namespace.work_log_inspect_format,
    )


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="python -m loushang.coding.cli",
        add_help=False,
        formatter_class=RawTextHelpFormatter,
    )
    parser.add_argument("messages", nargs="*")
    register_profile_arguments(parser, CODING_CLI_PROFILE)
    return parser


def _rewrite_method_subcommands(argv: list[str]) -> list[str]:
    method_index = _method_subcommand_index(argv)
    if method_index is None or len(argv) <= method_index + 1:
        return argv
    prefix = argv[:method_index]
    command = argv[method_index + 1]
    suffix = argv[method_index + 2 :]
    if command == "list":
        return [*prefix, "--list-methods", *suffix]
    if command == "show" and suffix:
        return [*prefix, "--show-method", suffix[0], *suffix[1:]]
    if command == "plan" and len(suffix) >= 2 and suffix[0] == "show":
        return [
            *prefix,
            "--show-method-plan",
            suffix[1],
            *_rewrite_method_plan_show_options(suffix[2:]),
        ]
    return argv


def _rewrite_method_plan_show_options(argv: list[str]) -> list[str]:
    rewritten: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--format":
            rewritten.append("--show-method-plan-format")
            if index + 1 < len(argv):
                rewritten.append(argv[index + 1])
                index += 2
                continue
        rewritten.append(token)
        index += 1
    return rewritten


def _method_subcommand_index(argv: list[str]) -> int | None:
    if argv and argv[0] == "method":
        return 0
    if len(argv) >= 3 and argv[0] == "--cwd" and argv[2] == "method":
        return 2
    if len(argv) >= 2 and argv[0].startswith("--cwd=") and argv[1] == "method":
        return 1
    return None


__all__ = ["CliArgs", "ExtensionFlag", "build_parser", "help_text", "parse_args"]
