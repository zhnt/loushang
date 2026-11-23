"""Private Product composer for Coding's first-party Capability Plugins."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from loushang.coding.composition.base_plugin import CodingBasePluginAssembly
from loushang.coding.composition.capability_specs import (
    CODING_CAPABILITY_PLUGIN_IDS,
    CODING_CAPABILITY_PLUGIN_SPEC_BY_ID,
    CodingCapabilityPluginConfig,
    CodingCapabilityToolOwner,
    ordered_coding_capability_plugin_specs,
)
from loushang.coding.composition.dependency_grants import (
    coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycle,
    CodingPluginManagementChange,
    CodingPluginSessionLease,
)
from loushang.coding.resources.catalog import (
    complete_coding_package_plugin_selection_seed as complete_coding_package_plugin_selection_seed,
)
from loushang.coding.resources.runtime import CodingPackageMaterializer
from loushang.coding.resume.activation_attempt import (
    CodingResumeRecoveryRequired as CodingResumeRecoveryRequired,
)
from loushang.coding.resume.activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
)
from loushang.coding.resume.plugin_effects import _require_resume_effect_owners
from loushang.harness.approval._plugin_resume_parents import (
    _PluginResumeParentMethods,
    plugin_resume_journals,
)
from loushang.harness.approval.plugin_activation import (
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationDecisionRecordV1,
)
from loushang.harness.approval.plugin_activation import (
    PluginActivationJournalError as PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionJournalError as PluginExecutionJournalError,
)
from loushang.harness.capabilities import (
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.component_host import CapabilityComponentHost
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_management.assembly import (
    _ManagedPluginErrors,
    _resolve_managed_plugin_runtimes,
)
from loushang.harness.resources.plugins.authority import (
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.selection import (
    PluginEffectiveConfigurationEntry,
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
    PluginSelection,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt
from loushang.harness.session._cleanup import run_cleanup_steps
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.session.plugin_lifecycle._composition_cleanup import (
    _PreparationFailureCleanup,
    _PreparedCompositionCleanup,
    _PublishedCompositionCleanup,
)
from loushang.harness.session.plugin_lifecycle._publication import _OwnerLeaseSet
from loushang.harness.session.product_composition_assembly import (
    ProductCapabilityProviderOwnerBinding,
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssembly,
    ProductPluginCompositionAssemblyRequest,
    ProductPluginCompositionPreparation,
    ProductPluginPlanSeed,
    ProductPluginSelectionSeed,
    bind_selected_registration_authority,
    build_product_plugin_selection_plan,
)
from loushang.harness.session.product_composition_assembly import (
    prepare_product_plugin_composition as prepare_product_plugin_composition,
)

_BASE_PLUGIN_ID = "coding.base"
_TOOL_OWNER_ID = "coding.tools"
_PRODUCT_POLICY_REVISION = "coding-capability-plugins-2"
_SOURCE_TRUST_CLASS = "host-equivalent-local"
_SOURCE_TRUST_POLICY_REVISION = "coding-capability-plugin-source-trust-2"
_TOOL_OWNER_POLICY_REVISION = "coding-capability-tools-owner-2"
_DEFAULT_APPROVAL_ACTOR_ID = "product:coding"
_DEFAULT_APPROVAL_SOURCE = "coding-capability-plugin-product-policy"
# Keep Product-issued activation authority live for the full default Provider
# admission window. Both remain bounded; the Session still has to recompose once
# the 300-second admission expires.
_DEFAULT_APPROVAL_TTL_MS = 300_000
_DEFAULT_DEFINITION_ENTRYPOINT = "definition.py:declare"
_PLUGIN_IDS = CODING_CAPABILITY_PLUGIN_IDS
_RESUME_PLUGIN_LABEL = "Coding Resume Plugin"
_DEFINITION_OWNER = "harness.plugin-execution"
_ACTIVATION_OWNER = "harness.plugin-activation"
_DEFINITION_DECISIONS_FILENAME = "definition-decisions.jsonl"
_ACTIVATION_DECISIONS_FILENAME = "activation-decisions.jsonl"


class CodingCapabilityPluginApprovalOwner(Protocol):
    """Sole issuer ports retained by one Product-owned composition request."""

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


class _CodingCapabilityApprovalInstanceBinder(Protocol):
    """Optional neutral port for issuers that bind exact managed instances."""

    def bind_selected_instances(
        self,
        *,
        selected_plugin_ids: frozenset[str],
        instance_revision_refs: Mapping[str, PluginInstanceRevisionRef],
    ) -> CodingCapabilityPluginApprovalOwner: ...


class CodingCapabilityPluginCompositionError(RuntimeError):
    """Stable fail-closed Product error before Session composition exists."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingResumePluginParents(_PluginResumeParentMethods):
    """Two inert native lookups from one frozen Resume intent, without grants."""

    definition: ResumeEffectParentContextV1
    activation: ResumeEffectParentContextV1

    def __post_init__(self) -> None:
        if any(
            type(item) is not ResumeEffectParentContextV1
            for item in (
                self.definition,
                self.activation,
            )
        ):
            raise TypeError("Coding Resume requires exact native parent contexts")
        if (
            self.definition.owner_id != "harness.plugin-execution"
            or self.activation.owner_id != "harness.plugin-activation"
            or any(
                getattr(self.definition, name) != getattr(self.activation, name)
                for name in (
                    "product_id",
                    "session_id",
                    "attempt_id",
                    "request_id",
                    "intent_digest",
                )
            )
            or self.definition.product_id != CODING_PRODUCT_ID
        ):
            raise ValueError("Coding Resume Plugin parents differ from one intent")

    def _journals(
        self, *, session_id: str, state_root: Path, clock: Callable[[], int]
    ) -> tuple[PluginExecutionDecisionJournal, PluginActivationDecisionJournal]:
        if self.definition.session_id != session_id:
            raise ValueError(
                f"{_RESUME_PLUGIN_LABEL} parents belong to another Session"
            )
        return plugin_resume_journals(
            session_id,
            state_root / _DEFINITION_DECISIONS_FILENAME,
            state_root / _ACTIVATION_DECISIONS_FILENAME,
            clock=clock,
            require_resume_context=True,
        )

    def _sealed_parent_error(
        self, *, definition: bool
    ) -> CodingCapabilityPluginCompositionError:
        if definition:
            return CodingCapabilityPluginCompositionError(
                "Resume Definition enumeration is sealed.",
                code="coding_resume_definition_parent_sealed",
            )
        return CodingCapabilityPluginCompositionError(
            "Resume Component enumeration is sealed.",
            code="coding_resume_activation_parent_sealed",
        )


def prepare_coding_resume_plugin_effect_owners(
    *, session_id: str, state_root: Path
) -> tuple[CodingResumeEffectOwnerV1, ...]:
    """Freeze the two original Plugin journal lookup obligations without I/O."""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(f"{_RESUME_PLUGIN_LABEL} owner Session id is invalid")
    if not isinstance(state_root, Path) or not state_root.is_absolute():
        raise ValueError(f"{_RESUME_PLUGIN_LABEL} owner state root is invalid")
    definition, activation = plugin_resume_journals(
        session_id,
        state_root / _DEFINITION_DECISIONS_FILENAME,
        state_root / _ACTIVATION_DECISIONS_FILENAME,
    )
    return tuple(
        sorted(
            (
                CodingResumeEffectOwnerV1(
                    _DEFINITION_OWNER,
                    definition.resume_parent_scope_digest(product_id=CODING_PRODUCT_ID),
                    definition.resume_parent_contract_digest,
                    ("declaration",),
                ),
                CodingResumeEffectOwnerV1(
                    _ACTIVATION_OWNER,
                    activation.resume_parent_scope_digest(product_id=CODING_PRODUCT_ID),
                    activation.resume_parent_contract_digest,
                    ("activation",),
                ),
            ),
            key=lambda owner: owner.identity,
        )
    )


def require_coding_resume_plugin_effect_settlement(
    attempt: CodingActivationAttemptV2,
    receipt: Mapping[str, object],
    *,
    state_root: Path,
    clock: Callable[[], int],
    allowed_external_owner_ids: frozenset[str] = frozenset(),
) -> None:
    """Reconcile the audited first-party startup closure in original journals.

    This adapter covers only the checked-in LSP and Architecture declaration and
    factory closures. Their factories construct lazy in-memory owners: process
    launch, workspace scans and private-cache I/O begin only on later Tool use.
    The surrounding candidate gate must separately prove that the receipt still
    names the current Product-selected first-party package revisions.
    """

    if type(attempt) is not CodingActivationAttemptV2:
        raise TypeError(
            f"{_RESUME_PLUGIN_LABEL} settlement requires an exact v2 intent"
        )
    if not isinstance(receipt, Mapping):
        raise TypeError(
            f"{_RESUME_PLUGIN_LABEL} settlement requires a current receipt"
        )
    owners = {owner.owner_id: owner for owner in attempt.effect_owners}
    _require_resume_effect_owners(
        attempt,
        set(owners),
        {_DEFINITION_OWNER, _ACTIVATION_OWNER} | allowed_external_owner_ids,
    )
    parents = CodingResumePluginParents(
        definition=attempt.parent_context(owners[_DEFINITION_OWNER]),
        activation=attempt.parent_context(owners[_ACTIVATION_OWNER]),
    )
    parents.require_settled_revisions(
        receipt,
        session_id=attempt.session_id,
        state_root=state_root,
        clock=clock,
        capability_plugin_ids=CODING_CAPABILITY_PLUGIN_IDS,
        unsettled=lambda: CodingResumeRecoveryRequired("input.effect_settlement_unknown"),
    )


@dataclass(slots=True)
class CodingCapabilityPluginCleanupCustodian(_PreparationFailureCleanup):
    """Retryable owner for a preparation that failed after acquiring evidence."""

    _cleanup_label = "Coding Capability"
    _failure_attribute = "_coding_capability_plugin_cleanup_custodian"

    runtime: PluginRuntimeResolution = field(repr=False)
    management_leases: Mapping[str, CodingPluginSessionLease] = field(repr=False)
    management_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
    )
    state_cleanup: Callable[[], None] | None = field(default=None, repr=False)
    private_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
    )
    _runtime_closed: bool = field(default=False, init=False, repr=False)
    _released_plugin_ids: set[str] = field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _management_released: bool = field(default=False, init=False, repr=False)
    _state_cleaned: bool = field(default=False, init=False, repr=False)
    _private_state_cleaned: bool = field(default=False, init=False, repr=False)


def coding_capability_plugin_failure_custodian(
    error: BaseException,
) -> CodingCapabilityPluginCleanupCustodian | None:
    """Recover a retryable preparation cleanup owner from an exception chain."""

    return CodingCapabilityPluginCleanupCustodian.retained_on(error)


@dataclass(frozen=True, slots=True)
class CodingCapabilityPluginCompositionRequest:
    """Product request carrying approval issuance, never authority facts."""

    approval_owner: CodingCapabilityPluginApprovalOwner = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not all(
            callable(getattr(self.approval_owner, member, None))
            for member in ("approve_definition", "approve_activation")
        ):
            raise TypeError("Coding Capability composition requires an Approval owner")


@dataclass(frozen=True, slots=True)
class _CodingDefaultCapabilityPluginApprovalOwner:
    """Approve only Coding's selected checked-in Capability Plugin closure."""

    clock: Callable[[], int] = field(repr=False, compare=False)
    plugin_ids: frozenset[str]
    instance_revision_refs: Mapping[str, PluginInstanceRevisionRef] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    approval_source: str = _DEFAULT_APPROVAL_SOURCE
    product_policy_revision: str = _PRODUCT_POLICY_REVISION
    source_trust_policy_revision: str = _SOURCE_TRUST_POLICY_REVISION

    def bind_selected_instances(
        self,
        *,
        selected_plugin_ids: frozenset[str],
        instance_revision_refs: Mapping[str, PluginInstanceRevisionRef],
    ) -> CodingCapabilityPluginApprovalOwner:
        selected = selected_plugin_ids & self.plugin_ids
        if not selected:
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability approval has no selected managed instance.",
                code="coding_capability_approval_selection_empty",
            )
        selected_refs = {
            plugin_id: instance_revision_refs[plugin_id]
            for plugin_id in selected
            if plugin_id in instance_revision_refs
        }
        if frozenset(selected_refs) != selected:
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability approval lacks an exact managed instance.",
                code="coding_capability_approval_instance_missing",
            )
        if self.instance_revision_refs is not None:
            if dict(self.instance_revision_refs) != selected_refs:
                raise CodingCapabilityPluginCompositionError(
                    "Coding Capability approval instance changed after binding.",
                    code="coding_capability_approval_instance_changed",
                )
            return self
        return _CodingDefaultCapabilityPluginApprovalOwner(
            clock=self.clock,
            plugin_ids=selected,
            instance_revision_refs=selected_refs,
            approval_source=self.approval_source,
            product_policy_revision=self.product_policy_revision,
            source_trust_policy_revision=self.source_trust_policy_revision,
        )

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1:
        _validate_default_definition_subject(
            subject,
            plugin_ids=self.plugin_ids,
            product_policy_revision=self.product_policy_revision,
            source_trust_policy_revision=self.source_trust_policy_revision,
            instance_revision_refs=self.instance_revision_refs,
        )
        now = _read_clock(self.clock)
        return journal.issue_execution_decision(
            subject,
            disposition="approved",
            authorization=_default_approval_authorization(self.approval_source),
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
            plugin_ids=self.plugin_ids,
            product_policy_revision=self.product_policy_revision,
            source_trust_policy_revision=self.source_trust_policy_revision,
            instance_revision_refs=self.instance_revision_refs,
        )
        now = _read_clock(self.clock)
        return journal.issue_activation_decision(
            subject,
            disposition="approved",
            authorization=_default_approval_authorization(self.approval_source),
            issued_at_unix_ms=now,
            expires_at_unix_ms=now + _DEFAULT_APPROVAL_TTL_MS,
            expected_journal_revision=journal.snapshot().journal_revision,
        )


def create_coding_capability_plugin_composition_request(
    *,
    clock: Callable[[], int],
    plugin_ids: frozenset[str],
    approval_source: str = _DEFAULT_APPROVAL_SOURCE,
    product_policy_revision: str = _PRODUCT_POLICY_REVISION,
    source_trust_policy_revision: str = _SOURCE_TRUST_POLICY_REVISION,
) -> CodingCapabilityPluginCompositionRequest:
    """Create Coding's exact-policy request for selected checked-in Plugins."""

    if not callable(clock):
        raise TypeError("Coding Capability Plugin Approval clock is invalid")
    if not plugin_ids or not plugin_ids.issubset(_PLUGIN_IDS):
        raise ValueError("Coding Capability Plugin selection is invalid")
    if not isinstance(approval_source, str) or not approval_source:
        raise ValueError("Coding Capability Plugin Approval source is invalid")
    if not isinstance(product_policy_revision, str) or not product_policy_revision:
        raise ValueError("Coding Capability Product policy revision is invalid")
    if (
        not isinstance(source_trust_policy_revision, str)
        or not source_trust_policy_revision
    ):
        raise ValueError("Coding Capability Source trust policy revision is invalid")
    return CodingCapabilityPluginCompositionRequest(
        approval_owner=_CodingDefaultCapabilityPluginApprovalOwner(
            clock=clock,
            plugin_ids=plugin_ids,
            approval_source=approval_source,
            product_policy_revision=product_policy_revision,
            source_trust_policy_revision=source_trust_policy_revision,
        )
    )


def _bind_default_approval_request_to_plan(
    request: CodingCapabilityPluginCompositionRequest,
    seed: ProductPluginPlanSeed,
) -> CodingCapabilityPluginCompositionRequest:
    """Narrow the built-in issuer to the exact managed instances in the plan."""

    binder = getattr(request.approval_owner, "bind_selected_instances", None)
    if not callable(binder):
        return request
    instance_revision_refs = {
        item.plugin_id: item for item in seed.plan.context.instance_revision_refs
    }
    instance_binder = cast(
        _CodingCapabilityApprovalInstanceBinder, request.approval_owner
    )
    return CodingCapabilityPluginCompositionRequest(
        approval_owner=instance_binder.bind_selected_instances(
            selected_plugin_ids=frozenset(seed.plan.selected_plugin_ids),
            instance_revision_refs=instance_revision_refs,
        )
    )


@dataclass(slots=True)
class CodingCapabilityPluginCompositionAssembly(_PublishedCompositionCleanup):
    """Approved Product closure awaiting bootstrap and Graph ownership transfer."""

    _cleanup_label = "Coding Capability"

    runtime: PluginRuntimeResolution = field(repr=False)
    selection: PluginSelection
    plugin_assembly: ProductPluginCompositionAssembly
    component_host: CapabilityComponentHost = field(repr=False)
    session_inputs: SessionCapabilityCompositionInputs
    tool_owners: Mapping[str, CodingCapabilityToolOwner] = field(repr=False)
    provider_owner_authorities: Mapping[str, CapabilityProviderOwnerAuthority] = field(
        repr=False
    )
    tool_owner_authority: OwnerContributionAuthority = field(repr=False)
    scope_id: str
    state_root: Path
    management_leases: Mapping[str, CodingPluginSessionLease] = field(
        default_factory=dict,
        repr=False,
    )
    management_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    private_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _runtime_closed: bool = field(default=False, init=False, repr=False)
    _management_released: bool = field(default=False, init=False, repr=False)
    _state_cleaned: bool = field(default=False, init=False, repr=False)
    _private_state_cleaned: bool = field(default=False, init=False, repr=False)
    _runtime_retired: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def tool_owner_for(self, plugin_id: str) -> CodingCapabilityToolOwner | None:
        """Return a selected Tool owner without encoding Provider identities."""

        return self.tool_owners.get(plugin_id)

    def evaluate_management_changes(
        self,
    ) -> Mapping[str, CodingPluginManagementChange]:
        return {
            plugin_id: lease.evaluate_management_change()
            for plugin_id, lease in self.management_leases.items()
        }

    def claim_runtime(self, runtime_claim_id: str) -> None:
        for lease in self.management_leases.values():
            lease.claim_runtime(runtime_claim_id)

    def prepare_owner_generations(
        self,
        receipts: Mapping[str, tuple[OwnerGenerationRetirementReceipt, ...]],
    ) -> None:
        _OwnerLeaseSet(self.management_leases).prepare_owner_generations(receipts)

    def publish_owner_generations(
        self,
        receipts: Mapping[str, tuple[OwnerGenerationRetirementReceipt, ...]],
    ) -> None:
        _OwnerLeaseSet(self.management_leases).publish_owner_generations(receipts)

    def retire_owner_generations(
        self,
        receipts: Mapping[str, tuple[OwnerGenerationRetirementReceipt, ...]],
    ) -> None:
        _OwnerLeaseSet(self.management_leases).retire_owner_generations(receipts)


@dataclass(slots=True)
class CodingCapabilityPluginCompositionPreparation(_PreparedCompositionCleanup):
    """Definition-approved closure compiled before host Provider construction."""

    _cleanup_label = "Coding Capability"

    request: CodingCapabilityPluginCompositionRequest = field(repr=False)
    runtime: PluginRuntimeResolution = field(repr=False)
    selection: PluginSelection
    product: ProductPluginCompositionPreparation
    provider_owner_authorities: Mapping[str, CapabilityProviderOwnerAuthority] = field(
        repr=False
    )
    tool_owner_authority: OwnerContributionAuthority = field(repr=False)
    scope_id: str
    state_root: Path
    management_leases: Mapping[str, CodingPluginSessionLease] = field(
        default_factory=dict,
        repr=False,
    )
    management_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    private_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    selection_recheck: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    resume_parents: CodingResumePluginParents | None = field(default=None, repr=False)
    _runtime_closed: bool = field(default=False, init=False, repr=False)
    _management_released: bool = field(default=False, init=False, repr=False)
    _state_cleaned: bool = field(default=False, init=False, repr=False)
    _private_state_cleaned: bool = field(default=False, init=False, repr=False)
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
        tool_modes: Mapping[str, CapabilityMountMode],
        clock: Callable[[], int],
    ) -> CodingCapabilityPluginCompositionAssembly:
        if self._closed or self._transferred:
            raise RuntimeError(
                "Coding Capability Plugin preparation is no longer available"
            )
        _validate_workspace_binding(
            workspace_binding,
            host_boot_id=host_boot_id,
            tool_modes=tool_modes,
            selected_capability_ids=frozenset(self.provider_owner_authorities.keys()),
            clock=clock,
        )
        try:
            if self.selection_recheck is not None:
                self.selection_recheck()
            plugin_assembly = self.product.bind_host_providers(
                (workspace_binding.provider,)
            )
            component_host, session_inputs = _approve_activation_and_bind_inputs(
                self.selection,
                plugin_assembly,
                request=self.request,
                provider_authorities=self.provider_owner_authorities,
                scope_id=self.scope_id,
                state_root=self.state_root,
                host_boot_id=host_boot_id,
                clock=clock,
                resume_parents=self.resume_parents,
            )
            tool_owners = _build_tool_owners(
                self.selection,
                plugin_assembly,
                authority=self.tool_owner_authority,
                scope_id=self.scope_id,
                tool_modes=tool_modes,
                clock=clock,
            )
        except BaseException as error:
            run_cleanup_steps(
                error,
                (("Coding Capability Plugin preparation cleanup", self.close),),
            )
            raise
        self._transferred = True
        return CodingCapabilityPluginCompositionAssembly(
            runtime=self.runtime,
            selection=self.selection,
            plugin_assembly=plugin_assembly,
            component_host=component_host,
            session_inputs=session_inputs,
            tool_owners=tool_owners,
            provider_owner_authorities=self.provider_owner_authorities,
            tool_owner_authority=self.tool_owner_authority,
            scope_id=self.scope_id,
            state_root=self.state_root,
            management_leases=self.management_leases,
            management_state_cleanup=self.management_state_cleanup,
            state_cleanup=self.state_cleanup,
            private_state_cleanup=self.private_state_cleanup,
        )


_MANAGED_ASSEMBLY_ERRORS = _ManagedPluginErrors(
    facts={
        "management_selection_incomplete": (
            "Enabled {plugin_id} lacks exact lifecycle evidence.",
            "coding_capability_management_selection_incomplete",
        ),
        "binding_replay_invalid": (
            "Selected {plugin_id} binding lock is invalid.",
            "coding_capability_binding_replay_invalid",
        ),
        "binding_replay_unavailable": (
            "Selected {plugin_id} binding is unavailable.",
            "coding_capability_binding_replay_unavailable",
        ),
        "revision_replay_failed": (
            "Selected {plugin_id} revision failed exact replay.",
            "coding_capability_revision_replay_failed",
        ),
        "selected_revision_mismatch": (
            "Replayed {plugin_id} is not the selected revision.",
            "coding_capability_selected_revision_mismatch",
        ),
        "session_lease_mismatch": (
            "{plugin_id} lease escaped the management snapshot.",
            "coding_capability_session_lease_mismatch",
        ),
    },
    make_error=lambda message, code: CodingCapabilityPluginCompositionError(
        message, code=code
    ),
    cleanup_notes={},
)


def _resolve_managed_capability_plugins(
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    *,
    session_id: str,
    package_materializer: CodingPackageMaterializer,
    lifecycle: CodingPluginLifecycle | None,
    session_owner_id: str | None,
    legacy_disabled_plugin_ids: frozenset[str],
) -> tuple[
    PluginRuntimeResolution,
    Mapping[str, CodingCapabilityPluginConfig],
    Mapping[str, CodingPluginSessionLease],
]:
    """Resolve exact revisions and optionally pin the common lifecycle snapshot."""

    specs = ordered_coding_capability_plugin_specs(configurations)
    return _resolve_managed_plugin_runtimes(
        configurations,
        specs,
        session_id=session_id,
        package_materializer=package_materializer,
        lifecycle=lifecycle,
        session_owner_id=session_owner_id,
        legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
        owner_contributions=lambda spec: (
            (
                f"capability.{spec.capability.capability_id}",
                (spec.provider_contribution_id,),
            ),
            (f"tools.{spec.capability.capability_id}", (spec.tool_contribution_id,)),
        ),
        errors=_MANAGED_ASSEMBLY_ERRORS,
        attach_failure=lambda error, runtime, leases: (
            CodingCapabilityPluginCleanupCustodian(
                runtime=runtime, management_leases=leases
            ).retain_on(error)
        ),
    )


def prepare_coding_capability_plugin_composition(
    request: CodingCapabilityPluginCompositionRequest,
    *,
    session_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    package_materializer: CodingPackageMaterializer,
    lifecycle: CodingPluginLifecycle | None = None,
    session_owner_id: str | None = None,
    management_state_cleanup: Callable[[], None] | None = None,
    state_root: str | Path,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
    coding_product_plan_seed: ProductPluginPlanSeed | None = None,
    state_cleanup: Callable[[], None] | None = None,
    private_state_cleanup: Callable[[], None] | None = None,
    legacy_disabled_plugin_ids: frozenset[str] = frozenset(),
) -> CodingCapabilityPluginCompositionPreparation:
    """Resolve, approve and compile once without constructing host Providers."""


    _validate_preparation_inputs(
        request,
        session_id=session_id,
        configurations=configurations,
        package_materializer=package_materializer,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
    )
    _read_clock(clock)
    if state_cleanup is not None and not callable(state_cleanup):
        raise TypeError('Coding Capability Plugin state cleanup is invalid')
    if private_state_cleanup is not None and not callable(private_state_cleanup):
        raise TypeError('Coding Capability Plugin private-state cleanup is invalid')
    if management_state_cleanup is not None and not callable(management_state_cleanup):
        raise TypeError('Coding Capability Plugin management cleanup is invalid')
    if not isinstance(legacy_disabled_plugin_ids, frozenset) or any(
        not isinstance(item, str) or not item for item in legacy_disabled_plugin_ids
    ):
        raise TypeError('Coding Capability Plugin legacy selection is invalid')
    if lifecycle is not None and not isinstance(
        lifecycle, CodingPluginLifecycle
    ):
        raise TypeError('Coding Capability Plugins require a common lifecycle')
    resolved_state_root = Path(state_root).expanduser().resolve()
    scope_id = f"session:{session_id.strip()}"

    acquired_runtime: PluginRuntimeResolution | None = None
    try:
        resolved_state_root.mkdir(parents=True, exist_ok=True)
        runtime, selected_configurations, management_leases = (
            _resolve_managed_capability_plugins(
                configurations,
                session_id=session_id,
                package_materializer=package_materializer,
                lifecycle=lifecycle,
                session_owner_id=session_owner_id,
                legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
            )
        )
        if not selected_configurations:
            runtime.close()
            raise CodingCapabilityPluginCompositionError(
                'No requested Coding Capability Plugin is management-enabled.',
                code='coding_capability_plugins_management_disabled',
            )
        acquired_runtime = runtime
        resolved_product_seed = coding_product_plan_seed or (
            coding_base_plugin_assembly.plan_seed
            if coding_base_plugin_assembly is not None
            else None
        )
        tool_authority = _tool_owner_authority(
            frozenset(selected_configurations)
        )
        plan_seed = _prepare_selection_plan_seed(
            runtime,
            scope_id=scope_id,
            configurations=selected_configurations,
            management_leases=management_leases,
            coding_product_plan_seed=resolved_product_seed,
            tool_authority=tool_authority,
        )
        preparation = _prepare_capability_plugin_plan(
            request,
            plan_seed,
            runtime=runtime,
            plugin_ids=frozenset(selected_configurations),
            tool_authority=tool_authority,
            state_root=resolved_state_root,
            clock=clock,
        )
        preparation.management_leases = management_leases
        preparation.management_state_cleanup = management_state_cleanup
        preparation.state_cleanup = state_cleanup
        preparation.private_state_cleanup = private_state_cleanup
        return preparation
    except BaseException as error:
        custodian: CodingCapabilityPluginCleanupCustodian | None
        if acquired_runtime is not None:
            custodian = CodingCapabilityPluginCleanupCustodian(
                runtime=acquired_runtime,
                management_leases=dict(management_leases),
            )
        else:
            custodian = coding_capability_plugin_failure_custodian(error)
            if custodian is None:
                custodian = CodingCapabilityPluginCleanupCustodian(
                    runtime=PluginRuntimeResolution((), (), ()),
                    management_leases={},
                )
        custodian.finish_failed_preparation(
            error,
            cleanup_note_prefix="Coding Capability Plugin preparation cleanup also failed: ",
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
        raise


def _prepare_capability_plugin_plan(
    request: CodingCapabilityPluginCompositionRequest,
    seed: ProductPluginPlanSeed,
    *,
    runtime: PluginRuntimeResolution,
    plugin_ids: frozenset[str],
    tool_authority: OwnerContributionAuthority,
    state_root: Path,
    clock: Callable[[], int],
    resume_parents: CodingResumePluginParents | None = None,
    project_store_owners: Callable[
        [PluginSelection], tuple[OwnerContributionCandidateEnvelope, ...] | None
    ] | None = None,
) -> CodingCapabilityPluginCompositionPreparation:
    request = _bind_default_approval_request_to_plan(request, seed)
    scope_id = seed.plan.context.scope_id
    selection = _finalize_selection(
        seed,
        request=request,
        scope_id=scope_id,
        state_root=state_root,
        clock=clock,
        resume_parents=resume_parents,
    )
    # Fenced composition validates Provider policy before Catalog owners.
    provider_authorities = (
        _provider_owner_authorities(plugin_ids)
        if project_store_owners is not None
        else None
    )
    selected_seed = complete_coding_package_plugin_selection_seed(
        seed, selection=selection
    )
    if provider_authorities is None:
        provider_authorities = _provider_owner_authorities(plugin_ids)
    product = prepare_product_plugin_composition(
        _assembly_request(
            selected_seed,
            provider_authorities=provider_authorities,
            owner_candidates=(
                project_store_owners(selection) if project_store_owners is not None else None
            ),
        ),
        evaluated_at=_read_clock(clock),
    )
    return CodingCapabilityPluginCompositionPreparation(
        request=request,
        runtime=runtime,
        selection=selection,
        product=product,
        provider_owner_authorities=provider_authorities,
        tool_owner_authority=tool_authority,
        scope_id=scope_id,
        state_root=state_root,
        resume_parents=resume_parents,
    )


def _build_tool_owners(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    authority: OwnerContributionAuthority,
    scope_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    clock: Callable[[], int],
) -> Mapping[str, CodingCapabilityToolOwner]:
    gate = bind_selected_registration_authority(
        selection,
        plugin_assembly,
        authority=authority,
        product_id=CODING_PRODUCT_ID,
        scope_id=scope_id,
        clock=clock,
        label="Coding Tool owner",
    )
    admissions = plugin_assembly.product_composition.catalog_admissions

    def exact_admission(plugin_id: str, contribution_id: str):
        matches = tuple(
            item
            for item in admissions
            if item.plugin_id == plugin_id
            and item.contribution_id == contribution_id
            and item.owner_id == _TOOL_OWNER_ID
            and item.contribution_kind == "tool_pack"
        )
        if len(matches) != 1:
            raise ValueError(
                f"Coding Tool owner requires one exact admission for {plugin_id}"
            )
        return matches[0]

    return {
        spec.plugin_id: spec.tool_owner_factory(
            admission=exact_admission(
                spec.plugin_id,
                spec.tool_contribution_id,
            ),
            authority_gate=gate,
            mode=tool_modes[spec.capability.capability_id],
            scope_id=scope_id,
        )
        for spec in ordered_coding_capability_plugin_specs(
            set(selection.plan.selected_plugin_ids) & _PLUGIN_IDS
        )
    }


def _approve_activation_and_bind_inputs(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    request: CodingCapabilityPluginCompositionRequest,
    provider_authorities: Mapping[str, CapabilityProviderOwnerAuthority],
    scope_id: str,
    state_root: Path,
    host_boot_id: str,
    clock: Callable[[], int],
    resume_parents: CodingResumePluginParents | None = None,
) -> tuple[CapabilityComponentHost, SessionCapabilityCompositionInputs]:
    component_host = CapabilityComponentHost.from_product_selection(
        selection,
        provider_authorities=provider_authorities,
        journal_path=state_root / _ACTIVATION_DECISIONS_FILENAME,
        scope_id=scope_id,
        host_boot_id=host_boot_id,
        clock=clock,
        expected_product_id=CODING_PRODUCT_ID,
        product_label="Coding",
        required_writer_capabilities=frozenset(
            {"harness.plugin-activation.resume-context/v1"}
        )
        if resume_parents is not None
        else frozenset(),
        distribution_evidence_resolver=lambda: (
            coding_plugin_distribution_evidence_resolver()
        ),
        resume_parent_context=lambda: (
            resume_parents.activation if resume_parents is not None else None
        ),
    )
    return (
        component_host,
        plugin_assembly.approve_and_bind_session_inputs(
            component_host=component_host,
            approval_owner=lambda: request.approval_owner,
            product_label="Coding",
            error_code_prefix="coding_capability_plugin",
            error_factory=lambda message, code: CodingCapabilityPluginCompositionError(
                message, code=code
            ),
        ),
    )


def _finalize_selection(
    seed: ProductPluginPlanSeed,
    *,
    request: CodingCapabilityPluginCompositionRequest,
    scope_id: str,
    state_root: Path,
    clock: Callable[[], int],
    resume_parents: CodingResumePluginParents | None = None,
) -> PluginSelection:
    if resume_parents is not None:
        if type(resume_parents) is not CodingResumePluginParents:
            raise TypeError("Coding Resume requires original Plugin parent lookups")
        resume_parents.require_open(
            session_id=seed.plan.context.scope_id.removeprefix("session:"),
            state_root=state_root,
            clock=clock,
        )
    approval_owner = request.approval_owner
    windows_initial_approval_recovery = None
    if (
        resume_parents is None
        and isinstance(approval_owner, _CodingDefaultCapabilityPluginApprovalOwner)
        and approval_owner.approval_source == _DEFAULT_APPROVAL_SOURCE
    ):
        windows_initial_approval_recovery = (
            _default_approval_authorization(_DEFAULT_APPROVAL_SOURCE),
            approval_owner.plugin_ids,
        )
    return PluginDeclarationHost.resolve_for_product(
        seed.packages,
        bindings=seed.bindings,
        plan=seed.plan,
        journal_path=state_root / _DEFINITION_DECISIONS_FILENAME,
        scope_kind="workspace",
        scope_id=scope_id,
        clock=clock,
        required_writer_capabilities=frozenset(
            {"harness.plugin-execution.resume-context/v1"}
        )
        if resume_parents is not None
        else frozenset(),
        approval_owner=lambda: approval_owner,
        distribution_evidence_resolver=lambda: (
            coding_plugin_distribution_evidence_resolver()
        ),
        resume_parent_context=lambda: (
            resume_parents.definition if resume_parents is not None else None
        ),
        approval_label="Coding Capability",
        error_code_prefix="coding_capability_plugin",
        error_factory=lambda message, code: CodingCapabilityPluginCompositionError(
            message, code=code
        ),
        windows_initial_approval_recovery=windows_initial_approval_recovery,
    )


def _capability_configuration_entries(
    packages: Iterable[PublishedPluginPackage],
    configurations: Mapping[str, CodingCapabilityPluginConfig],
) -> Iterator[PluginEffectiveConfigurationEntry]:
    for package in packages:
        plugin_id = package.manifest.name
        for contribution in package.contribution_index.items:
            yield PluginEffectiveConfigurationEntry(
                plugin_id=plugin_id,
                contribution_id=contribution.contribution_id,
                configuration=(
                    configurations[plugin_id].to_dict()
                    if contribution.kind == "capability_provider"
                    else {}
                ),
            )


def _prepare_selection_plan_seed(
    runtime: PluginRuntimeResolution,
    *,
    scope_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    management_leases: Mapping[str, CodingPluginSessionLease],
    coding_product_plan_seed: ProductPluginPlanSeed | None,
    tool_authority: OwnerContributionAuthority,
) -> ProductPluginPlanSeed:
    package_bindings = tuple(zip(runtime.packages, runtime.bindings, strict=True))
    base_plan = coding_product_plan_seed.plan if coding_product_plan_seed else None
    plugin_ids = tuple(sorted(configurations))
    plan = build_product_plugin_selection_plan(
        product_id=CODING_PRODUCT_ID,
        scope_id=scope_id,
        policy_revision=(
            _PRODUCT_POLICY_REVISION
            if base_plan is None
            else base_plan.context.policy_revision
        ),
        plugin_ids=plugin_ids,
        instance_refs=tuple(
            management_leases[plugin_id].instance_revision_ref
            if plugin_id in management_leases
            else PluginInstanceRevisionRef(
                instance_id=f"{plugin_id}@{scope_id}", plugin_id=plugin_id, revision=1
            )
            for plugin_id in plugin_ids
        ),
        source_trust=(
            PluginSourceTrustSnapshotV1(
                plugin_id=package.manifest.name,
                package_source_identity=binding.source_identity,
                source_trust_class=_SOURCE_TRUST_CLASS,
                source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                trusted=True,
            )
            for package, binding in sorted(
                package_bindings, key=lambda pair: pair[0].manifest.name
            )
        ),
        additions=_capability_configuration_entries(
            (package for package, _ in package_bindings), configurations
        ),
        base=base_plan,
        extend_base_selection=True,
        allowed_authority_ceiling=("filesystem", "process"),
    )
    return ProductPluginPlanSeed.from_package_bindings(
        plan,
        package_bindings,
        owner_bindings=(ProductContributionOwnerBinding(authority=tool_authority),),
        extend_seed=coding_product_plan_seed,
    )


def _assembly_request(
    selection_seed: ProductPluginSelectionSeed,
    *,
    provider_authorities: Mapping[str, CapabilityProviderOwnerAuthority],
    owner_candidates: tuple[OwnerContributionCandidateEnvelope, ...] | None = None,
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
            if item.capability_id in provider_authorities
            and item.provider.provider_id
            == provider_authorities[item.capability_id].policy.allowed_provider_ids[0]
        )

    return ProductPluginCompositionAssemblyRequest.for_agent_session(
        selection_seed,
        provider_definitions=tuple(
            spec.capability
            for spec in ordered_coding_capability_plugin_specs(
                set(selection_seed.selection.plan.selected_plugin_ids) & _PLUGIN_IDS
            )
            if spec.capability.capability_id in provider_authorities
        ),
        provider_owner_bindings=tuple(
            ProductCapabilityProviderOwnerBinding(authority=authority)
            for _capability_id, authority in sorted(provider_authorities.items())
        ),
        select_capability_providers=select,
        owner_candidates=owner_candidates,
    )


def _provider_owner_authorities(
    plugin_ids: frozenset[str],
) -> dict[str, CapabilityProviderOwnerAuthority]:
    return {
        spec.capability.capability_id: CapabilityProviderOwnerAuthority(
            CapabilityProviderOwnerPolicy(
                capability_id=spec.capability.capability_id,
                owner_id=spec.capability.owner_id,
                policy_revision=spec.provider_owner_policy_revision,
                revocation_epoch=0,
                allowed_provider_ids=(spec.provider_id,),
                allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
                authority_ceiling=tuple(sorted(spec.capability.authority_ceiling)),
            )
        )
        for spec in ordered_coding_capability_plugin_specs(plugin_ids)
    }


def _tool_owner_authority(plugin_ids: frozenset[str]) -> OwnerContributionAuthority:
    return OwnerContributionAuthority.for_direct_session(
        owner_id=_TOOL_OWNER_ID,
        contribution_kind="tool_pack",
        product_id=CODING_PRODUCT_ID,
        policy_revision=_TOOL_OWNER_POLICY_REVISION,
        trust_classes=(_SOURCE_TRUST_CLASS,),
        collection_ids=tuple(
            sorted(
                spec.tool_catalog_id
                for spec in ordered_coding_capability_plugin_specs(plugin_ids)
            )
        ),
    )


def _matches_default_approval_context(
    subject: PluginExecutionApprovalSubject | ContributionActivationApprovalSubject,
    source_trust_policy_revision: str,
    instance_revision_refs: Mapping[str, PluginInstanceRevisionRef] | None,
) -> bool:
    revision = subject.instance_revision_ref
    return (
        subject.product_id == CODING_PRODUCT_ID
        and subject.scope_id.startswith("session:")
        and subject.scope_id != "session:"
        and subject.source_trust_class == _SOURCE_TRUST_CLASS
        and subject.source_trust_policy_revision == source_trust_policy_revision
        and revision.plugin_id == subject.plugin_id
        and revision.revision >= 1
        and (
            instance_revision_refs is None
            or revision == instance_revision_refs.get(subject.plugin_id)
        )
    )


def _validate_default_definition_subject(
    subject: PluginExecutionApprovalSubject,
    *,
    plugin_ids: frozenset[str],
    product_policy_revision: str,
    source_trust_policy_revision: str,
    instance_revision_refs: Mapping[str, PluginInstanceRevisionRef] | None,
) -> None:
    spec = CODING_CAPABILITY_PLUGIN_SPEC_BY_ID.get(subject.plugin_id)
    if (
        spec is None
        or subject.plugin_id not in plugin_ids
        or subject.policy_revision != product_policy_revision
        or subject.entrypoint != _DEFAULT_DEFINITION_ENTRYPOINT
        or subject.requested_authorities != spec.requested_authorities
        or subject.allowed_authority_ceiling != ("filesystem", "process")
        or not _matches_default_approval_context(
            subject, source_trust_policy_revision, instance_revision_refs
        )
    ):
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Definition Subject is outside Product policy.",
            code="coding_capability_definition_subject_rejected",
        )


def _validate_default_activation_subject(
    subject: ContributionActivationApprovalSubject,
    *,
    plugin_ids: frozenset[str],
    product_policy_revision: str,
    source_trust_policy_revision: str,
    instance_revision_refs: Mapping[str, PluginInstanceRevisionRef] | None,
) -> None:
    spec = CODING_CAPABILITY_PLUGIN_SPEC_BY_ID.get(subject.plugin_id)
    if (
        spec is None
        or subject.plugin_id not in plugin_ids
        or subject.capability_id != spec.capability.capability_id
        or subject.owner_id != spec.capability.owner_id
        or subject.provider_id != spec.provider_id
        or subject.contribution_id != spec.provider_contribution_id
        or subject.product_policy_revision != product_policy_revision
        or subject.owner_policy_revision != spec.provider_owner_policy_revision
        or subject.revocation_epoch != 0
        or subject.effective_facets != tuple(sorted(spec.capability.facets))
        or subject.effective_authorities
        != tuple(sorted(spec.capability.authority_ceiling))
        or subject.execution_model != "in_process"
        or not _matches_default_approval_context(
            subject, source_trust_policy_revision, instance_revision_refs
        )
    ):
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Activation Subject is outside Product policy.",
            code="coding_capability_activation_subject_rejected",
        )


def _default_approval_authorization(source: str) -> PluginApprovalAuthorizationV1:
    return PluginApprovalAuthorizationV1.direct(
        actor_id=_DEFAULT_APPROVAL_ACTOR_ID,
        source=source,
    )


def _validate_preparation_inputs(
    request: CodingCapabilityPluginCompositionRequest,
    *,
    session_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    package_materializer: CodingPackageMaterializer,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None,
    coding_product_plan_seed: ProductPluginPlanSeed | None,
) -> None:
    if not isinstance(request, CodingCapabilityPluginCompositionRequest):
        raise TypeError("Coding Capability Plugin composition request is invalid")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding Capability Plugin Session id must not be empty")
    if not isinstance(configurations, Mapping):
        raise TypeError("Coding Capability Plugin configurations are invalid")
    plugin_ids = frozenset(configurations)
    if not plugin_ids or not plugin_ids.issubset(_PLUGIN_IDS):
        raise ValueError("Coding Capability Plugin configurations are invalid")
    if any(
        not isinstance(configurations[spec.plugin_id], spec.configuration_type)
        for spec in ordered_coding_capability_plugin_specs(plugin_ids)
    ):
        raise TypeError("Coding Capability Plugin configuration type is invalid")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Coding Capability Plugins require Coding materialization")
    if coding_base_plugin_assembly is not None:
        if not isinstance(coding_base_plugin_assembly, CodingBasePluginAssembly):
            raise TypeError("Coding Capability Plugin base assembly is invalid")
        expected_scope = f"session:{session_id.strip()}"
        if coding_base_plugin_assembly.scope_id != expected_scope:
            raise ValueError("Coding base and Capability Plugin scopes do not match")
        if coding_base_plugin_assembly.package.revision_handle.closed:
            raise RuntimeError("Coding base Plugin revision is unavailable")
    if coding_product_plan_seed is not None:
        if not isinstance(coding_product_plan_seed, ProductPluginPlanSeed):
            raise TypeError("Coding Capability Product plan seed is invalid")
        if (
            coding_base_plugin_assembly is not None
            and _BASE_PLUGIN_ID not in coding_product_plan_seed.plan.selected_plugin_ids
        ):
            raise ValueError("Coding Capability Product seed omits coding.base")
    if not callable(clock):
        raise TypeError("Coding Capability Plugin clock is invalid")


def _validate_workspace_binding(
    workspace_binding: CapabilityBundleProviderBinding,
    *,
    host_boot_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    selected_capability_ids: frozenset[str],
    clock: Callable[[], int],
) -> None:
    if not isinstance(workspace_binding, CapabilityBundleProviderBinding):
        raise TypeError("Coding Capability Plugin workspace binding is invalid")
    if (
        workspace_binding.provider.capability_id
        != WORKSPACE_CAPABILITY_DEFINITION.capability_id
    ):
        raise ValueError("Coding Capability Plugins require harness.workspace")
    if not isinstance(host_boot_id, str):
        raise TypeError("Coding Capability Plugin Host boot id is invalid")
    if len(host_boot_id) != 32 or any(
        item not in "0123456789abcdefABCDEF" for item in host_boot_id
    ):
        raise ValueError("Coding Capability Plugin Host boot id must be 32 hex digits")
    if frozenset(tool_modes) != selected_capability_ids or any(
        mode not in {"on_demand", "always"} for mode in tool_modes.values()
    ):
        raise ValueError("Coding Capability Plugins require enabled Tool modes")
    if not callable(clock):
        raise TypeError("Coding Capability Plugin clock is invalid")


def _read_clock(clock: Callable[[], int]) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Coding Capability Plugin clock must return an integer")
    if value < 0:
        raise ValueError("Coding Capability Plugin time cannot be negative")
    return value


__all__ = [
    "CodingCapabilityPluginApprovalOwner",
    "CodingCapabilityPluginCompositionAssembly",
    "CodingCapabilityPluginCompositionError",
    "CodingCapabilityPluginCompositionPreparation",
    "CodingCapabilityPluginCompositionRequest",
    "create_coding_capability_plugin_composition_request",
    "prepare_coding_resume_plugin_effect_owners",
    "prepare_coding_capability_plugin_composition",
    "require_coding_resume_plugin_effect_settlement",
]
