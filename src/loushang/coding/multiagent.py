"""Coding adapters for the Product-neutral multi-agent session runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from loushang.ai.model import Model, ModelSelection, parse_model_selection_reference
from loushang.ai.types import Message
from loushang.coding._tool_authority import (
    CODING_EXACT_OWNER_TOOL_NAMES,
    coding_peer_tool_names,
)
from loushang.coding.prompt.defaults import CODING_KERNEL_SYSTEM_PROMPT
from loushang.coding.runtime import AgentSessionRuntime
from loushang.coding.sandbox import coding_workspace_execution_profile
from loushang.coding.session import AgentSession
from loushang.coding.tool_pack import coding_platform_tool_names
from loushang.harness.approval import (
    ActorBoundApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.multiagent import (
    AgentTypeRegistry,
    AgentTypeSpec,
    DelegatedExecutionProfile,
    ForkedHistory,
    ForkTier,
    SubagentContextPlan,
    WorkspaceLease,
    WorkspaceLeasePort,
)
from loushang.harness.session import BootstrapServices
from loushang.harness.session.multiagent import (
    SessionMultiAgentRuntime,
    SessionSubagentBinding,
    SessionSubagentFactory,
    SessionSubagentRequest,
    bind_agent_session_multiagent,
)
from loushang.harness.session.subagent import AgentSessionSubagentFactory
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

_RuntimeBuilder = Callable[..., AgentSessionRuntime]
_DefaultModelProvider = Callable[[], Model | ModelSelection | None]

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
    maximum_children: int = 4,
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
    maximum_children: int = 4,
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
    *,
    host_environment: HostEnvironment | None = None,
) -> str:
    """Describe the admitted Coding collaboration surface to the root model."""

    resolved_host_environment = host_environment or LocalHostEnvironmentProbe().detect()

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
        "tools: "
        f"{', '.join(coding_platform_tool_names(spec.allowed_tools, resolved_host_environment)) or 'none'}; "
        f"maximum open children: {spec.maximum_children}"
        for spec in agent_types.values()
    )
    return (
        "## Multi-agent collaboration\n\n"
        "You may delegate focused work to session-owned child agents with "
        "`spawn_agent`. Spawning is asynchronous: use `wait_agent` to wait for "
        "new collaboration activity, `get_agent_result` to read a truncated "
        "child report using the exact path, incarnation, and round_id from its "
        "completion notice, `list_agents` to inspect the visible tree, "
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
        host_environment: HostEnvironment | None = None,
        selected_exact_tool_names: tuple[str, ...],
    ) -> None:
        resolved_cwd = Path(cwd).expanduser().resolve()
        if not resolved_cwd.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(resolved_cwd))
        self._session_dir = Path(session_dir)
        self._tool_registry = tool_registry
        self._default_model_provider = default_model_provider or (lambda: default_model)
        self._services = services
        self._runtime_builder = runtime_builder
        self._host_environment = (
            host_environment or LocalHostEnvironmentProbe().detect()
        )
        selected_exact_names = tuple(selected_exact_tool_names)
        if len(set(selected_exact_names)) != len(selected_exact_names):
            raise ValueError("selected exact Tool names must not contain duplicates")
        unknown_exact_names = tuple(
            name
            for name in selected_exact_names
            if name not in CODING_EXACT_OWNER_TOOL_NAMES
        )
        if unknown_exact_names:
            raise ValueError(
                "selected exact Tool names are not Coding exact-owner identities: "
                + ", ".join(unknown_exact_names)
            )
        self._selected_exact_tool_names = frozenset(selected_exact_names)
        self._children = AgentSessionSubagentFactory(
            cwd=resolved_cwd,
            runtime_builder=self._build_child_runtime,
            approval_resolver=approval_resolver,
            workspace_leases=workspace_leases,
            missing_response="Coding child produced no assistant response.",
            completed_response="Coding child completed.",
        )

    async def create(self, request: SessionSubagentRequest) -> SessionSubagentBinding:
        return await self._children.create(request)

    def _build_child_runtime(
        self,
        request: SessionSubagentRequest,
        cwd: Path,
        approval_resolver: ActorBoundApprovalResolver,
        workspace_lease: WorkspaceLease | None,
    ) -> AgentSessionRuntime:
        plan = request.context_plan
        allowed_tools = coding_platform_tool_names(
            _resolve_allowed_tools(request),
            self._host_environment,
        )
        unavailable_exact_tools = tuple(
            name
            for name in allowed_tools
            if name in CODING_EXACT_OWNER_TOOL_NAMES
            and name not in self._selected_exact_tool_names
        )
        if unavailable_exact_tools:
            raise ValueError(
                "Coding child exact-owner tools are not selected: "
                + ", ".join(unavailable_exact_tools)
            )
        model_ref = plan.model if plan is not None else None
        if model_ref is None:
            model_ref = request.agent_type.default_model
        selection_registry = getattr(
            getattr(self._services, "model_registry", None),
            "ai_registry",
            None,
        )
        model: Model | ModelSelection | None = (
            parse_model_selection_reference(
                model_ref,
                registry=selection_registry,
            )
            if model_ref is not None
            else self._default_model_provider()
        )
        delegated_execution_profile = DelegatedExecutionProfile(
            actor_ref=request.record.ref,
            allowed_tools=allowed_tools,
            execution_profile_ceiling=coding_workspace_execution_profile(
                cwd,
                writable=_sandbox_workspace_is_writable(request.agent_type.name),
            ),
            approval_actor_id=str(request.record.ref),
            workspace_ref=(
                workspace_lease.workspace_ref if workspace_lease is not None else None
            ),
        )
        return self._runtime_builder(
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
            approval_resolver=cast(Any, approval_resolver),
            delegated_execution_profile=delegated_execution_profile,
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
    return bind_agent_session_multiagent(
        session,
        child_factory=child_factory,
        agent_types=agent_types,
        agent_type_hints={
            "explorer": "read-only investigation",
            "reviewer": "review",
            "implementation_worker": "implementation in an isolated worktree",
        },
        register_tools=register_tools,
    )


def _resolve_system_prompt(request: SessionSubagentRequest) -> str:
    if request.context_plan is not None:
        return request.context_plan.system_prompt
    return _coding_role_system_prompt(request.agent_type.name)


def coding_agent_type_system_prompt(agent_type: str) -> str:
    """Return Coding's complete system prompt for one admitted agent type."""

    role_prompt = _ROLE_PROMPTS.get(agent_type)
    if role_prompt is None:
        raise ValueError(f"Coding has no system prompt for agent type {agent_type!r}")
    return f"{CODING_KERNEL_SYSTEM_PROMPT}\n\n{role_prompt}"


def _coding_role_system_prompt(agent_type: str) -> str:
    return coding_agent_type_system_prompt(agent_type)


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
    peer_tool_names = coding_peer_tool_names(allowed_tools)
    enabled = {definition.name for definition in source.list_enabled_definitions()}
    missing = tuple(name for name in peer_tool_names if name not in enabled)
    if missing:
        raise ValueError(
            "Coding child tools are not registered and enabled: " + ", ".join(missing)
        )
    return source.select(peer_tool_names)


__all__ = [
    "CodingSubagentFactory",
    "coding_agent_type_system_prompt",
    "coding_multiagent_system_prompt",
    "coding_recipe_context_plan",
    "coding_read_only_agent_types",
    "install_coding_multiagent_session",
]
