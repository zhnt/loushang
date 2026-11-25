"""CLI execution and presentation for immediate collaboration recipes."""

from __future__ import annotations

import json
from argparse import SUPPRESS, Namespace
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO, TypeVar

from loushang.foundation.reasoning import THINKING_LEVELS
from loushang.harness.cli.parser import (
    CliCommandUsageError,
    RaisingArgumentParser,
    extract_root_command,
    write_usage_error,
)
from loushang.harness.model_catalog import (
    AiModelRegistry,
    ModelSelection,
    canonical_model_reference,
)
from loushang.harness.multiagent import (
    CollaborationRecipe,
    ImmediateRecipeExecutor,
    RecipeExecutionResult,
    RecipeRunRequest,
    core_recipe_catalog,
)
from loushang.harness.multiagent.executor import RecipeContextBuilder

MultiAgentOutputFormat = Literal["plain", "json"]


class MultiAgentCliUsageError(CliCommandUsageError):
    pass


class _NoExitParser(RaisingArgumentParser):
    usage_error_type = MultiAgentCliUsageError


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


_ServicesT = TypeVar("_ServicesT")


class _RecipeSessionRuntime(Protocol):
    async def create_session(self, *, cwd: str) -> object: ...

    async def dispose_session_runtime(self, *, metadata: dict[str, object]) -> None: ...


async def run_multiagent_command(
    argv: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    cwd: str | Path | None,
    services: _ServicesT | None,
    build_services: Callable[[Path], _ServicesT],
    resolve_default_model: Callable[
        [MultiAgentRunCommand, AiModelRegistry | None], ModelSelection | None
    ],
    prepare_runtime: Callable[
        [MultiAgentRunCommand, _ServicesT, ModelSelection | None],
        Callable[[], _RecipeSessionRuntime],
    ],
    bind_context: Callable[[], RecipeContextBuilder],
    product_label: str,
) -> int:
    """Run a recipe in one ephemeral Product session and release its ownership."""

    try:
        command = parse_multiagent_command(argv)
    except MultiAgentCliUsageError as error:
        return write_usage_error(stderr, error)

    if isinstance(command, MultiAgentRecipesCommand):
        if command.help:
            stdout.write(multiagent_recipes_help())
        else:
            write_multiagent_recipe_catalog(
                stdout,
                core_recipe_catalog().values(),
                output_format=command.output_format,
            )
        return 0
    if command.help:
        stdout.write(multiagent_run_help())
        return 0

    project_root = Path(command.cwd or cwd or Path.cwd()).expanduser().resolve()
    if not project_root.is_dir():
        stderr.write(f"Error: not a directory: {project_root}\n")
        return 2
    try:
        resolved_services = services or build_services(project_root)
    except Exception as error:
        stderr.write(f"Error: failed to prepare collaboration runtime: {error}\n")
        return 1

    selection_registry = getattr(
        getattr(resolved_services, "model_registry", None), "ai_registry", None
    )
    try:
        prompt = resolve_multiagent_prompt(
            command.prompt, command.attachments, cwd=project_root
        )
        catalog = core_recipe_catalog()
        recipe = catalog.resolve(command.recipe_id)
        if recipe is None:
            available = ", ".join(item.recipe_id for item in catalog.values())
            raise ValueError(
                f"unknown collaboration recipe {command.recipe_id!r}; available: {available}"
            )
        replicas = resolve_multiagent_replicas(
            command.replicas, command.count, recipe=recipe
        )
        role_models = _resolve_role_models(command, registry=selection_registry)
        default_model = resolve_default_model(command, selection_registry)
    except (KeyError, OSError, UnicodeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 2

    try:
        create_runtime = prepare_runtime(command, resolved_services, default_model)
    except Exception as error:
        stderr.write(f"Error: failed to prepare collaboration runtime: {error}\n")
        return 1

    runtime = None
    exit_code = 1
    try:
        runtime = create_runtime()
        session = await runtime.create_session(cwd=str(project_root))
        collaboration = getattr(session, "multiagent_runtime", None)
        if collaboration is None:
            raise RuntimeError(f"{product_label} multi-agent runtime was not installed")
        result = await ImmediateRecipeExecutor(
            collaboration, build_context=bind_context()
        ).run(
            recipe,
            RecipeRunRequest(
                prompt=prompt,
                replicas=replicas,
                agent_models=role_models,
                max_parallel=command.max_parallel,
                timeout=command.timeout,
            ),
        )
        write_multiagent_recipe_result(
            stdout, result, output_format=command.output_format
        )
        exit_code = 0 if result.status == "completed" else 1
    except TimeoutError as error:
        _write_execution_error(
            stderr,
            f"collaboration recipe timed out after {command.timeout:g}s",
            error,
        )
    except Exception as error:
        _write_execution_error(stderr, str(error), error)
    finally:
        if runtime is not None:
            try:
                await runtime.dispose_session_runtime(
                    metadata={"source": "multiagent_recipe"}
                )
            except Exception as error:
                _write_execution_error(
                    stderr, f"failed to release recipe runtime: {error}", error
                )
                exit_code = 1
    return exit_code


def _write_execution_error(stderr: TextIO, message: str, error: BaseException) -> None:
    stderr.write(f"Error: {message}\n")
    for note in getattr(error, "__notes__", ()):
        stderr.write(f"{note}\n")


def _resolve_role_models(
    command: MultiAgentRunCommand,
    *,
    registry: AiModelRegistry | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for role, value in command.agent_models.items():
        result[role] = canonical_model_reference(
            value,
            provider=command.provider
            if "/" not in value and ":" not in value
            else None,
            registry=registry,
        )
    return result


def extract_multiagent_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    return extract_root_command(argv, "ma", "multiagent", append_cwd=True)


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
        choices=THINKING_LEVELS,
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
    "run_multiagent_command",
    "write_multiagent_recipe_catalog",
    "write_multiagent_recipe_result",
]
