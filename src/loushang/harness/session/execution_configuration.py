"""Invocation-local configuration owned by the original Agent Session.

Handles are registered before publication, remain reachable after partial setup,
and revoke only their own overlay. No baseline setter or snapshot restoration.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loushang.agent.types import AgentRunOptions, AgentState, AgentTool, StreamFn
from loushang.ai.model import Model
from loushang.harness.policy import PolicyDecision, PolicyEvaluator, evaluate_policy
from loushang.harness.session.execution_admission import (
    ExecutionReservation,
    SessionExecutionAdmission,
    SessionExecutionUnavailable,
)


@runtime_checkable
class ExecutionAgentPort(Protocol):
    @property
    def state(self) -> AgentState: ...

    @property
    def model(self) -> Model: ...

    @property
    def tools(self) -> Sequence[AgentTool]: ...

    @property
    def system_prompt(self) -> str: ...

    @property
    def stream_fn(self) -> StreamFn: ...

    @property
    def is_streaming(self) -> bool: ...


class ExecutionConfigurationError(RuntimeError):
    def __init__(self, handle: ExecutionConfiguration):
        super().__init__("execution configuration publication failed; cleanup handle retained")
        self.handle = handle


@dataclass(eq=False)
class ExecutionConfiguration:
    owner: SessionExecutionConfiguration
    execution: ExecutionReservation
    stream_fn: StreamFn | None
    tool_names: tuple[str, ...] | None
    render_prompt: Callable[[tuple[str, ...]], str] | None
    suppress_recovery: bool
    additional_policy: PolicyEvaluator | None = None
    published: bool = False
    released: bool = False

    def _publish(self) -> None:
        agent = self.owner.agent
        if not isinstance(agent, ExecutionAgentPort):
            raise SessionExecutionUnavailable("Session has no Agent invocation configuration port")
        self.owner.admission.check_execution(self.execution)
        self._model, self._baseline_stream = agent.model, agent.stream_fn
        self._baseline_prompt = agent.system_prompt
        self._selected = {
            tool.name: tool for tool in agent.tools
            if self.tool_names is None or tool.name in self.tool_names
        }
        if self.tool_names is not None and set(self._selected) != set(self.tool_names):
            raise SessionExecutionUnavailable("execution tools are not in the current selection")
        self._prompt = None
        if self.tool_names is not None:
            if self.render_prompt is None or agent.state.provider_window is not None:
                raise SessionExecutionUnavailable("Session cannot render this invocation's tool prompt")
            self._prompt = self.render_prompt(self.tool_names)
        self.published = True

    def checkpoint(self) -> None:
        self.owner.admission.check_execution(self.execution)
        if self.released or not self.published:
            raise SessionExecutionUnavailable("execution configuration is not published")
        agent = self.owner.agent
        if (agent.model != self._model or agent.stream_fn is not self._baseline_stream
                or agent.system_prompt != self._baseline_prompt):
            raise SessionExecutionUnavailable("Session configuration changed before model preparation")
        current = {tool.name: tool for tool in agent.tools}
        if any(current.get(name) != tool for name, tool in self._selected.items()):
            raise SessionExecutionUnavailable("Session tool selection changed before model preparation")

    def run_options(self) -> AgentRunOptions:
        self.checkpoint()
        return AgentRunOptions(
            stream_fn=self.stream_fn,
            tool_names=frozenset(self.tool_names) if self.tool_names is not None else None,
            system_prompt=self._prompt, deliver_queued_input=not self.execution.exclusive_input,
            checkpoint=self.checkpoint,
            execution_scope=self.owner.admission.execution_scope(self.execution),
        )

    def release(self) -> None:
        if self.released:
            return
        if self.execution.children_active or self.owner.agent.is_streaming:
            raise SessionExecutionUnavailable("Agent invocation must settle before configuration release")
        self.owner._handles.pop(self.execution, None)
        self.released, self.published = True, False


class SessionExecutionConfiguration:
    def __init__(self, agent: ExecutionAgentPort, admission: SessionExecutionAdmission) -> None:
        self.agent, self.admission = agent, admission
        self._handles: dict[ExecutionReservation, ExecutionConfiguration] = {}

    def install(
        self, execution: ExecutionReservation, *, stream_fn: StreamFn | None = None,
        tool_names: tuple[str, ...] | None = None,
        render_prompt: Callable[[tuple[str, ...]], str] | None = None,
        suppress_recovery: bool = True,
        additional_policy: PolicyEvaluator | None = None,
    ) -> ExecutionConfiguration:
        if execution in self._handles:
            raise SessionExecutionUnavailable("execution configuration already retained")
        self.admission.check_execution(execution)
        handle = ExecutionConfiguration(self, execution, stream_fn, tool_names, render_prompt,
                                        suppress_recovery, additional_policy)
        self._handles[execution] = handle
        try:
            handle._publish()
        except BaseException as error:
            raise ExecutionConfigurationError(handle) from error
        return handle

    def is_configured(self, execution: ExecutionReservation) -> bool:
        return execution in self._handles

    def require(self, execution: ExecutionReservation) -> ExecutionConfiguration:
        handle = self._handles.get(execution)
        if handle is None or not handle.published or handle.released:
            raise SessionExecutionUnavailable("execution configuration is unavailable")
        return handle

    def current(self) -> ExecutionConfiguration | None:
        execution = self.admission.current_execution()
        return self._handles.get(execution) if execution is not None else None

    async def evaluate(self, subject, /) -> PolicyDecision | None:
        if not any(handle.published for handle in self._handles.values()):
            return None
        try:
            current = self.current()
        except SessionExecutionUnavailable:
            current = None
        if current is None or not current.published or current.released:
            return PolicyDecision.deny("tool outside admitted execution", code="execution_scope")
        if current.additional_policy is None:
            return None
        decision = await evaluate_policy(current.additional_policy, subject)
        # An operation may further restrict the original policy, never grant
        # permission when the original authority abstained.
        return None if decision is not None and decision.disposition == "allow" else decision

    @property
    def recovery_allowed(self) -> bool:
        published = [handle for handle in self._handles.values() if handle.published]
        if not published:
            return True
        try:
            current = self.current()
        except SessionExecutionUnavailable:
            return False
        return current is not None and current in published and not current.suppress_recovery

    def close(self) -> None:
        for handle in tuple(self._handles.values()):
            handle.release()

    def release_execution(self, execution: ExecutionReservation) -> None:
        handle = self._handles.get(execution)
        if handle is not None:
            handle.release()
