from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loushang.agent import Agent, PrepareModelCallFn
from loushang.ai import Context, PreparedRequestLimits
from loushang.ai.api_registry import APIRegistry
from loushang.ai.types import Tool, UserMessage
from loushang.coding._base_plugin import (
    CodingBasePluginAssembly,
    CodingBasePluginAssemblyError,
    CodingBasePluginSessionAssembly,
    build_coding_base_plugin_owners,
)
from loushang.coding._base_plugin_owners import CodingBaseToolRegistrationSlot
from loushang.coding._base_product_composition import (
    CodingBaseProductSessionAssembly,
)
from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionError,
)
from loushang.coding._external_data_product_composition import (
    CodingExternalDataProductCompilation,
)
from loushang.coding._tool_authority import CODING_LSP_EXACT_OWNER_TOOL_NAMES
from loushang.coding._worker_tool_identity import CODING_WORKER_QUERY_TOOL_NAME
from loushang.coding.arch._plugin_tool_owner import (
    CodingArchToolOwner,
    CodingArchToolRegistrationSlot,
)
from loushang.coding.compaction.adapter import (
    coding_single_call_capacity_pressure,
    execute_coding_branch_summary,
)
from loushang.coding.compaction.adapter import (
    execute_coding_compaction as _execute_coding_compaction,
)
from loushang.coding.composition_provenance import (
    CODING_COMPOSITION_STARTUP_TYPE,
    historical_composition_provenance,
    historical_startup_composition_record,
)
from loushang.coding.composition_sets import CodingCompositionSetPlan
from loushang.coding.lsp._deferred_generation import (
    CodingDeferredLspGeneration,
    dormant_lsp_tool_infos,
)
from loushang.coding.lsp._plugin_opt_in import CodingLspPluginOptInAssembly
from loushang.coding.lsp._plugin_tool_owner import (
    CodingLspToolOwner,
    CodingLspToolRegistrationSlot,
)
from loushang.coding.lsp._provider_api import (
    CODING_LSP_SESSION_REQUIREMENT,
    CodingLspSessionCapabilityConsumer,
)
from loushang.coding.lsp.commands import (
    LSP_SESSION_COMMAND_NAME,
    execute_lsp_session_command,
    lsp_session_command_descriptor,
)
from loushang.coding.lsp.runtime import CodingLspSessionAccess
from loushang.coding.lsp.status import LspSessionStatus, disabled_lsp_session_status
from loushang.coding.package_product_runtime import CodingProductWorkspaceWitnessV1
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE, CODING_PRODUCT_ID
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import summarize_coding_package_root
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
)
from loushang.coding.resume_activation_attempt_v2 import CodingActivationAttemptV2
from loushang.coding.resume_binding import coding_user_input_digest
from loushang.coding.runtime_capability_admission import (
    CodingExtensionDeclarationPreflight,
    resolve_coding_capability_profile,
)
from loushang.coding.session_manager import SessionManager
from loushang.coding.tool_pack import (
    CODING_BUILTIN_TOOL_NAMES,
    coding_default_active_tool_names,
    coding_platform_tool_names,
)
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.capabilities import (
    CapabilityBundleProviderBinding,
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
)
from loushang.harness.capabilities.deferred_slot import DeferredCapabilitySlot
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.tool_intent import DefaultToolProfileSnapshot
from loushang.harness.capabilities.tools import ToolSelection
from loushang.harness.commands import normalize_command_name
from loushang.harness.config.agent import SettingsManager
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.environment import LocalHostEnvironmentProbe
from loushang.harness.events import RuntimeEvent
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import SessionStartEvent
from loushang.harness.model_catalog import ModelCatalog as ModelRegistry
from loushang.harness.multiagent import DelegatedExecutionProfile
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductPluginDesiredSelectionV1,
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resources._catalog_records import (
    ResourceCatalogSnapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleInventoryPort,
    PackageProductLifecycleMode,
    PackageProductLifecycleOperationPort,
)
from loushang.harness.resources.packages.roots import SelectedPluginPackageInput
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.sandbox import SandboxExecutionRuntime, SandboxStatus
from loushang.harness.session import AgentProductSession as AgentProductSession
from loushang.harness.session._cleanup import run_cleanup_steps
from loushang.harness.session._resume_continuation import (
    _ResumeContinuationSession,
    _ResumeRuntimeCandidate,
)
from loushang.harness.session.bash import UserBashHookResult, UserBashRequest
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityOwnerGenerationBinding,
)
from loushang.harness.session.changelog import read_changelog_for_cwd
from loushang.harness.session.command_controller import (
    SessionCommandGenerationRegistry,
)
from loushang.harness.session.composition import sleep_for_retry
from loushang.harness.session.cwd_audit import CwdBoundServicesAudit
from loushang.harness.session.event_types import AgentSessionEvent
from loushang.harness.session.footer import FooterDataProvider
from loushang.harness.session.legacy_side_question import (
    LegacySideQuestionBinding,
    bind_legacy_side_question,
)
from loushang.harness.session.model_call import SessionModelCallCapabilityConsumer
from loushang.harness.session.plugin_lifecycle._publication import (
    OwnerContributions,
    _owner_set_publication,
    _OwnerPublicationHooks,
    _single_owner_publication,
)
from loushang.harness.session.resource_refresh_gate import (
    ResourceCatalogRefreshGatePort,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionPreparation,
    CompactionResult,
)
from loushang.harness.transcript.kinds import (
    MODEL_SELECTION_KIND,
    THINKING_SELECTION_KIND,
)
from loushang.harness.workspace.exec import ExecResult, ExecService, ExecUpdateCallback
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

if TYPE_CHECKING:
    from loushang.coding.package_product_worker_session_composition import (
        CodingProductWorkerOrdinarySessionBinding,
    )
    from loushang.coding.package_product_worker_turn_tool import (
        CodingWorkerTurnToolBinding,
    )

SessionEventListener = Callable[[AgentSessionEvent], Awaitable[None] | None]
# project_runtime_event_to_session_event remains an external migration label.
RuntimeEventListener = Callable[[RuntimeEvent[object]], Awaitable[None] | None]


class _DormantLspSessionAccess:
    def status(self) -> LspSessionStatus:
        return LspSessionStatus(enabled=True)

    async def stop(self, *, definition_id: str, workspace_root: str | Path) -> bool:
        del definition_id, workspace_root
        return False


_DORMANT_LSP_ACCESS = _DormantLspSessionAccess()


def _copy_to_clipboard(text: str) -> object:
    from loushang.tui.clipboard import copy_to_clipboard

    return copy_to_clipboard(text)


async def _execute_coding_compaction_runtime(
    *,
    preparation: CompactionPreparation,
    model: object,
    headers: Mapping[str, str] | None,
    signal: object | None,
    custom_instructions: str | None = None,
    prepare_model_call: PrepareModelCallFn | None = None,
    request_limits: PreparedRequestLimits | None = None,
    settings_manager: SettingsManager | None = None,
    agent: Agent | None = None,
) -> CompactionResult:
    strategy = (
        settings_manager.get_compaction_settings().strategy
        if settings_manager is not None
        else "local_separate"
    )
    provider_context = None
    if strategy == "provider":
        if agent is None:
            raise RuntimeError("Provider compaction requires an Agent context")
        provider_context = Context(
            system_prompt=agent.state.system_prompt,
            tools=[
                Tool(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
                for tool in agent.state.tools
            ],
            provider_window=agent.state.provider_window,
        )
    return await _execute_coding_compaction(
        preparation=preparation,
        model=model,
        headers=headers,
        signal=signal,
        custom_instructions=custom_instructions,
        prepare_model_call=prepare_model_call,
        request_limits=request_limits,
        strategy=strategy,
        provider_context=provider_context,
    )


def _coding_single_call_capacity_probe(
    preparation: CompactionPreparation,
    model: object,
    request_limits: PreparedRequestLimits | None,
    *,
    settings_manager: SettingsManager | None,
) -> bool:
    return bool(
        settings_manager is not None
        and settings_manager.get_compaction_settings().strategy == "local_combined"
        and coding_single_call_capacity_pressure(preparation, model, request_limits)
    )


async def _execute_coding_branch_summary(
    entries: Sequence[object],
    *,
    model: object,
    signal: object | None,
    custom_instructions: str | None = None,
    replace_instructions: bool = False,
    prepare_model_call: PrepareModelCallFn | None = None,
) -> BranchSummaryOutput:
    return await execute_coding_branch_summary(
        entries,
        model=model,
        signal=signal,
        custom_instructions=custom_instructions,
        replace_instructions=replace_instructions,
        prepare_model_call=prepare_model_call,
    )


@dataclass(frozen=True, slots=True)
class _CodingResumeRuntimeCandidate:
    attempt: CodingActivationAttemptV1
    consumer: object
    graph_generation: int
    receipt_fingerprint: str


@dataclass(frozen=True, slots=True)
class _CodingResumeRuntimePublication:
    candidate: _CodingResumeRuntimeCandidate
    input_record_id: str
    current_admission: Callable[[CodingActivationAttemptV1], None]
    current_epoch_settlement: Callable[
        [CodingActivationAttemptV1, Mapping[str, object]], None
    ]


class AgentSession(_ResumeContinuationSession[CodingActivationAttemptV1]):
    """Coding content and policy bound to the shared Agent Product session."""

    _coding_session_manager: SessionManager
    _coding_lsp_plugin_assembly: CodingCapabilityPluginCompositionAssembly | None
    _lsp_access: CodingLspSessionAccess | None
    _deferred_lsp_slot: DeferredCapabilitySlot[CodingDeferredLspGeneration] | None
    _deferred_lsp_management_cleanup: Callable[[], None] | None

    @property
    def execution_available(self) -> bool:
        return (
            super().execution_available
            and not self._coding_session_manager.resume_runtime_publication_pending
        )

    def _require_coding_execution_admission(self) -> None:
        self._coding_session_manager.require_no_unsettled_resume_activation()
        publication = getattr(self, "_resume_publication", None)
        if publication is not None:
            self._require_current_resume_publication(publication)

    def _is_current_model_call_session(self) -> bool:
        if not super()._is_current_model_call_session():
            return False
        publication = getattr(self, "_resume_publication", None)
        if publication is not None:
            self._require_current_resume_publication(publication)
        return True

    async def _before_bash(self, request: UserBashRequest) -> UserBashHookResult | None:
        self._require_coding_execution_admission()
        return await super()._before_bash(request)

    async def compact(self, custom_instructions: str | None = None) -> object:
        self._require_coding_execution_admission()
        return await super().compact(custom_instructions)

    async def _exec_command_from_extension(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
        preview_max_lines: int = 2000,
        preview_max_bytes: int = 50 * 1024,
        artifact_dir: str | None = None,
        capture_full_output: bool = True,
        rolling_max_bytes: int = 100 * 1024,
    ) -> ExecResult:
        self._require_coding_execution_admission()
        return await super()._exec_command_from_extension(
            command,
            args,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            signal=signal,
            on_update=on_update,
            preview_max_lines=preview_max_lines,
            preview_max_bytes=preview_max_bytes,
            artifact_dir=artifact_dir,
            capture_full_output=capture_full_output,
            rolling_max_bytes=rolling_max_bytes,
        )

    @staticmethod
    def _reject_peer_worker_tool(tool: object) -> None:
        if (
            isinstance(tool, ToolDefinition)
            and tool.name == CODING_WORKER_QUERY_TOOL_NAME
        ):
            raise ValueError(
                "Coding Worker query Tool is reserved for the Product owner"
            )

    def register_runtime_tools(
        self,
        tools: Iterable[object],
        *,
        activate: bool = False,
        source_info: object | None = None,
    ) -> tuple[ToolDefinition, ...]:
        definitions = tuple(tools)
        for definition in definitions:
            self._reject_peer_worker_tool(definition)
        return super().register_runtime_tools(
            definitions, activate=activate, source_info=source_info
        )

    async def set_active_tools(self, tool_names: list[str]) -> None:
        slot = self._deferred_lsp_slot
        requested_lsp = set(tool_names).intersection(CODING_LSP_EXACT_OWNER_TOOL_NAMES)
        if slot is not None and requested_lsp:
            if any(
                not self._composition.tool_controller.is_tool_allowed(name)
                for name in requested_lsp
            ):
                raise ValueError("LSP Tool is not allowed in this Session")
            await self.prepare_model_call_runtime()
            generation = await slot.activate(retry=slot.state == "failed")
            self._lsp_access = generation.access
        await super().set_active_tools(tool_names)

    def get_all_tool_infos(self) -> list[dict[str, object]]:
        infos = super().get_all_tool_infos()
        slot = self._deferred_lsp_slot
        if slot is None or slot.active is not None:
            return infos
        known = {item.get("name") for item in infos}
        return [
            *infos,
            *(
                item
                for item in dormant_lsp_tool_infos()
                if item["name"] not in known
                and self._composition.tool_controller.is_tool_allowed(str(item["name"]))
            ),
        ]

    def install_deferred_lsp_slot(
        self,
        slot: DeferredCapabilitySlot[CodingDeferredLspGeneration],
        *,
        management_cleanup: Callable[[], None] | None = None,
    ) -> None:
        if self._deferred_lsp_slot is not None or self._coding_lsp_plugin_assembly:
            raise RuntimeError("Coding LSP already has an owner")
        if slot.declaration.capability_id != "coding.lsp":
            raise ValueError("deferred slot does not declare Coding LSP")
        self._deferred_lsp_slot = slot
        self._deferred_lsp_management_cleanup = management_cleanup

    def _register_extension_runtime_tool(
        self, tool: object, source_info: object | None = None
    ) -> None:
        self._reject_peer_worker_tool(tool)
        super()._register_extension_runtime_tool(tool, source_info)

    def _bind_extension_runtime_tool(
        self,
        tool: object,
        owner: RegistrationOwner | str,
        source_info: object | None = None,
    ) -> RegistrationLease:
        self._reject_peer_worker_tool(tool)
        return super()._bind_extension_runtime_tool(tool, owner, source_info)

    def _adopt_extension_runtime_tool(
        self,
        tool: object,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease | None:
        self._reject_peer_worker_tool(tool)
        return super()._adopt_extension_runtime_tool(tool, owner, source_info)

    def _stage_extension_runtime_tool(
        self,
        tool: object,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease:
        self._reject_peer_worker_tool(tool)
        return super()._stage_extension_runtime_tool(tool, owner, source_info)

    def __init__(
        self,
        *,
        agent: Agent,
        session_manager: SessionManager,
        settings_manager: SettingsManager | None = None,
        model_registry: ModelRegistry | None = None,
        resource_loader: ResourceLoader | None = None,
        resource_bundle: ResourceBundle | None = None,
        extension_runner: ExtensionRunner | None = None,
        tool_registry: WorkspaceToolRegistry | None = None,
        allowed_tool_names: list[str] | ToolSelection | None = ToolSelection.ALL,
        active_tool_names: list[str] | None = None,
        default_activate_new_tools: bool | None = None,
        show_empty_tool_prompt: bool = False,
        base_prompt: str | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        package_materializer: PackageMaterializer | None = None,
        package_product_lifecycle: PackageProductLifecycleOperationPort | None = None,
        package_product_inventory: PackageProductLifecycleInventoryPort | None = None,
        package_product_lifecycle_mode: PackageProductLifecycleMode = "legacy",
        session_start_event: SessionStartEvent | None = None,
        api_registry: APIRegistry | None = None,
        footer_data_provider: FooterDataProvider | None = None,
        exec_service: ExecService | None = None,
        output_capture_factory: ExecCaptureFactory | None = None,
        approval_resolver: InteractiveApprovalResolver | None = None,
        tool_policy_evaluator: PolicyEvaluator | None = None,
        capability_runtime: StagedResourceCompositionCandidate | None = None,
        side_question_binding: LegacySideQuestionBinding | None = None,
        sandbox_runtime: SandboxExecutionRuntime | None = None,
        coding_capability_plugin_assembly: (
            CodingCapabilityPluginCompositionAssembly | None
        ) = None,
        coding_lsp_plugin_assembly: (
            CodingLspPluginOptInAssembly
            | CodingCapabilityPluginCompositionAssembly
            | None
        ) = None,
        coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
        coding_base_plugin_session_assembly: (
            CodingBasePluginSessionAssembly | None
        ) = None,
        coding_base_product_session_assembly: (
            CodingBaseProductSessionAssembly | None
        ) = None,
        coding_external_data_product_compilation: (
            CodingExternalDataProductCompilation | None
        ) = None,
        coding_selected_capability_manifests: tuple[
            PackageProductSelectedPluginManifestV1, ...
        ] = (),
        coding_base_product_runtime_binding: (
            PackageProductRuntimeBindingV1 | None
        ) = None,
        coding_product_desired_selections: tuple[
            PackageProductPluginDesiredSelectionV1, ...
        ] = (),
        coding_product_workspace_witness: (
            CodingProductWorkspaceWitnessV1 | None
        ) = None,
        coding_plugin_clock: Callable[[], int] | None = None,
        delegated_execution_profile: DelegatedExecutionProfile | None = None,
        workspace_capability_binding: CapabilityBundleProviderBinding | None = None,
        coding_product_worker_ordinary_binding: (
            CodingProductWorkerOrdinarySessionBinding | None
        ) = None,
        coding_worker_turn_tool: CodingWorkerTurnToolBinding | None = None,
        coding_composition_plan: CodingCompositionSetPlan | None = None,
        initial_resource_catalog_bootstrap: Any | None = None,
        resource_catalog_refresh_bootstrap_factory: Any | None = None,
        resource_catalog_refresh_lock: ResourceCatalogRefreshGatePort | None = None,
    ) -> None:
        if (
            coding_capability_plugin_assembly is not None
            and coding_lsp_plugin_assembly is not None
        ):
            raise ValueError("Coding Capability Plugin assembly was supplied twice")
        capability_plugin_assembly = coding_capability_plugin_assembly or (
            (
                coding_lsp_plugin_assembly.capability_assembly
                if isinstance(
                    coding_lsp_plugin_assembly,
                    CodingLspPluginOptInAssembly,
                )
                else coding_lsp_plugin_assembly
            )
            if coding_lsp_plugin_assembly is not None
            else None
        )
        if capability_plugin_assembly is not None and not isinstance(
            capability_plugin_assembly,
            CodingCapabilityPluginCompositionAssembly,
        ):
            raise TypeError("Coding Capability Plugin assembly is invalid")
        if coding_base_plugin_assembly is not None and not isinstance(
            coding_base_plugin_assembly,
            CodingBasePluginAssembly,
        ):
            raise TypeError("Coding base Plugin assembly is invalid")
        if coding_base_plugin_session_assembly is not None and not isinstance(
            coding_base_plugin_session_assembly,
            CodingBasePluginSessionAssembly,
        ):
            raise TypeError("Coding base Plugin Session assembly is invalid")
        if coding_base_product_session_assembly is not None and not isinstance(
            coding_base_product_session_assembly,
            CodingBaseProductSessionAssembly,
        ):
            raise TypeError("Coding base Product Session assembly is invalid")
        if coding_base_product_session_assembly is not None and any(
            (
                coding_base_plugin_assembly,
                coding_base_plugin_session_assembly,
            )
        ):
            raise ValueError("Coding base Product cannot mix Plugin session routes")
        if coding_product_worker_ordinary_binding is not None:
            from loushang.coding.package_product_worker_session_composition import (
                CodingProductWorkerOrdinarySessionBinding,
                validate_coding_product_worker_ordinary_session_inputs,
            )

            if (
                not isinstance(
                    coding_product_worker_ordinary_binding,
                    CodingProductWorkerOrdinarySessionBinding,
                )
                or coding_base_product_session_assembly is None
                or coding_product_worker_ordinary_binding.ordinary
                is not coding_base_product_session_assembly.session_inputs
                or workspace_capability_binding
                is not coding_base_product_session_assembly.workspace_binding
                or coding_product_worker_ordinary_binding.workspace_binding
                is not workspace_capability_binding
            ):
                raise ValueError("Coding Product Worker ordinary Session changed")
            validate_coding_product_worker_ordinary_session_inputs(
                ordinary=coding_product_worker_ordinary_binding.ordinary,
                combined=coding_product_worker_ordinary_binding.combined,
                workspace_binding=workspace_capability_binding,
            )
        if coding_worker_turn_tool is not None and (
            coding_product_worker_ordinary_binding is None
            or coding_product_worker_ordinary_binding.activation_receipt is None
        ):
            raise ValueError(
                "Coding Worker turn Tool requires a selected Worker receipt"
            )
        if (
            coding_base_product_session_assembly is not None
            and capability_plugin_assembly is not None
            and (
                capability_plugin_assembly.session_inputs
                is not coding_base_product_session_assembly.session_inputs
                or capability_plugin_assembly.selection.plan
                != coding_base_product_session_assembly.compilation.plan
                or capability_plugin_assembly.plugin_assembly.product_composition
                is not coding_base_product_session_assembly.compilation.product_composition
            )
        ):
            raise ValueError("Coding Product Session composition changed")
        if (
            coding_base_product_session_assembly is not None
            and capability_plugin_assembly is not None
        ):
            compilation = coding_base_product_session_assembly.compilation
            selected = (
                compilation.selected_manifest,
                *compilation.selected_capability_manifests,
                *compilation.selected_external_data_manifests,
            )
            packages = capability_plugin_assembly.runtime.packages
            if tuple(package.manifest.name for package in packages) != tuple(
                sorted(item.manifest.name for item in selected)
            ) or {
                package.manifest.name: package.content_digest for package in packages
            } != {
                item.manifest.name: item.snapshot.root_ref.artifact_digest
                for item in selected
            }:
                raise ValueError("Coding Product Session packages changed")
        elif capability_plugin_assembly is not None and (
            coding_base_product_runtime_binding is not None
            or coding_selected_capability_manifests
        ):
            # Compare the Product-selected Capability set when this route has
            # Product evidence, including an empty set. Legacy management
            # leases have a separate owner and no Product selection to compare.
            # Resource-only Wheels are checked by their Catalog owner.
            selected = coding_selected_capability_manifests
            packages = capability_plugin_assembly.runtime.packages
            if len(packages) != len(selected) or {
                package.manifest.name: package.content_digest for package in packages
            } != {
                item.manifest.name: item.snapshot.root_ref.artifact_digest
                for item in selected
            }:
                raise ValueError("Coding Product Session packages changed")
        if coding_base_product_session_assembly is not None:
            if package_materializer is not None:
                raise ValueError("Coding base Product cannot use a peer materializer")
            if initial_resource_catalog_bootstrap is None:
                raise ValueError("Coding base Product requires Catalog bootstrap")
            if (
                workspace_capability_binding
                is not coding_base_product_session_assembly.workspace_binding
            ):
                raise ValueError("Coding base Product workspace binding changed")
            if coding_base_product_runtime_binding is None:
                raise ValueError("Coding base Product requires runtime binding")
            if (
                coding_base_product_session_assembly.compilation.plan.context.scope_id
                != f"session:{session_manager.get_header().conversation_id}"
            ):
                raise ValueError("Coding base Product Session identity changed")
        if coding_base_product_runtime_binding is not None and (
            not isinstance(
                coding_base_product_runtime_binding, PackageProductRuntimeBindingV1
            )
            or coding_base_product_runtime_binding.product_id != CODING_PRODUCT_ID
        ):
            raise ValueError("Coding Product runtime binding is invalid")
        if coding_product_workspace_witness is not None and (
            not isinstance(
                coding_product_workspace_witness, CodingProductWorkspaceWitnessV1
            )
            or coding_product_workspace_witness.session_id
            != session_manager.get_header().conversation_id
        ):
            raise ValueError("Coding Product workspace witness changed Session")
        if coding_product_workspace_witness is not None:
            coding_product_workspace_witness.assert_current()
        if coding_base_plugin_assembly is not None and (
            capability_plugin_assembly is None
            and coding_base_plugin_session_assembly is None
        ):
            raise ValueError("Coding base Plugin requires one Session composition")
        if coding_plugin_clock is not None and not callable(coding_plugin_clock):
            raise TypeError("Coding Plugin clock is invalid")
        self._sandbox_runtime = sandbox_runtime
        self._lsp_access = None
        self._deferred_lsp_slot = None
        self._deferred_lsp_management_cleanup = None
        self._coding_capability_plugin_assembly = capability_plugin_assembly
        lsp_tool_owner = (
            capability_plugin_assembly.tool_owner_for("coding.lsp.default")
            if capability_plugin_assembly is not None
            else None
        )
        if lsp_tool_owner is not None and not isinstance(
            lsp_tool_owner, CodingLspToolOwner
        ):
            raise TypeError("Coding LSP Plugin selected an invalid Tool owner")
        arch_tool_owner = (
            capability_plugin_assembly.tool_owner_for("coding.arch.default")
            if capability_plugin_assembly is not None
            else None
        )
        if arch_tool_owner is not None and not isinstance(
            arch_tool_owner, CodingArchToolOwner
        ):
            raise TypeError("Coding Arch Plugin selected an invalid Tool owner")
        self._coding_lsp_plugin_assembly = (
            capability_plugin_assembly if lsp_tool_owner is not None else None
        )
        self._coding_base_plugin_assembly = coding_base_plugin_assembly
        self._coding_base_product_runtime_binding = coding_base_product_runtime_binding
        self._coding_product_worker_ordinary_binding = (
            coding_product_worker_ordinary_binding
        )
        self._coding_worker_turn_tool_lease: RegistrationLease | None = None
        self._coding_product_desired_selections = coding_product_desired_selections
        self._coding_product_desired_preflight_completed = False
        self.coding_product_workspace_witness = coding_product_workspace_witness
        product_base = (
            coding_base_product_session_assembly.compilation
            if coding_base_product_session_assembly is not None
            else None
        )
        self._coding_base_product_compilation = product_base
        self._coding_session_manager = session_manager
        self._coding_external_data_product_compilation = (
            coding_external_data_product_compilation
        )
        self._coding_selected_capability_manifests = (
            coding_selected_capability_manifests
        )
        self._coding_composition_plan = coding_composition_plan
        self._coding_composition_record_lock = asyncio.Lock()
        self._init_resume_runtime_state()
        # A model can be saved before the session has prepared its first input.
        self._coding_composition_had_entries_at_construction = any(
            entry.kind not in {MODEL_SELECTION_KIND, THINKING_SELECTION_KIND}
            for entry in session_manager.get_entries()
        )
        owner_publication_hooks = self._create_coding_owner_publication_bindings()
        self._coding_lsp_plugin_capture: CapabilityFacetSet | None = None
        self.delegated_execution_profile = delegated_execution_profile
        self.cwd_bound_services_audit: CwdBoundServicesAudit | None = None
        resolved_capability_runtime = capability_runtime
        locally_created_capability_runtime: (
            StagedResourceCompositionCandidate | None
        ) = None
        locally_created_side_question_binding: LegacySideQuestionBinding | None = None
        lsp_tool_registration_slot: CodingLspToolRegistrationSlot | None = None
        arch_tool_registration_slot: CodingArchToolRegistrationSlot | None = None
        owner_bindings: tuple[SessionCapabilityOwnerGenerationBinding, ...] = ()
        base_tool_registration_slot: CodingBaseToolRegistrationSlot | None = None
        # Catalog-owned Sessions must never fall back to the historical
        # unconditional standard-command publisher.  An empty registry is the
        # explicit Product selection when ``coding.base`` is absent; the base
        # owner stages its exact command generation into the same registry.
        command_generations = (
            SessionCommandGenerationRegistry()
            if initial_resource_catalog_bootstrap is not None
            else None
        )
        plugin_assembly = (
            capability_plugin_assembly.plugin_assembly
            if capability_plugin_assembly is not None
            else (
                coding_base_plugin_session_assembly.plugin_assembly
                if coding_base_plugin_session_assembly is not None
                else None
            )
        )
        if coding_base_plugin_assembly is not None or product_base is not None:
            if coding_plugin_clock is None or (
                product_base is None and plugin_assembly is None
            ):
                raise ValueError("Coding base owner inputs are unavailable")
            if product_base is not None:
                base_host_environment = product_base.host_environment
            else:
                assert coding_base_plugin_assembly is not None
                base_host_environment = coding_base_plugin_assembly.host_environment
            if command_generations is None:
                command_generations = SessionCommandGenerationRegistry()
            get_external_tool_policy = getattr(
                settings_manager,
                "get_external_tool_policy",
                None,
            )
            get_shell_path = getattr(settings_manager, "get_shell_path", None)
            get_shell_command_prefix = getattr(
                settings_manager,
                "get_shell_command_prefix",
                None,
            )
            tool_options = ToolsOptions(
                diagnostics_service=diagnostics_service,
                external_tool_policy=(
                    get_external_tool_policy()
                    if callable(get_external_tool_policy)
                    else None
                ),
                host_environment=base_host_environment,
                shell_path=(get_shell_path() if callable(get_shell_path) else None),
                command_prefix=(
                    get_shell_command_prefix()
                    if callable(get_shell_command_prefix)
                    else None
                ),
            )
            if product_base is not None:
                base_owners = product_base.build_owners(
                    clock=coding_plugin_clock,
                    tool_options=tool_options,
                )
            else:
                assert coding_base_plugin_assembly is not None
                assert plugin_assembly is not None
                base_owners = build_coding_base_plugin_owners(
                    coding_base_plugin_assembly,
                    plugin_assembly,
                    clock=coding_plugin_clock,
                    tool_options=tool_options,
                )
            if base_owners.tool is not None:
                base_tool_registration_slot = CodingBaseToolRegistrationSlot()
                owner_bindings = (base_owners.tool.bind(base_tool_registration_slot),)
            if base_owners.command is not None:
                owner_bindings = (
                    *owner_bindings,
                    base_owners.command.bind(command_generations),
                )
        if lsp_tool_owner is not None:
            lsp_tool_registration_slot = CodingLspToolRegistrationSlot()
            owner_bindings = (
                *owner_bindings,
                lsp_tool_owner.bind(lsp_tool_registration_slot),
            )
        if arch_tool_owner is not None:
            arch_tool_registration_slot = CodingArchToolRegistrationSlot()
            owner_bindings = (
                *owner_bindings,
                arch_tool_owner.bind(arch_tool_registration_slot),
            )
        resolution = None
        if extension_runner is not None and (
            resolved_capability_runtime is None or side_question_binding is None
        ):
            resolution = resolve_coding_capability_profile(
                extension_runner.active_extensions
            )
        if resolved_capability_runtime is None:
            if resolution is not None:
                resolved_capability_runtime = resolution.bind()
            else:
                resolved_capability_runtime = stage_resource_composition_candidate(
                    CODING_CAPABILITY_PROFILE
                )
            locally_created_capability_runtime = resolved_capability_runtime
        elif resolution is not None:
            resolved_capability_runtime.select_final_profile(resolution.profile)
        host_environment = (
            product_base.host_environment
            if product_base is not None
            else coding_base_plugin_assembly.host_environment
            if coding_base_plugin_assembly is not None
            else LocalHostEnvironmentProbe().detect()
        )
        selected_base_tool_names = (
            set(product_base.tool_names)
            if product_base is not None
            else set(coding_base_plugin_assembly.tool_names)
            if coding_base_plugin_assembly is not None
            else set(coding_default_active_tool_names(host_environment))
        )
        coding_default_profile = DefaultToolProfileSnapshot(
            profile_id="coding.tools.default",
            profile_revision=0,
            static_default_names=tuple(
                name
                for name in coding_default_active_tool_names(host_environment)
                if name in selected_base_tool_names
            ),
            automatic_selection_policy_fingerprint="coding.tools.legacy-auto.v1",
            automatic_selection_enabled=(
                active_tool_names is None
                if default_activate_new_tools is None
                else default_activate_new_tools
            ),
            automatic_selection_excluded_names=coding_platform_tool_names(
                CODING_BUILTIN_TOOL_NAMES,
                host_environment,
            ),
        )
        try:
            if side_question_binding is None:
                side_question_binding = (
                    resolution.bind_side_question()
                    if resolution is not None
                    else bind_legacy_side_question(resolved_capability_runtime.profile)
                )
                locally_created_side_question_binding = side_question_binding
            super().__init__(
                agent=agent,
                session_manager=session_manager,
                capability_runtime=resolved_capability_runtime,
                side_question_binding=side_question_binding,
                execute_compaction=partial(
                    _execute_coding_compaction_runtime,
                    settings_manager=settings_manager,
                    agent=agent,
                ),
                single_call_capacity_probe=partial(
                    _coding_single_call_capacity_probe,
                    settings_manager=settings_manager,
                ),
                execute_branch_summary=_execute_coding_branch_summary,
                get_changelog=read_changelog_for_cwd,
                copy_to_clipboard=_copy_to_clipboard,
                retry_sleep=lambda delay, signal: sleep_for_retry(delay, signal),
                footer_data_provider=footer_data_provider
                or FooterDataProvider(session_manager.get_cwd()),
                package_summary_provider=summarize_coding_package_root,
                settings_manager=settings_manager,
                model_registry=model_registry,
                resource_loader=resource_loader,
                resource_bundle=resource_bundle,
                extension_runner=extension_runner,
                tool_registry=tool_registry,
                allowed_tool_names=allowed_tool_names,
                active_tool_names=active_tool_names,
                default_activate_new_tools=default_activate_new_tools,
                default_tool_profile=coding_default_profile,
                show_empty_tool_prompt=show_empty_tool_prompt,
                base_prompt=base_prompt,
                diagnostics_service=diagnostics_service,
                package_materializer=package_materializer,
                package_product_lifecycle=package_product_lifecycle,
                package_product_inventory=package_product_inventory,
                package_product_lifecycle_mode=package_product_lifecycle_mode,
                selected_plugin_packages=(
                    (
                        SelectedPluginPackageInput(
                            package=coding_base_plugin_assembly.package,
                            binding=coding_base_plugin_assembly.binding,
                        ),
                    )
                    if coding_base_plugin_assembly is not None
                    else ()
                ),
                session_start_event=session_start_event,
                api_registry=api_registry,
                exec_service=exec_service,
                output_capture_factory=output_capture_factory,
                tool_exec_service=(
                    None
                    if (
                        coding_base_plugin_session_assembly is not None
                        or coding_base_product_session_assembly is not None
                    )
                    else (
                        exec_service
                        if (
                            sandbox_runtime is not None
                            and sandbox_runtime.status().state != "disabled"
                        )
                        or getattr(exec_service, "execution_profile", None) is not None
                        else None
                    )
                ),
                approval_resolver=approval_resolver,
                tool_policy_evaluator=tool_policy_evaluator,
                workspace_capability_binding=workspace_capability_binding,
                capability_composition_inputs=(
                    coding_product_worker_ordinary_binding.combined
                    if coding_product_worker_ordinary_binding is not None
                    else (
                        capability_plugin_assembly.session_inputs
                        if capability_plugin_assembly is not None
                        else (
                            coding_base_plugin_session_assembly.session_inputs
                            if coding_base_plugin_session_assembly is not None
                            else (
                                coding_base_product_session_assembly.session_inputs
                                if coding_base_product_session_assembly is not None
                                else None
                            )
                        )
                    )
                ),
                capability_component_host=(
                    capability_plugin_assembly.component_host
                    if capability_plugin_assembly is not None
                    else None
                ),
                capability_owner_generation_bindings=owner_bindings,
                owner_publication_hooks=owner_publication_hooks,
                command_generation_registry=command_generations,
                initial_resource_catalog_bootstrap=(initial_resource_catalog_bootstrap),
                resource_catalog_refresh_bootstrap_factory=(
                    resource_catalog_refresh_bootstrap_factory
                ),
                resource_catalog_refresh_lock=resource_catalog_refresh_lock,
                extension_declaration_preflight=(
                    CodingExtensionDeclarationPreflight(
                        baseline_profile=resolved_capability_runtime.profile
                    )
                    if extension_runner is not None
                    else None
                ),
            )
            if lsp_tool_registration_slot is not None:
                lsp_tool_registration_slot.bind(self._composition.tool_controller)
            if arch_tool_registration_slot is not None:
                arch_tool_registration_slot.bind(self._composition.tool_controller)
            if base_tool_registration_slot is not None:
                base_tool_registration_slot.bind(self._composition.tool_controller)
            if coding_worker_turn_tool is not None:
                assert coding_product_worker_ordinary_binding is not None
                receipt = coding_product_worker_ordinary_binding.activation_receipt
                assert receipt is not None
                self._coding_worker_turn_tool_lease = (
                    self._composition.tool_controller.stage_runtime_tool(
                        coding_worker_turn_tool.definition(),
                        owner=RegistrationOwner(
                            owner_kind="product",
                            owner_id="coding",
                            runtime_id=(
                                f"{session_manager.get_header().conversation_id}:"
                                f"{coding_worker_turn_tool.plugin_id}:query"
                            ),
                            generation=receipt.policy.owner_selection_generation,
                        ),
                    )
                )
        except BaseException as error:
            run_cleanup_steps(
                error,
                (
                    *(
                        (
                            (
                                "Coding Worker turn Tool admission rollback",
                                self._coding_worker_turn_tool_lease.rollback_registration,
                            ),
                        )
                        if self._coding_worker_turn_tool_lease is not None
                        else ()
                    ),
                    *(
                        (
                            (
                                "Coding Capability Plugin evidence cleanup",
                                capability_plugin_assembly.abort_unpublished,
                            ),
                        )
                        if capability_plugin_assembly is not None
                        else ()
                    ),
                    *(
                        (
                            (
                                "Coding base Plugin evidence cleanup",
                                coding_base_plugin_assembly.close,
                            ),
                        )
                        if coding_base_plugin_assembly is not None
                        else ()
                    ),
                    *(
                        (
                            (
                                "direct Session side-question cleanup",
                                locally_created_side_question_binding.dispose,
                            ),
                        )
                        if locally_created_side_question_binding is not None
                        else ()
                    ),
                    *(
                        (
                            (
                                "direct Session capability cleanup",
                                locally_created_capability_runtime.dispose,
                            ),
                        )
                        if locally_created_capability_runtime is not None
                        else ()
                    ),
                ),
            )
            raise

    async def _ensure_session_graph_prepared(
        self,
    ) -> SessionModelCallCapabilityConsumer:
        assembly = self._coding_capability_plugin_assembly
        try:
            consumer = await super()._ensure_session_graph_prepared()
        except BaseException as error:
            run_cleanup_steps(
                error,
                (
                    (("Coding Capability Plugin evidence cleanup", assembly.close),)
                    if assembly is not None
                    else ()
                ),
            )
            raise
        if (
            assembly is not None
            and assembly.tool_owner_for("coding.lsp.default") is not None
            and self._coding_lsp_plugin_capture is None
        ):
            capture = self._capability_graph_runtime.capture(
                CODING_LSP_SESSION_REQUIREMENT
            )
            access = CodingLspSessionCapabilityConsumer(capture).access
            self._lsp_access = access
            self._coding_lsp_plugin_capture = capture
        if assembly is not None:
            assembly.close()
        return consumer

    def get_sandbox_status(self) -> SandboxStatus:
        if self._sandbox_runtime is None:
            return SandboxStatus(state="disabled")
        return self._sandbox_runtime.status()

    def get_lsp_status(self) -> LspSessionStatus:
        if self._lsp_access is None:
            if self._deferred_lsp_slot is not None:
                return LspSessionStatus(enabled=True)
            return disabled_lsp_session_status()
        return self._lsp_access.status()

    async def stop_lsp_server(
        self,
        *,
        definition_id: str,
        workspace_root: str,
    ) -> bool:
        if self._lsp_access is None:
            return False
        return await self._lsp_access.stop(
            definition_id=definition_id,
            workspace_root=workspace_root,
        )

    def list_commands(self) -> list[object]:
        commands = list(super().list_commands())
        if not any(
            getattr(command, "name", None) == LSP_SESSION_COMMAND_NAME
            for command in commands
        ):
            commands.append(lsp_session_command_descriptor())
        return commands

    async def query_worker_symbol(self, symbol: str) -> str:
        """Use the explicitly selected, read-only Coding Worker query facet."""

        from loushang.coding.package_product_worker_query_consumer import (
            bind_coding_worker_query_consumer,
        )

        await self.prepare_model_call_runtime()
        return await bind_coding_worker_query_consumer(self).query(symbol=symbol)

    async def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> object | None:
        await self.prepare_model_call_runtime()
        if normalize_command_name(invocation_name) == LSP_SESSION_COMMAND_NAME:
            return await execute_lsp_session_command(
                self._lsp_access
                or (
                    _DORMANT_LSP_ACCESS if self._deferred_lsp_slot is not None else None
                ),
                args,
            )
        return await super().execute_command_async(invocation_name, args)

    async def emit_product_tool_audit_event(
        self,
        event: Mapping[str, object],
    ) -> None:
        """Route a Product-owned runtime action through the session event stream."""

        await self._dispatch_event(dict(event))

    def _prepare_resource_refresh(self) -> None:
        capability_plugins = self._coding_capability_plugin_assembly
        if capability_plugins is not None:
            for (
                plugin_id,
                capability_change,
            ) in capability_plugins.evaluate_management_changes().items():
                if capability_change.disposition != "restart_required":
                    continue
                self._record_runtime_diagnostic(
                    DiagnosticDraft(
                        code="coding_capability_management_restart_required",
                        message=(
                            f"{plugin_id} management state changed; the active "
                            "Session retains its pinned generation and must restart."
                        ),
                        details={
                            "pluginId": plugin_id,
                            **capability_change.diagnostic_details(),
                        },
                    ),
                    source="session",
                    level="error",
                )
                raise CodingCapabilityPluginCompositionError(
                    "Active Coding Session requires restart after Capability "
                    "Plugin management change",
                    code="coding_capability_management_restart_required",
                )
        base_plugin = self._coding_base_plugin_assembly
        if base_plugin is not None:
            change = base_plugin.evaluate_management_change()
            if change is not None and change.disposition == "restart_required":
                self._record_runtime_diagnostic(
                    DiagnosticDraft(
                        code="coding_base_management_restart_required",
                        message=(
                            "coding.base management state changed; the active "
                            "Session retains its pinned generation and must restart."
                        ),
                        details=change.diagnostic_details(),
                    ),
                    source="session",
                    level="error",
                )
                raise CodingBasePluginAssemblyError(
                    "Active Coding Session requires restart after coding.base change",
                    code="coding_base_management_restart_required",
                )
        super()._prepare_resource_refresh()

    def _require_current_coding_runtime_selection(self) -> None:
        # The original factory witness retains both Workspace identity and its
        # native epoch owner. Recheck even when the composition has no selected
        # Plugin manifest; construction-time admission cannot authorize a later
        # preparation, publication or model transport after root replacement.
        witness = self.coding_product_workspace_witness
        if witness is not None:
            witness.assert_current()
        product_runtime = self._coding_base_product_runtime_binding
        product_compilation = self._coding_base_product_compilation
        worker_binding = self._coding_product_worker_ordinary_binding
        if (
            product_runtime is not None
            and worker_binding is not None
            and worker_binding.selected_worker_manifest is not None
        ):
            try:
                product_runtime.assert_selected_plugin_manifest_current(
                    worker_binding.selected_worker_manifest
                )
            except (
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                raise ValueError(
                    "Coding Worker selection changed before Session preparation"
                ) from exc
        if (
            product_runtime is not None
            and not self._coding_product_desired_preflight_completed
        ):
            for selection in self._coding_product_desired_selections:
                try:
                    product_runtime.assert_plugin_desired_selection_current(selection)
                except (
                    PackageProductRuntimeActivationError,
                    PackageProductRuntimeReadError,
                ) as exc:
                    raise CodingCapabilityPluginCompositionError(
                        "Active Coding Session requires restart after Product "
                        "Desired State change",
                        code="coding_product_desired_restart_required",
                    ) from exc
        if product_runtime is not None and product_compilation is not None:
            try:
                product_runtime.assert_selected_plugin_manifest_current(
                    product_compilation.selected_manifest
                )
            except (
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                self._record_runtime_diagnostic(
                    DiagnosticDraft(
                        code="coding_base_product_restart_required",
                        message=(
                            "coding.base Product selection changed; the active "
                            "Session must restart."
                        ),
                        details={"causeCode": exc.code},
                    ),
                    source="session",
                    level="error",
                )
                raise CodingBasePluginAssemblyError(
                    "Active Coding Session requires restart after Product selection change",
                    code="coding_base_product_restart_required",
                ) from exc
            for selected in product_compilation.selected_capability_manifests:
                try:
                    product_runtime.assert_selected_plugin_manifest_current(selected)
                except (
                    PackageProductRuntimeActivationError,
                    PackageProductRuntimeReadError,
                ) as exc:
                    self._record_runtime_diagnostic(
                        DiagnosticDraft(
                            code="coding_capability_product_restart_required",
                            message=(
                                f"{selected.manifest.name} Product selection changed; "
                                "the active Session must restart."
                            ),
                            details={
                                "pluginId": selected.manifest.name,
                                "causeCode": exc.code,
                            },
                        ),
                        source="session",
                        level="error",
                    )
                    raise CodingCapabilityPluginCompositionError(
                        "Active Coding Session requires restart after Product "
                        "Capability selection change",
                        code="coding_capability_product_restart_required",
                    ) from exc
        if product_runtime is not None and product_compilation is None:
            external = self._coding_external_data_product_compilation
            for selected in (
                *self._coding_selected_capability_manifests,
                *(external.selected_manifests if external is not None else ()),
            ):
                try:
                    product_runtime.assert_selected_plugin_manifest_current(selected)
                except (
                    PackageProductRuntimeActivationError,
                    PackageProductRuntimeReadError,
                ) as exc:
                    raise CodingCapabilityPluginCompositionError(
                        "Active Coding Session requires restart after Product "
                        "selection change",
                        code="coding_capability_product_restart_required",
                    ) from exc
        deferred_lsp = self._deferred_lsp_slot
        active_lsp = deferred_lsp.active if deferred_lsp is not None else None
        if active_lsp is not None:
            try:
                active_lsp.assert_current()
            except (
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                raise CodingCapabilityPluginCompositionError(
                    "Active Coding Session requires restart after deferred "
                    "LSP Product selection change",
                    code="coding_capability_product_restart_required",
                ) from exc

    def _claim_current_coding_runtime_owners(self) -> None:
        capability_plugins = self._coding_capability_plugin_assembly
        runtime_claim_id = (
            "coding-session-runtime:"
            f"{self.session_manager.get_header().conversation_id}"
        )
        if capability_plugins is not None:
            capability_plugins.claim_runtime(runtime_claim_id)
        assembly = self._coding_base_plugin_assembly
        if assembly is not None and assembly.management_lease is not None:
            assembly.management_lease.claim_runtime(
                runtime_claim_id
                if capability_plugins is not None or self._deferred_lsp_slot is not None
                else None
            )

    async def prepare_model_call_runtime(self) -> None:
        await self._coding_session_manager.prepare_resume_activation_guard()
        publication = self._resume_publication
        if publication is not None:
            self._require_current_resume_publication(publication)
            await super().prepare_model_call_runtime()
            self._require_current_resume_publication(publication)
            return
        self._require_current_coding_runtime_selection()
        self._claim_current_coding_runtime_owners()
        await super().prepare_model_call_runtime()
        worker_tool_lease = self._coding_worker_turn_tool_lease
        if worker_tool_lease is not None and worker_tool_lease.state == "staged":
            worker_tool_lease.activate()
            self._composition.tool_controller.activate_tool_names(
                [CODING_WORKER_QUERY_TOOL_NAME]
            )
        self._publish_coding_capability_owner_retirement_receipts()
        self._publish_coding_base_owner_retirement_receipts()
        await self._record_coding_composition_startup()
        self._coding_product_desired_preflight_completed = True

    _resume_label = "Coding Resume"
    _resume_recovery_error = CodingResumeRecoveryRequired

    @staticmethod
    def _resume_user_input_digest(message: UserMessage) -> str:
        return coding_user_input_digest(message)

    def _require_current_resume_selection(self) -> None:
        self._require_current_coding_runtime_selection()

    def _claim_resume_runtime_owners(self) -> None:
        self._claim_current_coding_runtime_owners()

    @property
    def _resume_transcript(self) -> SessionManager:
        return self._coding_session_manager

    def _resume_graph_prepared(self) -> None:
        self._publish_coding_capability_owner_retirement_receipts()
        self._publish_coding_base_owner_retirement_receipts()

    def _build_resume_composition_receipt(self) -> dict[str, object]:
        return self._build_current_coding_composition_receipt()

    def _create_resume_runtime_candidate(
        self,
        attempt: CodingActivationAttemptV1,
        receipt: Mapping[str, object],
    ) -> _CodingResumeRuntimeCandidate:
        return _CodingResumeRuntimeCandidate(
            attempt,
            self._model_call_consumer,
            self._capability_graph_runtime.generation,
            fingerprint_catalog_value("loushang.coding-resume-candidate/v1", receipt),
        )

    def _require_resume_candidate_policy(
        self,
        candidate: _ResumeRuntimeCandidate[CodingActivationAttemptV1],
    ) -> dict[str, object]:
        self._require_current_coding_runtime_selection()
        self.require_current_capability_component_activations()
        receipt = self._build_current_coding_composition_receipt()
        if (
            fingerprint_catalog_value("loushang.coding-resume-candidate/v1", receipt)
            != candidate.receipt_fingerprint
        ):
            raise CodingResumeRecoveryRequired("runtime.candidate_changed")
        return receipt

    def _create_resume_runtime_publication(
        self,
        candidate: _ResumeRuntimeCandidate[CodingActivationAttemptV1],
        input_record_id: str,
        current_admission: Callable[[CodingActivationAttemptV1], None],
        current_epoch_settlement: Callable[
            [CodingActivationAttemptV1, Mapping[str, object]], None
        ],
    ) -> _CodingResumeRuntimePublication:
        # Only the original factory above supplies candidates to this profile.
        return _CodingResumeRuntimePublication(
            cast(_CodingResumeRuntimeCandidate, candidate),
            input_record_id,
            current_admission,
            current_epoch_settlement,
        )

    def _activate_resume_runtime_tools(self) -> None:
        worker_tool_lease = self._coding_worker_turn_tool_lease
        if worker_tool_lease is not None and worker_tool_lease.state == "staged":
            worker_tool_lease.activate()
            self._composition.tool_controller.activate_tool_names(
                [CODING_WORKER_QUERY_TOOL_NAME],
            )

    def _resume_runtime_published(self) -> None:
        self._coding_product_desired_preflight_completed = True

    def _require_resume_worker_effect_settlement(
        self, attempt: CodingActivationAttemptV1
    ) -> None:
        """Reconcile Worker startup through this Session's original C5 owner."""

        binding = self._coding_product_worker_ordinary_binding
        settlement = None if binding is None else binding.resume_settlement
        worker_owners = (
            ()
            if type(attempt) is not CodingActivationAttemptV2
            else tuple(
                owner
                for owner in attempt.effect_owners
                if owner.owner_id == "harness.worker-activation"
            )
        )
        if not worker_owners and settlement is None:
            return
        if (
            type(attempt) is not CodingActivationAttemptV2
            or len(worker_owners) != 1
            or settlement is None
        ):
            raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
        settlement.require_current(attempt)

    async def _preflight_worker_preparation(
        self, catalog_snapshot: object | None
    ) -> None:
        if self._coding_product_worker_ordinary_binding is None:
            return
        attempt_id = self._resume_graph_attempt_id
        if attempt_id is not None:
            self._coding_session_manager._require_resume_runtime_preparation(attempt_id)
            self._require_current_coding_runtime_selection()
            self._build_current_coding_composition_receipt(
                prepared_catalog_snapshot=catalog_snapshot
            )
            return
        async with self._coding_composition_record_lock:
            await self._record_coding_composition_startup_locked(
                existing_only=True,
                prepared_catalog_snapshot=catalog_snapshot,
            )

    async def _record_coding_composition_startup(self) -> None:
        async with self._coding_composition_record_lock:
            await self._record_coding_composition_startup_locked()

    def _build_current_coding_composition_receipt(
        self,
        *,
        prepared_catalog_snapshot: object | None = None,
    ) -> dict[str, object]:
        """Observe current owner selections without interpreting old receipts.

        This detached data is neither effect settlement nor execution authority.
        Resume admission must validate live owners separately before publishing.
        """

        plan = self._coding_composition_plan
        if plan is None:
            raise ValueError(
                "Coding current composition receipt requires a selected plan"
            )
        compilation = self._coding_base_product_compilation
        external_compilation = self._coding_external_data_product_compilation
        capability_assembly = self._coding_capability_plugin_assembly
        selected = (
            (
                compilation.selected_manifest,
                *compilation.selected_capability_manifests,
                *compilation.selected_external_data_manifests,
            )
            if compilation is not None
            else (
                *self._coding_selected_capability_manifests,
                *(
                    external_compilation.selected_manifests
                    if external_compilation is not None
                    else ()
                ),
            )
        )
        worker_binding = self._coding_product_worker_ordinary_binding
        if (
            worker_binding is not None
            and worker_binding.selected_worker_manifest is not None
        ):
            selected = (*selected, worker_binding.selected_worker_manifest)
        revisions = [
            {
                "pluginId": item.manifest.name,
                "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                    item.snapshot.package_revision
                ),
                "instanceRevisionRef": item.snapshot.instance_revision_ref.to_dict(),
            }
            for item in selected
        ]
        if (
            compilation is None
            and not self._coding_selected_capability_manifests
            and capability_assembly is not None
        ):
            revisions.extend(
                {
                    "pluginId": plugin_id,
                    "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                        lease.package_revision
                    ),
                    "instanceRevisionRef": lease.instance_revision_ref.to_dict(),
                }
                for plugin_id, lease in capability_assembly.management_leases.items()
            )
        revisions = sorted(
            revisions,
            key=lambda item: str(item["pluginId"]),
        )
        policy_revision = (
            compilation.plan.context.policy_revision
            if compilation is not None
            else external_compilation.product_composition.authority_context.product_policy_revision
            if external_compilation is not None
            else capability_assembly.selection.plan.context.policy_revision
            if capability_assembly is not None
            else None
        )
        receipts = (
            *(
                self._coding_base_owner_publication.receipts
                if self._coding_base_owner_publication is not None
                else ()
            ),
            *(
                receipt
                for group in (
                    self._coding_capability_owner_publication.receipts
                    if self._coding_capability_owner_publication is not None
                    else {}
                ).values()
                for receipt in group
            ),
        )
        generations = sorted(
            (
                {
                    "ownerReference": receipt.owner_reference,
                    "ownerGenerationReference": receipt.owner_generation_reference,
                    "contributionIds": list(receipt.contribution_ids),
                }
                for receipt in receipts
            ),
            key=lambda item: (
                str(item["ownerReference"]),
                str(item["ownerGenerationReference"]),
            ),
        )
        catalog_snapshot = (
            prepared_catalog_snapshot
            if prepared_catalog_snapshot is not None
            else self._resource_catalog_snapshot
        )
        catalog_fingerprint = (
            fingerprint_catalog_value(
                "loushang.coding-composition-catalog-selection/v1",
                {
                    "activationPolicyFingerprint": (
                        catalog_snapshot.activation_policy_fingerprint
                    ),
                    "mergePolicyRevision": catalog_snapshot.merge_policy_revision,
                    "effectiveEntries": [
                        {
                            "identity": item.identity.to_payload(),
                            "modelInvocable": item.model_invocable,
                            "candidates": [
                                {
                                    "canonicalName": candidate.canonical_name,
                                    "description": candidate.description,
                                    "mediaType": candidate.media_type,
                                    "sourceClass": candidate.source_class,
                                    "sourceRootOrder": candidate.source_root_order,
                                    "expectedContentDigest": candidate.expected_content_digest,
                                    "expectedContentLength": candidate.expected_content_length,
                                    "invocationPolicy": candidate.invocation_policy.to_payload(),
                                }
                                for candidate in sorted(
                                    (
                                        catalog_snapshot.candidate_by_fingerprint(
                                            fingerprint
                                        )
                                        for fingerprint in item.candidate_fingerprints
                                    ),
                                    key=lambda candidate: (
                                        candidate.canonical_name,
                                        candidate.source_class,
                                        candidate.expected_content_digest or "",
                                    ),
                                )
                            ],
                        }
                        for item in catalog_snapshot.effective_entries
                    ],
                },
            )
            if isinstance(catalog_snapshot, ResourceCatalogSnapshot)
            else None
        )
        worker_receipt = (
            worker_binding.activation_receipt if worker_binding is not None else None
        )
        worker_selection: dict[str, object] | None = (
            {
                "pluginId": worker_receipt.policy.plugin_id,
                "receiptFingerprint": worker_receipt.fingerprint,
                "productPolicyRevision": worker_receipt.policy.product_policy_revision,
                "nativeProfileId": worker_receipt.policy.native_profile_id,
                "selectedLocatorRevision": worker_receipt.policy.selected_locator_revision,
                "selectedLocatorFingerprint": (
                    worker_receipt.policy.selected_locator_fingerprint
                ),
                "workerConfigurationFingerprint": (
                    worker_receipt.policy.worker_configuration_fingerprint
                ),
            }
            if worker_receipt is not None
            else None
        )
        startup_data: dict[str, object] = {
            "version": 1,
            "setId": plan.set_id,
            "planFingerprint": plan.fingerprint,
            "productPolicyRevision": policy_revision,
            "catalogSelectionFingerprint": catalog_fingerprint,
            "selectedRevisions": revisions,
            "ownerGenerations": generations,
        }
        if worker_selection is not None:
            startup_data["workerSelection"] = worker_selection
        return startup_data

    async def _record_coding_composition_startup_locked(
        self,
        *,
        existing_only: bool = False,
        prepared_catalog_snapshot: object | None = None,
    ) -> None:
        plan = self._coding_composition_plan
        if plan is None or not self.session_manager.persist:
            return
        provenance = historical_composition_provenance(
            self.session_manager.get_header().metadata
        )
        if provenance is None or provenance.set_id != plan.set_id:
            raise ValueError(
                "Coding Session composition startup changed its pinned set"
            )
        existing = historical_startup_composition_record(
            self.session_manager.get_entries()
        )
        if existing is not None:
            if (
                existing.get("setId") != provenance.set_id
                or existing.get("planFingerprint") != provenance.plan_fingerprint
            ):
                raise ValueError(
                    "Coding Session composition startup differs from its header"
                )
            if not existing_only:
                self._coding_session_manager.mark_composition_startup_prepared()
            return
        startup_data = self._build_current_coding_composition_receipt(
            prepared_catalog_snapshot=prepared_catalog_snapshot,
        )
        if self._coding_composition_had_entries_at_construction:
            raise ValueError(
                "Coding Session has input without startup composition evidence; "
                "create a new Session"
            )
        if existing_only:
            return
        await self.session_manager.append_custom_entry(
            CODING_COMPOSITION_STARTUP_TYPE,
            startup_data,
        )
        self._coding_session_manager.mark_composition_startup_prepared()

    def _get_builtin_session_info(self) -> dict[str, object]:
        info = super()._get_builtin_session_info()
        provenance = historical_composition_provenance(
            self.session_manager.get_header().metadata
        )
        startup = historical_startup_composition_record(
            self.session_manager.get_entries()
        )
        if startup is not None and (
            provenance is None
            or startup["setId"] != provenance.set_id
            or startup["planFingerprint"] != provenance.plan_fingerprint
        ):
            raise ValueError(
                "Coding Session composition startup differs from its header"
            )
        info["coding_composition"] = {
            "set_id": provenance.set_id if provenance else None,
            "plan_fingerprint": (provenance.plan_fingerprint if provenance else None),
            "startup": startup,
        }
        return info

    def _create_coding_owner_publication_bindings(
        self,
    ) -> tuple[_OwnerPublicationHooks, ...]:
        def base_owner_contributions() -> OwnerContributions | None:
            assembly = self._coding_base_plugin_assembly
            if assembly is None or assembly.management_lease is None:
                return None
            return assembly.management_lease.owner_contributions

        def capability_plugin_ids() -> Iterable[str]:
            assembly = self._coding_capability_plugin_assembly
            return () if assembly is None else assembly.management_leases

        base = self._coding_base_plugin_assembly
        capability = self._coding_capability_plugin_assembly
        self._coding_base_owner_publication = (
            _single_owner_publication(
                base.management_lease,
                plugin_id="coding.base",
                owner_contributions=base_owner_contributions,
                resource_owner_prefix="resources.",
                missing_candidate_message=(
                    "Coding base Resource owner generation is not mounted"
                ),
            )
            if base is not None and base.management_lease is not None
            else None
        )
        self._coding_capability_owner_publication = (
            _owner_set_publication(
                capability.management_leases,
                capability_plugin_ids,
            )
            if capability is not None
            else None
        )
        return tuple(
            publication
            for publication in (
                self._coding_capability_owner_publication,
                self._coding_base_owner_publication,
            )
            if publication is not None
        )

    def _publish_coding_base_owner_retirement_receipts(self) -> None:
        publication = self._coding_base_owner_publication
        if publication is not None:
            publication.require_published(
                lambda: (
                    self._capability_owner_generations,
                    self._mounted_resource_candidate,
                )
            )

    def _publish_coding_capability_owner_retirement_receipts(self) -> None:
        publication = self._coding_capability_owner_publication
        if publication is not None:
            publication.require_published(
                lambda: (self._capability_owner_generations, None)
            )

    async def _dispose_session_runtime_profile(self) -> None:
        primary_error: BaseException | None = None
        deferred_lsp = getattr(self, "_deferred_lsp_slot", None)
        if deferred_lsp is not None:
            # The child borrows parent Workspace/Resource capabilities. Keep
            # those owners and the original retirement handles alive if close
            # fails; the slot fences activation and retries the same candidate.
            # Session disposal has already stopped new work before this hook.
            await deferred_lsp.close()
            self._lsp_access = None
            deferred_cleanup = self._deferred_lsp_management_cleanup
            if deferred_cleanup is not None:
                deferred_cleanup()
        worker_tool_lease = getattr(self, "_coding_worker_turn_tool_lease", None)
        if worker_tool_lease is not None:
            try:
                result = (
                    worker_tool_lease.rollback_registration()
                    if worker_tool_lease.state == "staged"
                    else await worker_tool_lease.dispose()
                )
                if result.state not in {"removed", "already_removed"}:
                    raise RuntimeError(
                        "Coding Worker turn Tool retirement failed: "
                        f"{result.diagnostic_code or result.state}"
                    )
            except BaseException as exc:
                if primary_error is None:
                    primary_error = exc
                else:
                    primary_error.add_note(
                        f"Coding Worker turn Tool retirement also failed: {exc}"
                    )
        try:
            await super()._dispose_session_runtime_profile()
        except BaseException as exc:
            if primary_error is None:
                primary_error = exc
            else:
                primary_error.add_note(f"Session runtime retirement also failed: {exc}")
        base_plugin_assembly = getattr(self, "_coding_base_plugin_assembly", None)
        base_publication = getattr(self, "_coding_base_owner_publication", None)
        if (
            primary_error is None
            and base_plugin_assembly is not None
            and base_plugin_assembly.management_lease is not None
            and base_publication is not None
            and base_publication.receipts
            and not base_publication.retired
        ):
            primary_error = run_cleanup_steps(
                primary_error,
                (
                    (
                        "Coding base owner-generation retirement",
                        base_publication.retire_after_graph,
                    ),
                ),
            )
        plugin_assembly = getattr(
            self,
            "_coding_capability_plugin_assembly",
            None,
        )
        if plugin_assembly is not None:
            primary_error = run_cleanup_steps(
                primary_error,
                (("Coding Capability Plugin evidence cleanup", plugin_assembly.close),),
            )
            if primary_error is None:
                try:
                    publication = self._coding_capability_owner_publication
                    if publication is not None:
                        publication.retire_after_graph()
                    plugin_assembly.confirm_runtime_retirement(
                        graph_closed=self._capability_graph_runtime.is_closed,
                        runtime_was_published=(
                            publication is not None and publication.prepared
                        ),
                        graph_has_pending_retirements=(
                            self._capability_graph_runtime.has_pending_retirements
                        ),
                        owner_generations_remaining=bool(
                            self._capability_owner_generations
                        ),
                        component_generations_remaining=bool(
                            self._pending_capability_components
                        ),
                    )
                    plugin_assembly.release_management()
                    plugin_assembly.cleanup_private_state()
                except BaseException as error:
                    primary_error = error
                else:
                    self._coding_lsp_plugin_capture = None
                    self._lsp_access = None
        if base_plugin_assembly is not None:
            primary_error = run_cleanup_steps(
                primary_error,
                (("Coding base Plugin evidence cleanup", base_plugin_assembly.close),),
            )
        if self._sandbox_runtime is not None:
            try:
                await self._sandbox_runtime.close()
            except BaseException as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error.add_note(
                        f"process host or sandbox cleanup also failed: {cleanup_error}"
                    )
        if primary_error is not None:
            raise primary_error
