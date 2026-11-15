"""Ledger binding and policy-bound defaults; callers retain Product admission."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol

from loushang.harness.journal import JournalLoadPolicy, journal_file_lock
from loushang.harness.plugin_management.enablement_migration import (
    PluginEnablementMigrationJournal,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRetirementCompletionV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.package_records import PluginCleanupAttemptV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger,
    PluginRetirementIntentV1,
)
from loushang.harness.plugin_management.retirement_sets import PluginRetirementSetLedger
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService


@dataclass(frozen=True, slots=True)
class PluginManagementCoreBindings:
    gc_reservations: PluginPackageGcReservationJournal
    desired: PluginDesiredStateLedger
    intents: PluginRetirementIntentLedger
    retirement_sets: PluginRetirementSetLedger
    management: PluginManagementService
    migration_journal: PluginEnablementMigrationJournal
    load_policy: JournalLoadPolicy | None


@dataclass(frozen=True, slots=True)
class PluginRuntimeLedgerBindings:
    security: PluginInstanceSecurityRetirementJournal
    instances: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger


@dataclass(frozen=True, slots=True)
class PluginDesiredStateBindings:
    gc_reservations: PluginPackageGcReservationJournal
    desired: PluginDesiredStateLedger


def bind_plugin_desired_state(
    gc_path: str | Path,
    desired_state_path: str | Path,
    *,
    load_policy: JournalLoadPolicy | None,
) -> PluginDesiredStateBindings:
    """Bind Desired state to the GC gate that protects its references."""

    gate = PluginPackageGcReservationJournal(gc_path, load_policy=load_policy)
    desired = PluginDesiredStateLedger(
        desired_state_path, gc_gate=gate, load_policy=load_policy
    )
    return PluginDesiredStateBindings(gate, desired)


def bind_plugin_management_core(
    *,
    gc_reservations_path: str | Path,
    desired_state_path: str | Path,
    operation_journal_path: str | Path,
    retirement_intents_path: str | Path,
    retirement_sets_path: str | Path,
    migration_journal_path: str | Path,
    load_policy: JournalLoadPolicy | None = None,
) -> PluginManagementCoreBindings:
    desired_binding = bind_plugin_desired_state(
        gc_reservations_path, desired_state_path, load_policy=load_policy
    )
    intents = PluginRetirementIntentLedger(
        retirement_intents_path,
        load_policy=load_policy,
    )
    retirement_sets = PluginRetirementSetLedger(
        retirement_sets_path,
        retirement_intents=intents,
        load_policy=load_policy,
    )
    management = PluginManagementService(
        desired_state=desired_binding.desired,
        operation_journal_path=operation_journal_path,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
        load_policy=load_policy,
    )
    migration_journal = PluginEnablementMigrationJournal(
        migration_journal_path,
        load_policy=load_policy,
    )
    return PluginManagementCoreBindings(
        gc_reservations=desired_binding.gc_reservations,
        desired=desired_binding.desired,
        intents=intents,
        retirement_sets=retirement_sets,
        management=management,
        migration_journal=migration_journal,
        load_policy=load_policy,
    )


def bind_plugin_runtime_ledgers(
    core: PluginManagementCoreBindings,
    *,
    instance_runtime_path: str | Path,
    package_lifecycle_path: str | Path,
    startup_id: str,
    security_acceptances: PluginInstanceSecurityRetirementJournal | None = None,
) -> PluginRuntimeLedgerBindings:
    security = security_acceptances or (
        PluginInstanceSecurityRetirementJournal.for_instance_runtime(
            instance_runtime_path,
            load_policy=core.load_policy,
        )
    )
    instances = PluginInstanceRuntimeLedger(
        instance_runtime_path,
        management_operation_journal_path=core.management.operation_journal_path,
        desired_state=core.desired,
        retirement_intents=core.intents,
        retirement_sets=core.retirement_sets,
        security_acceptances=security,
        gc_gate=core.gc_reservations,
        load_policy=core.load_policy,
    )
    packages = PluginPackageLifecycleLedger(
        package_lifecycle_path,
        startup_id=startup_id,
        desired_state=core.desired,
        instance_runtime=instances,
        retirement_sets=core.retirement_sets,
        gc_gate=core.gc_reservations,
        load_policy=core.load_policy,
    )
    return PluginRuntimeLedgerBindings(
        security=security,
        instances=instances,
        packages=packages,
    )


@dataclass(frozen=True, slots=True)
class _SettledHostRetirementPolicy:
    """Product assertion that this direct-host route requires no further shutdown."""

    cleanup_kind: str
    handoff_namespace: str
    cleanup_reference_namespace: str
    attempt_namespace: str
    success_result_code: str
    outcome_namespace: str
    completion_namespace: str
    completion_reference_namespace: str
    family_release: Callable[
        [PluginInstanceLeaseFamilyV1], PluginInstanceLeaseFamilyReleaseV1
    ]


def _prepare_gc_writer_epoch(
    *,
    coordination_lock: Path,
    packages: PluginPackageLifecycleLedger,
    reservations: PluginPackageGcReservationJournal,
    desired: PluginDesiredStateLedger,
    instances: PluginInstanceRuntimeLedger,
    unavailable_error: Callable[[], RuntimeError],
) -> None:
    with journal_file_lock(coordination_lock, "exclusive"):
        if (
            not packages.gc_reservation_graph_bound_to(reservations)
            or reservations.snapshot().active
        ):
            raise unavailable_error()
        packages.gc_candidates()
        desired.seal_gc_writer_epoch()
        instances.seal_gc_writer_epoch()
        packages.seal_gc_writer_epoch()


def _gc_writer_epoch_ready(
    *,
    packages: PluginPackageLifecycleLedger,
    reservations: PluginPackageGcReservationJournal,
    desired: PluginDesiredStateLedger,
    instances: PluginInstanceRuntimeLedger,
) -> bool:
    return (
        packages.gc_reservation_graph_bound_to(reservations)
        and desired.gc_writer_epoch_sealed()
        and instances.gc_writer_epoch_sealed()
        and packages.gc_writer_epoch_sealed()
    )


def _complete_settled_host_retirement(
    intent: PluginRetirementIntentV1,
    *,
    retirement_sets: PluginRetirementSetLedger,
    instances: PluginInstanceRuntimeLedger,
    packages: PluginPackageLifecycleLedger,
    scope_id: str,
    policy: _SettledHostRetirementPolicy,
) -> None:
    retirement_set = retirement_sets.snapshot().retirement_set(intent.retirement_id)
    if retirement_set is None or retirement_set.state != "succeeded":
        return
    runtime = instances.snapshot()
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
    task = packages.handoff_cleanup_and_release(
        direct_family.family_id,
        retirement_target_id=None,
        cleanup_kind=policy.cleanup_kind,
        operation_id=f"{policy.handoff_namespace}:{identity}",
        idempotency_key=f"{policy.handoff_namespace}:{identity}",
        cleanup_reference=f"{policy.cleanup_reference_namespace}:{scope_id}",
        family_release=policy.family_release(direct_family),
    )
    packages.record_cleanup_attempt(
        PluginCleanupAttemptV1(
            cleanup_id=task.cleanup_id,
            operation_id=f"{policy.attempt_namespace}:{identity}",
            idempotency_key=f"{policy.attempt_namespace}:{identity}",
            attempt=1,
            disposition="succeeded",
            result_code=policy.success_result_code,
            retry_not_before_epoch_ms=None,
            outcome_reference=f"{policy.outcome_namespace}:{scope_id}",
        )
    )
    instances.complete_retirement(
        PluginInstanceRetirementCompletionV1.create(
            completion_kind="graceful",
            coordination_id=intent.retirement_id,
            installation_key=instance.installation_key,
            instance_revision_ref=instance.instance_revision_ref,
            operation_id=f"{policy.completion_namespace}:{identity}",
            idempotency_key=f"{policy.completion_namespace}:{identity}",
            completion_reference=f"{policy.completion_reference_namespace}:{scope_id}",
        )
    )


@dataclass(frozen=True, slots=True)
class _FirstPartyDefaultPolicy:
    product_id: str
    product_label: str
    actor_id: str
    policy_revision: str
    approval_reference: str
    operation_id_prefix: str
    error_code_prefix: str
    make_error: Callable[[str, str], Exception]


class _FirstPartyBootstrapScope(Protocol):
    @property
    def scope_id(self) -> str: ...


class _FirstPartyDefaultBootstrap:
    """Resume only this Product's own default install through existing commands."""

    __slots__ = ()
    layout: _FirstPartyBootstrapScope
    desired: PluginDesiredStateLedger
    management: PluginManagementService
    _first_party_default_policy: ClassVar[_FirstPartyDefaultPolicy]

    def bootstrap_first_party_default(
        self,
        key: PluginInstallationKeyV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> None:
        """Install+enable only a truly unseen first-party Installation.

        An absent record retained after remove is deliberately *seen* and is
        therefore never resurrected by Product composition.
        """

        policy = self._first_party_default_policy
        if (
            not isinstance(key, PluginInstallationKeyV1)
            or key.product_id != policy.product_id
            or key.installation_scope != "workspace"
            or key.scope_id != self.layout.scope_id
        ):
            raise policy.make_error(
                f"First-party default Installation is outside this {policy.product_label} scope",
                f"{policy.error_code_prefix}_default_bootstrap_scope_mismatch",
            )
        if (
            not isinstance(package_revision, PluginPackageRevisionRefV1)
            or package_revision.plugin_id != key.plugin_id
        ):
            raise policy.make_error(
                "First-party default Package Revision changed Plugin identity",
                f"{policy.error_code_prefix}_default_bootstrap_revision_mismatch",
            )
        # The two management commands are individually durable.  This loop is
        # the Product transaction coordinator: it resumes only its own exact
        # default install, stops at any operator-authored state, and retries a
        # CAS race with a fresh operation identity.
        for _attempt in range(32):
            snapshot = self.desired.snapshot()
            state = snapshot.installation(key)
            seen = any(item.installation_key == key for item in snapshot.installations)
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
                    raise policy.make_error(
                        "First-party Plugin bootstrap install failed",
                        error,
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
                raise policy.make_error(
                    "First-party Plugin bootstrap enable failed",
                    error,
                )
            return
        raise policy.make_error(
            "First-party Plugin bootstrap could not linearize",
            f"{policy.error_code_prefix}_default_bootstrap_busy",
        )

    def _is_own_default_install(
        self,
        key: PluginInstallationKeyV1,
        *,
        package_revision: PluginPackageRevisionRefV1,
    ) -> bool:
        policy = self._first_party_default_policy
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
            and mutation.actor_id == policy.actor_id
            and mutation.policy_revision == policy.policy_revision
            and mutation.approval_reference == policy.approval_reference
        )

    def _submit_default(
        self,
        key: PluginInstallationKeyV1,
        *,
        action: Literal["install", "enable"],
        desired_state: Literal["installed_disabled", "installed_enabled"],
        package_revision: PluginPackageRevisionRefV1 | None,
        expected_inventory_revision: int,
    ) -> str | None:
        policy = self._first_party_default_policy
        identity = hashlib.sha256(
            repr((key, action, package_revision, expected_inventory_revision)).encode(
                "utf-8"
            )
        ).hexdigest()
        event = self.management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=f"{policy.operation_id_prefix}{identity}",
                    idempotency_key=f"{policy.operation_id_prefix}{identity}",
                    expected_inventory_revision=expected_inventory_revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=package_revision,
                    actor_id=policy.actor_id,
                    policy_revision=policy.policy_revision,
                    approval_reference=policy.approval_reference,
                ),
            )
        )
        result = getattr(event, "result", None)
        if result is None:
            return f"{policy.error_code_prefix}_default_management_failed"
        if result.disposition != "succeeded":
            return (
                result.error_code
                or f"{policy.error_code_prefix}_default_management_failed"
            )
        return None
