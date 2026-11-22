"""Create and own child Agent sessions through the existing multi-agent seam.

Products supply runtime construction and workspace policy. The returned driver
calls the Session's existing prompt/continue/abort methods; it adds no Host or
input queue around a Session that already owns those mechanisms.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import InitVar, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from loushang.ai.model import Model, ModelSelection, parse_model_selection_reference
from loushang.foundation._owned_tasks import (
    _observe_task_result,
)
from loushang.harness.approval import ActorBoundApprovalResolver, DenyApprovalResolver
from loushang.harness.approval.ports import ApprovalResolver
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.environment import HostEnvironment
from loushang.harness.multiagent import (
    AgentInputMessage,
    DelegatedExecutionProfile,
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
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.tools.workspace.selection import (
    peer_tool_names,
    platform_tool_names,
)

if TYPE_CHECKING:
    from loushang.harness.session import BootstrapServices


class ChildSessionRuntime(Protocol):
    async def create_session(self, *, cwd: str) -> Any: ...

    async def dispose_session_runtime(self) -> None: ...


ChildRuntimeBuilder = Callable[
    [SessionSubagentRequest, Path, ActorBoundApprovalResolver, WorkspaceLease | None],
    ChildSessionRuntime,
]


@dataclass(slots=True)
class SubagentConstruction:
    """Bind Product policy to the synchronous child runtime builder."""

    product_label: str
    session_dir: Path
    registry: WorkspaceToolRegistry
    runtime_builder: Callable[..., ChildSessionRuntime]
    default_model: Callable[[], Model | ModelSelection | None]
    services: BootstrapServices | None
    host_environment: HostEnvironment
    exact_owner_tools: tuple[str, ...]
    selected_exact_tools: InitVar[tuple[str, ...]]
    writable_roles: frozenset[str]
    workspace_ceiling: Callable[[Path, bool], EffectiveExecutionProfile]
    role_prompt: Callable[[str], str]
    _selected: frozenset[str] = field(init=False)

    def __post_init__(self, selected_exact_tools: tuple[str, ...]) -> None:
        selected = tuple(selected_exact_tools)
        if len(set(selected)) != len(selected):
            raise ValueError("selected exact Tool names must not contain duplicates")
        unknown = tuple(name for name in selected if name not in self.exact_owner_tools)
        if unknown:
            raise ValueError(
                f"selected exact Tool names are not {self.product_label} exact-owner identities: "
                + ", ".join(unknown)
            )
        self._selected = frozenset(selected)

    def build(
        self,
        request: SessionSubagentRequest,
        cwd: Path,
        approval: ActorBoundApprovalResolver,
        lease: WorkspaceLease | None,
    ) -> ChildSessionRuntime:
        plan = request.context_plan
        spec = request.agent_type
        requested = spec.allowed_tools
        if plan is not None:
            unexpected = tuple(name for name in plan.allowed_tools if name not in requested)
            if unexpected:
                raise ValueError(
                    f"subagent context requested non-admitted {self.product_label} tools: "
                    + ", ".join(unexpected)
                )
            requested = plan.allowed_tools
        allowed_tools = platform_tool_names(requested, self.host_environment)
        unselected = tuple(
            name
            for name in allowed_tools
            if name in self.exact_owner_tools and name not in self._selected
        )
        if unselected:
            raise ValueError(
                f"{self.product_label} child exact-owner tools are not selected: "
                + ", ".join(unselected)
            )

        model_ref = plan.model if plan is not None else None
        if model_ref is None:
            model_ref = spec.default_model
        registry = getattr(
            getattr(self.services, "model_registry", None), "ai_registry", None
        )
        model = (
            parse_model_selection_reference(model_ref, registry=registry)
            if model_ref is not None
            else self.default_model()
        )
        actor_ref = request.record.ref
        writable = spec.name in self.writable_roles
        profile = DelegatedExecutionProfile(
            actor_ref=actor_ref,
            allowed_tools=allowed_tools,
            execution_profile_ceiling=self.workspace_ceiling(cwd, writable),
            approval_actor_id=str(request.record.ref),
            workspace_ref=lease.workspace_ref if lease is not None else None,
        )
        prompt = plan.system_prompt if plan is not None else self.role_prompt(spec.name)
        peer_names = peer_tool_names(allowed_tools, self.exact_owner_tools)
        enabled = {
            definition.name for definition in self.registry.list_enabled_definitions()
        }
        missing = tuple(name for name in peer_names if name not in enabled)
        if missing:
            raise ValueError(
                f"{self.product_label} child tools are not registered and enabled: "
                + ", ".join(missing)
            )
        return self.runtime_builder(
            session_dir=self.session_dir,
            model=model,
            system_prompt=prompt,
            tool_registry=self.registry.select(peer_names),
            allowed_tool_names=list(allowed_tools),
            active_tool_names=list(allowed_tools),
            services=self.services,
            persist=False,
            sandbox_workspace_writable=writable,
            approval_resolver=approval,
            delegated_execution_profile=profile,
        )


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
                    owner, error, cleanup_error, ref=request.record.ref
                ) from error
            if result.dispose_error is not None:
                raise SessionSubagentCreationError(
                    owner, error, result.dispose_error, ref=request.record.ref
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

    _observe_dispose = staticmethod(_observe_task_result)

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
