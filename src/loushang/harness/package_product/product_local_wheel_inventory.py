"""Product inventory over the exact desired and committed local-Wheel owners."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.records import (
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductUpdateCheckRequestV1,
    PackageProductUpdateCheckV1,
    PackageProductUpdateManifestReceiptV1,
    PackageProductUpdateTargetV1,
    canonicalize_package_product_scope,
)
from loushang.harness.resources.packages.product_inventory import (
    PackageProductUpdateManifestJournal,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)


class PackageProductLocalWheelInventory:
    """Read installed roots; freeze bulk targets; check only pinned candidates.

    Unrecognized or legacy-unverified roots yield an explicit check failure.
    They never become an empty inventory or a reason to consult a materializer.
    """

    def __init__(
        self,
        *,
        binding_id: str,
        policy: PackageProductLocalWheelPolicy,
        desired_state: PluginDesiredStateLedger,
        committed_sets: PackageCommittedSetJournal,
        manifest_path: Path,
    ) -> None:
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("Product lifecycle binding is required")
        if not isinstance(policy, PackageProductLocalWheelPolicy):
            raise TypeError("Product local Wheel policy is required")
        if not isinstance(desired_state, PluginDesiredStateLedger):
            raise TypeError("Product desired-state owner is required")
        if not isinstance(committed_sets, PackageCommittedSetJournal):
            raise TypeError("Product committed-set owner is required")
        if (
            not isinstance(manifest_path, Path)
            or not manifest_path.is_absolute()
            or ".." in manifest_path.parts
        ):
            raise ValueError("Product update manifest path must be absolute")
        self.binding_id = binding_id
        self._policy = policy
        self._desired = desired_state
        self._committed = committed_sets
        self._manifests = PackageProductUpdateManifestJournal(
            manifest_path, binding_id=binding_id
        )

    def list_update_targets(
        self, *, scope: str
    ) -> tuple[PackageProductUpdateTargetV1, ...]:
        canonical_scope = canonicalize_package_product_scope(scope)
        return tuple(
            sorted(
                (
                    PackageProductUpdateTargetV1(
                        target_ref=f"sha256:{sha256(source.encode()).hexdigest()}",
                        source=source,
                        scope=canonical_scope,
                    )
                    for source in self._installed(canonical_scope)
                ),
                key=lambda target: target.target_ref,
            )
        )

    def bind_update_targets(
        self,
        *,
        operation_id: str,
        scope: str,
        targets: tuple[PackageProductUpdateTargetV1, ...],
    ) -> PackageProductUpdateManifestReceiptV1:
        canonical_scope = canonicalize_package_product_scope(scope)
        if targets != self.list_update_targets(scope=canonical_scope):
            raise ValueError("Product update target set changed before binding")
        return self._manifests.bind_receipt(
            operation_id=operation_id,
            scope=canonical_scope,
            target_refs=tuple(target.target_ref for target in targets),
        )

    async def check_updates(
        self, *, request: PackageProductUpdateCheckRequestV1
    ) -> tuple[PackageProductUpdateCheckV1, ...]:
        if not isinstance(request, PackageProductUpdateCheckRequestV1):
            raise TypeError("Product update check request is required")
        installed = self._installed(request.scope)
        committed = self._committed.records()
        return tuple(
            sorted(
                (
                    PackageProductUpdateCheckV1(
                        target_ref=f"sha256:{sha256(source.encode()).hexdigest()}",
                        scope=request.scope,
                        update_available=available,
                        failure_code=failure,
                    )
                    for source, state in installed.items()
                    for available, failure in (self._check(state, committed),)
                ),
                key=lambda check: check.target_ref,
            )
        )

    def _installed(self, scope: str) -> dict[str, PluginInstallationStateV1]:
        if scope != "project":
            return {}
        installed: dict[str, PluginInstallationStateV1] = {}
        for state in self._desired.snapshot().installations:
            key = state.installation_key
            selected = state.selection.package_revision
            if (
                key.product_id != self._policy.product_id
                or key.installation_scope != "workspace"
                or key.scope_id != self._policy.project_scope_id
                or selected is None
            ):
                continue
            source = selected.package_source_identity
            if source in installed:
                raise ValueError("Product update inventory has ambiguous Source owner")
            installed[source] = state
        return dict(sorted(installed.items()))

    def _check(
        self,
        state: PluginInstallationStateV1,
        committed: tuple[PackageCommittedSetRecordV1, ...],
    ) -> tuple[bool, str | None]:
        selected = state.selection.package_revision
        assert isinstance(selected, PluginPackageRevisionRefV1)
        binding = next(
            (
                item
                for item in self._policy.bindings
                if item.source_identity == selected.package_source_identity
            ),
            None,
        )
        if binding is None or binding.plugin_id != state.installation_key.plugin_id:
            return False, "package_update_source_unavailable"
        record = next(
            (
                item
                for item in committed
                if item.closure_lock.lock_digest == selected.dependency_lock_digest
                and item.committed_set.product_id == state.installation_key.product_id
                and item.committed_set.scope_id == state.installation_key.scope_id
                and item.committed_set.plugin_id == selected.plugin_id
                and item.committed_set.root_ref.artifact_digest
                == selected.package_content_digest
                and next(
                    node.plan_node.canonical_source_identity
                    for node in item.closure_lock.nodes
                    if node.node_id == item.closure_lock.root_node_id
                )
                == selected.package_source_identity
            ),
            None,
        )
        if record is None or self._committed.is_tombstoned(
            record.committed_set.root_ref.ref_id
        ):
            return False, "package_update_provenance_unavailable"
        if selected.package_content_digest != binding.artifact_digest:
            return True, None
        dependencies = {
            item.project_name: item for item in self._policy.dependencies
        }
        for node in record.closure_lock.nodes:
            if node.plan_node.role != "dependency":
                continue
            candidate = dependencies.get(node.plan_node.distribution)
            if candidate is None:
                return False, "package_update_dependency_unavailable"
            if (
                candidate.version != node.plan_node.version
                or candidate.source_identity
                != node.plan_node.canonical_source_identity
                or candidate.artifact_digest != node.plan_node.artifact_digest
            ):
                return True, None
        return False, None


__all__ = ["PackageProductLocalWheelInventory"]
