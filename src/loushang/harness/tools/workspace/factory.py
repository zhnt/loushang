from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from loushang.agent.types import AgentTool
from loushang.harness.approval import (
    ApprovalResolver,
    HeadlessApprovalResolver,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.permissions import (
    PermissionProfileCeiling,
    PermissionProfilePolicyEvaluator,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.tools.authoring import ToolContext, ToolContextProvider
from loushang.harness.tools.execution import ToolExecutionHost
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.operations import (
    EditOperations,
    FindOperations,
    GrepOperations,
    LsOperations,
    ReadOperations,
    ToolOperations,
    WriteOperations,
)

from .authorization import WorkspaceToolAuthorizationGateway
from .bash import (
    BashOperations,
    BashSpawnHook,
    BashToolOptions,
    create_bash_tool_definition,
)
from .edit import EditToolOptions, create_edit_tool_definition
from .external_tools import (
    ExternalToolDownloader,
    ExternalToolPolicy,
    ExternalToolResolver,
    GitHubReleaseExternalToolDownloader,
    external_tool_required_for_policy,
    normalize_external_tool_policy,
)
from .find import FindToolOptions, create_find_tool_definition
from .grep import GrepToolOptions, create_grep_tool_definition
from .ls import LsToolOptions, create_ls_tool_definition
from .policy import ToolPolicyEvaluator
from .read import ReadToolOptions, create_read_tool_definition
from .types import ToolDefinition
from .wrapper import wrap_tool_definition
from .write import WriteToolOptions, create_write_tool_definition

ToolName = Literal["read", "bash", "edit", "write", "grep", "find", "ls"]
Tool = AgentTool[Any]
ToolDef = ToolDefinition
ALL_TOOL_NAMES: tuple[ToolName, ...] = (
    "read",
    "bash",
    "edit",
    "write",
    "grep",
    "find",
    "ls",
)
CORE_WORKSPACE_TOOL_NAMES: tuple[ToolName, ...] = ("read", "bash", "edit", "write")
READ_ONLY_TOOL_NAMES: tuple[ToolName, ...] = ("read", "grep", "find", "ls")
allToolNames: set[ToolName] = set(ALL_TOOL_NAMES)
coreWorkspaceToolNames: set[ToolName] = set(CORE_WORKSPACE_TOOL_NAMES)
readOnlyToolNames: set[ToolName] = set(READ_ONLY_TOOL_NAMES)


def _identity_tool_definition(definition: ToolDefinition) -> ToolDefinition:
    return definition


@dataclass(frozen=True)
class WorkspaceToolProfile:
    """Product selections and definition decoration for workspace tools."""

    profile_id: str
    tool_names: tuple[ToolName, ...] = CORE_WORKSPACE_TOOL_NAMES
    builtin_tool_names: tuple[ToolName, ...] = CORE_WORKSPACE_TOOL_NAMES
    pack_id: str = "workspace.builtin"
    decorate_definition: Callable[[ToolDefinition], ToolDefinition] = field(
        default=_identity_tool_definition,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id:
            raise ValueError("workspace tool profile id must be a non-empty string")
        if not isinstance(self.pack_id, str) or not self.pack_id:
            raise ValueError("workspace tool pack id must be a non-empty string")
        tool_names = _validated_tool_names(self.tool_names, name="tool_names")
        builtin_tool_names = _validated_tool_names(
            self.builtin_tool_names,
            name="builtin_tool_names",
        )
        if not callable(self.decorate_definition):
            raise TypeError("workspace tool definition decorator must be callable")
        object.__setattr__(self, "tool_names", tool_names)
        object.__setattr__(self, "builtin_tool_names", builtin_tool_names)


@dataclass(frozen=True)
class ToolsOptions:
    read: ReadToolOptions | None = None
    bash: BashToolOptions | None = None
    write: WriteToolOptions | None = None
    edit: EditToolOptions | None = None
    grep: GrepToolOptions | None = None
    find: FindToolOptions | None = None
    ls: LsToolOptions | None = None
    operations: ToolOperations | None = None
    read_operations: ReadOperations | None = None
    ls_operations: LsOperations | None = None
    find_operations: FindOperations | None = None
    grep_operations: GrepOperations | None = None
    write_operations: WriteOperations | None = None
    edit_operations: EditOperations | None = None
    exec_service: ExecService | None = None
    diagnostics_service: DiagnosticsService | None = None
    bash_operations: BashOperations | None = None
    command_prefix: str | None = None
    shell_path: str | None = None
    spawn_hook: BashSpawnHook | None = None
    external_tool_resolver: ExternalToolResolver | None = None
    external_tool_downloader: ExternalToolDownloader | None = None
    external_tool_policy: ExternalToolPolicy | None = None
    allow_external_tool_downloads: bool = False
    require_external_tools: bool = False


@dataclass(frozen=True)
class WorkspaceToolRuntimeSettings:
    policy_engine: ToolPolicyEvaluator | None = None
    approval_resolver: ApprovalResolver | None = None


def workspace_tool_runtime_settings(
    settings_manager: object | None,
    *,
    policy_factory: Callable[..., ToolPolicyEvaluator] = PolicyEngine,
) -> WorkspaceToolRuntimeSettings:
    """Resolve standard tool policy and headless approval settings."""

    tool_settings = _tool_settings(settings_manager)
    if tool_settings is None:
        return WorkspaceToolRuntimeSettings(policy_engine=policy_factory())
    policy_kwargs = {
        "blocked_tools": _string_tuple(tool_settings, "blocked_tools"),
        "ask_tools": _string_tuple(tool_settings, "ask_tools"),
        "blocked_substrings": _string_tuple(tool_settings, "blocked_substrings"),
        "ask_substrings": _string_tuple(tool_settings, "ask_substrings"),
        "blocked_path_substrings": _string_tuple(
            tool_settings, "blocked_path_substrings"
        ),
        "ask_path_substrings": _string_tuple(
            tool_settings, "ask_path_substrings"
        ),
    }
    base_policy_engine = policy_factory(**policy_kwargs)
    profile_getter = getattr(settings_manager, "get_permission_profile_id", None)
    ceiling_getter = getattr(
        settings_manager,
        "get_permission_profile_ceiling",
        None,
    )
    policy_engine = (
        PermissionProfilePolicyEvaluator(
            base_policy_engine,
            profile_provider=profile_getter,
            ceiling_provider=(
                ceiling_getter
                if callable(ceiling_getter)
                else PermissionProfileCeiling
            ),
        )
        if callable(profile_getter)
        else base_policy_engine
    )
    approval_mode = getattr(tool_settings, "approval_mode", None)
    approval_resolver = (
        HeadlessApprovalResolver(
            mode=approval_mode,
            reason=getattr(tool_settings, "approval_reason", None),
        )
        if approval_mode is not None
        else None
    )
    return WorkspaceToolRuntimeSettings(
        policy_engine=policy_engine,
        approval_resolver=approval_resolver,
    )


def _tool_settings(settings_manager: object | None) -> object | None:
    get_tool_settings = getattr(settings_manager, "get_tool_settings", None)
    if callable(get_tool_settings):
        return get_tool_settings()
    get_settings = getattr(settings_manager, "get_settings", None)
    if callable(get_settings):
        return getattr(get_settings(), "tools", None)
    return None


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    items = getattr(value, name, ())
    if not isinstance(items, list | tuple):
        return ()
    return tuple(item for item in items if isinstance(item, str))


def create_tool_definition(
    tool_name: ToolName, *, options: ToolsOptions | None = None
) -> ToolDefinition:
    options = options or ToolsOptions()
    if tool_name == "read":
        return create_read_tool_definition(
            options=options.read,
            operations=options.read_operations or options.operations,
        )
    if tool_name == "bash":
        return create_bash_tool_definition(
            options=options.bash,
            exec_service=options.exec_service,
            diagnostics_service=options.diagnostics_service,
            operations=options.bash_operations,
            command_prefix=options.command_prefix,
            shell_path=options.shell_path,
            spawn_hook=options.spawn_hook,
        )
    if tool_name == "edit":
        return create_edit_tool_definition(
            options=options.edit,
            operations=options.edit_operations or options.operations,
        )
    if tool_name == "write":
        return create_write_tool_definition(
            options=options.write,
            operations=options.write_operations or options.operations,
        )
    if tool_name == "grep":
        return create_grep_tool_definition(
            options=_grep_options(options),
            operations=options.grep_operations or options.operations,
        )
    if tool_name == "find":
        return create_find_tool_definition(
            options=_find_options(options),
            operations=options.find_operations or options.operations,
        )
    if tool_name == "ls":
        return create_ls_tool_definition(
            options=options.ls,
            operations=options.ls_operations or options.operations,
        )
    raise ValueError(f"Unknown tool name: {tool_name}")


def create_profiled_workspace_tool_definition(
    profile: WorkspaceToolProfile,
    tool_name: ToolName,
    *,
    options: ToolsOptions | None = None,
) -> ToolDefinition:
    """Create and decorate one definition selected by a Product profile."""

    if tool_name not in (*profile.tool_names, *profile.builtin_tool_names):
        raise ValueError(
            f"workspace tool {tool_name!r} is not selected by {profile.profile_id!r}"
        )
    definition = profile.decorate_definition(
        create_tool_definition(tool_name, options=options)
    )
    if not isinstance(definition, ToolDefinition):
        raise TypeError("workspace tool decorator must return ToolDefinition")
    if definition.name != tool_name:
        raise ValueError("workspace tool decorator must preserve the tool name")
    return definition


def create_profiled_workspace_tool_definitions(
    profile: WorkspaceToolProfile,
    *,
    options: ToolsOptions | None = None,
    tool_names: Iterable[ToolName] | None = None,
) -> list[ToolDefinition]:
    """Create an ordered definition list for a Product workspace profile."""

    selected = (
        profile.tool_names
        if tool_names is None
        else _validated_tool_names(tool_names, name="tool_names")
    )
    return [
        create_profiled_workspace_tool_definition(
            profile,
            tool_name,
            options=options,
        )
        for tool_name in selected
    ]


def _find_options(options: ToolsOptions) -> FindToolOptions | None:
    factory_policy = _external_tool_policy(options)
    if (
        factory_policy is None
        and options.external_tool_resolver is None
        and options.external_tool_downloader is None
        and not options.allow_external_tool_downloads
        and not options.require_external_tools
    ):
        return options.find
    current = options.find or FindToolOptions()
    policy = current.external_tool_policy or factory_policy
    return replace(
        current,
        external_tool_resolver=current.external_tool_resolver
        or options.external_tool_resolver,
        external_tool_downloader=current.external_tool_downloader
        or _external_tool_downloader(options, policy),
        external_tool_policy=policy,
        allow_external_tool_downloads=current.allow_external_tool_downloads
        or options.allow_external_tool_downloads,
        require_external_tool=current.require_external_tool
        or external_tool_required_for_policy(
            policy, require=options.require_external_tools
        ),
    )


def _grep_options(options: ToolsOptions) -> GrepToolOptions | None:
    factory_policy = _external_tool_policy(options)
    if (
        factory_policy is None
        and options.external_tool_resolver is None
        and options.external_tool_downloader is None
        and not options.allow_external_tool_downloads
        and not options.require_external_tools
    ):
        return options.grep
    current = options.grep or GrepToolOptions()
    policy = current.external_tool_policy or factory_policy
    return replace(
        current,
        external_tool_resolver=current.external_tool_resolver
        or options.external_tool_resolver,
        external_tool_downloader=current.external_tool_downloader
        or _external_tool_downloader(options, policy),
        external_tool_policy=policy,
        allow_external_tool_downloads=current.allow_external_tool_downloads
        or options.allow_external_tool_downloads,
        require_external_tool=current.require_external_tool
        or external_tool_required_for_policy(
            policy, require=options.require_external_tools
        ),
    )


def _external_tool_policy(options: ToolsOptions) -> ExternalToolPolicy | None:
    return normalize_external_tool_policy(
        options.external_tool_policy,
        allow_download=options.allow_external_tool_downloads,
    )


def _external_tool_downloader(
    options: ToolsOptions,
    policy: ExternalToolPolicy | None,
) -> ExternalToolDownloader | None:
    if policy == "never":
        return None
    if options.external_tool_downloader is not None:
        return options.external_tool_downloader
    if policy in {"auto", "required"} or options.allow_external_tool_downloads:
        return GitHubReleaseExternalToolDownloader()
    return None


def create_core_workspace_tool_definitions(
    *, options: ToolsOptions | None = None
) -> list[ToolDefinition]:
    return [
        create_tool_definition(tool_name, options=options)
        for tool_name in CORE_WORKSPACE_TOOL_NAMES
    ]


def create_read_only_tool_definitions(
    *, options: ToolsOptions | None = None
) -> list[ToolDefinition]:
    return [
        create_tool_definition(tool_name, options=options)
        for tool_name in READ_ONLY_TOOL_NAMES
    ]


def create_all_tool_definitions(
    *, options: ToolsOptions | None = None
) -> dict[ToolName, ToolDefinition]:
    return {
        tool_name: create_tool_definition(tool_name, options=options)
        for tool_name in ALL_TOOL_NAMES
    }


def create_tool(
    tool_name: ToolName,
    *,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return wrap_tool_definition(
        create_tool_definition(tool_name, options=options),
        execution_host=ToolExecutionHost(
            WorkspaceToolAuthorizationGateway(
                policy_evaluator=PolicyEngine(),
            )
        ),
        context_provider=_create_context_provider(
            cwd=cwd,
            options=options,
            context_provider=context_provider,
            model=model,
        ),
    )


def create_profiled_workspace_tools(
    profile: WorkspaceToolProfile,
    *,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> list[AgentTool[Any]]:
    """Materialize the tools selected by a Product workspace profile."""

    return [
        create_tool(
            tool_name,
            cwd=cwd,
            options=options,
            context_provider=context_provider,
            model=model,
        )
        for tool_name in profile.tool_names
    ]


def _validated_tool_names(
    values: Iterable[ToolName],
    *,
    name: str,
) -> tuple[ToolName, ...]:
    if isinstance(values, str):
        raise TypeError(f"{name} must be an iterable of tool names")
    result = tuple(values)
    if not result:
        raise ValueError(f"{name} must not be empty")
    unknown = tuple(value for value in result if value not in ALL_TOOL_NAMES)
    if unknown:
        raise ValueError(f"{name} contains unknown workspace tools: {unknown!r}")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not repeat workspace tools")
    return result


def create_read_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "read", cwd=cwd, options=options, context_provider=context_provider, model=model
    )


def create_bash_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "bash", cwd=cwd, options=options, context_provider=context_provider, model=model
    )


def create_edit_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "edit", cwd=cwd, options=options, context_provider=context_provider, model=model
    )


def create_write_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "write",
        cwd=cwd,
        options=options,
        context_provider=context_provider,
        model=model,
    )


def create_grep_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "grep", cwd=cwd, options=options, context_provider=context_provider, model=model
    )


def create_find_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "find", cwd=cwd, options=options, context_provider=context_provider, model=model
    )


def create_ls_tool(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    *,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> AgentTool[Any]:
    return create_tool(
        "ls", cwd=cwd, options=options, context_provider=context_provider, model=model
    )


def create_core_workspace_tools(
    *,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> list[AgentTool[Any]]:
    return [
        create_tool(
            tool_name,
            cwd=cwd,
            options=options,
            context_provider=context_provider,
            model=model,
        )
        for tool_name in CORE_WORKSPACE_TOOL_NAMES
    ]


def create_read_only_tools(
    *,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> list[AgentTool[Any]]:
    return [
        create_tool(
            tool_name,
            cwd=cwd,
            options=options,
            context_provider=context_provider,
            model=model,
        )
        for tool_name in READ_ONLY_TOOL_NAMES
    ]


def create_all_tools(
    *,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
    context_provider: ToolContextProvider | None = None,
    model: object | None = None,
) -> dict[ToolName, AgentTool[Any]]:
    return {
        tool_name: create_tool(
            tool_name,
            cwd=cwd,
            options=options,
            context_provider=context_provider,
            model=model,
        )
        for tool_name in ALL_TOOL_NAMES
    }


def createToolDefinition(
    tool_name: ToolName,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> ToolDefinition:
    del cwd
    return create_tool_definition(tool_name, options=options)


def createTool(
    tool_name: ToolName,
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> AgentTool[Any]:
    return create_tool(tool_name, cwd=cwd, options=options)


def createReadTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_read_tool(cwd=cwd, options=options)


def createBashTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_bash_tool(cwd=cwd, options=options)


def createEditTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_edit_tool(cwd=cwd, options=options)


def createWriteTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_write_tool(cwd=cwd, options=options)


def createGrepTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_grep_tool(cwd=cwd, options=options)


def createFindTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_find_tool(cwd=cwd, options=options)


def createLsTool(
    cwd: str | None = None, options: ToolsOptions | None = None
) -> AgentTool[Any]:
    return create_ls_tool(cwd=cwd, options=options)


def createCoreWorkspaceToolDefinitions(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> list[ToolDefinition]:
    del cwd
    return create_core_workspace_tool_definitions(options=options)


def createReadOnlyToolDefinitions(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> list[ToolDefinition]:
    del cwd
    return create_read_only_tool_definitions(options=options)


def createAllToolDefinitions(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> dict[ToolName, ToolDefinition]:
    del cwd
    return create_all_tool_definitions(options=options)


def createCoreWorkspaceTools(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> list[AgentTool[Any]]:
    return create_core_workspace_tools(cwd=cwd, options=options)


def createReadOnlyTools(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> list[AgentTool[Any]]:
    return create_read_only_tools(cwd=cwd, options=options)


def createAllTools(
    cwd: str | None = None,
    options: ToolsOptions | None = None,
) -> dict[ToolName, AgentTool[Any]]:
    return create_all_tools(cwd=cwd, options=options)


def _create_context_provider(
    *,
    cwd: str | None,
    options: ToolsOptions | None,
    context_provider: ToolContextProvider | None,
    model: object | None,
) -> ToolContextProvider | None:
    if context_provider is not None:
        return context_provider
    diagnostics = options.diagnostics_service if options is not None else None
    if cwd is None and diagnostics is None and model is None:
        return None

    def _context_provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(
            tool_call_id=tool_call_id,
            cwd=cwd,
            diagnostics=diagnostics,
            model=model,
            exec_service=options.exec_service if options is not None else None,
        )

    return _context_provider
