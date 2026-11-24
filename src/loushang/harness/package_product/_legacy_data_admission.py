"""Read and verify the bounded legacy local data set around the first fence."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import NamedTuple

from loushang.harness.plugin_authoring.resource_item import (
    _inspect_legacy_local_data_wheel,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyLocalWheelFields,
    _LegacyWheelValues,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotOwner,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsPreBSnapshotOwner,
)

from ._legacy_binding_evidence import (
    LegacyLocalBindingEvidence,
)
from ._legacy_inventory import (
    LegacyInventoryFacts,
    LegacyInventoryReader,
    prove_removed_legacy_bindings,
    reacquire_legacy_bound_wheel,
)
from ._legacy_management_evidence import (
    read_settled_management_history,
    require_empty_lock_markers,
    require_service_lock_markers,
)
from ._legacy_runtime import _LegacyFirstSnapshot, require_legacy_snapshot_members

_BINDING_LOCK = "package-lock.json"
_PACKAGE_LOCK_MARKER = "package-lock.json.lock"
_DESIRED_JOURNAL = "desired-state.jsonl"


class LegacyDataAdmissionEvidence(NamedTuple):
    inventory: LegacyInventoryFacts[LegacyLocalBindingEvidence]
    removed_local_ids: frozenset[str]
    source_projection: object


@dataclass(frozen=True, slots=True)
class LegacyDataSnapshotAdmission:
    source_member: str
    inventory_reader: LegacyInventoryReader
    maximum_bindings: int
    maximum_sources: int

    def require_adoptable_sources(
        self, evidence: LegacyDataAdmissionEvidence, plugin_id: str, *, message: str
    ) -> tuple[str, ...]:
        active = evidence.inventory.active_local
        removable_ids = self.inventory_reader.builtin_ids | evidence.removed_local_ids
        if (
            not 0 < len(active) <= self.maximum_sources
            or plugin_id not in {binding.plugin_id for binding, _, _ in active}
            or any(plugin not in removable_ids for plugin in evidence.inventory.removed_plugin_ids)
        ):
            raise ValueError(message)
        return tuple(binding.source_identity for binding, _, _ in active)

    def before_fence(
        self,
        owner: PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner,
        snapshot: PackageEpochCutoverSnapshotReceiptV1,
        *,
        has_legacy_state: bool,
    ) -> LegacyDataAdmissionEvidence:
        receipt = snapshot.receipt_id
        evidence = owner.snapshot(receipt)
        shape_error = ValueError("Legacy Skill snapshot shape is unsupported")
        if evidence is None or evidence.snapshot != snapshot or not has_legacy_state:
            raise shape_error
        members = partial(owner.list_domain_members, receipt)
        require_legacy_snapshot_members(members, self._expected(), error=shape_error)
        lock_members = members(domain="lock_history") or ()
        instance_members = members(domain="instance_state") or ()
        has_operations = self.inventory_reader.classify_members(
            members(domain="desired_state") or (),
            instance_members,
            lock_members,
            has_binding=True,
        )
        read = partial(owner.read_regular_member, receipt)
        if _PACKAGE_LOCK_MARKER in lock_members:
            require_empty_lock_markers(
                read,
                (("lock_history", _PACKAGE_LOCK_MARKER),),
                error_type=ValueError,
                message="Legacy Package lock changed",
            )
        source_raw = read(domain="source_configuration", member_name=self.source_member)
        lock_raw = read(domain="binding_history", member_name=_BINDING_LOCK)
        desired_raw = read(domain="desired_state", member_name=_DESIRED_JOURNAL)
        if source_raw is None or lock_raw is None or desired_raw is None:
            raise ValueError("Legacy Skill snapshot members are incomplete")
        source = json.loads(source_raw)
        bindings = self.inventory_reader.decode_binding_heads(lock_raw)
        desired, _, transitions = self.inventory_reader.decode_desired(desired_raw)
        if has_operations:
            require_service_lock_markers(
                read,
                instance_members,
                error_type=ValueError,
                message="Legacy management lock changed",
            )
            read_settled_management_history(
                read,
                paths=self.inventory_reader.management_paths,
                instance_members=instance_members,
                desired_snapshot=desired,
                desired_transitions=transitions,
                error_type=ValueError,
                missing_messages=(
                    "Legacy management operation journal is missing",
                    "Legacy retirement journals are missing",
                    "Legacy Instance evidence is missing",
                ),
                operation_error=self.inventory_reader.operation_error,
                operation_label=f"{self.inventory_reader.label} old",
                instance_error=self.inventory_reader.instance_error,
            )
        inventory = self.inventory_reader.classify(bindings, desired)
        return LegacyDataAdmissionEvidence(
            inventory,
            self._removed_ids(inventory, bindings, transitions)
            if inventory.unselected_source_identities
            else frozenset(),
            source,
        )

    def after_fence(
        self,
        reader: _LegacyFirstSnapshot,
    ) -> LegacyDataAdmissionEvidence:
        members = reader.list_members
        require_legacy_snapshot_members(
            members,
            self._expected(),
            error=ValueError(
                f"{self.inventory_reader.label} first-B local Skill snapshot is unsupported"
            ),
        )
        self.inventory_reader.classify_members(
            members(domain="desired_state"),
            members(domain="instance_state"),
            members(domain="lock_history"),
            has_binding=True,
        )
        read = reader.read_member
        source_raw = read(
            domain="source_configuration",
            member_name=self.source_member,
            maximum_bytes=2 * 1024 * 1024,
        )
        if source_raw is None:
            raise ValueError(
                f"{self.inventory_reader.label} first-B Source configuration is missing"
            )
        source = json.loads(source_raw)
        reader.runtime.assert_current()
        evidence = self.inventory_reader.read(reader)
        inventory = evidence.inventory
        removed_ids: frozenset[str] = frozenset()
        if inventory.unselected_source_identities:
            reader.assert_snapshot_current(evidence.snapshot_receipt_id)
            removed_ids = self._removed_ids(
                inventory, evidence.binding_heads, evidence.desired_transitions
            )
        return LegacyDataAdmissionEvidence(inventory, removed_ids, source)

    def _expected(self) -> dict[str, tuple[str, ...]]:
        return {
            "binding_history": (_BINDING_LOCK,),
            "source_configuration": (self.source_member,),
            "enablement_state": (),
        }

    def _removed_ids(
        self,
        inventory: LegacyInventoryFacts[LegacyLocalBindingEvidence],
        bindings: tuple[LegacyLocalBindingEvidence, ...],
        transitions: tuple[PluginDesiredStateJournalTransition, ...],
    ) -> frozenset[str]:
        return frozenset(
            item.binding.plugin_id
            for item in prove_removed_legacy_bindings(
                bindings,
                transitions,
                unselected_source_identities=inventory.unselected_source_identities,
                removed_plugin_ids=inventory.removed_plugin_ids,
                builtin_ids=self.inventory_reader.builtin_ids,
                maximum_bindings=self.maximum_bindings,
                error_type=self.inventory_reader.inventory_error,
                label=f"{self.inventory_reader.label} old local removal",
            )
        )


def verify_legacy_data_wheels(
    evidence: LegacyDataAdmissionEvidence,
    *,
    legacy_package_root: Path,
    plugin_id: str,
    required_kind: str,
    result_factory: Callable[[_LegacyWheelValues], _LegacyLocalWheelFields],
) -> None:
    names: set[tuple[str, str]] = set()
    for binding, _, _ in evidence.inventory.active_local:
        if not binding.source_identity.startswith("local:/"):
            raise ValueError("Legacy Skill Source is not local")
        wheel = reacquire_legacy_bound_wheel(
            binding,
            legacy_package_root=legacy_package_root,
            staging_prefix="loushang-legacy-pre-fence-",
            result_factory=result_factory,
        )
        if not isinstance(wheel, _LegacyLocalWheelFields):
            raise ValueError("Legacy data Wheel digest is invalid")
        identity = _inspect_legacy_local_data_wheel(wheel)
        if binding.plugin_id == plugin_id and identity[0] != required_kind:
            raise ValueError("Legacy data Resource type changed")
        if identity in names:
            raise ValueError("Legacy data names conflict across Installations")
        names.add(identity)
