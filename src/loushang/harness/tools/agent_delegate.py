"""Authorized one-shot agent invocation exposed as a model-visible tool."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from loushang.agent.types import AgentToolResult, TextPart
from loushang.ai.types import ToolCall
from loushang.harness.effects import ProcessEffect
from loushang.harness.policy import (
    build_tool_policy_subject,
    executable_search_path_from_env,
    normalize_command_subject,
)
from loushang.harness.tools.contribution import ToolPackDefinition
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    PreparedToolAction,
    ToolCallContext,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.exec import ExecRequest, ExecResult

AGENT_DELEGATE_TOOL_NAME = "delegate_agent"
AGENT_DELEGATE_TOOL_PACK = ToolPackDefinition(
    name="harness.agent_delegate",
    tools=(AGENT_DELEGATE_TOOL_NAME,),
)
MAX_AGENT_DELEGATE_TASK_CHARS = 100_000


@dataclass(frozen=True, slots=True)
class AgentInvocationRequest:
    """Model-requested, Product-neutral input for one finite invocation."""

    agent_type: str
    task: str = field(repr=False)
    cwd: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent_type, str) or not self.agent_type.strip():
            raise ValueError("agent_type must be a non-empty string")
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("task must be a non-empty string")
        if len(self.task) > MAX_AGENT_DELEGATE_TASK_CHARS:
            raise ValueError(
                "task exceeds the delegate_agent input limit of "
                f"{MAX_AGENT_DELEGATE_TASK_CHARS} characters"
            )
        if self.cwd is not None and (
            not isinstance(self.cwd, str) or not self.cwd.strip()
        ):
            raise ValueError("cwd must be a non-empty string when provided")


@dataclass(frozen=True, slots=True)
class PreparedAgentInvocation:
    """Complete subprocess plan frozen before Policy and Approval."""

    request: AgentInvocationRequest
    exec_request: ExecRequest = field(repr=False)
    allowed_tools: tuple[str, ...]
    model_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, AgentInvocationRequest):
            raise TypeError("request must be an AgentInvocationRequest")
        if not isinstance(self.exec_request, ExecRequest):
            raise TypeError("exec_request must be an ExecRequest")
        tools = tuple(self.allowed_tools)
        if not tools or any(not isinstance(tool, str) or not tool for tool in tools):
            raise ValueError("allowed_tools must contain non-empty tool names")
        if len(set(tools)) != len(tools):
            raise ValueError("allowed_tools must not contain duplicates")
        if self.model_ref is not None and (
            not isinstance(self.model_ref, str) or not self.model_ref
        ):
            raise ValueError("model_ref must be non-empty when provided")
        if not self.exec_request.command:
            raise ValueError("agent invocation command must not be empty")
        if self.exec_request.cwd is None:
            raise ValueError("agent invocation cwd must be materialized")
        if self.exec_request.effective_environment is None:
            raise ValueError("agent invocation environment must be materialized")
        if self.exec_request.stdin != self.request.task:
            raise ValueError("agent invocation task must be carried through stdin")
        object.__setattr__(self, "allowed_tools", tools)

    @property
    def task_digest(self) -> str:
        return _text_digest(self.request.task)

    @property
    def environment_digest(self) -> str:
        environment = self.exec_request.effective_environment
        assert environment is not None
        serialized = json.dumps(
            sorted(environment),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return _text_digest(serialized)


@dataclass(frozen=True, slots=True)
class AgentInvocationResult:
    """Bounded child-process projection returned to the invoking model."""

    output_text: str = field(repr=False)
    exit_code: int
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.output_text, str):
            raise TypeError("output_text must be a string")
        if type(self.exit_code) is not int:
            raise TypeError("exit_code must be an integer")
        for name, value in (
            ("timed_out", self.timed_out),
            ("cancelled", self.cancelled),
            ("truncated", self.truncated),
        ):
            if type(value) is not bool:
                raise TypeError(f"{name} must be a boolean")


class AgentInvocationAdapter(Protocol):
    """Product-owned compiler/projector around the neutral process boundary."""

    @property
    def admitted_agent_types(self) -> tuple[str, ...]: ...

    def prepare(
        self,
        request: AgentInvocationRequest,
        *,
        default_cwd: str | None,
        model: object | None,
    ) -> PreparedAgentInvocation: ...

    def project(
        self,
        prepared: PreparedAgentInvocation,
        result: ExecResult,
    ) -> AgentInvocationResult: ...


@dataclass(frozen=True, slots=True)
class _AgentDelegateActionAdapter:
    adapter: AgentInvocationAdapter

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        arguments = dict(call.arguments)
        request = AgentInvocationRequest(
            agent_type=_required_string(arguments.get("agent_type"), "agent_type"),
            task=_required_string(arguments.get("task"), "task"),
            cwd=_optional_string(arguments.get("cwd"), "cwd"),
        )
        if request.agent_type not in self.adapter.admitted_agent_types:
            raise ValueError(
                f"agent type {request.agent_type!r} is not admitted for "
                f"{AGENT_DELEGATE_TOOL_NAME}"
            )
        prepared = self.adapter.prepare(
            request,
            default_cwd=context.cwd,
            model=context.model,
        )
        _validate_adapter_output(request, prepared)
        exec_request = prepared.exec_request
        environment = exec_request.effective_environment
        assert environment is not None
        effect = ProcessEffect(exec_request.command)
        authorization_arguments = _authorization_arguments(prepared)
        command_subject = normalize_command_subject(
            exec_request.command,
            cwd=exec_request.cwd,
            stdin=None,
            executable_search_path=executable_search_path_from_env(
                environment,
                default=os.defpath,
            ),
            environment_overrides=environment,
            environment_is_complete=True,
        )
        return PreparedToolAction(
            tool_name=AGENT_DELEGATE_TOOL_NAME,
            authorization_arguments=authorization_arguments,
            execution_arguments={"prepared_invocation": prepared},
            cwd=exec_request.cwd,
            effects=(effect,),
            policy_subject=build_tool_policy_subject(
                tool_name=AGENT_DELEGATE_TOOL_NAME,
                arguments=authorization_arguments,
                cwd=exec_request.cwd,
                command=command_subject,
                effects=(effect,),
            ),
            execution_environment=environment,
        )


@dataclass(frozen=True, slots=True)
class _AgentDelegateAuthorizedHandler:
    adapter: AgentInvocationAdapter

    async def __call__(
        self,
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        prepared = action.execution_arguments.get("prepared_invocation")
        if not isinstance(prepared, PreparedAgentInvocation):
            raise TypeError(
                "authorized delegate_agent action requires a "
                "PreparedAgentInvocation"
            )
        if dict(action.authorization_arguments) != _authorization_arguments(prepared):
            raise RuntimeError("authorized delegate_agent plan no longer matches")
        execute = getattr(context.exec_service, "execute", None)
        if not callable(execute):
            raise RuntimeError("delegate_agent requires an authorized exec service")

        exec_request = (
            replace(
                prepared.exec_request,
                execution_profile=action.execution_profile,
            )
            if action.execution_profile is not None
            else prepared.exec_request
        )
        result = execute(exec_request, signal=context.signal)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ExecResult):
            raise TypeError("delegate_agent exec service must return ExecResult")

        projected = self.adapter.project(prepared, result)
        if not isinstance(projected, AgentInvocationResult):
            raise TypeError(
                "agent invocation adapter must return AgentInvocationResult"
            )
        if (
            projected.exit_code != result.exit_code
            or projected.timed_out != result.timed_out
            or projected.cancelled != result.cancelled
        ):
            raise RuntimeError(
                "agent invocation adapter changed subprocess status semantics"
            )
        if projected.timed_out:
            raise TimeoutError(_failure_message(projected, "Delegated agent timed out"))
        if projected.cancelled:
            raise RuntimeError(_failure_message(projected, "Delegated agent aborted"))
        if projected.exit_code != 0:
            raise RuntimeError(
                _failure_message(
                    projected,
                    f"Delegated agent exited with code {projected.exit_code}",
                )
            )
        if not projected.output_text.strip():
            raise RuntimeError("Delegated agent returned no output")
        return AgentToolResult(
            content=[TextPart(type="text", text=projected.output_text)],
            details={
                "agent_type": prepared.request.agent_type,
                "exit_code": projected.exit_code,
                "timed_out": projected.timed_out,
                "cancelled": projected.cancelled,
                "truncated": projected.truncated,
                "allowed_tools": list(prepared.allowed_tools),
                "model": prepared.model_ref,
            },
        )


class AgentDelegateToolPack:
    """Bind one Product adapter to the shared authorized tool definition."""

    def __init__(self, *, adapter: AgentInvocationAdapter) -> None:
        admitted = tuple(adapter.admitted_agent_types)
        if not admitted or any(
            not isinstance(agent_type, str) or not agent_type
            for agent_type in admitted
        ):
            raise ValueError("delegate_agent requires admitted agent types")
        if len(set(admitted)) != len(admitted):
            raise ValueError("admitted agent types must not contain duplicates")
        self._adapter = adapter
        self._admitted_agent_types = admitted

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (self.definition(),)

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=AGENT_DELEGATE_TOOL_NAME,
            label="Delegate agent",
            description=(
                "Run one admitted read-only agent as a finite subprocess and "
                "return its bounded output. The child has no session, follow-up, "
                "interactive approval, or further agent-delegation capability."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_type": {
                        "type": "string",
                        "enum": list(self._admitted_agent_types),
                    },
                    "task": {
                        "type": "string",
                        "maxLength": MAX_AGENT_DELEGATE_TASK_CHARS,
                    },
                    "cwd": {"type": "string"},
                },
                "required": ["agent_type", "task"],
                "additionalProperties": False,
            },
            execution=AuthorizedExecution(
                action_adapter=_AgentDelegateActionAdapter(self._adapter),
                handler=_AgentDelegateAuthorizedHandler(self._adapter),
            ),
            execution_mode="sequential",
            prompt_snippet=(
                "- delegate_agent: Run one bounded read-only agent task in a "
                "subprocess and wait for its output."
            ),
            prompt_guidelines=(
                "Use delegate_agent only for a focused task that can finish in one response.",
                "Do not expect follow-up, steering, persisted state, or interactive approval from the child.",
            ),
        )

    def register(
        self,
        registry: WorkspaceToolRegistry,
        *,
        enabled: bool = True,
    ) -> WorkspaceToolRegistry:
        registry.register_tool(self.definition(), enabled=enabled)
        return registry


def _authorization_arguments(
    prepared: PreparedAgentInvocation,
) -> dict[str, object]:
    request = prepared.exec_request
    return {
        "agent_type": prepared.request.agent_type,
        "cwd": request.cwd,
        "command": request.command,
        "allowed_tools": prepared.allowed_tools,
        "model": prepared.model_ref,
        "task_sha256": prepared.task_digest,
        "environment_sha256": prepared.environment_digest,
        "timeout_seconds": request.timeout_seconds,
    }


def _validate_adapter_output(
    request: AgentInvocationRequest,
    prepared: PreparedAgentInvocation,
) -> None:
    if not isinstance(prepared, PreparedAgentInvocation):
        raise TypeError(
            "agent invocation adapter must return PreparedAgentInvocation"
        )
    if prepared.request != request:
        raise ValueError("agent invocation adapter changed the invocation request")


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_name)


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _failure_message(result: AgentInvocationResult, prefix: str) -> str:
    output = result.output_text.strip()
    return f"{prefix}: {output}" if output else prefix


__all__ = [
    "AGENT_DELEGATE_TOOL_NAME",
    "AGENT_DELEGATE_TOOL_PACK",
    "MAX_AGENT_DELEGATE_TASK_CHARS",
    "AgentDelegateToolPack",
    "AgentInvocationAdapter",
    "AgentInvocationRequest",
    "AgentInvocationResult",
    "PreparedAgentInvocation",
]
