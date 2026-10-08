"""Explicit POSIX Product composition for pinned local Wheel transactions.

The Product supplies its existing management and GC authorities, an already
fenced Store root, and a live runtime lease. This module creates Package-local
journals and owner adapters but never publishes an epoch or switches a root.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Never, cast

from packaging.markers import default_environment
from packaging.tags import sys_tags

from loushang.harness.package_product.product_local_wheel_inventory import (
    PackageProductLocalWheelInventory,
)
from loushang.harness.package_product.product_pinned_adoption import (
    PackageProductPinnedAdoptionOwner,
)
from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductRebindCleanupReader,
)
from loushang.harness.package_product.product_rebind_decision import (
    PackageProductRebindDecisionOwner,
)
from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseReader,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceReader,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductPluginDesiredSelectionV1,
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.package_product.product_staging_adoption import (
    PackageProductStagingAdoptionOwner,
)
from loushang.harness.package_product.product_worker_wheel_admission import (
    admit_explicit_local_worker_wheel_candidate,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
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
    PackageProductSelectedDependencyClosureSnapshotV1,
    PackageProductSelectedDependencyReader,
    PackageProductSelectedDependencySnapshotV1,
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
    VerifiedPackageClosureCandidate,
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
    PosixPackageDependencyReadOnlyStore,
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
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_materialization import (
    WindowsPackageDependencyMaterializationStore,
    WindowsPackageDependencyReadOnlyStore,
    WindowsPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductEpochTransactionGuardPort,
)
from loushang.harness.resources.packages.product_admission_binding import (
    PackageProductAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_composition import (
    PackageCommittedProductHandoffRecovery,
    PackageRetentionHandoffRecovery,
    compose_package_product_lifecycle,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductFileEpochTransactionGuard,
    PackageProductPosixFencedRuntimeOwner,
    PackageProductRuntimeLease,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffFinalizer,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductRouteRequestV1,
    PackageProductTransactionRoute,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_root_target import (
    PackageProductRootTargetAuthority,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_transaction import (
    PackageProductCandidateRejected,
    PackageProductLifecycleTransaction,
    PackageProductWheelExecutionFactory,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsEpochTransactionGuard,
    PackageProductWindowsFencedRuntimeOwner,
    PackageProductWindowsStoreRootAdmission,
    PackageWindowsProductRuntimeLease,
    inspect_windows_product_private_directory_identity,
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
from loushang.harness.resources.theme_document import parse_theme_document_v1


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


def _admit_external_data_only_candidate(
    policy: PackageProductLocalWheelPolicy,
    request: PackageProductTransactionRoute,
    closure: VerifiedPackageClosureCandidate,
) -> None:
    """Check the gated data Resource shapes after PLC9B wheel verification."""

    source = request.ingress.source_locator
    bindings = tuple(item for item in policy.bindings if item.source_identity == source)
    legacy_kinds = {
        "legacy-local-reacquired": "skill",
        "legacy-local-reacquired-prompt": "prompt",
        "legacy-local-reacquired-theme": "theme",
    }
    if len(bindings) != 1 or bindings[0].source_trust_class not in {
        "local-data-only",
        *legacy_kinds,
    }:
        return
    binding = bindings[0]

    def reject() -> Never:
        raise PackageProductCandidateRejected(
            "Untrusted data Wheel shape is unsupported"
        )

    if len(closure.candidates) != 1 or binding.plugin_manifest_path is None:
        reject()
    wheel = closure.candidates[0]
    tree = wheel.transfer_manifest
    legacy = binding.source_trust_class in legacy_kinds
    root = (
        binding.plugin_manifest_path.removesuffix("/plugin.json")
        if legacy
        else binding.plugin_id
    )
    distribution = root.replace("_", "-") if legacy else binding.plugin_id
    if legacy and not re.fullmatch(r"loushang_legacy_[0-9a-f]{24}", root):
        reject()
    dist_info = f"{root}-{tree.version}.dist-info"
    metadata_paths = {
        f"{dist_info}/WHEEL",
        f"{dist_info}/METADATA",
        f"{dist_info}/RECORD",
    }
    fixed_paths = {
        f"{root}/plugin.json",
        f"{root}/declarations/resources.json",
    }
    if (
        tree.node_id != "root"
        or tree.distribution != distribution
        or wheel.evidence.artifact_digest != binding.artifact_digest
        or binding.plugin_manifest_path != f"{root}/plugin.json"
        or binding.requested_package != f"{distribution}=={tree.version}"
        or wheel.requires_dist
        or wheel.provides_extra
        or len(tree.entries) > 16
        or tree.total_byte_count > 1024 * 1024
    ):
        reject()
    files: dict[str, bytes] = {}
    for entry in tree.entries:
        path = entry.logical_path
        resource_path = (
            (
                path.startswith(f"{root}/skills/")
                and len(path.split("/")) == 4
                and path.endswith("/SKILL.md")
            )
            or (
                path.startswith(f"{root}/prompts/")
                and len(path.split("/")) == 3
                and path.endswith(".md")
            )
            or (
                path.startswith(f"{root}/themes/")
                and len(path.split("/")) == 3
                and path.endswith(".json")
            )
        )
        if path not in metadata_paths | fixed_paths and not resource_path:
            reject()
        if entry.byte_count > 1024 * 1024:
            reject()
        with wheel.open_verified_tree_file(entry) as handle:
            body = handle.read(entry.byte_count + 1)
        if (
            len(body) != entry.byte_count
            or sha256(body).hexdigest() != entry.content_digest
        ):
            reject()
        files[path] = body
    if not fixed_paths | metadata_paths <= files.keys():
        reject()
    try:
        manifest = PluginManifestParser().parse_file_set(
            files, manifest_logical_path=f"{root}/plugin.json"
        )
        if (
            manifest.name != binding.plugin_id
            or manifest.version != tree.version
            or len(manifest.contribution_index.items) != 1
        ):
            reject()
        reservation = manifest.contribution_index.items[0]
        if (
            reservation.kind != "resource_item"
            or reservation.contribution_execution_model != "data_only"
            or reservation.declaration_source.kind != "document"
            or reservation.declaration_source.relative_path.as_posix()
            != "declarations/resources.json"
            or reservation.requested_authorities
            or reservation.configuration
            or reservation.worker_configuration is not None
        ):
            reject()
        document = PluginDeclarationDocumentCodec.decode_bytes(
            files[f"{root}/declarations/resources.json"]
        )
        if not _declarations_match_reservations(
            binding.plugin_id, [reservation], document
        ):
            reject()
        declaration = document.declarations[0]
        payload = ResourceItemDeclarationPayload.from_dict(dict(declaration.payload))
        if legacy and payload.resource_kind != legacy_kinds.get(
            binding.source_trust_class or ""
        ):
            reject()
        if payload.owner_namespace != f"resources.{payload.resource_kind}":
            reject()
        if payload.resource_kind == "skill":
            expected_body = f"{root}/{payload.locator}/SKILL.md"
            admissible = (
                payload.locator_kind == "directory"
                and payload.schema_id == "loushang.resource.skill"
                and payload.media_type == "text/markdown"
            )
        elif payload.resource_kind == "prompt":
            expected_body = f"{root}/{payload.locator}"
            admissible = (
                payload.locator_kind == "file"
                and payload.schema_id == "loushang.resource.prompt"
                and payload.media_type == "text/markdown"
                and payload.locator.startswith("prompts/")
                and len(payload.locator.split("/")) == 2
                and payload.locator.endswith(".md")
            )
        elif payload.resource_kind == "theme":
            expected_body = f"{root}/{payload.locator}"
            admissible = (
                payload.locator_kind == "file"
                and payload.schema_id == "loushang.resource.theme"
                and payload.media_type == "application/json"
                and payload.locator.startswith("themes/")
                and len(payload.locator.split("/")) == 2
                and payload.locator.endswith(".json")
            )
        else:
            reject()
        if not admissible or set(files) - fixed_paths - metadata_paths != {
            expected_body
        }:
            reject()
        if payload.resource_kind == "theme":
            parse_theme_document_v1(files[expected_body])
    except (
        KeyError,
        ValueError,
        TypeError,
        PluginManifestError,
        PluginDeclarationCodecError,
    ) as exc:
        raise PackageProductCandidateRejected(
            "External data Wheel declaration is unsupported"
        ) from exc


@dataclass(frozen=True, slots=True)
class _LocalWheelSelectedManifestReader:
    policy: PackageProductLocalWheelPolicy
    root_reader: PackageProductSelectedRootReader
    read_only: bool = False

    def capture_plugin_desired_selection_for(
        self, plugin_id: str
    ) -> PackageProductPluginDesiredSelectionV1:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Product Plugin selection id is invalid")
        key = PluginInstallationKeyV1(
            product_id=self.policy.product_id,
            installation_scope="workspace",
            scope_id=self.policy.project_scope_id,
            plugin_id=plugin_id,
        )
        snapshot, _ = self.root_reader.desired_state.capture_read_only()
        return PackageProductPluginDesiredSelectionV1(
            installation_key=key,
            inventory_revision=snapshot.inventory_revision,
            desired_state=snapshot.installation(key).selection.desired_state,
            recorded=any(
                item.installation_key == key for item in snapshot.installations
            ),
        )

    def selected_external_data_plugin_ids(self) -> tuple[str, ...]:
        selected = (
            self.root_reader.desired_state.capture_read_only()[0].installations
            if self.read_only
            else self.root_reader.desired_state.snapshot().installations
        )
        return tuple(
            sorted(
                item.installation_key.plugin_id
                for item in selected
                if item.installation_key.product_id == self.policy.product_id
                and item.installation_key.installation_scope
                == self.root_reader.installation_scope
                and item.installation_key.scope_id == self.policy.project_scope_id
                and item.selection.desired_state == "installed_enabled"
                and item.selection.package_revision is not None
                and any(
                    binding.plugin_id == item.installation_key.plugin_id
                    and binding.source_trust_class
                    in {
                        "local-data-only",
                        "legacy-local-reacquired",
                        "legacy-local-reacquired-prompt",
                        "legacy-local-reacquired-theme",
                    }
                    and binding.source_identity
                    == item.selection.package_revision.package_source_identity
                    and binding.artifact_digest
                    == item.selection.package_revision.package_content_digest
                    for binding in self.policy.bindings
                )
            )
        )

    def assert_selected_manifest_current(
        self, selected: PackageProductSelectedPluginManifestV1
    ) -> None:
        if self.read_only:
            raise PermissionError(
                "Read-only Product manifest reader has no live recheck"
            )
        if not isinstance(selected, PackageProductSelectedPluginManifestV1):
            raise TypeError("Product selected Plugin manifest is required")
        self.root_reader.assert_selected_root_current(selected.snapshot)

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
        snapshot = (
            self.root_reader.capture_selected_root_read_only(
                installation_key,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
            if self.read_only
            else self.root_reader.capture_selected_root(
                installation_key,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
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


@dataclass(frozen=True, slots=True)
class _LocalWheelSelectedDependencyReader:
    policy: PackageProductLocalWheelPolicy
    root_reader: PackageProductSelectedRootReader
    store_root: Path
    store_identity: str
    settlements: PackageStoreSettlementJournal
    windows: bool

    def capture_selected_dependency_for_plugin(
        self,
        plugin_id: str,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencySnapshotV1:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Product Plugin selection id is invalid")
        return self._reader().capture_selected_dependency(
            PluginInstallationKeyV1(
                product_id=self.policy.product_id,
                installation_scope="workspace",
                scope_id=self.policy.project_scope_id,
                plugin_id=plugin_id,
            ),
            max_files=max_files,
            max_total_bytes=max_total_bytes,
        )

    def assert_selected_dependency_current(
        self, snapshot: PackageProductSelectedDependencySnapshotV1
    ) -> None:
        self._reader().assert_selected_dependency_current(snapshot)

    def capture_selected_dependency_closure_for_plugin(
        self,
        plugin_id: str,
        *,
        max_dependencies: int,
        max_files_per_dependency: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencyClosureSnapshotV1:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Product Plugin selection id is invalid")
        return self._reader().capture_selected_dependency_closure(
            PluginInstallationKeyV1(
                product_id=self.policy.product_id,
                installation_scope="workspace",
                scope_id=self.policy.project_scope_id,
                plugin_id=plugin_id,
            ),
            max_dependencies=max_dependencies,
            max_files_per_dependency=max_files_per_dependency,
            max_total_bytes=max_total_bytes,
        )

    def assert_selected_dependency_closure_current(
        self, snapshot: PackageProductSelectedDependencyClosureSnapshotV1
    ) -> None:
        self._reader().assert_selected_dependency_closure_current(snapshot)

    def _reader(self) -> PackageProductSelectedDependencyReader:
        store = (
            WindowsPackageDependencyReadOnlyStore(
                self.store_root,
                store_identity=self.store_identity,
                settlement_journal=self.settlements,
            )
            if self.windows
            else PosixPackageDependencyReadOnlyStore(
                self.store_root,
                store_identity=self.store_identity,
                settlement_journal=self.settlements,
            )
        )
        return PackageProductSelectedDependencyReader(
            root_reader=self.root_reader,
            dependency_settlements=self.settlements,
            dependency_store=store,
            dependency_store_identity=self.store_identity,
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
    """Compose the POSIX Product with its fenced Store and live lease owner."""

    return _compose_local_wheel_product(
        state_root=state_root,
        plugin_store_root=plugin_store_root,
        policy=policy,
        environment=environment,
        acquisition_budgets=acquisition_budgets,
        inspection_budgets=inspection_budgets,
        closure_budgets=closure_budgets,
        root_store_identity=root_store_identity,
        dependency_store_identity=dependency_store_identity,
        registry=registry,
        admission_request=admission_request,
        management=management,
        desired_state=desired_state,
        gc_bindings=gc_bindings,
        gc_gate=gc_gate,
        actor_id=actor_id,
        desired_policy_revision=desired_policy_revision,
        recovery_identity=recovery_identity,
        windows_epoch_runtime=None,
    )


def compose_windows_local_wheel_product(
    *,
    epoch_runtime: PackageProductWindowsFencedRuntimeOwner,
    policy: PackageProductLocalWheelPolicy,
    environment: PackageResolutionEnvironmentV1,
    acquisition_budgets: PackageAcquisitionBudgetV1,
    inspection_budgets: PackageInspectionBudgetV1,
    closure_budgets: PackageClosureBudgetV1,
    root_store_identity: str,
    dependency_store_identity: str,
    admission_request: PackageEpochRuntimeAdmissionRequestV1,
    management: PluginManagementService,
    desired_state: PluginDesiredStateLedger,
    gc_bindings: PluginPackageGcBindingJournal,
    gc_gate: PluginPackageGcReservationJournal,
    actor_id: str,
    desired_policy_revision: str,
    recovery_identity: str,
) -> PackageProductRuntimeBindingV1:
    """Compose the Windows Product from exact epoch-owned private roots."""

    if not isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        raise TypeError("Windows Package Product epoch owner is required")
    return _compose_local_wheel_product(
        state_root=epoch_runtime.prepare_product_state_root(),
        plugin_store_root=epoch_runtime.selected_store_root(),
        policy=policy,
        environment=environment,
        acquisition_budgets=acquisition_budgets,
        inspection_budgets=inspection_budgets,
        closure_budgets=closure_budgets,
        root_store_identity=root_store_identity,
        dependency_store_identity=dependency_store_identity,
        registry=epoch_runtime.registry,
        admission_request=admission_request,
        management=management,
        desired_state=desired_state,
        gc_bindings=gc_bindings,
        gc_gate=gc_gate,
        actor_id=actor_id,
        desired_policy_revision=desired_policy_revision,
        recovery_identity=recovery_identity,
        windows_epoch_runtime=epoch_runtime,
    )


def _compose_local_wheel_product(
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
    registry: PackageEpochRuntimeLeaseRegistry
    | PackageWindowsEpochRuntimeLeaseRegistry,
    admission_request: PackageEpochRuntimeAdmissionRequestV1,
    management: PluginManagementService,
    desired_state: PluginDesiredStateLedger,
    gc_bindings: PluginPackageGcBindingJournal,
    gc_gate: PluginPackageGcReservationJournal,
    actor_id: str,
    desired_policy_revision: str,
    recovery_identity: str,
    windows_epoch_runtime: PackageProductWindowsFencedRuntimeOwner | None,
) -> PackageProductRuntimeBindingV1:
    """Bind the exact Product transaction and inventory before activation."""

    if windows_epoch_runtime is None:
        if os.name != "posix" or not all(
            hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC")
        ):
            raise RuntimeError("POSIX rooted Package Store is required")
        if not isinstance(registry, PackageEpochRuntimeLeaseRegistry):
            raise TypeError("POSIX runtime lease registry is required")
    elif (
        os.name != "nt"
        or not isinstance(registry, PackageWindowsEpochRuntimeLeaseRegistry)
        or windows_epoch_runtime.registry is not registry
    ):
        raise RuntimeError("Windows rooted Package Store is required")
    for value, expected, name in (
        (policy, PackageProductLocalWheelPolicy, "Product Wheel policy"),
        (environment, PackageResolutionEnvironmentV1, "resolution environment"),
        (acquisition_budgets, PackageAcquisitionBudgetV1, "acquisition budgets"),
        (inspection_budgets, PackageInspectionBudgetV1, "inspection budgets"),
        (closure_budgets, PackageClosureBudgetV1, "closure budgets"),
        (
            registry,
            (PackageEpochRuntimeLeaseRegistry, PackageWindowsEpochRuntimeLeaseRegistry),
            "runtime lease registry",
        ),
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
    if windows_epoch_runtime is None:
        _require_private_directory(state_root)
    else:
        windows_epoch_runtime.assert_current()
        if (
            state_root != windows_epoch_runtime.control_root / "product-state"
            or plugin_store_root != windows_epoch_runtime.selected_store_root()
        ):
            raise ValueError("Windows Package Product roots changed")
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
    observed_root_identity = (
        _directory_identity(plugin_store_root)
        if windows_epoch_runtime is None
        else current_fence.fenced_root_identity
        if current_fence is not None
        else None
    )
    if (
        environment.fingerprint != policy.resolution_environment_fingerprint
        or registry.store_id != admission_request.store_id
        or current_fence is None
        or current_fence.fence_id != admission_request.fence_id
        or observed_root_identity != admission_request.store_root_identity
        or desired_state.gc_gate is not gc_gate
        or management.gc_gate is not gc_gate
        or getattr(management, "_desired_state", None) is not desired_state
    ):
        raise ValueError("Package Product owner, epoch, or Store identity changed")

    if windows_epoch_runtime is None:
        dependency_root = state_root / "dependency-store"
        dependency_root.mkdir(mode=0o700, exist_ok=True)
        _require_private_directory(dependency_root)
    else:
        dependency_root = windows_epoch_runtime.prepare_product_dependency_root()
    lifecycle_journal = PackageLifecycleJournal(state_root / "lifecycle.jsonl")
    admission_bindings = PackageProductAdmissionBindingJournal(
        state_root / "admission-bindings.jsonl"
    )
    proposed_rebind_bindings = PackageProductRebindAdmissionBindingJournal(
        state_root / "rebind-admissions.jsonl"
    )
    proposed_pinned_bindings = PackageProductPinnedAdoptionBindingJournal(
        state_root / "pinned-admissions.jsonl"
    )
    proposed_staging_bindings = PackageProductStagingAdoptionBindingJournal(
        state_root / "staging-admissions.jsonl"
    )
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
    root_store = (
        PosixPackagePluginRootMaterializationStore(
            plugin_store_root,
            store_identity=root_store_identity,
            package_store_id=registry.store_id,
            settlement_journal=root_settlements,
        )
        if windows_epoch_runtime is None
        else WindowsPackagePluginRootMaterializationStore(
            plugin_store_root,
            store_identity=root_store_identity,
            package_store_id=registry.store_id,
            settlement_journal=root_settlements,
        )
    )
    dependency_settlements = PackageStoreSettlementJournal(
        state_root / "dependency-settlements.jsonl"
    )
    dependency_store = (
        PosixPackageDependencyMaterializationStore(
            dependency_root,
            store_identity=dependency_store_identity,
            settlement_journal=dependency_settlements,
        )
        if windows_epoch_runtime is None
        else WindowsPackageDependencyMaterializationStore(
            dependency_root,
            store_identity=dependency_store_identity,
            settlement_journal=dependency_settlements,
        )
    )
    staging_journal = PackageArtifactStagingJournal(state_root / "staging.jsonl")
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
        dependency_staging=dependency_store,
        root_staging=root_store,
        staging_journal=staging_journal,
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
            lifecycle_journal=lifecycle_journal,
            desired_state=desired_state,
        ),
    )

    def update_inventory_revision(operation_id: str) -> int:
        anchor = gc_bindings.update_anchor(operation_id)
        if anchor is None:
            raise PackageProductRuntimeReadError(
                "Product update predecessor is unbound",
                code="package_product_update_anchor_missing",
            )
        _, transitions = desired_state.capture()
        anchored_prior = next(
            (
                item.committed_state.selection.package_revision
                for item in reversed(transitions)
                if item.inventory_revision <= anchor.expected_inventory_revision
                and item.committed_state.installation_key.plugin_id == anchor.plugin_id
                and item.committed_state.installation_key.product_id
                == policy.product_id
                and item.committed_state.installation_key.scope_id
                == policy.project_scope_id
            ),
            None,
        )
        if anchored_prior != anchor.expected_package_revision:
            raise PackageProductRuntimeReadError(
                "Product update predecessor changed",
                code="package_product_update_anchor_conflict",
            )
        return anchor.expected_inventory_revision

    finalizer = PackageProductHandoffFinalizer(
        kernel=kernel,
        commit=commit,
        admission=admission,
        transaction_pins=pin_journal,
        journal=handoff_journal,
        handoff=handoff,
        inventory_revision=projection.inventory_revision,
        update_inventory_revision=update_inventory_revision,
        rebind_bindings=proposed_rebind_bindings,
        pinned_bindings=proposed_pinned_bindings,
        staging_bindings=proposed_staging_bindings,
    )

    def update_allowed(request: PackageProductTransactionRoute) -> bool:
        bindings = tuple(
            binding
            for binding in policy.bindings
            if binding.source_identity == request.ingress.source_locator
        )
        return len(bindings) == 1 and bindings[0].source_trust_class in {
            "local-data-only",
            "local-worker-candidate",
        }

    def anchor_update(request: PackageProductRouteRequestV1) -> None:
        if not update_allowed(request):
            return
        ingress = request.ingress
        plugin_id = ingress.requested_plugin_id
        if not isinstance(plugin_id, str) or not plugin_id:
            return
        existing = gc_bindings.update_anchor(ingress.operation_id)
        if existing is not None:
            if (
                existing.plugin_id != plugin_id
                or existing.source_identity != ingress.source_locator
            ):
                raise PackageProductRuntimeReadError(
                    "Product update predecessor identity changed",
                    code="package_product_update_anchor_conflict",
                )
            return
        key = PluginInstallationKeyV1(
            product_id=ingress.product_id,
            installation_scope="workspace",
            scope_id=ingress.scope_id,
            plugin_id=plugin_id,
        )
        snapshot = desired_state.snapshot()
        prior = snapshot.installation(key).selection.package_revision
        if prior is None:
            return
        gc_bindings.anchor_update(
            operation_id=ingress.operation_id,
            source_identity=ingress.source_locator,
            plugin_id=plugin_id,
            expected_inventory_revision=snapshot.inventory_revision,
            expected_package_revision=prior,
        )

    def existing_installation(request: PackageProductTransactionRoute) -> bool:
        ingress = request.ingress
        plugin_id = ingress.requested_plugin_id
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Package Product installation identity is missing")
        key = PluginInstallationKeyV1(
            product_id=ingress.product_id,
            installation_scope="workspace",
            scope_id=ingress.scope_id,
            plugin_id=plugin_id,
        )
        return (
            desired_state.snapshot().installation(key).selection.desired_state
            != "absent"
        )

    rebind_source = PackageProductRebindSourceReader(
        policy=policy,
        lifecycle=lifecycle_journal,
        resolution=resolution_journal,
    )
    rebind_lease = PackageProductRebindLeaseReader(
        lifecycle=lifecycle_journal,
        original_bindings=admission_bindings,
        proposed_bindings=proposed_rebind_bindings,
        pinned_bindings=proposed_pinned_bindings,
        staging_bindings=proposed_staging_bindings,
        snapshots=registry,
        current_admission_request=admission_request,
    )
    rebind_cleanup = PackageProductRebindCleanupReader(
        lifecycle=lifecycle_journal,
        resolution=resolution_journal,
        artifacts=evidence_journal,
        cleanup=cleanup,
        quarantine=quarantine,
        pins=pin_journal,
        staging=staging_journal,
        committed_sets=committed_sets,
        handoff=handoff_journal,
        pin_recovery_identity=recovery_identity,
    )
    rebind_decision = PackageProductRebindDecisionOwner(
        lifecycle=lifecycle_journal,
        source=rebind_source,
        lease=rebind_lease,
        cleanup=rebind_cleanup,
        quarantine_cleanup=cleanup,
        proposals=proposed_rebind_bindings,
    )
    pinned_adoption = PackageProductPinnedAdoptionOwner(
        lifecycle=lifecycle_journal,
        source=rebind_source,
        lease=rebind_lease,
        cleanup=rebind_cleanup,
        resolution=resolution_journal,
        proposals=proposed_pinned_bindings,
    )
    staging_adoption = PackageProductStagingAdoptionOwner(
        lifecycle=lifecycle_journal,
        source=rebind_source,
        lease=rebind_lease,
        checkpoint=staging,
        proposals=proposed_staging_bindings,
    )

    def admit_candidate(
        request: PackageProductTransactionRoute,
        candidate: VerifiedPackageClosureCandidate,
    ) -> None:
        _admit_external_data_only_candidate(policy, request, candidate)
        admit_explicit_local_worker_wheel_candidate(policy, request, candidate)

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
        existing_installation=existing_installation,
        update_allowed=update_allowed,
        candidate_admission=admit_candidate,
        cleanup=cleanup,
        rebound_execution_authority=rebind_decision.authorize,
        pinned_execution_authority=pinned_adoption.authorize,
        staging_execution_authority=staging_adoption.authorize,
    )
    runtime_admission: PackageEpochRuntimeAdmissionOwner
    transaction_guard: PackageProductEpochTransactionGuardPort
    if windows_epoch_runtime is None:
        if not isinstance(registry, PackageEpochRuntimeLeaseRegistry):
            raise TypeError("POSIX runtime lease registry changed")
        runtime_admission = _PosixStoreRootAdmission(
            registry=registry, root=plugin_store_root
        )
        transaction_guard = PackageProductFileEpochTransactionGuard(
            store_id=registry.store_id,
            coordination_lock=registry.coordination_lock,
            file_io=registry._io,
        )
    else:
        runtime_admission = PackageProductWindowsStoreRootAdmission(
            epoch_runtime=windows_epoch_runtime
        )
        transaction_guard = PackageProductWindowsEpochTransactionGuard(
            windows_epoch_runtime
        )
    lifecycle = compose_package_product_lifecycle(
        product_id=policy.product_id,
        owner=kernel,
        transaction=transaction,
        ingress_factory=policy,
        runtime_admission=runtime_admission,
        admission_request=admission_request,
        transaction_guard=transaction_guard,
        update_preflight=anchor_update,
        admission_binding=admission_bindings,
        reference_guard=gc_gate.guard,
        recoveries=(PackageRetentionHandoffRecovery(handoff_journal, handoff),),
        admitted_recoveries=(
            PackageCommittedProductHandoffRecovery(
                product_id=policy.product_id,
                kernel=kernel,
                journal=handoff_journal,
                finalizer=finalizer,
                rebind_bindings=proposed_rebind_bindings,
                pinned_bindings=proposed_pinned_bindings,
                staging_bindings=proposed_staging_bindings,
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
        _selected_dependency_reader=_LocalWheelSelectedDependencyReader(
            policy=policy,
            root_reader=selected_root_reader,
            store_root=dependency_root,
            store_identity=dependency_store_identity,
            settlements=dependency_settlements,
            windows=windows_epoch_runtime is not None,
        ),
        _rebind_source_reader=rebind_source,
        _rebind_lease_reader=rebind_lease,
        _rebind_cleanup_reader=rebind_cleanup,
        _rebind_decision_owner=rebind_decision,
        _pinned_adoption_owner=pinned_adoption,
        _staging_adoption_owner=staging_adoption,
        _staging_checkpoint_reader=staging,
    )


@dataclass(frozen=True, slots=True)
class PosixLocalWheelProductHostInputs:
    """Host resolution facts and bounded local-Wheel work for one Product."""

    environment: PackageResolutionEnvironmentV1
    acquisition_budgets: PackageAcquisitionBudgetV1
    inspection_budgets: PackageInspectionBudgetV1
    closure_budgets: PackageClosureBudgetV1

    @classmethod
    def current_host(
        cls, *, max_transport_bytes: int
    ) -> PosixLocalWheelProductHostInputs:
        return cls(
            environment=PackageResolutionEnvironmentV1.from_mapping(
                {key: str(value) for key, value in default_environment().items()},
                supported_tags=tuple(str(tag) for tag in sys_tags()),
            ),
            acquisition_budgets=PackageAcquisitionBudgetV1(
                max_transport_bytes=max_transport_bytes,
                max_requests=1,
                max_redirects=0,
                max_wall_time_ms=30_000,
            ),
            inspection_budgets=PackageInspectionBudgetV1(),
            closure_budgets=PackageClosureBudgetV1(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PosixLocalWheelProductSessionOwner:
    """Issue one Session factory from fixed, fenced Product authorities."""

    workspace: Path
    state_root: Path
    plugin_store_root: Path
    policy: PackageProductLocalWheelPolicy
    environment: PackageResolutionEnvironmentV1
    acquisition_budgets: PackageAcquisitionBudgetV1
    inspection_budgets: PackageInspectionBudgetV1
    closure_budgets: PackageClosureBudgetV1
    root_store_identity: str
    dependency_store_identity: str
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    recovery_identity: str
    runtime_version: str
    runtime_protocol_epoch: int
    _workspace_identity: tuple[int, int] = field(init=False, repr=False)
    _state_root_identity: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            getattr(self.management, "_desired_state", None) is not self.desired_state
            or self.management.gc_gate is not self.gc_gate
            or self.desired_state.gc_gate is not self.gc_gate
            or not isinstance(self.epoch_runtime, PackageProductPosixFencedRuntimeOwner)
        ):
            raise ValueError("Package Product owners are not bound")
        self.epoch_runtime.assert_current()
        if (
            not isinstance(self.workspace, Path)
            or not self.workspace.is_absolute()
            or self.workspace != self.workspace.resolve(strict=True)
        ):
            raise ValueError("Package Product workspace is not canonical")
        metadata = self.workspace.stat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("Package Product workspace is not a directory")
        object.__setattr__(
            self, "_workspace_identity", (metadata.st_dev, metadata.st_ino)
        )
        state_identity = _directory_identity(self.state_root)
        if state_identity is None:
            raise ValueError("Package Product state root is unsafe")
        object.__setattr__(self, "_state_root_identity", state_identity)
        self.epoch_runtime.assert_current()

    def factory_for_session(
        self, *, session_id: str, cwd: Path, runtime_id: str
    ) -> PosixLocalWheelProductRuntimeFactory:
        """Register a live lease and transfer it to a one-shot Session factory."""

        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Package Product Session identity is required")
        if not isinstance(cwd, Path) or cwd.resolve(strict=True) != self.workspace:
            raise ValueError("Package Product Session workspace changed")
        if self._current_workspace_identity() != self._workspace_identity:
            raise ValueError("Package Product workspace identity changed")
        self.assert_root_gc_authority_current()
        lease = self.epoch_runtime.issue_runtime_lease(
            runtime_id=runtime_id,
            runtime_version=self.runtime_version,
            runtime_protocol_epoch=self.runtime_protocol_epoch,
        )
        try:
            factory = PosixLocalWheelProductRuntimeFactory(
                expected_session_id=session_id,
                expected_cwd=self.workspace,
                state_root=self.state_root,
                plugin_store_root=self.plugin_store_root,
                policy=self.policy,
                environment=self.environment,
                acquisition_budgets=self.acquisition_budgets,
                inspection_budgets=self.inspection_budgets,
                closure_budgets=self.closure_budgets,
                root_store_identity=self.root_store_identity,
                dependency_store_identity=self.dependency_store_identity,
                runtime_lease=lease,
                cutover_result=self.epoch_runtime.cutover_result,
                epoch_runtime=self.epoch_runtime,
                management=self.management,
                desired_state=self.desired_state,
                gc_bindings=self.gc_bindings,
                gc_gate=self.gc_gate,
                actor_id=self.actor_id,
                desired_policy_revision=self.desired_policy_revision,
                recovery_identity=self.recovery_identity,
            )
            if self._current_workspace_identity() != self._workspace_identity:
                raise ValueError("Package Product workspace identity changed")
            self.assert_root_gc_authority_current()
            return factory
        except BaseException:
            lease.release()
            raise

    def settled_install_command_id(
        self, *, operation_id: str, plugin_id: str
    ) -> str | None:
        """Read the exact Product handoff for a completed install retry."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package Product operation id is required")
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Package Product Plugin id is required")
        self.epoch_runtime.assert_current()
        state_identity = self._state_root_identity
        if _directory_identity(self.state_root) != state_identity:
            raise ValueError("Package Product state root changed")
        journal = PackageRetentionHandoffJournal(self.state_root / "handoff.jsonl")
        receipts = tuple(
            record.receipt
            for record in journal.records()
            if record.receipt is not None
            and record.receipt.request.operation_id == operation_id
        )
        if _directory_identity(self.state_root) != state_identity:
            raise ValueError("Package Product state root changed during handoff read")
        self.epoch_runtime.assert_current()
        if not receipts:
            return None
        if len({receipt.request.handoff_id for receipt in receipts}) != 1:
            raise ValueError("Package Product operation has multiple handoffs")
        latest = receipts[-1]
        desired = latest.request.desired_request
        if (
            latest.state != "settled"
            or latest.desired_receipt is None
            or desired.product_id != self.policy.product_id
            or desired.scope_id != self.policy.project_scope_id
            or desired.plugin_id != plugin_id
            or journal.current(latest.request.handoff_id) != latest
        ):
            raise ValueError("Package Product install handoff is not settled")
        if _directory_identity(self.state_root) != state_identity:
            raise ValueError("Package Product state root changed during handoff read")
        self.epoch_runtime.assert_current()
        return desired.command_id

    def assert_root_gc_authority_current(self) -> None:
        """Require the same fenced Product, workspace, state, and Store roots."""

        self.epoch_runtime.assert_current()
        if self._current_workspace_identity() != self._workspace_identity:
            raise ValueError("Package Product workspace identity changed")
        if _directory_identity(self.state_root) != self._state_root_identity:
            raise ValueError("Package Product state root changed")
        fence = self.epoch_runtime.cutover_result.fence
        if (
            fence is None
            or _directory_identity(self.plugin_store_root) != fence.fenced_root_identity
        ):
            raise ValueError("Package Product fenced Store root changed")
        self.epoch_runtime.assert_current()

    @contextmanager
    def pinned_state_root_gc_read(self) -> Iterator[int]:
        """Read GC debt from the original Product state directory, not a path swap."""

        self.assert_root_gc_authority_current()
        descriptor = os.open(
            self.state_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            if (
                _private_directory_identity(os.fstat(descriptor))
                != self._state_root_identity
            ):
                raise ValueError("Package Product state root descriptor changed")
            self.assert_root_gc_authority_current()
            yield descriptor
            if (
                _private_directory_identity(os.fstat(descriptor))
                != self._state_root_identity
            ):
                raise ValueError("Package Product state root descriptor changed")
            self.assert_root_gc_authority_current()
        finally:
            os.close(descriptor)

    @property
    def dependency_store_root(self) -> Path:
        return self.state_root / "dependency-store"

    def _current_workspace_identity(self) -> tuple[int, int] | None:
        try:
            metadata = self.workspace.lstat()
        except OSError:
            return None
        if not stat.S_ISDIR(metadata.st_mode):
            return None
        return metadata.st_dev, metadata.st_ino


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
    epoch_runtime: PackageProductPosixFencedRuntimeOwner | None = None
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
        if self.epoch_runtime is not None:
            if (
                not isinstance(
                    self.epoch_runtime, PackageProductPosixFencedRuntimeOwner
                )
                or self.epoch_runtime.registry is not self.runtime_lease.registry
                or self.epoch_runtime.cutover_result != self.cutover_result
            ):
                raise ValueError("Package Product epoch owner changed")
            self.epoch_runtime.assert_current()
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
        if self.epoch_runtime is not None:
            self.epoch_runtime.assert_current()
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
            if self.epoch_runtime is not None:
                self.epoch_runtime.assert_current()
            bound = replace(
                binding,
                session_id=request.session_id,
                product_runtime_id=admission_request.runtime_id,
                on_dispose=self.runtime_lease.release,
            )
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

    def assert_workspace_current(self) -> None:
        """Recheck the workspace identity captured for this Product Session."""

        if self._current_cwd_identity() != self._cwd_identity:
            raise ValueError("Package Product Session workspace identity changed")
        if self.epoch_runtime is not None:
            self.epoch_runtime.assert_current()


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowsLocalWheelProductSessionOwner:
    """Issue a Session factory from the current Windows Product fence."""

    workspace: Path
    policy: PackageProductLocalWheelPolicy
    host_inputs: PosixLocalWheelProductHostInputs
    root_store_identity: str
    dependency_store_identity: str
    epoch_runtime: PackageProductWindowsFencedRuntimeOwner
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    recovery_identity: str
    runtime_version: str
    runtime_protocol_epoch: int
    _workspace_identities: tuple[tuple[int, int], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Package Product Session owner is unavailable")
        if (
            not isinstance(self.epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
            or getattr(self.management, "_desired_state", None)
            is not self.desired_state
            or self.management.gc_gate is not self.gc_gate
            or self.desired_state.gc_gate is not self.gc_gate
        ):
            raise ValueError("Windows Package Product owners are not bound")
        self.epoch_runtime.assert_current()
        object.__setattr__(
            self, "_workspace_identities", _windows_workspace_identities(self.workspace)
        )
        self.epoch_runtime.assert_current()

    @property
    def state_root(self) -> Path:
        return self.epoch_runtime.prepare_product_state_root()

    @property
    def plugin_store_root(self) -> Path:
        return self.epoch_runtime.selected_store_root()

    @property
    def dependency_store_root(self) -> Path:
        return self.epoch_runtime.prepare_product_dependency_root()

    def assert_root_gc_authority_current(self) -> None:
        self.epoch_runtime.assert_current()
        if _windows_workspace_identities(self.workspace) != self._workspace_identities:
            raise ValueError("Windows Package Product workspace changed")
        self.epoch_runtime.prepare_product_state_root()
        self.epoch_runtime.prepare_product_dependency_root()
        self.epoch_runtime.selected_store_root()
        self.epoch_runtime.assert_current()

    def assert_private_data_read_authority_current(self) -> None:
        """Recheck the selected Windows Product without preparing absent roots."""

        self.epoch_runtime.assert_current()
        if _windows_workspace_identities(self.workspace) != self._workspace_identities:
            raise ValueError("Windows Package Product workspace changed")
        inspect_windows_product_private_directory_identity(
            self.epoch_runtime.control_root / "product-state"
        )
        self.epoch_runtime.selected_store_root()
        self.epoch_runtime.assert_current()

    def assert_session_runtime_current(
        self, runtime: PackageProductRuntimeBindingV1
    ) -> None:
        """Require a live Session binding from this exact Windows Product graph."""

        if type(runtime) is not PackageProductRuntimeBindingV1:
            raise ValueError("Windows Product Session runtime is invalid")
        reader = runtime._selected_manifest_reader
        root_reader = runtime._selected_root_reader
        lease = getattr(runtime.on_dispose, "__self__", None)
        if (
            runtime.product_id != self.policy.product_id
            or not runtime.lifecycle.active
            or type(reader) is not _LocalWheelSelectedManifestReader
            or reader.read_only
            or reader.policy is not self.policy
            or reader.root_reader is not root_reader
            or root_reader is None
            or root_reader.desired_state is not self.desired_state
            or root_reader.bindings is not self.gc_bindings
            or root_reader.gc_gate is not self.gc_gate
            or getattr(lease, "registry", None) is not self.epoch_runtime.registry
        ):
            raise ValueError("Windows Product Session runtime changed owner")
        self.assert_root_gc_authority_current()

    def factory_for_session(
        self, *, session_id: str, cwd: Path, runtime_id: str
    ) -> WindowsLocalWheelProductRuntimeFactory:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Package Product Session identity is required")
        if cwd != self.workspace or (
            _windows_workspace_identities(cwd) != self._workspace_identities
        ):
            raise ValueError("Package Product Session workspace changed")
        lease = self.epoch_runtime.issue_runtime_lease(
            runtime_id=runtime_id,
            runtime_version=self.runtime_version,
            runtime_protocol_epoch=self.runtime_protocol_epoch,
        )
        try:
            factory = WindowsLocalWheelProductRuntimeFactory(
                expected_session_id=session_id,
                expected_cwd=self.workspace,
                expected_workspace_identities=self._workspace_identities,
                policy=self.policy,
                host_inputs=self.host_inputs,
                root_store_identity=self.root_store_identity,
                dependency_store_identity=self.dependency_store_identity,
                runtime_lease=lease,
                epoch_runtime=self.epoch_runtime,
                management=self.management,
                desired_state=self.desired_state,
                gc_bindings=self.gc_bindings,
                gc_gate=self.gc_gate,
                actor_id=self.actor_id,
                desired_policy_revision=self.desired_policy_revision,
                recovery_identity=self.recovery_identity,
            )
            if _windows_workspace_identities(cwd) != self._workspace_identities:
                raise ValueError("Package Product workspace changed")
            self.epoch_runtime.assert_current()
            return factory
        except BaseException:
            lease.release()
            raise

    def settled_install_command_id(
        self, *, operation_id: str, plugin_id: str
    ) -> str | None:
        """Read one settled Windows Product install handoff."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package Product operation id is required")
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Package Product Plugin id is required")
        self.epoch_runtime.assert_current()
        state_root = self.epoch_runtime.prepare_product_state_root()
        journal = PackageRetentionHandoffJournal(state_root / "handoff.jsonl")
        receipts = tuple(
            record.receipt
            for record in journal.records()
            if record.receipt is not None
            and record.receipt.request.operation_id == operation_id
        )
        self.epoch_runtime.assert_current()
        if not receipts:
            return None
        if len({receipt.request.handoff_id for receipt in receipts}) != 1:
            raise ValueError("Package Product operation has multiple handoffs")
        latest = receipts[-1]
        desired = latest.request.desired_request
        if (
            latest.state != "settled"
            or latest.desired_receipt is None
            or desired.product_id != self.policy.product_id
            or desired.scope_id != self.policy.project_scope_id
            or desired.plugin_id != plugin_id
            or journal.current(latest.request.handoff_id) != latest
        ):
            raise ValueError("Package Product install handoff is not settled")
        self.epoch_runtime.assert_current()
        return desired.command_id


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowsLocalWheelProductRuntimeFactory:
    """Transfer one Windows runtime lease to one Product Session binding."""

    expected_session_id: str
    expected_cwd: Path
    expected_workspace_identities: tuple[tuple[int, int], ...]
    policy: PackageProductLocalWheelPolicy
    host_inputs: PosixLocalWheelProductHostInputs
    root_store_identity: str
    dependency_store_identity: str
    runtime_lease: PackageWindowsProductRuntimeLease
    epoch_runtime: PackageProductWindowsFencedRuntimeOwner
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    recovery_identity: str
    _create_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _create_started: bool = field(default=False, init=False, repr=False)
    _binding_issued: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            os.name != "nt"
            or not isinstance(self.runtime_lease, PackageWindowsProductRuntimeLease)
            or self.runtime_lease.registry is not self.epoch_runtime.registry
            or not isinstance(self.expected_session_id, str)
            or not self.expected_session_id
            or _windows_workspace_identities(self.expected_cwd)
            != self.expected_workspace_identities
        ):
            raise ValueError("Windows Package Product Session factory is invalid")
        self.epoch_runtime.assert_current()

    def assert_workspace_current(self) -> None:
        """Recheck the Windows directory chain captured for this Session."""

        if (
            _windows_workspace_identities(self.expected_cwd)
            != self.expected_workspace_identities
        ):
            raise ValueError(
                "Windows Package Product Session workspace identity changed"
            )
        self.epoch_runtime.assert_current()

    def create(
        self, request: PackageProductRuntimeRequestV1
    ) -> PackageProductRuntimeBindingV1:
        if not isinstance(request, PackageProductRuntimeRequestV1):
            raise TypeError("Package Product runtime request is required")
        if (
            request.product_id != self.policy.product_id
            or request.session_id != self.expected_session_id
            or request.cwd != str(self.expected_cwd)
            or _windows_workspace_identities(self.expected_cwd)
            != self.expected_workspace_identities
        ):
            raise ValueError("Package Product Session or workspace identity changed")
        self.epoch_runtime.assert_current()
        with self._create_lock:
            if self._create_started:
                raise ValueError("Package Product runtime factory already used")
            object.__setattr__(self, "_create_started", True)
            host = self.host_inputs
            binding = compose_windows_local_wheel_product(
                epoch_runtime=self.epoch_runtime,
                policy=self.policy,
                environment=host.environment,
                acquisition_budgets=host.acquisition_budgets,
                inspection_budgets=host.inspection_budgets,
                closure_budgets=host.closure_budgets,
                root_store_identity=self.root_store_identity,
                dependency_store_identity=self.dependency_store_identity,
                admission_request=self.runtime_lease.admission_request,
                management=self.management,
                desired_state=self.desired_state,
                gc_bindings=self.gc_bindings,
                gc_gate=self.gc_gate,
                actor_id=self.actor_id,
                desired_policy_revision=self.desired_policy_revision,
                recovery_identity=self.recovery_identity,
            )
            if (
                _windows_workspace_identities(self.expected_cwd)
                != self.expected_workspace_identities
            ):
                raise ValueError("Package Product workspace changed during composition")
            self.epoch_runtime.assert_current()
            bound = replace(
                binding,
                session_id=request.session_id,
                product_runtime_id=self.runtime_lease.admission_request.runtime_id,
                on_dispose=self.runtime_lease.release,
            )
            object.__setattr__(self, "_binding_issued", True)
            return bound

    def dispose_unbound_runtime(self) -> None:
        with self._create_lock:
            if self._binding_issued:
                return
            object.__setattr__(self, "_create_started", True)
            self.runtime_lease.release()


def _windows_workspace_identities(path: Path) -> tuple[tuple[int, int], ...]:
    if (
        os.name != "nt"
        or not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or path != path.resolve(strict=True)
    ):
        raise ValueError("Windows Package Product workspace is not canonical")
    pinned = _PinnedWindowsAuthority.open(path)
    try:
        pinned.assert_visible()
        return pinned.identities
    finally:
        pinned.close()


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
        return _private_directory_identity(os.fstat(fd))
    except OSError:
        return None
    finally:
        os.close(fd)


def _private_directory_identity(metadata: os.stat_result) -> str | None:
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


__all__ = [
    "PackageProductSelectedPluginManifestV1",
    "PosixLocalWheelProductHostInputs",
    "PosixLocalWheelProductSessionOwner",
    "PosixLocalWheelProductRuntimeFactory",
    "compose_posix_local_wheel_product",
]
