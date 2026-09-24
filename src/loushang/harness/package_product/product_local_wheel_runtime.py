"""Explicit POSIX Product composition for pinned local Wheel transactions.

The Product supplies its existing management and GC authorities, an already
fenced Store root, and a live runtime lease. This module creates Package-local
journals and owner adapters but never publishes an epoch or switches a root.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import cast

from loushang.harness.package_product.product_local_wheel_inventory import (
    PackageProductLocalWheelInventory,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    CommittedSetPackageRevisionProjection,
    PackageProductRuntimeReadError,
    PackageProductSelectedRootReader,
    PackageProductSelectedRootSnapshotV1,
    PluginManagementCommandSubmitPort,
    PluginManagementPackageDesiredStateAdapter,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
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
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverResultV1,
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
    PackageProductRuntimeLease,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffFinalizer,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.packages.product_root_target import (
    PackageProductRootTargetAuthority,
)
from loushang.harness.resources.packages.product_transaction import (
    PackageProductLifecycleTransaction,
    PackageProductWheelExecutionFactory,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.manifest import (
    InertPluginFileManifest,
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.selection import PluginSourceTrustSnapshotV1


@dataclass(frozen=True, slots=True)
class PackageProductSelectedPluginManifestV1:
    """Policy-chosen inert manifest plus its complete admitted root evidence."""

    snapshot: PackageProductSelectedRootSnapshotV1
    manifest: InertPluginFileManifest
    declaration_documents: tuple[tuple[str, PluginDeclarationDocument], ...] = ()
    source_trust_snapshot: PluginSourceTrustSnapshotV1 | None = None

    def __post_init__(self) -> None:
        self.verified_manifest()

    def verified_manifest(self) -> InertPluginFileManifest:
        """Reparse captured bytes before using this copyable evidence value."""

        if not isinstance(self.snapshot, PackageProductSelectedRootSnapshotV1):
            raise TypeError("Selected Plugin manifest requires Product root evidence")
        if not isinstance(self.manifest, InertPluginFileManifest):
            raise TypeError("Selected Plugin manifest requires inert metadata")
        if (
            self.manifest.name != self.snapshot.installation_key.plugin_id
            or self.manifest.version != self.snapshot.root_ref.version
        ):
            raise ValueError("Selected Plugin manifest changed Product identity")
        trust = self.source_trust_snapshot
        if trust is not None and (
            not isinstance(trust, PluginSourceTrustSnapshotV1)
            or trust.plugin_id != self.manifest.name
            or trust.package_source_identity
            != self.snapshot.package_revision.package_source_identity
            or not trust.trusted
        ):
            raise ValueError("Selected Plugin source trust changed Product identity")
        root = self.manifest.root_relative_path.as_posix()
        manifest_path = "plugin.json" if root == "." else f"{root}/plugin.json"
        members = dict(self.snapshot.files)
        body = members.get(manifest_path)
        if body is None or sha256(body).hexdigest() != self.manifest.manifest_digest:
            raise ValueError("Selected Plugin manifest changed root bytes")
        parsed = PluginManifestParser().parse_file_set(
            members, manifest_logical_path=manifest_path
        )
        if parsed != self.manifest:
            raise ValueError("Selected Plugin manifest changed captured bytes")
        paths = tuple(path for path, _ in self.declaration_documents)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("Selected Plugin declaration paths are not canonical")
        prefix = "" if root == "." else f"{root}/"
        reservations_by_path: dict[str, list[PluginContributionReservation]] = {}
        for item in parsed.contribution_index.items:
            if item.declaration_source.kind == "document":
                path = f"{prefix}{item.declaration_source.relative_path.as_posix()}"
                reservations_by_path.setdefault(path, []).append(item)
        expected_paths = tuple(sorted(reservations_by_path))
        if paths != expected_paths:
            raise ValueError("Selected Plugin declarations are incomplete")
        for path, document in self.declaration_documents:
            body = members.get(path)
            if (
                not isinstance(document, PluginDeclarationDocument)
                or body is None
                or sha256(body).hexdigest() != document.bytes_digest
            ):
                raise ValueError("Selected Plugin declaration changed root bytes")
            if PluginDeclarationDocumentCodec.decode_bytes(body) != document:
                raise ValueError("Selected Plugin declaration changed captured bytes")
            if not _declarations_match_reservations(
                parsed.name, reservations_by_path[path], document
            ):
                raise ValueError("Selected Plugin declaration changed reservation")
        return parsed

    def verified_data_only_declarations(
        self,
    ) -> tuple[tuple[PluginContributionReservation, PluginDeclaration], ...]:
        """Return exact path-free reservation/declaration pairs from captured bytes."""

        manifest = self.verified_manifest()
        root = manifest.root_relative_path.as_posix()
        prefix = "" if root == "." else f"{root}/"
        documents = dict(self.declaration_documents)
        pairs: list[tuple[PluginContributionReservation, PluginDeclaration]] = []
        for reservation in manifest.contribution_index.items:
            if (
                reservation.contribution_execution_model != "data_only"
                or reservation.declaration_source.kind != "document"
            ):
                raise ValueError("Selected Plugin contribution is not data-only")
            path = f"{prefix}{reservation.declaration_source.relative_path.as_posix()}"
            declaration = next(
                item
                for item in documents[path].declarations
                if item.contribution_id == reservation.contribution_id
            )
            pairs.append((reservation, declaration))
        return tuple(pairs)


def _declarations_match_reservations(
    plugin_id: str,
    reservations: list[PluginContributionReservation],
    document: PluginDeclarationDocument,
) -> bool:
    expected = {item.contribution_id: item for item in reservations}
    actual = {item.contribution_id: item for item in document.declarations}
    return set(expected) == set(actual) and all(
        declaration.plugin_id == plugin_id
        and declaration.kind == reservation.kind
        and declaration.owner == reservation.owner
        and declaration.reservation_fingerprint == reservation.fingerprint
        and declaration.source_descriptor_fingerprint
        == reservation.source_descriptor_fingerprint
        and declaration.source_kind == "document"
        and (
            declaration.contribution_execution_model is None
            or declaration.contribution_execution_model
            == reservation.contribution_execution_model
        )
        and declaration.worker_configuration == reservation.worker_configuration
        for contribution_id, reservation in expected.items()
        for declaration in (actual[contribution_id],)
    )


@dataclass(frozen=True, slots=True)
class _LocalWheelSelectedManifestReader:
    policy: PackageProductLocalWheelPolicy
    root_reader: PackageProductSelectedRootReader

    def capture_selected_manifest_for_plugin(
        self,
        plugin_id: str,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedPluginManifestV1:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Product Plugin selection id is invalid")
        return self.capture_selected_manifest(
            PluginInstallationKeyV1(
                product_id=self.policy.product_id,
                installation_scope="workspace",
                scope_id=self.policy.project_scope_id,
                plugin_id=plugin_id,
            ),
            max_files=max_files,
            max_total_bytes=max_total_bytes,
        )

    def capture_selected_manifest(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedPluginManifestV1:
        if (
            not isinstance(installation_key, PluginInstallationKeyV1)
            or installation_key.product_id != self.policy.product_id
            or installation_key.scope_id != self.policy.project_scope_id
        ):
            raise PackageProductRuntimeReadError(
                "Product Plugin manifest scope changed",
                code="package_product_root_scope_changed",
            )
        snapshot = self.root_reader.capture_selected_root(
            installation_key,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
        )
        matches = tuple(
            binding
            for binding in self.policy.bindings
            if binding.plugin_id == installation_key.plugin_id
            and binding.source_identity
            == snapshot.package_revision.package_source_identity
            and binding.artifact_digest == snapshot.root_ref.artifact_digest
            and binding.plugin_manifest_path is not None
        )
        if len(matches) != 1:
            raise PackageProductRuntimeReadError(
                "Selected Plugin manifest has no exact Product policy binding",
                code="package_product_manifest_unbound",
            )
        manifest_path = matches[0].plugin_manifest_path
        assert manifest_path is not None
        try:
            manifest = PluginManifestParser().parse_file_set(
                dict(snapshot.files), manifest_logical_path=manifest_path
            )
        except PluginManifestError as exc:
            raise PackageProductRuntimeReadError(
                "Selected Plugin manifest failed inert parsing",
                code="package_product_manifest_invalid",
            ) from exc
        if (
            manifest.name != installation_key.plugin_id
            or manifest.version != snapshot.root_ref.version
        ):
            raise PackageProductRuntimeReadError(
                "Selected Plugin manifest changed Product identity",
                code="package_product_manifest_mismatch",
            )
        root = manifest.root_relative_path.as_posix()
        root_prefix = "" if root == "." else f"{root}/"
        reservations_by_path: dict[str, list[PluginContributionReservation]] = {}
        for reservation in manifest.contribution_index.items:
            source = reservation.declaration_source
            if source.kind == "document":
                path = f"{root_prefix}{source.relative_path.as_posix()}"
                reservations_by_path.setdefault(path, []).append(reservation)
        members = dict(snapshot.files)
        documents: list[tuple[str, PluginDeclarationDocument]] = []
        for path, reservations in sorted(reservations_by_path.items()):
            try:
                document = PluginDeclarationDocumentCodec.decode_bytes(members[path])
            except (KeyError, PluginDeclarationCodecError) as exc:
                raise PackageProductRuntimeReadError(
                    "Selected Plugin declaration document is invalid",
                    code="package_product_declaration_invalid",
                ) from exc
            if not _declarations_match_reservations(
                manifest.name, reservations, document
            ):
                raise PackageProductRuntimeReadError(
                    "Selected Plugin declaration changed its manifest reservation",
                    code="package_product_declaration_mismatch",
                )
            documents.append((path, document))
        return PackageProductSelectedPluginManifestV1(
            snapshot=snapshot,
            manifest=manifest,
            declaration_documents=tuple(documents),
            source_trust_snapshot=(
                PluginSourceTrustSnapshotV1(
                    plugin_id=manifest.name,
                    package_source_identity=matches[0].source_identity,
                    source_trust_class=matches[0].source_trust_class,
                    source_trust_policy_revision=self.policy.authority_revision,
                    trusted=True,
                )
                if matches[0].source_trust_class is not None
                else None
            ),
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
    root_settlements = PackageStoreSettlementJournal(
        state_root / "root-settlements.jsonl"
    )
    root_store = PosixPackagePluginRootMaterializationStore(
        plugin_store_root,
        store_identity=root_store_identity,
        package_store_id=registry.store_id,
        settlement_journal=root_settlements,
    )
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
        root_staging=root_store,
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
    selected_root_reader = PackageProductSelectedRootReader(
        product_id=policy.product_id,
        scope_id=policy.project_scope_id,
        installation_scope="workspace",
        desired_state=desired_state,
        bindings=gc_bindings,
        committed_sets=committed_sets,
        root_settlements=root_settlements,
        root_store=root_store,
        gc_gate=gc_gate,
    )
    return PackageProductRuntimeBindingV1(
        product_id=policy.product_id,
        lifecycle=lifecycle,
        inventory=inventory,
        mode="enforced",
        _selected_root_reader=selected_root_reader,
        _selected_manifest_reader=_LocalWheelSelectedManifestReader(
            policy=policy, root_reader=selected_root_reader
        ),
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
    runtime_lease: PackageProductRuntimeLease
    cutover_result: PackagePosixEpochCutoverResultV1
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    recovery_identity: str
    _cwd_identity: tuple[int, int] = field(init=False, repr=False)
    _create_lock: Lock = field(
        default_factory=Lock, init=False, repr=False, compare=False
    )
    _create_started: bool = field(default=False, init=False, repr=False, compare=False)
    _binding_issued: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.expected_session_id, str)
            or not self.expected_session_id
        ):
            raise ValueError("Package Product Session identity is required")
        if not isinstance(self.runtime_lease, PackageProductRuntimeLease):
            raise TypeError("Package Product runtime lease is required")
        if (
            not isinstance(self.cutover_result, PackagePosixEpochCutoverResultV1)
            or self.cutover_result.disposition != "fenced"
            or self.cutover_result.fence is None
            or self.cutover_result.switch_receipt is None
        ):
            raise ValueError("Package Product requires completed POSIX cutover")
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
        cutover = self.cutover_result
        fence = cutover.fence
        switch = cutover.switch_receipt
        registry = self.runtime_lease.registry
        admission_request = self.runtime_lease.admission_request
        if fence is None or switch is None:
            raise ValueError("Package Product requires completed POSIX cutover")
        if (
            registry.fences.current(registry.store_id) != fence
            or switch.store_id != registry.store_id
            or fence.request.store_id != switch.store_id
            or fence.request.prior_epoch != switch.prior_epoch
            or fence.request.next_epoch != switch.next_epoch
            or fence.request.legacy_root_identity != switch.legacy_root_identity
            or fence.request.fenced_root_identity != switch.fenced_root_identity
            or fence.request.namespace_id != switch.namespace_id
            or fence.request.quiescence_receipt_id != switch.quiescence_receipt_id
            or fence.request.snapshot_receipt_id != switch.snapshot_receipt_id
            or self.plugin_store_root.name != switch.namespace_id
            or _directory_identity(self.plugin_store_root)
            != switch.fenced_root_identity
            or admission_request.fence_id != fence.fence_id
            or admission_request.store_root_identity != switch.fenced_root_identity
        ):
            raise ValueError("Package Product POSIX cutover evidence changed")
        with self._create_lock:
            if self._create_started:
                raise ValueError("Package Product runtime factory already used")
            object.__setattr__(self, "_create_started", True)
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
                registry=registry,
                admission_request=admission_request,
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
            bound = replace(binding, on_dispose=self.runtime_lease.release)
            object.__setattr__(self, "_binding_issued", True)
            return bound

    def dispose_unbound_runtime(self) -> None:
        """Release the lease if Session bootstrap rejects before binding exists."""

        with self._create_lock:
            if self._binding_issued:
                return
            object.__setattr__(self, "_create_started", True)
            self.runtime_lease.release()

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


__all__ = [
    "PackageProductSelectedPluginManifestV1",
    "PosixLocalWheelProductRuntimeFactory",
    "compose_posix_local_wheel_product",
]
