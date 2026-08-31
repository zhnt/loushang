"""Coding Product adapter for the common durable Plugin lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_owner_generations import (
    CodingOwnerGenerationEvidenceLedger,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.journal import JournalLockUnavailable, journal_file_lock
from loushang.harness.plugin_management import (
    PluginCleanupAttemptV1,
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRetirementCompletionV1,
    PluginInstanceRuntimeLedger,
    PluginManagementCommandV1,
    PluginManagementService,
    PluginOwnerRetirementOutcomeV1,
    PluginOwnerRetirementPlanV1,
    PluginOwnerRetirementTargetV1,
    PluginPackageLifecycleLedger,
    PluginPackageRevisionRefV1,
    PluginRetirementIntentLedger,
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.resources.plugins import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)

_PRODUCT_POLICY_REVISION = "coding-plugin-lifecycle-v1"
_DEFAULT_APPROVAL_REFERENCE = "coding-first-party-default"
_CODING_PLUGIN_RUNTIME_BOOT_ID = secrets.token_hex(16)
_PROCESS_STARTUP_LEASES_LOCK = threading.Lock()
_PROCESS_STARTUP_LEASES: dict[Path, AbstractContextManager[None]] = {}
_PROCESS_SESSION_OWNER_LEASES_LOCK = threading.Lock()


@dataclass(slots=True)
class _ProcessSessionOwnerLeaseState:
    owner_id: str
    authority_id: str
    lease: AbstractContextManager[None]
    references: int = 1
    runtime_claim_id: str | None = None
    runtime_claim_references: int = 0


_PROCESS_SESSION_OWNER_LEASES: dict[Path, _ProcessSessionOwnerLeaseState] = {}


@dataclass(slots=True)
class _ProcessSessionOwnerLease(AbstractContextManager[None]):
    path: Path
    owner_id: str
    authority_id: str
    _runtime_claim_id: str | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _state_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def claim_runtime(self, claim_id: str) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("Closed Coding Session owner cannot claim a runtime")
            normalized_claim_id = _nonempty(
                claim_id,
                name="Session runtime claim id",
            )
            if self._runtime_claim_id == normalized_claim_id:
                return
            if self._runtime_claim_id is not None:
                raise RuntimeError(
                    "Coding Session owner lease already claimed another runtime"
                )
            _claim_session_owner_runtime(
                self.path,
                owner_id=self.owner_id,
                authority_id=self.authority_id,
                claim_id=normalized_claim_id,
            )
            self._runtime_claim_id = normalized_claim_id

    def __exit__(self, *_args: object) -> None:
        with self._state_lock:
            if self._closed:
                return
            try:
                _release_session_owner_lease(
                    self.path,
                    owner_id=self.owner_id,
                    authority_id=self.authority_id,
                    runtime_claim_id=self._runtime_claim_id,
                )
            except BaseException:
                with _PROCESS_SESSION_OWNER_LEASES_LOCK:
                    current = _PROCESS_SESSION_OWNER_LEASES.get(self.path)
                    authority_was_removed = (
                        current is None
                        or current.authority_id != self.authority_id
                    )
                # journal_file_lock closes its handle even when platform
                # unlock reports an error. In that case the exact authority
                # incarnation was removed and this wrapper cannot retry it.
                if authority_was_removed:
                    self._closed = True
                raise
            else:
                self._closed = True


class CodingPluginLifecycleError(RuntimeError):
    """Stable Product failure at the common management boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPluginLifecycleStateLayout:
    """One workspace namespace for every Coding Plugin Installation."""

    root: Path
    private_state_base: Path
    package_root: Path
    private_data_base: Path
    scope_id: str
    desired_state: Path
    management_operations: Path
    retirement_intents: Path
    retirement_sets: Path
    instance_runtime: Path
    package_lifecycle: Path

    @property
    def package_install_root(self) -> Path:
        return self.package_root / "installed"

    @property
    def package_lockfile(self) -> Path:
        return self.package_root / "package-lock.json"

    @property
    def plugin_revision_root(self) -> Path:
        return self.package_root / "plugin-revisions"

    @property
    def owner_generation_evidence(self) -> Path:
        return self.root / "owner-generation-evidence.jsonl"

    @property
    def coordination_lock(self) -> Path:
        return self.root / "lifecycle-coordination"


@dataclass(slots=True)
class CodingPluginLifecycle:
    """Installed common Harness authorities bound to Coding Product policy."""

    layout: CodingPluginLifecycleStateLayout
    startup_id: str
    desired: PluginDesiredStateLedger = field(repr=False)
    management: PluginManagementService = field(repr=False)
    instances: PluginInstanceRuntimeLedger = field(repr=False)
    retirement_sets: PluginRetirementSetLedger = field(repr=False)
    packages: PluginPackageLifecycleLedger = field(repr=False)
    security: PluginInstanceSecurityRetirementJournal = field(repr=False)
    owner_evidence: CodingOwnerGenerationEvidenceLedger = field(repr=False)
    _owns_process_startup_lease: bool = field(repr=False)

    def release_owned_process_startup_lease(self) -> None:
        """Release a startup lease acquired specifically by this lifecycle.

        Durable Coding state deliberately keeps its startup lease for the
        process lifetime. Disposable composition roots instead call this
        before removing their private state directory.
        """

        if not self._owns_process_startup_lease:
            return
        _release_process_startup_lease(
            self.layout,
            startup_id=self.startup_id,
        )
        self._owns_process_startup_lease = False

    def complete_startup_recovery(self) -> None:
        """Seal Package recovery after the composition root reconciles Instances."""

        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            self._reconcile_retirements_unlocked()
            self.packages.complete_startup_recovery(
                operation_id=f"coding-package-recovery:{self.startup_id}",
                idempotency_key=f"coding-package-recovery:{self.startup_id}",
                recovery_reference=f"coding-runtime:{self.startup_id}",
            )

    def installation_key(self, plugin_id: str) -> PluginInstallationKeyV1:
        return PluginInstallationKeyV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=_nonempty(plugin_id, name="Plugin id"),
        )

    def bootstrap_first_party_default(
        self,
        key: PluginInstallationKeyV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> None:
        """Install+enable only a truly unseen first-party Installation.

        An absent record retained after remove is deliberately *seen* and is
        therefore never resurrected by Product composition.
        """

        # The two management commands are individually durable.  This loop is
        # the Product transaction coordinator: it resumes only its own exact
        # default install, stops at any operator-authored state, and retries a
        # CAS race with a fresh operation identity.
        for _attempt in range(32):
            snapshot = self.desired.snapshot()
            state = snapshot.installation(key)
            seen = any(
                item.installation_key == key for item in snapshot.installations
            )
            if not seen:
                error = self._submit_default(
                    key,
                    action="install",
                    desired_state="installed_disabled",
                    package_revision=package_revision,
                    expected_inventory_revision=snapshot.inventory_revision,
                )
                if error == "plugin_inventory_revision_conflict":
                    continue
                if error is not None:
                    raise CodingPluginLifecycleError(
                        "First-party Plugin bootstrap install failed",
                        code=error,
                    )
                continue
            if state.selection.desired_state == "installed_enabled":
                return
            if not self._is_own_default_install(
                key,
                package_revision=package_revision,
            ):
                return
            error = self._submit_default(
                key,
                action="enable",
                desired_state="installed_enabled",
                package_revision=None,
                expected_inventory_revision=snapshot.inventory_revision,
            )
            if error == "plugin_inventory_revision_conflict":
                continue
            if error is not None:
                raise CodingPluginLifecycleError(
                    "First-party Plugin bootstrap enable failed",
                    code=error,
                )
            return
        raise CodingPluginLifecycleError(
            "First-party Plugin bootstrap could not linearize",
            code="coding_plugin_default_bootstrap_busy",
        )

    def _is_own_default_install(
        self,
        key: PluginInstallationKeyV1,
        *,
        package_revision: PluginPackageRevisionRefV1,
    ) -> bool:
        matching = tuple(
            transition
            for transition in self.desired.transitions()
            if transition.mutation.installation_key == key
        )
        if not matching:
            return False
        mutation = matching[-1].mutation
        return (
            isinstance(mutation, PluginDesiredStateMutationV1)
            and mutation.desired_state == "installed_disabled"
            and mutation.package_revision == package_revision
            and mutation.actor_id == "product:coding"
            and mutation.policy_revision == _PRODUCT_POLICY_REVISION
            and mutation.approval_reference == _DEFAULT_APPROVAL_REFERENCE
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

        runtime = self.instances.snapshot()
        for family in runtime.open_families:
            if family.lease_kind != "session_membership":
                continue
            evidence = _session_holder_evidence(family.holder_reference)
            if (
                evidence is None
                or evidence.startup_id == self.startup_id
                or not _startup_lease_is_inactive(
                    self.layout,
                    startup_id=evidence.startup_id,
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
                        "coding-session-process-exit-confirmed:"
                        f"{evidence.startup_id}:{family.family_id}"
                    ),
                )
            self.instances.release_family(
                _orphan_family_release(
                    family,
                    inactive_startup_id=evidence.startup_id,
                )
            )

    def release_session_family_and_reconcile(
        self,
        family: PluginInstanceLeaseFamilyV1,
    ) -> None:
        """Linearize the last Session release with cross-journal retirement."""

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError("Coding Session release requires a Session family")
        with journal_file_lock(self.layout.coordination_lock, "exclusive"):
            self.instances.release_family(_family_release(family))
            self._reconcile_retirements_unlocked()

    def publish_session_owner_generations(
        self,
        family: PluginInstanceLeaseFamilyV1,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        """Bind actual live owner generations to their exact Session family."""

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError("Coding owner publication requires a Session family")
        [member] = family.members
        # Preserve the write-ahead invariant for legacy/public callers that
        # still invoke publish directly.  Ledger replay remains compatible
        # with historical journals whose first record was already published.
        self.owner_evidence.prepare(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            preparation_reference=f"coding-session-preparation:{family.family_id}",
        )
        self.owner_evidence.publish(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            publication_reference=f"coding-session-publication:{family.family_id}",
        )

    def prepare_session_owner_generations(
        self,
        family: PluginInstanceLeaseFamilyV1,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        """Write exact cleanup identities before owner publication can commit."""

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError("Coding owner preparation requires a Session family")
        [member] = family.members
        self.owner_evidence.prepare(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            preparation_reference=f"coding-session-preparation:{family.family_id}",
        )

    def retire_session_owner_generations(
        self,
        family: PluginInstanceLeaseFamilyV1,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        """Record success only after the exact owner runtimes fully disposed."""

        if not isinstance(family, PluginInstanceLeaseFamilyV1):
            raise TypeError("Coding owner retirement requires a Session family")
        [member] = family.members
        self.owner_evidence.retire(
            family_id=family.family_id,
            instance_revision_ref=member.instance_revision_ref,
            receipts=receipts,
            outcome_reference=f"coding-session-disposed:{family.family_id}",
        )

    def _ensure_owner_retirement_plan(self, intent, runtime) -> None:
        retirement_set = self.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        if retirement_set is None:
            raise CodingPluginLifecycleError(
                "Coding retirement set is unavailable",
                code="coding_plugin_retirement_set_unavailable",
            )
        if retirement_set.plan is None and any(
            family.lease_kind == "session_membership"
            and any(
                member.instance_revision_ref == intent.instance_revision_ref
                for member in family.members
            )
            for family in runtime.open_families
        ):
            # A family that acquired before cutover may still publish its exact
            # owner generations.  Seal the plan only after every Session family
            # has either retired its receipts or closed without publishing.
            return
        families = self.owner_evidence.retired_families_for_instance(
            intent.instance_revision_ref
        )
        receipts = tuple(
            receipt for family in families for receipt in family.receipts
        )
        targets = tuple(
            PluginOwnerRetirementTargetV1.create(
                owner_reference=receipt.owner_reference,
                owner_generation_reference=receipt.owner_generation_reference,
                retirement_handle=receipt.retirement_handle,
                contribution_ids=receipt.contribution_ids,
            )
            for receipt in receipts
        )
        canonical_targets = tuple(sorted(targets, key=lambda item: item.target_id))
        closure_digest = hashlib.sha256(
            repr(tuple(item.target_id for item in canonical_targets)).encode("utf-8")
        ).hexdigest()
        # Re-submit the exact plan and outcomes idempotently.  A process may
        # stop after sealing the plan or after only some target outcomes; the
        # next reconciliation must finish that durable transition.
        committed = self.retirement_sets.commit_plan(
            PluginOwnerRetirementPlanV1.create(
                retirement_id=intent.retirement_id,
                owner_closure_reference=f"coding-owner-closure:{closure_digest}",
                targets=canonical_targets,
            )
        )
        if committed.plan is None:
            raise CodingPluginLifecycleError(
                "Coding owner retirement plan was not committed",
                code="coding_plugin_owner_retirement_plan_unavailable",
            )
        outcome_references = {
            (
                receipt.owner_reference,
                receipt.owner_generation_reference,
                receipt.retirement_handle,
            ): family.retirement_outcome_reference
            for family in families
            for receipt in family.receipts
        }
        for target in committed.plan.targets:
            outcome_reference = outcome_references[
                (
                    target.owner_reference,
                    target.owner_generation_reference,
                    target.retirement_handle,
                )
            ]
            if outcome_reference is None:
                raise CodingPluginLifecycleError(
                    "Coding owner retirement lacks an exact cleanup outcome",
                    code="coding_plugin_owner_retirement_outcome_unavailable",
                )
            identity = hashlib.sha256(
                repr((intent.retirement_id, target.target_id)).encode("utf-8")
            ).hexdigest()
            self.retirement_sets.record_outcome(
                PluginOwnerRetirementOutcomeV1(
                    retirement_id=intent.retirement_id,
                    target_id=target.target_id,
                    operation_id=f"coding-owner-retired:{identity}",
                    idempotency_key=f"coding-owner-retired:{identity}",
                    attempt=1,
                    disposition="succeeded",
                    result_code="coding.owner.exact_retired",
                    owner_outcome_reference=outcome_reference,
                )
            )

    def _complete_ready_retirement(self, intent) -> None:
        retirement_set = self.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        if retirement_set is None or retirement_set.state != "succeeded":
            return
        runtime = self.instances.snapshot()
        instance = runtime.instance(intent.instance_revision_ref)
        if instance is None or instance.state == "RETIRED":
            return
        direct_family = instance.activation.direct_host_family
        open_family_ids = set(instance.open_family_ids)
        if open_family_ids not in ({direct_family.family_id}, set()):
            return
        identity = intent.retirement_id
        # The cleanup handoff is write-ahead: after it appends the durable task
        # it releases the direct-host family.  Therefore an empty family set is
        # a valid interrupted state, and replaying the same operation must
        # resume the task rather than wait forever for a family already handed
        # off.
        task = self.packages.handoff_cleanup_and_release(
            direct_family.family_id,
            retirement_target_id=None,
            cleanup_kind="coding.product_host.shutdown",
            operation_id=f"coding-host-cleanup:{identity}",
            idempotency_key=f"coding-host-cleanup:{identity}",
            cleanup_reference=f"coding-host:{self.layout.scope_id}",
            family_release=_family_release(direct_family),
        )
        self.packages.record_cleanup_attempt(
            PluginCleanupAttemptV1(
                cleanup_id=task.cleanup_id,
                operation_id=f"coding-host-cleaned:{identity}",
                idempotency_key=f"coding-host-cleaned:{identity}",
                attempt=1,
                disposition="succeeded",
                result_code="coding.host.retired",
                retry_not_before_epoch_ms=None,
                outcome_reference=f"coding-host-outcome:{self.layout.scope_id}",
            )
        )
        self.instances.complete_retirement(
            PluginInstanceRetirementCompletionV1.create(
                completion_kind="graceful",
                coordination_id=intent.retirement_id,
                installation_key=instance.installation_key,
                instance_revision_ref=instance.instance_revision_ref,
                operation_id=f"coding-instance-retired:{identity}",
                idempotency_key=f"coding-instance-retired:{identity}",
                completion_reference=f"coding-instance:{self.layout.scope_id}",
            )
        )

    def management_retirement_intents(self):
        return PluginRetirementIntentLedger(
            self.layout.retirement_intents
        ).snapshot().intents

    def acquire_session(
        self,
        key: PluginInstallationKeyV1,
        *,
        session_id: str,
        lease_attempt_id: str,
        owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
        session_owner_id: str | None = None,
    ) -> CodingPluginSessionLease:
        session_owner_lease = _acquire_session_owner_lease(
            self.layout,
            session_id=session_id,
            owner_id=session_owner_id or secrets.token_hex(16),
        )
        try:
            self.reconcile_retirements()
            state = self.desired.snapshot().installation(key)
            ref = state.selection.instance_revision_ref
            if state.selection.desired_state != "installed_enabled" or ref is None:
                raise CodingPluginLifecycleError(
                    "Plugin Installation is not selected for a new Coding Session",
                    code="coding_plugin_not_enabled",
                )
            instance = self.instances.snapshot().instance(ref)
            activation_identity = _activation_identity(key, ref)
            if instance is None:
                instance = self.instances.activate_current(
                    key,
                    operation_id=f"coding-plugin-activate:{activation_identity}",
                    idempotency_key=f"coding-plugin-activate:{activation_identity}",
                    direct_host_reference=(
                        "coding-plugin-host:"
                        f"{self.layout.scope_id}:{ref.instance_id}:{ref.revision}"
                    ),
                )
            if instance.state != "ACTIVE" or instance.instance_revision_ref != ref:
                raise CodingPluginLifecycleError(
                    "Selected Plugin Instance is not ACTIVE",
                    code="coding_plugin_instance_not_active",
                )
            owners = _normalize_owner_contributions(owner_contributions)
            identity = _lease_identity(
                key,
                ref,
                session_id,
                lease_attempt_id,
                owners,
            )
            holder_reference = _session_holder_reference(
                session_id=session_id,
                lease_attempt_id=lease_attempt_id,
                owner_contributions=owners,
                startup_id=self.startup_id,
            )
            family = self.instances.acquire_current_family(
                (key,),
                lease_kind="session_membership",
                operation_id=f"coding-plugin-session:{identity}",
                idempotency_key=f"coding-plugin-session:{identity}",
                holder_reference=holder_reference,
            )
            [member] = family.members
            if member.instance_revision_ref != ref:
                release = _family_release(family)
                self.instances.release_family(release)
                raise CodingPluginLifecycleError(
                    "Session lease returned another Plugin Instance Revision",
                    code="coding_plugin_instance_revision_stale",
                )
            return CodingPluginSessionLease(
                lifecycle=self,
                installation_key=key,
                family=family,
                package_revision=member.package_revision,
                instance_revision_ref=member.instance_revision_ref,
                owner_contributions=owners,
                _session_owner_lease=session_owner_lease,
            )
        except BaseException:
            session_owner_lease.__exit__(None, None, None)
            raise

    def _submit_default(
        self,
        key: PluginInstallationKeyV1,
        *,
        action: Literal["install", "enable"],
        desired_state: Literal["installed_disabled", "installed_enabled"],
        package_revision: PluginPackageRevisionRefV1 | None,
        expected_inventory_revision: int,
    ) -> str | None:
        identity = hashlib.sha256(
            repr(
                (key, action, package_revision, expected_inventory_revision)
            ).encode("utf-8")
        ).hexdigest()
        event = self.management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=f"coding-default:{identity}",
                    idempotency_key=f"coding-default:{identity}",
                    expected_inventory_revision=expected_inventory_revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=package_revision,
                    actor_id="product:coding",
                    policy_revision=_PRODUCT_POLICY_REVISION,
                    approval_reference=_DEFAULT_APPROVAL_REFERENCE,
                ),
            )
        )
        result = getattr(event, "result", None)
        if result is None:
            return "coding_plugin_default_management_failed"
        if result.disposition != "succeeded":
            return result.error_code or "coding_plugin_default_management_failed"
        return None


@dataclass(slots=True)
class CodingPluginSessionLease:
    """One exact Plugin Instance family pinned by a Coding Session."""

    lifecycle: CodingPluginLifecycle = field(repr=False)
    installation_key: PluginInstallationKeyV1
    family: PluginInstanceLeaseFamilyV1
    package_revision: PluginPackageRevisionRefV1
    instance_revision_ref: PluginInstanceRevisionRef
    owner_contributions: tuple[tuple[str, tuple[str, ...]], ...]
    _session_owner_lease: _ProcessSessionOwnerLease = field(
        repr=False,
    )
    _closed: bool = field(default=False, init=False, repr=False)

    def claim_runtime(self, runtime_claim_id: str | None = None) -> None:
        if self._closed:
            raise CodingPluginLifecycleError(
                "Closed Coding Session cannot claim a runtime",
                code="coding_plugin_session_lease_closed",
            )
        self._session_owner_lease.claim_runtime(
            self.family.family_id
            if runtime_claim_id is None
            else _nonempty(runtime_claim_id, name="Session runtime claim id")
        )

    def evaluate_management_change(self) -> CodingPluginManagementChange:
        snapshot = self.lifecycle.desired.snapshot()
        state = snapshot.installation(self.installation_key)
        current_ref = state.selection.instance_revision_ref
        current_package = state.selection.package_revision
        if (
            state.selection.desired_state == "installed_enabled"
            and current_ref == self.instance_revision_ref
            and current_package == self.package_revision
        ):
            disposition: Literal["no_change", "restart_required"] = "no_change"
            reason = "selected_revision_unchanged"
        else:
            disposition = "restart_required"
            reason = {
                "absent": "plugin_removed",
                "installed_disabled": "plugin_disabled",
                "installed_enabled": "plugin_updated",
            }[state.selection.desired_state]
        return CodingPluginManagementChange(
            disposition=disposition,
            reason=reason,
            inventory_revision=snapshot.inventory_revision,
            desired_state=state.selection.desired_state,
            pinned_instance_revision_ref=self.instance_revision_ref,
            current_instance_revision_ref=current_ref,
            pinned_package_revision=self.package_revision,
            current_package_revision=current_package,
        )

    def prepare_owner_generations(
        self,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        if self._closed:
            raise CodingPluginLifecycleError(
                "Closed Coding Session cannot prepare owner generations",
                code="coding_plugin_session_lease_closed",
            )
        self.lifecycle.prepare_session_owner_generations(self.family, receipts)

    def publish_owner_generations(
        self,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        if self._closed:
            raise CodingPluginLifecycleError(
                "Closed Coding Session cannot publish owner generations",
                code="coding_plugin_session_lease_closed",
            )
        self.lifecycle.publish_session_owner_generations(self.family, receipts)

    def retire_owner_generations(
        self,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        if self._closed:
            raise CodingPluginLifecycleError(
                "Closed Coding Session cannot retire owner generations",
                code="coding_plugin_session_lease_closed",
            )
        self.lifecycle.retire_session_owner_generations(self.family, receipts)

    def close(self) -> None:
        if self._closed:
            return
        evidence = self.lifecycle.owner_evidence.family(self.family.family_id)
        if evidence is not None and not evidence.retired:
            raise CodingPluginLifecycleError(
                "Coding Session owner generation cleanup remains pending",
                code="coding_plugin_owner_generation_cleanup_pending",
            )
        self.lifecycle.release_session_family_and_reconcile(self.family)
        self._session_owner_lease.__exit__(None, None, None)
        self._closed = True


@dataclass(frozen=True, slots=True)
class CodingPluginManagementChange:
    disposition: Literal["no_change", "restart_required"]
    reason: str
    inventory_revision: int
    desired_state: Literal["absent", "installed_disabled", "installed_enabled"]
    pinned_instance_revision_ref: PluginInstanceRevisionRef
    current_instance_revision_ref: PluginInstanceRevisionRef | None
    pinned_package_revision: PluginPackageRevisionRefV1
    current_package_revision: PluginPackageRevisionRefV1 | None

    def diagnostic_details(self) -> dict[str, object]:
        return {
            "currentInstanceRevisionRef": (
                None
                if self.current_instance_revision_ref is None
                else self.current_instance_revision_ref.to_dict()
            ),
            "currentPackageRevision": (
                None
                if self.current_package_revision is None
                else self.current_package_revision.to_dict()
            ),
            "desiredState": self.desired_state,
            "inventoryRevision": self.inventory_revision,
            "pinnedInstanceRevisionRef": self.pinned_instance_revision_ref.to_dict(),
            "pinnedPackageRevision": self.pinned_package_revision.to_dict(),
            "reason": self.reason,
            "restartRequired": self.disposition == "restart_required",
        }


def resolve_coding_plugin_lifecycle_state_layout(
    cwd: str | Path,
    *,
    platform_paths: PlatformPaths | None = None,
) -> CodingPluginLifecycleStateLayout:
    workspace = Path(cwd).expanduser().resolve(strict=False)
    # Keep the deployed Continuity workspace identity and location.  PLC6D
    # widens that namespace into the one Coding Product lifecycle authority;
    # changing it would silently strand existing desired-state journals.
    digest = hashlib.sha256(
        b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
    ).hexdigest()
    paths = platform_paths or resolve_platform_paths()
    root = paths.state / "plugins" / "coding" / "continuity" / "workspaces" / digest
    package_root = paths.data / "plugins" / "coding" / "workspaces" / digest
    private_state_base = (
        paths.home
        if paths.state == paths.home or paths.home in paths.state.parents
        else paths.state
    )
    return CodingPluginLifecycleStateLayout(
        root=root,
        private_state_base=private_state_base,
        package_root=package_root,
        private_data_base=(
            paths.home
            if paths.data == paths.home or paths.home in paths.data.parents
            else paths.data
        ),
        scope_id=f"workspace:{digest}",
        desired_state=root / "desired-state.jsonl",
        management_operations=root / "management-operations.jsonl",
        retirement_intents=root / "retirement-intents.jsonl",
        retirement_sets=root / "retirement-sets.jsonl",
        instance_runtime=root / "instance-runtime.jsonl",
        package_lifecycle=root / "package-lifecycle.jsonl",
    )


def resolve_ephemeral_coding_plugin_lifecycle_state_layout(
    session_dir: str | Path,
    *,
    cwd: str | Path,
) -> CodingPluginLifecycleStateLayout:
    """Bind non-persistent Sessions to disposable management evidence."""

    base = Path(session_dir).expanduser().resolve(strict=False)
    root = base / "plugin-state" / "coding-lifecycle"
    workspace = Path(cwd).expanduser().resolve(strict=False)
    digest = hashlib.sha256(
        b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
    ).hexdigest()
    return CodingPluginLifecycleStateLayout(
        root=root,
        private_state_base=base,
        package_root=base / "plugin-packages" / "coding-lifecycle",
        private_data_base=base,
        scope_id=f"workspace:{digest}",
        desired_state=root / "desired-state.jsonl",
        management_operations=root / "management-operations.jsonl",
        retirement_intents=root / "retirement-intents.jsonl",
        retirement_sets=root / "retirement-sets.jsonl",
        instance_runtime=root / "instance-runtime.jsonl",
        package_lifecycle=root / "package-lifecycle.jsonl",
    )


def build_coding_plugin_lifecycle(
    layout: CodingPluginLifecycleStateLayout,
    *,
    startup_id: str | None = None,
    security_acceptances: PluginInstanceSecurityRetirementJournal | None = None,
) -> CodingPluginLifecycle:
    if not isinstance(layout, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    _prepare_private_state_layout(layout)
    desired = PluginDesiredStateLedger(layout.desired_state)
    intents = PluginRetirementIntentLedger(layout.retirement_intents)
    retirement_sets = PluginRetirementSetLedger(
        layout.retirement_sets,
        retirement_intents=intents,
    )
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=layout.management_operations,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
    )
    management.recover()
    security = security_acceptances or (
        PluginInstanceSecurityRetirementJournal.for_instance_runtime(
            layout.instance_runtime
        )
    )
    instances = PluginInstanceRuntimeLedger(
        layout.instance_runtime,
        management_operation_journal_path=layout.management_operations,
        desired_state=desired,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
        security_acceptances=security,
    )
    resolved_startup_id = startup_id or _CODING_PLUGIN_RUNTIME_BOOT_ID
    owns_process_startup_lease = _hold_process_startup_lease(
        layout,
        startup_id=resolved_startup_id,
    )
    try:
        packages = PluginPackageLifecycleLedger(
            layout.package_lifecycle,
            startup_id=resolved_startup_id,
            desired_state=desired,
            instance_runtime=instances,
            retirement_sets=retirement_sets,
        )
        owner_evidence = CodingOwnerGenerationEvidenceLedger(
            layout.owner_generation_evidence
        )
        return CodingPluginLifecycle(
            layout=layout,
            startup_id=resolved_startup_id,
            desired=desired,
            management=management,
            instances=instances,
            retirement_sets=retirement_sets,
            packages=packages,
            security=security,
            owner_evidence=owner_evidence,
            _owns_process_startup_lease=owns_process_startup_lease,
        )
    except BaseException:
        if owns_process_startup_lease:
            _release_process_startup_lease(
                layout,
                startup_id=resolved_startup_id,
            )
        raise


def package_revision_ref(
    *,
    plugin_id: str,
    plugin_version: str | None,
    package_content_digest: str,
    dependency_lock_digest: str,
    package_source_identity: str,
) -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        package_content_digest=package_content_digest,
        dependency_lock_digest=dependency_lock_digest,
        package_source_identity=package_source_identity,
    )


def _family_release(
    family: PluginInstanceLeaseFamilyV1,
) -> PluginInstanceLeaseFamilyReleaseV1:
    return PluginInstanceLeaseFamilyReleaseV1(
        family_id=family.family_id,
        operation_id=f"coding-plugin-release:{family.family_id}",
        idempotency_key=f"coding-plugin-release:{family.family_id}",
        release_reference=family.holder_reference,
    )


def _orphan_family_release(
    family: PluginInstanceLeaseFamilyV1,
    *,
    inactive_startup_id: str,
) -> PluginInstanceLeaseFamilyReleaseV1:
    identity = hashlib.sha256(
        repr((family.family_id, inactive_startup_id)).encode("utf-8")
    ).hexdigest()
    return PluginInstanceLeaseFamilyReleaseV1(
        family_id=family.family_id,
        operation_id=f"coding-plugin-orphan-release:{identity}",
        idempotency_key=f"coding-plugin-orphan-release:{identity}",
        release_reference=(
            "coding-session-process-exit-confirmed:"
            f"{inactive_startup_id}:{family.family_id}"
        ),
    )


def _activation_identity(
    key: PluginInstallationKeyV1,
    ref: PluginInstanceRevisionRef,
) -> str:
    return hashlib.sha256(repr((key, ref)).encode("utf-8")).hexdigest()


def _lease_identity(
    key: PluginInstallationKeyV1,
    ref: PluginInstanceRevisionRef,
    session_id: str,
    lease_attempt_id: str,
    owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
) -> str:
    return hashlib.sha256(
        repr(
            (
                key,
                ref,
                _nonempty(session_id, name="Session id"),
                _nonempty(lease_attempt_id, name="Lease attempt id"),
                owner_contributions,
            )
        ).encode("utf-8")
    ).hexdigest()


def _normalize_owner_contributions(
    values: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(values, tuple):
        raise TypeError("Coding owner contributions must be a tuple")
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for owner_reference, contribution_ids in values:
        owner = _nonempty(owner_reference, name="Owner reference")
        if (
            not isinstance(contribution_ids, tuple)
            or not contribution_ids
            or any(
                not isinstance(item, str) or not item or item.strip() != item
                for item in contribution_ids
            )
        ):
            raise ValueError("Owner contribution ids must be non-empty strings")
        canonical_ids = tuple(sorted(set(contribution_ids)))
        normalized.append((owner, canonical_ids))
    canonical = tuple(sorted(normalized))
    if len({owner for owner, _items in canonical}) != len(canonical):
        raise ValueError("Coding owner references must be unique")
    return canonical


_SESSION_HOLDER_PREFIX = "coding-session-owner-family:v2:"


@dataclass(frozen=True, slots=True)
class _CodingSessionHolderEvidence:
    startup_id: str
    owner_contributions: tuple[tuple[str, tuple[str, ...]], ...]


def _session_holder_reference(
    *,
    session_id: str,
    lease_attempt_id: str,
    owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
    startup_id: str,
) -> str:
    payload = {
        "leaseAttemptId": _nonempty(lease_attempt_id, name="Lease attempt id"),
        "owners": [
            {
                "contributionIds": list(contribution_ids),
                "ownerReference": owner_reference,
            }
            for owner_reference, contribution_ids in owner_contributions
        ],
        "sessionId": _nonempty(session_id, name="Session id"),
        "startupId": _nonempty(startup_id, name="Startup id"),
    }
    return _SESSION_HOLDER_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _session_holder_evidence(
    holder_reference: str,
) -> _CodingSessionHolderEvidence | None:
    if not holder_reference.startswith(_SESSION_HOLDER_PREFIX):
        # V1 and foreign holder references contain no process epoch.  Preserve
        # them fail-closed because inactivity cannot be proven.
        return None
    try:
        payload = json.loads(holder_reference[len(_SESSION_HOLDER_PREFIX) :])
        if not isinstance(payload, dict) or set(payload) != {
            "leaseAttemptId",
            "owners",
            "sessionId",
            "startupId",
        }:
            raise ValueError("invalid Session holder fields")
        _nonempty(payload["leaseAttemptId"], name="Lease attempt id")
        _nonempty(payload["sessionId"], name="Session id")
        startup_id = _nonempty(payload["startupId"], name="Startup id")
        owners = payload["owners"]
        if not isinstance(owners, list):
            raise ValueError("owners must be an array")
        values = tuple(
            (
                item["ownerReference"],
                tuple(item["contributionIds"]),
            )
            for item in owners
            if isinstance(item, dict)
            and set(item) == {"contributionIds", "ownerReference"}
            and isinstance(item["contributionIds"], list)
        )
        if len(values) != len(owners):
            raise ValueError("invalid owner entry")
        return _CodingSessionHolderEvidence(
            startup_id=startup_id,
            owner_contributions=_normalize_owner_contributions(values),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CodingPluginLifecycleError(
            "Coding Session family owner evidence is invalid",
            code="coding_plugin_session_owner_evidence_invalid",
        ) from exc


def _startup_lease_path(
    layout: CodingPluginLifecycleStateLayout,
    *,
    startup_id: str,
) -> Path:
    identity = hashlib.sha256(
        b"loushang.coding-plugin-startup/v1\0"
        + _nonempty(startup_id, name="Startup id").encode("utf-8")
    ).hexdigest()
    return (layout.root / "process-startups" / f"{identity}.lease").resolve()


def _session_owner_lease_path(
    layout: CodingPluginLifecycleStateLayout,
    *,
    session_id: str,
) -> Path:
    identity = hashlib.sha256(
        b"loushang.coding-plugin-session-owner/v1\0"
        + _nonempty(session_id, name="Session id").encode("utf-8")
    ).hexdigest()
    return (layout.root / "session-owners" / f"{identity}.lease").resolve()


def _acquire_session_owner_lease(
    layout: CodingPluginLifecycleStateLayout,
    *,
    session_id: str,
    owner_id: str,
) -> _ProcessSessionOwnerLease:
    lease_path = _session_owner_lease_path(layout, session_id=session_id)
    normalized_owner_id = _nonempty(owner_id, name="Session owner id")
    with _PROCESS_SESSION_OWNER_LEASES_LOCK:
        existing = _PROCESS_SESSION_OWNER_LEASES.get(lease_path)
        if existing is not None:
            if existing.owner_id != normalized_owner_id:
                raise CodingPluginLifecycleError(
                    "Coding Session is already active in another runtime",
                    code="coding_plugin_session_already_active",
                )
            existing.references += 1
            return _ProcessSessionOwnerLease(
                path=lease_path,
                owner_id=normalized_owner_id,
                authority_id=existing.authority_id,
            )
        lease = journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        )
        try:
            lease.__enter__()
        except JournalLockUnavailable as exc:
            raise CodingPluginLifecycleError(
                "Coding Session is already active in another runtime",
                code="coding_plugin_session_already_active",
            ) from exc
        authority_id = secrets.token_hex(16)
        _PROCESS_SESSION_OWNER_LEASES[lease_path] = (
            _ProcessSessionOwnerLeaseState(
                owner_id=normalized_owner_id,
                authority_id=authority_id,
                lease=lease,
            )
        )
        return _ProcessSessionOwnerLease(
            path=lease_path,
            owner_id=normalized_owner_id,
            authority_id=authority_id,
        )


def _claim_session_owner_runtime(
    path: Path,
    *,
    owner_id: str,
    authority_id: str,
    claim_id: str,
) -> None:
    with _PROCESS_SESSION_OWNER_LEASES_LOCK:
        existing = _PROCESS_SESSION_OWNER_LEASES.get(path)
        if (
            existing is None
            or existing.owner_id != owner_id
            or existing.authority_id != authority_id
        ):
            raise RuntimeError("Coding Session owner lease ownership was lost")
        if existing.runtime_claim_id is None:
            existing.runtime_claim_id = claim_id
            existing.runtime_claim_references = 1
            return
        if existing.runtime_claim_id != claim_id:
            raise CodingPluginLifecycleError(
                "Coding Session already has another prepared runtime",
                code="coding_plugin_session_runtime_already_active",
            )
        existing.runtime_claim_references += 1


def _release_session_owner_lease(
    path: Path,
    *,
    owner_id: str,
    authority_id: str,
    runtime_claim_id: str | None,
) -> None:
    with _PROCESS_SESSION_OWNER_LEASES_LOCK:
        existing = _PROCESS_SESSION_OWNER_LEASES.get(path)
        if (
            existing is None
            or existing.owner_id != owner_id
            or existing.authority_id != authority_id
        ):
            raise RuntimeError("Coding Session owner lease ownership was lost")
        if runtime_claim_id is not None:
            if existing.runtime_claim_id != runtime_claim_id:
                raise RuntimeError("Coding Session runtime claim ownership was lost")
            existing.runtime_claim_references -= 1
            if existing.runtime_claim_references < 0:
                raise RuntimeError("Coding Session runtime claim count is invalid")
            if existing.runtime_claim_references == 0:
                existing.runtime_claim_id = None
        if existing.references > 1:
            existing.references -= 1
            return
        # Keep the process-local authority visible until the OS authority is
        # actually released. A replacement acquisition then waits on this
        # mutex instead of observing an empty registry and failing against the
        # still-held non-blocking file lock.
        try:
            existing.lease.__exit__(None, None, None)
        finally:
            # The journal lock context always closes its file handle on exit.
            # Never retain a ref-countable state after a reported unlock
            # failure because the cross-process authority is already gone.
            del _PROCESS_SESSION_OWNER_LEASES[path]


def _hold_process_startup_lease(
    layout: CodingPluginLifecycleStateLayout,
    *,
    startup_id: str,
) -> bool:
    lease_path = _startup_lease_path(layout, startup_id=startup_id)
    with _PROCESS_STARTUP_LEASES_LOCK:
        if lease_path in _PROCESS_STARTUP_LEASES:
            return False
        lease = journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        )
        try:
            lease.__enter__()
        except JournalLockUnavailable as exc:
            raise CodingPluginLifecycleError(
                "Coding Plugin startup id is active in another process",
                code="coding_plugin_startup_already_active",
            ) from exc
        _PROCESS_STARTUP_LEASES[lease_path] = lease
        return True


def _release_process_startup_lease(
    layout: CodingPluginLifecycleStateLayout,
    *,
    startup_id: str,
) -> None:
    lease_path = _startup_lease_path(layout, startup_id=startup_id)
    with _PROCESS_STARTUP_LEASES_LOCK:
        lease = _PROCESS_STARTUP_LEASES.pop(lease_path, None)
    if lease is not None:
        lease.__exit__(None, None, None)


def _startup_lease_is_inactive(
    layout: CodingPluginLifecycleStateLayout,
    *,
    startup_id: str,
) -> bool:
    lease_path = _startup_lease_path(layout, startup_id=startup_id)
    with _PROCESS_STARTUP_LEASES_LOCK:
        if lease_path in _PROCESS_STARTUP_LEASES:
            return False
    try:
        metadata = lease_path.lstat()
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_reparse_tag", 0))
            or (
                os.name == "posix"
                and callable(getuid)
                and metadata.st_uid != getuid()
            )
        ):
            raise OSError("startup lease is not a private regular file")
        with journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        ):
            return True
    except JournalLockUnavailable:
        return False
    except OSError as exc:
        raise CodingPluginLifecycleError(
            "Coding Plugin startup liveness evidence is invalid",
            code="coding_plugin_startup_evidence_invalid",
        ) from exc


def _prepare_private_state_layout(layout: CodingPluginLifecycleStateLayout) -> None:
    _prepare_private_tree(
        layout.root,
        private_base=layout.private_state_base,
        label="state",
    )
    _prepare_private_tree(
        layout.package_root,
        private_base=layout.private_data_base,
        label="data",
    )


def _prepare_private_tree(
    path: Path,
    *,
    private_base: Path,
    label: str,
) -> None:
    base = private_base.expanduser().absolute()
    root = path.expanduser().absolute()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise CodingPluginLifecycleError(
            f"Coding Plugin {label} root is outside its private base",
            code="coding_plugin_state_permissions_failed",
        ) from None
    current = base
    _prepare_private_directory(current)
    for part in relative.parts:
        current /= part
        _prepare_private_directory(current)


def _prepare_private_directory(root: Path) -> None:
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        before = root.lstat()
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or bool(getattr(before, "st_reparse_tag", 0))
        ):
            raise OSError("private root is not a direct directory")
        getuid = getattr(os, "getuid", None)
        if os.name == "posix" and callable(getuid) and before.st_uid != getuid():
            raise PermissionError("private root belongs to another user")
        if os.name == "posix":
            root.chmod(0o700)
        if not os.path.samestat(before, root.lstat()):
            raise OSError("private root identity changed")
    except OSError:
        raise CodingPluginLifecycleError(
            "Coding Plugin state root is not private",
            code="coding_plugin_state_permissions_failed",
        ) from None


def _nonempty(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be non-empty")
    return value


__all__ = [
    "CodingPluginLifecycle",
    "CodingPluginLifecycleError",
    "CodingPluginLifecycleStateLayout",
    "CodingPluginManagementChange",
    "CodingPluginSessionLease",
    "build_coding_plugin_lifecycle",
    "package_revision_ref",
    "resolve_coding_plugin_lifecycle_state_layout",
    "resolve_ephemeral_coding_plugin_lifecycle_state_layout",
]
