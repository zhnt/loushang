"""PLC9A2 adapters from Package handoff records to Plugin management owners."""

from __future__ import annotations

from dataclasses import dataclass
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
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
    PackageDesiredStateCommitResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
    PackageStoreSettlementRecordV1,
)

PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION = 1


class PluginManagementCommandSubmitPort(Protocol):
    """Narrow command surface retained by the Package desired adapter."""

    @property
    def gc_gate(self) -> PluginPackageGcReferenceGatePort | None: ...

    def submit(
        self,
        command: PluginManagementCommandV1,
    ) -> PluginManagementOperationEventV1: ...


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
        transition: PluginDesiredStateTransitionV1,
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
            or self.committed_sets.is_tombstoned(committed.root_ref.ref_id)
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

    def inventory_revision(self) -> int:
        return self.desired_state.snapshot().inventory_revision


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


class PackageProductRuntimeReadError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductRootStoreReadPort(Protocol):
    def read_root_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes: ...


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
            settlement = self._selected_settlement(installation_key, reserved)
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
            settlement = self._selected_settlement(installation_key, reserved)
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
            return tuple(
                self.root_store.read_root_file(
                    settlement, path, max_bytes=members[path].byte_count
                )
                for path in logical_paths
            )

    def _selected_settlement(
        self,
        installation_key: PluginInstallationKeyV1,
        reserved: frozenset[PluginPackageRevisionRefV1],
    ) -> PackageStoreSettlementRecordV1:
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
        snapshot, transitions = self.desired_state.capture()
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
        if not isinstance(selected_commit, PluginDesiredStateTransitionV1):
            raise self._error(
                "Selected update lacks a PLC9B Product binding",
                "package_product_root_unbound",
            )
        matches = tuple(
            binding
            for binding in self.bindings.records()
            if binding.desired_transition_revision == selected_commit.inventory_revision
            and binding.package_revision == package_revision
            and binding.request.command_id == selected_commit.mutation.operation_id
            and binding.request.desired_request_id
            == selected_commit.mutation.idempotency_key
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
        try:
            projected = CommittedSetPackageRevisionProjection(
                self.desired_state, self.committed_sets
            ).project(request)
        except ValueError:
            raise self._error(
                "Selected committed set changed", "package_product_root_stale"
            ) from None
        committed_record = self.committed_sets.current(request.operation_id)
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
        settlements = tuple(
            settlement
            for settlement in self.root_settlements.records()
            if settlement.receipt.stable_ref == request.root_ref
            and settlement.receipt.operation_id == request.operation_id
        )
        if len(settlements) != 1:
            raise self._error(
                "Selected Store root is unavailable",
                "package_product_root_unavailable",
            )
        return settlements[0]

    @staticmethod
    def _error(message: str, code: str) -> PackageProductRuntimeReadError:
        return PackageProductRuntimeReadError(message, code=code)


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
    "PackageProductRootStoreReadPort",
    "PackageProductSelectedRootReader",
    "PluginManagementCommandSubmitPort",
    "PluginManagementPackageDesiredStateAdapter",
]
