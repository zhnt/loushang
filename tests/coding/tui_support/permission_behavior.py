from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loushang.coding.tool_pack import register_coding_builtin_tools
from loushang.harness.approval import (
    ActorBoundApprovalResolver,
    ApprovalDecision,
    ApprovalRequest,
)
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.config.agent import (
    ControlConfig,
    PermissionSettings,
    SettingsManager,
    ToolSettings,
)
from loushang.harness.permissions import (
    PermissionProfileCeiling,
    PermissionProfileId,
)
from loushang.harness.tools.workspace import (
    PolicyEnforcementError,
    ToolContext,
    workspace_tool_runtime_settings,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.exec import ExecRequest, ExecResult, ExecService


@dataclass(frozen=True, slots=True)
class PermissionBehaviorCase:
    name: str
    requested_profile: PermissionProfileId
    effective_profile: PermissionProfileId
    outcome: str
    policy_code: str | None
    capability: str
    actor_id: str
    approval_count: int
    event_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermissionBehaviorEvidence:
    cases: tuple[PermissionBehaviorCase, ...]
    audit_events: tuple[dict[str, object], ...]


class PermissionBehaviorHarness:
    """Run real Coding tools through the live Policy/Approval/Gateway path."""

    def __init__(
        self,
        workspace: Path,
        *,
        initial_profile: PermissionProfileId = "standard",
        ceiling: PermissionProfileCeiling | None = None,
        blocked_tools: tuple[str, ...] = (),
        actor_id: str = "root",
        execution_profile: EffectiveExecutionProfile | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "notes.txt").write_text("public notes\n", encoding="utf-8")
        (self.workspace / ".env").write_text(
            "PRIVATE_TOKEN=not-for-audit\n",
            encoding="utf-8",
        )
        self.settings = SettingsManager(
            ControlConfig(
                permissions=PermissionSettings(initial_profile),
                tools=ToolSettings(blocked_tools=blocked_tools),
            ),
            permission_profile_ceiling=ceiling,
        )
        self.approvals = _RecordingDenyResolver()
        approval_resolver: object = self.approvals
        if actor_id != "root":
            approval_resolver = ActorBoundApprovalResolver(
                resolver=self.approvals,
                actor_id=actor_id,
            )
        self.events: list[dict[str, object]] = []
        self.executions: list[ExecRequest] = []
        self.exec_service = ExecService(
            backend=self._execute,
            execution_profile=execution_profile,
        )
        runtime_settings = workspace_tool_runtime_settings(self.settings)
        from loushang.harness.tools.workspace.authorization import (
            create_workspace_tool_execution_host,
        )

        self.registry = WorkspaceToolRegistry(
            execution_host=create_workspace_tool_execution_host(
                policy_evaluator=runtime_settings.policy_engine,  # type: ignore[arg-type]
                approval_resolver=approval_resolver,  # type: ignore[arg-type]
            )
        )
        register_coding_builtin_tools(
            self.registry,
            exec_service=self.exec_service,
        )
        self._call_sequence = 0

    async def run(
        self,
        name: str,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        profile: PermissionProfileId | None = None,
    ) -> PermissionBehaviorCase:
        if profile is not None:
            self.settings.set_permission_profile(profile, scope="session")
        event_start = len(self.events)
        approval_start = len(self.approvals.requests)
        self._call_sequence += 1
        tool = self.registry.materialize_tool(
            tool_name,
            context_provider=lambda *, tool_call_id: ToolContext(
                tool_call_id=tool_call_id,
                cwd=str(self.workspace),
                event_sink=self.events.append,
                exec_service=self.exec_service,
            ),
        )
        outcome = "allowed"
        try:
            await tool.execute(
                f"permission-behavior-{self._call_sequence}",
                arguments,
            )
        except ExecutionAuthorizationError:
            outcome = "contained"
        except PolicyEnforcementError as error:
            disposition = error.tool_result_details.get("policy_disposition")
            outcome = "asked" if disposition == "ask" else "denied"

        events = tuple(self.events[event_start:])
        policy_event = next(
            event for event in events if event["type"] == "tool_policy_evaluated"
        )
        snapshot = self.settings.get_permission_profile_snapshot()
        return PermissionBehaviorCase(
            name=name,
            requested_profile=snapshot.requested_profile_id,
            effective_profile=snapshot.effective_profile.profile_id,
            outcome=outcome,
            policy_code=_optional_string(policy_event.get("policy_code")),
            capability=str(policy_event["capability"]),
            actor_id=str(policy_event["actor_id"]),
            approval_count=len(self.approvals.requests) - approval_start,
            event_types=tuple(str(event["type"]) for event in events),
        )

    async def _execute(
        self,
        request: ExecRequest,
        **_kwargs: object,
    ) -> ExecResult:
        self.executions.append(request)
        return ExecResult(exit_code=0, stdout="simulated execution\n")


class _RecordingDenyResolver:
    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision.deny("permission behavior playback denied the prompt")


async def run_permission_behavior_matrix(
    workspace: Path,
) -> PermissionBehaviorEvidence:
    harness = PermissionBehaviorHarness(workspace)
    cases: list[PermissionBehaviorCase] = []

    cases.append(
        await harness.run(
            "standard-read",
            tool_name="read",
            arguments={"path": "notes.txt"},
            profile="standard",
        )
    )
    cases.append(
        await harness.run(
            "standard-write",
            tool_name="write",
            arguments={"path": "standard.txt", "content": "allowed"},
        )
    )
    for name, command in (
        ("standard-test", "pytest -q"),
        ("standard-git-status", "git status --short"),
        ("standard-public-http-read", "curl https://example.com"),
        ("standard-unknown-harmless", "custom-inspector --summary"),
    ):
        cases.append(
            await harness.run(
                name,
                tool_name="bash",
                arguments={"command": command},
            )
        )

    for name, tool_name, arguments in _RISK_CASES:
        cases.append(
            await harness.run(
                f"standard-{name}",
                tool_name=tool_name,
                arguments=dict(arguments),
            )
        )

    cases.append(
        await harness.run(
            "cautious-write",
            tool_name="write",
            arguments={"path": "cautious.txt", "content": "requires approval"},
            profile="cautious",
        )
    )
    cases.append(
        await harness.run(
            "cautious-read",
            tool_name="read",
            arguments={"path": "notes.txt"},
        )
    )

    for name, tool_name, arguments in _RISK_CASES:
        cases.append(
            await harness.run(
                f"full-access-{name}",
                tool_name=tool_name,
                arguments=dict(arguments),
                profile="full_access" if name == "delete" else None,
            )
        )

    managed_deny = PermissionBehaviorHarness(
        workspace / "managed-deny",
        initial_profile="full_access",
        blocked_tools=("bash",),
    )
    cases.append(
        await managed_deny.run(
            "managed-deny",
            tool_name="bash",
            arguments={"command": "git status --short"},
        )
    )

    managed_ceiling = PermissionBehaviorHarness(
        workspace / "managed-ceiling",
        initial_profile="full_access",
        ceiling=PermissionProfileCeiling(
            maximum_profile="standard",
            reason="Managed session ceiling",
        ),
    )
    cases.append(
        await managed_ceiling.run(
            "managed-profile-ceiling",
            tool_name="bash",
            arguments={"command": "git push origin main"},
        )
    )

    delegated_workspace = workspace / "delegated"
    root = PermissionBehaviorHarness(
        delegated_workspace,
        initial_profile="full_access",
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(delegated_workspace,),
            writable_roots=(delegated_workspace,),
        ),
    )
    child = PermissionBehaviorHarness(
        delegated_workspace,
        initial_profile="full_access",
        actor_id="/root/reviewer@2",
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(delegated_workspace,),
            writable_roots=(),
        ),
    )
    cases.append(
        await root.run(
            "root-full-access-write",
            tool_name="write",
            arguments={"path": "root.txt", "content": "root"},
        )
    )
    cases.append(
        await child.run(
            "child-delegated-ceiling",
            tool_name="write",
            arguments={"path": "child.txt", "content": "child"},
        )
    )

    return PermissionBehaviorEvidence(
        cases=tuple(cases),
        audit_events=tuple(
            (
                *harness.events,
                *managed_deny.events,
                *managed_ceiling.events,
                *root.events,
                *child.events,
            )
        ),
    )


_RISK_CASES: tuple[tuple[str, str, dict[str, object]], ...] = (
    ("delete", "bash", {"command": "rm -rf ./build"}),
    ("publish", "bash", {"command": "git push origin main"}),
    ("privilege", "bash", {"command": "sudo true"}),
    ("secret", "read", {"path": ".env"}),
    (
        "external-effect",
        "bash",
        {"command": "curl -X POST https://example.com/resource"},
    ),
)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "PermissionBehaviorCase",
    "PermissionBehaviorEvidence",
    "PermissionBehaviorHarness",
    "run_permission_behavior_matrix",
]
