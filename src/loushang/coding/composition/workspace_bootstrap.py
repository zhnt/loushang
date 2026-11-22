"""Bind an authorized workspace and its prepared plugin assemblies."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
    from collections.abc import Callable, Mapping

    from loushang.coding.composition.base_plugin import (
        CodingBasePluginSessionAssembly,
        CodingBasePluginSessionPreparation,
    )
    from loushang.coding.composition.base_product import (
        CodingBaseProductCompilation,
        CodingBaseProductSessionAssembly,
    )
    from loushang.coding.composition.capability_plugins import (
        CodingCapabilityPluginCompositionAssembly,
        CodingCapabilityPluginCompositionPreparation,
    )
    from loushang.coding.composition.product_capability_plugins import (
        CodingBuiltinProductCompositionPreparation,
    )
    from loushang.harness.approval import InteractiveApprovalResolver
    from loushang.harness.capabilities.provider_binding import (
        CapabilityBundleProviderBinding,
    )
    from loushang.harness.config.agent import CapabilityMountMode
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
    provider_id: str,
    source_id: str,
    fingerprint_namespace: str,
    ceiling_type_error: str,
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
            raise TypeError(ceiling_type_error)
        execution_ceiling = constrain_execution_profile(
            execution_ceiling,
            requested_profile,
        )
    execution_authority = CodingExecutionAuthority(
        workspace_root=workspace_root_path,
        workspace_profile=workspace_execution_profile,
        ceiling=execution_ceiling,
        permission_snapshot=services.settings_manager.get_permission_profile_snapshot,
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
        provider_id=provider_id,
        source_id=source_id,
        fingerprint_namespace=fingerprint_namespace,
    )
    return sandbox_runtime, workspace_binding


def bind_workspace_plugins(
    workspace_binding: CapabilityBundleProviderBinding,
    *,
    builtin_product_preparation: CodingBuiltinProductCompositionPreparation | None,
    capability_preparation: CodingCapabilityPluginCompositionPreparation | None,
    base_plugin_session_preparation: CodingBasePluginSessionPreparation | None,
    product_base_compilation: CodingBaseProductCompilation | None,
    host_boot_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    clock: Callable[[], int],
) -> tuple[
    CodingCapabilityPluginCompositionAssembly | None,
    CodingBasePluginSessionAssembly | None,
    CodingBaseProductSessionAssembly | None,
]:
    """Bind admitted plugin preparations in their original custody order."""
    builtin_product_session = (
        builtin_product_preparation.bind_workspace(
            workspace_binding,
            host_boot_id=host_boot_id,
            tool_modes=tool_modes,
            clock=clock,
        )
        if builtin_product_preparation is not None
        else None
    )
    capability_plugin_assembly = (
        builtin_product_session.capability_assembly
        if builtin_product_session is not None
        else capability_preparation.bind_workspace(
            workspace_binding=workspace_binding,
            host_boot_id=host_boot_id,
            tool_modes=tool_modes,
            clock=clock,
        )
        if capability_preparation is not None
        else None
    )
    base_plugin_session_assembly = (
        base_plugin_session_preparation.bind_workspace(workspace_binding)
        if base_plugin_session_preparation is not None
        else None
    )
    product_base_session_assembly = (
        builtin_product_session.base_session
        if builtin_product_session is not None
        else product_base_compilation.bind_workspace(workspace_binding)
        if product_base_compilation is not None
        else None
    )
    return capability_plugin_assembly, base_plugin_session_assembly, product_base_session_assembly
