from __future__ import annotations

import asyncio
import hashlib
import secrets
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from functools import partial
from inspect import iscoroutine, iscoroutinefunction
from pathlib import Path
from typing import Any, Literal, cast

from loushang.agent import Agent, StreamFn, ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.coding.arch._provider_api import (
    CodingArchPluginConfigV1,
)
from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssembly,
    prepare_managed_coding_base_plugin_assembly,
)
from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssemblyError as CodingBasePluginAssemblyError,
)
from loushang.coding.composition.base_product import (
    CodingBaseProductCompilation,
    compile_coding_base_product_selection,
)
from loushang.coding.composition.capabilities import (
    CODING_ARCH_CAPABILITY,
    CODING_LSP_CAPABILITY,
    coding_capability_mount_mode,
    coding_lsp_should_defer,
)
from loushang.coding.composition.capability_plugins import (
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionError,
    CodingCapabilityPluginCompositionPreparation,
    CodingResumePluginParents,
    coding_capability_plugin_failure_custodian,
    create_coding_capability_plugin_composition_request,
)
from loushang.coding.composition.capability_plugins import (
    prepare_coding_capability_plugin_composition as prepare_coding_capability_plugin_composition,
)
from loushang.coding.composition.invocation_profile import (
    CODING_READ_ONLY_AGENT_INVOCATION_PRODUCT_PROFILE,
    CodingAgentInvocationProductProfile,
    canonical_coding_agent_invocation_product_profile,
)
from loushang.coding.composition.managed_plugin_preparation import (
    _session_manager_plugin_owner_id,
    bind_deferred_plugin,
    prepare_managed_plugins,
)
from loushang.coding.composition.package_catalog import (
    InitialCatalogHandoff,
    prepare_coding_catalog_projection,
)
from loushang.coding.composition.plan import (
    CODING_CAPABILITY_PROFILE,
    CODING_PRODUCT_ID,
)
from loushang.coding.composition.product_capability_plugins import (
    CodingBuiltinProductCompositionPreparation as CodingBuiltinProductCompositionPreparation,
)
from loushang.coding.composition.product_capability_plugins import (
    coding_session_plugin_state_relative_path,
)
from loushang.coding.composition.product_capability_plugins import (
    prepare_coding_product_capability_plugin_composition as prepare_coding_product_capability_plugin_composition,
)
from loushang.coding.composition.provenance import (
    composition_header_metadata,
    historical_composition_provenance,
    historical_startup_composition_record,
)
from loushang.coding.composition.runtime_admission import (
    bind_coding_side_question,
    resolve_coding_capability_profile,
)
from loushang.coding.composition.sets import (
    CODING_KERNEL_PROMPT_REVISION,
    CodingCompositionSetId,
    CodingCompositionSetPlan,
    infer_coding_composition_set,
    resolve_coding_composition_set,
)
from loushang.coding.composition.workspace_bootstrap import (
    bind_session_workspace,
    bind_workspace_plugins,
)
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.diagnostics.profile import coding_runtime_identity
from loushang.coding.lsp._deferred_generation import CodingDeferredLspGeneration
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CodingLspPluginConfigV1,
)
from loushang.coding.lsp.discovery import (
    coding_lsp_config_paths,
    default_lsp_environment,
    discover_lsp_catalog,
)
from loushang.coding.lsp.model import LspServerDefinition
from loushang.coding.lsp.ports import WorkspaceTextReader
from loushang.coding.package.installation_private_data import (
    prepare_coding_product_arch_private_data_root,
)
from loushang.coding.package.product_runtime import (
    CodingApplicationWorkerProductRuntimeFactory,
    CodingFencedProductApplicationSelection,
    CodingSessionOwnedProductRuntimeFactory,
    bind_coding_product_workspace_witness,
)
from loushang.coding.package.product_worker_ordinary_error import (
    CodingWorkerOrdinaryBootstrapError,
)
from loushang.coding.plugin_manager.enablement_compatibility import (
    bind_coding_plugin_enablement_compatibility,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.plugin_manager.lifecycle import (
    build_coding_plugin_lifecycle as build_coding_plugin_lifecycle,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout as resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.prompt.defaults import (
    CODING_KERNEL_SYSTEM_PROMPT,
    DEFAULT_CODING_SYSTEM_PROMPT,
)
from loushang.coding.resources.catalog import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
    CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
    CodingResourceCatalogAdmissionError,
    CodingResourceCatalogSourcePolicy,
    canonical_coding_resource_catalog_source_policy,
)
from loushang.coding.resources.runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resources.runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.resources.tool_authority import (
    CODING_ARCH_EXACT_OWNER_TOOL_NAMES,
    CODING_EXACT_OWNER_TOOL_NAMES,
    CODING_LSP_EXACT_OWNER_TOOL_NAMES,
)
from loushang.coding.resources.tool_pack import coding_default_active_tool_names
from loushang.coding.resume._cleanup import discard_candidate
from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
from loushang.coding.runtime import AgentSessionRuntime
from loushang.coding.session import AgentSession
from loushang.coding.session.manager import SessionManager
from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.approval import (
    InteractiveApprovalResolver,
    approval_actor_id,
)
from loushang.harness.bootstrap import (
    create_standard_resource_bootstrap_runtime,
)
from loushang.harness.capabilities import (
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
)
from loushang.harness.capabilities.deferred_slot import (
    DeferredCapabilityDeclaration,
    DeferredCapabilitySlot,
)
from loushang.harness.capabilities.tools import ToolSelection
from loushang.harness.config.agent import SettingsManager
from loushang.harness.diagnostics.types import StartupCheckResult
from loushang.harness.environment import LocalHostEnvironmentProbe
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import SessionStartEvent
from loushang.harness.multiagent import DelegatedExecutionProfile
from loushang.harness.package_product._selected_plugin_revisions import (
    capture_selected_manifests,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductRuntimeFactory,
    WindowsLocalWheelProductRuntimeFactory,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeFactoryPort,
    dispose_unbound_factory_after_failure,
)
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.catalog_diagnostics import (
    record_package_lockfile_diagnostics,
)
from loushang.harness.resources.packages.materializer import (
    GitPackageMaterializerBackend,
    resolve_session_package_install_root,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleInventoryPort,
    PackageProductLifecycleMode,
    PackageProductLifecycleOperationPort,
)
from loushang.harness.resources.packages.roots import SelectedPluginPackageInput
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.session import (
    AgentProductConstructionBinding,
    AgentSessionServices,
    BootstrapServices,
    CreateAgentSessionResult,
    CwdBoundServicesAudit,
    build_agent_product_session_runtime,
    build_standard_agent_session_result,
    create_standard_agent_bootstrap_services,
    normalize_no_tools,
    project_root_from_settings_base,
    record_default_model_unavailable,
)
from loushang.harness.session import (
    CwdBoundServicesAuditIssue as _CwdBoundServicesAuditIssue,
)
from loushang.harness.session import (
    audit_cwd_bound_services as _audit_cwd_bound_services,
)
from loushang.harness.session import (
    prepare_agent_session_services as prepare_standard_agent_session_services,
)
from loushang.harness.session._cleanup import (
    ExplicitTemporaryDirectory as _ExplicitTemporaryDirectory,
)
from loushang.harness.session._cleanup import (
    get_session_construction_cleanup as get_session_construction_cleanup,
)
from loushang.harness.session._cleanup import (
    retain_session_construction_failure,
    run_cleanup_steps,
)
from loushang.harness.session.bootstrap_construction import (
    PreparationRootCustody,
    construct_catalog_session,
)
from loushang.harness.session.legacy_side_question import LegacySideQuestionBinding
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductPluginPlanSeed,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.tools.workspace.selection import initial_tool_names
from loushang.harness.transcript import context_items_to_model_messages
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

AgentFactory = Callable[..., Agent]
ServicesFactory = Callable[[str], "BootstrapServices"]
NoToolsMode = Literal["all", "builtin"]
_RESERVED_CODING_EXACT_TOOL_NAMES = frozenset(CODING_EXACT_OWNER_TOOL_NAMES)
_CATALOG_MANIFEST_MAX_FILES = 64
_CATALOG_MANIFEST_MAX_BYTES = 1024 * 1024


def _reject_peer_coding_exact_tools(
    *,
    tool_registry: WorkspaceToolRegistry | None,
    tools: Iterable[object] | None,
) -> None:
    """Keep reserved Tool identities under their exact Plugin owners."""

    supplied_names = {
        definition.name
        for definition in (
            tool_registry.list_definitions() if tool_registry is not None else ()
        )
    }
    supplied_names.update(
        name
        for definition in tools or ()
        if isinstance((name := getattr(definition, "name", None)), str)
    )
    if supplied_names.intersection(_RESERVED_CODING_EXACT_TOOL_NAMES):
        raise CodingResourceCatalogAdmissionError(("peer_exact_tool_publisher",))


ExtensionFlagValues = Mapping[str, bool | str]
CwdBoundServicesAuditIssue = _CwdBoundServicesAuditIssue
_CODING_PLUGIN_HOST_BOOT_ID = secrets.token_hex(16)


def create_services(
    *,
    ai_model_registry: AiModelRegistry | None = None,
    resource_loader: DefaultResourceLoader | None = None,
    settings_manager: SettingsManager | None = None,
    exec_service: ExecService | None = None,
    default_model: ModelSelection | None = None,
    thinking_level: ThinkingLevel | None = None,
    system_prompt: str = "",
) -> BootstrapServices:
    return create_standard_agent_bootstrap_services(
        resource_loader_factory=DefaultResourceLoader,
        ai_model_registry=ai_model_registry,
        resource_loader=resource_loader,
        settings_manager=settings_manager,
        exec_service=exec_service,
        default_model=default_model,
        thinking_level=thinking_level,
        system_prompt=system_prompt,
    )


def _create_agent_session_services(
    *,
    cwd: str | Path,
    services: BootstrapServices | None = None,
    ai_model_registry: AiModelRegistry | None = None,
    resource_loader: DefaultResourceLoader | None = None,
    settings_manager: SettingsManager | None = None,
    exec_service: ExecService | None = None,
    default_model: ModelSelection | None = None,
    thinking_level: ThinkingLevel | None = None,
    system_prompt: str = "",
    global_settings_path: str | Path | None = None,
    project_settings_path: str | Path | None = None,
    resource_loader_options: dict[str, object] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
) -> AgentSessionServices:
    resolved_source_policy = canonical_coding_resource_catalog_source_policy(
        resource_catalog_source_policy
    )

    def prepare_catalog_preview(
        loader: DefaultResourceLoader,
        resolved_cwd: Path,
    ) -> ResourceBundle:
        if not any(
            (
                resolved_source_policy.include_native_resources,
                resolved_source_policy.include_package_resources,
                resolved_source_policy.include_embedded_resources,
            )
        ):
            # This compatibility preview exists only to collect Extension
            # flags before the Product Session is constructed.  A Product
            # profile that admits no Resource sources must not import an
            # excluded Extension merely to discover those flags.
            return ResourceBundle(cwd=resolved_cwd)
        preview_id = hashlib.sha256(str(resolved_cwd).encode("utf-8")).hexdigest()
        _, bundle = prepare_coding_catalog_projection(
            loader,
            cwd=resolved_cwd,
            session_id=f"services-preview:{preview_id}",
            source_policy=resolved_source_policy,
        )
        return bundle

    def create_cwd_services(resolved_cwd: Path) -> BootstrapServices:
        resolved_settings_manager = settings_manager or SettingsManager(
            global_settings_path=Path(global_settings_path)
            if global_settings_path is not None
            else default_global_settings_path(),
            project_settings_path=Path(project_settings_path)
            if project_settings_path is not None
            else default_project_settings_path(resolved_cwd),
        )
        return create_services(
            ai_model_registry=ai_model_registry,
            resource_loader=resource_loader,
            settings_manager=resolved_settings_manager,
            exec_service=exec_service,
            default_model=default_model,
            thinking_level=thinking_level,
            system_prompt=system_prompt,
        )

    return prepare_standard_agent_session_services(
        cwd=cwd,
        services=services,
        create_services=create_cwd_services,
        service_overrides={
            "ai_model_registry": ai_model_registry,
            "resource_loader": resource_loader,
            "settings_manager": settings_manager,
            "exec_service": exec_service,
            "default_model": default_model,
        },
        build_resource_bootstrap=lambda resolved_services: (
            create_standard_resource_bootstrap_runtime(
                create_extension_runtime=lambda bundle: ExtensionRunner(
                    bundle.extensions
                ),
                diagnostics_service=resolved_services.diagnostics_service,
            )
        ),
        get_resource_loader=lambda resolved_services: resolved_services.resource_loader,
        resource_loader_options=resource_loader_options,
        configure_resource_loader=lambda loader, options: loader.set_runtime_options(
            **dict(options)
        ),
        prepare_catalog_projection=prepare_catalog_preview,
        extension_flag_values=extension_flag_values,
    )


def create_agent_session_services(
    *,
    cwd: str | Path,
    services: BootstrapServices | None = None,
    ai_model_registry: AiModelRegistry | None = None,
    resource_loader: DefaultResourceLoader | None = None,
    settings_manager: SettingsManager | None = None,
    exec_service: ExecService | None = None,
    default_model: ModelSelection | None = None,
    thinking_level: ThinkingLevel | None = None,
    system_prompt: str = "",
    global_settings_path: str | Path | None = None,
    project_settings_path: str | Path | None = None,
    resource_loader_options: dict[str, object] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
) -> AgentSessionServices:
    """Prepare standard cwd-bound services through the stable Coding SDK."""

    return _create_agent_session_services(
        cwd=cwd,
        services=services,
        ai_model_registry=ai_model_registry,
        resource_loader=resource_loader,
        settings_manager=settings_manager,
        exec_service=exec_service,
        default_model=default_model,
        thinking_level=thinking_level,
        system_prompt=system_prompt,
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
        resource_loader_options=resource_loader_options,
        extension_flag_values=extension_flag_values,
        resource_catalog_source_policy=(CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY),
    )


def audit_cwd_bound_services(
    *,
    session_manager: SessionManager,
    services: BootstrapServices,
    resource_bundle: ResourceBundle | None = None,
) -> CwdBoundServicesAudit:
    return _audit_cwd_bound_services(
        session_cwd=session_manager.get_cwd(),
        project_root=project_root_from_settings_base(
            services.settings_manager.project_base_dir
        ),
        resource_cwd=resource_bundle.cwd if resource_bundle is not None else None,
    )


def _canonical_coding_composition_set(
    plan: CodingCompositionSetPlan | None,
) -> CodingCompositionSetPlan:
    if plan is None:
        return resolve_coding_composition_set()
    if not isinstance(plan, CodingCompositionSetPlan):
        raise TypeError("Coding Session composition set is invalid")
    canonical = resolve_coding_composition_set(plan.set_id)
    if plan != canonical or plan.fingerprint != canonical.fingerprint:
        raise ValueError("Coding Session composition set must be a canonical plan")
    return canonical


def _resolve_coding_kernel_prompt(plan: CodingCompositionSetPlan) -> str:
    if plan.kernel_prompt_revision != CODING_KERNEL_PROMPT_REVISION:
        raise ValueError("Unsupported Coding Kernel Prompt revision")
    return CODING_KERNEL_SYSTEM_PROMPT


class CodingPackageProductLegacyPathError(RuntimeError):
    """Reject a Product runtime before any peer Plugin Package preparation."""

    code = "coding_package_product_legacy_plugin_path"


@dataclass(frozen=True, slots=True)
class _CodingResumeBootstrapAdmission:
    manager: SessionManager
    attempt_id: str
    composition: CodingCompositionSetPlan
    current_admission: Callable[[CodingActivationAttemptV1], None]

    def require(
        self, manager: SessionManager, composition: CodingCompositionSetPlan,
    ) -> CodingCompositionSetPlan:
        if manager is not self.manager or composition != self.composition:
            raise ValueError("Coding Resume bootstrap admission belongs to another candidate")
        with manager._lifecycle_session.sync_operation_scope():
            attempt = manager._require_resume_bootstrap_composition(self.attempt_id, composition)
            if not callable(self.current_admission) or iscoroutinefunction(self.current_admission):
                raise TypeError("Coding Resume bootstrap admission must be synchronous")
            result = cast(Callable[[CodingActivationAttemptV1], object], self.current_admission)(attempt)
            if result is not None:
                if iscoroutine(result):
                    result.close()
                raise TypeError("Coding Resume bootstrap admission must return None")
        return composition


def _create_agent_session(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    services: BootstrapServices | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    package_product_runtime_factory: PackageProductRuntimeFactoryPort | None = None,
    worker_candidate_plugin_id: str | None = None,
    worker_query_turn_tool: bool = False,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    sandbox_workspace_writable: bool = True,
    delegated_execution_profile: DelegatedExecutionProfile | None = None,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
    initial_resource_catalog_product_composition_assembly: (
        ProductCompositionAssemblyRequest | None
    ) = None,
    composition_set: CodingCompositionSetPlan | None = None,
    composition_set_explicit: bool = False,
    composition_choice_from_cli: bool = False,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    invocation_product_profile: CodingAgentInvocationProductProfile | None = None,
    use_default_model: bool = True,
    _resume_bootstrap_admission: _CodingResumeBootstrapAdmission | None = None,
    _resume_plugin_parents: CodingResumePluginParents | None = None,
    _resume_worker_parent: ResumeEffectParentContextV1 | None = None,
    _resume_effect_owner_ids: frozenset[str] | None = None,
) -> AgentSession:
    if _resume_bootstrap_admission is None:
        session_manager.require_no_unsettled_resume_activation()
    elif type(_resume_bootstrap_admission) is not _CodingResumeBootstrapAdmission:
        raise TypeError("Coding Resume bootstrap requires its current admission context")
    if _resume_plugin_parents is not None and (
        type(_resume_plugin_parents) is not CodingResumePluginParents
        or _resume_bootstrap_admission is None
    ):
        raise TypeError("Coding Resume Plugin parents require current Resume admission")
    if _resume_worker_parent is not None and (
        type(_resume_worker_parent) is not ResumeEffectParentContextV1
        or _resume_worker_parent.owner_id != "harness.worker-activation"
        or _resume_bootstrap_admission is None
        or worker_candidate_plugin_id is None
    ):
        raise TypeError("Coding Resume Worker parent requires one selected Worker")
    if _resume_effect_owner_ids is not None and (
        type(_resume_effect_owner_ids) is not frozenset
        or any(type(item) is not str for item in _resume_effect_owner_ids)
        or _resume_bootstrap_admission is None
    ):
        raise TypeError("Coding Resume effect owners require current Resume admission")
    if (
        initial_resource_catalog_product_composition_assembly is not None
        and not isinstance(
            initial_resource_catalog_product_composition_assembly,
            ProductCompositionAssemblyRequest,
        )
    ):
        raise TypeError(
            "initial Resource Catalog Product composition assembly is invalid"
        )
    resource_catalog_source_policy = canonical_coding_resource_catalog_source_policy(
        resource_catalog_source_policy
    )
    session_no_tools_mode = normalize_no_tools(no_tools)
    requested_composition_set = _canonical_coding_composition_set(composition_set)
    historical_composition = historical_composition_provenance(
        session_manager.get_header().metadata
    )
    if historical_composition is not None and not composition_set_explicit:
        requested_composition_set = resolve_coding_composition_set(
            historical_composition.set_id
        )
    if _resume_bootstrap_admission is not None:
        _resume_bootstrap_admission.require(session_manager, requested_composition_set)
    services = services or create_services()
    if (
        composition_choice_from_cli
        and not composition_set_explicit
        and (
            infer_coding_composition_set(
                services.settings_manager.get_settings().capabilities
            )
            != requested_composition_set.set_id
        )
    ):
        raise ValueError(
            "Coding composition settings changed before Session startup; "
            "retry with the current settings"
        )
    resolved_composition_set = (
        session_manager.bind_new_composition_plan(requested_composition_set)
        if _resume_bootstrap_admission is None
        else _resume_bootstrap_admission.require(session_manager, requested_composition_set)
    )
    if (
        composition_set_explicit
        and resolved_composition_set.set_id != requested_composition_set.set_id
    ):
        raise ValueError(
            "Coding Session composition set is pinned to "
            f"{resolved_composition_set.set_id}; requested "
            f"{requested_composition_set.set_id}. Create a new Session to switch sets"
        )
    resolved_invocation_profile = (
        canonical_coding_agent_invocation_product_profile(invocation_product_profile)
        if invocation_product_profile is not None
        else None
    )
    if resolved_invocation_profile is not None:
        if (
            resolved_composition_set.set_id
            != resolved_invocation_profile.composition_set_id
        ):
            raise ValueError(
                "Coding agent invocation profile composition set is inconsistent"
            )
        if (
            resource_catalog_source_policy
            != resolved_invocation_profile.resource_catalog_source_policy
        ):
            raise ValueError(
                "Coding agent invocation profile Resource policy is inconsistent"
            )
        if (
            sandbox_workspace_writable
            != resolved_invocation_profile.sandbox_workspace_writable
        ):
            raise ValueError(
                "Coding agent invocation profile sandbox policy is inconsistent"
            )
    if (
        resource_catalog_source_policy != CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
        and initial_resource_catalog_product_composition_assembly is not None
    ):
        raise ValueError(
            "Custom Product composition requires the standard Resource policy"
        )
    coding_kernel_prompt = _resolve_coding_kernel_prompt(resolved_composition_set)
    session_host_environment = LocalHostEnvironmentProbe().detect()
    requested_plugin_ids = {
        item.plugin_id for item in resolved_composition_set.plugin_requests
    }
    if (
        package_product_runtime_factory is not None
        and resolved_composition_set.set_id == "coding-minimal"
        and resource_catalog_source_policy
        == CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ):
        # The minimal composition requests no package plugins. Its default
        # policy must not imply a second, legacy package resource route.
        resource_catalog_source_policy = (
            CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
        )
    product_base_requested = (
        package_product_runtime_factory is not None
        and "coding.base" in requested_plugin_ids
    )
    if worker_candidate_plugin_id is not None and (
        sys.platform not in {"linux", "win32"}
        or not isinstance(worker_candidate_plugin_id, str)
        or not worker_candidate_plugin_id
        or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
        or not product_base_requested
        or not isinstance(
            package_product_runtime_factory,
            (
                CodingSessionOwnedProductRuntimeFactory,
                CodingApplicationWorkerProductRuntimeFactory,
            ),
        )
        or not session_manager.is_persisted()
    ):
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_explicit_selection_unavailable"
        )
    if worker_query_turn_tool and (
        worker_candidate_plugin_id is None
        or sys.platform not in {"linux", "win32"}
        or session_host_environment.architecture.lower() not in {"x86_64", "amd64"}
        or resolved_composition_set.set_id != "coding-standard"
        or session_no_tools_mode is not None
        or not session_manager.persist
    ):
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_query_turn_scope_unsupported"
        )
    if package_product_runtime_factory is not None and (
        initial_resource_catalog_product_composition_assembly is not None
        or package_materializer is not None
        or (
            product_base_requested
            and resource_catalog_source_policy
            != CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
        )
        or (
            not product_base_requested
            and (
                requested_plugin_ids
                or resource_catalog_source_policy.include_package_resources
            )
        )
    ):
        raise CodingPackageProductLegacyPathError(
            "Package Product runtime cannot coexist with legacy Plugin inputs"
        )
    enable_multiagent_tools = (
        enable_multiagent
        and allowed_tool_names is ToolSelection.ALL
        and session_no_tools_mode is None
    )
    if delegated_execution_profile is not None:
        if (
            allowed_tool_names is ToolSelection.ALL
            or tuple(allowed_tool_names or ())
            != delegated_execution_profile.allowed_tools
        ):
            raise ValueError(
                "child allowed tools must match its delegated execution profile"
            )
        if (
            approval_actor_id(approval_resolver)
            != delegated_execution_profile.approval_actor_id
        ):
            raise ValueError(
                "child approval actor must match its delegated execution profile"
            )
    if package_product_runtime_factory is not None:
        settings = services.settings_manager.get_settings()
        if settings.package_roots or settings.plugin_sources:
            raise CodingPackageProductLegacyPathError(
                "Package Product runtime cannot coexist with legacy Plugin inputs"
            )
    legacy_disabled_plugin_ids = (
        frozenset(
            getattr(services.settings_manager.get_settings(), "disabled_plugins", ())
        )
        if package_product_runtime_factory is None
        else frozenset()
    )
    lsp_mode = coding_capability_mount_mode(
        services.settings_manager,
        CODING_LSP_CAPABILITY,
    )
    arch_mode = coding_capability_mount_mode(
        services.settings_manager,
        CODING_ARCH_CAPABILITY,
    )
    resolved_lsp_environment = (
        dict(lsp_baseline_environment)
        if lsp_baseline_environment is not None
        else default_lsp_environment()
    )
    explicit_lsp_definitions = tuple(lsp_definitions)
    lsp_enabled_for_session = (
        "coding.lsp.default" in requested_plugin_ids
        and (
            resolved_invocation_profile is None
            or resolved_invocation_profile.include_lsp_provider
        )
        and lsp_mode != "disabled"
        and session_no_tools_mode != "all"
    )
    arch_enabled_for_session = (
        "coding.arch.default" in requested_plugin_ids
        and arch_mode != "disabled"
        and session_no_tools_mode != "all"
    )
    historical_entries = session_manager.get_entries()
    historical_startup = (
        historical_startup_composition_record(historical_entries)
        if historical_entries and lsp_enabled_for_session and lsp_mode == "on_demand"
        else None
    )
    defer_lsp_for_session = coding_lsp_should_defer(
        enabled=lsp_enabled_for_session,
        mode=lsp_mode,
        has_history=bool(historical_entries),
        startup=historical_startup,
        legacy_disabled="coding.lsp.default" in legacy_disabled_plugin_ids,
    )
    eager_lsp_enabled_for_session = (
        lsp_enabled_for_session and not defer_lsp_for_session
    )
    eager_capability_plugins_enabled_for_session = (
        eager_lsp_enabled_for_session or arch_enabled_for_session
    )
    capability_plugins_enabled_for_session = (
        lsp_enabled_for_session or arch_enabled_for_session
    )
    if _resume_effect_owner_ids is not None:
        expected_plugin_owners = (
            frozenset(
                {
                    "harness.plugin-execution",
                    "harness.plugin-activation",
                }
            )
            if eager_capability_plugins_enabled_for_session
            else frozenset()
        )
        if worker_candidate_plugin_id is not None:
            expected_plugin_owners |= frozenset({"harness.worker-activation"})
        if _resume_effect_owner_ids != expected_plugin_owners:
            raise CodingResourceCatalogAdmissionError(
                ("resume_plugin_participation_changed",)
            )
    if _resume_plugin_parents is not None and not eager_capability_plugins_enabled_for_session:
        raise ValueError(
            "Coding Resume Plugin parents require selected capability Plugins"
        )
    if lsp_enabled_for_session and lsp_read_text is not None:
        raise ValueError("Coding LSP reads only through harness.workspace")
    global_lsp_config, project_lsp_config = coding_lsp_config_paths(
        services.settings_manager,
        workspace_root=session_manager.get_cwd(),
    )
    resolved_lsp_definitions = (
        discover_lsp_catalog(
            workspace_root=session_manager.get_cwd(),
            baseline_environment=resolved_lsp_environment,
            explicit_definitions=explicit_lsp_definitions,
            global_config_path=global_lsp_config,
            project_config_path=project_lsp_config,
        ).definitions
        if eager_lsp_enabled_for_session
        else ()
    )
    # Restored sessions carry historical transcript.  A previous run may have
    # been interrupted between a tool call and its result, leaving an unpaired
    # toolCall in the transcript.  Force repair pairing for such sessions so
    # resume recovers automatically instead of raising
    # "Missing tool results before next message".  New sessions have no
    # history and stay on the (global) default.
    if historical_entries:
        base_factory = agent_factory

        def _resume_agent_factory(**kwargs: object) -> Agent:
            from loushang.ai.options import CallOptions

            call_options = kwargs.get("call_options")
            if call_options is None:
                kwargs["call_options"] = CallOptions(pairing_mode="repair")
            else:
                kwargs["call_options"] = replace(
                    cast(CallOptions, call_options), pairing_mode="repair"
                )
            return base_factory(**kwargs)

        agent_factory = _resume_agent_factory
    multiagent_types = None
    resolved_append_system_prompt = tuple(append_system_prompt or ())
    if enable_multiagent:
        from loushang.coding.session.multiagent import (
            coding_agent_types,
            coding_multiagent_system_prompt,
        )

        multiagent_types = coding_agent_types()
        if enable_multiagent_tools:
            resolved_append_system_prompt = (
                *resolved_append_system_prompt,
                coding_multiagent_system_prompt(
                    multiagent_types,
                    host_environment=session_host_environment,
                ),
            )
    session_tool_registry = (
        tool_registry.copy()
        if (enable_multiagent_tools or capability_plugins_enabled_for_session)
        and tool_registry is not None
        else tool_registry
    )
    construction_tools = tools
    if capability_plugins_enabled_for_session and session_tool_registry is None:
        session_tool_registry = WorkspaceToolRegistry()
        for definition in tools or ():
            session_tool_registry.register_tool(definition)
        if tools is not None:
            construction_tools = None
    resolved_package_materializer = (
        None
        if package_product_runtime_factory is not None
        else package_materializer or _default_package_materializer(session_manager)
    )
    session_id = session_manager.get_header().conversation_id
    product_workspace_witness = bind_coding_product_workspace_witness(
        package_product_runtime_factory, session_id=session_id
    )
    # PLC6 prepares Product-selected package evidence before the standard
    # activation graph reaches its startup-check step. Preserve the existing
    # diagnostic-before-failure contract when a corrupt binding lock prevents
    # that preparation from completing.
    if resolved_package_materializer is not None:
        record_package_lockfile_diagnostics(
            resolved_package_materializer.get_lockfile_diagnostics(),
            diagnostics_service=services.diagnostics_service,
            session_id=session_id,
        )
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None
    capability_management_state_cleanup: Callable[[], None] | None = None
    deferred_lsp_management_state_cleanup: Callable[[], None] | None = None
    managed = None
    use_managed_base = "coding.base" in requested_plugin_ids
    include_base_tools = session_no_tools_mode is None and (
        resolved_invocation_profile is None
        or resolved_invocation_profile.include_base_tool_contribution
    )
    include_base_tool_claim = session_no_tools_mode is None and (
        resolved_invocation_profile is None
        or resolved_invocation_profile.include_base_tool_claim_prompt
    )
    include_base_skills = (
        resolved_invocation_profile is None
        or resolved_invocation_profile.include_base_skill_contribution
    )
    include_base_commands = (
        resolved_invocation_profile is None
        or resolved_invocation_profile.include_base_command_contribution
    )
    if (
        package_product_runtime_factory is None
        and initial_resource_catalog_product_composition_assembly is None
        and (use_managed_base or capability_plugins_enabled_for_session)
    ):
        def prepare_primary(
            lifecycle: CodingPluginLifecycle,
            selected_materializer: PackageMaterializer,
            cleanup: Callable[[], None] | None,
        ) -> CodingBasePluginAssembly | None:
            return prepare_managed_coding_base_plugin_assembly(
                resolved_composition_set,
                session_id=session_id,
                package_materializer=selected_materializer,
                lifecycle=lifecycle,
                legacy_disabled=("coding.base" in legacy_disabled_plugin_ids),
                host_environment=session_host_environment,
                include_tool_contribution=include_base_tools,
                include_tool_claim_prompt=include_base_tool_claim,
                include_skill_contribution=include_base_skills,
                include_command_contribution=include_base_commands,
                state_cleanup=cleanup,
                session_owner_id=(
                    _session_manager_plugin_owner_id(session_manager)
                ),
            )

        # A configured settings runtime keeps Product desired state durable
        # even when the Session itself has no persistent transcript.
        managed = prepare_managed_plugins(
            session_manager=session_manager,
            services=services,
            session_id=session_id,
            package_materializer=package_materializer,
            resolved_package_materializer=resolved_package_materializer,
            ephemeral_prefix=(
                None
                if session_manager.persist or services.settings_manager.global_base_dir is not None
                else "loushang-coding-plugin-"
            ),
            prepare_primary=prepare_primary if use_managed_base else None,
            needs_eager=eager_capability_plugins_enabled_for_session,
            needs_deferred=defer_lsp_for_session,
        )
        coding_base_plugin_assembly = managed.primary
        capability_management_state_cleanup = managed.eager_cleanup
        deferred_lsp_management_state_cleanup = managed.deferred_cleanup

    def coding_plugin_clock() -> int:
        return time.time_ns() // 1_000_000

    preparation_custody: PreparationRootCustody[
        CodingCapabilityPluginCompositionPreparation
    ] = PreparationRootCustody()
    initial_catalog = InitialCatalogHandoff(
        services=services,
        session_id=session_id,
        custody=preparation_custody,
        source_policy=resource_catalog_source_policy,
    )

    def prepare_capability_roots(
        state_prefix: str, private_prefix: str, *, arch_enabled: bool
    ) -> Path:
        return preparation_custody.prepare_roots(
            state_prefix=None if session_manager.persist else state_prefix,
            private_prefix=(
                private_prefix if arch_enabled and not session_manager.persist else None
            ),
            persistent_root=lambda: _coding_capability_plugin_state_root(
                session_manager, session_id=session_id
            ),
            directory_factory=_ExplicitTemporaryDirectory,
        )

    def build_capability_configurations(
        *, lsp_enabled: bool, arch_enabled: bool, make_arch_root: Callable[[], Path]
    ) -> dict[str, CodingLspPluginConfigV1 | CodingArchPluginConfigV1]:
        configurations: dict[
            str,
            CodingLspPluginConfigV1 | CodingArchPluginConfigV1,
        ] = {}
        if lsp_enabled:
            configurations["coding.lsp.default"] = (
                CodingLspPluginConfigV1.from_runtime_inputs(
                    workspace_root=session_manager.get_cwd(),
                    definitions=resolved_lsp_definitions,
                    baseline_environment=resolved_lsp_environment,
                )
            )
        if arch_enabled:
            configurations["coding.arch.default"] = (
                CodingArchPluginConfigV1.from_runtime_inputs(
                    workspace_root=session_manager.get_cwd(),
                    private_data_root=(
                        Path(preparation_custody.private_root.name)
                        if preparation_custody.private_root is not None
                        else make_arch_root()
                    ),
                )
            )
        return configurations

    def prepare_capability_plugins(
        plan_seed: ProductPluginPlanSeed | None = None,
    ) -> CodingCapabilityPluginCompositionPreparation | None:

        preparation_custody.begin_once(
            "Coding Capability Plugins were already prepared"
        )
        state_root = prepare_capability_roots(
            "loushang-coding-capability-plugins-",
            "loushang-coding-arch-private-",
            arch_enabled=arch_enabled_for_session,
        )
        policy_revision = (
            plan_seed.plan.context.policy_revision if plan_seed is not None else None
        )
        plugin_ids = frozenset(
            {
                *(("coding.lsp.default",) if eager_lsp_enabled_for_session else ()),
                *(("coding.arch.default",) if arch_enabled_for_session else ()),
            }
        )
        request = (
            create_coding_capability_plugin_composition_request(
                clock=coding_plugin_clock,
                plugin_ids=plugin_ids,
                product_policy_revision=policy_revision,
            )
            if policy_revision is not None
            else create_coding_capability_plugin_composition_request(
                clock=coding_plugin_clock,
                plugin_ids=plugin_ids,
            )
        )
        configurations = build_capability_configurations(
            lsp_enabled=eager_lsp_enabled_for_session,
            arch_enabled=arch_enabled_for_session,
            make_arch_root=lambda: state_root / "private-data" / "coding-arch-default",
        )
        assert managed is not None
        try:
            return managed.prepare_capabilities(
                request,
                configurations,
                session_manager=session_manager,
                session_id=session_id,
                state_root=state_root,
                clock=coding_plugin_clock,
                legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
                management_cleanup=capability_management_state_cleanup,
                base=coding_base_plugin_assembly,
                plan_seed=plan_seed,
                state_cleanup=preparation_custody.state_cleanup,
                private_state_cleanup=preparation_custody.private_cleanup,
            )
        except CodingCapabilityPluginCompositionError as error:
            if error.code != "coding_capability_plugins_management_disabled":
                raise
            return None

    catalog_product_composition_assembly = (
        initial_resource_catalog_product_composition_assembly
    )
    include_configured_catalog_plugins = (
        resolved_invocation_profile.include_configured_resource_plugins
        if resolved_invocation_profile is not None
        else resource_catalog_source_policy.include_package_resources
    )
    selected_plugin_packages = (
        (
            SelectedPluginPackageInput(
                package=coding_base_plugin_assembly.package,
                binding=coding_base_plugin_assembly.binding,
            ),
        )
        if coding_base_plugin_assembly is not None
        else ()
    )

    def prepare_initial_resource_catalog_projection(
        loader: ResourceLoader,
        resolved_cwd: Path,
    ) -> ResourceBundle:
        def reconcile_compatibility() -> None:
            compatibility = bind_coding_plugin_enablement_compatibility(
                resolve_coding_plugin_lifecycle_state_layout(resolved_cwd),
                services.settings_manager,
            )
            if compatibility is not None:
                compatibility.reconcile()

        try:
            initial_catalog.require_unprepared(
                "Initial Resource Catalog projection was already prepared"
            )
            _reject_peer_coding_exact_tools(
                tool_registry=session_tool_registry,
                tools=construction_tools,
            )
            return initial_catalog.prepare_legacy_projection(
                loader,
                cwd=resolved_cwd,
                base=coding_base_plugin_assembly,
                supplied=catalog_product_composition_assembly,
                include_configured=include_configured_catalog_plugins,
                prepare_capabilities=(
                    prepare_capability_plugins
                    if eager_capability_plugins_enabled_for_session
                    else None
                ),
                reconcile_compatibility=reconcile_compatibility,
                clock=(
                    coding_plugin_clock
                    if coding_base_plugin_assembly is not None
                    or capability_plugins_enabled_for_session
                    else None
                ),
            )
        except CodingResourceCatalogAdmissionError as error:
            initial_catalog.record_admission_failure(error)
            raise

    def _prepare_package_product_catalog_projection(
        loader: ResourceLoader,
        resolved_cwd: Path,
        product_runtime: PackageProductRuntimeBindingV1,
    ) -> ResourceBundle:
        if not product_base_requested or initial_catalog.authority.base is not None:
            raise RuntimeError("Coding Product base Catalog was already prepared")
        initial_catalog.require_unprepared("Coding Product base cannot mix Catalog routes")
        _reject_peer_coding_exact_tools(
            tool_registry=session_tool_registry,
            tools=construction_tools,
        )

        def prepare_capability_inputs(
            enabled_ids: list[str],
        ) -> tuple[Path, dict[str, CodingLspPluginConfigV1 | CodingArchPluginConfigV1]]:
            arch_enabled = "coding.arch.default" in enabled_ids
            state_root = prepare_capability_roots(
                "loushang-coding-product-capability-plugins-",
                "loushang-coding-product-arch-private-",
                arch_enabled=arch_enabled,
            )
            return state_root, build_capability_configurations(
                lsp_enabled="coding.lsp.default" in enabled_ids,
                arch_enabled=arch_enabled,
                make_arch_root=lambda: prepare_coding_product_arch_private_data_root(
                    resolve_coding_plugin_lifecycle_state_layout(
                        session_manager.get_cwd()
                    ),
                    product_runtime,
                    session_id=session_id,
                ),
            )

        requested_capabilities = (
            ("coding.lsp.default", eager_lsp_enabled_for_session),
            ("coding.arch.default", arch_enabled_for_session),
        )

        def compile_base(
            selected: PackageProductSelectedPluginManifestV1, evaluated_at: int
        ) -> CodingBaseProductCompilation:
            return compile_coding_base_product_selection(
                selected,
                resolved_composition_set,
                installation_key=selected.snapshot.installation_key,
                session_id=session_id,
                host_environment=session_host_environment,
                evaluated_at=evaluated_at,
                include_tool_contribution=include_base_tools,
                include_tool_claim_prompt=include_base_tool_claim,
                include_skill_contribution=include_base_skills,
                include_command_contribution=include_base_commands,
            )

        return initial_catalog.prepare_fenced_projection(
            product_runtime,
            loader,
            cwd=resolved_cwd,
            composition_set=resolved_composition_set,
            requested_capabilities=requested_capabilities,
            max_files=_CATALOG_MANIFEST_MAX_FILES,
            max_total_bytes=_CATALOG_MANIFEST_MAX_BYTES,
            clock=coding_plugin_clock,
            compile_base=compile_base,
            prepare_capability_inputs=prepare_capability_inputs,
            resume_parents=_resume_plugin_parents,
        )

    def prepare_package_product_catalog_projection(
        loader: ResourceLoader,
        resolved_cwd: Path,
        product_runtime: PackageProductRuntimeBindingV1,
    ) -> ResourceBundle:
        try:
            return _prepare_package_product_catalog_projection(
                loader, resolved_cwd, product_runtime
            )
        except BaseException as error:
            if isinstance(error, CodingResourceCatalogAdmissionError):
                initial_catalog.record_admission_failure(error)
            run_cleanup_steps(
                error,
                (("Coding Product runtime bootstrap cleanup", product_runtime.dispose_runtime),),
            )
            raise

    constructed_session: AgentSession | None = None

    def _create_session(
        capability_runtime: StagedResourceCompositionCandidate,
        side_question_binding: LegacySideQuestionBinding | None,
        agent: Agent,
        bundle: ResourceBundle,
        extension_runner: ExtensionRunner,
        registry: WorkspaceToolRegistry | None,
        initial_active_tool_names: list[str] | None,
        session_base_prompt: str,
        session_no_tools_mode: NoToolsMode | None,
        package_product_lifecycle: PackageProductLifecycleOperationPort | None,
        package_product_inventory: PackageProductLifecycleInventoryPort | None,
        package_product_lifecycle_mode: PackageProductLifecycleMode,
    ) -> AgentSession:
        nonlocal constructed_session
        resource_catalog_adapter = initial_catalog.take_adapter()
        catalog_authority = initial_catalog.authority
        product_base_compilation = catalog_authority.base
        product_base_runtime = catalog_authority.runtime
        product_base_disabled_selection = catalog_authority.disabled_base
        product_capability_desired_selections = catalog_authority.capability_selections
        product_external_data_compilation = catalog_authority.external
        catalog_authority.require_current()

        prepare_resource_catalog_refresh = partial(
            initial_catalog.prepare_refresh,
            get_cwd=session_manager.get_cwd,
            base=coding_base_plugin_assembly,
            supplied=catalog_product_composition_assembly,
            include_configured=include_configured_catalog_plugins,
            clock=coding_plugin_clock,
        )

        process_session: AgentSession | None = None

        async def emit_process_audit_event(event: Mapping[str, object]) -> None:
            if process_session is None:
                raise RuntimeError("Coding workspace Session is not yet bound")
            await process_session.emit_product_tool_audit_event(event)

        sandbox_runtime, workspace_binding = bind_session_workspace(
            services,
            session_manager.get_cwd,
            session_id=session_id,
            writable_workspace=sandbox_workspace_writable,
            delegated_execution_profile=delegated_execution_profile,
            tool_policy_evaluator=tool_policy_evaluator,
            approval_resolver=approval_resolver,
            audit_sink=emit_process_audit_event,
            provider_id="coding.workspace.standard",
            source_id=CODING_PRODUCT_ID,
            fingerprint_namespace="coding.workspace.standard.v1",
            ceiling_type_error=(
                "Coding workspace execution ceiling must be an EffectiveExecutionProfile"
            ),
        )

        capability_tool_modes = (
            {
                capability_id: {
                    CODING_LSP_CAPABILITY: lsp_mode,
                    CODING_ARCH_CAPABILITY: arch_mode,
                }[capability_id]
                for capability_id in (
                    preparation_custody.preparation.provider_owner_authorities
                )
            }
            if preparation_custody.preparation is not None
            else {}
        )
        (
            capability_plugin_assembly,
            base_plugin_session_assembly,
            product_base_session_assembly,
        ) = bind_workspace_plugins(
            workspace_binding,
            builtin_product_preparation=initial_catalog.builtin_preparation,
            capability_preparation=preparation_custody.preparation,
            base_plugin_session_preparation=initial_catalog.legacy_preparation,
            product_base_compilation=product_base_compilation,
            host_boot_id=_CODING_PLUGIN_HOST_BOOT_ID,
            tool_modes=capability_tool_modes,
            clock=coding_plugin_clock,
        )
        worker_ordinary_binding = None
        if worker_candidate_plugin_id is not None:
            from loushang.coding.package.product_worker_ordinary_bootstrap import (
                prepare_coding_product_worker_ordinary_binding,
            )

            if product_base_session_assembly is None or product_base_runtime is None:
                raise CodingWorkerOrdinaryBootstrapError(
                    "coding_worker_ordinary_base_product_unavailable"
                )
            assert isinstance(
                package_product_runtime_factory,
                (
                    CodingSessionOwnedProductRuntimeFactory,
                    CodingApplicationWorkerProductRuntimeFactory,
                ),
            )
            worker_ordinary_binding = prepare_coding_product_worker_ordinary_binding(
                product_owner=package_product_runtime_factory.product_owner_for_worker(),
                runtime=product_base_runtime,
                session_manager=session_manager,
                plugin_id=worker_candidate_plugin_id,
                ordinary=product_base_session_assembly,
                clock=coding_plugin_clock,
                resume_parent_context=_resume_worker_parent,
            )
        worker_turn_tool = None
        worker_tool_registry = registry
        if worker_ordinary_binding is not None and worker_query_turn_tool:
            from loushang.coding.package.product_worker_turn_tool import (
                CODING_WORKER_QUERY_TOOL_NAME,
                CodingWorkerTurnToolBinding,
            )

            assert worker_candidate_plugin_id is not None
            assert worker_ordinary_binding.activation_receipt is not None
            worker_turn_tool = CodingWorkerTurnToolBinding(worker_candidate_plugin_id)
            if any(
                definition.name == CODING_WORKER_QUERY_TOOL_NAME
                for definition in (
                    registry.list_definitions() if registry is not None else ()
                )
            ):
                raise CodingWorkerOrdinaryBootstrapError(
                    "coding_worker_query_tool_name_conflict"
                )

        def construct_child_session(
            initial_resource_catalog_bootstrap: Any | None = None,
        ) -> AgentSession:
            resolved_initial_active_tool_names = initial_active_tool_names
            if resolved_initial_active_tool_names is None and (
                coding_base_plugin_assembly is not None
                or product_base_compilation is not None
            ):
                if product_base_compilation is not None:
                    base_tool_names = set(product_base_compilation.tool_names)
                    base_host_environment = product_base_compilation.host_environment
                else:
                    assert coding_base_plugin_assembly is not None
                    base_tool_names = set(coding_base_plugin_assembly.tool_names)
                    base_host_environment = coding_base_plugin_assembly.host_environment
                resolved_initial_active_tool_names = initial_tool_names(
                    coding_default_active_tool_names(base_host_environment),
                    base_tool_names,
                    worker_tool_registry,
                )
            session = AgentSession(
                agent=agent,
                session_manager=session_manager,
                settings_manager=services.settings_manager,
                model_registry=services.model_registry,
                resource_loader=services.resource_loader,
                resource_bundle=bundle,
                extension_runner=extension_runner,
                tool_registry=worker_tool_registry,
                allowed_tool_names=[]
                if session_no_tools_mode == "all"
                else allowed_tool_names,
                active_tool_names=resolved_initial_active_tool_names,
                default_activate_new_tools=(
                    session_no_tools_mode != "all" and active_tool_names is None
                ),
                show_empty_tool_prompt=session_no_tools_mode == "all",
                base_prompt=session_base_prompt,
                diagnostics_service=services.diagnostics_service,
                session_start_event=session_start_event,
                package_materializer=resolved_package_materializer,
                package_product_lifecycle=package_product_lifecycle,
                package_product_inventory=package_product_inventory,
                package_product_lifecycle_mode=package_product_lifecycle_mode,
                exec_service=sandbox_runtime.exec_service,
                output_capture_factory=output_capture_factory,
                approval_resolver=approval_resolver,
                tool_policy_evaluator=tool_policy_evaluator,
                capability_runtime=capability_runtime,
                side_question_binding=side_question_binding,
                sandbox_runtime=sandbox_runtime,
                coding_capability_plugin_assembly=capability_plugin_assembly,
                coding_base_plugin_assembly=coding_base_plugin_assembly,
                coding_base_plugin_session_assembly=(base_plugin_session_assembly),
                coding_base_product_session_assembly=(product_base_session_assembly),
                coding_external_data_product_compilation=(
                    product_external_data_compilation
                ),
                coding_selected_capability_manifests=(
                    capture_selected_manifests(
                        product_base_runtime.capture_selected_plugin_manifest_for,
                        (
                            selection.installation_key.plugin_id
                            for selection in product_capability_desired_selections
                            if selection.desired_state == "installed_enabled"
                        ),
                        max_files=_CATALOG_MANIFEST_MAX_FILES,
                        max_total_bytes=_CATALOG_MANIFEST_MAX_BYTES,
                    )
                    if product_base_compilation is None
                    and product_base_runtime is not None
                    else ()
                ),
                coding_base_product_runtime_binding=(product_base_runtime),
                coding_product_desired_selections=(
                    *(
                        (product_base_disabled_selection,)
                        if product_base_disabled_selection is not None
                        else ()
                    ),
                    *product_capability_desired_selections,
                ),
                coding_product_workspace_witness=product_workspace_witness,
                coding_plugin_clock=coding_plugin_clock,
                delegated_execution_profile=delegated_execution_profile,
                workspace_capability_binding=workspace_binding,
                coding_product_worker_ordinary_binding=worker_ordinary_binding,
                coding_worker_turn_tool=worker_turn_tool,
                coding_composition_plan=resolved_composition_set,
                initial_resource_catalog_bootstrap=(initial_resource_catalog_bootstrap),
                resource_catalog_refresh_bootstrap_factory=(
                    prepare_resource_catalog_refresh
                ),
                resource_catalog_refresh_lock=(services.resource_catalog_refresh_lock),
            )
            if defer_lsp_for_session:
                product_lsp_available = (
                    product_base_runtime is None
                    or product_base_runtime.capture_plugin_desired_selection_for(
                        "coding.lsp.default"
                    ).desired_state
                    == "installed_enabled"
                )
                if product_lsp_available:

                    def build_deferred_lsp_config() -> CodingLspPluginConfigV1:
                        global_config, project_config = coding_lsp_config_paths(
                            services.settings_manager,
                            workspace_root=session_manager.get_cwd(),
                        )
                        definitions = discover_lsp_catalog(
                            workspace_root=session_manager.get_cwd(),
                            baseline_environment=resolved_lsp_environment,
                            explicit_definitions=explicit_lsp_definitions,
                            global_config_path=global_config,
                            project_config_path=project_config,
                        ).definitions
                        return CodingLspPluginConfigV1.from_runtime_inputs(
                            workspace_root=session_manager.get_cwd(),
                            definitions=definitions,
                            baseline_environment=resolved_lsp_environment,
                        )

                    build_deferred_lsp_assembly = partial(
                        bind_deferred_plugin,
                        workspace_binding,
                        session_manager=session_manager,
                        session_id=session_id,
                        plugin_id="coding.lsp.default",
                        managed=managed,
                        runtime=product_base_runtime,
                        build_config=build_deferred_lsp_config,
                        temporary_prefix="loushang-coding-deferred-lsp-",
                        persistent_root=lambda: _coding_capability_plugin_state_root(
                            session_manager, session_id=session_id
                        ) / "deferred-lsp",
                        legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
                        clock=coding_plugin_clock,
                        host_boot_id=_CODING_PLUGIN_HOST_BOOT_ID,
                        tool_modes={CODING_LSP_CAPABILITY: "on_demand"},
                        max_manifest_files=_CATALOG_MANIFEST_MAX_FILES,
                        max_manifest_bytes=_CATALOG_MANIFEST_MAX_BYTES,
                        admission_failure=CodingResourceCatalogAdmissionError,
                    )

                    def create_deferred_lsp_generation() -> CodingDeferredLspGeneration:
                        async def assemble_deferred_lsp(
                        ) -> CodingCapabilityPluginCompositionAssembly:
                            task = asyncio.create_task(
                                asyncio.to_thread(build_deferred_lsp_assembly)
                            )
                            assembly, check = await _await_cancellation_atomic(task)
                            generation.current_selection_check = check
                            return assembly

                        generation = CodingDeferredLspGeneration(
                            session_id=session_id,
                            profile_fingerprint=(
                                session._capability_graph_runtime.profile_fingerprint
                            ),
                            workspace_binding=workspace_binding,
                            registration=session._composition.tool_controller,
                            assembly_factory=assemble_deferred_lsp,
                        )
                        return generation

                    session.install_deferred_lsp_slot(
                        DeferredCapabilitySlot(
                            DeferredCapabilityDeclaration(
                                capability_id=CODING_LSP_CAPABILITY,
                                facet_ids=CODING_LSP_CAPABILITY_DEFINITION.facets,
                                tool_names=CODING_LSP_EXACT_OWNER_TOOL_NAMES,
                            ),
                            create_deferred_lsp_generation,
                        ),
                        management_cleanup=deferred_lsp_management_state_cleanup,
                    )
                elif deferred_lsp_management_state_cleanup is not None:
                    deferred_lsp_management_state_cleanup()
            if worker_turn_tool is not None:
                worker_turn_tool.bind_session(session)
            return session

        child_session = construct_catalog_session(
            resource_catalog_adapter,
            product_id=CODING_PRODUCT_ID,
            session_id=session_id,
            bundle=bundle,
            construct=construct_child_session,
            abort_unpublished=(
                (
                    "Coding Capability Plugin assembly cleanup",
                    capability_plugin_assembly.abort_unpublished,
                )
                if capability_plugin_assembly is not None
                else None
            ),
        )
        process_session = child_session
        constructed_session = child_session
        return child_session

    construction_binding = replace(
        _CODING_AGENT_PRODUCT_CONSTRUCTION,
        default_system_prompt=coding_kernel_prompt,
    )
    try:
        result = construction_binding.construct(
            services=services,
            package_materializer=resolved_package_materializer,
            package_product_runtime_factory=package_product_runtime_factory,
            session_id=session_id,
            cwd=session_manager.get_cwd(),
            extension_flag_values=extension_flag_values,
            catalog_authoritative=True,
            prepare_catalog_bootstrap_projection=(
                prepare_initial_resource_catalog_projection
            ),
            prepare_package_product_catalog_bootstrap_projection=(
                prepare_package_product_catalog_projection
                if product_base_requested
                else None
            ),
            selected_plugin_packages=selected_plugin_packages,
            explicit_system_prompt=system_prompt,
            append_system_prompt=resolved_append_system_prompt,
            model=model,
            use_default_model=use_default_model,
            thinking_level=thinking_level,
            tools=construction_tools,
            tool_registry=session_tool_registry,
            allowed_tool_names=allowed_tool_names,
            active_tool_names=active_tool_names,
            no_tools=no_tools,
            stream_fn=stream_fn,
            convert_to_llm=lambda messages: context_items_to_model_messages(
                messages,
                image_placeholder=(
                    "Image reading is disabled."
                    if services.settings_manager.get_block_images()
                    else None
                ),
            ),
            agent_factory=agent_factory,
            session_factory=_create_session,
            on_default_model_unavailable=lambda selection, error, reason: (
                record_default_model_unavailable(
                    selection,
                    error=error,
                    reason=reason,
                    diagnostics_service=services.diagnostics_service,
                    session_id=session_id,
                )
            ),
            set_scoped_models=lambda session, scoped_models: session.set_scoped_models(
                cast(list[dict[str, object]], scoped_models)
            ),
        )
    except BaseException as error:
        cleanup = get_session_construction_cleanup(error)
        if cleanup is not None and cleanup.owns_session(constructed_session):
            raise
        preparation_custody.rollback_startup(
            error,
            failure_custodian=coding_capability_plugin_failure_custodian(error),
            management_cleanup=capability_management_state_cleanup,
            product_label="Coding",
            private_label="Coding Arch private-state cleanup",
            before=(
                "Deferred Coding LSP management-state cleanup",
                deferred_lsp_management_state_cleanup,
            ),
            after=(
                "Coding base Plugin cleanup",
                coding_base_plugin_assembly.close if coding_base_plugin_assembly is not None else None,
            ),
        )
        raise
    try:
        result.session.cwd_bound_services_audit = (
            result.configuration.cwd_bound_services_audit
        )
        if enable_multiagent:
            from loushang.coding.session.multiagent import (
                CodingSubagentFactory,
                install_coding_multiagent_session,
            )
            from loushang.coding.workspace.worktree import CodingGitWorktreeLeasePort

            assert multiagent_types is not None
            selected_capability_plugin_ids = (
                frozenset(result.session._coding_capability_plugin_assembly.tool_owners)
                if result.session._coding_capability_plugin_assembly is not None
                else frozenset()
            )
            install_coding_multiagent_session(
                result.session,
                child_factory=CodingSubagentFactory(
                    session_dir=session_manager.get_session_dir(),
                    cwd=session_manager.get_cwd(),
                    tool_registry=(session_tool_registry or WorkspaceToolRegistry()),
                    default_model_provider=lambda: result.session.agent.model,
                    services=services,
                    approval_resolver=approval_resolver,
                    host_environment=session_host_environment,
                    selected_exact_tool_names=(
                        *(
                            initial_catalog.authority.base.tool_names
                            if initial_catalog.authority.base is not None
                            else coding_base_plugin_assembly.tool_names
                            if coding_base_plugin_assembly is not None
                            else ()
                        ),
                        *(
                            CODING_LSP_EXACT_OWNER_TOOL_NAMES
                            if "coding.lsp.default" in selected_capability_plugin_ids
                            else ()
                        ),
                        *(
                            CODING_ARCH_EXACT_OWNER_TOOL_NAMES
                            if "coding.arch.default" in selected_capability_plugin_ids
                            else ()
                        ),
                    ),
                    workspace_leases=CodingGitWorktreeLeasePort(
                        cwd=session_manager.get_cwd(),
                        exec_service=services.exec_service,
                    ),
                    runtime_builder=partial(
                        _create_agent_session_runtime,
                        stream_fn=stream_fn,
                        agent_factory=agent_factory,
                        tool_policy_evaluator=tool_policy_evaluator,
                        composition_set=resolved_composition_set,
                    ),
                ),
                agent_types=multiagent_types,
                register_tools=enable_multiagent_tools,
            )
        return result.session
    except BaseException as error:
        retained = retain_session_construction_failure(error, result.session)
        if retained is error:
            raise
        raise retained from error





def _select_direct_coding_product_factory(
    manager: SessionManager,
    *,
    services: BootstrapServices | None,
    worker_candidates: bool = False,
    windows_candidate: bool = False,
) -> PackageProductRuntimeFactoryPort | None:
    selection = CodingFencedProductApplicationSelection(
        worker_candidates=worker_candidates,
        windows_candidate=windows_candidate,
    )
    try:
        factory = selection.factory_for_session(
            manager,
            settings_manager=(None if services is None else services.settings_manager),
        )
    except BaseException as error:
        try:
            selection.close()
        except BaseException:
            error.add_note("Coding Product owner cleanup also failed")
        raise
    if factory is None:
        selection.close()
        return None
    return CodingSessionOwnedProductRuntimeFactory(factory, selection)


async def _create_resume_agent_session(
    *, session_manager: SessionManager, attempt_id: str,
    composition_set: CodingCompositionSetPlan,
    require_current_admission: Callable[[CodingActivationAttemptV1], None],
    services: BootstrapServices | None = None,
    model: Model | ModelSelection | None = None,
    thinking_level: ThinkingLevel | None = None,
    stream_fn: StreamFn | None = None,
    tools: list[ToolDefinition] | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    no_tools: NoToolsMode | bool | None = None,
    agent_factory: AgentFactory = Agent,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    product_owner_selection: CodingFencedProductApplicationSelection | None = None,
    worker_candidates: bool = False,
    worker_candidate_plugin_id: str | None = None,
    resume_plugin_parents: CodingResumePluginParents | None = None,
    resume_worker_parent: ResumeEffectParentContextV1 | None = None,
    resume_effect_owner_ids: frozenset[str] | None = None,
) -> AgentSession:
    """Construct a fenced current candidate for a locally committed Resume Plan.

    Current admission belongs to the activation coordinator. This owner route
    retains the old Header and does not publish execution or commit user input.
    It must not be used for recovery of an uncertain or historical-only intent.
    """

    if product_owner_selection is not None and not isinstance(
        product_owner_selection, CodingFencedProductApplicationSelection,
    ):
        raise TypeError("Coding Resume Product application owner is invalid")
    if (
        type(worker_candidates) is not bool
        or (
            worker_candidate_plugin_id is not None
            and (
                not isinstance(worker_candidate_plugin_id, str)
                or not worker_candidate_plugin_id
                or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
            )
        )
        or ((worker_candidates or worker_candidate_plugin_id is not None) and product_owner_selection is None)
        or (resume_worker_parent is not None and worker_candidate_plugin_id is None)
    ):
        raise ValueError("Coding Resume Worker requires its application Product owner")
    include_worker_candidates = worker_candidates or worker_candidate_plugin_id is not None
    composition = _canonical_coding_composition_set(composition_set)
    admission = _CodingResumeBootstrapAdmission(
        session_manager, attempt_id, composition, require_current_admission,
    )
    admission.require(session_manager, composition)
    selected_factory = (
        _borrow_application_coding_product_factory(
            product_owner_selection, session_manager, services=services,
            worker_candidates=include_worker_candidates,
        ) if product_owner_selection is not None else _select_direct_coding_product_factory(
            session_manager, services=services, windows_candidate=sys.platform == "win32",
        )
    )
    session: AgentSession | None = None
    try:
        admission.require(session_manager, composition)
        session = _create_agent_session(
            session_manager=session_manager, composition_set=composition,
            composition_set_explicit=True, services=services, model=model,
            stream_fn=stream_fn, thinking_level=thinking_level, tools=tools,
            output_capture_factory=output_capture_factory,
            no_tools=no_tools, agent_factory=agent_factory,
            approval_resolver=approval_resolver, tool_policy_evaluator=tool_policy_evaluator,
            package_product_runtime_factory=selected_factory,
            worker_candidate_plugin_id=worker_candidate_plugin_id,
            _resume_bootstrap_admission=admission,
            _resume_plugin_parents=resume_plugin_parents,
            _resume_worker_parent=resume_worker_parent,
            _resume_effect_owner_ids=resume_effect_owner_ids,
        )
        admission.require(session_manager, composition)
        return session
    except BaseException as error:
        if session is not None:
            await discard_candidate(
                session, error, cleanup_note="Coding Resume candidate cleanup also failed: "
            )
        else:
            dispose_unbound_factory_after_failure(selected_factory, error)
        raise


def create_agent_session(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    composition_set: CodingCompositionSetId | None = None,
    services: BootstrapServices | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    package_product_runtime_factory: PackageProductRuntimeFactoryPort | None = None,
    worker_candidate_plugin_id: str | None = None,
    worker_query_turn_tool: bool = False,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
) -> AgentSession:
    return _create_agent_session_with_model_policy(
        session_manager=session_manager,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        composition_set=composition_set,
        services=services,
        output_capture_factory=output_capture_factory,
        agent_factory=agent_factory,
        session_start_event=session_start_event,
        package_materializer=package_materializer,
        package_product_runtime_factory=package_product_runtime_factory,
        worker_candidate_plugin_id=worker_candidate_plugin_id,
        worker_query_turn_tool=worker_query_turn_tool,
        resource_catalog_source_policy=resource_catalog_source_policy,
        append_system_prompt=append_system_prompt,
        extension_flag_values=extension_flag_values,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
    )


def _create_agent_session_with_model_policy(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    composition_set: CodingCompositionSetId | None = None,
    services: BootstrapServices | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    package_product_runtime_factory: PackageProductRuntimeFactoryPort | None = None,
    worker_candidate_plugin_id: str | None = None,
    worker_query_turn_tool: bool = False,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
    _use_default_model: bool = True,
) -> AgentSession:
    session_manager.require_no_unsettled_resume_activation()
    if worker_candidate_plugin_id is not None and (
        not isinstance(worker_candidate_plugin_id, str)
        or not worker_candidate_plugin_id
        or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
        or not session_manager.is_persisted()
    ):
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_transcript_not_materialized"
        )
    selected_factory = (
        package_product_runtime_factory
        if package_product_runtime_factory is not None
        else _select_direct_coding_product_factory(
            session_manager,
            services=services,
            worker_candidates=worker_candidate_plugin_id is not None,
            windows_candidate=sys.platform == "win32",
        )
    )
    try:
        return _create_agent_session(
            session_manager=session_manager,
            model=model,
            use_default_model=_use_default_model,
            stream_fn=stream_fn,
            system_prompt=system_prompt,
            thinking_level=thinking_level,
            tools=tools,
            tool_registry=tool_registry,
            allowed_tool_names=allowed_tool_names,
            active_tool_names=active_tool_names,
            no_tools=no_tools,
            composition_set=resolve_coding_composition_set(
                "coding-standard" if composition_set is None else composition_set
            ),
            composition_set_explicit=composition_set is not None,
            services=services,
            output_capture_factory=output_capture_factory,
            agent_factory=agent_factory,
            session_start_event=session_start_event,
            package_materializer=package_materializer,
            package_product_runtime_factory=selected_factory,
            worker_candidate_plugin_id=worker_candidate_plugin_id,
            worker_query_turn_tool=worker_query_turn_tool,
            resource_catalog_source_policy=resource_catalog_source_policy,
            append_system_prompt=append_system_prompt,
            extension_flag_values=extension_flag_values,
            approval_resolver=approval_resolver,
            tool_policy_evaluator=tool_policy_evaluator,
            enable_multiagent=enable_multiagent,
            sandbox_workspace_writable=True,
            lsp_definitions=lsp_definitions,
            lsp_baseline_environment=lsp_baseline_environment,
            lsp_read_text=lsp_read_text,
        )
    except BaseException as error:
        dispose_unbound_factory_after_failure(selected_factory, error)
        raise


def create_agent_session_from_services(
    *,
    agent_services: AgentSessionServices,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    composition_set: CodingCompositionSetId | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    package_product_runtime_factory: PackageProductRuntimeFactoryPort | None = None,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
) -> CreateAgentSessionResult:
    try:
        extension_flag_values = (
            agent_services.extension_runner.get_flag_values()
            if agent_services.extension_runner is not None
            else None
        )
    except BaseException as error:
        dispose_unbound_factory_after_failure(package_product_runtime_factory, error)
        raise
    return create_agent_session_result(
        session_manager=session_manager,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        composition_set=composition_set,
        services=agent_services.services,
        agent_factory=agent_factory,
        session_start_event=session_start_event,
        package_materializer=package_materializer,
        package_product_runtime_factory=package_product_runtime_factory,
        resource_catalog_source_policy=resource_catalog_source_policy,
        append_system_prompt=append_system_prompt,
        extension_flag_values=extension_flag_values,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
    )


def create_agent_session_result(
    *,
    session_manager: SessionManager,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    composition_set: CodingCompositionSetId | None = None,
    services: BootstrapServices | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    agent_factory: AgentFactory = Agent,
    session_start_event: SessionStartEvent | None = None,
    package_materializer: PackageMaterializer | None = None,
    package_product_runtime_factory: PackageProductRuntimeFactoryPort | None = None,
    worker_candidate_plugin_id: str | None = None,
    worker_query_turn_tool: bool = False,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    extension_flag_values: ExtensionFlagValues | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
) -> CreateAgentSessionResult:
    try:
        resolved_services = services or create_services()
    except BaseException as error:
        dispose_unbound_factory_after_failure(package_product_runtime_factory, error)
        raise
    session = create_agent_session(
        session_manager=session_manager,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        composition_set=composition_set,
        services=resolved_services,
        output_capture_factory=output_capture_factory,
        agent_factory=agent_factory,
        session_start_event=session_start_event,
        package_materializer=package_materializer,
        package_product_runtime_factory=package_product_runtime_factory,
        worker_candidate_plugin_id=worker_candidate_plugin_id,
        worker_query_turn_tool=worker_query_turn_tool,
        resource_catalog_source_policy=resource_catalog_source_policy,
        append_system_prompt=append_system_prompt,
        extension_flag_values=extension_flag_values,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
    )
    try:
        return build_standard_agent_session_result(
            session,
            resource_bundle=session.resource_bundle,
            diagnostics_service=resolved_services.diagnostics_service,
            session_id=session.session_id,
            cwd_bound_services_audit=session.cwd_bound_services_audit,
        )
    except BaseException as error:
        retained = retain_session_construction_failure(error, session)
        if retained is error:
            raise
        raise retained from error


def _default_package_materializer(
    session_manager: SessionManager,
) -> PackageMaterializer:
    return PackageMaterializer(
        install_root=resolve_session_package_install_root(
            session_dir=session_manager.get_session_dir(),
            cwd=session_manager.get_cwd(),
        ),
        backend=GitPackageMaterializerBackend(),
    )


def _coding_capability_plugin_state_root(
    session_manager: SessionManager,
    *,
    session_id: str,
) -> Path:
    relative_path = coding_session_plugin_state_relative_path(session_id)
    return session_manager.get_session_dir() / relative_path



def _source_identity_startup_check(cwd: str) -> StartupCheckResult:
    return StartupCheckResult(
        name="executable_source_identity",
        ok=True,
        code="executable_source_identity",
        level="info",
        message="Executable and import source identity captured.",
        source_path=Path(__file__).resolve(strict=False),
        details=coding_runtime_identity(cwd=cwd),
    )


_CODING_AGENT_PRODUCT_CONSTRUCTION = AgentProductConstructionBinding[
    Agent,
    AgentSession,
    ExtensionRunner,
](
    default_system_prompt=DEFAULT_CODING_SYSTEM_PROMPT,
    product_id=CODING_PRODUCT_ID,
    bind_capabilities=lambda: stage_resource_composition_candidate(
        CODING_CAPABILITY_PROFILE
    ),
    create_extension_runtime=lambda bundle: ExtensionRunner(bundle.extensions),
    source_identity_check=_source_identity_startup_check,
    list_tool_definitions=lambda runner: runner.list_tool_definitions(),
    get_tool_source_info=lambda runner, name: runner.get_tool_source_info(name),
    bind_session_side_question=bind_coding_side_question,
    resolve_session_capability_profile=lambda runner: (
        resolve_coding_capability_profile(runner.active_extensions).profile
    ),
    product_tool_pack_id="coding.registry",
    extension_tool_pack_id="coding.extensions",
)


def _borrow_application_coding_product_factory(
    selection: CodingFencedProductApplicationSelection,
    manager: SessionManager,
    *,
    services: BootstrapServices | None,
    worker_candidates: bool = False,
) -> PackageProductRuntimeFactoryPort | None:
    factory = selection.factory_for_session(
        manager, settings_manager=None if services is None else services.settings_manager,
    )
    selected_factory: PackageProductRuntimeFactoryPort | None = factory
    if worker_candidates:
        if not isinstance(
            factory,
            (
                PosixLocalWheelProductRuntimeFactory,
                WindowsLocalWheelProductRuntimeFactory,
            ),
        ):
            error = TypeError("Coding Worker requires Product selection")
            dispose_unbound_factory_after_failure(factory, error)
            raise error
        selected_factory = CodingApplicationWorkerProductRuntimeFactory(
            factory=factory,
            selection=selection,
        )
    return selected_factory


def _build_with_package_product_selection(
    selection: CodingFencedProductApplicationSelection,
    manager: SessionManager,
    services: BootstrapServices,
    build: Callable[[PackageProductRuntimeFactoryPort | None], AgentSession],
    worker_candidates: bool = False,
) -> AgentSession:
    manager.require_no_unsettled_resume_activation()
    selected_factory = _borrow_application_coding_product_factory(
        selection, manager, services=services, worker_candidates=worker_candidates,
    )
    try:
        return build(selected_factory)
    except BaseException as error:
        dispose_unbound_factory_after_failure(selected_factory, error)
        raise


def _create_agent_session_runtime(
    *,
    session_dir: Path,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    composition_set: CodingCompositionSetPlan | None = None,
    composition_set_explicit: bool = False,
    composition_choice_from_cli: bool = False,
    services: BootstrapServices | None = None,
    services_factory: ServicesFactory | None = None,
    agent_factory: AgentFactory = Agent,
    persist: bool = True,
    worker_candidate_plugin_id: str | None = None,
    worker_query_turn_tool: bool = False,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    sandbox_workspace_writable: bool = True,
    delegated_execution_profile: DelegatedExecutionProfile | None = None,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    invocation_product_profile: CodingAgentInvocationProductProfile | None = None,
) -> AgentSessionRuntime:
    if worker_candidate_plugin_id is not None and (
        not isinstance(worker_candidate_plugin_id, str)
        or not worker_candidate_plugin_id
        or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
        or not persist
    ):
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_runtime_selection_invalid"
        )
    resolved_invocation_profile = (
        canonical_coding_agent_invocation_product_profile(invocation_product_profile)
        if invocation_product_profile is not None
        else None
    )
    if resolved_invocation_profile is not None:
        resource_catalog_source_policy = (
            resolved_invocation_profile.resource_catalog_source_policy
        )
        sandbox_workspace_writable = (
            resolved_invocation_profile.sandbox_workspace_writable
        )
    fixed_services = services if services is not None else create_services()
    fixed_lsp_definitions = tuple(lsp_definitions)
    fixed_lsp_environment = (
        dict(lsp_baseline_environment) if lsp_baseline_environment is not None else None
    )
    product_owner_selection = CodingFencedProductApplicationSelection(
        worker_candidates=worker_candidate_plugin_id is not None,
        windows_candidate=sys.platform == "win32",
    )
    resolved_composition_set = _canonical_coding_composition_set(composition_set)
    return build_agent_product_session_runtime(
        session_dir=Path(session_dir),
        runtime_factory=partial(
            AgentSessionRuntime,
            owned_transcripts=sys.platform == "linux",
            store_state_root=(
                resolve_platform_home() / "state/session-stores"
                if sys.platform == "linux"
                else None
            ),
            enroll_legacy_shared_store=(
                sys.platform == "linux"
                and Path(session_dir).expanduser().resolve(strict=False)
                == (resolve_platform_home() / "data/sessions").resolve(strict=False)
            ),
            product_owner_selection=product_owner_selection,
            materialize_new_transcript=worker_candidate_plugin_id is not None,
            new_session_header_metadata=composition_header_metadata(
                resolved_composition_set
            ),
        ),
        fixed_services=fixed_services,
        build_session=lambda session_manager, session_services, start_event: (
            _build_with_package_product_selection(
                product_owner_selection,
                cast(SessionManager, session_manager),
                session_services,
                lambda product_factory: _create_agent_session(
                    session_manager=cast(SessionManager, session_manager),
                    model=model,
                    stream_fn=stream_fn,
                    system_prompt=system_prompt,
                    thinking_level=thinking_level,
                    tools=tools,
                    tool_registry=tool_registry,
                    allowed_tool_names=allowed_tool_names,
                    active_tool_names=active_tool_names,
                    no_tools=no_tools,
                    composition_set=resolved_composition_set,
                    composition_set_explicit=composition_set_explicit,
                    composition_choice_from_cli=composition_choice_from_cli,
                    services=session_services,
                    package_product_runtime_factory=product_factory,
                    worker_candidate_plugin_id=worker_candidate_plugin_id,
                    worker_query_turn_tool=worker_query_turn_tool,
                    agent_factory=agent_factory,
                    session_start_event=cast(SessionStartEvent | None, start_event),
                    append_system_prompt=append_system_prompt,
                    approval_resolver=approval_resolver,
                    tool_policy_evaluator=tool_policy_evaluator,
                    enable_multiagent=enable_multiagent,
                    sandbox_workspace_writable=sandbox_workspace_writable,
                    delegated_execution_profile=delegated_execution_profile,
                    lsp_definitions=fixed_lsp_definitions,
                    lsp_baseline_environment=fixed_lsp_environment,
                    lsp_read_text=lsp_read_text,
                    resource_catalog_source_policy=resource_catalog_source_policy,
                    invocation_product_profile=resolved_invocation_profile,
                ),
                worker_candidates=worker_candidate_plugin_id is not None,
            )
        ),
        session_cwd=lambda manager: cast(SessionManager, manager).get_cwd(),
        services_factory=services_factory,
        persist=persist,
        diagnostics_service=fixed_services.diagnostics_service,
        on_non_persistent_session=lambda session: setattr(
            session.agent,
            "session_id",
            None,
        ),
    )


def _create_agent_invocation_session_runtime(
    *,
    session_dir: Path,
    services: BootstrapServices,
    services_factory: ServicesFactory | None,
    tool_registry: WorkspaceToolRegistry,
    allowed_tool_names: list[str] | ToolSelection | None,
    active_tool_names: list[str] | None,
    no_tools: NoToolsMode | bool | None,
    persist: bool,
    approval_resolver: InteractiveApprovalResolver | None,
    tool_policy_evaluator: PolicyEvaluator | None,
    enable_multiagent: bool,
    product_profile: CodingAgentInvocationProductProfile = (
        CODING_READ_ONLY_AGENT_INVOCATION_PRODUCT_PROFILE
    ),
) -> AgentSessionRuntime:
    """Build the Catalog-native one-shot delegate runtime."""

    resolved_profile = canonical_coding_agent_invocation_product_profile(
        product_profile
    )

    return _create_agent_session_runtime(
        session_dir=session_dir,
        composition_set=resolve_coding_composition_set(
            resolved_profile.composition_set_id
        ),
        services=services,
        services_factory=services_factory,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        persist=persist,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        invocation_product_profile=resolved_profile,
    )


def create_agent_session_runtime(
    *,
    session_dir: Path,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_registry: WorkspaceToolRegistry | None = None,
    allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
    active_tool_names: list[str] | None = None,
    no_tools: NoToolsMode | bool | None = None,
    composition_set: CodingCompositionSetId | None = None,
    composition_set_explicit: bool | None = None,
    composition_choice_from_cli: bool = False,
    services: BootstrapServices | None = None,
    services_factory: ServicesFactory | None = None,
    agent_factory: AgentFactory = Agent,
    persist: bool = True,
    worker_candidate_plugin_id: str | None = None,
    worker_query_turn_tool: bool = False,
    append_system_prompt: list[str] | tuple[str, ...] | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    enable_multiagent: bool = False,
    lsp_definitions: Iterable[LspServerDefinition] = (),
    lsp_baseline_environment: Mapping[str, str] | None = None,
    lsp_read_text: WorkspaceTextReader | None = None,
) -> AgentSessionRuntime:
    return _create_agent_session_runtime(
        session_dir=session_dir,
        model=model,
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        active_tool_names=active_tool_names,
        no_tools=no_tools,
        composition_set=resolve_coding_composition_set(
            "coding-standard" if composition_set is None else composition_set
        ),
        composition_set_explicit=(
            composition_set is not None
            if composition_set_explicit is None
            else composition_set_explicit
        ),
        composition_choice_from_cli=composition_choice_from_cli,
        services=services,
        services_factory=services_factory,
        agent_factory=agent_factory,
        persist=persist,
        worker_candidate_plugin_id=worker_candidate_plugin_id,
        worker_query_turn_tool=worker_query_turn_tool,
        append_system_prompt=append_system_prompt,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        enable_multiagent=enable_multiagent,
        sandbox_workspace_writable=True,
        lsp_definitions=lsp_definitions,
        lsp_baseline_environment=lsp_baseline_environment,
        lsp_read_text=lsp_read_text,
    )


# Component entry names borrow the existing operations and retain old identities.
create_agent_session_services_with_catalog_policy = _create_agent_session_services
create_agent_session_with_model_policy = _create_agent_session_with_model_policy
create_agent_session_runtime_with_product_policy = _create_agent_session_runtime
create_agent_invocation_session_runtime = _create_agent_invocation_session_runtime
create_resume_agent_session = _create_resume_agent_session
coding_capability_plugin_state_root = _coding_capability_plugin_state_root
