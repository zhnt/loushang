"""Coding's selected workspace-tool pack.

Concrete workspace tools, their protocols, and their render/runtime helpers are
owned by :mod:`loushang.harness.tools.workspace`.  This module only describes
how the Coding product selects and configures that reusable capability.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from loushang.agent.types import AgentTool
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.tools.authoring import ToolContextProvider
from loushang.harness.tools.contribution import ToolPackDefinition
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.external_tools import (
    ExternalToolDownloader,
    ExternalToolPolicy,
    ExternalToolResolver,
)
from loushang.harness.tools.workspace.factory import (
    CORE_WORKSPACE_TOOL_NAMES,
    ToolName,
    ToolsOptions,
    WorkspaceToolProfile,
    create_profiled_workspace_tool_definition,
    create_profiled_workspace_tool_definitions,
    create_profiled_workspace_tools,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.operations import ToolOperations

CODING_TOOL_NAMES: tuple[ToolName, ...] = CORE_WORKSPACE_TOOL_NAMES
CODING_BUILTIN_TOOL_NAMES: tuple[ToolName, ...] = (
    "bash",
    "read",
    "ls",
    "find",
    "grep",
    "write",
    "edit",
)

_CODING_TOOL_TEXT: dict[ToolName, tuple[str, str]] = {
    "read": (
        "Read text files and images from the coding workspace. "
        "For large text files, use offset and limit to continue reading.",
        "- read: Read text files and images from the coding workspace.",
    ),
    "bash": (
        "Execute a shell command through the coding exec service.",
        "- bash: Execute shell commands. Prefer a single command string; use cwd for the working directory.",
    ),
    "shell": (
        "Execute a PowerShell script through the coding exec service. Use Windows PowerShell 5.1-compatible syntax unless PowerShell 7 availability is known.",
        "- shell: Execute PowerShell scripts on Windows using PowerShell syntax.",
    ),
    "edit": (
        "Apply exact text replacements to a file in the coding workspace.",
        "- edit: Apply exact text replacements to a file in the coding workspace.",
    ),
    "write": (
        "Write a text file in the coding workspace.",
        "- write: Write a text file in the coding workspace.",
    ),
    "grep": (
        "Search file contents in the coding workspace.",
        "- grep: Search file contents for patterns in the coding workspace.",
    ),
    "find": (
        "Find file paths in the coding workspace.",
        "- find: Find file paths by glob pattern in the coding workspace.",
    ),
    "ls": (
        "List directory entries in the coding workspace.",
        "- ls: List directory entries in the coding workspace.",
    ),
}


def _decorate_coding_tool_definition(
    definition: ToolDefinition,
) -> ToolDefinition:
    description, prompt_snippet = _CODING_TOOL_TEXT[
        cast(ToolName, definition.name)
    ]
    return replace(
        definition,
        description=description,
        prompt_snippet=prompt_snippet,
    )


CODING_WORKSPACE_TOOL_PROFILE = WorkspaceToolProfile(
    profile_id="coding.workspace",
    tool_names=CODING_TOOL_NAMES,
    builtin_tool_names=CODING_BUILTIN_TOOL_NAMES,
    pack_id="coding.builtin",
    decorate_definition=_decorate_coding_tool_definition,
)
CODING_BUILTIN_TOOL_PACK = ToolPackDefinition(
    name=CODING_WORKSPACE_TOOL_PROFILE.pack_id,
    tools=CODING_WORKSPACE_TOOL_PROFILE.builtin_tool_names,
)


def coding_workspace_tool_profile(
    environment: HostEnvironment,
) -> WorkspaceToolProfile:
    """Select the command tool from execution-target facts."""

    if environment.os_family != "windows":
        return CODING_WORKSPACE_TOOL_PROFILE
    return replace(
        CODING_WORKSPACE_TOOL_PROFILE,
        tool_names=tuple(
            "shell" if name == "bash" else name for name in CODING_TOOL_NAMES
        ),
        builtin_tool_names=tuple(
            "shell" if name == "bash" else name
            for name in CODING_BUILTIN_TOOL_NAMES
        ),
    )


def _profile_from_options(options: ToolsOptions | None) -> WorkspaceToolProfile:
    environment = options.host_environment if options is not None else None
    return (
        coding_workspace_tool_profile(environment)
        if environment is not None
        else CODING_WORKSPACE_TOOL_PROFILE
    )


def create_coding_tool_definition(
    tool_name: ToolName,
    *,
    options: ToolsOptions | None = None,
) -> ToolDefinition:
    """Create a workspace definition with Coding's selected copy."""

    return create_profiled_workspace_tool_definition(
        _profile_from_options(options),
        tool_name,
        options=options,
    )


def create_coding_tool_definitions(
    *, options: ToolsOptions | None = None
) -> list[ToolDefinition]:
    return create_profiled_workspace_tool_definitions(
        _profile_from_options(options),
        options=options,
    )


def create_coding_tools(
    *,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> list[AgentTool[Any]]:
    return create_profiled_workspace_tools(
        _profile_from_options(options),
        cwd=cwd,
        options=options,
        context_provider=context_provider,
        model=model,
    )


def register_coding_builtin_tools(
    registry: WorkspaceToolRegistry,
    *,
    exec_service: ExecService | None = None,
    diagnostics_service: DiagnosticsService | None = None,
    operations: ToolOperations | None = None,
    external_tool_resolver: ExternalToolResolver | None = None,
    external_tool_downloader: ExternalToolDownloader | None = None,
    external_tool_policy: ExternalToolPolicy | None = None,
    allow_external_tool_downloads: bool = False,
    require_external_tools: bool = False,
    host_environment: HostEnvironment | None = None,
    shell_path: str | None = None,
    command_prefix: str | None = None,
) -> WorkspaceToolRegistry:
    resolved_environment = host_environment or LocalHostEnvironmentProbe().detect()
    profile = coding_workspace_tool_profile(resolved_environment)
    options = ToolsOptions(
        exec_service=exec_service or ExecService(),
        diagnostics_service=diagnostics_service,
        operations=operations,
        external_tool_resolver=external_tool_resolver,
        external_tool_downloader=external_tool_downloader,
        external_tool_policy=external_tool_policy,
        allow_external_tool_downloads=allow_external_tool_downloads,
        require_external_tools=require_external_tools,
        host_environment=resolved_environment,
        shell_path=shell_path,
        command_prefix=command_prefix,
    )
    return registry.register_profile(
        profile,
        options=options,
    )


__all__ = [
    "CODING_BUILTIN_TOOL_NAMES",
    "CODING_BUILTIN_TOOL_PACK",
    "CODING_TOOL_NAMES",
    "CODING_WORKSPACE_TOOL_PROFILE",
    "coding_workspace_tool_profile",
    "create_coding_tool_definition",
    "create_coding_tool_definitions",
    "create_coding_tools",
    "register_coding_builtin_tools",
]
