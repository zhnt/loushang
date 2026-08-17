"""Restricted execution-context projection for extension tools."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from loushang.agent.types import AgentToolResult
from loushang.ai.types import ToolCall
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    AuthorizedToolHandler,
    DirectExecution,
    DirectToolContext,
    DirectToolHandler,
    PreparedToolAction,
    ToolActionAdapter,
    ToolCallContext,
)


@dataclass(frozen=True, slots=True)
class _ExtensionDirectHandler:
    inner: DirectToolHandler
    cwd: str

    async def __call__(
        self,
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[Any]:
        return await self.inner(call, replace(context, cwd=self.cwd))


@dataclass(frozen=True, slots=True)
class _ExtensionActionAdapter:
    inner: ToolActionAdapter
    cwd: str

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        return self.inner.prepare(call, replace(context, cwd=self.cwd))


@dataclass(frozen=True, slots=True)
class _ExtensionAuthorizedHandler:
    inner: AuthorizedToolHandler
    cwd: str

    async def __call__(
        self,
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[Any]:
        return await self.inner(action, replace(context, cwd=self.cwd))


def wrap_registered_tool_definition(
    definition: ToolDefinition,
    cwd: str,
) -> ToolDefinition:
    """Bind extension-relative cwd without exposing full ExtensionContext."""

    binding = definition.execution
    if isinstance(binding, DirectExecution):
        return replace(
            definition,
            execution=DirectExecution(_ExtensionDirectHandler(binding.handler, cwd)),
        )
    if isinstance(binding, AuthorizedExecution):
        return replace(
            definition,
            execution=AuthorizedExecution(
                action_adapter=_ExtensionActionAdapter(
                    binding.action_adapter,
                    cwd,
                ),
                handler=_ExtensionAuthorizedHandler(binding.handler, cwd),
            ),
        )
    raise TypeError(
        f"unsupported extension execution binding: {type(binding).__name__}"
    )


def wrap_registered_tool_definitions(
    definitions: list[ToolDefinition],
    cwd: str,
) -> list[ToolDefinition]:
    return [
        wrap_registered_tool_definition(definition, cwd) for definition in definitions
    ]


__all__ = [
    "wrap_registered_tool_definition",
    "wrap_registered_tool_definitions",
]
