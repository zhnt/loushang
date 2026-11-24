"""Bind an authorized workspace and its prepared plugin assemblies."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.control.sandbox import (
    CodingExecutionAuthority,
    bind_coding_sandbox_runtime,
    coding_host_execution_profile,
    coding_workspace_execution_profile,
)
from loushang.coding.workspace.operations import CodingWorkspaceOperations
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.capabilities.workspace_provider import bind_workspace_execution
from loushang.harness.workspace.exec import ExecService

if TYPE_CHECKING:
    from collections.abc import Callable

    from loushang.harness.approval import InteractiveApprovalResolver
    from loushang.harness.authorization.execution_profile import (
        WorkspaceExecutionSelection,
    )
    from loushang.harness.capabilities.provider_binding import (
        CapabilityBundleProviderBinding,
    )
    from loushang.harness.multiagent import DelegatedExecutionProfile
    from loushang.harness.policy import PolicyEvaluator
    from loushang.harness.sandbox import SandboxExecutionRuntime
    from loushang.harness.session.bootstrap_services import BootstrapServices
    from loushang.harness.tools.process_hosting import ProcessAuditSink


def bind_session_workspace(
    services: BootstrapServices,
    get_cwd: Callable[[], str],
    *,
    session_id: str,
    writable_workspace: bool,
    delegated_execution_profile: DelegatedExecutionProfile | None,
    tool_policy_evaluator: PolicyEvaluator | None,
    approval_resolver: InteractiveApprovalResolver | None,
    audit_sink: ProcessAuditSink,
) -> tuple[SandboxExecutionRuntime, CapabilityBundleProviderBinding]:
    """Use one ceiling for sandbox operations, process launch and tool binding."""
    base_exec_service = services.exec_service or ExecService()
    workspace_root_path = Path(get_cwd()).resolve()
    workspace_execution_profile = (
        coding_workspace_execution_profile(
            workspace_root_path,
            writable=writable_workspace,
        )
        if workspace_root_path.is_dir()
        else EffectiveExecutionProfile(
            readable_roots=(workspace_root_path,),
            writable_roots=(workspace_root_path,)
            if writable_workspace
            else (),
            network="allowed",
        )
    )
    sandbox_settings = services.settings_manager.get_sandbox_settings()
    execution_ceiling = (
        workspace_execution_profile
        if sandbox_settings.requirement == "required"
        else coding_host_execution_profile(workspace_root_path, writable=writable_workspace)
    )
    def bind_sandbox(authority: WorkspaceExecutionSelection) -> SandboxExecutionRuntime:
        return bind_coding_sandbox_runtime(
            workspace_root=get_cwd(),
            writable_workspace=writable_workspace,
            settings=sandbox_settings,
            base_exec_service=base_exec_service,
            diagnostics_service=services.diagnostics_service,
            session_id=session_id,
            execution_profile=authority.ceiling,
            execution_profile_provider=authority,
        )

    return bind_workspace_execution(
        ceiling=execution_ceiling,
        requested_profiles=(
            getattr(base_exec_service, "execution_profile", None),
            delegated_execution_profile.execution_profile_ceiling
            if delegated_execution_profile is not None
            else None,
        ),
        authority_factory=lambda ceiling: CodingExecutionAuthority(
            workspace_root_path,
            workspace_execution_profile,
            ceiling,
            services.settings_manager.get_permission_profile_snapshot,
        ),
        bind_runtime=bind_sandbox,
        operations_factory=CodingWorkspaceOperations,
        policy_evaluator=tool_policy_evaluator,
        approval_resolver=approval_resolver,
        audit_sink=audit_sink,
        provider_id="coding.workspace.standard",
        source_id=CODING_PRODUCT_ID,
        fingerprint_namespace="coding.workspace.standard.v1",
        product_label="Coding",
    )
