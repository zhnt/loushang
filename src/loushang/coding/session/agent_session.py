from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from loushang.agent import Agent, PrepareModelCallFn
from loushang.ai import PreparedRequestLimits
from loushang.ai.api_registry import APIRegistry
from loushang.coding._base_plugin import (
    CodingBasePluginAssembly,
    CodingBasePluginAssemblyError,
    CodingBasePluginSessionAssembly,
    build_coding_base_plugin_owners,
)
from loushang.coding._base_plugin_owners import CodingBaseToolRegistrationSlot
from loushang.coding.compaction.adapter import (
    execute_coding_branch_summary,
)
from loushang.coding.compaction.adapter import (
    execute_coding_compaction as _execute_coding_compaction,
)
from loushang.coding.lsp._plugin_opt_in import CodingLspPluginOptInAssembly
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolRegistrationSlot
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
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import summarize_coding_package_root
from loushang.coding.runtime_capability_admission import (
    CodingExtensionDeclarationPreflight,
    resolve_coding_capability_profile,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.capabilities import (
    CapabilityBundleProviderBinding,
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.commands import normalize_command_name
from loushang.harness.config.agent import SettingsManager
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.events import RuntimeEvent
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import SessionStartEvent
from loushang.harness.model_catalog import ModelCatalog as ModelRegistry
from loushang.harness.multiagent import DelegatedExecutionProfile
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.roots import SelectedPluginPackageInput
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)
from loushang.harness.sandbox import SandboxExecutionRuntime, SandboxStatus
from loushang.harness.session import AgentProductSession
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
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionPreparation,
    CompactionResult,
)
from loushang.harness.workspace.exec import ExecService

SessionEventListener = Callable[[AgentSessionEvent], Awaitable[None] | None]
# project_runtime_event_to_session_event remains an external migration label.
RuntimeEventListener = Callable[[RuntimeEvent[object]], Awaitable[None] | None]


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


class AgentSession(AgentProductSession):
    """Coding content and policy bound to the shared Agent Product session."""

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
        allowed_tool_names: list[str] | None = None,
        active_tool_names: list[str] | None = None,
        default_activate_new_tools: bool | None = None,
        show_empty_tool_prompt: bool = False,
        base_prompt: str | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        package_materializer: PackageMaterializer | None = None,
        session_start_event: SessionStartEvent | None = None,
        api_registry: APIRegistry | None = None,
        footer_data_provider: FooterDataProvider | None = None,
        exec_service: ExecService | None = None,
        approval_resolver: InteractiveApprovalResolver | None = None,
        tool_policy_evaluator: PolicyEvaluator | None = None,
        capability_runtime: StagedResourceCompositionCandidate | None = None,
        side_question_binding: LegacySideQuestionBinding | None = None,
        sandbox_runtime: SandboxExecutionRuntime | None = None,
        coding_lsp_plugin_assembly: CodingLspPluginOptInAssembly | None = None,
        coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
        coding_base_plugin_session_assembly: (
            CodingBasePluginSessionAssembly | None
        ) = None,
        coding_plugin_clock: Callable[[], int] | None = None,
        delegated_execution_profile: DelegatedExecutionProfile | None = None,
        workspace_capability_binding: CapabilityBundleProviderBinding | None = None,
        initial_resource_catalog_bootstrap: Any | None = None,
        resource_catalog_refresh_bootstrap_factory: Any | None = None,
        resource_catalog_refresh_lock: ResourceCatalogRefreshGatePort | None = None,
    ) -> None:
        if coding_lsp_plugin_assembly is not None and not isinstance(
            coding_lsp_plugin_assembly,
            CodingLspPluginOptInAssembly,
        ):
            raise TypeError("Coding LSP Plugin assembly is invalid")
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
        if coding_base_plugin_assembly is not None and (
            coding_lsp_plugin_assembly is None
            and coding_base_plugin_session_assembly is None
        ):
            raise ValueError("Coding base Plugin requires one Session composition")
        if coding_plugin_clock is not None and not callable(coding_plugin_clock):
            raise TypeError("Coding Plugin clock is invalid")
        self._sandbox_runtime = sandbox_runtime
        self._lsp_access: CodingLspSessionAccess | None = None
        self._coding_lsp_plugin_assembly = coding_lsp_plugin_assembly
        self._coding_base_plugin_assembly = coding_base_plugin_assembly
        self._coding_base_owner_retirement_receipts: tuple[
            OwnerGenerationRetirementReceipt,
            ...,
        ] = ()
        self._coding_base_owner_generations_prepared = False
        self._coding_base_owner_generations_published = False
        self._coding_base_owner_generations_retired = False
        self._coding_base_owner_publication_error: BaseException | None = None
        self._coding_lsp_plugin_capture: CapabilityFacetSet | None = None
        self.delegated_execution_profile = delegated_execution_profile
        self.cwd_bound_services_audit: CwdBoundServicesAudit | None = None
        resolved_capability_runtime = capability_runtime
        locally_created_capability_runtime: (
            StagedResourceCompositionCandidate | None
        ) = None
        locally_created_side_question_binding: LegacySideQuestionBinding | None = None
        lsp_tool_registration_slot: CodingLspToolRegistrationSlot | None = None
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
            coding_lsp_plugin_assembly.plugin_assembly
            if coding_lsp_plugin_assembly is not None
            else (
                coding_base_plugin_session_assembly.plugin_assembly
                if coding_base_plugin_session_assembly is not None
                else None
            )
        )
        if coding_base_plugin_assembly is not None:
            if plugin_assembly is None or coding_plugin_clock is None:
                raise ValueError("Coding base Plugin owner inputs are unavailable")
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
            base_owners = build_coding_base_plugin_owners(
                coding_base_plugin_assembly,
                plugin_assembly,
                clock=coding_plugin_clock,
                tool_options=ToolsOptions(
                    diagnostics_service=diagnostics_service,
                    external_tool_policy=(
                        get_external_tool_policy()
                        if callable(get_external_tool_policy)
                        else None
                    ),
                    host_environment=coding_base_plugin_assembly.host_environment,
                    shell_path=(get_shell_path() if callable(get_shell_path) else None),
                    command_prefix=(
                        get_shell_command_prefix()
                        if callable(get_shell_command_prefix)
                        else None
                    ),
                ),
            )
            if base_owners.tool is not None:
                base_tool_registration_slot = CodingBaseToolRegistrationSlot()
                owner_bindings = (
                    base_owners.tool.bind(base_tool_registration_slot),
                )
            owner_bindings = (
                *owner_bindings,
                base_owners.command.bind(command_generations),
            )
        if coding_lsp_plugin_assembly is not None:
            lsp_tool_registration_slot = CodingLspToolRegistrationSlot()
            owner_bindings = (
                *owner_bindings,
                coding_lsp_plugin_assembly.tool_owner.bind(lsp_tool_registration_slot),
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
                show_empty_tool_prompt=show_empty_tool_prompt,
                base_prompt=base_prompt,
                diagnostics_service=diagnostics_service,
                package_materializer=package_materializer,
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
                tool_exec_service=(
                    None
                    if coding_base_plugin_session_assembly is not None
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
                    coding_lsp_plugin_assembly.session_inputs
                    if coding_lsp_plugin_assembly is not None
                    else (
                        coding_base_plugin_session_assembly.session_inputs
                        if coding_base_plugin_session_assembly is not None
                        else None
                    )
                ),
                capability_component_host=(
                    coding_lsp_plugin_assembly.component_host
                    if coding_lsp_plugin_assembly is not None
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
            if base_tool_registration_slot is not None:
                base_tool_registration_slot.bind(self._composition.tool_controller)
        except BaseException as error:
            if coding_lsp_plugin_assembly is not None:
                coding_lsp_plugin_assembly.close()
            if coding_base_plugin_assembly is not None:
                coding_base_plugin_assembly.close()
            if locally_created_side_question_binding is not None:
                try:
                    locally_created_side_question_binding.dispose()
                except BaseException as cleanup_error:
                    error.add_note(
                        "direct Session side-question cleanup also failed: "
                        f"{cleanup_error}"
                    )
            if locally_created_capability_runtime is not None:
                try:
                    locally_created_capability_runtime.dispose()
                except BaseException as cleanup_error:
                    error.add_note(
                        "direct Session capability cleanup also failed: "
                        f"{cleanup_error}"
                    )
            raise

    async def _ensure_session_graph_prepared(
        self,
    ) -> SessionModelCallCapabilityConsumer:
        assembly = self._coding_lsp_plugin_assembly
        try:
            consumer = await super()._ensure_session_graph_prepared()
        except BaseException:
            if assembly is not None:
                assembly.close()
            raise
        if assembly is not None and self._coding_lsp_plugin_capture is None:
            capture = self._capability_graph_runtime.capture(
                CODING_LSP_SESSION_REQUIREMENT
            )
            self._lsp_access = CodingLspSessionCapabilityConsumer(capture).access
            self._coding_lsp_plugin_capture = capture
            assembly.close()
        return consumer

    def get_sandbox_status(self) -> SandboxStatus:
        if self._sandbox_runtime is None:
            return SandboxStatus(state="disabled")
        return self._sandbox_runtime.status()

    def get_lsp_status(self) -> LspSessionStatus:
        if self._lsp_access is None:
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

    async def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> object | None:
        await self.prepare_model_call_runtime()
        if normalize_command_name(invocation_name) == LSP_SESSION_COMMAND_NAME:
            return await execute_lsp_session_command(self._lsp_access, args)
        return await super().execute_command_async(invocation_name, args)

    async def emit_product_tool_audit_event(
        self,
        event: Mapping[str, object],
    ) -> None:
        """Route a Product-owned runtime action through the session event stream."""

        await self._dispatch_event(dict(event))

    def _prepare_resource_refresh(self) -> None:
        base_plugin = self._coding_base_plugin_assembly
        if base_plugin is not None:
            change = base_plugin.evaluate_management_change()
            if change is not None and change.disposition == "restart_required":
                self._record_extension_runtime_diagnostic(
                    DiagnosticDraft(
                        code="coding_base_management_restart_required",
                        message=(
                            "coding.base management state changed; the active "
                            "Session retains its pinned generation and must restart."
                        ),
                        details=change.diagnostic_details(),
                    )
                )
                raise CodingBasePluginAssemblyError(
                    "Active Coding Session requires restart after coding.base change",
                    code="coding_base_management_restart_required",
                )
        super()._prepare_resource_refresh()

    async def prepare_model_call_runtime(self) -> None:
        await super().prepare_model_call_runtime()
        self._publish_coding_base_owner_retirement_receipts()

    def _prepare_session_owner_generation_evidence(
        self,
        owner_generations: tuple[
            StagedSessionCapabilityOwnerGeneration,
            ...,
        ],
    ) -> None:
        super()._prepare_session_owner_generation_evidence(owner_generations)
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
        try:
            await super()._dispose_session_runtime_profile()
        except BaseException as exc:
            primary_error = exc
        base_plugin_assembly = getattr(self, "_coding_base_plugin_assembly", None)
        if (
            primary_error is None
            and base_plugin_assembly is not None
            and base_plugin_assembly.management_lease is not None
            and self._coding_base_owner_retirement_receipts
            and not self._coding_base_owner_generations_retired
        ):
            try:
                if not self._coding_base_owner_generations_prepared:
                    base_plugin_assembly.management_lease.prepare_owner_generations(
                        self._coding_base_owner_retirement_receipts
                    )
                    self._coding_base_owner_generations_prepared = True
                base_plugin_assembly.management_lease.retire_owner_generations(
                    self._coding_base_owner_retirement_receipts
                )
                self._coding_base_owner_generations_retired = True
            except BaseException as cleanup_error:
                primary_error = cleanup_error
        plugin_assembly = getattr(self, "_coding_lsp_plugin_assembly", None)
        if primary_error is None and plugin_assembly is not None:
            try:
                plugin_assembly.close()
            except BaseException as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error.add_note(
                        "Coding LSP Plugin evidence cleanup also failed: "
                        f"{cleanup_error}"
                    )
            self._coding_lsp_plugin_capture = None
            self._lsp_access = None
        if primary_error is None and base_plugin_assembly is not None:
            try:
                base_plugin_assembly.close()
            except BaseException as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error.add_note(
                        "Coding base Plugin evidence cleanup also failed: "
                        f"{cleanup_error}"
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
