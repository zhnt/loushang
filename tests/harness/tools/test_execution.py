from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from loushang.agent.types import AgentToolResult, TextPart
from loushang.ai.types import ToolCall
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    CallableToolActionAdapter,
    DirectExecution,
    DirectToolContext,
    PreparedToolAction,
    ToolCallContext,
    ToolExecutionHost,
)
from loushang.harness.tools.workspace.factory import (
    ALL_TOOL_NAMES,
    create_all_tool_definitions,
)


def _call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(
        type="toolCall",
        id="call-1",
        name=name,
        arguments=arguments,
    )


def _result(text: str) -> AgentToolResult[str]:
    return AgentToolResult(
        content=[TextPart(type="text", text=text)],
        details=text,
    )


def test_direct_execution_receives_only_the_restricted_context() -> None:
    received: list[DirectToolContext] = []

    async def run(
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[str]:
        received.append(context)
        return _result(str(call.arguments["value"]))

    definition = ToolDefinition(
        name="calculate",
        label="Calculate",
        description="Calculate in process",
        parameters={"type": "object"},
        execution=DirectExecution(run),
    )
    result = asyncio.run(
        ToolExecutionHost().dispatch(
            definition,
            _call("calculate", value=42),
            ToolCallContext(
                tool_call_id="call-1",
                cwd="/workspace",
                event_sink=object(),
                exec_service=object(),
                operation_bindings={"filesystem": object()},
            ),
        )
    )

    assert result.details == "42"
    assert received == [DirectToolContext(tool_call_id="call-1", cwd="/workspace")]
    assert not hasattr(received[0], "exec_service")
    assert not hasattr(received[0], "event_sink")
    assert not hasattr(received[0], "operation_bindings")


def test_authorized_execution_requires_a_gateway() -> None:
    async def run(
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[str]:
        del action, context
        return _result("should not run")

    definition = ToolDefinition(
        name="publish",
        label="Publish",
        description="Publish an artifact",
        parameters={"type": "object"},
        execution=AuthorizedExecution(
            action_adapter=CallableToolActionAdapter(
                lambda call, context: PreparedToolAction(
                    tool_name=call.name,
                    authorization_arguments=call.arguments,
                    execution_arguments=call.arguments,
                    cwd=context.cwd,
                )
            ),
            handler=run,
        ),
    )

    with pytest.raises(RuntimeError, match="requires a session gateway"):
        asyncio.run(
            ToolExecutionHost().dispatch(
                definition,
                _call("publish", target="origin"),
                ToolCallContext(tool_call_id="call-1"),
            )
        )


def test_custom_authorized_tool_executes_only_through_the_gateway() -> None:
    order: list[str] = []

    @dataclass
    class Gateway:
        async def execute(
            self,
            prepared: PreparedToolAction,
            handler,
            context: AuthorizedToolContext,
        ) -> AgentToolResult[str]:
            order.append("gateway")
            action = AuthorizedToolAction(
                tool_name=prepared.tool_name,
                authorization_arguments=prepared.authorization_arguments,
                execution_arguments=prepared.execution_arguments,
                cwd=prepared.cwd,
                fingerprint="fingerprint",
                policy_code="allow_test",
            )
            return await handler(action, context)

    async def run(
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[str]:
        order.append("handler")
        assert action.fingerprint == "fingerprint"
        assert context.exec_service == "scoped-exec"
        return _result(str(action.execution_arguments["target"]))

    definition = ToolDefinition(
        name="publish",
        label="Publish",
        description="Publish an artifact",
        parameters={"type": "object"},
        execution=AuthorizedExecution(
            action_adapter=CallableToolActionAdapter(
                lambda call, context: PreparedToolAction(
                    tool_name=call.name,
                    authorization_arguments={"target": call.arguments["target"]},
                    execution_arguments=call.arguments,
                    cwd=context.cwd,
                )
            ),
            handler=run,
        ),
    )
    result = asyncio.run(
        ToolExecutionHost(Gateway()).dispatch(
            definition,
            _call("publish", target="origin"),
            ToolCallContext(
                tool_call_id="call-1",
                exec_service="scoped-exec",
            ),
        )
    )

    assert order == ["gateway", "handler"]
    assert result.details == "origin"


def test_every_builtin_workspace_tool_uses_authorized_execution() -> None:
    definitions = create_all_tool_definitions()

    assert tuple(definitions) == ALL_TOOL_NAMES
    assert all(
        isinstance(definition.execution, AuthorizedExecution)
        for definition in definitions.values()
    )
