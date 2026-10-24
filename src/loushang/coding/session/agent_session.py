from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loushang.agent import Agent, PrepareModelCallFn
from loushang.ai import PreparedRequestLimits
from loushang.ai.api_registry import APIRegistry
from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.types import ImagePart, UserMessage
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
from loushang.coding._cleanup import run_cleanup_steps
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
    OwnerGenerationRetirementReceipt,
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.sandbox import SandboxExecutionRuntime, SandboxStatus
from loushang.harness.session import AgentProductSession
from loushang.harness.session.bash import UserBashHookResult, UserBashRequest
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityOwnerGenerationBinding,
    StagedSessionCapabilityOwnerGeneration,
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

    async def stop(
        self, *, definition_id: str, workspace_root: str | Path
    ) -> bool:
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
) -> CompactionResult:
    return await _execute_coding_compaction(
        preparation=preparation,
        model=model,
        headers=headers,
        signal=signal,
        custom_instructions=custom_instructions,
        prepare_model_call=prepare_model_call,
        request_limits=request_limits,
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
    current_epoch_settlement: Callable[[CodingActivationAttemptV1, Mapping[str, object]], None]


class AgentSession(AgentProductSession):
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
        publication = getattr(self, "_coding_resume_publication", None)
        if publication is not None:
            self._require_current_resume_publication(publication)

    def _is_current_model_call_session(self) -> bool:
        if not super()._is_current_model_call_session():
            return False
        publication = getattr(self, "_coding_resume_publication", None)
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
        self, command: str, args: Sequence[str] = (), *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
        timeout_seconds: float | None = None, stdin: str | None = None,
        signal: object | None = None, on_update: ExecUpdateCallback | None = None,
        preview_max_lines: int = 2000, preview_max_bytes: int = 50 * 1024,
        artifact_dir: str | None = None, capture_full_output: bool = True,
        rolling_max_bytes: int = 100 * 1024,
    ) -> ExecResult:
        self._require_coding_execution_admission()
        return await super()._exec_command_from_extension(
            command, args, cwd=cwd, env=env, timeout_seconds=timeout_seconds,
            stdin=stdin, signal=signal, on_update=on_update,
            preview_max_lines=preview_max_lines, preview_max_bytes=preview_max_bytes,
            artifact_dir=artifact_dir, capture_full_output=capture_full_output,
            rolling_max_bytes=rolling_max_bytes,
        )

    @staticmethod
    def _reject_peer_worker_tool(tool: object) -> None:
        if isinstance(tool, ToolDefinition) and tool.name == CODING_WORKER_QUERY_TOOL_NAME:
            raise ValueError("Coding Worker query Tool is reserved for the Product owner")

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
                and self._composition.tool_controller.is_tool_allowed(
                    str(item["name"])
                )
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
            raise ValueError("Coding Worker turn Tool requires a selected Worker receipt")
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
        elif (
            capability_plugin_assembly is not None
            and (
                coding_base_product_runtime_binding is not None
                or coding_selected_capability_manifests
            )
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
            or coding_base_product_runtime_binding.product_id
            != CODING_PRODUCT_ID
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
        self._coding_resume_runtime_preparation_lock = asyncio.Lock()
        self._coding_resume_graph_attempt_id: str | None = None
        self._coding_resume_candidate: _CodingResumeRuntimeCandidate | None = None
        self._coding_resume_publication: _CodingResumeRuntimePublication | None = None
        self._coding_resume_dispatch_claimed = False
        self._coding_resume_input_commit_claimed = False
        self._coding_resume_input_preflight_claimed = False
        self._coding_resume_preflight_input_digest: str | None = None
        self._coding_composition_had_entries_at_construction = bool(
            session_manager.get_entries()
        )
        self._coding_base_owner_retirement_receipts: tuple[
            OwnerGenerationRetirementReceipt,
            ...,
        ] = ()
        self._coding_base_owner_generations_prepared = False
        self._coding_base_owner_generations_published = False
        self._coding_base_owner_generations_retired = False
        self._coding_base_owner_publication_error: BaseException | None = None
        self._coding_capability_owner_retirement_receipts: dict[
            str,
            tuple[OwnerGenerationRetirementReceipt, ...],
        ] = {}
        self._coding_capability_owner_generations_prepared = False
        self._coding_capability_owner_generations_published = False
        self._coding_capability_owner_generations_retired = False
        self._coding_capability_owner_publication_error: BaseException | None = None
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
                execute_compaction=_execute_coding_compaction_runtime,
                single_call_capacity_probe=coding_single_call_capacity_pressure,
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
                    _DORMANT_LSP_ACCESS
                    if self._deferred_lsp_slot is not None
                    else None
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
        publication = self._coding_resume_publication
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

    async def _prepare_resume_runtime_graph(
        self, *, attempt_id: str,
        require_current_admission: Callable[[CodingActivationAttemptV1], None],
    ) -> dict[str, object]:
        """Prepare current owners for one committed intent, keeping execution fenced.

        The activation coordinator supplies live subject/policy admission. This
        path returns current observations; it does not commit input, activate
        the Worker turn Tool or publish Product execution readiness.
        """

        manager = self._coding_session_manager

        def require_current() -> None:
            # Graph rollback can retire this same Transcript Writer. Never hold
            # its operation scope across graph awaits or retirement would wait
            # for the operation that is itself waiting for retirement.
            with manager._lifecycle_session.sync_operation_scope():
                attempt = manager._require_resume_runtime_preparation(attempt_id)
                self._require_candidate_preparation_admission(lambda: require_current_admission(attempt))
                self._require_current_coding_runtime_selection()

        async with self._coding_resume_runtime_preparation_lock:
            self._require_candidate_preparation_admission(require_current)
            self._coding_resume_graph_attempt_id = attempt_id
            try:
                self._claim_current_coding_runtime_owners()
                await self._prepare_candidate_session_graph(require_current_admission=require_current)
                self._publish_coding_capability_owner_retirement_receipts()
                self._publish_coding_base_owner_retirement_receipts()
                require_current()
                receipt = self._build_current_coding_composition_receipt()
                self._coding_resume_candidate = _CodingResumeRuntimeCandidate(
                    manager._require_resume_runtime_preparation(attempt_id),
                    self._model_call_consumer, self._capability_graph_runtime.generation,
                    fingerprint_catalog_value("loushang.coding-resume-candidate/v1", receipt),
                )
                return receipt
            except BaseException:
                self._execution_preparation_failed = True
                raise
            finally:
                self._coding_resume_graph_attempt_id = None

    async def _prepare_resume_first_user_input(
        self, text: str, *, attempt_id: str,
        require_current_admission: Callable[[CodingActivationAttemptV1], None],
        images: list[ImagePart] | None = None,
    ) -> UserMessage:
        """Prepare one current input through original prompt/Resource owners.

        Formal preparation requires the locally committed intent and prepared
        graph. It does not stage or commit a UserMessage, execute commands,
        publish a runtime or run a model. The coordinator still owns those steps.
        """

        from loushang.harness.runtime.turn import TurnInput

        if not isinstance(text, str) or (not text.strip() and not images):
            raise ValueError("Coding Resume requires nonempty user input")
        manager = self._coding_session_manager
        async with self._coding_resume_runtime_preparation_lock:
            candidate = self._coding_resume_candidate
            if candidate is None or candidate.attempt.attempt_id != attempt_id:
                raise CodingResumeRecoveryRequired("runtime.candidate_unverified")
            if self._coding_resume_input_preflight_claimed or self._coding_resume_input_commit_claimed:
                raise CodingResumeRecoveryRequired("input.preflight_already_claimed")

            def require_current() -> None:
                with manager._lifecycle_session.sync_operation_scope():
                    manager._require_resume_runtime_preparation(attempt_id)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )
                    self._require_resume_candidate(candidate)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )

            require_current()
            commands = self._composition.command_controller
            if (
                commands.extract_extension_command_invocation(text) is not None
                or commands.extract_builtin_command_invocation(text) is not None
            ):
                raise CodingResumeRecoveryRequired("input.command_requires_separate_admission")
            self._coding_resume_input_preflight_claimed = True
            evidence_owner = object()
            try:
                message = await self._composition.session_runtime.prompt_controller.prepare_user_message(
                    TurnInput(text=text, attachments=None if images is None else list(images), source="resume"),
                    evidence_owner=evidence_owner,
                )
                require_current()
                self._coding_resume_preflight_input_digest = coding_user_input_digest(message)
                return message
            except BaseException:
                self._request_evidence_runtime.discard_owner(evidence_owner)
                self._execution_preparation_failed = True
                raise

    async def _commit_resume_first_user_input(
        self, message: UserMessage, *, attempt_id: str,
        require_current_admission: Callable[[CodingActivationAttemptV1], None],
    ) -> str:
        """Commit the staged fixed input through native Request Evidence owners.

        This initial route is claimed once, including unknown outcomes. The
        coordinator must use durable lookup for recovery and still settle the
        current epoch before publication or model dispatch.
        """

        if not isinstance(message, UserMessage):
            raise TypeError("Coding Resume input requires a UserMessage")
        manager = self._coding_session_manager
        async with self._coding_resume_runtime_preparation_lock:
            candidate = self._coding_resume_candidate
            if candidate is None or candidate.attempt.attempt_id != attempt_id:
                raise CodingResumeRecoveryRequired("runtime.candidate_unverified")
            if self._coding_resume_input_commit_claimed:
                raise CodingResumeRecoveryRequired("input.commit_already_claimed")
            if (
                self._coding_resume_preflight_input_digest is not None
                and coding_user_input_digest(message) != self._coding_resume_preflight_input_digest
            ):
                raise CodingResumeRecoveryRequired("input.preflight_payload_changed")
            with manager._lifecycle_session.sync_operation_scope():
                manager._require_resume_runtime_preparation(attempt_id)
                manager._require_resume_staged_input(attempt_id, message)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt),
                )
                self._require_resume_candidate(candidate)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt),
                )
            self._coding_resume_input_commit_claimed = True
            try:
                record_id = await self._composition.session_runtime.agent_event_router.commit_prepared_user_message(message)
                with manager._lifecycle_session.sync_operation_scope():
                    manager._require_committed_resume_input(attempt_id, record_id)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )
                    self._require_resume_candidate(candidate)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )
                return record_id
            except BaseException:
                self._execution_preparation_failed = True
                raise

    def _require_resume_candidate(
        self, candidate: _CodingResumeRuntimeCandidate,
    ) -> dict[str, object]:
        if (
            not super().execution_available or self._coding_resume_candidate is not candidate
            or candidate.consumer is None or self._model_call_consumer is not candidate.consumer
            or self._capability_graph_runtime.is_closed
            or self._capability_graph_runtime.generation != candidate.graph_generation
        ):
            raise CodingResumeRecoveryRequired("runtime.candidate_changed")
        self._require_current_coding_runtime_selection()
        self.require_current_capability_component_activations()
        receipt = self._build_current_coding_composition_receipt()
        if fingerprint_catalog_value("loushang.coding-resume-candidate/v1", receipt) != candidate.receipt_fingerprint:
            raise CodingResumeRecoveryRequired("runtime.candidate_changed")
        return receipt

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

    def _require_current_resume_publication(
        self, publication: _CodingResumeRuntimePublication,
    ) -> None:
        candidate = publication.candidate
        with self._coding_session_manager._lifecycle_session.sync_operation_scope():
            attempt, _ = self._coding_session_manager._require_committed_resume_input(
                candidate.attempt.attempt_id, publication.input_record_id,
            )
            self._require_candidate_preparation_admission(lambda: publication.current_admission(attempt))
            receipt = self._require_resume_candidate(candidate)
            self._require_candidate_preparation_admission(lambda: publication.current_admission(attempt))
            self._require_resume_worker_effect_settlement(attempt)
            self._require_candidate_preparation_admission(lambda: publication.current_admission(attempt))
            self._require_candidate_preparation_admission(
                lambda: publication.current_epoch_settlement(attempt, receipt),
            )
            self._require_candidate_preparation_admission(lambda: publication.current_admission(attempt))
            self._require_resume_candidate(candidate)
            self._require_candidate_preparation_admission(lambda: publication.current_admission(attempt))

    async def _publish_resume_runtime(
        self, *, attempt_id: str, input_record_id: str,
        require_current_admission: Callable[[CodingActivationAttemptV1], None],
        require_current_epoch_settlement: Callable[[CodingActivationAttemptV1, Mapping[str, object]], None],
    ) -> None:
        """Publish a prepared graph after exact durable input and live owner checks.

        The activation coordinator owns current grants and native effect
        settlement. Historical Binding and these local observations grant none.
        Publication is in memory; recovery must acquire fresh owner authority.
        """

        manager = self._coding_session_manager
        async with self._coding_resume_runtime_preparation_lock:
            candidate = self._coding_resume_candidate
            if candidate is None or candidate.attempt.attempt_id != attempt_id:
                raise CodingResumeRecoveryRequired("runtime.candidate_unverified")
            if self._coding_resume_publication is not None:
                raise CodingResumeRecoveryRequired("runtime.already_published")
            with manager._lifecycle_session.sync_operation_scope():
                manager._require_committed_resume_input(attempt_id, input_record_id)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt),
                )
                self._require_resume_candidate(candidate)
                self._require_candidate_preparation_admission(lambda: require_current_admission(candidate.attempt))
            await manager._verify_resume_publication_input(attempt_id, input_record_id)
            publication = _CodingResumeRuntimePublication(
                candidate, input_record_id, require_current_admission, require_current_epoch_settlement,
            )
            self._require_current_resume_publication(publication)
            with manager._lifecycle_session.sync_operation_scope():
                try:
                    worker_tool_lease = self._coding_worker_turn_tool_lease
                    if worker_tool_lease is not None and worker_tool_lease.state == "staged":
                        worker_tool_lease.activate()
                        self._composition.tool_controller.activate_tool_names(
                            [CODING_WORKER_QUERY_TOOL_NAME],
                        )
                    self._require_current_resume_publication(publication)
                    manager._publish_resume_runtime(attempt_id, input_record_id)
                    self._coding_resume_publication = publication
                    self._coding_product_desired_preflight_completed = True
                except BaseException:
                    self._execution_preparation_failed = True
                    raise

    async def _run_published_resume_input(self, *, attempt_id: str, input_record_id: str) -> None:
        """Consume the published input once through the original Host/Agent loop.

        No prompt submission or user append occurs here. The original Model
        Input transport barrier remains installed. A claimed run is never
        automatically replayed after an error, cancellation or unknown outcome.
        """

        publication = self._coding_resume_publication
        if (
            publication is None or publication.candidate.attempt.attempt_id != attempt_id
            or publication.input_record_id != input_record_id
        ):
            raise CodingResumeRecoveryRequired("model.publication_unverified")
        if self._coding_resume_dispatch_claimed:
            raise CodingResumeRecoveryRequired("model.dispatch_already_claimed")
        await self.prepare_model_call_runtime()
        original_options: CallOptions | None = None
        claimed_here = False

        def prepare_current_input() -> None:
            nonlocal original_options, claimed_here
            self._require_current_resume_publication(publication)
            if (
                self._coding_resume_dispatch_claimed or self.session_manager.leaf_id != input_record_id
                or self.agent.has_queued_messages() or self._composition.retry_runtime.is_retrying
            ):
                raise CodingResumeRecoveryRequired("model.input_not_current")
            self._refresh_agent_messages()
            if not self.agent.state.messages or getattr(self.agent.state.messages[-1], "role", None) != "user":
                raise CodingResumeRecoveryRequired("model.input_not_current")
            original_options = self.agent.call_options
            self.agent.call_options = replace(original_options, retry=RetryOptions(max_attempts=1))
            self._coding_resume_dispatch_claimed = claimed_here = True

        try:
            await self._composition.session_runtime.run_committed_input(prepare_current_input=prepare_current_input)
            last_assistant = next(
                (message for message in reversed(self.agent.state.messages)
                 if getattr(message, "role", None) == "assistant"), None,
            )
            if claimed_here and (
                last_assistant is None or getattr(last_assistant, "stop_reason", None) in {"error", "aborted"}
            ):
                self._execution_preparation_failed = True
        except BaseException:
            if claimed_here:
                self._execution_preparation_failed = True
            raise
        finally:
            if original_options is not None:
                self.agent.call_options = original_options

    async def _preflight_worker_preparation(
        self, catalog_snapshot: object | None
    ) -> None:
        if self._coding_product_worker_ordinary_binding is None:
            return
        attempt_id = self._coding_resume_graph_attempt_id
        if attempt_id is not None:
            self._coding_session_manager._require_resume_runtime_preparation(attempt_id)
            self._require_current_coding_runtime_selection()
            self._build_current_coding_composition_receipt(prepared_catalog_snapshot=catalog_snapshot)
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
            raise ValueError("Coding current composition receipt requires a selected plan")
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
        if worker_binding is not None and worker_binding.selected_worker_manifest is not None:
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
            *self._coding_base_owner_retirement_receipts,
            *(
                receipt
                for group in self._coding_capability_owner_retirement_receipts.values()
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
                                        catalog_snapshot.candidate_by_fingerprint(fingerprint)
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
            raise ValueError("Coding Session composition startup changed its pinned set")
        existing = historical_startup_composition_record(
            self.session_manager.get_entries()
        )
        if existing is not None:
            if (
                existing.get("setId") != provenance.set_id
                or existing.get("planFingerprint")
                != provenance.plan_fingerprint
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
            raise ValueError("Coding Session composition startup differs from its header")
        info["coding_composition"] = {
            "set_id": provenance.set_id if provenance else None,
            "plan_fingerprint": (
                provenance.plan_fingerprint if provenance else None
            ),
            "startup": startup,
        }
        return info

    def _prepare_session_owner_generation_evidence(
        self,
        owner_generations: tuple[
            StagedSessionCapabilityOwnerGeneration,
            ...,
        ],
    ) -> None:
        super()._prepare_session_owner_generation_evidence(owner_generations)
        capability_plugins = self._coding_capability_plugin_assembly
        if capability_plugins is not None:
            capability_receipts = (
                self._capture_coding_capability_owner_retirement_receipts(
                    owner_generations,
                    prepared=True,
                )
            )
            self._coding_capability_owner_retirement_receipts = capability_receipts
            capability_plugins.prepare_owner_generations(capability_receipts)
            self._coding_capability_owner_generations_prepared = True
        assembly = self._coding_base_plugin_assembly
        if assembly is None or assembly.management_lease is None:
            return
        receipts = self._capture_coding_base_owner_retirement_receipts(
            owner_generations,
            candidate=self._staged_resource_candidate,
            prepared=True,
        )
        self._coding_base_owner_retirement_receipts = receipts
        assembly.management_lease.prepare_owner_generations(receipts)
        self._coding_base_owner_generations_prepared = True

    def _commit_session_owner_generation_evidence(self) -> None:
        super()._commit_session_owner_generation_evidence()
        capability_plugins = self._coding_capability_plugin_assembly
        if (
            capability_plugins is not None
            and self._coding_capability_owner_retirement_receipts
            and not self._coding_capability_owner_generations_published
        ):
            try:
                capability_plugins.publish_owner_generations(
                    self._coding_capability_owner_retirement_receipts
                )
            except BaseException as error:
                self._coding_capability_owner_publication_error = error
            else:
                self._coding_capability_owner_generations_published = True
        assembly = self._coding_base_plugin_assembly
        if (
            assembly is None
            or assembly.management_lease is None
            or not self._coding_base_owner_retirement_receipts
            or self._coding_base_owner_generations_published
        ):
            return
        try:
            assembly.management_lease.publish_owner_generations(
                self._coding_base_owner_retirement_receipts
            )
        except BaseException as error:
            # Publication already has durable prepared evidence.  Preserve the
            # committed graph so the Coding boundary can surface this failure
            # once and retry only the evidence append on the next prepare.
            self._coding_base_owner_publication_error = error
        else:
            self._coding_base_owner_generations_published = True

    def _publish_coding_base_owner_retirement_receipts(self) -> None:
        assembly = self._coding_base_plugin_assembly
        if assembly is None or assembly.management_lease is None:
            return
        publication_error = self._coding_base_owner_publication_error
        if publication_error is not None:
            self._coding_base_owner_publication_error = None
            raise publication_error
        if self._coding_base_owner_retirement_receipts:
            if not self._coding_base_owner_generations_prepared:
                assembly.management_lease.prepare_owner_generations(
                    self._coding_base_owner_retirement_receipts
                )
                self._coding_base_owner_generations_prepared = True
            if not self._coding_base_owner_generations_published:
                assembly.management_lease.publish_owner_generations(
                    self._coding_base_owner_retirement_receipts
                )
                self._coding_base_owner_generations_published = True
            return
        canonical = self._capture_coding_base_owner_retirement_receipts(
            self._capability_owner_generations,
            candidate=self._mounted_resource_candidate,
            prepared=False,
        )
        self._coding_base_owner_retirement_receipts = canonical
        if not self._coding_base_owner_generations_prepared:
            assembly.management_lease.prepare_owner_generations(canonical)
            self._coding_base_owner_generations_prepared = True
        assembly.management_lease.publish_owner_generations(canonical)
        self._coding_base_owner_generations_published = True

    def _publish_coding_capability_owner_retirement_receipts(self) -> None:
        assembly = self._coding_capability_plugin_assembly
        if assembly is None or not assembly.management_leases:
            return
        publication_error = self._coding_capability_owner_publication_error
        if publication_error is not None:
            self._coding_capability_owner_publication_error = None
            raise publication_error
        receipts = self._coding_capability_owner_retirement_receipts
        if not receipts:
            receipts = self._capture_coding_capability_owner_retirement_receipts(
                self._capability_owner_generations,
                prepared=False,
            )
            self._coding_capability_owner_retirement_receipts = receipts
        if not self._coding_capability_owner_generations_prepared:
            assembly.prepare_owner_generations(receipts)
            self._coding_capability_owner_generations_prepared = True
        if not self._coding_capability_owner_generations_published:
            assembly.publish_owner_generations(receipts)
            self._coding_capability_owner_generations_published = True

    def _capture_coding_capability_owner_retirement_receipts(
        self,
        owner_generations: tuple[
            StagedSessionCapabilityOwnerGeneration,
            ...,
        ],
        *,
        prepared: bool,
    ) -> dict[str, tuple[OwnerGenerationRetirementReceipt, ...]]:
        assembly = self._coding_capability_plugin_assembly
        if assembly is None:
            return {}
        return {
            plugin_id: tuple(
                sorted(
                    [
                        (
                            generation.capture_prepared_retirement_receipt()
                            if prepared
                            else generation.capture_retirement_receipt()
                        )
                        for generation in owner_generations
                        if generation.binding.plugin_id == plugin_id
                    ],
                    key=lambda item: (
                        item.owner_reference,
                        item.owner_generation_reference,
                        item.retirement_handle,
                    ),
                )
            )
            for plugin_id in assembly.management_leases
        }

    def _capture_coding_base_owner_retirement_receipts(
        self,
        owner_generations: tuple[
            StagedSessionCapabilityOwnerGeneration,
            ...,
        ],
        *,
        candidate: StagedResourceCompositionCandidate | None,
        prepared: bool,
    ) -> tuple[OwnerGenerationRetirementReceipt, ...]:
        receipts = [
            (
                generation.capture_prepared_retirement_receipt()
                if prepared
                else generation.capture_retirement_receipt()
            )
            for generation in owner_generations
            if generation.binding.plugin_id == "coding.base"
        ]
        assembly = self._coding_base_plugin_assembly
        if assembly is None or assembly.management_lease is None:
            return ()
        resource_contribution_ids = tuple(
            sorted(
                {
                    contribution_id
                    for owner_reference, contribution_ids in (
                        assembly.management_lease.owner_contributions
                    )
                    if owner_reference.startswith("resources.")
                    for contribution_id in contribution_ids
                }
            )
        )
        if resource_contribution_ids:
            if candidate is None:
                raise RuntimeError(
                    "Coding base Resource owner generation is not mounted"
                )
            receipts.append(
                candidate.resource_owner_generation_retirement_receipt(
                    contribution_ids=resource_contribution_ids,
                )
            )
        canonical = tuple(
            sorted(
                receipts,
                key=lambda item: (
                    item.owner_reference,
                    item.owner_generation_reference,
                    item.retirement_handle,
                ),
            )
        )
        return canonical

    async def _dispose_session_runtime_profile(self) -> None:
        primary_error: BaseException | None = None
        deferred_lsp = getattr(self, "_deferred_lsp_slot", None)
        if deferred_lsp is not None:
            try:
                await deferred_lsp.close()
                self._lsp_access = None
                deferred_cleanup = self._deferred_lsp_management_cleanup
                if deferred_cleanup is not None:
                    deferred_cleanup()
            except BaseException as exc:
                primary_error = exc
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
                primary_error.add_note(
                    f"Session runtime retirement also failed: {exc}"
                )
        base_plugin_assembly = getattr(self, "_coding_base_plugin_assembly", None)
        if (
            primary_error is None
            and base_plugin_assembly is not None
            and base_plugin_assembly.management_lease is not None
            and self._coding_base_owner_retirement_receipts
            and not self._coding_base_owner_generations_retired
        ):

            def retire_base_owner_generations() -> None:
                if not self._coding_base_owner_generations_prepared:
                    base_plugin_assembly.management_lease.prepare_owner_generations(
                        self._coding_base_owner_retirement_receipts
                    )
                    self._coding_base_owner_generations_prepared = True
                base_plugin_assembly.management_lease.retire_owner_generations(
                    self._coding_base_owner_retirement_receipts
                )
                self._coding_base_owner_generations_retired = True

            primary_error = run_cleanup_steps(
                primary_error,
                (
                    (
                        "Coding base owner-generation retirement",
                        retire_base_owner_generations,
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
                    receipts = self._coding_capability_owner_retirement_receipts
                    if (
                        receipts
                        and not self._coding_capability_owner_generations_retired
                    ):
                        if not self._coding_capability_owner_generations_prepared:
                            plugin_assembly.prepare_owner_generations(receipts)
                            self._coding_capability_owner_generations_prepared = True
                        plugin_assembly.retire_owner_generations(receipts)
                        self._coding_capability_owner_generations_retired = True
                    plugin_assembly.confirm_runtime_retirement(
                        graph_closed=self._capability_graph_runtime.is_closed,
                        runtime_was_published=(
                            self._coding_capability_owner_generations_prepared
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
