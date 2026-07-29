"""Runtime binding for Product-selected tools and commands in one session.

The generic capability primitives resolve names, packs, and command dispatch.
This module owns their live session application: selected tools are rebound to
the Agent, command providers are composed in order, and user-triggered command
tools can stream output into a transcript.  Products inject prompt wording,
tool contexts, command handlers, and extension interception.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from loushang.agent import AbortController
from loushang.agent.types import AgentTool
from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposer,
    CapabilityPackSource,
)
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.capabilities.prompt_assembly import assemble_prompt
from loushang.harness.capabilities.tools import (
    ToolActivationChange,
    ToolActivationCoordinator,
)
from loushang.harness.commands import (
    CommandHandler,
    CommandHandlerBinding,
    ParsedSlashCommand,
    dispatch_command_async,
    normalize_command_name,
)
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.resources.activation import ResourceActivationRuntime
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.tools.authoring import ToolContextProvider
from loushang.harness.tools.contribution import (
    ToolContribution,
    ToolResolutionResult,
    resolve_tool_contributions,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.workspace.exec import ExecOutputChunk


class AgentToolPort(Protocol):
    """The mutable Agent tool surface required by the session tool runtime."""

    @property
    def tools(self) -> list[AgentTool[Any]]: ...

    @tools.setter
    def tools(self, value: list[AgentTool[Any]]) -> None: ...


class ToolRegistryPort(Protocol):
    """Registry operations needed after a Product admits a tool contribution."""

    def get_definition(self, name: str) -> ToolDefinition: ...

    def get_source_info(self, name: str) -> object | None: ...

    def list_contributions(self) -> tuple[ToolContribution, ...]: ...

    def list_definitions(self) -> list[ToolDefinition]: ...

    def list_enabled_definitions(self) -> list[ToolDefinition]: ...

    def materialize_definitions(
        self,
        definitions: list[ToolDefinition],
        *,
        context_provider: ToolContextProvider | None = None,
    ) -> list[AgentTool[Any]]: ...

    def register_tool(
        self,
        tool: ToolDefinition,
        *,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> ToolDefinition: ...


ToolPromptRebuilder = Callable[[list[ToolDefinition] | None], None]
ToolActivationPolicy = Callable[[str, ToolDefinition], bool]
ToolDefaultSelection = Callable[[], Iterable[str]]
ToolContributionResolver = Callable[..., ToolResolutionResult]


@dataclass(frozen=True)
class ToolActivationProfile:
    """Product-selected defaults for the shared tool activation coordinator."""

    preferred_names: tuple[str, ...] = ()
    builtin_names: frozenset[str] = frozenset()
    activate_new_tools: bool = False

    def default_names(
        self,
        definitions: Iterable[ToolDefinition],
        allowed_names: set[str] | None = None,
    ) -> list[str]:
        available = [definition.name for definition in definitions]
        if allowed_names is not None:
            return [name for name in available if name in allowed_names]
        available_set = set(available)
        selected = [name for name in self.preferred_names if name in available_set]
        selected.extend(
            name
            for name in available
            if name not in self.builtin_names and name not in selected
        )
        return selected

    def should_activate_new(self, name: str, definition: ToolDefinition) -> bool:
        del definition
        return self.activate_new_tools and name not in self.builtin_names


def create_tool_prompt_rebuilder(
    *,
    agent: AgentToolPort,
    base_prompt: str,
    get_resource_bundle: Callable[[], ResourceBundle | None],
    show_empty_tool_prompt: bool = False,
    resource_activation_runtime: ResourceActivationRuntime | None = None,
    prompt_section_composer: PromptSectionComposer | None = None,
) -> ToolPromptRebuilder:
    """Build the neutral prompt update callback used by session tool runtime."""
    activation = resource_activation_runtime or ResourceActivationRuntime()
    composer = prompt_section_composer or PromptSectionComposer()

    def rebuild(active_definitions: list[ToolDefinition] | None) -> None:
        if show_empty_tool_prompt and active_definitions is None:
            active_definitions = []
        tool_prompt = (
            "Available tools:\n(none)"
            if show_empty_tool_prompt and active_definitions == []
            else None
        )
        bundle = get_resource_bundle()
        assembly = assemble_prompt(
            base_prompt=base_prompt,
            resource_bundle=bundle,
            tool_definitions=active_definitions,
            tool_prompt=tool_prompt,
            resource_activation=activation.activate(bundle),
            prompt_section_composer=composer,
        )
        agent.system_prompt = assembly.system_prompt

    return rebuild


@dataclass
class SessionToolRuntime:
    """Apply the Product-selected tool capability set to one live Agent."""

    agent: AgentToolPort
    tool_registry: ToolRegistryPort
    allowed_tool_names: set[str] | None
    initial_active_tool_names: Iterable[str]
    default_active_tool_names: ToolDefaultSelection
    should_activate_new_tool: ToolActivationPolicy
    build_tool_context: ToolContextProvider
    rebuild_prompt: ToolPromptRebuilder
    resolve_contributions: ToolContributionResolver = resolve_tool_contributions
    _activation: ToolActivationCoordinator[ToolDefinition] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._activation = ToolActivationCoordinator(
            available=self._available_definitions(),
            requested_names=self.initial_active_tool_names,
            allowed_names=self.allowed_tool_names,
            should_activate_new=self.should_activate_new_tool,
            rebind=self._rebind_active_tools,
        )

    def get_active_tool_names(self) -> list[str]:
        return list(self._activation.snapshot().active_names)

    def get_all_tools(self) -> list[ToolDefinition]:
        return list(self._activation.filter_items(self._available_definitions()))

    def get_tool_definition(self, name: str) -> ToolDefinition | None:
        if not self.is_tool_allowed(name):
            return None
        try:
            return self.tool_registry.get_definition(name)
        except KeyError:
            return None

    def apply_active_tools(self, tool_names: Iterable[str]) -> None:
        self._require_registry()
        self._sync_available(activate_new=False, rebind=False)
        self._activation.request(tool_names)

    def resolve_active_tool_definitions(
        self, tool_names: Iterable[str]
    ) -> tuple[list[ToolDefinition], list[str]]:
        self._require_registry()
        self._sync_available(activate_new=False, rebind=False)
        resolution = self._activation.resolve(tool_names)
        return list(resolution.items), list(resolution.names)

    def is_tool_allowed(self, name: str) -> bool:
        return self._activation.is_allowed(name)

    def filter_allowed_tool_names(self, tool_names: Iterable[str]) -> list[str]:
        return list(self._activation.filter_names(tool_names))

    def filter_allowed_tool_definitions(
        self, definitions: Iterable[ToolDefinition]
    ) -> list[ToolDefinition]:
        return list(self._activation.filter_items(definitions))

    def tool_source_info(self, name: str) -> object | None:
        try:
            return self.tool_registry.get_source_info(name)
        except KeyError:
            return None

    def default_active_names(self) -> list[str]:
        return self.filter_allowed_tool_names(self.default_active_tool_names())

    def set_tool_registry(self, registry: ToolRegistryPort) -> None:
        self.tool_registry = registry
        self._sync_available(activate_new=False, rebind=False)

    def register_runtime_tool(
        self,
        tool: object,
        *,
        source_info: object | None = None,
    ) -> ToolDefinition:
        registry = self._require_registry()
        contribution = _runtime_tool_contribution(tool, source_info=source_info)
        resolution = self.resolve_contributions(
            (*registry.list_contributions(), contribution),
            fail_on_errors=False,
        )
        registration = _runtime_tool_registration_contribution(
            resolution,
            fallback=contribution,
        )
        definition = registry.register_tool(
            registration.definition,
            source_info=registration.source_info,
        )
        if not self.is_tool_allowed(definition.name):
            self.rebuild_prompt_and_tools_view()
            return definition
        self._sync_available(activate_new=True, rebind=True)
        return definition

    def rebuild_prompt_and_tools_view(self) -> None:
        active_definitions: list[ToolDefinition] | None = None
        self._sync_available(activate_new=False, rebind=False)
        active_definitions = list(self._activation.active_items())
        self.rebuild_prompt(active_definitions)

    def _available_definitions(self) -> list[ToolDefinition]:
        return self.tool_registry.list_definitions()

    def _sync_available(self, *, activate_new: bool, rebind: bool) -> None:
        self._activation.refresh(
            self._available_definitions(),
            activate_new=activate_new,
            rebind=rebind,
        )

    def _rebind_active_tools(
        self,
        change: ToolActivationChange[ToolDefinition],
    ) -> None:
        self.agent.tools = self.tool_registry.materialize_definitions(
            list(change.active_items),
            context_provider=self.build_tool_context,
        )
        self.rebuild_prompt(list(change.active_items))

    def _require_registry(self) -> ToolRegistryPort:
        return self.tool_registry


DescriptorT = TypeVar("DescriptorT")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class CommandRuntimeSource(Generic[DescriptorT, ResultT]):
    """A Product-approved dynamic command contribution source."""

    pack_id: str
    source: CapabilityPackSource
    descriptor_priority: int
    handler_priority: int
    list_descriptors: Callable[[], Iterable[DescriptorT]]
    handler_name: str
    handler: CommandHandler[ResultT]


@dataclass
class SessionCommandRuntime(Generic[DescriptorT, ResultT]):
    """Compose and dispatch dynamic command sources for one live session."""

    sources: tuple[CommandRuntimeSource[DescriptorT, ResultT], ...]
    pack_composer: CapabilityPackComposer = field(
        default_factory=CapabilityPackComposer
    )

    def list_commands(self) -> list[DescriptorT]:
        packs = tuple(
            CapabilityPack(
                pack_id=source.pack_id,
                source=source.source,
                priority=source.descriptor_priority,
                items=tuple(source.list_descriptors()),
            )
            for source in self.sources
        )
        return list(self.pack_composer.compose(packs).items)

    async def execute(
        self,
        invocation_name: str,
        args: str,
    ) -> ResultT | None:
        normalized_name = normalize_command_name(invocation_name)
        invocation = ParsedSlashCommand(
            name=normalized_name,
            args=args,
            is_mcp=normalized_name.endswith(" (MCP)"),
        )
        handlers = self.pack_composer.compose(
            CapabilityPack(
                pack_id=source.pack_id,
                source=source.source,
                priority=source.handler_priority,
                items=(CommandHandlerBinding(source.handler_name, source.handler),),
            )
            for source in self.sources
        ).items
        outcome = await dispatch_command_async(invocation, handlers)
        return outcome.result if outcome.handled else None


CommandHook = Callable[["UserCommandRequest"], Awaitable["UserCommandHookResult | None"]]
CommandOutputCallback = Callable[[ExecOutputChunk], Awaitable[None] | None]
AppendCommandRecord = Callable[[CommandExecutionRecord], Awaitable[object]]
ContextRefresher = Callable[[], None]
CommandDefinitionProvider = Callable[[], ToolDefinition | None]
CommandCallIdFactory = Callable[[], str]
CommandParametersBuilder = Callable[[str, str], Mapping[str, object]]
CommandToolExecutor = Callable[..., Awaitable[object]]


@dataclass(frozen=True)
class UserCommandRequest:
    command: str
    cwd: str
    exclude_from_context: bool


@dataclass(frozen=True)
class UserCommandHookResult:
    """Optional intercepted result or execution operations for a command."""

    result: Mapping[str, object] | None = None
    operations: object | None = None


@dataclass
class SessionCommandExecutionRuntime:
    """Run a selected command tool and commit its result to the transcript."""

    command_name: str
    get_cwd: Callable[[], str]
    get_definition: CommandDefinitionProvider
    build_execution_params: CommandParametersBuilder
    create_call_id: CommandCallIdFactory
    execute_definition: CommandToolExecutor
    append_record: AppendCommandRecord
    refresh_context: ContextRefresher
    before_execute: CommandHook | None = None
    operations: object | None = None
    _abort_controller: AbortController | None = field(default=None, init=False)

    @property
    def is_running(self) -> bool:
        return self._abort_controller is not None

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: list[list[str] | tuple[str, str]]
        | tuple[tuple[str, str], ...]
        | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        exclude_from_context: bool = False,
        on_output: CommandOutputCallback | None = None,
        operations: object | None = None,
    ) -> dict[str, object]:
        if self._abort_controller is not None:
            raise RuntimeError(f"{self.command_name} execution already in progress")
        effective_cwd = cwd or self.get_cwd()
        selected_operations = (
            operations if operations is not None else self.operations
        )
        if self.before_execute is not None:
            interception = await self.before_execute(
                UserCommandRequest(
                    command=command,
                    cwd=effective_cwd,
                    exclude_from_context=exclude_from_context,
                )
            )
            if interception is not None:
                if interception.result is not None:
                    result = dict(interception.result)
                    await self.record_result(
                        command=command,
                        result=result,
                        exclude_from_context=exclude_from_context,
                    )
                    return result
                if interception.operations is not None:
                    selected_operations = interception.operations

        definition = self.get_definition()
        if definition is None:
            raise RuntimeError(f"{self.command_name} tool is not registered")
        controller = AbortController()
        self._abort_controller = controller
        streamed_chunks: list[str] = []

        async def forward_update(partial_result: object) -> None:
            details = getattr(partial_result, "details", None)
            stream = details.get("stream") if isinstance(details, dict) else None
            if stream not in {"stdout", "stderr"}:
                return
            text = "".join(
                block.text
                for block in getattr(partial_result, "content", ())
                if getattr(block, "type", None) == "text"
                and isinstance(getattr(block, "text", None), str)
            )
            if not text:
                return
            streamed_chunks.append(text)
            if on_output is None:
                return
            forwarded = on_output(ExecOutputChunk(stream=stream, text=text))
            if inspect.isawaitable(forwarded):
                await forwarded

        params = dict(self.build_execution_params(command, effective_cwd))
        if env is not None:
            params["env"] = [list(pair) for pair in env]
        if timeout_seconds is not None:
            params["timeout_seconds"] = timeout_seconds
        if stdin is not None:
            params["stdin"] = stdin
        try:
            tool_result = await self.execute_definition(
                definition,
                tool_call_id=self.create_call_id(),
                arguments=params,
                signal=controller.signal,
                on_update=forward_update,
                operation_bindings=(
                    {"bash_operations": selected_operations}
                    if selected_operations is not None
                    else None
                ),
            )
            result = command_result_from_tool_result(tool_result)
        except RuntimeError as exc:
            if "Command aborted" not in str(exc) or not getattr(
                controller.signal, "aborted", False
            ):
                raise
            result = {
                "output": "".join(streamed_chunks),
                "exit_code": None,
                "cancelled": True,
                "truncated": False,
                "full_output_path": None,
            }
        finally:
            self._abort_controller = None

        await self.record_result(
            command=command,
            result=result,
            exclude_from_context=exclude_from_context,
        )
        return result

    def abort(self) -> None:
        if self._abort_controller is not None:
            self._abort_controller.abort()

    async def record_result(
        self,
        *,
        command: str,
        result: Mapping[str, object],
        exclude_from_context: bool,
    ) -> None:
        exit_code = result.get("exit_code")
        await self.append_record(
            CommandExecutionRecord(
                command=command,
                output=str(result.get("output") or ""),
                exit_code=exit_code if type(exit_code) is int else None,
                cancelled=bool(result.get("cancelled", False)),
                truncated=bool(result.get("truncated", False)),
                full_output_path=(
                    str(result["full_output_path"])
                    if isinstance(result.get("full_output_path"), str)
                    and result.get("full_output_path")
                    else None
                ),
                exclude_from_context=exclude_from_context,
            )
        )
        self.refresh_context()


def command_result_from_tool_result(tool_result: object) -> dict[str, object]:
    """Normalize the stable workspace-tool result into a transcript record."""

    details = getattr(tool_result, "details", None)
    details = details if isinstance(details, Mapping) else {}
    output = "".join(
        block.text
        for block in getattr(tool_result, "content", ())
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
    )
    stderr = details.get("stderr")
    if isinstance(stderr, str) and stderr and not output.endswith(stderr):
        output = output + stderr
    return {
        "output": output,
        "exit_code": details.get("exit_code"),
        "cancelled": bool(details.get("cancelled", False)),
        "truncated": bool(
            details.get("truncated", False) or details.get("stderr_truncated", False)
        ),
        "full_output_path": details.get("stdout_artifact_path")
        or details.get("stderr_artifact_path"),
    }


def _runtime_tool_contribution(
    tool: object, *, source_info: object | None = None
) -> ToolContribution:
    definition = _runtime_tool_definition(tool)
    return ToolContribution(
        definition,
        source_info=source_info,
        metadata={"kind": "runtime_tool", "runtime_tool": definition.name},
    )


def _runtime_tool_definition(tool: object) -> ToolDefinition:
    if isinstance(tool, ToolDefinition):
        return tool
    raise TypeError(
        "runtime tools require an explicitly bound ToolDefinition"
    )


def _runtime_tool_registration_contribution(
    resolution: ToolResolutionResult,
    *,
    fallback: ToolContribution,
) -> ToolContribution:
    for contribution in resolution.contributions:
        if contribution.definition.name != fallback.definition.name:
            continue
        if contribution.metadata.get("kind") == "runtime_tool":
            return contribution
    return fallback


__all__ = [
    "AgentToolPort",
    "CommandRuntimeSource",
    "SessionCommandExecutionRuntime",
    "SessionCommandRuntime",
    "SessionToolRuntime",
    "ToolRegistryPort",
    "UserCommandHookResult",
    "UserCommandRequest",
    "command_result_from_tool_result",
]
