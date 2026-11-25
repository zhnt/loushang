"""Coding's CLI adapter for immediate, session-owned collaboration recipes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, TextIO

from loushang.ai.model import (
    ModelSelection,
    parse_model_selection_reference,
)
from loushang.ai.model.registry import ModelRegistry
from loushang.coding.composition.bootstrap import (
    BootstrapServices,
    create_agent_session_runtime,
)
from loushang.coding.session.multiagent import (
    coding_read_only_agent_types,
    coding_recipe_context_plan,
)
from loushang.harness.cli.agent_args import resolve_cli_session_dir
from loushang.harness.cli.multiagent import MultiAgentRunCommand, run_multiagent_command
from loushang.harness.cli.session_resolution import prepare_platform_session_directory
from loushang.harness.environment import resolve_platform_paths
from loushang.harness.multiagent.executor import RecipeContextBuilder
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
    return await run_multiagent_command(
        argv,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        services=services,
        build_services=build_services,
        resolve_default_model=_resolve_default_model,
        prepare_runtime=partial(
            _prepare_runtime,
            build_tool_registry=build_tool_registry,
            runtime_builder=runtime_builder,
        ),
        bind_context=_bind_context,
        product_label="Coding",
    )


def _prepare_runtime(
    command: MultiAgentRunCommand,
    services: BootstrapServices,
    model: ModelSelection | None,
    *,
    build_tool_registry: ToolRegistryBuilder,
    runtime_builder: RuntimeBuilder,
) -> Callable[[], Any]:
    stream_fn = None
    if command.provider == "scripted":
        from loushang.coding.cli.multiagent_scripted import (
            scripted_multiagent_services,
            scripted_multiagent_stream,
        )

        services = scripted_multiagent_services(services)
        stream_fn = scripted_multiagent_stream
    settings_manager = getattr(services, "settings_manager", None)
    tool_settings = workspace_tool_runtime_settings(
        settings_manager, policy_factory=PolicyEngine
    )
    session_dir = (
        resolve_cli_session_dir(command.session_dir, settings_manager=settings_manager)
        if command.session_dir or settings_manager is not None
        else resolve_platform_paths().data / "sessions"
    )
    platform_sessions = resolve_platform_paths().data / "sessions"
    if session_dir == platform_sessions:
        prepare_platform_session_directory(platform_sessions)
    tool_registry = build_tool_registry(
        diagnostics_service=getattr(services, "diagnostics_service", None),
        settings_manager=settings_manager,
    )
    def create_runtime() -> Any:
        options = {"stream_fn": stream_fn} if stream_fn is not None else {}
        return runtime_builder(
            session_dir=session_dir,
            model=model,
            thinking_level=command.thinking,
            tool_registry=tool_registry,
            services=services,
            persist=False,
            enable_multiagent=True,
            approval_resolver=tool_settings.approval_resolver,
            tool_policy_evaluator=tool_settings.policy_engine,
            **options,
        )

    return create_runtime


def _bind_context() -> RecipeContextBuilder:
    agent_types = coding_read_only_agent_types()
    return lambda role, model: coding_recipe_context_plan(
        agent_type=role.agent_type,
        model=model,
        agent_types=agent_types,
    )


def _resolve_default_model(
    command: MultiAgentRunCommand,
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


__all__ = [
    "run_coding_multiagent_command",
]
