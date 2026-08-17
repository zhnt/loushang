"""Live tool activation and Agent rebind mechanics for one session."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from loushang.agent.types import AgentTool
from loushang.harness.capabilities.tools import (
    ToolActivationChange,
    ToolActivationCoordinator,
)
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.tools.authoring import ToolContextProvider
from loushang.harness.tools.contribution import (
    ToolContribution,
    ToolResolutionResult,
    resolve_tool_contributions,
)
from loushang.harness.tools.core import ToolDefinition


class AgentToolPort(Protocol):
    """Only the mutable Agent tool surface required by activation mechanics."""

    @property
    def tools(self) -> list[AgentTool[Any]]: ...

    @tools.setter
    def tools(self, value: list[AgentTool[Any]]) -> None: ...


class ToolRegistryPort(Protocol):
    """Registry operations consumed by the live tool runtime."""

    def get_definition(self, name: str) -> ToolDefinition: ...

    def get_source_info(self, name: str) -> object | None: ...

    def list_contributions(self) -> tuple[ToolContribution, ...]: ...

    def list_definitions(self) -> list[ToolDefinition]: ...

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

    def bind_tool(
        self,
        tool: ToolDefinition,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease: ...

    def stage_tool(
        self,
        tool: ToolDefinition,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease: ...

    def _rollback_tool_binding(
        self,
        lease: RegistrationLease,
    ) -> RegistrationDisposalResult: ...

    def adopt_compatibility_tool(
        self,
        tool: ToolDefinition,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease | None: ...


class ToolContributionResolver(Protocol):
    """The contribution-resolution operation used for runtime tool admission."""

    def __call__(
        self,
        contributions: Iterable[ToolContribution],
        *,
        fail_on_errors: bool = True,
    ) -> ToolResolutionResult: ...


ToolPromptRebuilder = Callable[[list[ToolDefinition] | None], None]
ToolActivationPolicy = Callable[[str, ToolDefinition], bool]
ToolDefaultSelection = Callable[[], Iterable[str]]


@dataclass
class SessionToolRuntime:
    """Apply a Product-selected tool capability set to one live Agent."""

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
        self._sync_available(activate_new=False, rebind=False)
        self._activation.request(tool_names)

    def resolve_active_tool_definitions(
        self, tool_names: Iterable[str]
    ) -> tuple[list[ToolDefinition], list[str]]:
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
        """Compatibility path for callers that cannot yet retain a lease."""

        registration = self._resolve_runtime_tool_registration(
            tool,
            source_info=source_info,
        )
        definition = self.tool_registry.register_tool(
            registration.definition,
            source_info=registration.source_info,
        )
        if not self.is_tool_allowed(definition.name):
            self.rebuild_prompt_and_tools_view()
            return definition
        self._sync_available(activate_new=True, rebind=True)
        return definition

    def bind_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease:
        registration = self._resolve_runtime_tool_registration(
            tool,
            source_info=source_info,
        )
        previous_requested_names = self._activation.snapshot().requested_names
        registry_lease = self.tool_registry.bind_tool(
            registration.definition,
            owner=owner,
            source_info=registration.source_info,
        )
        try:
            if not self.is_tool_allowed(registration.definition.name):
                self.rebuild_prompt_and_tools_view()
            else:
                self._sync_available(activate_new=True, rebind=True)
        except BaseException as bind_error:
            rollback = self.tool_registry._rollback_tool_binding(registry_lease)
            if rollback.state not in {"removed", "already_removed"}:
                bind_error.add_note("tool registry binding rollback failed")
            try:
                self._sync_available(activate_new=False, rebind=False)
                self._activation.request(previous_requested_names, rebind=True)
            except BaseException:
                bind_error.add_note("tool binding view rollback failed")
            raise

        return self._runtime_view_lease(registry_lease)

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease:
        registration = self._resolve_runtime_tool_registration(
            tool,
            source_info=source_info,
        )
        registry_lease = self.tool_registry.stage_tool(
            registration.definition,
            owner=owner,
            source_info=registration.source_info,
        )
        return self._runtime_view_lease(registry_lease, staged=True)

    def adopt_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease | None:
        if not isinstance(tool, ToolDefinition):
            raise TypeError("runtime Tool adoption requires a ToolDefinition")
        registry_lease = self.tool_registry.adopt_compatibility_tool(
            tool,
            owner=owner,
            source_info=source_info,
        )
        if registry_lease is None:
            return None
        return self._runtime_view_lease(registry_lease)

    def rebuild_prompt_and_tools_view(self) -> None:
        self._sync_available(activate_new=False, rebind=False)
        self.rebuild_prompt(list(self._activation.active_items()))

    def _available_definitions(self) -> list[ToolDefinition]:
        return self.tool_registry.list_definitions()

    def _runtime_view_lease(
        self,
        registry_lease: RegistrationLease,
        *,
        staged: bool = False,
    ) -> RegistrationLease:
        async def dispose_runtime_binding() -> RegistrationDisposalResult:
            result = await registry_lease.dispose()
            if result.state in {"removed", "already_removed"}:
                self._sync_available(activate_new=False, rebind=True)
            return result

        def activate_runtime_binding() -> None:
            registry_lease.activate()
            self._sync_available(activate_new=True, rebind=True)

        def deactivate_runtime_binding() -> None:
            registry_lease.deactivate()
            self._sync_available(activate_new=False, rebind=True)

        def rollback_runtime_binding() -> RegistrationDisposalResult:
            result = registry_lease.rollback_registration()
            if result.state in {"removed", "already_removed"}:
                self._sync_available(activate_new=False, rebind=True)
            return result

        return RegistrationLease(
            owner=registry_lease.owner,
            identity=registry_lease.identity,
            dispose=dispose_runtime_binding,
            activate=activate_runtime_binding if staged else None,
            deactivate=deactivate_runtime_binding if staged else None,
            rollback=rollback_runtime_binding,
        )

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

    def _resolve_runtime_tool_registration(
        self,
        tool: object,
        *,
        source_info: object | None,
    ) -> ToolContribution:
        contribution = _runtime_tool_contribution(tool, source_info=source_info)
        resolution = self.resolve_contributions(
            (*self.tool_registry.list_contributions(), contribution),
            fail_on_errors=False,
        )
        return _runtime_tool_registration_contribution(
            resolution,
            fallback=contribution,
        )


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
    raise TypeError("runtime tools require an explicitly bound ToolDefinition")


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
    "SessionToolRuntime",
    "ToolActivationPolicy",
    "ToolContributionResolver",
    "ToolDefaultSelection",
    "ToolPromptRebuilder",
    "ToolRegistryPort",
]
