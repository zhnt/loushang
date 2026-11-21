"""Prepare the delegated inputs for the existing child Session factory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.ai.model import Model, ModelSelection, parse_model_selection_reference
from loushang.harness.approval import ActorBoundApprovalResolver
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.environment import HostEnvironment
from loushang.harness.multiagent import DelegatedExecutionProfile, WorkspaceLease
from loushang.harness.session.multiagent import SessionSubagentRequest
from loushang.harness.session.subagent import ChildSessionRuntime
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

from .tool_selection import peer_tool_names, platform_tool_names

if TYPE_CHECKING:
    from loushang.harness.session import BootstrapServices


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
