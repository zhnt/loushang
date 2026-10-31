"""Create and own child Agent sessions through the existing multi-agent seam.

Products supply runtime construction and workspace policy. The returned driver
calls the Session's existing prompt/continue/abort methods; it adds no Host or
input queue around a Session that already owns those mechanisms.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from loushang.harness.approval import ActorBoundApprovalResolver, DenyApprovalResolver
from loushang.harness.approval.ports import ApprovalResolver
from loushang.harness.multiagent import (
    AgentInputMessage,
    SubagentDisposeResult,
    SubagentRoundResult,
    WorkspaceLease,
    WorkspaceLeasePort,
    WorkspaceLeaseRequest,
    WorkspaceLeaseSnapshot,
)
from loushang.harness.multiagent.run_handle import RoundMode
from loushang.harness.session.multiagent import (
    SessionSubagentBinding,
    SessionSubagentCreationError,
    SessionSubagentRequest,
    build_agent_session_input_facade,
    install_agent_forked_history,
    project_agent_round_result,
)


class ChildSessionRuntime(Protocol):
    async def create_session(self, *, cwd: str) -> Any: ...

    async def dispose_session_runtime(self) -> None: ...


ChildRuntimeBuilder = Callable[
    [SessionSubagentRequest, Path, ActorBoundApprovalResolver, WorkspaceLease | None],
    ChildSessionRuntime,
]


class AgentSessionSubagentFactory:
    """Build one Product runtime, retaining every acquired resource on failure."""

    def __init__(
        self,
        *,
        cwd: str | Path,
        runtime_builder: ChildRuntimeBuilder,
        approval_resolver: ApprovalResolver | None = None,
        workspace_leases: WorkspaceLeasePort | None = None,
        missing_response: str = "Child agent produced no assistant response.",
        completed_response: str = "Child agent completed.",
    ) -> None:
        self._cwd = Path(cwd).expanduser().resolve()
        if not self._cwd.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(self._cwd))
        self._build = runtime_builder
        self._approval = approval_resolver
        self._workspaces = workspace_leases
        self._missing_response = missing_response
        self._completed_response = completed_response

    async def create(self, request: SessionSubagentRequest) -> SessionSubagentBinding:
        owner = _AgentSessionChild(
            self._workspaces, self._missing_response, self._completed_response
        )
        cwd = self._cwd
        try:
            if request.agent_type.workspace_mode == "isolated":
                if self._workspaces is None:
                    raise RuntimeError("isolated child requires a workspace lease")
                owner._lease = await self._workspaces.acquire(
                    WorkspaceLeaseRequest(
                        request.record.ref, request.agent_type.name, "isolated"
                    )
                )
                cwd = Path(owner._lease.execution_ref)
            plan = request.context_plan
            resolver = (
                plan.approval_resolver
                if plan is not None and plan.approval_resolver is not None
                else self._approval or DenyApprovalResolver()
            )
            owner._approval = ActorBoundApprovalResolver(
                resolver, str(request.record.ref)
            )
            # Construction is synchronous: once returned, the runtime is owned
            # before the first await. Builders own their own partial failures.
            owner._runtime = self._build(request, cwd, owner._approval, owner._lease)
            owner._session = await owner._runtime.create_session(cwd=str(cwd))
            install_agent_forked_history(owner._session, plan)
            owner.input_facade = build_agent_session_input_facade(owner._session)
            return SessionSubagentBinding(
                driver=owner,
                input_activity=owner.input_facade,
                workspace_ref=owner._lease.workspace_ref if owner._lease else None,
            )
        except BaseException as error:
            try:
                result = await owner.dispose()
            except BaseException as cleanup_error:
                raise SessionSubagentCreationError(
                    owner, error, cleanup_error
                ) from error
            if result.dispose_error is not None:
                raise SessionSubagentCreationError(
                    owner, error, result.dispose_error
                ) from error
            raise


class _AgentSessionChild:
    """Private driver and cleanup owner for the already-hosted Agent Session."""

    def __init__(self, workspaces, missing_response: str, completed_response: str):
        self._runtime: ChildSessionRuntime | None = None
        self._session: Any = None
        self.input_facade: Any = None
        self._approval: ActorBoundApprovalResolver | None = None
        self._lease: WorkspaceLease | None = None
        self._workspaces: WorkspaceLeasePort | None = workspaces
        self._initial_message: AgentInputMessage | None = None
        self._rounds_started = 0
        self._missing_response, self._completed_response = (
            missing_response,
            completed_response,
        )
        self._dispose_task: asyncio.Task[SubagentDisposeResult] | None = None
        self._approval_closed = self._runtime_closed = False
        self._released: WorkspaceLeaseSnapshot | None = None

    def deliver(self, message: AgentInputMessage) -> None:
        if self._dispose_task is not None:
            raise RuntimeError("child session is closing")
        if self._rounds_started == 0 and self._initial_message is None:
            self._initial_message = message
        else:
            self.input_facade.enqueue_message(message)

    async def run_round(self, *, round_id: int, mode: RoundMode) -> SubagentRoundResult:
        del round_id
        if self._dispose_task is not None:
            raise RuntimeError("child session is closing")
        assert self._approval is not None
        self._approval.open_session()
        message_count = len(self._session.agent.state.messages)
        self._rounds_started += 1
        if mode == "prompt":
            initial, self._initial_message = self._initial_message, None
            if initial is None:
                raise RuntimeError("child has no staged initial prompt")
            await self._session.prompt(
                initial.text, source=f"multiagent:{initial.message_id}"
            )
        else:
            await self._session.continue_run()
        result = project_agent_round_result(
            tuple(self._session.agent.state.messages[message_count:]),
            missing_response=self._missing_response,
            completed_response=self._completed_response,
        )
        if self._lease is None or self._workspaces is None:
            return result
        snapshot = await self._workspaces.snapshot(self._lease)
        return replace(
            result,
            workspace_ref=snapshot.workspace_ref,
            artifact_refs=snapshot.artifact_refs,
            change_set_ref=snapshot.change_set_ref,
        )

    def abort(self) -> None:
        if self._approval is not None:
            self._approval.close_session("Child agent interrupted")
        if self._session is not None:
            self._session.abort()

    async def dispose(self) -> SubagentDisposeResult:
        task = self._dispose_task
        if task is None or (
            task.done()
            and (
                task.cancelled()
                or task.exception() is not None
                or task.result().dispose_error is not None
            )
        ):
            task = asyncio.create_task(
                self._dispose_owned(), name="child-session:dispose"
            )
            self._dispose_task = task
            task.add_done_callback(self._observe_dispose)
        return await asyncio.shield(task)

    @staticmethod
    def _observe_dispose(task: asyncio.Task[SubagentDisposeResult]) -> None:
        if not task.cancelled():
            task.exception()

    async def _dispose_owned(self) -> SubagentDisposeResult:
        try:
            if not self._approval_closed:
                if self._approval is not None:
                    self._approval.end_session("Child agent closed")
                self._approval_closed = True
            if not self._runtime_closed:
                if self._runtime is not None:
                    await self._runtime.dispose_session_runtime()
                self._runtime_closed = True
            # The workspace remains available until all child runtime owners
            # have actually closed. Failed stages retry these same objects.
            if self._released is None and self._lease is not None:
                assert self._workspaces is not None
                self._released = await self._workspaces.release(self._lease)
            return SubagentDisposeResult(released_workspace=self._released)
        except Exception as error:
            return SubagentDisposeResult(dispose_error=error)


__all__ = ["AgentSessionSubagentFactory", "ChildRuntimeBuilder", "ChildSessionRuntime"]
