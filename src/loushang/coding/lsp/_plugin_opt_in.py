"""Private Product composer for the staged ``coding.lsp.default`` opt-in."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loushang.coding.lsp._plugin_tool_owner import CodingLspToolOwner
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CodingLspPluginConfigV1,
)
from loushang.coding.plugin_dependency_grants import (
    coding_lsp_default_plugin_root,
    coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.approval.plugin_activation import (
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationDecisionRecordV1,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.component_host import CapabilityComponentHost
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionPolicy,
    OwnerContributionSnapshot,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.plugin_authoring.evaluator import PluginDefinitionEvaluator
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginPreflightDeniedOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PublishedPluginPackage,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityOwnerAuthorityGate,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCapabilityProviderOwnerBinding,
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssembly,
    ProductPluginCompositionAssemblyRequest,
    assemble_product_plugin_composition,
)

_PLUGIN_ID = "coding.lsp.default"
_PROVIDER_ID = "coding.lsp.default"
_TOOL_OWNER_ID = "coding.tools"
_TOOL_CATALOG_ID = "coding.lsp.tools"
_PRODUCT_POLICY_REVISION = "coding-lsp-plugin-opt-in-1"
_SOURCE_TRUST_CLASS = "host-equivalent-local"
_SOURCE_TRUST_POLICY_REVISION = "coding-lsp-source-trust-1"
_PROVIDER_OWNER_POLICY_REVISION = "coding-lsp-owner-1"
_TOOL_OWNER_POLICY_REVISION = "coding-lsp-tools-owner-1"


class CodingLspPluginApprovalOwner(Protocol):
    """Sole issuer ports retained by one Product-owned opt-in request."""

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1: ...

    def approve_activation(
        self,
        *,
        journal: PluginActivationDecisionJournal,
        subject: ContributionActivationApprovalSubject,
    ) -> PluginActivationDecisionRecordV1: ...


class CodingLspPluginOptInError(RuntimeError):
    """Stable fail-closed Product error before Session composition exists."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingLspPluginOptInRequest:
    """Private request for Product-owned selection; it carries no authority facts."""

    approval_owner: CodingLspPluginApprovalOwner = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not all(
            callable(getattr(self.approval_owner, member, None))
            for member in ("approve_definition", "approve_activation")
        ):
            raise TypeError("Coding LSP opt-in requires an Approval owner")


@dataclass(slots=True)
class CodingLspPluginOptInAssembly:
    """Approved Product closure awaiting bootstrap and Graph ownership transfer."""

    runtime: PluginRuntimeResolution = field(repr=False)
    selection: PluginSelection
    plugin_assembly: ProductPluginCompositionAssembly
    component_host: CapabilityComponentHost = field(repr=False)
    session_inputs: SessionCapabilityCompositionInputs
    tool_owner: CodingLspToolOwner = field(repr=False)
    provider_owner_authority: CapabilityProviderOwnerAuthority = field(repr=False)
    tool_owner_authority: OwnerContributionAuthority = field(repr=False)
    scope_id: str
    state_root: Path
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Release verified revision handles before ownership transfers to Session."""

        if self._closed:
            return
        self.runtime.close()
        self._closed = True


def assemble_coding_lsp_plugin_opt_in(
    request: CodingLspPluginOptInRequest,
    *,
    session_id: str,
    config: CodingLspPluginConfigV1,
    package_materializer: CodingPackageMaterializer,
    workspace_binding: CapabilityBundleProviderBinding,
    state_root: str | Path,
    host_boot_id: str,
    tool_mode: CapabilityMountMode,
    clock: Callable[[], int],
) -> CodingLspPluginOptInAssembly:
    """Resolve and approve the fixed package without importing or starting it."""

    _validate_inputs(
        request,
        session_id=session_id,
        config=config,
        package_materializer=package_materializer,
        workspace_binding=workspace_binding,
        host_boot_id=host_boot_id,
        tool_mode=tool_mode,
        clock=clock,
    )
    _read_clock(clock)
    resolved_state_root = Path(state_root).expanduser().resolve()
    resolved_state_root.mkdir(parents=True, exist_ok=True)
    scope_id = f"session:{session_id.strip()}"

    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=coding_lsp_default_plugin_root()))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=package_materializer,
    )
    try:
        selection = _finalize_selection(
            runtime,
            request=request,
            scope_id=scope_id,
            config=config,
            state_root=resolved_state_root,
            clock=clock,
        )
        provider_authority = _provider_owner_authority()
        tool_authority = _tool_owner_authority()
        plugin_assembly = assemble_product_plugin_composition(
            _assembly_request(
                selection,
                provider_authority=provider_authority,
                tool_authority=tool_authority,
                workspace_binding=workspace_binding,
            ),
            evaluated_at=_read_clock(clock),
        )
        component_host, session_inputs = _approve_activation_and_bind_inputs(
            selection,
            plugin_assembly,
            request=request,
            provider_authority=provider_authority,
            scope_id=scope_id,
            state_root=resolved_state_root,
            host_boot_id=host_boot_id,
            clock=clock,
        )
        tool_owner = _build_tool_owner(
            selection,
            plugin_assembly,
            authority=tool_authority,
            scope_id=scope_id,
            mode=tool_mode,
            clock=clock,
        )
        return CodingLspPluginOptInAssembly(
            runtime=runtime,
            selection=selection,
            plugin_assembly=plugin_assembly,
            component_host=component_host,
            session_inputs=session_inputs,
            tool_owner=tool_owner,
            provider_owner_authority=provider_authority,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=resolved_state_root,
        )
    except BaseException:
        runtime.close()
        raise


def _build_tool_owner(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    authority: OwnerContributionAuthority,
    scope_id: str,
    mode: CapabilityMountMode,
    clock: Callable[[], int],
) -> CodingLspToolOwner:
    [admission] = plugin_assembly.product_composition.catalog_admissions
    trust_snapshots = selection.plan.source_trust_snapshots

    def read_owner(
        owner_id: str,
        contribution_kind: str,
        product_id: str,
    ) -> OwnerContributionSnapshot:
        policy = authority.policy
        if (
            owner_id != policy.owner_id
            or contribution_kind != policy.contribution_kind
            or product_id != policy.product_id
        ):
            raise ValueError("Coding LSP Tool owner reader received another owner")
        return authority.snapshot()

    def read_trust(
        plugin_id: str,
        source_identity: str,
    ) -> PluginSourceTrustSnapshotV1:
        matches = tuple(
            item
            for item in trust_snapshots
            if item.plugin_id == plugin_id
            and item.package_source_identity == source_identity
        )
        if len(matches) != 1:
            raise ValueError("Coding LSP Tool owner requires one trust snapshot")
        return matches[0]

    def read_product_policy(product_id: str, requested_scope_id: str) -> str:
        if product_id != CODING_PRODUCT_ID or requested_scope_id != scope_id:
            raise ValueError("Coding LSP Tool owner received another Product scope")
        return _PRODUCT_POLICY_REVISION

    return CodingLspToolOwner(
        admission=admission,
        authority_gate=SessionCapabilityOwnerAuthorityGate(
            authority_context=(plugin_assembly.product_composition.authority_context),
            owner_snapshot_reader=read_owner,
            trust_snapshot_reader=read_trust,
            product_policy_revision_reader=read_product_policy,
            clock=clock,
        ),
        mode=mode,
        scope_id=scope_id,
    )


def _approve_activation_and_bind_inputs(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    request: CodingLspPluginOptInRequest,
    provider_authority: CapabilityProviderOwnerAuthority,
    scope_id: str,
    state_root: Path,
    host_boot_id: str,
    clock: Callable[[], int],
) -> tuple[CapabilityComponentHost, SessionCapabilityCompositionInputs]:
    journal = PluginActivationDecisionJournal(
        state_root / "activation-decisions.jsonl",
        scope_id=scope_id,
        clock=clock,
    )
    trust_snapshots = selection.plan.source_trust_snapshots

    def read_owner(capability_id: str) -> CapabilityProviderOwnerSnapshot:
        if capability_id != CODING_LSP_CAPABILITY_DEFINITION.capability_id:
            raise ValueError("Coding LSP owner reader received another Capability")
        return provider_authority.snapshot()

    def read_trust(
        plugin_id: str,
        source_identity: str,
    ) -> PluginSourceTrustSnapshotV1:
        matches = tuple(
            item
            for item in trust_snapshots
            if item.plugin_id == plugin_id
            and item.package_source_identity == source_identity
        )
        if len(matches) != 1:
            raise ValueError("Coding LSP trust reader requires one exact snapshot")
        return matches[0]

    def read_product_policy(product_id: str, requested_scope_id: str) -> str:
        if product_id != CODING_PRODUCT_ID or requested_scope_id != scope_id:
            raise ValueError("Coding LSP policy reader received another Product scope")
        return _PRODUCT_POLICY_REVISION

    component_host = CapabilityComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(),
        host_boot_id=host_boot_id,
        clock=clock,
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_product_policy,
        distribution_evidence_resolver=(coding_plugin_distribution_evidence_resolver()),
    )
    decision_ids: dict[str, str] = {}
    for candidate in plugin_assembly.component_candidates:
        subject = component_host.activation_subject(
            candidate.resolved,
            owner_snapshot=candidate.owner_snapshot,
            trust_snapshot=candidate.trust_snapshot,
        )
        decision = request.approval_owner.approve_activation(
            journal=journal,
            subject=subject,
        )
        if not isinstance(decision, PluginActivationDecisionRecordV1):
            raise TypeError(
                "Coding LSP Activation Approval owner returned invalid evidence"
            )
        recorded = next(
            (
                item
                for item in journal.snapshot().decisions
                if item.decision_id == decision.decision_id
            ),
            None,
        )
        if recorded != decision or decision.subject_digest != subject.digest:
            raise CodingLspPluginOptInError(
                "Coding LSP activation approval does not match its Subject.",
                code="coding_lsp_plugin_activation_approval_mismatch",
            )
        if decision.disposition != "approved":
            raise CodingLspPluginOptInError(
                "Coding LSP Plugin activation was not approved.",
                code="coding_lsp_plugin_activation_denied",
            )
        if decision.consumption_state != "AVAILABLE":
            raise CodingLspPluginOptInError(
                "Coding LSP Plugin activation decision is not available.",
                code="coding_lsp_plugin_activation_not_available",
            )
        decision_ids[candidate.capability_id] = decision.decision_id
    return (
        component_host,
        plugin_assembly.bind_session_inputs(decision_ids),
    )


def _finalize_selection(
    runtime: PluginRuntimeResolution,
    *,
    request: CodingLspPluginOptInRequest,
    scope_id: str,
    config: CodingLspPluginConfigV1,
    state_root: Path,
    clock: Callable[[], int],
) -> PluginSelection:
    [package] = runtime.packages
    [binding] = runtime.bindings
    plan = _selection_plan(
        package,
        source_identity=binding.source_identity,
        scope_id=scope_id,
        config=config,
    )
    journal = PluginExecutionDecisionJournal(
        state_root / "definition-decisions.jsonl",
        scope_kind="workspace",
        scope_id=scope_id,
        clock=clock,
    )
    host = PluginDeclarationHost(
        execution_evaluator=PluginDefinitionEvaluator(
            decision_journal=journal,
            import_realm=PluginImportRealm(),
            clock=clock,
            distribution_evidence_resolver=(
                coding_plugin_distribution_evidence_resolver()
            ),
        )
    )
    outcome = host.resolve(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decision_lookup=journal,
    )
    if isinstance(outcome, PluginPreflightPendingApprovalOutcome):
        for subject in outcome.subjects:
            decision = request.approval_owner.approve_definition(
                journal=journal,
                subject=subject,
            )
            if not isinstance(decision, PluginApprovalDecisionRecordV1):
                raise TypeError(
                    "Coding LSP Definition Approval owner returned invalid evidence"
                )
            if decision.subject_digest != subject.digest:
                raise CodingLspPluginOptInError(
                    "Coding LSP Definition approval does not match its Subject.",
                    code="coding_lsp_plugin_definition_approval_mismatch",
                )
        outcome = host.resolve(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decision_lookup=journal,
        )
    if not isinstance(outcome, PluginSelection):
        disposition = outcome.disposition
        raise CodingLspPluginOptInError(
            "Coding LSP Plugin Definition was not approved.",
            code=(
                "coding_lsp_plugin_definition_denied"
                if isinstance(outcome, PluginPreflightDeniedOutcome)
                else f"coding_lsp_plugin_definition_{disposition}"
            ),
        )
    return outcome


def _selection_plan(
    package: PublishedPluginPackage,
    *,
    source_identity: str,
    scope_id: str,
    config: CodingLspPluginConfigV1,
) -> PluginSelectionPlanV2:
    contributions = package.contribution_index.items
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id=CODING_PRODUCT_ID,
            scope_id=scope_id,
            policy_revision=_PRODUCT_POLICY_REVISION,
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{_PLUGIN_ID}@{scope_id}",
                    plugin_id=_PLUGIN_ID,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(_PLUGIN_ID,),
        selected_contributions=tuple(
            PluginContributionRef(_PLUGIN_ID, item.contribution_id)
            for item in contributions
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=_PLUGIN_ID,
                package_source_identity=source_identity,
                source_trust_class=_SOURCE_TRUST_CLASS,
                source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=_PLUGIN_ID,
                    contribution_id=item.contribution_id,
                    configuration=(
                        config.to_dict() if item.kind == "capability_provider" else {}
                    ),
                )
                for item in contributions
            )
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )


def _assembly_request(
    selection: PluginSelection,
    *,
    provider_authority: CapabilityProviderOwnerAuthority,
    tool_authority: OwnerContributionAuthority,
    workspace_binding: CapabilityBundleProviderBinding,
) -> ProductPluginCompositionAssemblyRequest:
    def select(
        admissions: tuple[CapabilityProviderAdmissionRecord, ...],
    ) -> tuple[ProductCapabilityProviderChoice, ...]:
        return tuple(
            ProductCapabilityProviderChoice(
                capability_id=item.capability_id,
                provider_id=item.provider.provider_id,
                candidate_fingerprint=item.candidate_fingerprint,
            )
            for item in admissions
            if item.capability_id == CODING_LSP_CAPABILITY_DEFINITION.capability_id
            and item.provider.provider_id == _PROVIDER_ID
        )

    return ProductPluginCompositionAssemblyRequest(
        contribution_request=ProductCompositionAssemblyRequest(
            selection=selection,
            owner_bindings=(ProductContributionOwnerBinding(authority=tool_authority),),
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
                CODING_LSP_CAPABILITY_DEFINITION,
            ),
        ),
        provider_owner_bindings=(
            ProductCapabilityProviderOwnerBinding(
                authority=provider_authority,
            ),
        ),
        provider_roots=(CODING_LSP_CAPABILITY_DEFINITION.capability_id,),
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        select_capability_providers=select,
        prebound_providers=(workspace_binding.provider,),
    )


def _provider_owner_authority() -> CapabilityProviderOwnerAuthority:
    definition = CODING_LSP_CAPABILITY_DEFINITION
    return CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision=_PROVIDER_OWNER_POLICY_REVISION,
            revocation_epoch=0,
            allowed_provider_ids=(_PROVIDER_ID,),
            allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
            authority_ceiling=("filesystem", "process"),
        )
    )


def _tool_owner_authority() -> OwnerContributionAuthority:
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=_TOOL_OWNER_ID,
            contribution_kind="tool_pack",
            product_id=CODING_PRODUCT_ID,
            policy_revision=_TOOL_OWNER_POLICY_REVISION,
            revocation_epoch=0,
            allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
            allowed_collection_ids=(_TOOL_CATALOG_ID,),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    )


def _validate_inputs(
    request: CodingLspPluginOptInRequest,
    *,
    session_id: str,
    config: CodingLspPluginConfigV1,
    package_materializer: CodingPackageMaterializer,
    workspace_binding: CapabilityBundleProviderBinding,
    host_boot_id: str,
    tool_mode: CapabilityMountMode,
    clock: Callable[[], int],
) -> None:
    if not isinstance(request, CodingLspPluginOptInRequest):
        raise TypeError("Coding LSP Plugin opt-in request is invalid")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding LSP Plugin opt-in Session id must not be empty")
    if not isinstance(config, CodingLspPluginConfigV1):
        raise TypeError("Coding LSP Plugin opt-in configuration is invalid")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Coding LSP Plugin opt-in requires Coding materialization")
    if not isinstance(workspace_binding, CapabilityBundleProviderBinding):
        raise TypeError("Coding LSP Plugin opt-in workspace binding is invalid")
    if (
        workspace_binding.provider.capability_id
        != WORKSPACE_CAPABILITY_DEFINITION.capability_id
    ):
        raise ValueError("Coding LSP Plugin opt-in requires harness.workspace")
    if not isinstance(host_boot_id, str):
        raise TypeError("Coding LSP Plugin opt-in Host boot id is invalid")
    if len(host_boot_id) != 32 or any(
        item not in "0123456789abcdefABCDEF" for item in host_boot_id
    ):
        raise ValueError("Coding LSP Plugin opt-in Host boot id must be 32 hex digits")
    if tool_mode not in {"on_demand", "always"}:
        raise ValueError("Coding LSP Plugin opt-in requires an enabled Tool mode")
    if not callable(clock):
        raise TypeError("Coding LSP Plugin opt-in clock is invalid")


def _read_clock(clock: Callable[[], int]) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Coding LSP opt-in clock must return an integer")
    if value < 0:
        raise ValueError("Coding LSP opt-in time cannot be negative")
    return value


__all__ = [
    "CodingLspPluginApprovalOwner",
    "CodingLspPluginOptInAssembly",
    "CodingLspPluginOptInError",
    "CodingLspPluginOptInRequest",
    "assemble_coding_lsp_plugin_opt_in",
]
