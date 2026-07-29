"""Coding's CLI adapter for immediate, session-owned collaboration recipes."""

from __future__ import annotations

import json
from argparse import SUPPRESS, ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO

from loushang.ai.model import (
    ModelSelection,
    model_selection_ref,
    parse_model_selection_reference,
)
from loushang.coding.bootstrap import BootstrapServices, create_agent_session_runtime
from loushang.coding.multiagent import (
    coding_read_only_agent_types,
    coding_recipe_context_plan,
)
from loushang.harness.multiagent import (
    CollaborationRecipe,
    ImmediateRecipeExecutor,
    RecipeExecutionResult,
    RecipeRunRequest,
    core_recipe_catalog,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.tools.workspace.factory import (
    workspace_tool_runtime_settings,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

RecipeOutputFormat = Literal["plain", "json"]


class MultiAgentCliUsageError(ValueError):
    def __init__(self, message: str, *, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _NoExitParser(ArgumentParser):
    def error(self, message: str) -> None:
        raise MultiAgentCliUsageError(message, usage=self.format_usage())


@dataclass(frozen=True, slots=True)
class MultiAgentRecipesCommand:
    output_format: RecipeOutputFormat = "plain"
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
    output_format: RecipeOutputFormat
    help: bool = False


MultiAgentCliCommand = MultiAgentRecipesCommand | MultiAgentRunCommand
RuntimeBuilder = Callable[..., Any]
ServicesBuilder = Callable[[Path], BootstrapServices]
ToolRegistryBuilder = Callable[..., WorkspaceToolRegistry]


def extract_multiagent_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    """Extract `ma`/`multiagent`, preserving a leading common `--cwd`."""

    values = list(argv)
    if values and values[0] in {"ma", "multiagent"}:
        return tuple(values[1:])
    if (
        len(values) >= 3
        and values[0] == "--cwd"
        and values[2]
        in {
            "ma",
            "multiagent",
        }
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
        parser = _recipes_parser()
        namespace = parser.parse_args(rest)
        return MultiAgentRecipesCommand(
            output_format=namespace.output_format,
            help=namespace.help,
        )
    if command == "run":
        parser = _run_parser()
        namespace = parser.parse_intermixed_args(rest)
        return _run_command(namespace)
    raise MultiAgentCliUsageError(
        f"unknown multiagent command: {command}",
        usage="usage: loushang multiagent {recipes,run} ...\n",
    )


async def run_coding_multiagent_command(
    argv: Sequence[str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO,
    stderr: TextIO,
    cwd: str | Path | None = None,
    services: BootstrapServices | Any | None = None,
    build_services: ServicesBuilder,
    build_tool_registry: ToolRegistryBuilder,
    runtime_builder: RuntimeBuilder = create_agent_session_runtime,
) -> int:
    """Parse and run one Coding collaboration command."""

    del stdin
    try:
        command = parse_multiagent_command(argv)
    except MultiAgentCliUsageError as error:
        stderr.write(error.usage)
        stderr.write(f"Error: {error}\n")
        return 2

    if isinstance(command, MultiAgentRecipesCommand):
        if command.help:
            stdout.write(_recipes_parser().format_help())
            return 0
        _write_recipe_catalog(stdout, output_format=command.output_format)
        return 0
    if command.help:
        stdout.write(_run_parser().format_help())
        return 0

    project_root = Path(command.cwd or cwd or Path.cwd()).expanduser().resolve()
    if not project_root.is_dir():
        stderr.write(f"Error: not a directory: {project_root}\n")
        return 2
    try:
        prompt = _resolve_prompt(
            command.prompt,
            command.attachments,
            cwd=project_root,
        )
        recipe = core_recipe_catalog().resolve(command.recipe_id)
        if recipe is None:
            available = ", ".join(
                item.recipe_id for item in core_recipe_catalog().values()
            )
            raise ValueError(
                f"unknown collaboration recipe {command.recipe_id!r}; "
                f"available: {available}"
            )
        replicas = _resolve_replicas(command, recipe)
        role_models = _resolve_role_models(
            command.agent_models,
            provider=command.provider,
        )
        default_model = _resolve_default_model(command)
    except (OSError, UnicodeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 2

    try:
        resolved_services = services or build_services(project_root)
        stream_fn = None
        if command.provider == "scripted":
            from loushang.coding.cli.multiagent_scripted import (
                scripted_multiagent_services,
                scripted_multiagent_stream,
            )

            resolved_services = scripted_multiagent_services(resolved_services)
            stream_fn = scripted_multiagent_stream
        settings_manager = getattr(resolved_services, "settings_manager", None)
        tool_settings = workspace_tool_runtime_settings(
            settings_manager,
            policy_factory=PolicyEngine,
        )
        session_dir = _resolve_session_dir(
            command.session_dir,
            project_root=project_root,
            settings_manager=settings_manager,
        )
        registry = build_tool_registry(
            diagnostics_service=getattr(
                resolved_services,
                "diagnostics_service",
                None,
            ),
            settings_manager=settings_manager,
        )
    except Exception as error:
        stderr.write(f"Error: failed to prepare collaboration runtime: {error}\n")
        return 1
    runtime = None
    exit_code = 1
    try:
        runtime_options: dict[str, object] = {
            "session_dir": session_dir,
            "model": default_model,
            "thinking_level": command.thinking,
            "tool_registry": registry,
            "services": resolved_services,
            "persist": False,
            "enable_multiagent": True,
            "approval_resolver": tool_settings.approval_resolver,
            "tool_policy_evaluator": tool_settings.policy_engine,
        }
        if stream_fn is not None:
            runtime_options["stream_fn"] = stream_fn
        runtime = runtime_builder(
            **runtime_options,
        )
        session = await runtime.create_session(cwd=str(project_root))
        collaboration = getattr(session, "multiagent_runtime", None)
        if collaboration is None:
            raise RuntimeError("Coding multi-agent runtime was not installed")
        agent_types = coding_read_only_agent_types()
        executor = ImmediateRecipeExecutor(
            collaboration,
            build_context=lambda role, model: coding_recipe_context_plan(
                agent_type=role.agent_type,
                model=model,
                agent_types=agent_types,
            ),
        )
        result = await executor.run(
            recipe,
            RecipeRunRequest(
                prompt=prompt,
                replicas=replicas,
                agent_models=role_models,
                max_parallel=command.max_parallel,
                timeout=command.timeout,
            ),
        )
        _write_recipe_result(
            stdout,
            result,
            output_format=command.output_format,
        )
        exit_code = 0 if result.status == "completed" else 1
    except TimeoutError:
        stderr.write(
            f"Error: collaboration recipe timed out after {command.timeout:g}s\n"
        )
    except Exception as error:
        stderr.write(f"Error: {error}\n")
    finally:
        if runtime is not None:
            try:
                await runtime.dispose_session_runtime(
                    metadata={"source": "multiagent_recipe"},
                )
            except Exception as error:
                stderr.write(f"Error: failed to release recipe runtime: {error}\n")
                exit_code = 1
    return exit_code


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
    parser.add_argument("--model", help="Default model or provider/model reference.")
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


def _run_command(namespace: Namespace) -> MultiAgentRunCommand:
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
            usage=_run_parser().format_usage(),
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
        agent_models=_parse_assignments(namespace.agent, value_name="model"),
        replicas={
            role: _positive_int(value, label=f"{role} replica count")
            for role, value in _parse_assignments(
                namespace.replicas,
                value_name="count",
            ).items()
        },
        count=_optional_positive_int(namespace.count, label="count"),
        max_parallel=_optional_positive_int(
            namespace.max_parallel,
            label="max-parallel",
        ),
        timeout=_positive_float(namespace.timeout, label="timeout"),
        output_format=namespace.output_format,
    )


def _parse_assignments(
    values: Sequence[str],
    *,
    value_name: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        role, separator, assigned = value.partition("=")
        if not separator or not role or not assigned:
            raise MultiAgentCliUsageError(
                f"expected ROLE={value_name}, got {value!r}",
                usage=_run_parser().format_usage(),
            )
        if role in result:
            raise MultiAgentCliUsageError(
                f"duplicate role override: {role}",
                usage=_run_parser().format_usage(),
            )
        result[role] = assigned
    return result


def _positive_int(value: str, *, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise MultiAgentCliUsageError(
            f"{label} must be an integer",
            usage=_run_parser().format_usage(),
        ) from error
    if parsed < 1:
        raise MultiAgentCliUsageError(
            f"{label} must be positive",
            usage=_run_parser().format_usage(),
        )
    return parsed


def _optional_positive_int(value: int | None, *, label: str) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise MultiAgentCliUsageError(
            f"{label} must be positive",
            usage=_run_parser().format_usage(),
        )
    return value


def _positive_float(value: float, *, label: str) -> float:
    if value <= 0:
        raise MultiAgentCliUsageError(
            f"{label} must be positive",
            usage=_run_parser().format_usage(),
        )
    return value


def _resolve_prompt(
    prompt: str | None,
    attachments: tuple[str, ...],
    *,
    cwd: Path,
) -> str:
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


def _resolve_replicas(
    command: MultiAgentRunCommand,
    recipe: CollaborationRecipe,
) -> dict[str, int]:
    replicas = dict(command.replicas)
    if command.count is None:
        return replicas
    scalable = tuple(role for role in recipe.roles if role.scalable)
    if len(scalable) != 1:
        raise ValueError(
            "--count is valid only when the recipe has exactly one scalable role"
        )
    role = scalable[0]
    if role.name in replicas:
        raise ValueError(f"--count conflicts with --replicas {role.name}=...")
    replicas[role.name] = command.count
    return replicas


def _resolve_role_models(
    values: Mapping[str, str],
    *,
    provider: str | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for role, value in values.items():
        selection = parse_model_selection_reference(
            value,
            provider=(provider if "/" not in value and value.count(":") < 2 else None),
        )
        assert selection is not None
        result[role] = model_selection_ref(selection)
    return result


def _resolve_default_model(
    command: MultiAgentRunCommand,
) -> ModelSelection | None:
    if command.provider == "scripted":
        from loushang.coding.cli.multiagent_scripted import SCRIPTED_MODEL

        if command.model not in {None, SCRIPTED_MODEL.model_id}:
            raise ValueError(
                "--provider scripted uses the fixed multiagent-check model"
            )
        return SCRIPTED_MODEL
    return parse_model_selection_reference(
        command.model,
        provider=command.provider,
    )


def _resolve_session_dir(
    value: str | None,
    *,
    project_root: Path,
    settings_manager: object | None,
) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    get_settings = getattr(settings_manager, "get_settings", None)
    if callable(get_settings):
        configured = getattr(get_settings(), "session_dir", None)
        if configured:
            return Path(configured).expanduser().resolve()
    return project_root / ".loushang" / "sessions"


def _write_recipe_catalog(
    stdout: TextIO,
    *,
    output_format: RecipeOutputFormat,
) -> None:
    recipes = core_recipe_catalog().values()
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


def _write_recipe_result(
    stdout: TextIO,
    result: RecipeExecutionResult,
    *,
    output_format: RecipeOutputFormat,
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


__all__ = [
    "MultiAgentCliCommand",
    "MultiAgentCliUsageError",
    "MultiAgentRecipesCommand",
    "MultiAgentRunCommand",
    "extract_multiagent_argv",
    "parse_multiagent_command",
    "run_coding_multiagent_command",
]
