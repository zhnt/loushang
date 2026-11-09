"""Session family membership and exact-owner retirement over existing authorities."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from loushang.harness.journal import journal_file_lock
from loushang.harness.package_product import _legacy_runtime
from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginInstallationKeyV1,
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRuntimeLedger,
    PluginPackageLifecycleLedger,
    PluginRetirementIntentLedger,
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.assembly import (
    _complete_settled_host_retirement,
    _SettledHostRetirementPolicy,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeInventorySnapshotV1,
)
from loushang.harness.plugin_management.retirement import PluginRetirementIntentV1
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.resources.plugins import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt
from loushang.harness.session._plugin_retirement import (
    OwnerRetirementReportPolicy,
    report_exact_owner_retirement,
)

from ._owner_evidence import EventT, FamilyT, _OwnerGenerationEvidenceLedger
from ._owner_lease import _acquire_session_owner_lease, _SessionOwnerLease

Owners = tuple[tuple[str, tuple[str, ...]], ...]


class _LifecycleRoots(Protocol):
    @property
    def scope_id(self) -> str: ...
    @property
    def coordination_lock(self) -> Path: ...
    @property
    def retirement_intents(self) -> Path: ...


class _HolderEvidence(Protocol):
    @property
    def startup_id(self) -> str: ...


RootsT = TypeVar("RootsT", bound=_LifecycleRoots)
LeaseT = TypeVar("LeaseT", bound=_SessionOwnerLease)


@dataclass(frozen=True, slots=True)
class _MembershipPolicy(Generic[RootsT]):
    product_label: str
    identity_prefix: str
    error_code_prefix: str
    make_error: Callable[[str, str], RuntimeError]
    family_release: Callable[
        [PluginInstanceLeaseFamilyV1], PluginInstanceLeaseFamilyReleaseV1
    ]
    orphan_release: Callable[
        [PluginInstanceLeaseFamilyV1, str], PluginInstanceLeaseFamilyReleaseV1
    ]
    activation_identity: Callable[
        [PluginInstallationKeyV1, PluginInstanceRevisionRef], str
    ]
    lease_identity: Callable[
        [PluginInstallationKeyV1, PluginInstanceRevisionRef, str, str, Owners], str
    ]
    normalize_owners: Callable[[Owners], Owners]
    holder_reference: Callable[[str, str, Owners, str], str]
    holder_evidence: Callable[[str], _HolderEvidence | None]
    startup_path: Callable[[RootsT, str], Path]
    owner_path: Callable[[RootsT, str], Path]
    startup_policy: _legacy_runtime._LegacyStartupPolicy
    retirement_policy: OwnerRetirementReportPolicy


class _StartupLeaseState(Protocol):
    _owns_process_startup_lease: bool


class _PluginSessionLifecycle(Generic[RootsT, EventT, FamilyT, LeaseT]):
    # All fields remain on the real Product facade; no second lifecycle state.
    __slots__ = ()
    layout: RootsT
    startup_id: str
    desired: PluginDesiredStateLedger
    instances: PluginInstanceRuntimeLedger
    retirement_sets: PluginRetirementSetLedger
    packages: PluginPackageLifecycleLedger
    security: PluginInstanceSecurityRetirementJournal
    owner_evidence: _OwnerGenerationEvidenceLedger[EventT, FamilyT]
    _owns_process_startup_lease: bool
    _membership_policy: _MembershipPolicy[RootsT]
    _owner_lease_type: type[LeaseT]
    _settled_host_policy: _SettledHostRetirementPolicy

    def _complete_ready_retirement(self, intent: PluginRetirementIntentV1) -> None:
        _complete_settled_host_retirement(
            intent,
            instances=self.instances,
            packages=self.packages,
            retirement_sets=self.retirement_sets,
            scope_id=self.layout.scope_id,
            policy=self._settled_host_policy,
        )

    def release_owned_process_startup_lease(self) -> None:
        """Release a startup lease acquired specifically by this lifecycle.

        Durable Product state deliberately keeps its startup lease for the
        process lifetime. Disposable composition roots instead call this
        before removing their private state directory.
        """
        policy = self._membership_policy

        if not self._owns_process_startup_lease:
            return
        _legacy_runtime._release_process_startup_lease(
            policy.startup_path(self.layout, self.startup_id),
        )
        # The concrete facade declares the slot; this is a typed view of the
        # same object, keeping the mixin free of slots or duplicated state.
        state: _StartupLeaseState = self
        state._owns_process_startup_lease = False

    def complete_startup_recovery(self) -> None:
        """Seal Package recovery after the composition root reconciles Instances."""
        policy = self._membership_policy

        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            self._reconcile_retirements_unlocked()
            self.packages.complete_startup_recovery(
                operation_id=f"{policy.identity_prefix}-package-recovery:{self.startup_id}",
                idempotency_key=f"{policy.identity_prefix}-package-recovery:{self.startup_id}",
                recovery_reference=f"{policy.identity_prefix}-runtime:{self.startup_id}",
            )

    def reconcile_retirements(self) -> None:
        """Project committed management cutovers into the Instance runtime."""

        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            self._reconcile_retirements_unlocked()

    def _reconcile_retirements_unlocked(self) -> None:
        """Reconcile while the Product-wide cross-journal lock is held."""

        self._recover_inactive_session_families()
        self.security.reconcile(self.instances)
        runtime = self.instances.snapshot()
        for intent in self.management_retirement_intents():
            instance = runtime.instance(intent.instance_revision_ref)
            if instance is None or instance.state in {"REVOKING", "RETIRED"}:
                continue
            if instance.state == "ACTIVE":
                self.instances.begin_drain(intent)
            runtime = self.instances.snapshot()
            self._ensure_owner_retirement_plan(intent, runtime)
            self._complete_ready_retirement(intent)
            runtime = self.instances.snapshot()

    def _recover_inactive_session_families(self) -> None:
        """Release only Session families whose process death is lock-proven."""
        policy = self._membership_policy

        runtime = self.instances.snapshot()
        for family in runtime.open_families:
            if family.lease_kind != "session_membership":
                continue
            evidence = policy.holder_evidence(family.holder_reference)
            if (
                evidence is None
                or evidence.startup_id == self.startup_id
                or not _legacy_runtime._startup_lease_is_inactive(
                    policy.startup_path(self.layout, evidence.startup_id),
                    policy=policy.startup_policy,
                )
            ):
                continue
            [member] = family.members
            owner_evidence = self.owner_evidence.family(family.family_id)
            if owner_evidence is not None and not owner_evidence.retired:
                self.owner_evidence.retire(
                    family_id=family.family_id,
                    instance_revision_ref=member.instance_revision_ref,
                    receipts=owner_evidence.receipts,
                    outcome_reference=(
                        f"{policy.identity_prefix}-session-process-exit-confirmed:"
                        f"{evidence.startup_id}:{family.family_id}"
                    ),
                )
            self.instances.release_family(
                policy.orphan_release(
                    family,
                    evidence.startup_id,
                )
            )

    def release_session_family_and_reconcile(
        self,
        family: PluginInstanceLeaseFamilyV1,
    ) -> None:
        """Linearize the last Session release with cross-journal retirement."""
        policy = self._membership_policy

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError(
                f"{policy.product_label} Session release requires a Session family"
            )
        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            self.instances.release_family(policy.family_release(family))
            self._reconcile_retirements_unlocked()

    def publish_session_owner_generations(
        self,
        family: PluginInstanceLeaseFamilyV1,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        """Publish only owner generations with prior durable preparation."""
        policy = self._membership_policy

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError(
                f"{policy.product_label} owner publication requires a Session family"
            )
        [member] = family.members
        self.owner_evidence.publish(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            publication_reference=f"{policy.identity_prefix}-session-publication:{family.family_id}",
        )

    def prepare_session_owner_generations(
        self,
        family: PluginInstanceLeaseFamilyV1,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        """Write exact cleanup identities before owner publication can commit."""
        policy = self._membership_policy

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError(
                f"{policy.product_label} owner preparation requires a Session family"
            )
        [member] = family.members
        self.owner_evidence.prepare(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            preparation_reference=f"{policy.identity_prefix}-session-preparation:{family.family_id}",
        )

    def retire_session_owner_generations(
        self,
        family: PluginInstanceLeaseFamilyV1,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        """Record success only after the exact owner runtimes fully disposed."""
        policy = self._membership_policy

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError(
                f"{policy.product_label} owner retirement requires a Session family"
            )
        [member] = family.members
        self.owner_evidence.retire(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            outcome_reference=f"{policy.identity_prefix}-session-disposed:{family.family_id}",
        )

    def _ensure_owner_retirement_plan(
        self,
        intent: PluginRetirementIntentV1,
        runtime: PluginInstanceRuntimeInventorySnapshotV1,
    ) -> None:
        policy = self._membership_policy
        report_exact_owner_retirement(
            intent,
            runtime,
            retirement_sets=self.retirement_sets,
            owner_evidence=self.owner_evidence,
            policy=policy.retirement_policy,
        )

    def management_retirement_intents(self) -> tuple[PluginRetirementIntentV1, ...]:
        return (
            PluginRetirementIntentLedger(self.layout.retirement_intents)
            .snapshot()
            .intents
        )

    @contextmanager
    def _acquire_session_family(
        self,
        key: PluginInstallationKeyV1,
        *,
        session_id: str,
        lease_attempt_id: str,
        owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
        session_owner_id: str | None = None,
    ) -> Iterator[tuple[PluginInstanceLeaseFamilyV1, Owners, LeaseT]]:
        policy = self._membership_policy
        resolved_owner_id = session_owner_id or secrets.token_hex(16)
        session_owner_lease = _acquire_session_owner_lease(
            policy.owner_path(self.layout, session_id),
            owner_id=resolved_owner_id,
            lease_type=self._owner_lease_type,
        )
        try:
            self.reconcile_retirements()
            state = self.desired.snapshot().installation(key)
            ref = state.selection.instance_revision_ref
            if state.selection.desired_state != "installed_enabled" or ref is None:
                raise policy.make_error(
                    f"Plugin Installation is not selected for a new {policy.product_label} Session",
                    f"{policy.error_code_prefix}_not_enabled",
                )
            instance = self.instances.snapshot().instance(ref)
            activation_identity = policy.activation_identity(key, ref)
            if instance is None:
                instance = self.instances.activate_current(
                    key,
                    operation_id=f"{policy.identity_prefix}-plugin-activate:{activation_identity}",
                    idempotency_key=f"{policy.identity_prefix}-plugin-activate:{activation_identity}",
                    direct_host_reference=(
                        f"{policy.identity_prefix}-plugin-host:"
                        f"{self.layout.scope_id}:{ref.instance_id}:{ref.revision}"
                    ),
                )
            if instance.state != "ACTIVE" or instance.instance_revision_ref != ref:
                raise policy.make_error(
                    "Selected Plugin Instance is not ACTIVE",
                    f"{policy.error_code_prefix}_instance_not_active",
                )
            owners = policy.normalize_owners(owner_contributions)
            identity = policy.lease_identity(
                key,
                ref,
                session_id,
                lease_attempt_id,
                owners,
            )
            holder_reference = policy.holder_reference(
                session_id,
                lease_attempt_id,
                owners,
                self.startup_id,
            )
            family = self.instances.acquire_current_family(
                (key,),
                lease_kind="session_membership",
                operation_id=f"{policy.identity_prefix}-plugin-session:{identity}",
                idempotency_key=f"{policy.identity_prefix}-plugin-session:{identity}",
                holder_reference=holder_reference,
            )
            [member] = family.members
            if member.instance_revision_ref != ref:
                release = policy.family_release(family)
                self.instances.release_family(release)
                raise policy.make_error(
                    "Session lease returned another Plugin Instance Revision",
                    f"{policy.error_code_prefix}_instance_revision_stale",
                )
            yield family, owners, session_owner_lease
        except BaseException:
            session_owner_lease.__exit__(None, None, None)
            raise
