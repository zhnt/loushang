"""Private Product composer for Coding's first-party Capability Plugins."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from loushang.coding._base_plugin import CodingBasePluginAssembly
from loushang.coding._capability_plugin_specs import (
    CODING_CAPABILITY_PLUGIN_IDS,
    CODING_CAPABILITY_PLUGIN_SPEC_BY_ID,
    CodingCapabilityPluginConfig,
    CodingCapabilityToolOwner,
    ordered_coding_capability_plugin_specs,
)
from loushang.coding._cleanup import run_cleanup_steps
from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycle,
    CodingPluginManagementChange,
    CodingPluginSessionLease,
    package_revision_ref,
)
from loushang.coding._resource_catalog_shadow import (
    complete_coding_package_plugin_selection_seed,
)
from loushang.coding.plugin_dependency_grants import (
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
from loushang.harness.resources.plugins.manifest import PluginManifestError
from loushang.harness.resources.plugins.revisions import PluginRevisionError
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
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt
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
_FAILURE_CUSTODIAN_ATTRIBUTE = "_coding_capability_plugin_cleanup_custodian"


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


@dataclass(slots=True)
class CodingCapabilityPluginCleanupCustodian:
    """Retryable owner for a preparation that failed after acquiring evidence."""

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

    def adopt_cleanup_callbacks(
        self,
        *,
        management_state_cleanup: Callable[[], None] | None,
        state_cleanup: Callable[[], None] | None,
        private_state_cleanup: Callable[[], None] | None,
    ) -> None:
        for name, callback in (
            ("management_state_cleanup", management_state_cleanup),
            ("state_cleanup", state_cleanup),
            ("private_state_cleanup", private_state_cleanup),
        ):
            current = getattr(self, name)
            if current is not None and callback is not None and current is not callback:
                raise RuntimeError(
                    "Coding Capability cleanup callback ownership changed"
                )
            if current is None:
                setattr(self, name, callback)

    def close(self) -> None:
        """Retry cleanup without deleting management/private roots too early."""

        primary_error: BaseException | None = None
        if not self._runtime_closed:
            try:
                self.runtime.close()
            except BaseException as error:
                primary_error = error
            else:
                self._runtime_closed = True
        if self._runtime_closed:
            for plugin_id, lease in reversed(tuple(self.management_leases.items())):
                if plugin_id in self._released_plugin_ids:
                    continue
                try:
                    lease.close()
                except BaseException as cleanup_error:
                    if primary_error is None:
                        primary_error = cleanup_error
                    else:
                        primary_error.add_note(
                            f"{plugin_id} Session lifecycle release also failed: "
                            f"{cleanup_error}"
                        )
                else:
                    self._released_plugin_ids.add(plugin_id)
        all_leases_released = len(self._released_plugin_ids) == len(
            self.management_leases
        )
        if (
            self._runtime_closed
            and all_leases_released
            and not self._management_released
        ):
            try:
                if self.management_state_cleanup is not None:
                    self.management_state_cleanup()
            except BaseException as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error.add_note(
                        "Coding Capability management-state cleanup also failed: "
                        f"{cleanup_error}"
                    )
            else:
                self._management_released = True
        if self._management_released and not self._state_cleaned:
            try:
                if self.state_cleanup is not None:
                    self.state_cleanup()
            except BaseException as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error.add_note(
                        "Coding Capability composition-state cleanup also failed: "
                        f"{cleanup_error}"
                    )
            else:
                self._state_cleaned = True
        if self._state_cleaned and not self._private_state_cleaned:
            try:
                if self.private_state_cleanup is not None:
                    self.private_state_cleanup()
            except BaseException as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error.add_note(
                        "Coding Capability private-state cleanup also failed: "
                        f"{cleanup_error}"
                    )
            else:
                self._private_state_cleaned = True
        if primary_error is not None:
            raise primary_error


def coding_capability_plugin_failure_custodian(
    error: BaseException,
) -> CodingCapabilityPluginCleanupCustodian | None:
    """Recover a retryable preparation cleanup owner from an exception chain."""

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        custodian = getattr(current, _FAILURE_CUSTODIAN_ATTRIBUTE, None)
        if isinstance(custodian, CodingCapabilityPluginCleanupCustodian):
            return custodian
        current = current.__cause__ or current.__context__
    return None


def _attach_failure_custodian(
    error: BaseException,
    custodian: CodingCapabilityPluginCleanupCustodian,
) -> None:
    setattr(error, _FAILURE_CUSTODIAN_ATTRIBUTE, custodian)


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
    return CodingCapabilityPluginCompositionRequest(
        approval_owner=_CodingDefaultCapabilityPluginApprovalOwner(
            clock=clock,
            plugin_ids=plugin_ids,
            approval_source=approval_source,
            product_policy_revision=product_policy_revision,
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
        item.plugin_id: item
        for item in seed.plan.context.instance_revision_refs
    }
    instance_binder = cast(_CodingCapabilityApprovalInstanceBinder, request.approval_owner)
    return CodingCapabilityPluginCompositionRequest(
        approval_owner=instance_binder.bind_selected_instances(
            selected_plugin_ids=frozenset(seed.plan.selected_plugin_ids),
            instance_revision_refs=instance_revision_refs,
        )
    )


@dataclass(slots=True)
class CodingCapabilityPluginCompositionAssembly:
    """Approved Product closure awaiting bootstrap and Graph ownership transfer."""

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

    def close(self) -> None:
        """Release verified revision handles before ownership transfers to Session."""

        if self._closed:
            return
        if not self._runtime_closed:
            self.runtime.close()
            self._runtime_closed = True
        # Composition state is evidence for graph publication, not lifecycle
        # management state.  Once runtime evidence closes after publication it
        # can retire independently; management/private roots remain gated on
        # graph and owner retirement.
        if not self._state_cleaned:
            if self.state_cleanup is not None:
                self.state_cleanup()
            self._state_cleaned = True
        self._closed = self._runtime_closed and self._state_cleaned

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
        for plugin_id, lease in self.management_leases.items():
            lease.prepare_owner_generations(receipts.get(plugin_id, ()))

    def publish_owner_generations(
        self,
        receipts: Mapping[str, tuple[OwnerGenerationRetirementReceipt, ...]],
    ) -> None:
        for plugin_id, lease in self.management_leases.items():
            lease.publish_owner_generations(receipts.get(plugin_id, ()))

    def retire_owner_generations(
        self,
        receipts: Mapping[str, tuple[OwnerGenerationRetirementReceipt, ...]],
    ) -> None:
        for plugin_id, lease in self.management_leases.items():
            lease.retire_owner_generations(receipts.get(plugin_id, ()))

    def confirm_runtime_retirement(
        self,
        *,
        graph_closed: bool,
        runtime_was_published: bool,
        graph_has_pending_retirements: bool,
        owner_generations_remaining: bool,
        component_generations_remaining: bool,
    ) -> None:
        """Accept cleanup eligibility only from a completely retired Session."""

        if (
            (runtime_was_published and not graph_closed)
            or graph_has_pending_retirements
            or owner_generations_remaining
            or component_generations_remaining
        ):
            raise RuntimeError(
                "Coding Capability Plugin runtime retirement remains incomplete"
            )
        self._runtime_retired = True

    def release_management(self) -> None:
        if self._management_released:
            return
        if not self._runtime_retired:
            raise RuntimeError(
                "Coding Capability Plugin management cannot release before retirement"
            )
        if not self._runtime_closed:
            raise RuntimeError(
                "Coding Capability Plugin management cannot release before "
                "runtime evidence closes"
            )
        primary_error = run_cleanup_steps(
            None,
            tuple(
                (
                    f"{plugin_id} Session lifecycle release",
                    lease.close,
                )
                for plugin_id, lease in reversed(tuple(self.management_leases.items()))
            ),
        )
        if primary_error is not None:
            raise primary_error
        if self.management_state_cleanup is not None:
            self.management_state_cleanup()
        self._management_released = True

    def abort_unpublished(self) -> None:
        """Release an assembly that never published a Session graph."""

        self._runtime_retired = True
        if not self._runtime_closed:
            self.runtime.close()
            self._runtime_closed = True
        self.release_management()
        if not self._state_cleaned:
            if self.state_cleanup is not None:
                self.state_cleanup()
            self._state_cleaned = True
        self.cleanup_private_state()
        self._closed = True

    def cleanup_private_state(self) -> None:
        """Delete disposable private data only after Provider retirement."""

        if self._private_state_cleaned:
            return
        if (
            not self._runtime_retired
            or not self._management_released
            or not self._state_cleaned
        ):
            raise RuntimeError(
                "Coding Capability Plugin private state requires retirement evidence"
            )
        if self.private_state_cleanup is not None:
            self.private_state_cleanup()
        self._private_state_cleaned = True


@dataclass(slots=True)
class CodingCapabilityPluginCompositionPreparation:
    """Definition-approved closure compiled before host Provider construction."""

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
            selected_capability_ids=frozenset(
                self.provider_owner_authorities.keys()
            ),
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
                provider_authorities=self.provider_owner_authorities,
                scope_id=self.scope_id,
                state_root=self.state_root,
                host_boot_id=host_boot_id,
                clock=clock,
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

    def close(self) -> None:
        if self._closed or self._transferred:
            return
        if not self._runtime_closed:
            self.runtime.close()
            self._runtime_closed = True
        if not self._management_released:
            primary_error = run_cleanup_steps(
                None,
                tuple(
                    (
                        f"{plugin_id} Session lifecycle release",
                        lease.close,
                    )
                    for plugin_id, lease in reversed(
                        tuple(self.management_leases.items())
                    )
                ),
            )
            if primary_error is not None:
                raise primary_error
            if self.management_state_cleanup is not None:
                self.management_state_cleanup()
            self._management_released = True
        if not self._state_cleaned:
            if self.state_cleanup is not None:
                self.state_cleanup()
            self._state_cleaned = True
        if not self._private_state_cleaned:
            if self.private_state_cleanup is not None:
                self.private_state_cleanup()
            self._private_state_cleaned = True
        self._closed = (
            self._runtime_closed
            and self._management_released
            and self._state_cleaned
            and self._private_state_cleaned
        )


def _resolve_managed_capability_plugins(
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    *,
    session_id: str,
    package_materializer: CodingPackageMaterializer,
    lifecycle: CodingPluginLifecycle | None,
    session_owner_id: str | None,
) -> tuple[
    PluginRuntimeResolution,
    Mapping[str, CodingCapabilityPluginConfig],
    Mapping[str, CodingPluginSessionLease],
]:
    """Resolve exact revisions and optionally pin the common lifecycle snapshot."""

    specs = ordered_coding_capability_plugin_specs(configurations)
    authority = PluginResolutionAuthority()
    if lifecycle is None:
        inspections = tuple(
            authority.inspect(PluginSource(path=spec.source_root())) for spec in specs
        )
        return (
            authority.publish_runtime(
                inspections,
                binding_store=package_materializer,
            ),
            dict(configurations),
            {},
        )

    packages = []
    plugins = []
    bindings = []
    selected_configurations: dict[str, CodingCapabilityPluginConfig] = {}
    leases: dict[str, CodingPluginSessionLease] = {}
    current_package = None
    try:
        for spec in specs:
            current_package = None
            key = lifecycle.installation_key(spec.plugin_id)
            snapshot = lifecycle.desired.snapshot()
            state = snapshot.installation(key)
            seen = any(
                item.installation_key == key for item in snapshot.installations
            )
            package = None
            binding = None
            if not seen:
                published = authority.publish_runtime(
                    (authority.inspect(PluginSource(path=spec.source_root())),),
                    binding_store=package_materializer,
                )
                [package] = published.packages
                [binding] = published.bindings
                current_package = package
                revision = package_revision_ref(
                    plugin_id=package.manifest.name,
                    plugin_version=package.manifest.version,
                    package_content_digest=package.content_digest,
                    dependency_lock_digest=package.dependency_lock.digest,
                    package_source_identity=binding.source_identity,
                )
                lifecycle.bootstrap_first_party_default(key, revision)
                state = lifecycle.desired.snapshot().installation(key)
            else:
                retained_package = state.selection.package_revision
                if (
                    state.selection.desired_state == "installed_disabled"
                    and retained_package is not None
                ):
                    lifecycle.bootstrap_first_party_default(key, retained_package)
                    state = lifecycle.desired.snapshot().installation(key)
                lifecycle.reconcile_retirements()
            if state.selection.desired_state != "installed_enabled":
                if package is not None:
                    package.revision_handle.close()
                    current_package = None
                continue
            selected_revision = state.selection.package_revision
            selected_instance = state.selection.instance_revision_ref
            if selected_revision is None or selected_instance is None:
                raise CodingCapabilityPluginCompositionError(
                    f"Enabled {spec.plugin_id} lacks exact lifecycle evidence.",
                    code="coding_capability_management_selection_incomplete",
                )
            if package is None or binding is None:
                try:
                    binding = package_materializer.get_plugin_binding_by_revision(
                        selected_revision.package_source_identity,
                        content_digest=selected_revision.package_content_digest,
                        dependency_lock_digest=(
                            selected_revision.dependency_lock_digest
                        ),
                    )
                except PluginManifestError as exc:
                    raise CodingCapabilityPluginCompositionError(
                        f"Selected {spec.plugin_id} binding lock is invalid.",
                        code="coding_capability_binding_replay_invalid",
                    ) from exc
                if binding is None:
                    raise CodingCapabilityPluginCompositionError(
                        f"Selected {spec.plugin_id} binding is unavailable.",
                        code="coding_capability_binding_replay_unavailable",
                    )
                try:
                    package = package_materializer.reopen_plugin_package(binding)
                    current_package = package
                except PluginRevisionError as exc:
                    raise CodingCapabilityPluginCompositionError(
                        f"Selected {spec.plugin_id} revision failed exact replay.",
                        code="coding_capability_revision_replay_failed",
                    ) from exc
            actual_revision = package_revision_ref(
                plugin_id=package.manifest.name,
                plugin_version=package.manifest.version,
                package_content_digest=package.content_digest,
                dependency_lock_digest=package.dependency_lock.digest,
                package_source_identity=binding.source_identity,
            )
            if actual_revision != selected_revision:
                raise CodingCapabilityPluginCompositionError(
                    f"Replayed {spec.plugin_id} is not the selected revision.",
                    code="coding_capability_selected_revision_mismatch",
                )
            lease = lifecycle.acquire_session(
                key,
                session_id=session_id.strip(),
                lease_attempt_id=secrets.token_hex(16),
                owner_contributions=(
                    (
                        f"capability.{spec.capability.capability_id}",
                        (spec.provider_contribution_id,),
                    ),
                    (
                        f"tools.{spec.capability.capability_id}",
                        (spec.tool_contribution_id,),
                    ),
                ),
                session_owner_id=session_owner_id,
            )
            leases[spec.plugin_id] = lease
            if (
                lease.package_revision != selected_revision
                or lease.instance_revision_ref != selected_instance
            ):
                raise CodingCapabilityPluginCompositionError(
                    f"{spec.plugin_id} lease escaped the management snapshot.",
                    code="coding_capability_session_lease_mismatch",
                )
            packages.append(package)
            current_package = None
            plugins.append(authority.project_package(package))
            bindings.append(binding)
            selected_configurations[spec.plugin_id] = configurations[spec.plugin_id]
        return (
            PluginRuntimeResolution(
                packages=tuple(packages),
                plugins=tuple(plugins),
                bindings=tuple(bindings),
            ),
            selected_configurations,
            leases,
        )
    except BaseException as error:
        failure_packages = list(packages)
        if current_package is not None and current_package not in failure_packages:
            failure_packages.append(current_package)
        _attach_failure_custodian(
            error,
            CodingCapabilityPluginCleanupCustodian(
                runtime=PluginRuntimeResolution(
                    packages=tuple(failure_packages),
                    plugins=tuple(plugins),
                    bindings=tuple(bindings),
                ),
                management_leases=dict(leases),
            ),
        )
        raise


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
        raise TypeError("Coding Capability Plugin state cleanup is invalid")
    if private_state_cleanup is not None and not callable(private_state_cleanup):
        raise TypeError("Coding Capability Plugin private-state cleanup is invalid")
    if management_state_cleanup is not None and not callable(
        management_state_cleanup
    ):
        raise TypeError("Coding Capability Plugin management cleanup is invalid")
    if lifecycle is not None and not isinstance(lifecycle, CodingPluginLifecycle):
        raise TypeError("Coding Capability Plugins require a common lifecycle")
    resolved_state_root = Path(state_root).expanduser().resolve()
    scope_id = f"session:{session_id.strip()}"

    try:
        resolved_state_root.mkdir(parents=True, exist_ok=True)
        runtime, selected_configurations, management_leases = (
            _resolve_managed_capability_plugins(
                configurations,
                session_id=session_id,
                package_materializer=package_materializer,
                lifecycle=lifecycle,
                session_owner_id=session_owner_id,
            )
        )
        if not selected_configurations:
            runtime.close()
            raise CodingCapabilityPluginCompositionError(
                "No requested Coding Capability Plugin is management-enabled.",
                code="coding_capability_plugins_management_disabled",
            )
    except BaseException as error:
        custodian = coding_capability_plugin_failure_custodian(error)
        if custodian is None:
            custodian = CodingCapabilityPluginCleanupCustodian(
                runtime=PluginRuntimeResolution((), (), ()),
                management_leases={},
            )
        custodian.adopt_cleanup_callbacks(
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
        try:
            custodian.close()
        except BaseException as cleanup_error:
            error.add_note(
                "Coding Capability Plugin preparation cleanup also failed: "
                f"{cleanup_error}"
            )
            _attach_failure_custodian(error, custodian)
        raise
    try:
        resolved_product_seed = coding_product_plan_seed or (
            coding_base_plugin_assembly.plan_seed
            if coding_base_plugin_assembly is not None
            else None
        )
        tool_authority = _tool_owner_authority(frozenset(selected_configurations))
        plan_seed = _prepare_selection_plan_seed(
            runtime,
            scope_id=scope_id,
            configurations=selected_configurations,
            management_leases=management_leases,
            coding_product_plan_seed=resolved_product_seed,
            tool_authority=tool_authority,
        )
        request = _bind_default_approval_request_to_plan(request, plan_seed)
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
        provider_authorities = _provider_owner_authorities(
            frozenset(selected_configurations)
        )
        product = prepare_product_plugin_composition(
            _assembly_request(
                selection_seed,
                provider_authorities=provider_authorities,
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
            state_root=resolved_state_root,
            management_leases=management_leases,
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
    except BaseException as error:
        custodian = CodingCapabilityPluginCleanupCustodian(
            runtime=runtime,
            management_leases=dict(management_leases),
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
        try:
            custodian.close()
        except BaseException as cleanup_error:
            error.add_note(
                "Coding Capability Plugin preparation cleanup also failed: "
                f"{cleanup_error}"
            )
            _attach_failure_custodian(error, custodian)
        raise


def _build_tool_owners(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    authority: OwnerContributionAuthority,
    scope_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    clock: Callable[[], int],
) -> Mapping[str, CodingCapabilityToolOwner]:
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
            raise ValueError("Coding Tool owner reader received another owner")
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
            raise ValueError("Coding Tool owner requires one trust snapshot")
        return matches[0]

    def read_product_policy(product_id: str, requested_scope_id: str) -> str:
        if product_id != CODING_PRODUCT_ID or requested_scope_id != scope_id:
            raise ValueError("Coding Tool owner received another Product scope")
        return selection.plan.context.policy_revision

    gate = SessionCapabilityOwnerAuthorityGate(
        authority_context=(plugin_assembly.product_composition.authority_context),
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_product_policy,
        clock=clock,
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
) -> tuple[CapabilityComponentHost, SessionCapabilityCompositionInputs]:
    journal = PluginActivationDecisionJournal(
        state_root / "activation-decisions.jsonl",
        scope_id=scope_id,
        clock=clock,
    )
    trust_snapshots = selection.plan.source_trust_snapshots

    def read_owner(capability_id: str) -> CapabilityProviderOwnerSnapshot:
        try:
            return provider_authorities[capability_id].snapshot()
        except KeyError as exc:
            raise ValueError(
                "Coding owner reader received another Capability"
            ) from exc

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
            raise ValueError("Coding trust reader requires one exact snapshot")
        return matches[0]

    def read_product_policy(product_id: str, requested_scope_id: str) -> str:
        if product_id != CODING_PRODUCT_ID or requested_scope_id != scope_id:
            raise ValueError("Coding policy reader received another Product scope")
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
                "Coding Capability Activation Approval owner returned invalid evidence"
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
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability activation approval does not match its Subject.",
                code="coding_capability_plugin_activation_approval_mismatch",
            )
        if decision.disposition != "approved":
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability Plugin activation was not approved.",
                code="coding_capability_plugin_activation_denied",
            )
        if decision.consumption_state != "AVAILABLE":
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability Plugin activation decision is not available.",
                code="coding_capability_plugin_activation_not_available",
            )
        decision_ids[candidate.capability_id] = decision.decision_id
    return (
        component_host,
        plugin_assembly.bind_session_inputs(decision_ids),
    )


def _finalize_selection(
    seed: ProductPluginPlanSeed,
    *,
    request: CodingCapabilityPluginCompositionRequest,
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
                    "Coding Capability Definition Approval owner returned invalid evidence"
                )
            if decision.subject_digest != subject.digest:
                raise CodingCapabilityPluginCompositionError(
                    "Coding Capability Definition approval does not match its Subject.",
                    code="coding_capability_plugin_definition_approval_mismatch",
                )
        outcome = host.resolve(
            seed.packages,
            bindings=seed.bindings,
            plan=seed.plan,
            decision_lookup=journal,
        )
    if not isinstance(outcome, PluginSelection):
        disposition = outcome.disposition
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Plugin Definition was not approved.",
            code=(
                "coding_capability_plugin_definition_denied"
                if isinstance(outcome, PluginPreflightDeniedOutcome)
                else f"coding_capability_plugin_definition_{disposition}"
            ),
        )
    return outcome


def _prepare_selection_plan_seed(
    runtime: PluginRuntimeResolution,
    *,
    scope_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    management_leases: Mapping[str, CodingPluginSessionLease],
    coding_product_plan_seed: ProductPluginPlanSeed | None,
    tool_authority: OwnerContributionAuthority,
) -> ProductPluginPlanSeed:
    package_bindings = tuple(
        zip(runtime.packages, runtime.bindings, strict=True)
    )
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
                        *tuple(
                            (
                                management_leases[plugin_id].instance_revision_ref
                                if plugin_id in management_leases
                                else PluginInstanceRevisionRef(
                                    instance_id=f"{plugin_id}@{scope_id}",
                                    plugin_id=plugin_id,
                                    revision=1,
                                )
                            )
                            for plugin_id in sorted(configurations)
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
        selected_plugin_ids=tuple(
            sorted((*base_plugin_ids, *configurations.keys()))
        ),
        selected_contributions=tuple(
            sorted(
                (
                    *base_contributions,
                    *tuple(
                        PluginContributionRef(
                            package.manifest.name,
                            item.contribution_id,
                        )
                        for package, _binding in package_bindings
                        for item in package.contribution_index.items
                    )
                )
            )
        ),
        source_trust_snapshots=tuple(
            sorted(
                (
                    *base_trust,
                    *tuple(
                        PluginSourceTrustSnapshotV1(
                            plugin_id=package.manifest.name,
                            package_source_identity=binding.source_identity,
                            source_trust_class=_SOURCE_TRUST_CLASS,
                            source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                            trusted=True,
                        )
                        for package, binding in package_bindings
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
                                plugin_id=package.manifest.name,
                                contribution_id=item.contribution_id,
                                configuration=(
                                    configurations[package.manifest.name].to_dict()
                                    if item.kind == "capability_provider"
                                    else {}
                                ),
                            )
                            for package, _binding in package_bindings
                            for item in package.contribution_index.items
                        ),
                    ),
                    key=lambda item: (item.plugin_id, item.contribution_id),
                )
            )
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
    all_package_bindings = tuple(
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
                *package_bindings,
            ),
            key=lambda item: item[0].manifest.name,
        )
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple(item[0] for item in all_package_bindings),
        bindings=tuple(item[1] for item in all_package_bindings),
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
    provider_authorities: Mapping[str, CapabilityProviderOwnerAuthority],
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

    return ProductPluginCompositionAssemblyRequest(
        contribution_request=ProductCompositionAssemblyRequest(
            selection=selection_seed.selection,
            owner_bindings=selection_seed.owner_bindings,
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
                *tuple(
                    spec.capability
                    for spec in ordered_coding_capability_plugin_specs(
                        set(selection_seed.selection.plan.selected_plugin_ids)
                        & _PLUGIN_IDS
                    )
                    if spec.capability.capability_id in provider_authorities
                ),
            ),
        ),
        provider_owner_bindings=tuple(
            ProductCapabilityProviderOwnerBinding(
                authority=authority,
            )
            for _capability_id, authority in sorted(provider_authorities.items())
        ),
        provider_roots=tuple(sorted(provider_authorities)),
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        select_capability_providers=select,
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
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=_TOOL_OWNER_ID,
            contribution_kind="tool_pack",
            product_id=CODING_PRODUCT_ID,
            policy_revision=_TOOL_OWNER_POLICY_REVISION,
            revocation_epoch=0,
            allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
            allowed_collection_ids=tuple(
                sorted(
                    spec.tool_catalog_id
                    for spec in ordered_coding_capability_plugin_specs(plugin_ids)
                )
            ),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    )


def _validate_default_definition_subject(
    subject: PluginExecutionApprovalSubject,
    *,
    plugin_ids: frozenset[str],
    product_policy_revision: str,
    instance_revision_refs: Mapping[str, PluginInstanceRevisionRef] | None,
) -> None:
    spec = CODING_CAPABILITY_PLUGIN_SPEC_BY_ID.get(subject.plugin_id)
    if (
        spec is None
        or subject.plugin_id not in plugin_ids
        or subject.product_id != CODING_PRODUCT_ID
        or not subject.scope_id.startswith("session:")
        or subject.scope_id == "session:"
        or subject.policy_revision != product_policy_revision
        or subject.entrypoint != _DEFAULT_DEFINITION_ENTRYPOINT
        or subject.source_trust_class != _SOURCE_TRUST_CLASS
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or subject.requested_authorities
        != spec.requested_authorities
        or subject.allowed_authority_ceiling != ("filesystem", "process")
        or subject.instance_revision_ref.plugin_id != subject.plugin_id
        or subject.instance_revision_ref.revision < 1
        or (
            instance_revision_refs is not None
            and subject.instance_revision_ref
            != instance_revision_refs.get(subject.plugin_id)
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
    instance_revision_refs: Mapping[str, PluginInstanceRevisionRef] | None,
) -> None:
    spec = CODING_CAPABILITY_PLUGIN_SPEC_BY_ID.get(subject.plugin_id)
    if subject.plugin_id not in plugin_ids or spec is None:
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Activation Subject is outside Product policy.",
            code="coding_capability_activation_subject_rejected",
        )
    if (
        subject.capability_id != spec.capability.capability_id
        or subject.owner_id != spec.capability.owner_id
        or subject.provider_id != spec.provider_id
        or subject.contribution_id != spec.provider_contribution_id
        or subject.product_id != CODING_PRODUCT_ID
        or not subject.scope_id.startswith("session:")
        or subject.scope_id == "session:"
        or subject.source_trust_class != _SOURCE_TRUST_CLASS
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or subject.product_policy_revision != product_policy_revision
        or subject.owner_policy_revision != spec.provider_owner_policy_revision
        or subject.revocation_epoch != 0
        or subject.effective_facets
        != tuple(sorted(spec.capability.facets))
        or subject.effective_authorities
        != tuple(sorted(spec.capability.authority_ceiling))
        or subject.execution_model != "in_process"
        or subject.instance_revision_ref.plugin_id != subject.plugin_id
        or subject.instance_revision_ref.revision < 1
        or (
            instance_revision_refs is not None
            and subject.instance_revision_ref
            != instance_revision_refs.get(subject.plugin_id)
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
            and _BASE_PLUGIN_ID
            not in coding_product_plan_seed.plan.selected_plugin_ids
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
    "prepare_coding_capability_plugin_composition",
]
