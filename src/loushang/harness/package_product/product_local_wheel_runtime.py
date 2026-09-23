"""Explicit POSIX Product composition for pinned local Wheel transactions.

The Product supplies its existing management and GC authorities, an already
fenced Store root, and a live runtime lease. This module creates Package-local
journals and owner adapters but never publishes an epoch or switches a root.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import cast

from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    CommittedSetPackageRevisionProjection,
    PluginManagementCommandSubmitPort,
    PluginManagementPackageDesiredStateAdapter,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    PackageClosureBudgetV1,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageRecursiveClosureOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitAdmissionOwner,
    PackageCommitLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeAdmissionResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PosixPackageDependencyMaterializationStore,
    PosixPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.product_retention import (
    PackageProductRetentionSettlementOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pin_runtime import (
    PackageTransactionPinLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_retention import (
    PackageJournaledTransactionRetentionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
)
from loushang.harness.resources.packages.product_composition import (
    PackageCommittedProductHandoffRecovery,
    PackageRetentionHandoffRecovery,
    compose_package_product_lifecycle,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductFileEpochTransactionGuard,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffFinalizer,
)
from loushang.harness.resources.packages.product_local_wheel_inventory import (
    PackageProductLocalWheelInventory,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.packages.product_root_target import (
    PackageProductRootTargetAuthority,
)
from loushang.harness.resources.packages.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.resources.packages.product_transaction import (
    PackageProductLifecycleTransaction,
    PackageProductWheelExecutionFactory,
)


class _PosixStoreRootAdmission(PackageEpochRuntimeAdmissionOwner):
    """Reject a moved Product root before admission reaches Source or journals."""

    def __init__(
        self, *, registry: PackageEpochRuntimeLeaseRegistry, root: Path
    ) -> None:
        super().__init__(fences=registry.fences, leases=registry)
        self._root = root

    def admit(
        self, request: PackageEpochRuntimeAdmissionRequestV1
    ) -> PackageEpochRuntimeAdmissionResultV1:
        if _directory_identity(self._root) != request.store_root_identity:
            return self._reject_root(request)
        result = super().admit(request)
        if result.disposition == "admitted" and (
            _directory_identity(self._root) != request.store_root_identity
        ):
            return self._reject_root(request)
        return result

    @staticmethod
    def _reject_root(
        request: PackageEpochRuntimeAdmissionRequestV1,
    ) -> PackageEpochRuntimeAdmissionResultV1:
        return PackageEpochRuntimeAdmissionResultV1.rejected(
            request,
            evidence_ref=request.fence_id,
            operator_action="offline_restore",
        )


def compose_posix_local_wheel_product(
    *,
    state_root: Path,
    plugin_store_root: Path,
    policy: PackageProductLocalWheelPolicy,
    environment: PackageResolutionEnvironmentV1,
    acquisition_budgets: PackageAcquisitionBudgetV1,
    inspection_budgets: PackageInspectionBudgetV1,
    closure_budgets: PackageClosureBudgetV1,
    root_store_identity: str,
    dependency_store_identity: str,
    registry: PackageEpochRuntimeLeaseRegistry,
    admission_request: PackageEpochRuntimeAdmissionRequestV1,
    management: PluginManagementService,
    desired_state: PluginDesiredStateLedger,
    gc_bindings: PluginPackageGcBindingJournal,
    gc_gate: PluginPackageGcReservationJournal,
    actor_id: str,
    desired_policy_revision: str,
    recovery_identity: str,
) -> PackageProductRuntimeBindingV1:
    """Bind the exact Product transaction and inventory before activation."""

    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC")
    ):
        raise RuntimeError("POSIX rooted Package Store is required")
    for value, expected, name in (
        (policy, PackageProductLocalWheelPolicy, "Product Wheel policy"),
        (environment, PackageResolutionEnvironmentV1, "resolution environment"),
        (acquisition_budgets, PackageAcquisitionBudgetV1, "acquisition budgets"),
        (inspection_budgets, PackageInspectionBudgetV1, "inspection budgets"),
        (closure_budgets, PackageClosureBudgetV1, "closure budgets"),
        (registry, PackageEpochRuntimeLeaseRegistry, "runtime lease registry"),
        (admission_request, PackageEpochRuntimeAdmissionRequestV1, "runtime admission"),
        (management, PluginManagementService, "Product management owner"),
        (desired_state, PluginDesiredStateLedger, "Product desired-state owner"),
        (gc_bindings, PluginPackageGcBindingJournal, "Product GC bindings"),
        (gc_gate, PluginPackageGcReservationJournal, "Product GC gate"),
    ):
        if not isinstance(value, expected):
            raise TypeError(f"{name} is required")
    for identifier, name in (
        (root_store_identity, "root Store identity"),
        (dependency_store_identity, "dependency Store identity"),
        (actor_id, "Product actor identity"),
        (desired_policy_revision, "Product desired policy revision"),
        (recovery_identity, "Package recovery identity"),
    ):
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{name} is required")
    _require_private_directory(state_root)
    if (
        not isinstance(plugin_store_root, Path)
        or not plugin_store_root.is_absolute()
        or ".." in plugin_store_root.parts
        or state_root == plugin_store_root
        or state_root.is_relative_to(plugin_store_root)
        or plugin_store_root.is_relative_to(state_root)
    ):
        raise ValueError("Package state and fenced Store roots must be distinct")
    current_fence = registry.fences.current(registry.store_id)
    if (
        environment.fingerprint != policy.resolution_environment_fingerprint
        or registry.store_id != admission_request.store_id
        or current_fence is None
        or current_fence.fence_id != admission_request.fence_id
        or _directory_identity(plugin_store_root)
        != admission_request.store_root_identity
        or desired_state.gc_gate is not gc_gate
        or management.gc_gate is not gc_gate
        or getattr(management, "_desired_state", None) is not desired_state
    ):
        raise ValueError("Package Product owner, epoch, or Store identity changed")

    dependency_root = state_root / "dependency-store"
    dependency_root.mkdir(mode=0o700, exist_ok=True)
    _require_private_directory(dependency_root)
    lifecycle_journal = PackageLifecycleJournal(state_root / "lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=policy,
        enabled=True,
    )
    quarantine = PackageQuarantineStore(state_root / "quarantine")
    evidence_journal = PackageArtifactEvidenceJournal(
        state_root / "artifact-evidence.jsonl"
    )
    cleanup = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(state_root / "cleanup.jsonl"),
        store=quarantine,
    )
    acquisition = PackageAcquisitionOwner(
        source_authority=policy.source_authority(),
        quarantine_store=quarantine,
    )
    wheel_verifier = PackageWheelVerifier()
    artifact = PackageArtifactLifecycleOwner(
        kernel=kernel,
        classification_recheck=policy,
        acquisition_owner=acquisition,
        evidence_journal=evidence_journal,
        cleanup_owner=cleanup,
        wheel_verifier=wheel_verifier,
        acquisition_budgets=acquisition_budgets,
        inspection_budgets=inspection_budgets,
        supported_tags=frozenset(environment.supported_tags),
    )
    resolution_journal = PackageClosureResolutionJournal(
        state_root / "resolution.jsonl"
    )
    recursive = PackageRecursiveClosureOwner(
        resolver=policy,
        acquisition_owner=acquisition,
        evidence_journal=evidence_journal,
        wheel_verifier=wheel_verifier,
        closure_verifier=PackageClosureVerifier(),
        acquisition_budgets=acquisition_budgets,
        inspection_budgets=inspection_budgets,
        cleanup_owner=cleanup,
        selection_journal=resolution_journal,
    )
    closure = PackageClosureLifecycleOwner(
        kernel=kernel,
        artifact_owner=artifact,
        closure_builder=recursive,
        resolution_journal=resolution_journal,
    )
    pin_journal = PackageTransactionPinJournal(state_root / "transaction-pins.jsonl")
    pins = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=resolution_journal,
        retention=PackageJournaledTransactionRetentionOwner(journal=pin_journal),
        pin_journal=pin_journal,
    )
    committed_sets = PackageCommittedSetJournal(state_root / "committed-sets.jsonl")
    staging = PackageStagingSetLifecycleOwner(
        kernel=kernel,
        classification_recheck=policy,
        closure_plans=resolution_journal,
        pin_journal=pin_journal,
        root_targets=PackageProductRootTargetAuthority(
            product_id=policy.product_id,
            installation_scope="workspace",
            authority_id=policy.authority_id,
            authority_revision=policy.authority_revision,
        ),
        dependency_staging=PosixPackageDependencyMaterializationStore(
            dependency_root,
            store_identity=dependency_store_identity,
            settlement_journal=PackageStoreSettlementJournal(
                state_root / "dependency-settlements.jsonl"
            ),
        ),
        root_staging=PosixPackagePluginRootMaterializationStore(
            plugin_store_root,
            store_identity=root_store_identity,
            package_store_id=registry.store_id,
            settlement_journal=PackageStoreSettlementJournal(
                state_root / "root-settlements.jsonl"
            ),
        ),
        staging_journal=PackageArtifactStagingJournal(state_root / "staging.jsonl"),
        committed_sets=committed_sets,
    )
    commit = PackageCommitLifecycleOwner(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    )
    admission = PackageCommitAdmissionOwner(
        lifecycle_journal=lifecycle_journal,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    )
    projection = CommittedSetPackageRevisionProjection(desired_state, committed_sets)
    handoff_journal = PackageRetentionHandoffJournal(state_root / "handoff.jsonl")
    handoff = PackageRetentionHandoffOwner(
        journal=handoff_journal,
        admission=admission,
        retention=PackageProductRetentionSettlementOwner(
            path=state_root / "product-retention.jsonl",
            transaction_pins=pin_journal,
        ),
        desired_state=PluginManagementPackageDesiredStateAdapter(
            # The concrete service also supports update commands, so its
            # return annotation is wider than this install-only Port.
            management=cast(PluginManagementCommandSubmitPort, management),
            revisions=projection,
            installation_scope="workspace",
            actor_id=actor_id,
            policy_revision=desired_policy_revision,
            gc_bindings=gc_bindings,
            gc_gate=gc_gate,
        ),
    )
    finalizer = PackageProductHandoffFinalizer(
        kernel=kernel,
        commit=commit,
        admission=admission,
        transaction_pins=pin_journal,
        journal=handoff_journal,
        handoff=handoff,
        inventory_revision=projection.inventory_revision,
    )
    transaction = PackageProductLifecycleTransaction(
        kernel=kernel,
        execution=PackageProductWheelExecutionFactory(
            environment=environment,
            budgets=closure_budgets,
        ),
        recovery_identity=recovery_identity,
        closure=closure,
        pins=pins,
        staging=staging,
        commit=commit,
        handoff=finalizer,
    )
    lifecycle = compose_package_product_lifecycle(
        product_id=policy.product_id,
        owner=kernel,
        transaction=transaction,
        ingress_factory=policy,
        runtime_admission=_PosixStoreRootAdmission(
            registry=registry,
            root=plugin_store_root,
        ),
        admission_request=admission_request,
        transaction_guard=PackageProductFileEpochTransactionGuard(
            store_id=registry.store_id,
            coordination_lock=registry.coordination_lock,
            file_io=registry._io,
        ),
        recoveries=(PackageRetentionHandoffRecovery(handoff_journal, handoff),),
        admitted_recoveries=(
            PackageCommittedProductHandoffRecovery(
                product_id=policy.product_id,
                kernel=kernel,
                journal=handoff_journal,
                finalizer=finalizer,
            ),
        ),
    )
    inventory = PackageProductLocalWheelInventory(
        binding_id=lifecycle.binding_id,
        policy=policy,
        desired_state=desired_state,
        committed_sets=committed_sets,
        manifest_path=state_root / "update-manifests.jsonl",
    )
    return PackageProductRuntimeBindingV1(
        product_id=policy.product_id,
        lifecycle=lifecycle,
        inventory=inventory,
        mode="enforced",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PosixLocalWheelProductRuntimeFactory:
    """Bind one Session to Product-supplied owners of a fenced local Store."""

    expected_session_id: str
    expected_cwd: Path
    state_root: Path
    plugin_store_root: Path
    policy: PackageProductLocalWheelPolicy
    environment: PackageResolutionEnvironmentV1
    acquisition_budgets: PackageAcquisitionBudgetV1
    inspection_budgets: PackageInspectionBudgetV1
    closure_budgets: PackageClosureBudgetV1
    root_store_identity: str
    dependency_store_identity: str
    registry: PackageEpochRuntimeLeaseRegistry
    admission_request: PackageEpochRuntimeAdmissionRequestV1
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    recovery_identity: str
    _cwd_identity: tuple[int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.expected_session_id, str) or not self.expected_session_id:
            raise ValueError("Package Product Session identity is required")
        cwd = self.expected_cwd
        if not isinstance(cwd, Path) or not cwd.is_absolute() or ".." in cwd.parts:
            raise ValueError("Package Product workspace must be absolute")
        resolved = cwd.resolve(strict=True)
        metadata = resolved.stat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("Package Product workspace must be a directory")
        object.__setattr__(self, "expected_cwd", resolved)
        object.__setattr__(self, "_cwd_identity", (metadata.st_dev, metadata.st_ino))

    def create(
        self, request: PackageProductRuntimeRequestV1
    ) -> PackageProductRuntimeBindingV1:
        if not isinstance(request, PackageProductRuntimeRequestV1):
            raise TypeError("Package Product runtime request is required")
        if (
            request.product_id != self.policy.product_id
            or request.session_id != self.expected_session_id
            or request.cwd != str(self.expected_cwd)
            or self._current_cwd_identity() != self._cwd_identity
        ):
            raise ValueError("Package Product Session or workspace identity changed")
        binding = compose_posix_local_wheel_product(
            state_root=self.state_root,
            plugin_store_root=self.plugin_store_root,
            policy=self.policy,
            environment=self.environment,
            acquisition_budgets=self.acquisition_budgets,
            inspection_budgets=self.inspection_budgets,
            closure_budgets=self.closure_budgets,
            root_store_identity=self.root_store_identity,
            dependency_store_identity=self.dependency_store_identity,
            registry=self.registry,
            admission_request=self.admission_request,
            management=self.management,
            desired_state=self.desired_state,
            gc_bindings=self.gc_bindings,
            gc_gate=self.gc_gate,
            actor_id=self.actor_id,
            desired_policy_revision=self.desired_policy_revision,
            recovery_identity=self.recovery_identity,
        )
        if self._current_cwd_identity() != self._cwd_identity:
            raise ValueError("Package Product workspace changed during composition")
        return binding

    def _current_cwd_identity(self) -> tuple[int, int] | None:
        try:
            metadata = self.expected_cwd.stat()
        except OSError:
            return None
        if not stat.S_ISDIR(metadata.st_mode):
            return None
        return metadata.st_dev, metadata.st_ino


def _require_private_directory(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError("Package private state root must be absolute")
    if _directory_identity(path) is None:
        raise ValueError("Package private state root is unsafe")


def _directory_identity(path: Path) -> str | None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open("/", flags)
    except OSError:
        return None
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o077
            or metadata.st_uid != os.geteuid()
        ):
            return None
        return sha256(
            canonical_json_bytes(
                {
                    "device": metadata.st_dev,
                    "fileType": "directory",
                    "identityVersion": 1,
                    "inode": metadata.st_ino,
                }
            )
        ).hexdigest()
    except OSError:
        return None
    finally:
        os.close(fd)


__all__ = ["PosixLocalWheelProductRuntimeFactory", "compose_posix_local_wheel_product"]
