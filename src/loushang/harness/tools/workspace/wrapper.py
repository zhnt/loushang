"""Workspace compatibility imports for the common hosted tool wrapper."""

from __future__ import annotations

from typing import Any

from loushang.agent.types import AgentTool
from loushang.harness.approval import ApprovalResolver
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.tools.core import (
    ToolDefinition,
    WrappedToolDefinition,
)
from loushang.harness.tools.core import (
    wrap_tool_definition as _wrap_tool_definition,
)
from loushang.harness.tools.core import (
    wrap_tool_definitions as _wrap_tool_definitions,
)
from loushang.harness.tools.execution import ToolExecutionHost

from .authorization import (
    create_workspace_tool_execution_host as _create_workspace_tool_execution_host,
)
from .policy import ToolPolicyEvaluator


def create_workspace_tool_execution_host(
    *,
    policy_evaluator: ToolPolicyEvaluator | None = None,
    approval_resolver: ApprovalResolver | None = None,
) -> ToolExecutionHost:
    """Compose the Workspace gateway for one standalone or session host."""

    return _create_workspace_tool_execution_host(
        policy_evaluator=policy_evaluator or PolicyEngine(),
        approval_resolver=approval_resolver,
    )


def create_tool_definition_from_tool(tool: AgentTool[Any]) -> ToolDefinition:
    """Recover only a definition materialized by the common hosted wrapper."""

    definition = getattr(tool, "definition", None)
    if not isinstance(definition, ToolDefinition):
        raise TypeError(
            "raw AgentTool values have no execution binding; register an "
            "explicit ToolDefinition"
        )
    return definition


def wrap_tool_definition(
    definition: ToolDefinition,
    *,
    context_provider: object | None = None,
    execution_host: ToolExecutionHost | None = None,
    policy_evaluator: ToolPolicyEvaluator | None = None,
    approval_resolver: ApprovalResolver | None = None,
) -> AgentTool[Any]:
    return _wrap_tool_definition(
        definition,
        execution_host=execution_host
        or create_workspace_tool_execution_host(
            policy_evaluator=policy_evaluator,
            approval_resolver=approval_resolver,
        ),
        context_provider=context_provider if callable(context_provider) else None,
    )


def wrap_tool_definitions(
    definitions: list[ToolDefinition],
    *,
    context_provider: object | None = None,
    execution_host: ToolExecutionHost | None = None,
    policy_evaluator: ToolPolicyEvaluator | None = None,
    approval_resolver: ApprovalResolver | None = None,
) -> list[AgentTool[Any]]:
    host = execution_host or create_workspace_tool_execution_host(
        policy_evaluator=policy_evaluator,
        approval_resolver=approval_resolver,
    )
    return _wrap_tool_definitions(
        definitions,
        execution_host=host,
        context_provider=context_provider if callable(context_provider) else None,
    )


__all__ = [
    "WrappedToolDefinition",
    "create_workspace_tool_execution_host",
    "create_tool_definition_from_tool",
    "wrap_tool_definition",
    "wrap_tool_definitions",
]
