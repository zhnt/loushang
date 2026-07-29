"""Coding adapters for the Product-neutral multi-agent session runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from loushang.ai.model import Model, ModelSelection, parse_model_selection_reference
from loushang.ai.types import (
    AssistantMessage,
    Message,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from loushang.coding.prompt.defaults import DEFAULT_CODING_SYSTEM_PROMPT
from loushang.coding.runtime import AgentSessionRuntime
from loushang.coding.sandbox import coding_workspace_execution_profile
from loushang.coding.session import AgentSession
from loushang.harness.approval import (
    ActorBoundApprovalResolver,
    DenyApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.multiagent import (
    AgentCaller,
    AgentInputMessage,
    AgentTypeRegistry,
    AgentTypeSpec,
    DelegatedExecutionProfile,
    ForkedHistory,
    ForkTier,
    MultiAgentControl,
    SubagentContextPlan,
    SubagentRoundResult,
    WorkspaceLease,
    WorkspaceLeasePort,
    WorkspaceLeaseRequest,
    WorkspaceLeaseSnapshot,
)
from loushang.harness.multiagent.run_handle import RoundMode, SubagentRoundDriver
from loushang.harness.session import BootstrapServices
from loushang.harness.session.multiagent import (
    AgentInputFacade,
    SessionMultiAgentRuntime,
    SessionSubagentFactory,
    SessionSubagentRequest,
)
from loushang.harness.tools.multiagent import MultiAgentToolPack
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import ApplicationMessage

_RuntimeBuilder = Callable[..., AgentSessionRuntime]
_DefaultModelProvider = Callable[[], Model | ModelSelection | None]
_ALLOWED_HISTORY_TYPES = (UserMessage, AssistantMessage, ToolResultMessage)

_ROLE_PROMPTS: Mapping[str, str] = {
    "explorer": (
        "You are a non-writing coding explorer. Inspect the requested code and "
        "report concrete evidence, paths, commands, and relevant constraints. "
        "You may run investigative shell commands, including Git inspection, "
        "local searches, Python analysis, and curl-based network retrieval when "
        "policy permits it. Do not modify product files, install software, "
        "publish changes, or use shell redirection and in-place editing to "
        "bypass the absence of write/edit tools."
    ),
    "reviewer": (
        "You are an independent read-only code reviewer. Identify correctness, "
        "security, lifecycle, and test risks. Lead with actionable findings and "
        "cite the relevant files. Do not modify files or execute shell commands."
    ),
    "synthesizer": (
        "You are a read-only review synthesizer. Reconcile independent findings, "
        "preserve material disagreements, distinguish blockers from optional "
        "improvements, and give one evidence-based recommendation."
    ),
    "proposer": (
        "You are the proposing side of a technical debate. Build the strongest "
        "evidence-based case for the requested proposal and state its assumptions."
    ),
    "critic": (
        "You are the critical side of a technical debate. Challenge the proposal "
        "with concrete counterexamples, hidden costs, and invalid assumptions."
    ),
    "judge": (
        "You are an impartial technical judge. Compare both positions against the "
        "evidence, state unresolved uncertainty, and give a reasoned decision."
    ),
    "implementation_worker": (
        "You are an implementation worker in a system-managed isolated Git "
        "worktree. Make the requested bounded change, run focused validation, and "
        "report the files changed and remaining risks. Do not merge branches."
    ),
    "shared_implementation_worker": (
        "You are an implementation worker sharing the parent Coding session's "
        "current worktree and branch. Other agents may modify this worktree "
        "concurrently. Make only the requested bounded change within your "
        "explicitly assigned files or responsibility, preserve unrelated and "
        "uncommitted edits, and adapt to changes made by others instead of "
        "reverting them. Run focused validation and report the files changed and "
        "remaining risks. Do not commit, merge, publish, or modify files outside "
        "the assigned scope. Stop and report the conflict if your required write "
        "scope overlaps the parent or another worker."
    ),
    "test_runner": (
        "You are a test runner in a system-managed isolated Git worktree. Run the "
        "requested checks, diagnose failures, and report reproducible evidence. "
        "Do not intentionally edit product source files or merge branches."
    ),
}


def coding_read_only_agent_types(
    *,
    default_model: str | None = None,
    maximum_children: int = 3,
) -> AgentTypeRegistry:
    """Return Coding's initial admitted, non-writing analysis roles."""

    return AgentTypeRegistry(
        AgentTypeSpec(
            name=name,
            default_model=default_model,
            allowed_tools=(
                ("bash", "read", "grep", "find", "ls")
                if name == "explorer"
                else ("read", "grep", "find", "ls")
            ),
            maximum_children=(
                maximum_children if name in {"explorer", "reviewer"} else 1
            ),
        )
        for name in (
            "explorer",
            "reviewer",
            "synthesizer",
            "proposer",
            "critic",
            "judge",
        )
    )


def coding_agent_types(
    *,
    default_model: str | None = None,
    maximum_children: int = 3,
) -> AgentTypeRegistry:
    """Return Coding's complete phase-two type catalog."""

    read_only = coding_read_only_agent_types(
        default_model=default_model,
        maximum_children=maximum_children,
    )
    return AgentTypeRegistry(
        (
            *read_only.values(),
            AgentTypeSpec(
                name="implementation_worker",
                default_model=default_model,
                allowed_tools=(
                    "bash",
                    "read",
                    "grep",
                    "find",
                    "ls",
                    "write",
                    "edit",
                ),
                maximum_children=maximum_children,
                workspace_mode="isolated",
            ),
            AgentTypeSpec(
                name="shared_implementation_worker",
                default_model=default_model,
                allowed_tools=(
                    "bash",
                    "read",
                    "grep",
                    "find",
                    "ls",
                    "write",
                    "edit",
                ),
                maximum_children=maximum_children,
                workspace_mode="inherit",
            ),
            AgentTypeSpec(
                name="test_runner",
                default_model=default_model,
                allowed_tools=("bash", "read", "grep", "find", "ls"),
                maximum_children=maximum_children,
                workspace_mode="isolated",
            ),
        )
    )


def coding_multiagent_system_prompt(
    agent_types: AgentTypeRegistry,
) -> str:
    """Describe the admitted Coding collaboration surface to the root model."""

    role_descriptions = {
        "explorer": (
            "inspect code, run investigative commands, and report evidence "
            "without modifying product files"
        ),
        "reviewer": "independently review correctness, lifecycle, security, and tests",
        "synthesizer": "reconcile independent reviews into one recommendation",
        "proposer": "make an evidence-based case for a proposal",
        "critic": "challenge a proposal and expose invalid assumptions",
        "judge": "compare both sides and give an impartial decision",
        "implementation_worker": (
            "implement a bounded change in a managed isolated Git worktree"
        ),
        "shared_implementation_worker": (
            "implement a bounded change directly in the current worktree and "
            "branch; multiple workers require explicitly assigned, disjoint "
            "files or responsibilities"
        ),
        "test_runner": "run and diagnose checks in a managed isolated Git worktree",
    }
    type_lines = "\n".join(
        f"- `{spec.name}`: {role_descriptions.get(spec.name, 'bounded Coding task')}; "
        f"tools: {', '.join(spec.allowed_tools) or 'none'}; "
        f"maximum open children: {spec.maximum_children}"
        for spec in agent_types.values()
    )
    return (
        "## Multi-agent collaboration\n\n"
        "You may delegate focused work to session-owned child agents with "
        "`spawn_agent`. Spawning is asynchronous: use `wait_agent` to wait for "
        "new collaboration activity, `list_agents` to inspect the visible tree, "
        "and `send_message` for a follow-up. Use `interrupt_agent` or "
        "`close_agent` only for agents you own. Child completion notices enter "
        "your system mailbox, separate from editable follow-up and steering input "
        "queues, and must be synthesized into your answer. A successful "
        "`spawn_agent` call returns the canonical child path. A failed spawn "
        "creates no child: do not claim it succeeded, do not wait for it, and do "
        "not invent a path to close. Instead inspect the structured error and "
        "`list_agents`.\n\n"
        "Choose an agent type whose listed tools cover the delegated task. "
        "A completed child run means that its model turn ended; it is not proof "
        "that the requested task succeeded. Completed, failed, and interrupted "
        "children remain open, addressable, and count against open-child limits "
        "until `close_agent` releases them. Reuse an existing child with "
        "`send_message` when continuity is useful. After one-shot fan-out and "
        "aggregation, close children that are no longer needed. If spawning "
        "reaches a limit, list the tree, then reuse or close an existing child "
        "before retrying. Verify that each child returned the requested evidence "
        "before aggregating it. Preserve result provenance: "
        "never attribute a root fallback, a different child result, or a new "
        "computation to the original child. If required results are missing, "
        "delegate again to a capable type or report the result as incomplete. "
        "For shared implementation work, assign each child explicit ownership "
        "of files or responsibility and run children concurrently only when "
        "their write scopes are disjoint. Tell each shared worker that it is not "
        "alone in the worktree, must not revert others' edits, and must adapt to "
        "concurrent changes. Do not edit an assigned file in the parent while "
        "its worker is running.\n\n"
        "Admitted child types:\n"
        f"{type_lines}"
    )


def coding_recipe_context_plan(
    *,
    agent_type: str,
    model: str | None,
    agent_types: AgentTypeRegistry,
) -> SubagentContextPlan[Message]:
    """Build a fresh, read-only Coding context for one recipe role."""

    spec = agent_types.resolve(agent_type)
    if spec is None:
        raise ValueError(f"Coding recipe agent type is not admitted: {agent_type}")
    return SubagentContextPlan(
        system_prompt=_coding_role_system_prompt(agent_type),
        model=model,
        history=ForkedHistory(
            requested_tier=ForkTier.none(),
            effective_tier=ForkTier.none(),
            watermark=None,
            messages=(),
        ),
        allowed_tools=spec.allowed_tools,
    )


class CodingSubagentFactory(SessionSubagentFactory):
    """Create non-persistent Coding child sessions behind the shared driver seam."""

    def __init__(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        tool_registry: WorkspaceToolRegistry,
        runtime_builder: _RuntimeBuilder,
        default_model: Model | ModelSelection | None = None,
        default_model_provider: _DefaultModelProvider | None = None,
        services: BootstrapServices | None = None,
        approval_resolver: InteractiveApprovalResolver | None = None,
        workspace_leases: WorkspaceLeasePort | None = None,
    ) -> None:
        resolved_cwd = Path(cwd).expanduser().resolve()
        if not resolved_cwd.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(resolved_cwd))
        self._session_dir = Path(session_dir)
        self._cwd = resolved_cwd
        self._tool_registry = tool_registry
        self._default_model_provider = default_model_provider or (lambda: default_model)
        self._services = services
        self._approval_resolver = approval_resolver
        self._runtime_builder = runtime_builder
        self._workspace_leases = workspace_leases

    async def create_driver(
        self,
        request: SessionSubagentRequest,
    ) -> SubagentRoundDriver:
        workspace_lease: WorkspaceLease | None = None
        runtime: AgentSessionRuntime | None = None
        child_approval_resolver: ActorBoundApprovalResolver | None = None
        delegated_execution_profile: DelegatedExecutionProfile | None = None
        child_cwd = self._cwd
        try:
            if request.agent_type.workspace_mode == "isolated":
                if self._workspace_leases is None:
                    raise RuntimeError(
                        f"Coding agent type {request.agent_type.name!r} requires "
                        "an isolated workspace lease"
                    )
                workspace_lease = await self._workspace_leases.acquire(
                    WorkspaceLeaseRequest(
                        agent_ref=request.record.ref,
                        agent_type=request.agent_type.name,
                        mode="isolated",
                    )
                )
                child_cwd = Path(workspace_lease.execution_ref)
            plan = request.context_plan
            allowed_tools = _resolve_allowed_tools(request)
            model_ref = plan.model if plan is not None else None
            if model_ref is None:
                model_ref = request.agent_type.default_model
            model: Model | ModelSelection | None = (
                parse_model_selection_reference(model_ref)
                if model_ref is not None
                else self._default_model_provider()
            )
            approval_resolver = (
                plan.approval_resolver
                if plan is not None and plan.approval_resolver is not None
                else self._approval_resolver or DenyApprovalResolver()
            )
            child_approval_resolver = ActorBoundApprovalResolver(
                resolver=approval_resolver,
                actor_id=str(request.record.ref),
            )
            delegated_execution_profile = DelegatedExecutionProfile(
                actor_ref=request.record.ref,
                allowed_tools=allowed_tools,
                execution_profile_ceiling=coding_workspace_execution_profile(
                    child_cwd,
                    writable=_sandbox_workspace_is_writable(
                        request.agent_type.name
                    ),
                ),
                approval_actor_id=str(request.record.ref),
                workspace_ref=(
                    workspace_lease.workspace_ref
                    if workspace_lease is not None
                    else None
                ),
            )
            runtime = self._runtime_builder(
                session_dir=self._session_dir,
                model=model,
                system_prompt=_resolve_system_prompt(request),
                tool_registry=_select_tool_registry(
                    self._tool_registry,
                    allowed_tools,
                ),
                allowed_tool_names=list(allowed_tools),
                active_tool_names=list(allowed_tools),
                services=self._services,
                persist=False,
                sandbox_workspace_writable=_sandbox_workspace_is_writable(
                    request.agent_type.name
                ),
                approval_resolver=cast(Any, child_approval_resolver),
                delegated_execution_profile=delegated_execution_profile,
            )
            session = await runtime.create_session(cwd=str(child_cwd))
            _install_forked_history(session, request)
        except BaseException:
            try:
                if child_approval_resolver is not None:
                    child_approval_resolver.end_session(
                        "Child session creation failed"
                    )
            finally:
                try:
                    if runtime is not None:
                        await runtime.dispose_session_runtime()
                finally:
                    if (
                        workspace_lease is not None
                        and self._workspace_leases is not None
                    ):
                        await self._workspace_leases.release(workspace_lease)
            raise
        return _CodingSubagentDriver(
            runtime=runtime,
            session=session,
            approval_resolver=child_approval_resolver,
            delegated_execution_profile=delegated_execution_profile,
            workspace_lease=workspace_lease,
            workspace_leases=self._workspace_leases,
        )


def _sandbox_workspace_is_writable(agent_type: str) -> bool:
    return agent_type in {
        "implementation_worker",
        "shared_implementation_worker",
        "test_runner",
    }


def install_coding_multiagent_session(
    session: AgentSession,
    *,
    child_factory: SessionSubagentFactory,
    agent_types: AgentTypeRegistry,
    register_tools: bool = False,
) -> SessionMultiAgentRuntime:
    """Bind one explicit Coding child factory to one live root session."""

    if getattr(session, "multiagent_runtime", None) is not None:
        raise RuntimeError("Coding multi-agent runtime is already installed")
    input_facade: AgentInputFacade[object] = AgentInputFacade(
        queue=session.runtime.queue.input_queue,
        build_payload=_coding_input_payload,
        submit_mailbox=_mailbox_submitter(session),
    )
    runtime = SessionMultiAgentRuntime(
        control=MultiAgentControl(agent_types=agent_types),
        child_factory=child_factory,
        root_input=input_facade,
        root_is_active=lambda: session.runtime.is_active,
        notice_wake_policy="queue_only",
    )
    session.multiagent_input = input_facade
    session.multiagent_runtime = runtime
    if register_tools:
        pack = MultiAgentToolPack(
            runtime=runtime,
            caller=AgentCaller(runtime.control.root_ref),
        )
        session.register_runtime_tools(
            pack.definitions(),
            activate=True,
            source_info={"pack": "harness.multiagent"},
        )
        session.multiagent_tool_pack = pack
    return runtime


class _CodingSubagentDriver:
    """Map one Coding child session to the shared round-driver contract."""

    def __init__(
        self,
        *,
        runtime: AgentSessionRuntime,
        session: AgentSession,
        approval_resolver: ActorBoundApprovalResolver | None = None,
        delegated_execution_profile: DelegatedExecutionProfile | None = None,
        workspace_lease: WorkspaceLease | None = None,
        workspace_leases: WorkspaceLeasePort | None = None,
    ) -> None:
        self._runtime = runtime
        self._session = session
        self.input_facade: AgentInputFacade[object] = AgentInputFacade(
            queue=session.runtime.queue.input_queue,
            build_payload=_coding_input_payload,
            submit_mailbox=_mailbox_submitter(session),
        )
        self._initial_message: AgentInputMessage | None = None
        self._rounds_started = 0
        self._approval_resolver = approval_resolver
        self.delegated_execution_profile = delegated_execution_profile
        self._workspace_lease = workspace_lease
        self._workspace_leases = workspace_leases
        self.released_workspace: WorkspaceLeaseSnapshot | None = None

    @property
    def workspace_ref(self) -> str | None:
        return (
            self._workspace_lease.workspace_ref
            if self._workspace_lease is not None
            else None
        )

    def deliver(self, message: AgentInputMessage) -> None:
        if self._rounds_started == 0 and self._initial_message is None:
            self._initial_message = message
            return
        self.input_facade.enqueue_message(message)

    async def run_round(
        self,
        *,
        round_id: int,
        mode: RoundMode,
    ) -> SubagentRoundResult:
        del round_id
        message_count = len(self._session.agent.state.messages)
        self._rounds_started += 1
        if mode == "prompt":
            initial = self._initial_message
            self._initial_message = None
            if initial is None:
                raise RuntimeError("Coding child has no staged initial prompt")
            await self._session.prompt(
                initial.text,
                source=f"multiagent:{initial.message_id}",
            )
        else:
            await self._session.continue_run()
        result = _round_result(
            tuple(self._session.agent.state.messages[message_count:])
        )
        if self._workspace_lease is None or self._workspace_leases is None:
            return result
        snapshot = await self._workspace_leases.snapshot(self._workspace_lease)
        return replace(
            result,
            workspace_ref=snapshot.workspace_ref,
            artifact_refs=snapshot.artifact_refs,
            change_set_ref=snapshot.change_set_ref,
        )

    def abort(self) -> None:
        self._session.abort()

    async def dispose(self) -> None:
        runtime_error: Exception | None = None
        if self._approval_resolver is not None:
            self._approval_resolver.end_session("Child agent closed")
        try:
            await self._runtime.dispose_session_runtime()
        except Exception as error:
            runtime_error = error
        if self._workspace_lease is not None and self._workspace_leases is not None:
            self.released_workspace = await self._workspace_leases.release(
                self._workspace_lease
            )
        if runtime_error is not None:
            raise runtime_error


def _resolve_system_prompt(request: SessionSubagentRequest) -> str:
    if request.context_plan is not None:
        return request.context_plan.system_prompt
    return _coding_role_system_prompt(request.agent_type.name)


def _coding_role_system_prompt(agent_type: str) -> str:
    role_prompt = _ROLE_PROMPTS.get(agent_type)
    if role_prompt is None:
        raise ValueError(f"Coding has no system prompt for agent type {agent_type!r}")
    return f"{DEFAULT_CODING_SYSTEM_PROMPT}\n\n{role_prompt}"


def _resolve_allowed_tools(request: SessionSubagentRequest) -> tuple[str, ...]:
    admitted = request.agent_type.allowed_tools
    if request.context_plan is None:
        return admitted
    requested = request.context_plan.allowed_tools
    unexpected = tuple(tool for tool in requested if tool not in admitted)
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(
            f"subagent context requested non-admitted Coding tools: {joined}"
        )
    return requested


def _select_tool_registry(
    source: WorkspaceToolRegistry,
    allowed_tools: tuple[str, ...],
) -> WorkspaceToolRegistry:
    enabled = {definition.name for definition in source.list_enabled_definitions()}
    missing = tuple(name for name in allowed_tools if name not in enabled)
    if missing:
        raise ValueError(
            "Coding child tools are not registered and enabled: " + ", ".join(missing)
        )
    selected = WorkspaceToolRegistry()
    for name in allowed_tools:
        selected.register_tool(
            source.get_definition(name),
            source_info=source.get_source_info(name),
        )
    return selected


def _coding_input_payload(message: AgentInputMessage) -> ApplicationMessage:
    sender = (
        str(message.sender.ref.path)
        if isinstance(message.sender, AgentCaller)
        else "host"
    )
    return ApplicationMessage(
        application_message_id=message.message_id,
        custom_type=(
            "harness.multiagent.completion_notice"
            if message.message_id.startswith("completion:")
            else "harness.multiagent.message"
        ),
        content=message.text,
        timestamp=0.0,
        display=False,
        details={
            "sender": sender,
            "recipient": str(message.recipient_ref.path),
            "references": list(message.references),
        },
        origin="harness.multiagent",
        delivery_mode=("next_turn" if message.kind == "mailbox" else message.kind),
    )


def _mailbox_submitter(session: AgentSession) -> Callable[[object], object]:
    queue = session.runtime.queue
    submit = getattr(queue, "queue_mailbox_message", None)
    if callable(submit):
        return cast(Callable[[object], object], submit)
    return queue.input_queue.append_next_turn


def _install_forked_history(
    session: AgentSession,
    request: SessionSubagentRequest,
) -> None:
    plan = request.context_plan
    if plan is None or not plan.history.messages:
        return
    messages: list[Message] = []
    for message in plan.history.messages:
        if not isinstance(message, _ALLOWED_HISTORY_TYPES):
            raise TypeError(
                "Coding subagent history must contain canonical Agent messages"
            )
        messages.append(message)
    session.agent.state.set_messages(messages)


def _round_result(messages: tuple[Message, ...]) -> SubagentRoundResult:
    assistant_messages = tuple(
        message for message in messages if isinstance(message, AssistantMessage)
    )
    if not assistant_messages:
        return SubagentRoundResult(
            status="failed",
            final_message="Coding child produced no assistant response.",
        )

    final = assistant_messages[-1]
    text = _assistant_text(final)
    if final.stop_reason == "aborted":
        status = "interrupted"
    elif final.error_message is not None or final.stop_reason == "error":
        status = "failed"
    else:
        status = "completed"
    final_message = final.error_message or text or "Coding child completed."
    return SubagentRoundResult(
        status=status,
        final_message=final_message,
        summary=_summary(final_message),
        latest_input_tokens=(
            int(final.usage.input or 0) + int(final.usage.cache_read or 0)
        ),
        output_tokens=sum(
            int(message.usage.output or 0) for message in assistant_messages
        ),
        tool_uses=sum(
            isinstance(part, ToolCall)
            for message in assistant_messages
            for part in message.content
        ),
    )


def _assistant_text(message: AssistantMessage) -> str:
    return "".join(
        part.text for part in message.content if isinstance(part, TextPart)
    ).strip()


def _summary(value: str, *, limit: int = 1000) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1]}…"


__all__ = [
    "CodingSubagentFactory",
    "coding_multiagent_system_prompt",
    "coding_recipe_context_plan",
    "coding_read_only_agent_types",
    "install_coding_multiagent_session",
]
