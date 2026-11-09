"""Coding Product adapter for the common durable Plugin lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_owner_generations import (
    CodingOwnerGenerationEvidenceEventV1,
    CodingOwnerGenerationEvidenceLedger,
    CodingOwnerGenerationFamilyEvidence,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.journal import (
    JournalLoadPolicy,
)
from loushang.harness.journal import (
    journal_file_lock_at as journal_file_lock_at,
)
from loushang.harness.journal import (
    read_journal_file_at as read_journal_file_at,
)
from loushang.harness.package_product import _legacy_runtime
from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginEnablementCompatibilityProjectionV1,
    PluginEnablementMigrationCoordinator,
    PluginEnablementMigrationRequestV1,
    PluginEnablementMigrationSnapshotV1,
    PluginInstallationKeyV1,
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRuntimeLedger,
    PluginManagementApplicationPorts,
    PluginManagementCommandApplication,
    PluginManagementCommandV1,
    PluginManagementReadModelProjector,
    PluginManagementService,
    PluginPackageLifecycleLedger,
    PluginPackageRevisionRefV1,
    PluginRetirementSetLedger,
    PluginSourceProjectionSourcePort,
    _enablement_capture,
    decode_plugin_desired_state_snapshot,
    decode_plugin_enablement_migration_snapshots,
)
from loushang.harness.plugin_management.assembly import (
    _gc_writer_epoch_ready,
    _prepare_gc_writer_epoch,
    _SettledHostRetirementPolicy,
    bind_plugin_management_core,
    bind_plugin_runtime_ledgers,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.resources.packages import _private_directory as _private_state_io
from loushang.harness.resources.plugins import PluginInstanceRevisionRef
from loushang.harness.session._plugin_retirement import (
    OwnerRetirementReportPolicy,
    OwnerRetirementUnavailableReason,
)
from loushang.harness.session.plugin_lifecycle import _owner_lease
from loushang.harness.session.plugin_lifecycle._membership import (
    _MembershipPolicy,
    _PluginSessionLifecycle,
)
from loushang.harness.session.plugin_lifecycle._session_lease import _PluginSessionLease

_PRODUCT_POLICY_REVISION = "coding-plugin-lifecycle-v1"
_DEFAULT_APPROVAL_REFERENCE = "coding-first-party-default"
_CODING_PLUGIN_RUNTIME_BOOT_ID = secrets.token_hex(16)


class CodingPluginLifecycleError(RuntimeError):
    """Stable Product failure at the common management boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _lifecycle_error(message: str, code: str) -> CodingPluginLifecycleError:
    return CodingPluginLifecycleError(message, code=code)


_STARTUP_POLICY = _legacy_runtime._LegacyStartupPolicy(
    product_label="Coding",
    error_code_prefix="coding_plugin",
    make_error=_lifecycle_error,
    registration_identity=lambda startup_id: (
        "coding:" + hashlib.sha256(startup_id.encode("utf-8")).hexdigest()
    ),
)


class _ProcessSessionOwnerLease(_owner_lease._SessionOwnerLease):
    __slots__ = ()
    _policy = _owner_lease._OwnerLeasePolicy(
        product_label="Coding",
        error_code_prefix="coding_plugin",
        make_error=_lifecycle_error,
        normalize_identifier=lambda value, name: _nonempty(value, name=name),
    )


_PROCESS_STARTUP_LEASES_LOCK = _legacy_runtime._PROCESS_STARTUP_LEASES_LOCK
_PROCESS_STARTUP_LEASES = _legacy_runtime._PROCESS_STARTUP_LEASES
_PROCESS_SESSION_OWNER_LEASES_LOCK = _owner_lease._PROCESS_SESSION_OWNER_LEASES_LOCK
_PROCESS_SESSION_OWNER_LEASES = _owner_lease._PROCESS_SESSION_OWNER_LEASES


def _hold_process_startup_lease(
    layout: CodingPluginLifecycleStateLayout, *, startup_id: str
) -> bool:
    def resolve_epoch() -> _legacy_runtime._LegacyEpoch:
        from loushang.coding.package_epoch_layout import (
            resolve_coding_package_epoch_layout,
        )

        return resolve_coding_package_epoch_layout(layout)

    return _legacy_runtime._hold_process_startup_lease(
        layout,
        startup_id=startup_id,
        lease_path=_startup_lease_path(layout, startup_id=startup_id),
        resolve_epoch=resolve_epoch,
        policy=_STARTUP_POLICY,
    )


def _release_process_startup_lease(
    layout: CodingPluginLifecycleStateLayout, *, startup_id: str
) -> None:
    _legacy_runtime._release_process_startup_lease(
        _startup_lease_path(layout, startup_id=startup_id)
    )


def _prepare_private_state_layout(layout: CodingPluginLifecycleStateLayout) -> None:
    _legacy_runtime.prepare_private_state_layout(layout, policy=_STARTUP_POLICY)


def _prepare_private_tree(path: Path, *, private_base: Path, label: str) -> None:
    _legacy_runtime._prepare_tree(
        path,
        private_base=private_base,
        label=label,
        policy=_STARTUP_POLICY,
    )


def _owner_retirement_unavailable_error(
    reason: OwnerRetirementUnavailableReason,
) -> CodingPluginLifecycleError:
    message, code = {
        "set_unavailable": (
            "Coding retirement set is unavailable",
            "coding_plugin_retirement_set_unavailable",
        ),
        "plan_unavailable": (
            "Coding owner retirement plan was not committed",
            "coding_plugin_owner_retirement_plan_unavailable",
        ),
        "outcome_unavailable": (
            "Coding owner retirement lacks an exact cleanup outcome",
            "coding_plugin_owner_retirement_outcome_unavailable",
        ),
    }[reason]
    return CodingPluginLifecycleError(message, code=code)


_CODING_OWNER_RETIREMENT_REPORT_POLICY = OwnerRetirementReportPolicy(
    closure_namespace="coding-owner-closure",
    outcome_namespace="coding-owner-retired",
    success_result_code="coding.owner.exact_retired",
    unavailable_error=_owner_retirement_unavailable_error,
)


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
    def enablement_migration(self) -> Path:
        return self.root / "enablement-migration.jsonl"

    @property
    def coordination_lock(self) -> Path:
        return self.root / "lifecycle-coordination"

    @property
    def package_gc_reservations(self) -> Path:
        return self.root / "package-gc-reservations.jsonl"


@dataclass(frozen=True, slots=True)
class _CodingPluginEnablementStateCapture:
    desired_raw: str
    migration_raw: str


_SESSION_HOLDER_PREFIX = "coding-session-owner-family:v2:"


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


def _coding_membership_policy() -> _MembershipPolicy[CodingPluginLifecycleStateLayout]:
    return _MembershipPolicy(
        product_label="Coding",
        identity_prefix="coding",
        error_code_prefix="coding_plugin",
        make_error=_lifecycle_error,
        family_release=_family_release,
        orphan_release=lambda family, startup: _orphan_family_release(
            family, inactive_startup_id=startup
        ),
        activation_identity=_activation_identity,
        lease_identity=_lease_identity,
        normalize_owners=_normalize_owner_contributions,
        holder_reference=lambda session, attempt, owners, startup: (
            _session_holder_reference(
                session_id=session,
                lease_attempt_id=attempt,
                owner_contributions=owners,
                startup_id=startup,
            )
        ),
        holder_evidence=_session_holder_evidence,
        startup_path=lambda layout, startup: _startup_lease_path(
            layout, startup_id=startup
        ),
        owner_path=lambda layout, session: _session_owner_lease_path(
            layout, session_id=session
        ),
        startup_policy=_STARTUP_POLICY,
        retirement_policy=_CODING_OWNER_RETIREMENT_REPORT_POLICY,
    )


@dataclass(slots=True)
class CodingPluginLifecycle(
    _PluginSessionLifecycle[
        CodingPluginLifecycleStateLayout,
        CodingOwnerGenerationEvidenceEventV1,
        CodingOwnerGenerationFamilyEvidence,
        _ProcessSessionOwnerLease,
    ]
):
    """Installed common Harness authorities bound to Coding Product policy."""

    layout: CodingPluginLifecycleStateLayout
    startup_id: str
    desired: PluginDesiredStateLedger = field(repr=False)
    management: PluginManagementService = field(repr=False)
    enablement_migrations: PluginEnablementMigrationCoordinator = field(repr=False)
    instances: PluginInstanceRuntimeLedger = field(repr=False)
    retirement_sets: PluginRetirementSetLedger = field(repr=False)
    packages: PluginPackageLifecycleLedger = field(repr=False)
    _gc_reservations: PluginPackageGcReservationJournal = field(repr=False)
    security: PluginInstanceSecurityRetirementJournal = field(repr=False)
    owner_evidence: CodingOwnerGenerationEvidenceLedger = field(repr=False)
    _owns_process_startup_lease: bool = field(repr=False)

    _owner_lease_type = _ProcessSessionOwnerLease
    _membership_policy = _coding_membership_policy()
    _settled_host_policy = _SettledHostRetirementPolicy(
        cleanup_kind="coding.product_host.shutdown",
        handoff_namespace="coding-host-cleanup",
        cleanup_reference_namespace="coding-host",
        attempt_namespace="coding-host-cleaned",
        success_result_code="coding.host.retired",
        outcome_namespace="coding-host-outcome",
        completion_namespace="coding-instance-retired",
        completion_reference_namespace="coding-instance",
        family_release=_family_release,
    )

    def prepare_gc_writer_epoch(self) -> None:
        _prepare_gc_writer_epoch(
            coordination_lock=self.layout.coordination_lock,
            packages=self.packages,
            reservations=self._gc_reservations,
            desired=self.desired,
            instances=self.instances,
            unavailable_error=lambda: CodingPluginLifecycleError(
                "Coding Plugin GC writer graph is not quiescent and bound",
                code="coding_plugin_gc_writer_epoch_unavailable",
            ),
        )

    def gc_writer_epoch_ready(self) -> bool:
        return _gc_writer_epoch_ready(
            packages=self.packages,
            reservations=self._gc_reservations,
            desired=self.desired,
            instances=self.instances,
        )

    def installation_key(self, plugin_id: str) -> PluginInstallationKeyV1:
        return PluginInstallationKeyV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=_nonempty(plugin_id, name="Plugin id"),
        )

    def migrate_legacy_enablement(
        self,
        key: PluginInstallationKeyV1,
        package_revision: PluginPackageRevisionRefV1 | None,
        *,
        legacy_disabled: bool,
        manifest_enabled_default: bool,
        legacy_input_fingerprint: str,
    ) -> PluginEnablementMigrationSnapshotV1:
        """Import an immutable legacy snapshot once through canonical commands."""

        if (
            key.product_id != CODING_PRODUCT_ID
            or key.installation_scope != "workspace"
            or key.scope_id != self.layout.scope_id
        ):
            raise CodingPluginLifecycleError(
                "Enablement migration Installation is outside this Coding scope",
                code="coding_plugin_enablement_migration_scope_mismatch",
            )
        return self.enablement_migrations.migrate(
            PluginEnablementMigrationRequestV1(
                installation_key=key,
                package_revision=package_revision,
                legacy_disabled=legacy_disabled,
                manifest_enabled_default=manifest_enabled_default,
                legacy_input_fingerprint=legacy_input_fingerprint,
            )
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

        if (
            not isinstance(key, PluginInstallationKeyV1)
            or key.product_id != CODING_PRODUCT_ID
            or key.installation_scope != "workspace"
            or key.scope_id != self.layout.scope_id
        ):
            raise CodingPluginLifecycleError(
                "First-party default Installation is outside this Coding scope",
                code="coding_plugin_default_bootstrap_scope_mismatch",
            )
        if (
            not isinstance(package_revision, PluginPackageRevisionRefV1)
            or package_revision.plugin_id != key.plugin_id
        ):
            raise CodingPluginLifecycleError(
                "First-party default Package Revision changed Plugin identity",
                code="coding_plugin_default_bootstrap_revision_mismatch",
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

    def acquire_session(
        self,
        key: PluginInstallationKeyV1,
        *,
        session_id: str,
        lease_attempt_id: str,
        owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
        session_owner_id: str | None = None,
    ) -> CodingPluginSessionLease:
        with self._acquire_session_family(
            key,
            session_id=session_id,
            lease_attempt_id=lease_attempt_id,
            owner_contributions=owner_contributions,
            session_owner_id=session_owner_id,
        ) as (family, owners, owner_lease):
            [member] = family.members
            return CodingPluginSessionLease(
                lifecycle=self,
                installation_key=key,
                family=family,
                package_revision=member.package_revision,
                instance_revision_ref=member.instance_revision_ref,
                owner_contributions=owners,
                _session_owner_lease=owner_lease,
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
        identity = hashlib.sha256(
            repr((key, action, package_revision, expected_inventory_revision)).encode(
                "utf-8"
            )
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
class CodingPluginSessionLease(
    _PluginSessionLease[
        CodingPluginLifecycleStateLayout,
        CodingOwnerGenerationEvidenceEventV1,
        CodingOwnerGenerationFamilyEvidence,
        _ProcessSessionOwnerLease,
    ]
):
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

    _membership_policy = CodingPluginLifecycle._membership_policy

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
    resolved_startup_id = startup_id or _CODING_PLUGIN_RUNTIME_BOOT_ID
    owns_process_startup_lease = _hold_process_startup_lease(
        layout,
        startup_id=resolved_startup_id,
    )
    try:
        if not owns_process_startup_lease:
            _prepare_private_state_layout(layout)
        core = bind_plugin_management_core(
            gc_reservations_path=layout.package_gc_reservations,
            desired_state_path=layout.desired_state,
            operation_journal_path=layout.management_operations,
            retirement_intents_path=layout.retirement_intents,
            retirement_sets_path=layout.retirement_sets,
            migration_journal_path=layout.enablement_migration,
        )
        gc_reservations = core.gc_reservations
        desired = core.desired
        retirement_sets = core.retirement_sets
        management = core.management
        enablement_journal = core.migration_journal
        enablement_journal.assert_runtime_compatible(
            supported_migration_epoch=1,
            runtime_version=version("loushang"),
        )
        management.recover()
        enablement_migrations = PluginEnablementMigrationCoordinator(
            journal=enablement_journal,
            desired_state=desired,
            commands=PluginManagementCommandApplication(management),
            runtime_version=version("loushang"),
        )
        runtime = bind_plugin_runtime_ledgers(
            core,
            instance_runtime_path=layout.instance_runtime,
            package_lifecycle_path=layout.package_lifecycle,
            startup_id=resolved_startup_id,
            security_acceptances=security_acceptances,
        )
        security = runtime.security
        instances = runtime.instances
        packages = runtime.packages
        owner_evidence = CodingOwnerGenerationEvidenceLedger(
            layout.owner_generation_evidence
        )
        return CodingPluginLifecycle(
            layout=layout,
            startup_id=resolved_startup_id,
            desired=desired,
            management=management,
            enablement_migrations=enablement_migrations,
            instances=instances,
            retirement_sets=retirement_sets,
            packages=packages,
            _gc_reservations=gc_reservations,
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


def build_coding_plugin_management_application(
    layout: CodingPluginLifecycleStateLayout,
    *,
    source: PluginSourceProjectionSourcePort | None = None,
    read_only: bool = False,
) -> PluginManagementApplicationPorts:
    """Compose command/query ports without acquiring a Product runtime lease."""

    if not isinstance(layout, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    owns_process_startup_lease = (
        not read_only
        and (sys.platform.startswith("linux") or os.name == "nt")
        and _hold_process_startup_lease(
            layout,
            startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID,
        )
    )
    try:
        if not read_only and not owns_process_startup_lease:
            _prepare_private_state_layout(layout)
        load_policy = (
            JournalLoadPolicy(partial_tail="raise", create_lock=False)
            if read_only
            else None
        )
        core = bind_plugin_management_core(
            gc_reservations_path=layout.package_gc_reservations,
            desired_state_path=layout.desired_state,
            operation_journal_path=layout.management_operations,
            retirement_intents_path=layout.retirement_intents,
            retirement_sets_path=layout.retirement_sets,
            migration_journal_path=layout.enablement_migration,
            load_policy=load_policy,
        )
        desired = core.desired
        retirement_sets = core.retirement_sets
        management = core.management
        migrations = core.migration_journal
        migrations.assert_runtime_compatible(
            supported_migration_epoch=1,
            runtime_version=version("loushang"),
        )
        if not read_only:
            management.recover()
        runtime = bind_plugin_runtime_ledgers(
            core,
            instance_runtime_path=layout.instance_runtime,
            package_lifecycle_path=layout.package_lifecycle,
            startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID,
        )
        instances = runtime.instances
        packages = runtime.packages
        return PluginManagementApplicationPorts(
            commands=PluginManagementCommandApplication(management),
            queries=PluginManagementReadModelProjector(
                desired_state=desired,
                operations=management,
                migrations=migrations,
                source=source,
                instances=instances,
                packages=packages,
                retirement=retirement_sets,
            ),
        )
    except BaseException:
        if owns_process_startup_lease:
            _release_process_startup_lease(
                layout, startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID
            )
        raise


def project_coding_plugin_enablement_compatibility(
    layout: CodingPluginLifecycleStateLayout,
    *,
    _capture: _CodingPluginEnablementStateCapture | None = None,
) -> tuple[PluginEnablementCompatibilityProjectionV1, frozenset[str]]:
    """Read Coding's derived downgrade view without exposing owner stores."""

    if not isinstance(layout, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if _capture is None:
        with _capture_existing_plugin_enablement_state(layout) as captured:
            if captured is None:
                return _empty_plugin_enablement_compatibility_projection()
            return project_coding_plugin_enablement_compatibility(
                layout,
                _capture=captured,
            )
    desired = decode_plugin_desired_state_snapshot(
        _capture.desired_raw,
        path=layout.desired_state,
        gc_gate=PluginPackageGcReservationJournal(layout.package_gc_reservations),
    )
    migrations = tuple(
        item
        for item in decode_plugin_enablement_migration_snapshots(
            _capture.migration_raw,
            path=layout.enablement_migration,
        )
        if item.request.installation_key.product_id == CODING_PRODUCT_ID
        and item.request.installation_key.installation_scope == "workspace"
        and item.request.installation_key.scope_id == layout.scope_id
        and item.phase in {"compatibility_window", "finalized"}
    )
    migrated = frozenset(item.request.installation_key.plugin_id for item in migrations)
    disabled = tuple(
        sorted(
            item.request.installation_key.plugin_id
            for item in migrations
            if desired.installation(
                item.request.installation_key
            ).selection.desired_state
            != "installed_enabled"
        )
    )
    projection = PluginEnablementCompatibilityProjectionV1(
        desired_inventory_revision=desired.inventory_revision,
        migration_journal_revision=max(
            (item.journal_revision for item in migrations),
            default=0,
        ),
        disabled_plugin_ids=disabled,
    )
    return projection, migrated


def _empty_plugin_enablement_compatibility_projection() -> tuple[
    PluginEnablementCompatibilityProjectionV1, frozenset[str]
]:
    return (
        PluginEnablementCompatibilityProjectionV1(
            desired_inventory_revision=0,
            migration_journal_revision=0,
            disabled_plugin_ids=(),
        ),
        frozenset(),
    )


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


@contextmanager
def _capture_existing_plugin_enablement_state(
    layout: CodingPluginLifecycleStateLayout,
) -> Iterator[_CodingPluginEnablementStateCapture | None]:
    with _enablement_capture._capture_existing_plugin_enablement_state(
        layout,
        error_factory=_private_state_read_error,
        capture_factory=_CodingPluginEnablementStateCapture,
    ) as captured:
        yield captured


def _nonempty(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be non-empty")
    return value


__all__ = [
    "build_coding_plugin_management_application",
    "CodingPluginLifecycle",
    "CodingPluginLifecycleError",
    "CodingPluginLifecycleStateLayout",
    "CodingPluginManagementChange",
    "CodingPluginSessionLease",
    "build_coding_plugin_lifecycle",
    "package_revision_ref",
    "project_coding_plugin_enablement_compatibility",
    "resolve_coding_plugin_lifecycle_state_layout",
    "resolve_ephemeral_coding_plugin_lifecycle_state_layout",
]


def _private_state_read_error(
    reason: _private_state_io._PrivateStateErrorReason,
) -> CodingPluginLifecycleError:
    message = {
        "outside_base": "Coding Plugin state root is outside its private base",
        "not_private": "Coding Plugin state root is not private",
        "journal_not_private": "Coding Plugin state journal is not private",
        "handles_unavailable": "Secure Coding Plugin state handles are unavailable",
    }[reason]
    return CodingPluginLifecycleError(
        message, code="coding_plugin_state_permissions_failed"
    )
