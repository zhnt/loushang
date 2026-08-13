"""Coding's CLI adapter for immediate, session-owned collaboration recipes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from loushang.ai.model import (
    ModelSelection,
    model_selection_ref,
    parse_model_selection_reference,
)
from loushang.ai.model.registry import ModelRegistry
from loushang.coding.bootstrap import BootstrapServices, create_agent_session_runtime
from loushang.coding.multiagent import (
    coding_read_only_agent_types,
    coding_recipe_context_plan,
)
from loushang.harness.cli.multiagent import (
    MultiAgentCliUsageError,
    MultiAgentRecipesCommand,
    MultiAgentRunCommand,
    multiagent_recipes_help,
    multiagent_run_help,
    parse_multiagent_command,
    resolve_multiagent_prompt,
    resolve_multiagent_replicas,
    write_multiagent_recipe_catalog,
    write_multiagent_recipe_result,
)
from loushang.harness.multiagent import (
    ImmediateRecipeExecutor,
    RecipeRunRequest,
    core_recipe_catalog,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.tools.workspace.factory import (
    workspace_tool_runtime_settings,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

RuntimeBuilder = Callable[..., Any]
ServicesBuilder = Callable[[Path], BootstrapServices]
ToolRegistryBuilder = Callable[..., WorkspaceToolRegistry]


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
            stdout.write(multiagent_recipes_help())
            return 0
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
        getattr(resolved_services, "model_registry", None),
        "ai_registry",
        None,
    )
    try:
        prompt = resolve_multiagent_prompt(
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
        replicas = resolve_multiagent_replicas(
            command.replicas,
            command.count,
            recipe=recipe,
        )
        role_models = _resolve_role_models(
            command.agent_models,
            provider=command.provider,
            registry=selection_registry,
        )
        default_model = _resolve_default_model(command, registry=selection_registry)
    except (KeyError, OSError, UnicodeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 2

    try:
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
        tool_registry = build_tool_registry(
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
            "tool_registry": tool_registry,
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
        write_multiagent_recipe_result(
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


def _resolve_default_model(
    command: MultiAgentRunCommand,
    *,
    registry: ModelRegistry | None = None,
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
        registry=registry,
    )


def _resolve_role_models(
    values: Mapping[str, str],
    *,
    provider: str | None,
    registry: ModelRegistry | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for role, value in values.items():
        selection = parse_model_selection_reference(
            value,
            provider=(provider if "/" not in value and ":" not in value else None),
            registry=registry,
        )
        assert selection is not None
        result[role] = model_selection_ref(selection)
    return result


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


__all__ = [
    "run_coding_multiagent_command",
]
