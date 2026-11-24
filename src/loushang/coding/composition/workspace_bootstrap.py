"""Bind an authorized workspace and its prepared plugin assemblies."""

from __future__ import annotations

from dataclasses import replace
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
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    constrain_execution_profile,
)
from loushang.harness.capabilities.workspace_provider import bind_authorized_workspace
from loushang.harness.tools.process_hosting import ProcessExecutionScope
from loushang.harness.workspace.exec import ExecService

if TYPE_CHECKING:
    from collections.abc import Callable

    from loushang.coding.hosted_workspace import CodingHostedWorkspace
    from loushang.harness.approval import InteractiveApprovalResolver
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
    hosted_workspace: CodingHostedWorkspace | None = None,
) -> tuple[SandboxExecutionRuntime, CapabilityBundleProviderBinding]:
    """Use one ceiling for sandbox operations, process launch and tool binding."""
    base_exec_service = services.exec_service or ExecService()
    workspace_root_path = Path(get_cwd()).resolve()
    sandbox_settings = services.settings_manager.get_sandbox_settings()
    if hosted_workspace is not None:
        workspace_execution_profile = EffectiveExecutionProfile(
            readable_roots=hosted_workspace.roots,
            writable_roots=hosted_workspace.roots if writable_workspace else (),
            denied_roots=hosted_workspace.private_roots,
        )
        execution_ceiling = workspace_execution_profile
        if hosted_workspace.roots:
            # A shell's cwd alone cannot enforce the attached directory boundary.
            sandbox_settings = replace(sandbox_settings, enabled=True, requirement="required")
    else:
        workspace_execution_profile = (
            coding_workspace_execution_profile(workspace_root_path, writable=writable_workspace)
            if workspace_root_path.is_dir()
            else EffectiveExecutionProfile(
                readable_roots=(workspace_root_path,),
                writable_roots=(workspace_root_path,) if writable_workspace else (),
            )
        )
        execution_ceiling = (
            workspace_execution_profile if sandbox_settings.requirement == "required"
            else coding_host_execution_profile(workspace_root_path, writable=writable_workspace)
        )
    requested_profiles = (
        getattr(base_exec_service, "execution_profile", None),
        (
            delegated_execution_profile.execution_profile_ceiling
            if delegated_execution_profile is not None
            else None
        ),
    )
    for requested_profile in requested_profiles:
        if requested_profile is None:
            continue
        if not isinstance(requested_profile, EffectiveExecutionProfile):
            raise TypeError(
                "Coding workspace execution ceiling must be an EffectiveExecutionProfile"
            )
        execution_ceiling = constrain_execution_profile(
            execution_ceiling,
            requested_profile,
        )
    execution_authority = CodingExecutionAuthority(
        workspace_root=workspace_root_path,
        workspace_profile=workspace_execution_profile,
        ceiling=execution_ceiling,
        permission_snapshot=services.settings_manager.get_permission_profile_snapshot,
        current_workspace_roots=hosted_workspace.current_roots if hosted_workspace is not None else None,
    )
    sandbox_runtime = bind_coding_sandbox_runtime(
        workspace_root=get_cwd(),
        writable_workspace=writable_workspace,
        settings=sandbox_settings,
        base_exec_service=base_exec_service,
        diagnostics_service=services.diagnostics_service,
        session_id=session_id,
        execution_profile=execution_ceiling,
        execution_profile_provider=execution_authority,
    )
    workspace_binding = bind_authorized_workspace(
        sandbox_runtime,
        process_scope=ProcessExecutionScope(
            policy_evaluator=tool_policy_evaluator,
            approval_resolver=approval_resolver,
            audit_sink=audit_sink,
            execution_profile_ceiling=execution_ceiling,
            execution_profile_provider=execution_authority,
        ),
        operations_factory=CodingWorkspaceOperations,
        provider_id="coding.workspace.standard",
        source_id=CODING_PRODUCT_ID,
        fingerprint_namespace="coding.workspace.standard.v1",
    )
    return sandbox_runtime, workspace_binding
