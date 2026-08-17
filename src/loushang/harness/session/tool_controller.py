"""Product-neutral workspace tool coordination for composed sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from loushang.ai.types import ToolCall
from loushang.harness.approval import ApprovalResolver
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.capabilities.prompt_assembly import assemble_prompt
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.resources.activation import ResourceActivationRuntime
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime.registration import RegistrationLease, RegistrationOwner
from loushang.harness.session.tool_runtime import (
    AgentToolPort,
    SessionToolRuntime,
    ToolPromptRebuilder,
)
from loushang.harness.tools.authoring import ToolContext
from loushang.harness.tools.contribution import resolve_tool_contributions
from loushang.harness.tools.core import ToolDefinition, project_tool_definition
from loushang.harness.tools.execution import (
    ToolCallContext,
    ToolExecutionHost,
)
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)
from loushang.harness.tools.workspace.policy import ToolPolicyEvaluator
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.exec import ExecService

_DEFAULT_ACTIVE_TOOL_NAMES: tuple[str, ...] = (
    "read",
    "ls",
    "find",
    "grep",
    "bash",
    "edit",
    "write",
)
_BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    ("bash", "read", "ls", "find", "grep", "write", "edit")
)


class AgentPort(AgentToolPort, Protocol):
    @property
    def system_prompt(self) -> str: ...

    @system_prompt.setter
    def system_prompt(self, value: str) -> None: ...


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
    agent: AgentPort,
    base_prompt: str,
    get_resource_bundle: Callable[[], ResourceBundle | None],
    show_empty_tool_prompt: bool = False,
    resource_activation_runtime: ResourceActivationRuntime | None = None,
    prompt_section_composer: PromptSectionComposer | None = None,
) -> ToolPromptRebuilder:
    """Build the prompt callback bound to a Product's Agent and resources."""

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
class SessionToolController:
    """Coordinate workspace tools using Product-injected policy ports."""

    agent: AgentPort
    get_cwd: Callable[[], str]
    tool_registry: WorkspaceToolRegistry | None
    allowed_tool_names: set[str] | None
    initial_active_tool_names: list[str]
    base_prompt: str
    get_resource_bundle: Callable[[], ResourceBundle | None]
    get_diagnostics_service: Callable[[], DiagnosticsService | None]
    emit_tool_audit_event: Callable[[dict[str, object]], Awaitable[None]] | None = None
    default_activate_new_tools: bool = False
    activation_profile: ToolActivationProfile | None = None
    show_empty_tool_prompt: bool = False
    resource_activation_runtime: ResourceActivationRuntime = field(
        default_factory=ResourceActivationRuntime
    )
    prompt_section_composer: PromptSectionComposer = field(
        default_factory=PromptSectionComposer
    )
    get_exec_service: Callable[[], ExecService | None] | None = None
    get_approval_resolver: Callable[[], ApprovalResolver | None] | None = None
    policy_evaluator: ToolPolicyEvaluator | None = None
    _runtime: SessionToolRuntime = field(init=False, repr=False)
    _execution_host: ToolExecutionHost = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.tool_registry is None:
            if self.agent.tools:
                raise TypeError(
                    "Harness sessions require explicitly bound ToolDefinitions; "
                    "raw preinstalled AgentTool values are not admitted"
                )
            self.tool_registry = WorkspaceToolRegistry()
        tool_registry = self.tool_registry
        policy_evaluator = self.policy_evaluator
        if policy_evaluator is None:
            from loushang.harness.policy_engine import PolicyEngine

            policy_evaluator = PolicyEngine()
        approval_resolver = (
            self.get_approval_resolver()
            if self.get_approval_resolver is not None
            else None
        )
        self._execution_host = create_workspace_tool_execution_host(
            policy_evaluator=policy_evaluator,
            approval_resolver=approval_resolver,
        )
        tool_registry.bind_execution_host(self._execution_host)
        profile = self.activation_profile or ToolActivationProfile(
            preferred_names=_DEFAULT_ACTIVE_TOOL_NAMES,
            builtin_names=_BUILTIN_TOOL_NAMES,
            activate_new_tools=self.default_activate_new_tools,
        )
        if profile.activate_new_tools != self.default_activate_new_tools:
            profile = ToolActivationProfile(
                preferred_names=profile.preferred_names,
                builtin_names=profile.builtin_names,
                activate_new_tools=self.default_activate_new_tools,
            )
        self._runtime = SessionToolRuntime(
            agent=self.agent,
            tool_registry=tool_registry,
            allowed_tool_names=self.allowed_tool_names,
            initial_active_tool_names=self.initial_active_tool_names,
            default_active_tool_names=lambda: profile.default_names(
                tool_registry.list_enabled_definitions(),
                self.allowed_tool_names,
            ),
            should_activate_new_tool=profile.should_activate_new,
            build_tool_context=self.build_tool_context,
            rebuild_prompt=create_tool_prompt_rebuilder(
                agent=self.agent,
                base_prompt=self.base_prompt,
                get_resource_bundle=self.get_resource_bundle,
                show_empty_tool_prompt=self.show_empty_tool_prompt,
                resource_activation_runtime=self.resource_activation_runtime,
                prompt_section_composer=self.prompt_section_composer,
            ),
            resolve_contributions=resolve_tool_contributions,
        )

    def get_active_tool_names(self) -> list[str]:
        return self._runtime.get_active_tool_names()

    def get_all_tools(self) -> list[ToolDefinition]:
        return self._runtime.get_all_tools()

    def get_all_tool_infos(self) -> list[dict[str, object]]:
        return [
            project_tool_definition(
                definition,
                self.tool_source_info(definition.name),
                builtin_names=_BUILTIN_TOOL_NAMES,
            )
            for definition in self.get_all_tools()
        ]

    def get_tool_definition(self, name: str) -> ToolDefinition | None:
        return self._runtime.get_tool_definition(name)

    def apply_active_tools(self, tool_names: list[str]) -> None:
        self._runtime.apply_active_tools(tool_names)

    def build_tool_context(self, *, tool_call_id: str) -> ToolContext:
        return ToolContext(
            tool_call_id=tool_call_id,
            cwd=self.get_cwd(),
            diagnostics=self.get_diagnostics_service(),
            exec_service=(
                self.get_exec_service() if self.get_exec_service is not None else None
            ),
            model=getattr(self.agent, "model", None),
            event_sink=(
                self._emit_tool_audit_event
                if self.emit_tool_audit_event is not None
                else None
            ),
        )

    async def execute_tool_definition(
        self,
        definition: ToolDefinition,
        *,
        tool_call_id: str,
        arguments: dict[str, Any],
        signal: object | None = None,
        on_update: object | None = None,
        operation_bindings: Mapping[str, object] | None = None,
    ) -> object:
        base = self.build_tool_context(tool_call_id=tool_call_id)
        return await self._execution_host.dispatch(
            definition,
            ToolCall(
                type="toolCall",
                id=tool_call_id,
                name=definition.name,
                arguments=dict(arguments),
            ),
            ToolCallContext(
                tool_call_id=tool_call_id,
                cwd=base.cwd,
                diagnostics=base.diagnostics,
                signal=signal,
                model=base.model,
                event_sink=base.event_sink,
                exec_service=base.exec_service,
                on_update=on_update if callable(on_update) else None,
                operation_bindings=operation_bindings or {},
            ),
        )

    def resolve_active_tool_definitions(
        self, tool_names: list[str]
    ) -> tuple[list[ToolDefinition], list[str]]:
        return self._runtime.resolve_active_tool_definitions(tool_names)

    def is_tool_allowed(self, name: str) -> bool:
        return self._runtime.is_tool_allowed(name)

    def filter_allowed_tool_names(self, tool_names: list[str]) -> list[str]:
        return self._runtime.filter_allowed_tool_names(tool_names)

    def filter_allowed_tool_definitions(
        self, definitions: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        return self._runtime.filter_allowed_tool_definitions(definitions)

    def tool_source_info(self, name: str) -> object | None:
        return self._runtime.tool_source_info(name)

    def default_active_tool_names(self) -> list[str]:
        return self._runtime.default_active_names()

    def ensure_tool_registry(self) -> WorkspaceToolRegistry:
        if self.tool_registry is None:
            self.tool_registry = WorkspaceToolRegistry()
            self._runtime.set_tool_registry(self.tool_registry)
        return self.tool_registry

    def register_runtime_tool(
        self, tool: object, *, source_info: object | None = None
    ) -> ToolDefinition:
        """Compatibility path; owner-aware live callers use ``bind_runtime_tool``."""

        self.ensure_tool_registry()
        return self._runtime.register_runtime_tool(tool, source_info=source_info)

    def bind_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease:
        self.ensure_tool_registry()
        return self._runtime.bind_runtime_tool(
            tool,
            owner=owner,
            source_info=source_info,
        )

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease:
        self.ensure_tool_registry()
        return self._runtime.stage_runtime_tool(
            tool,
            owner=owner,
            source_info=source_info,
        )

    def adopt_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease | None:
        self.ensure_tool_registry()
        return self._runtime.adopt_runtime_tool(
            tool,
            owner=owner,
            source_info=source_info,
        )

    def rebuild_prompt_and_tools_view(self) -> None:
        self._runtime.rebuild_prompt_and_tools_view()

    async def _emit_tool_audit_event(
        self,
        event: Mapping[str, object],
    ) -> None:
        if self.emit_tool_audit_event is not None:
            await self.emit_tool_audit_event(dict(event))


ToolController = SessionToolController

__all__ = [
    "AgentPort",
    "SessionToolController",
    "ToolActivationProfile",
    "ToolController",
    "create_tool_prompt_rebuilder",
]
