"""Registry conveniences for materialized workspace tools and tool packs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from loushang.agent.types import AgentTool
from loushang.harness.tools.contribution import (
    ToolContribution,
    ToolPackDefinition,
    ToolResolutionResult,
    resolve_tool_contributions,
)
from loushang.harness.tools.core import ToolContextProvider, ToolDefinition
from loushang.harness.tools.core import ToolRegistry as CoreToolRegistry
from loushang.harness.tools.execution import ToolExecutionHost

from .factory import (
    ToolsOptions,
    WorkspaceToolProfile,
    create_profiled_workspace_tool_definitions,
)


class WorkspaceToolRegistry(CoreToolRegistry):
    """A generic registry for explicitly bound workspace definitions."""

    def __init__(
        self,
        *,
        execution_host: ToolExecutionHost | None = None,
    ) -> None:
        super().__init__(execution_host=execution_host)

    def register_tool(
        self,
        tool: ToolDefinition,
        *,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> ToolDefinition:
        """Compatibility facade; live owners should use inherited ``bind_tool``."""

        return super().register_tool(
            tool,
            enabled=enabled,
            source_info=source_info,
        )

    def materialize_tool(
        self,
        name: str,
        *,
        context_provider: ToolContextProvider | None = None,
    ) -> AgentTool[Any]:
        return self.materialize_definitions(
            [self.get_definition(name)],
            context_provider=context_provider,
        )[0]

    def materialize_definitions(
        self,
        definitions: list[ToolDefinition],
        *,
        context_provider: ToolContextProvider | None = None,
    ) -> list[AgentTool[Any]]:
        return super().materialize_definitions(
            definitions,
            context_provider=context_provider,
        )

    def list_contributions(self) -> tuple[ToolContribution, ...]:
        enabled_names = {
            definition.name for definition in self.list_enabled_definitions()
        }
        return tuple(
            ToolContribution(
                definition,
                enabled=definition.name in enabled_names,
                source_info=self.get_source_info(definition.name),
            )
            for definition in self.list_definitions()
        )

    def copy(self) -> WorkspaceToolRegistry:
        """Copy definitions and activation state without carrying runtime bindings."""

        return self._copy_contributions(self.list_contributions())

    def select(self, names: Iterable[str]) -> WorkspaceToolRegistry:
        """Copy the named contributions in caller order into a fresh registry."""

        contributions = {
            contribution.definition.name: contribution
            for contribution in self.list_contributions()
        }
        return self._copy_contributions(contributions[name] for name in names)

    @staticmethod
    def _copy_contributions(
        contributions: Iterable[ToolContribution],
    ) -> WorkspaceToolRegistry:
        copied = WorkspaceToolRegistry()
        for contribution in contributions:
            copied.register_tool(
                contribution.definition,
                enabled=contribution.enabled,
                source_info=contribution.source_info,
            )
        return copied

    def resolve_contributions(
        self,
        *,
        packs: tuple[ToolPackDefinition, ...] | list[ToolPackDefinition] = (),
        include_packs: tuple[str, ...] | list[str] = (),
        disabled_tools: tuple[str, ...] | list[str] = (),
        fail_on_errors: bool = True,
    ) -> ToolResolutionResult:
        return resolve_tool_contributions(
            self.list_contributions(),
            packs=packs,
            include_packs=include_packs,
            disabled_tools=disabled_tools,
            fail_on_errors=fail_on_errors,
        )

    def register_profile(
        self,
        profile: WorkspaceToolProfile,
        *,
        options: ToolsOptions | None = None,
    ) -> WorkspaceToolRegistry:
        """Build, resolve, and register one Product workspace tool profile."""

        definitions = create_profiled_workspace_tool_definitions(
            profile,
            options=options,
            tool_names=profile.builtin_tool_names,
        )
        pack = ToolPackDefinition(
            name=profile.pack_id,
            tools=profile.builtin_tool_names,
        )
        result = resolve_tool_contributions(
            tuple(ToolContribution(definition) for definition in definitions),
            packs=(pack,),
            include_packs=(pack.name,),
        )
        for definition in result.definitions:
            self.register_tool(definition)
        return self


__all__ = ["WorkspaceToolRegistry"]
