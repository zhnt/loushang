"""CLI contracts and projections for immediate collaboration recipes."""

from __future__ import annotations

import json
from argparse import SUPPRESS, ArgumentParser, Namespace
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Never, TextIO

from loushang.harness.multiagent import (
    CollaborationRecipe,
    RecipeExecutionResult,
)

MultiAgentOutputFormat = Literal["plain", "json"]


class MultiAgentCliUsageError(ValueError):
    def __init__(self, message: str, *, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _NoExitParser(ArgumentParser):
    def error(self, message: str) -> Never:
        raise MultiAgentCliUsageError(message, usage=self.format_usage())


@dataclass(frozen=True, slots=True)
class MultiAgentRecipesCommand:
    output_format: MultiAgentOutputFormat = "plain"
    help: bool = False


@dataclass(frozen=True, slots=True)
class MultiAgentRunCommand:
    recipe_id: str
    prompt: str | None
    attachments: tuple[str, ...]
    cwd: str | None
    session_dir: str | None
    provider: str | None
    model: str | None
    thinking: str | None
    agent_models: Mapping[str, str]
    replicas: Mapping[str, int]
    count: int | None
    max_parallel: int | None
    timeout: float
    output_format: MultiAgentOutputFormat
    help: bool = False


MultiAgentCliCommand = MultiAgentRecipesCommand | MultiAgentRunCommand


def extract_multiagent_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    """Extract ``ma``/``multiagent``, preserving a leading common ``--cwd``."""

    values = list(argv)
    if values and values[0] in {"ma", "multiagent"}:
        return tuple(values[1:])
    if (
        len(values) >= 3
        and values[0] == "--cwd"
        and values[2] in {"ma", "multiagent"}
    ):
        return (*values[3:], "--cwd", values[1])
    if (
        len(values) >= 2
        and values[0].startswith("--cwd=")
        and values[1] in {"ma", "multiagent"}
    ):
        return (*values[2:], values[0])
    return None


def parse_multiagent_command(argv: Sequence[str]) -> MultiAgentCliCommand:
    values = list(argv)
    if not values:
        raise MultiAgentCliUsageError(
            "a command is required",
            usage="usage: loushang multiagent {recipes,run} ...\n",
        )
    command, *rest = values
    if command == "recipes":
        namespace = _recipes_parser().parse_args(rest)
        return MultiAgentRecipesCommand(
            output_format=namespace.output_format,
            help=namespace.help,
        )
    if command == "run":
        parser = _run_parser()
        return _run_command(parser.parse_intermixed_args(rest), parser=parser)
    raise MultiAgentCliUsageError(
        f"unknown multiagent command: {command}",
        usage="usage: loushang multiagent {recipes,run} ...\n",
    )


def multiagent_recipes_help() -> str:
    return _recipes_parser().format_help()


def multiagent_run_help() -> str:
    return _run_parser().format_help()


def resolve_multiagent_prompt(
    prompt: str | None,
    attachments: Sequence[str],
    *,
    cwd: Path,
) -> str:
    """Combine a recipe prompt with ordered UTF-8 ``@file`` attachments."""

    parts = [prompt.strip()] if prompt is not None and prompt.strip() else []
    for attachment in attachments:
        if not attachment.startswith("@") or len(attachment) == 1:
            raise ValueError(
                f"recipe attachments must use @path syntax: {attachment!r}"
            )
        path = Path(attachment[1:]).expanduser()
        path = path if path.is_absolute() else cwd / path
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"recipe attachment not found: {resolved}")
        parts.append(
            f"## Attached: {resolved}\n\n{resolved.read_text(encoding='utf-8')}"
        )
    if not parts:
        raise ValueError("recipe run requires --prompt and/or an @file attachment")
    return "\n\n".join(parts)


def resolve_multiagent_replicas(
    replicas: Mapping[str, int],
    count: int | None,
    *,
    recipe: CollaborationRecipe,
) -> dict[str, int]:
    """Project the convenience count onto the recipe's sole scalable role."""

    resolved = dict(replicas)
    if count is None:
        return resolved
    scalable = tuple(role for role in recipe.roles if role.scalable)
    if len(scalable) != 1:
        raise ValueError(
            "--count is valid only when the recipe has exactly one scalable role"
        )
    role = scalable[0]
    if role.name in resolved:
        raise ValueError(f"--count conflicts with --replicas {role.name}=...")
    resolved[role.name] = count
    return resolved


def write_multiagent_recipe_catalog(
    stdout: TextIO,
    recipes: Sequence[CollaborationRecipe],
    *,
    output_format: MultiAgentOutputFormat,
) -> None:
    if output_format == "json":
        stdout.write(
            json.dumps(
                [
                    {
                        "id": recipe.recipe_id,
                        "description": recipe.description,
                        "roles": [role.name for role in recipe.roles],
                    }
                    for recipe in recipes
                ],
                ensure_ascii=False,
            )
            + "\n"
        )
        return
    for recipe in recipes:
        stdout.write(f"{recipe.recipe_id}\n  {recipe.description}\n")


def write_multiagent_recipe_result(
    stdout: TextIO,
    result: RecipeExecutionResult,
    *,
    output_format: MultiAgentOutputFormat,
) -> None:
    if output_format == "json":
        stdout.write(
            json.dumps(
                {
                    "recipe": result.recipe_id,
                    "status": result.status,
                    "final_message": result.final_message,
                    "agents": [
                        {
                            "path": str(notice.sender_ref.path),
                            "status": notice.terminal.status,
                            "summary": notice.summary,
                            "final_message": notice.terminal.final_message,
                            "duration_ms": notice.terminal.duration_ms,
                            "usage": {
                                "latest_input_tokens": (
                                    notice.terminal.usage.latest_input_tokens
                                ),
                                "cumulative_output_tokens": (
                                    notice.terminal.usage.cumulative_output_tokens
                                ),
                            },
                            "tool_uses": notice.terminal.tool_uses,
                            "workspace_ref": notice.workspace_ref,
                            "artifact_refs": list(notice.artifact_refs),
                            "change_set_ref": notice.change_set_ref,
                        }
                        for notice in result.notices
                    ],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return
    stdout.write(f"{result.recipe_id} · {result.status}\n\n")
    for notice in result.notices:
        stdout.write(
            f"{notice.sender_ref.path} · {notice.terminal.status} · "
            f"{notice.terminal.duration_ms}ms\n"
        )
        if notice is not result.final_notice:
            stdout.write(f"  {notice.summary or notice.terminal.final_message}\n")
    stdout.write(f"\nResult\n{result.final_message}\n")


def _recipes_parser() -> _NoExitParser:
    parser = _NoExitParser(
        prog="loushang multiagent recipes",
        add_help=False,
        description="List immediate, session-owned collaboration recipes.",
    )
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--cwd", help=SUPPRESS)
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("plain", "json"),
        default="plain",
    )
    return parser


def _run_parser() -> _NoExitParser:
    parser = _NoExitParser(
        prog="loushang multiagent run",
        add_help=False,
        description="Run one immediate collaboration recipe.",
    )
    parser.add_argument("recipe_id", nargs="?")
    parser.add_argument("attachments", nargs="*")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--prompt", help="Question or task given to the recipe.")
    parser.add_argument("--cwd", help="Existing Product workspace directory.")
    parser.add_argument("--session-dir", help="Temporary session runtime directory.")
    parser.add_argument("--provider", help="Default model provider.")
    parser.add_argument(
        "--model",
        help="Default provider:model shorthand or provider:endpoint:model reference.",
    )
    parser.add_argument(
        "--thinking",
        choices=("off", "minimal", "low", "medium", "high", "xhigh"),
    )
    parser.add_argument(
        "--agent",
        action="append",
        default=[],
        metavar="ROLE=MODEL",
        help="Override one declared role's model; repeatable.",
    )
    parser.add_argument(
        "--replicas",
        action="append",
        default=[],
        metavar="ROLE=COUNT",
        help="Override one scalable role's replica count; repeatable.",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Alias when the recipe has exactly one scalable role.",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        help="Lower the number of concurrently running replicas.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Per-agent timeout in seconds (default: 600).",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("plain", "json"),
        default="plain",
    )
    return parser


def _run_command(
    namespace: Namespace,
    *,
    parser: _NoExitParser,
) -> MultiAgentRunCommand:
    if namespace.help:
        return MultiAgentRunCommand(
            recipe_id=namespace.recipe_id or "",
            prompt=namespace.prompt,
            attachments=tuple(namespace.attachments),
            cwd=namespace.cwd,
            session_dir=namespace.session_dir,
            provider=namespace.provider,
            model=namespace.model,
            thinking=namespace.thinking,
            agent_models={},
            replicas={},
            count=namespace.count,
            max_parallel=namespace.max_parallel,
            timeout=namespace.timeout,
            output_format=namespace.output_format,
            help=True,
        )
    if not namespace.recipe_id:
        raise MultiAgentCliUsageError(
            "run requires a recipe name",
            usage=parser.format_usage(),
        )
    return MultiAgentRunCommand(
        recipe_id=namespace.recipe_id,
        prompt=namespace.prompt,
        attachments=tuple(namespace.attachments),
        cwd=namespace.cwd,
        session_dir=namespace.session_dir,
        provider=namespace.provider,
        model=namespace.model,
        thinking=namespace.thinking,
        agent_models=_parse_assignments(
            namespace.agent,
            value_name="model",
            parser=parser,
        ),
        replicas={
            role: _positive_int(
                value,
                label=f"{role} replica count",
                parser=parser,
            )
            for role, value in _parse_assignments(
                namespace.replicas,
                value_name="count",
                parser=parser,
            ).items()
        },
        count=_optional_positive_int(namespace.count, label="count", parser=parser),
        max_parallel=_optional_positive_int(
            namespace.max_parallel,
            label="max-parallel",
            parser=parser,
        ),
        timeout=_positive_float(namespace.timeout, label="timeout", parser=parser),
        output_format=namespace.output_format,
    )


def _parse_assignments(
    values: Sequence[str],
    *,
    value_name: str,
    parser: _NoExitParser,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        role, separator, assigned = value.partition("=")
        if not separator or not role or not assigned:
            raise MultiAgentCliUsageError(
                f"expected ROLE={value_name}, got {value!r}",
                usage=parser.format_usage(),
            )
        if role in result:
            raise MultiAgentCliUsageError(
                f"duplicate role override: {role}",
                usage=parser.format_usage(),
            )
        result[role] = assigned
    return result


def _positive_int(
    value: str,
    *,
    label: str,
    parser: _NoExitParser,
) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise MultiAgentCliUsageError(
            f"{label} must be an integer",
            usage=parser.format_usage(),
        ) from error
    if parsed < 1:
        raise MultiAgentCliUsageError(
            f"{label} must be positive",
            usage=parser.format_usage(),
        )
    return parsed


def _optional_positive_int(
    value: int | None,
    *,
    label: str,
    parser: _NoExitParser,
) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise MultiAgentCliUsageError(
            f"{label} must be positive",
            usage=parser.format_usage(),
        )
    return value


def _positive_float(
    value: float,
    *,
    label: str,
    parser: _NoExitParser,
) -> float:
    if value <= 0:
        raise MultiAgentCliUsageError(
            f"{label} must be positive",
            usage=parser.format_usage(),
        )
    return value


__all__ = [
    "MultiAgentCliCommand",
    "MultiAgentCliUsageError",
    "MultiAgentOutputFormat",
    "MultiAgentRecipesCommand",
    "MultiAgentRunCommand",
    "extract_multiagent_argv",
    "multiagent_recipes_help",
    "multiagent_run_help",
    "parse_multiagent_command",
    "resolve_multiagent_prompt",
    "resolve_multiagent_replicas",
    "write_multiagent_recipe_catalog",
    "write_multiagent_recipe_result",
]
