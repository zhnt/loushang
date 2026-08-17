from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.ai.types import ToolCall
from loushang.harness.effects import ProcessEffect
from loushang.harness.policy import PolicyDecision
from loushang.harness.tools.agent_delegate import (
    AGENT_DELEGATE_TOOL_NAME,
    AgentDelegateToolPack,
    AgentInvocationResult,
    PreparedAgentInvocation,
)
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    PreparedToolAction,
    ToolCallContext,
    ToolExecutionHost,
)
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)
from loushang.harness.tools.workspace.policy import PolicyEnforcementError
from loushang.harness.workspace.exec import ExecRequest, ExecResult


@dataclass
class _Adapter:
    result: AgentInvocationResult = AgentInvocationResult("review complete", 0)

    @property
    def admitted_agent_types(self) -> tuple[str, ...]:
        return ("reviewer",)

    def prepare(self, request, *, default_cwd, model):
        del model
        return PreparedAgentInvocation(
            request=request,
            exec_request=ExecRequest(
                command=("/workspace/.venv/bin/loushang", "--mode", "print"),
                cwd=default_cwd,
                stdin=request.task,
                timeout_seconds=30,
                capture_full_output=False,
                effective_environment=(("PATH", "/usr/bin"), ("TOKEN", "secret")),
            ),
            allowed_tools=("read",),
            model_ref="provider/model",
        )

    def project(self, prepared, result):
        del prepared, result
        return self.result


class _ExecService:
    def __init__(self, result: ExecResult | None = None) -> None:
        self.requests: list[ExecRequest] = []
        self.signals: list[object | None] = []
        self.result = result or ExecResult(exit_code=0, stdout="review complete")

    async def execute(self, request: ExecRequest, *, signal=None) -> ExecResult:
        self.requests.append(request)
        self.signals.append(signal)
        return self.result


class _Gateway:
    def __init__(self, *, execution_profile: object | None = None) -> None:
        self.prepared: PreparedToolAction | None = None
        self.execution_profile = execution_profile

    async def execute(self, prepared, handler, context: AuthorizedToolContext):
        self.prepared = prepared
        return await handler(
            AuthorizedToolAction(
                tool_name=prepared.tool_name,
                authorization_arguments=prepared.authorization_arguments,
                execution_arguments=prepared.execution_arguments,
                cwd=prepared.cwd,
                fingerprint="authorized",
                effects=prepared.effects,
                execution_profile=self.execution_profile,
            ),
            context,
        )


def _call(**arguments: object) -> ToolCall:
    return ToolCall(
        type="toolCall",
        id="delegate-1",
        name=AGENT_DELEGATE_TOOL_NAME,
        arguments=arguments,
    )


def test_delegate_agent_is_sequential_and_uses_authorized_process_execution() -> None:
    definition = AgentDelegateToolPack(adapter=_Adapter()).definition()
    binding = definition.execution

    assert definition.execution_mode == "sequential"
    assert definition.parameters["properties"]["agent_type"]["enum"] == [
        "reviewer"
    ]
    assert isinstance(binding, AuthorizedExecution)

    prepared = binding.action_adapter.prepare(
        _call(agent_type="reviewer", task="find the bug"),
        ToolCallContext(tool_call_id="delegate-1", cwd="/workspace"),
    )

    assert prepared.tool_name == AGENT_DELEGATE_TOOL_NAME
    assert prepared.effects == (
        ProcessEffect(("/workspace/.venv/bin/loushang", "--mode", "print")),
    )
    assert prepared.policy_subject is not None
    assert prepared.policy_subject.command is not None
    assert "find the bug" not in repr(prepared.authorization_arguments)
    assert "find the bug" not in repr(prepared.effects)
    assert prepared.authorization_arguments["task_sha256"]
    assert prepared.authorization_arguments["environment_sha256"]
    assert "secret" not in repr(prepared.authorization_arguments)


def test_delegate_agent_executes_the_frozen_request_through_the_scoped_service() -> None:
    adapter = _Adapter()
    definition = AgentDelegateToolPack(adapter=adapter).definition()
    execution_profile = object()
    gateway = _Gateway(execution_profile=execution_profile)
    exec_service = _ExecService()
    signal = object()

    result = asyncio.run(
        ToolExecutionHost(gateway).dispatch(
            definition,
            _call(agent_type="reviewer", task="review this"),
            ToolCallContext(
                tool_call_id="delegate-1",
                cwd="/workspace",
                signal=signal,
                exec_service=exec_service,
            ),
        )
    )

    assert result.content[0].text == "review complete"
    assert result.details == {
        "agent_type": "reviewer",
        "exit_code": 0,
        "timed_out": False,
        "cancelled": False,
        "truncated": False,
        "allowed_tools": ["read"],
        "model": "provider/model",
    }
    assert len(exec_service.requests) == 1
    assert exec_service.requests[0].stdin == "review this"
    assert exec_service.requests[0].execution_profile is execution_profile
    assert exec_service.signals == [signal]


def test_delegate_agent_policy_denial_prevents_process_execution() -> None:
    subjects: list[object] = []

    class DenyPolicy:
        def evaluate(self, subject):
            subjects.append(subject)
            return PolicyDecision.deny("subprocess denied", code="deny_delegate")

    exec_service = _ExecService()
    definition = AgentDelegateToolPack(adapter=_Adapter()).definition()

    with pytest.raises(PolicyEnforcementError, match="subprocess denied"):
        asyncio.run(
            create_workspace_tool_execution_host(
                policy_evaluator=DenyPolicy(),
            ).dispatch(
                definition,
                _call(agent_type="reviewer", task="private review task"),
                ToolCallContext(
                    tool_call_id="delegate-1",
                    cwd="/workspace",
                    exec_service=exec_service,
                ),
            )
        )

    assert len(subjects) == 1
    assert "private review task" not in repr(subjects[0])
    assert exec_service.requests == []


def test_delegate_agent_revalidates_the_authorized_plan_before_execution() -> None:
    adapter = _Adapter()
    binding = AgentDelegateToolPack(adapter=adapter).definition().execution
    assert isinstance(binding, AuthorizedExecution)
    prepared = binding.action_adapter.prepare(
        _call(agent_type="reviewer", task="review this"),
        ToolCallContext(tool_call_id="delegate-1", cwd="/workspace"),
    )
    action = AuthorizedToolAction(
        tool_name=prepared.tool_name,
        authorization_arguments={**prepared.authorization_arguments, "cwd": "/other"},
        execution_arguments=prepared.execution_arguments,
        cwd=prepared.cwd,
        fingerprint="authorized",
        effects=prepared.effects,
    )

    with pytest.raises(RuntimeError, match="no longer matches"):
        asyncio.run(
            binding.handler(
                action,
                AuthorizedToolContext(
                    tool_call_id="delegate-1",
                    exec_service=_ExecService(),
                ),
            )
        )


def test_delegate_agent_does_not_let_product_projection_change_process_status() -> None:
    adapter = _Adapter(result=AgentInvocationResult("pretend success", 0))
    definition = AgentDelegateToolPack(adapter=adapter).definition()

    with pytest.raises(RuntimeError, match="changed subprocess status"):
        asyncio.run(
            ToolExecutionHost(_Gateway()).dispatch(
                definition,
                _call(agent_type="reviewer", task="review this"),
                ToolCallContext(
                    tool_call_id="delegate-1",
                    cwd="/workspace",
                    exec_service=_ExecService(ExecResult(exit_code=2)),
                ),
            )
        )


@pytest.mark.parametrize(
    ("projected", "error", "message"),
    (
        (AgentInvocationResult("late", -9, timed_out=True), TimeoutError, "timed out"),
        (AgentInvocationResult("stopped", -9, cancelled=True), RuntimeError, "aborted"),
        (AgentInvocationResult("failure", 2), RuntimeError, "exited with code 2"),
        (AgentInvocationResult("", 0), RuntimeError, "returned no output"),
    ),
)
def test_delegate_agent_projects_stable_failure_semantics(
    projected: AgentInvocationResult,
    error: type[Exception],
    message: str,
) -> None:
    adapter = _Adapter(result=projected)
    definition = AgentDelegateToolPack(adapter=adapter).definition()
    exec_service = _ExecService(
        ExecResult(
            exit_code=projected.exit_code,
            timed_out=projected.timed_out,
            cancelled=projected.cancelled,
        )
    )

    with pytest.raises(error, match=message):
        asyncio.run(
            ToolExecutionHost(_Gateway()).dispatch(
                definition,
                _call(agent_type="reviewer", task="review this"),
                ToolCallContext(
                    tool_call_id="delegate-1",
                    cwd="/workspace",
                    exec_service=exec_service,
                ),
            )
        )


def test_delegate_agent_rejects_unadmitted_types_before_process_execution() -> None:
    binding = AgentDelegateToolPack(adapter=_Adapter()).definition().execution
    assert isinstance(binding, AuthorizedExecution)

    with pytest.raises(ValueError, match="not admitted"):
        binding.action_adapter.prepare(
            _call(agent_type="implementation_worker", task="edit files"),
            ToolCallContext(tool_call_id="delegate-1", cwd="/workspace"),
        )
