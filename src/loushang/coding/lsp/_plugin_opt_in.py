"""Private Product composer for the staged ``coding.lsp.default`` opt-in."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loushang.coding._base_plugin import CodingBasePluginAssembly
from loushang.coding._resource_catalog_shadow import (
    complete_coding_package_plugin_selection_seed,
)
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
    PluginApprovalAuthorizationV1,
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
from loushang.harness.resources.plugins.types import PluginSource
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
    ProductPluginCompositionPreparation,
    ProductPluginPlanSeed,
    ProductPluginSelectionSeed,
    prepare_product_plugin_composition,
)

_PLUGIN_ID = "coding.lsp.default"
_BASE_PLUGIN_ID = "coding.base"
_PROVIDER_ID = "coding.lsp.default"
_TOOL_OWNER_ID = "coding.tools"
_TOOL_CATALOG_ID = "coding.lsp.tools"
_PRODUCT_POLICY_REVISION = "coding-lsp-plugin-opt-in-1"
_SOURCE_TRUST_CLASS = "host-equivalent-local"
_SOURCE_TRUST_POLICY_REVISION = "coding-lsp-source-trust-1"
_PROVIDER_OWNER_POLICY_REVISION = "coding-lsp-owner-1"
_TOOL_OWNER_POLICY_REVISION = "coding-lsp-tools-owner-1"
_DEFAULT_APPROVAL_ACTOR_ID = "product:coding"
_DEFAULT_APPROVAL_SOURCE = "coding-lsp-default-product-policy"
# Keep Product-issued activation authority live for the full default Provider
# admission window. Both remain bounded; the Session still has to recompose once
# the 300-second admission expires.
_DEFAULT_APPROVAL_TTL_MS = 300_000
_DEFAULT_DEFINITION_ENTRYPOINT = "definition.py:declare"
_DEFAULT_PROVIDER_CONTRIBUTION_ID = "coding-lsp-default"


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


@dataclass(frozen=True, slots=True)
class _CodingLspDefaultPluginApprovalOwner:
    """Approve only Coding's exact checked-in LSP package policy closure."""

    clock: Callable[[], int] = field(repr=False, compare=False)
    product_policy_revision: str = _PRODUCT_POLICY_REVISION

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1:
        _validate_default_definition_subject(
            subject,
            product_policy_revision=self.product_policy_revision,
        )
        now = _read_clock(self.clock)
        return journal.issue_execution_decision(
            subject,
            disposition="approved",
            authorization=_default_approval_authorization(),
            revocation_epoch=0,
            issued_at_unix_ms=now,
            expires_at_unix_ms=now + _DEFAULT_APPROVAL_TTL_MS,
            expected_journal_revision=journal.snapshot().journal_revision,
        )

    def approve_activation(
        self,
        *,
        journal: PluginActivationDecisionJournal,
        subject: ContributionActivationApprovalSubject,
    ) -> PluginActivationDecisionRecordV1:
        _validate_default_activation_subject(
            subject,
            product_policy_revision=self.product_policy_revision,
        )
        now = _read_clock(self.clock)
        return journal.issue_activation_decision(
            subject,
            disposition="approved",
            authorization=_default_approval_authorization(),
            issued_at_unix_ms=now,
            expires_at_unix_ms=now + _DEFAULT_APPROVAL_TTL_MS,
            expected_journal_revision=journal.snapshot().journal_revision,
        )


def create_coding_lsp_default_plugin_opt_in_request(
    *,
    clock: Callable[[], int],
    product_policy_revision: str = _PRODUCT_POLICY_REVISION,
) -> CodingLspPluginOptInRequest:
    """Create Coding's private exact-policy request for its checked-in Plugin."""

    if not callable(clock):
        raise TypeError("Coding LSP default Approval clock is invalid")
    if not isinstance(product_policy_revision, str) or not product_policy_revision:
        raise ValueError("Coding LSP Product policy revision is invalid")
    return CodingLspPluginOptInRequest(
        approval_owner=_CodingLspDefaultPluginApprovalOwner(
            clock=clock,
            product_policy_revision=product_policy_revision,
        )
    )


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
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Release verified revision handles before ownership transfers to Session."""

        if self._closed:
            return
        primary_error: BaseException | None = None
        try:
            self.runtime.close()
        except BaseException as exc:
            primary_error = exc
        try:
            if self.state_cleanup is not None:
                self.state_cleanup()
        except BaseException as cleanup_error:
            if primary_error is None:
                primary_error = cleanup_error
            else:
                primary_error.add_note(
                    f"Coding LSP state cleanup also failed: {cleanup_error}"
                )
        finally:
            self._closed = True
        if primary_error is not None:
            raise primary_error


@dataclass(slots=True)
class CodingLspPluginOptInPreparation:
    """Definition-approved closure compiled before host Provider construction."""

    request: CodingLspPluginOptInRequest = field(repr=False)
    runtime: PluginRuntimeResolution = field(repr=False)
    selection: PluginSelection
    product: ProductPluginCompositionPreparation
    provider_owner_authority: CapabilityProviderOwnerAuthority = field(repr=False)
    tool_owner_authority: OwnerContributionAuthority = field(repr=False)
    scope_id: str
    state_root: Path
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _closed: bool = field(default=False, init=False, repr=False)
    _transferred: bool = field(default=False, init=False, repr=False)

    @property
    def product_composition(self):
        return self.product.product_composition

    def bind_workspace(
        self,
        workspace_binding: CapabilityBundleProviderBinding,
        *,
        host_boot_id: str,
        tool_mode: CapabilityMountMode,
        clock: Callable[[], int],
    ) -> CodingLspPluginOptInAssembly:
        if self._closed or self._transferred:
            raise RuntimeError("Coding LSP Plugin preparation is no longer available")
        _validate_workspace_binding(
            workspace_binding,
            host_boot_id=host_boot_id,
            tool_mode=tool_mode,
            clock=clock,
        )
        try:
            plugin_assembly = self.product.bind_host_providers(
                (workspace_binding.provider,)
            )
            component_host, session_inputs = _approve_activation_and_bind_inputs(
                self.selection,
                plugin_assembly,
                request=self.request,
                provider_authority=self.provider_owner_authority,
                scope_id=self.scope_id,
                state_root=self.state_root,
                host_boot_id=host_boot_id,
                clock=clock,
            )
            tool_owner = _build_tool_owner(
                self.selection,
                plugin_assembly,
                authority=self.tool_owner_authority,
                scope_id=self.scope_id,
                mode=tool_mode,
                clock=clock,
            )
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup_error:
                error.add_note(
                    f"Coding LSP preparation cleanup also failed: {cleanup_error}"
                )
            raise
        self._transferred = True
        return CodingLspPluginOptInAssembly(
            runtime=self.runtime,
            selection=self.selection,
            plugin_assembly=plugin_assembly,
            component_host=component_host,
            session_inputs=session_inputs,
            tool_owner=tool_owner,
            provider_owner_authority=self.provider_owner_authority,
            tool_owner_authority=self.tool_owner_authority,
            scope_id=self.scope_id,
            state_root=self.state_root,
            state_cleanup=self.state_cleanup,
        )

    def close(self) -> None:
        if self._closed or self._transferred:
            return
        primary_error: BaseException | None = None
        try:
            self.runtime.close()
        except BaseException as exc:
            primary_error = exc
        try:
            if self.state_cleanup is not None:
                self.state_cleanup()
        except BaseException as cleanup_error:
            if primary_error is None:
                primary_error = cleanup_error
            else:
                primary_error.add_note(
                    f"Coding LSP state cleanup also failed: {cleanup_error}"
                )
        finally:
            self._closed = True
        if primary_error is not None:
            raise primary_error


def prepare_coding_lsp_plugin_opt_in(
    request: CodingLspPluginOptInRequest,
    *,
    session_id: str,
    config: CodingLspPluginConfigV1,
    package_materializer: CodingPackageMaterializer,
    state_root: str | Path,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
    coding_product_plan_seed: ProductPluginPlanSeed | None = None,
    state_cleanup: Callable[[], None] | None = None,
) -> CodingLspPluginOptInPreparation:
    """Resolve, approve and compile once without constructing host Providers."""

    _validate_preparation_inputs(
        request,
        session_id=session_id,
        config=config,
        package_materializer=package_materializer,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
    )
    _read_clock(clock)
    if state_cleanup is not None and not callable(state_cleanup):
        raise TypeError("Coding LSP Plugin state cleanup is invalid")
    resolved_state_root = Path(state_root).expanduser().resolve()
    scope_id = f"session:{session_id.strip()}"

    try:
        resolved_state_root.mkdir(parents=True, exist_ok=True)
        authority = PluginResolutionAuthority()
        inspection = authority.inspect(
            PluginSource(path=coding_lsp_default_plugin_root())
        )
        runtime = authority.publish_runtime(
            (inspection,),
            binding_store=package_materializer,
        )
    except BaseException as error:
        if state_cleanup is not None:
            try:
                state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(f"Coding LSP state cleanup also failed: {cleanup_error}")
        raise
    try:
        resolved_product_seed = coding_product_plan_seed or (
            coding_base_plugin_assembly.plan_seed
            if coding_base_plugin_assembly is not None
            else None
        )
        tool_authority = _tool_owner_authority()
        plan_seed = _prepare_selection_plan_seed(
            runtime,
            scope_id=scope_id,
            config=config,
            coding_product_plan_seed=resolved_product_seed,
            tool_authority=tool_authority,
        )
        selection = _finalize_selection(
            plan_seed,
            request=request,
            scope_id=scope_id,
            state_root=resolved_state_root,
            clock=clock,
        )
        selection_seed = complete_coding_package_plugin_selection_seed(
            plan_seed,
            selection=selection,
        )
        provider_authority = _provider_owner_authority()
        product = prepare_product_plugin_composition(
            _assembly_request(
                selection_seed,
                provider_authority=provider_authority,
            ),
            evaluated_at=_read_clock(clock),
        )
        return CodingLspPluginOptInPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authority=provider_authority,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=resolved_state_root,
            state_cleanup=state_cleanup,
        )
    except BaseException as error:
        try:
            runtime.close()
        except BaseException as cleanup_error:
            error.add_note(f"Coding LSP revision cleanup also failed: {cleanup_error}")
        if state_cleanup is not None:
            try:
                state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(f"Coding LSP state cleanup also failed: {cleanup_error}")
        raise


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
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
    coding_product_plan_seed: ProductPluginPlanSeed | None = None,
    state_cleanup: Callable[[], None] | None = None,
) -> CodingLspPluginOptInAssembly:
    """Compatibility facade over the prepare-once, bind-host phases."""

    preparation = prepare_coding_lsp_plugin_opt_in(
        request,
        session_id=session_id,
        config=config,
        package_materializer=package_materializer,
        state_root=state_root,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
        state_cleanup=state_cleanup,
    )
    return preparation.bind_workspace(
        workspace_binding,
        host_boot_id=host_boot_id,
        tool_mode=tool_mode,
        clock=clock,
    )


def _build_tool_owner(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    authority: OwnerContributionAuthority,
    scope_id: str,
    mode: CapabilityMountMode,
    clock: Callable[[], int],
) -> CodingLspToolOwner:
    matches = tuple(
        item
        for item in plugin_assembly.product_composition.catalog_admissions
        if item.plugin_id == _PLUGIN_ID
        and item.contribution_id == "coding-lsp-tools"
        and item.owner_id == _TOOL_OWNER_ID
        and item.contribution_kind == "tool_pack"
    )
    if len(matches) != 1:
        raise ValueError("Coding LSP Tool owner requires one exact admission")
    [admission] = matches
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
        return selection.plan.context.policy_revision

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
        return selection.plan.context.policy_revision

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
    seed: ProductPluginPlanSeed,
    *,
    request: CodingLspPluginOptInRequest,
    scope_id: str,
    state_root: Path,
    clock: Callable[[], int],
) -> PluginSelection:
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
        seed.packages,
        bindings=seed.bindings,
        plan=seed.plan,
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
            seed.packages,
            bindings=seed.bindings,
            plan=seed.plan,
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


def _prepare_selection_plan_seed(
    runtime: PluginRuntimeResolution,
    *,
    scope_id: str,
    config: CodingLspPluginConfigV1,
    coding_product_plan_seed: ProductPluginPlanSeed | None,
    tool_authority: OwnerContributionAuthority,
) -> ProductPluginPlanSeed:
    [package] = runtime.packages
    [binding] = runtime.bindings
    contributions = package.contribution_index.items
    base_plan = coding_product_plan_seed.plan if coding_product_plan_seed else None
    policy_revision = (
        base_plan.context.policy_revision
        if base_plan is not None
        else _PRODUCT_POLICY_REVISION
    )
    base_instance_refs = (
        base_plan.context.instance_revision_refs if base_plan is not None else ()
    )
    base_plugin_ids = base_plan.selected_plugin_ids if base_plan is not None else ()
    base_contributions = (
        base_plan.selected_contributions if base_plan is not None else ()
    )
    base_trust = base_plan.source_trust_snapshots if base_plan is not None else ()
    base_config_entries = (
        base_plan.effective_configuration_set.entries if base_plan is not None else ()
    )
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id=CODING_PRODUCT_ID,
            scope_id=scope_id,
            policy_revision=policy_revision,
            instance_revision_refs=tuple(
                sorted(
                    (
                        *base_instance_refs,
                        PluginInstanceRevisionRef(
                            instance_id=f"{_PLUGIN_ID}@{scope_id}",
                            plugin_id=_PLUGIN_ID,
                            revision=1,
                        ),
                    ),
                    key=lambda item: (
                        item.plugin_id,
                        item.instance_id,
                        item.revision,
                    ),
                )
            ),
        ),
        selected_plugin_ids=tuple(sorted((*base_plugin_ids, _PLUGIN_ID))),
        selected_contributions=tuple(
            sorted(
                (
                    *base_contributions,
                    *tuple(
                        PluginContributionRef(_PLUGIN_ID, item.contribution_id)
                        for item in contributions
                    ),
                )
            )
        ),
        source_trust_snapshots=tuple(
            sorted(
                (
                    *base_trust,
                        PluginSourceTrustSnapshotV1(
                            plugin_id=_PLUGIN_ID,
                            package_source_identity=binding.source_identity,
                        source_trust_class=_SOURCE_TRUST_CLASS,
                        source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                        trusted=True,
                    ),
                ),
                key=lambda item: (item.plugin_id, item.package_source_identity),
            )
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        *base_config_entries,
                        *tuple(
                            PluginEffectiveConfigurationEntry(
                                plugin_id=_PLUGIN_ID,
                                contribution_id=item.contribution_id,
                                configuration=(
                                    config.to_dict()
                                    if item.kind == "capability_provider"
                                    else {}
                                ),
                            )
                            for item in contributions
                        ),
                    ),
                    key=lambda item: (item.plugin_id, item.contribution_id),
                )
            )
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
    package_bindings = tuple(
        sorted(
            (
                *(
                    tuple(
                        zip(
                            coding_product_plan_seed.packages,
                            coding_product_plan_seed.bindings,
                            strict=True,
                        )
                    )
                    if coding_product_plan_seed is not None
                    else ()
                ),
                (package, binding),
            ),
            key=lambda item: item[0].manifest.name,
        )
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple(item[0] for item in package_bindings),
        bindings=tuple(item[1] for item in package_bindings),
        owner_bindings=(
            *(
                coding_product_plan_seed.owner_bindings
                if coding_product_plan_seed is not None
                else ()
            ),
            ProductContributionOwnerBinding(authority=tool_authority),
        ),
    )


def _assembly_request(
    selection_seed: ProductPluginSelectionSeed,
    *,
    provider_authority: CapabilityProviderOwnerAuthority,
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
            selection=selection_seed.selection,
            owner_bindings=selection_seed.owner_bindings,
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


def _validate_default_definition_subject(
    subject: PluginExecutionApprovalSubject,
    *,
    product_policy_revision: str,
) -> None:
    if (
        subject.plugin_id != _PLUGIN_ID
        or subject.product_id != CODING_PRODUCT_ID
        or not subject.scope_id.startswith("session:")
        or subject.scope_id == "session:"
        or subject.policy_revision != product_policy_revision
        or subject.entrypoint != _DEFAULT_DEFINITION_ENTRYPOINT
        or subject.source_trust_class != _SOURCE_TRUST_CLASS
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or subject.requested_authorities != ("filesystem", "process")
        or subject.allowed_authority_ceiling != ("filesystem", "process")
        or subject.instance_revision_ref.instance_id
        != f"{_PLUGIN_ID}@{subject.scope_id}"
        or subject.instance_revision_ref.plugin_id != _PLUGIN_ID
        or subject.instance_revision_ref.revision != 1
    ):
        raise CodingLspPluginOptInError(
            "Coding LSP default Definition Subject is outside Product policy.",
            code="coding_lsp_default_definition_subject_rejected",
        )


def _validate_default_activation_subject(
    subject: ContributionActivationApprovalSubject,
    *,
    product_policy_revision: str,
) -> None:
    if (
        subject.capability_id != CODING_LSP_CAPABILITY_DEFINITION.capability_id
        or subject.owner_id != CODING_LSP_CAPABILITY_DEFINITION.owner_id
        or subject.provider_id != _PROVIDER_ID
        or subject.plugin_id != _PLUGIN_ID
        or subject.contribution_id != _DEFAULT_PROVIDER_CONTRIBUTION_ID
        or subject.product_id != CODING_PRODUCT_ID
        or not subject.scope_id.startswith("session:")
        or subject.scope_id == "session:"
        or subject.source_trust_class != _SOURCE_TRUST_CLASS
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or subject.product_policy_revision != product_policy_revision
        or subject.owner_policy_revision != _PROVIDER_OWNER_POLICY_REVISION
        or subject.revocation_epoch != 0
        or subject.effective_facets
        != tuple(sorted(CODING_LSP_CAPABILITY_DEFINITION.facets))
        or subject.effective_authorities != ("filesystem", "process")
        or subject.execution_model != "in_process"
        or subject.instance_revision_ref.instance_id
        != f"{_PLUGIN_ID}@{subject.scope_id}"
        or subject.instance_revision_ref.plugin_id != _PLUGIN_ID
        or subject.instance_revision_ref.revision != 1
    ):
        raise CodingLspPluginOptInError(
            "Coding LSP default Activation Subject is outside Product policy.",
            code="coding_lsp_default_activation_subject_rejected",
        )


def _default_approval_authorization() -> PluginApprovalAuthorizationV1:
    return PluginApprovalAuthorizationV1.direct(
        actor_id=_DEFAULT_APPROVAL_ACTOR_ID,
        source=_DEFAULT_APPROVAL_SOURCE,
    )


def _validate_preparation_inputs(
    request: CodingLspPluginOptInRequest,
    *,
    session_id: str,
    config: CodingLspPluginConfigV1,
    package_materializer: CodingPackageMaterializer,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None,
    coding_product_plan_seed: ProductPluginPlanSeed | None,
) -> None:
    if not isinstance(request, CodingLspPluginOptInRequest):
        raise TypeError("Coding LSP Plugin opt-in request is invalid")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding LSP Plugin opt-in Session id must not be empty")
    if not isinstance(config, CodingLspPluginConfigV1):
        raise TypeError("Coding LSP Plugin opt-in configuration is invalid")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Coding LSP Plugin opt-in requires Coding materialization")
    if coding_base_plugin_assembly is not None:
        if not isinstance(coding_base_plugin_assembly, CodingBasePluginAssembly):
            raise TypeError("Coding LSP Plugin base assembly is invalid")
        expected_scope = f"session:{session_id.strip()}"
        if coding_base_plugin_assembly.scope_id != expected_scope:
            raise ValueError("Coding base and LSP Plugin scopes do not match")
        if coding_base_plugin_assembly.package.revision_handle.closed:
            raise RuntimeError("Coding base Plugin revision is unavailable")
    if coding_product_plan_seed is not None:
        if not isinstance(coding_product_plan_seed, ProductPluginPlanSeed):
            raise TypeError("Coding LSP Product plan seed is invalid")
        if (
            coding_base_plugin_assembly is not None
            and _BASE_PLUGIN_ID
            not in coding_product_plan_seed.plan.selected_plugin_ids
        ):
            raise ValueError("Coding LSP Product seed omits coding.base")
    if not callable(clock):
        raise TypeError("Coding LSP Plugin opt-in clock is invalid")


def _validate_workspace_binding(
    workspace_binding: CapabilityBundleProviderBinding,
    *,
    host_boot_id: str,
    tool_mode: CapabilityMountMode,
    clock: Callable[[], int],
) -> None:
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
    _validate_preparation_inputs(
        request,
        session_id=session_id,
        config=config,
        package_materializer=package_materializer,
        clock=clock,
        coding_base_plugin_assembly=None,
        coding_product_plan_seed=None,
    )
    _validate_workspace_binding(
        workspace_binding,
        host_boot_id=host_boot_id,
        tool_mode=tool_mode,
        clock=clock,
    )


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
    "CodingLspPluginOptInPreparation",
    "CodingLspPluginOptInRequest",
    "assemble_coding_lsp_plugin_opt_in",
    "create_coding_lsp_default_plugin_opt_in_request",
    "prepare_coding_lsp_plugin_opt_in",
]
