"""PLC9A2 adapters from Package handoff records to Plugin management owners."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from loushang.harness.plugin_management.gc_fence import (
    PluginPackageGcReferenceGatePort,
    gc_reference_guard,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
    PluginPackageGcBindingV1,
    PluginPackageGcClaimV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginInstallationScope,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
    PluginManagementUpdateCommandV2,
    PluginUpdateOperationEventV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetGcTombstoneV1,
    PackageCommittedSetJournal,
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
    PackageDesiredStateCommitResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreGcTombstoneV1,
    PackageStoreSettlementJournal,
    PackageStoreSettlementRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackageVerifiedTreeManifestV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION = 1


class PluginManagementCommandSubmitPort(Protocol):
    """Narrow command surface retained by the Package desired adapter."""

    @property
    def gc_gate(self) -> PluginPackageGcReferenceGatePort | None: ...

    def submit(
        self,
        command: PluginManagementCommandV1 | PluginManagementUpdateCommandV2,
    ) -> PluginManagementOperationEventV1 | PluginUpdateOperationEventV2: ...


class PackageProductDesiredRevisionProjectionPort(Protocol):
    """Resolve owner evidence omitted from the capability-poor handoff record."""

    def project(
        self,
        request: PackageDesiredStateCommitRequestV1,
    ) -> PluginPackageRevisionRefV1: ...

    def inventory_revision(self) -> int: ...


class PackageProductGcBindingPort(Protocol):
    def records(self) -> tuple[PluginPackageGcBindingV1, ...]: ...

    def claims(self) -> tuple[PluginPackageGcClaimV1, ...]: ...

    def prepare(
        self,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> PluginPackageGcClaimV1: ...

    def record(
        self,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
        transition: PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2,
    ) -> object: ...


class PackageProductGcAdmissionError(RuntimeError):
    code = "package_product_gc_root_reserved"


@dataclass(frozen=True, slots=True)
class CommittedSetPackageRevisionProjection:
    """Project one exact committed Package root into Product desired evidence."""

    desired_state: PluginDesiredStateLedger
    committed_sets: PackageCommittedSetJournal

    def __post_init__(self) -> None:
        if not isinstance(self.desired_state, PluginDesiredStateLedger):
            raise TypeError("Product desired-state ledger is required")
        if not isinstance(self.committed_sets, PackageCommittedSetJournal):
            raise TypeError("Package committed-set journal is required")

    def project(
        self, request: PackageDesiredStateCommitRequestV1
    ) -> PluginPackageRevisionRefV1:
        if not isinstance(request, PackageDesiredStateCommitRequestV1):
            raise TypeError("Package desired-state commit request is required")
        record = self.committed_sets.current(request.operation_id)
        if record is None:
            raise ValueError("Package desired revision lacks a committed set")
        return _project_committed_record(
            request,
            record,
            root_tombstoned=self.committed_sets.is_tombstoned(
                record.committed_set.root_ref.ref_id
            ),
        )

    def inventory_revision(self) -> int:
        return self.desired_state.snapshot().inventory_revision


def _project_committed_record(
    request: PackageDesiredStateCommitRequestV1,
    record: PackageCommittedSetRecordV1,
    *,
    root_tombstoned: bool,
) -> PluginPackageRevisionRefV1:
    """Pure projection shared by runtime admission and inert inspection."""

    if not isinstance(request, PackageDesiredStateCommitRequestV1):
        raise TypeError("Package desired-state commit request is required")
    if not isinstance(record, PackageCommittedSetRecordV1):
        raise TypeError("Package committed-set record is required")
    committed = record.committed_set
    closure = record.closure_lock
    if (
            committed.operation_id != request.operation_id
            or committed.request_fingerprint != request.request_fingerprint
            or committed.attempt_epoch != request.attempt_epoch
            or committed.product_id != request.product_id
            or committed.scope_id != request.scope_id
            or committed.installation_id != request.installation_id
            or committed.plugin_id != request.plugin_id
            or committed.set_id != request.committed_set_id
            or committed.root_ref != request.root_ref
            or committed.closure_lock_digest != closure.lock_digest
            or root_tombstoned
    ):
        raise ValueError("Package desired revision changed committed set")
    root = next(
        node for node in closure.nodes if node.node_id == closure.root_node_id
    )
    if (
            root.plan_node.role != "root"
            or not isinstance(root.stable_ref, PluginRevisionRefV1)
            or root.stable_ref != request.root_ref
    ):
        raise ValueError("Package desired revision changed committed set root")
    return PluginPackageRevisionRefV1(
        plugin_id=committed.plugin_id,
        plugin_version=committed.root_ref.version,
        package_content_digest=committed.root_ref.artifact_digest,
        dependency_lock_digest=closure.lock_digest,
        package_source_identity=root.plan_node.canonical_source_identity,
    )


@dataclass(frozen=True, slots=True)
class PluginManagementPackageDesiredStateAdapter:
    """Commit an admitted PLC9B root through the sole management service."""

    management: PluginManagementCommandSubmitPort
    revisions: PackageProductDesiredRevisionProjectionPort
    installation_scope: PluginInstallationScope
    actor_id: str
    policy_revision: str
    approval_reference: str | None = None
    gc_bindings: PackageProductGcBindingPort | None = None
    gc_gate: PluginPackageGcReferenceGatePort | None = None
    lifecycle_journal: PackageLifecycleJournal | None = None
    desired_state: PluginDesiredStateLedger | None = None
    owner_identity: str = "plugin-management-service"
    adapter_version: int = PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if not callable(getattr(self.management, "submit", None)):
            raise TypeError("Plugin management command owner is required")
        if not all(
            callable(getattr(self.revisions, method, None))
            for method in ("project", "inventory_revision")
        ):
            raise TypeError("Package desired revision projector is required")
        if self.gc_bindings is not None:
            if not all(
                callable(getattr(self.gc_bindings, method, None))
                for method in ("records", "claims", "prepare", "record")
            ):
                raise TypeError("Package GC binding journal is required")
            if not callable(getattr(self.gc_gate, "guard", None)):
                raise TypeError("Package GC binding requires the shared reference gate")
            if getattr(self.management, "gc_gate", None) is not self.gc_gate:
                raise ValueError("Package GC adapter and management gate differ")
        elif self.gc_gate is not None:
            raise ValueError("Package GC reference gate requires the binding journal")
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Unsupported Package Product installation scope")
        if self.lifecycle_journal is not None and not isinstance(
            self.lifecycle_journal, PackageLifecycleJournal
        ):
            raise TypeError("Package Product lifecycle journal is invalid")
        if self.desired_state is not None and not isinstance(
            self.desired_state, PluginDesiredStateLedger
        ):
            raise TypeError("Package Product desired state is invalid")
        for value, name in (
            (self.actor_id, "Package Product actor id"),
            (self.policy_revision, "Package Product policy revision"),
            (self.owner_identity, "Package Product desired owner identity"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.adapter_version != PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION:
            raise ValueError("Unsupported Package Product desired adapter")

    def commit(
        self,
        request: PackageDesiredStateCommitRequestV1,
    ) -> PackageDesiredStateCommitResultV1:
        if not isinstance(request, PackageDesiredStateCommitRequestV1):
            raise TypeError("Package desired-state commit request is required")
        with gc_reference_guard(self.gc_gate) as reserved:
            return self._commit_guarded(request, reserved=reserved)

    def _commit_guarded(
        self,
        request: PackageDesiredStateCommitRequestV1,
        *,
        reserved: frozenset[PluginPackageRevisionRefV1],
    ) -> PackageDesiredStateCommitResultV1:
        package_revision = self.revisions.project(request)
        if not isinstance(package_revision, PluginPackageRevisionRefV1):
            raise TypeError(
                "Package desired revision projector returned invalid evidence"
            )
        if (
            package_revision.plugin_id != request.plugin_id
            or package_revision.plugin_version != request.root_ref.version
            or package_revision.package_content_digest
            != request.root_ref.artifact_digest
        ):
            raise ValueError("Package desired revision evidence changed")
        if self.gc_bindings is not None and (
            package_revision in reserved
            or any(
                binding.package_revision in reserved
                and binding.request.root_ref.ref_id == request.root_ref.ref_id
                for binding in self.gc_bindings.records()
            )
            or any(
                claim.package_revision in reserved
                and claim.request.root_ref.ref_id == request.root_ref.ref_id
                for claim in self.gc_bindings.claims()
            )
        ):
            raise PackageProductGcAdmissionError("Package root is reserved for GC")
        if self.gc_bindings is not None:
            self.gc_bindings.prepare(request, package_revision)
        if self.lifecycle_journal is not None:
            lifecycle_request = self.lifecycle_journal.request(request.operation_id)
            if (
                not isinstance(lifecycle_request, PackageLifecycleRequestV2)
                or lifecycle_request.request_fingerprint != request.request_fingerprint
            ):
                raise ValueError("Product desired handoff changed Package request")
            if lifecycle_request.action == "update":
                return self._commit_update(request, package_revision)
            if lifecycle_request.action != "install":
                raise ValueError("Product desired handoff action is unsupported")
        command = PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id=request.command_id,
                idempotency_key=request.desired_request_id,
                expected_inventory_revision=request.expected_inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id=request.product_id,
                    installation_scope=self.installation_scope,
                    scope_id=request.scope_id,
                    plugin_id=request.plugin_id,
                ),
                desired_state="installed_disabled",
                package_revision=package_revision,
                actor_id=self.actor_id,
                policy_revision=self.policy_revision,
                approval_reference=self.approval_reference,
            ),
        )
        event = self.management.submit(command)
        if not isinstance(event, PluginManagementOperationEventV1):
            raise TypeError("Plugin management owner returned an invalid operation")
        if event.status != "terminal" or event.result is None:
            raise RuntimeError("Plugin management desired operation is not terminal")
        if event.result.disposition == "succeeded":
            transition = event.result.transition
            if (
                not isinstance(transition, PluginDesiredStateTransitionV1)
                or transition.inventory_revision
                != request.expected_inventory_revision + 1
            ):
                raise RuntimeError("Plugin management desired receipt changed")
            if self.gc_bindings is not None:
                self.gc_bindings.record(request, package_revision, transition)
            return PackageDesiredStateCommitResultV1.committed(
                request,
                owner_identity=self.owner_identity,
                owner_revision=event.journal_revision,
            )
        if event.result.error_code == "plugin_inventory_revision_conflict":
            return PackageDesiredStateCommitResultV1.rejected(
                request,
                observed_inventory_revision=_observed_inventory_revision(
                    self.revisions,
                    request,
                ),
                owner_identity=self.owner_identity,
                owner_revision=event.journal_revision,
            )
        raise RuntimeError(
            "Plugin management desired operation failed: "
            f"{event.result.error_code or 'unknown'}"
        )

    def _commit_update(
        self,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> PackageDesiredStateCommitResultV1:
        desired = self.desired_state
        if desired is None:
            raise ValueError("Product update lacks the desired-state owner")
        key = PluginInstallationKeyV1(
            product_id=request.product_id,
            installation_scope=self.installation_scope,
            scope_id=request.scope_id,
            plugin_id=request.plugin_id,
        )
        snapshot, transitions = desired.capture()
        if snapshot.inventory_revision < request.expected_inventory_revision:
            raise ValueError("Product update expected inventory is unavailable")
        prior = next(
            (
                item.committed_state.selection.package_revision
                for item in reversed(transitions)
                if item.inventory_revision <= request.expected_inventory_revision
                and item.committed_state.installation_key == key
            ),
            None,
        )
        if prior is None:
            raise ValueError("Product update has no predecessor Package revision")
        event = self.management.submit(
            PluginManagementUpdateCommandV2(
                operation_id=request.command_id,
                idempotency_key=request.desired_request_id,
                expected_inventory_revision=request.expected_inventory_revision,
                installation_key=key,
                expected_package_revision=prior,
                staged_package_revision=package_revision,
                actor_id=self.actor_id,
                policy_revision=self.policy_revision,
                approval_reference=self.approval_reference,
            )
        )
        if not isinstance(event, PluginUpdateOperationEventV2):
            raise TypeError("Plugin update owner returned incompatible evidence")
        terminal = event.result
        if event.status != "terminal" or terminal is None:
            raise RuntimeError("Plugin update desired operation is not terminal")
        if terminal.disposition in {"succeeded", "restart_required"}:
            transition = terminal.transition
            if (
                not isinstance(transition, PluginDesiredStateUpdateTransitionV2)
                or transition.inventory_revision != request.expected_inventory_revision + 1
            ):
                raise RuntimeError("Plugin update desired receipt changed")
            if self.gc_bindings is not None:
                self.gc_bindings.record(request, package_revision, transition)
            return PackageDesiredStateCommitResultV1.committed(
                request,
                owner_identity=self.owner_identity,
                owner_revision=event.journal_revision,
            )
        if terminal.error_code == "plugin_inventory_revision_conflict":
            return PackageDesiredStateCommitResultV1.rejected(
                request,
                observed_inventory_revision=_observed_inventory_revision(
                    self.revisions, request
                ),
                owner_identity=self.owner_identity,
                owner_revision=event.journal_revision,
            )
        raise RuntimeError(
            "Plugin update desired operation failed: "
            f"{terminal.error_code or 'unknown'}"
        )


class PackageProductRuntimeReadError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductSelectedRootSnapshotV1:
    """Complete Store-pathless bytes from one admitted Product selection.

    This is inert data evidence, not a lease or permission to execute. The
    Product reader constructs it only after checking live selection and Store.
    """

    installation_key: PluginInstallationKeyV1
    package_revision: PluginPackageRevisionRefV1
    instance_revision_ref: PluginInstanceRevisionRef
    committed_record: PackageCommittedSetRecordV1
    root_ref: PluginRevisionRefV1
    manifest: PackageVerifiedTreeManifestV1
    files: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.installation_key, PluginInstallationKeyV1):
            raise TypeError("Selected root requires a Product installation key")
        if not isinstance(self.package_revision, PluginPackageRevisionRefV1):
            raise TypeError("Selected root requires a Product package revision")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Selected root requires a Product Instance revision")
        if not isinstance(self.committed_record, PackageCommittedSetRecordV1):
            raise TypeError("Selected root requires a committed Package set")
        if not isinstance(self.root_ref, PluginRevisionRefV1):
            raise TypeError("Selected root requires a Store root ref")
        if not isinstance(self.manifest, PackageVerifiedTreeManifestV1):
            raise TypeError("Selected root requires a verified tree manifest")
        committed = self.committed_record.committed_set
        root_node = next(
            node
            for node in self.committed_record.closure_lock.nodes
            if node.node_id == self.committed_record.closure_lock.root_node_id
        )
        if (
            self.installation_key.plugin_id != self.root_ref.plugin_id
            or self.instance_revision_ref.plugin_id != self.root_ref.plugin_id
            or self.installation_key.product_id != committed.product_id
            or self.installation_key.scope_id != committed.scope_id
            or committed.plugin_id != self.root_ref.plugin_id
            or committed.root_ref != self.root_ref
            or self.package_revision.plugin_id != self.root_ref.plugin_id
            or self.package_revision.plugin_version != self.root_ref.version
            or self.package_revision.package_content_digest
            != self.root_ref.artifact_digest
            or self.package_revision.dependency_lock_digest
            != committed.closure_lock_digest
            or self.package_revision.package_source_identity
            != root_node.plan_node.canonical_source_identity
            or self.root_ref.artifact_digest != self.manifest.artifact_digest
            or self.root_ref.extraction_tree_digest
            != self.manifest.extraction_tree_digest
            or committed.operation_id != self.manifest.operation_id
            or committed.attempt_epoch != self.manifest.attempt_epoch
        ):
            raise ValueError("Selected Product revision and Store root changed")
        if (
            not isinstance(self.files, tuple)
            or len(self.files) != len(self.manifest.entries)
        ):
            raise ValueError("Selected Store snapshot is incomplete")
        for item, entry in zip(self.files, self.manifest.entries, strict=True):
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or item[0] != entry.logical_path
                or not isinstance(item[1], bytes)
                or len(item[1]) != entry.byte_count
                or sha256(item[1]).hexdigest() != entry.content_digest
            ):
                raise ValueError("Selected Store snapshot member changed")


class PackageProductRootStoreReadPort(Protocol):
    def read_root_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes: ...


class PackageProductDependencyStoreReadPort(Protocol):
    read_only: bool

    def read_dependency_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]: ...


@dataclass(frozen=True, slots=True)
class PackageProductSelectedRootReader:
    """Join a live Product selection to one exact, Store-verified root member.

    The GC gate is held through the physical read so a concurrent writer cannot
    remove the selected revision between logical admission and byte delivery.
    This owner returns data only; it grants no execution or runtime lease.
    """

    product_id: str
    scope_id: str
    installation_scope: PluginInstallationScope
    desired_state: PluginDesiredStateLedger
    bindings: PluginPackageGcBindingJournal
    committed_sets: PackageCommittedSetJournal
    root_settlements: PackageStoreSettlementJournal
    root_store: PackageProductRootStoreReadPort
    gc_gate: PluginPackageGcReferenceGatePort

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_id, str)
            or not self.product_id
            or not isinstance(self.scope_id, str)
            or not self.scope_id
            or self.installation_scope not in {"process", "tenant", "workspace"}
        ):
            raise ValueError("Product selected-root scope is invalid")
        for value, expected, name in (
            (self.desired_state, PluginDesiredStateLedger, "desired-state ledger"),
            (self.bindings, PluginPackageGcBindingJournal, "Package crosswalk"),
            (self.committed_sets, PackageCommittedSetJournal, "committed sets"),
            (self.root_settlements, PackageStoreSettlementJournal, "root settlements"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"Product {name} is required")
        if not callable(getattr(self.root_store, "read_root_file", None)):
            raise TypeError("Product root Store read owner is required")
        if self.desired_state.gc_gate is not self.gc_gate or not callable(
            getattr(self.gc_gate, "guard", None)
        ):
            raise ValueError("Product root reader requires the desired-state GC gate")

    def read_selected_file(
        self,
        installation_key: PluginInstallationKeyV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        with self.gc_gate.guard() as reserved:
            _, _, _, settlement = self._selected_settlement(installation_key, reserved)
            return self.root_store.read_root_file(
                settlement, logical_path, max_bytes=max_bytes
            )

    def read_selected_files(
        self,
        installation_key: PluginInstallationKeyV1,
        logical_paths: tuple[str, ...],
        *,
        max_total_bytes: int,
    ) -> tuple[bytes, ...]:
        """Read one bounded file set from a single admitted Product selection."""

        if (
            not isinstance(logical_paths, tuple)
            or not logical_paths
            or len(logical_paths) > 64
            or any(not isinstance(path, str) for path in logical_paths)
            or len(set(logical_paths)) != len(logical_paths)
        ):
            raise ValueError("Product selected-root file set is invalid")
        if (
            type(max_total_bytes) is not int
            or max_total_bytes < 0
            or max_total_bytes > 16 * 1024 * 1024
        ):
            raise ValueError("Product selected-root read budget is invalid")
        with self.gc_gate.guard() as reserved:
            _, _, _, settlement = self._selected_settlement(installation_key, reserved)
            members = {
                entry.logical_path: entry for entry in settlement.manifest.entries
            }
            if (
                any(path not in members for path in logical_paths)
                or sum(members[path].byte_count for path in logical_paths)
                > max_total_bytes
            ):
                raise self._error(
                    "Selected root file set is unavailable or exceeds budget",
                    "package_product_root_file_unavailable",
                )
            return self._read_settlement_members(
                settlement,
                tuple((path, members[path].byte_count) for path in logical_paths),
            )

    def capture_selected_root(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedRootSnapshotV1:
        """Capture every verified root member under one Product/GC admission."""

        if type(max_files) is not int or not 1 <= max_files <= 64:
            raise ValueError("Product selected-root file budget is invalid")
        if (
            type(max_total_bytes) is not int
            or not 0 <= max_total_bytes <= 16 * 1024 * 1024
        ):
            raise ValueError("Product selected-root byte budget is invalid")
        with self.gc_gate.guard() as reserved:
            (
                package_revision,
                instance_revision_ref,
                committed_record,
                settlement,
            ) = self._selected_settlement(installation_key, reserved)
            root_ref = settlement.receipt.stable_ref
            if not isinstance(root_ref, PluginRevisionRefV1):
                raise self._error(
                    "Selected Store root has the wrong role",
                    "package_product_root_unavailable",
                )
            entries = settlement.manifest.entries
            if (
                len(entries) > max_files
                or settlement.manifest.total_byte_count > max_total_bytes
            ):
                raise self._error(
                    "Selected Store root exceeds capture budget",
                    "package_product_root_capture_budget_exceeded",
                )
            files = tuple(
                zip(
                    (entry.logical_path for entry in entries),
                    self._read_settlement_members(
                        settlement,
                        tuple(
                            (entry.logical_path, entry.byte_count) for entry in entries
                        ),
                    ),
                    strict=True,
                )
            )
            return PackageProductSelectedRootSnapshotV1(
                installation_key=installation_key,
                package_revision=package_revision,
                instance_revision_ref=instance_revision_ref,
                committed_record=committed_record,
                root_ref=root_ref,
                manifest=settlement.manifest,
                files=files,
            )

    def capture_selected_root_read_only(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedRootSnapshotV1:
        """Capture an existing Product selection without owner-state mutation."""

        if type(max_files) is not int or not 1 <= max_files <= 64:
            raise ValueError("Product selected-root file budget is invalid")
        if (
            type(max_total_bytes) is not int
            or not 0 <= max_total_bytes <= 16 * 1024 * 1024
        ):
            raise ValueError("Product selected-root byte budget is invalid")
        read_guard = getattr(self.gc_gate, "read_guard", None)
        if not callable(read_guard) or getattr(self.root_store, "read_only", False) is not True:
            raise TypeError("Product read-only owners are required")
        with read_guard() as reserved:
            (
                package_revision,
                instance_revision_ref,
                committed_record,
                settlement,
            ) = self._selected_settlement(
                installation_key, reserved, read_only=True
            )
            root_ref = settlement.receipt.stable_ref
            if not isinstance(root_ref, PluginRevisionRefV1):
                raise self._error(
                    "Selected Store root has the wrong role",
                    "package_product_root_unavailable",
                )
            entries = settlement.manifest.entries
            if (
                len(entries) > max_files
                or settlement.manifest.total_byte_count > max_total_bytes
            ):
                raise self._error(
                    "Selected Store root exceeds capture budget",
                    "package_product_root_capture_budget_exceeded",
                )
            files = tuple(
                zip(
                    (entry.logical_path for entry in entries),
                    self._read_settlement_members(
                        settlement,
                        tuple(
                            (entry.logical_path, entry.byte_count) for entry in entries
                        ),
                    ),
                    strict=True,
                )
            )
            return PackageProductSelectedRootSnapshotV1(
                installation_key=installation_key,
                package_revision=package_revision,
                instance_revision_ref=instance_revision_ref,
                committed_record=committed_record,
                root_ref=root_ref,
                manifest=settlement.manifest,
                files=files,
            )

    def assert_selected_root_current(
        self, snapshot: PackageProductSelectedRootSnapshotV1
    ) -> None:
        """Recheck a pinned selection without rereading its Store bytes."""

        if not isinstance(snapshot, PackageProductSelectedRootSnapshotV1):
            raise TypeError("Product selected-root snapshot is required")
        with self.gc_gate.guard() as reserved:
            package_revision, instance_revision_ref, committed_record, settlement = (
                self._selected_settlement(snapshot.installation_key, reserved)
            )
            if (
                package_revision != snapshot.package_revision
                or instance_revision_ref != snapshot.instance_revision_ref
                or committed_record != snapshot.committed_record
                or settlement.receipt.stable_ref != snapshot.root_ref
                or settlement.manifest != snapshot.manifest
            ):
                raise self._error(
                    "Product selected root changed since Session activation",
                    "package_product_root_selection_changed",
                )

    def _read_settlement_members(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        read_many = getattr(self.root_store, "read_root_files", None)
        if callable(read_many):
            return read_many(settlement, members)
        return tuple(
            self.root_store.read_root_file(settlement, path, max_bytes=budget)
            for path, budget in members
        )

    def _selected_settlement(
        self,
        installation_key: PluginInstallationKeyV1,
        reserved: frozenset[PluginPackageRevisionRefV1],
        *,
        read_only: bool = False,
    ) -> tuple[
        PluginPackageRevisionRefV1,
        PluginInstanceRevisionRef,
        PackageCommittedSetRecordV1,
        PackageStoreSettlementRecordV1,
    ]:
        if not isinstance(installation_key, PluginInstallationKeyV1):
            raise TypeError("Exact Product installation key is required")
        if (
            installation_key.product_id != self.product_id
            or installation_key.scope_id != self.scope_id
            or installation_key.installation_scope != self.installation_scope
        ):
            raise self._error(
                "Product Plugin scope changed", "package_product_root_scope_changed"
            )
        snapshot, transitions = (
            self.desired_state.capture_read_only()
            if read_only
            else self.desired_state.capture()
        )
        selection = snapshot.installation(installation_key).selection
        package_revision = selection.package_revision
        if (
            selection.desired_state != "installed_enabled"
            or package_revision is None
            or selection.instance_revision_ref is None
            or package_revision in reserved
        ):
            raise self._error(
                "Product Plugin is not selected", "package_product_root_not_selected"
            )
        provenance = tuple(
            transition
            for transition in transitions
            if transition.committed_state.installation_key == installation_key
            and (
                isinstance(transition, PluginDesiredStateUpdateTransitionV2)
                or (
                    isinstance(transition, PluginDesiredStateTransitionV1)
                    and transition.transition_kind == "install"
                )
            )
        )
        if not provenance:
            raise self._error(
                "Selected root has no Product commit", "package_product_root_unbound"
            )
        selected_commit = provenance[-1]
        selected_command = (
            selected_commit.mutation
            if isinstance(selected_commit, PluginDesiredStateTransitionV1)
            else selected_commit.mutation.command
        )
        matches = tuple(
            binding
            for binding in (
                self.bindings.read_records() if read_only else self.bindings.records()
            )
            if binding.desired_transition_revision == selected_commit.inventory_revision
            and binding.package_revision == package_revision
            and binding.request.command_id == selected_command.operation_id
            and binding.request.desired_request_id
            == selected_command.idempotency_key
            and binding.request.product_id == installation_key.product_id
            and binding.request.scope_id == installation_key.scope_id
            and binding.request.plugin_id == installation_key.plugin_id
        )
        if len(matches) != 1:
            raise self._error(
                "Selected root lacks an exact Product binding",
                "package_product_root_unbound",
            )
        binding = matches[0]
        request = binding.request
        if read_only:
            committed_events = self.committed_sets.read_events()
            committed_record = next(
                (
                    event
                    for event in committed_events
                    if isinstance(event, PackageCommittedSetRecordV1)
                    and event.operation_id == request.operation_id
                ),
                None,
            )
            root_tombstoned = any(
                isinstance(event, PackageCommittedSetGcTombstoneV1)
                and event.root_ref_id == request.root_ref.ref_id
                for event in committed_events
            )
        else:
            committed_record = self.committed_sets.current(request.operation_id)
            root_tombstoned = (
                self.committed_sets.is_tombstoned(request.root_ref.ref_id)
                if committed_record is not None
                else False
            )
        try:
            projected = (
                _project_committed_record(
                    request, committed_record, root_tombstoned=root_tombstoned
                )
                if committed_record is not None
                else None
            )
        except ValueError:
            raise self._error(
                "Selected committed set changed", "package_product_root_stale"
            ) from None
        if (
            projected != package_revision
            or committed_record is None
            or committed_record.committed_set.set_id != request.committed_set_id
            or committed_record.committed_set.root_ref != request.root_ref
            or selected_commit.committed_state.selection.package_revision
            != package_revision
        ):
            raise self._error(
                "Selected committed set changed", "package_product_root_stale"
            )
        settlement_events = (
            self.root_settlements.read_events() if read_only else None
        )
        settlements = tuple(
            settlement
            for settlement in (
                settlement_events
                if settlement_events is not None
                else self.root_settlements.records()
            )
            if isinstance(settlement, PackageStoreSettlementRecordV1)
            if settlement.receipt.stable_ref == request.root_ref
            and settlement.receipt.operation_id == request.operation_id
        )
        root_store_tombstoned = (
            any(
                isinstance(event, PackageStoreGcTombstoneV1)
                and event.stable_ref_id == request.root_ref.ref_id
                for event in settlement_events
            )
            if settlement_events is not None
            else False
        )
        if len(settlements) != 1 or root_store_tombstoned:
            raise self._error(
                "Selected Store root is unavailable",
                "package_product_root_unavailable",
            )
        return (
            package_revision,
            selection.instance_revision_ref,
            committed_record,
            settlements[0],
        )

    @staticmethod
    def _error(message: str, code: str) -> PackageProductRuntimeReadError:
        return PackageProductRuntimeReadError(message, code=code)


@dataclass(frozen=True, slots=True)
class PackageProductSelectedDependencySnapshotV1:
    """Inert, Store-pathless bytes captured for one selected dependency node."""

    installation_key: PluginInstallationKeyV1
    package_revision: PluginPackageRevisionRefV1
    instance_revision_ref: PluginInstanceRevisionRef
    committed_record: PackageCommittedSetRecordV1
    dependency_ref: VerifiedArtifactRefV1
    settlement_id: str
    manifest: PackageVerifiedTreeManifestV1
    files: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_key, PluginInstallationKeyV1)
            or not isinstance(self.package_revision, PluginPackageRevisionRefV1)
            or not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef)
            or not isinstance(self.committed_record, PackageCommittedSetRecordV1)
            or not isinstance(self.dependency_ref, VerifiedArtifactRefV1)
            or not isinstance(self.settlement_id, str)
            or len(self.settlement_id) != 64
            or any(char not in "0123456789abcdef" for char in self.settlement_id)
            or not isinstance(self.manifest, PackageVerifiedTreeManifestV1)
        ):
            raise TypeError("Selected dependency evidence is invalid")
        committed = self.committed_record.committed_set
        nodes = tuple(
            node
            for node in self.committed_record.closure_lock.nodes
            if node.plan_node.role == "dependency"
        )
        if (
            not 1 <= len(nodes) <= 3
            or len(
                tuple(node for node in nodes if node.stable_ref == self.dependency_ref)
            )
            != 1
            or tuple(sorted(node.stable_ref.ref_id for node in nodes))
            != tuple(sorted(ref.ref_id for ref in committed.dependency_refs))
            or self.package_revision.dependency_lock_digest
            != self.committed_record.closure_lock.lock_digest
            or committed.product_id != self.installation_key.product_id
            or committed.scope_id != self.installation_key.scope_id
            or committed.plugin_id != self.installation_key.plugin_id
            or self.package_revision.plugin_id != self.installation_key.plugin_id
            or self.package_revision.plugin_version != committed.root_ref.version
            or self.package_revision.package_content_digest
            != committed.root_ref.artifact_digest
            or self.instance_revision_ref.plugin_id
            != self.installation_key.plugin_id
            or self.dependency_ref.distribution != self.manifest.distribution
            or self.dependency_ref.version != self.manifest.version
            or self.dependency_ref.artifact_digest != self.manifest.artifact_digest
            or self.dependency_ref.extraction_tree_digest
            != self.manifest.extraction_tree_digest
            or not any(
                node.node_id == self.manifest.node_id
                and node.stable_ref == self.dependency_ref
                for node in nodes
            )
            or committed.operation_id != self.manifest.operation_id
            or committed.attempt_epoch != self.manifest.attempt_epoch
            or len(self.files) != len(self.manifest.entries)
        ):
            raise ValueError("Selected dependency changed Product identity")
        for (path, body), entry in zip(
            self.files, self.manifest.entries, strict=True
        ):
            if (
                path != entry.logical_path
                or not isinstance(body, bytes)
                or len(body) != entry.byte_count
                or sha256(body).hexdigest() != entry.content_digest
            ):
                raise ValueError("Selected dependency changed Store bytes")


@dataclass(frozen=True, slots=True)
class PackageProductSelectedDependencyClosureSnapshotV1:
    """One GC-gate-bound closure read, without execution or retention authority."""

    installation_key: PluginInstallationKeyV1
    package_revision: PluginPackageRevisionRefV1
    instance_revision_ref: PluginInstanceRevisionRef
    committed_record: PackageCommittedSetRecordV1
    members: tuple[PackageProductSelectedDependencySnapshotV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_key, PluginInstallationKeyV1)
            or not isinstance(self.package_revision, PluginPackageRevisionRefV1)
            or not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef)
            or not isinstance(self.committed_record, PackageCommittedSetRecordV1)
            or type(self.members) is not tuple
            or not 1 <= len(self.members) <= 3
            or any(
                not isinstance(member, PackageProductSelectedDependencySnapshotV1)
                or member.installation_key != self.installation_key
                or member.package_revision != self.package_revision
                or member.instance_revision_ref != self.instance_revision_ref
                or member.committed_record != self.committed_record
                for member in self.members
            )
        ):
            raise ValueError("Selected dependency closure identity is invalid")
        expected_refs = tuple(
            sorted(
                ref.ref_id
                for ref in self.committed_record.committed_set.dependency_refs
            )
        )
        observed_refs = tuple(sorted(member.dependency_ref.ref_id for member in self.members))
        if expected_refs != observed_refs or tuple(
            member.manifest.node_id for member in self.members
        ) != tuple(sorted(member.manifest.node_id for member in self.members)):
            raise ValueError("Selected dependency closure members changed")


@dataclass(frozen=True, slots=True)
class PackageProductSelectedDependencyReader:
    """Join current Product selection to exact dependency Store bytes.

    The GC read gate spans selection and physical reads. The returned snapshot
    is data evidence only; a Worker execution attempt still needs its own
    retained dependency refs and contained runtime profile.
    """

    root_reader: PackageProductSelectedRootReader
    dependency_settlements: PackageStoreSettlementJournal
    dependency_store: PackageProductDependencyStoreReadPort
    dependency_store_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.root_reader, PackageProductSelectedRootReader):
            raise TypeError("Product selected-root owner is required")
        if not isinstance(self.dependency_settlements, PackageStoreSettlementJournal):
            raise TypeError("Product dependency settlement owner is required")
        if (
            getattr(self.dependency_store, "read_only", False) is not True
            or not callable(getattr(self.dependency_store, "read_dependency_files", None))
        ):
            raise TypeError("Product read-only dependency Store is required")
        if not isinstance(self.dependency_store_identity, str) or not self.dependency_store_identity:
            raise ValueError("Product dependency Store identity is required")

    def capture_selected_dependency(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencySnapshotV1:
        if type(max_files) is not int or not 1 <= max_files <= 16:
            raise ValueError("Product dependency capture file budget is invalid")
        if type(max_total_bytes) is not int or not 0 <= max_total_bytes <= 1024 * 1024:
            raise ValueError("Product dependency capture byte budget is invalid")
        read_guard = getattr(self.root_reader.gc_gate, "read_guard", None)
        if not callable(read_guard):
            raise TypeError("Product read-only GC gate is required")
        with read_guard() as reserved:
            package_revision, instance_revision_ref, committed_record, _ = (
                self.root_reader._selected_settlement(
                    installation_key, reserved, read_only=True
                )
            )
            lock = committed_record.closure_lock
            nodes = tuple(node for node in lock.nodes if node.plan_node.role == "dependency")
            if lock.node_count != 2 or len(nodes) != 1:
                raise PackageProductRuntimeReadError(
                    "Selected dependency profile requires one dependency",
                    code="package_product_dependency_shape_unsupported",
                )
            node = nodes[0]
            ref = node.stable_ref
            if (
                not isinstance(ref, VerifiedArtifactRefV1)
                or ref.store_identity != self.dependency_store_identity
                or committed_record.committed_set.dependency_refs != (ref,)
            ):
                raise PackageProductRuntimeReadError(
                    "Selected dependency has no exact Store ref",
                    code="package_product_dependency_unbound",
                )
            events = self.dependency_settlements.read_events()
            matches = tuple(
                event
                for event in events
                if isinstance(event, PackageStoreSettlementRecordV1)
                and event.store_role == "dependency"
                and event.store_identity == self.dependency_store_identity
                and event.receipt.stable_ref == ref
                and event.receipt.operation_id == committed_record.operation_id
                and event.receipt.staging_request.attempt_epoch
                == committed_record.committed_set.attempt_epoch
                and event.receipt.staging_request.request_fingerprint
                == committed_record.committed_set.request_fingerprint
                and event.receipt.staging_request.classification_fingerprint
                == committed_record.committed_set.classification_fingerprint
                and event.receipt.staging_request.verified_plan_fingerprint
                == lock.verified_plan_fingerprint
                and event.receipt.staging_request.prepublication_graph_digest
                == lock.prepublication_graph_digest
                and event.receipt.staging_request.plan_node == node.plan_node
            )
            if len(matches) != 1 or any(
                isinstance(event, PackageStoreGcTombstoneV1)
                and event.stable_ref_id == ref.ref_id
                for event in events
            ):
                raise PackageProductRuntimeReadError(
                    "Selected dependency has no live exact settlement",
                    code="package_product_dependency_unavailable",
                )
            settlement = matches[0]
            if (
                len(settlement.manifest.entries) > max_files
                or settlement.manifest.total_byte_count > max_total_bytes
            ):
                raise PackageProductRuntimeReadError(
                    "Selected dependency exceeds capture budget",
                    code="package_product_dependency_capture_budget_exceeded",
                )
            members = tuple(
                (entry.logical_path, entry.byte_count)
                for entry in settlement.manifest.entries
            )
            files = tuple(
                zip(
                    (path for path, _ in members),
                    self.dependency_store.read_dependency_files(settlement, members),
                    strict=True,
                )
            )
            return PackageProductSelectedDependencySnapshotV1(
                installation_key=installation_key,
                package_revision=package_revision,
                instance_revision_ref=instance_revision_ref,
                committed_record=committed_record,
                dependency_ref=ref,
                settlement_id=settlement.settlement_id,
                manifest=settlement.manifest,
                files=files,
            )

    def assert_selected_dependency_current(
        self, snapshot: PackageProductSelectedDependencySnapshotV1
    ) -> None:
        """Reopen selection and physical bytes; this is a preflight, not a lease."""

        if not isinstance(snapshot, PackageProductSelectedDependencySnapshotV1):
            raise TypeError("Product selected dependency snapshot is required")
        current = self.capture_selected_dependency(
            snapshot.installation_key,
            max_files=16,
            max_total_bytes=1024 * 1024,
        )
        if current != snapshot:
            raise PackageProductRuntimeReadError(
                "Product selected dependency changed",
                code="package_product_dependency_selection_changed",
            )

    def capture_selected_dependency_closure(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_dependencies: int,
        max_files_per_dependency: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencyClosureSnapshotV1:
        """Read every selected dependency under one GC guard as inert bytes."""

        if type(max_dependencies) is not int or not 1 <= max_dependencies <= 3:
            raise ValueError("Product dependency closure count budget is invalid")
        if (
            type(max_files_per_dependency) is not int
            or not 1 <= max_files_per_dependency <= 16
        ):
            raise ValueError("Product dependency closure file budget is invalid")
        if (
            type(max_total_bytes) is not int
            or not 0 <= max_total_bytes <= 3 * 1024 * 1024
        ):
            raise ValueError("Product dependency closure byte budget is invalid")
        read_guard = getattr(self.root_reader.gc_gate, "read_guard", None)
        if not callable(read_guard):
            raise TypeError("Product read-only GC gate is required")
        with read_guard() as reserved:
            package_revision, instance_revision_ref, committed_record, _ = (
                self.root_reader._selected_settlement(
                    installation_key, reserved, read_only=True
                )
            )
            lock = committed_record.closure_lock
            nodes = tuple(
                sorted(
                    (
                        node
                        for node in lock.nodes
                        if node.plan_node.role == "dependency"
                    ),
                    key=lambda node: node.node_id,
                )
            )
            if (
                lock.node_count != len(nodes) + 1
                or not 1 <= len(nodes) <= max_dependencies
            ):
                raise PackageProductRuntimeReadError(
                    "Selected dependency closure exceeds Product shape",
                    code="package_product_dependency_shape_unsupported",
                )
            refs = tuple(node.stable_ref for node in nodes)
            if (
                any(
                    not isinstance(ref, VerifiedArtifactRefV1)
                    or ref.store_identity != self.dependency_store_identity
                    for ref in refs
                )
                or tuple(sorted(ref.ref_id for ref in refs))
                != tuple(
                    sorted(
                        ref.ref_id
                        for ref in committed_record.committed_set.dependency_refs
                    )
                )
            ):
                raise PackageProductRuntimeReadError(
                    "Selected dependency closure has no exact Store refs",
                    code="package_product_dependency_unbound",
                )
            events = self.dependency_settlements.read_events()
            members: list[PackageProductSelectedDependencySnapshotV1] = []
            total_bytes = 0
            for node in nodes:
                ref = node.stable_ref
                if not isinstance(ref, VerifiedArtifactRefV1):
                    raise PackageProductRuntimeReadError(
                        "Selected dependency closure has no exact Store ref",
                        code="package_product_dependency_unbound",
                    )
                matches = tuple(
                    event
                    for event in events
                    if isinstance(event, PackageStoreSettlementRecordV1)
                    and event.store_role == "dependency"
                    and event.store_identity == self.dependency_store_identity
                    and event.receipt.stable_ref == ref
                    and event.receipt.operation_id == committed_record.operation_id
                    and event.receipt.staging_request.attempt_epoch
                    == committed_record.committed_set.attempt_epoch
                    and event.receipt.staging_request.request_fingerprint
                    == committed_record.committed_set.request_fingerprint
                    and event.receipt.staging_request.classification_fingerprint
                    == committed_record.committed_set.classification_fingerprint
                    and event.receipt.staging_request.verified_plan_fingerprint
                    == lock.verified_plan_fingerprint
                    and event.receipt.staging_request.prepublication_graph_digest
                    == lock.prepublication_graph_digest
                    and event.receipt.staging_request.plan_node == node.plan_node
                )
                if len(matches) != 1 or any(
                    isinstance(event, PackageStoreGcTombstoneV1)
                    and event.stable_ref_id == ref.ref_id
                    for event in events
                ):
                    raise PackageProductRuntimeReadError(
                        "Selected dependency closure has no live settlement",
                        code="package_product_dependency_unavailable",
                    )
                settlement = matches[0]
                if (
                    len(settlement.manifest.entries) > max_files_per_dependency
                    or settlement.manifest.total_byte_count > 1024 * 1024
                    or total_bytes + settlement.manifest.total_byte_count
                    > max_total_bytes
                ):
                    raise PackageProductRuntimeReadError(
                        "Selected dependency closure exceeds capture budget",
                        code="package_product_dependency_capture_budget_exceeded",
                    )
                total_bytes += settlement.manifest.total_byte_count
                requested_files = tuple(
                    (entry.logical_path, entry.byte_count)
                    for entry in settlement.manifest.entries
                )
                files = tuple(
                    zip(
                        (path for path, _ in requested_files),
                        self.dependency_store.read_dependency_files(
                            settlement, requested_files
                        ),
                        strict=True,
                    )
                )
                members.append(
                    PackageProductSelectedDependencySnapshotV1(
                        installation_key=installation_key,
                        package_revision=package_revision,
                        instance_revision_ref=instance_revision_ref,
                        committed_record=committed_record,
                        dependency_ref=ref,
                        settlement_id=settlement.settlement_id,
                        manifest=settlement.manifest,
                        files=files,
                    )
                )
            return PackageProductSelectedDependencyClosureSnapshotV1(
                installation_key=installation_key,
                package_revision=package_revision,
                instance_revision_ref=instance_revision_ref,
                committed_record=committed_record,
                members=tuple(members),
            )

    def assert_selected_dependency_closure_current(
        self, snapshot: PackageProductSelectedDependencyClosureSnapshotV1
    ) -> None:
        """Reopen the entire selected closure; this is not an attempt lease."""

        if not isinstance(snapshot, PackageProductSelectedDependencyClosureSnapshotV1):
            raise TypeError("Product selected dependency closure is required")
        current = self.capture_selected_dependency_closure(
            snapshot.installation_key,
            max_dependencies=3,
            max_files_per_dependency=16,
            max_total_bytes=3 * 1024 * 1024,
        )
        if current != snapshot:
            raise PackageProductRuntimeReadError(
                "Product selected dependency closure changed",
                code="package_product_dependency_selection_changed",
            )


def _observed_inventory_revision(
    revisions: PackageProductDesiredRevisionProjectionPort,
    request: PackageDesiredStateCommitRequestV1,
) -> int:
    value = revisions.inventory_revision()
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError("Package desired inventory projection is invalid")
    if value == request.expected_inventory_revision:
        raise RuntimeError("Plugin management conflict lacks changed owner revision")
    return value


__all__ = [
    "PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION",
    "CommittedSetPackageRevisionProjection",
    "PackageProductGcBindingPort",
    "PackageProductGcAdmissionError",
    "PackageProductDesiredRevisionProjectionPort",
    "PackageProductRuntimeReadError",
    "PackageProductSelectedDependencyReader",
    "PackageProductSelectedDependencyClosureSnapshotV1",
    "PackageProductSelectedDependencySnapshotV1",
    "PackageProductSelectedRootSnapshotV1",
    "PackageProductRootStoreReadPort",
    "PackageProductSelectedRootReader",
    "PluginManagementCommandSubmitPort",
    "PluginManagementPackageDesiredStateAdapter",
]
