"""Read the old removal proof before cutover or from the authenticated fence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import NamedTuple

from loushang.harness.package_product._legacy_binding_evidence import (
    LEGACY_BINDING_CAPTURE_MAX_BYTES,
    LegacyLocalBindingEvidence,
    decode_legacy_local_binding_heads,
)
from loushang.harness.package_product._legacy_inventory import (
    LegacyInventoryFacts,
    LegacyRemovedBinding,
    classify_legacy_installations,
    prove_removed_legacy_bindings,
)
from loushang.harness.package_product._legacy_management_evidence import (
    LEGACY_DESIRED_CAPTURE_MAX_BYTES,
    LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
    LegacyManagementCapturePaths,
    classify_management_members,
    decode_legacy_desired_evidence,
    read_settled_management_history,
    require_empty_lock_markers,
)
from loushang.harness.package_product._legacy_runtime import _LegacyFirstSnapshot
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotOwner,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsPreBSnapshotOwner,
)

_DOMAINS = (
    "binding_history",
    "desired_state",
    "source_configuration",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)
_JOURNAL_DOMAINS = ("desired_state", "instance_state", "lock_history")
_SHAPE_CHANGED = "Old removal snapshot shape changed"
LEGACY_REMOVAL_STORE_ROOTS = frozenset({"installed", "plugin-revisions"})


class LegacyRemovalFacts(NamedTuple):
    inventory: LegacyInventoryFacts[LegacyLocalBindingEvidence]
    removed: tuple[LegacyRemovedBinding[LegacyLocalBindingEvidence], ...]
    desired_digest: str
    operation_digest: str | None


@dataclass(frozen=True, slots=True)
class LegacyRemovalSnapshot:
    _read_member: Callable[..., bytes | None]
    _instance_members: tuple[str, ...]
    retained_store_roots: tuple[str, ...]
    has_operations: bool
    _before_fence: bool
    _review_error: type[ValueError]
    _operation_error: type[ValueError]
    _label: str

    @classmethod
    def before_fence(
        cls,
        owner: PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner,
        snapshot: PackageEpochCutoverSnapshotReceiptV1,
        *,
        eligible: bool,
        source_member: str,
        review_error: type[ValueError],
        operation_error: type[ValueError],
        label: str,
    ) -> LegacyRemovalSnapshot:
        evidence = owner.snapshot(snapshot.receipt_id)
        members = {
            domain: owner.list_domain_members(snapshot.receipt_id, domain=domain) or ()
            for domain in _DOMAINS
        }
        if not eligible or evidence is None or evidence.snapshot != snapshot:
            raise review_error(_SHAPE_CHANGED)
        return cls._verify_members(
            members,
            partial(owner.read_regular_member, snapshot.receipt_id),
            source_member=source_member,
            review_error=review_error,
            operation_error=operation_error,
            label=label,
            before_fence=True,
        )

    @classmethod
    def after_fence(
        cls,
        reader: _LegacyFirstSnapshot,
        *,
        source_member: str,
        review_error: type[ValueError],
        operation_error: type[ValueError],
        label: str,
    ) -> LegacyRemovalSnapshot:
        return cls._verify_members(
            {domain: reader.list_members(domain=domain) for domain in _DOMAINS},
            reader.read_member,
            source_member=source_member,
            review_error=review_error,
            operation_error=operation_error,
            label=label,
            before_fence=False,
        )

    @classmethod
    def _verify_members(
        cls,
        members: Mapping[str, tuple[str, ...]],
        read_member: Callable[..., bytes | None],
        *,
        source_member: str,
        review_error: type[ValueError],
        operation_error: type[ValueError],
        label: str,
        before_fence: bool,
    ) -> LegacyRemovalSnapshot:
        store_roots = members["store_bytes"]
        if (
            members["binding_history"] != ("package-lock.json",)
            or members["source_configuration"] != (source_member,)
            or members["enablement_state"]
            or store_roots
            != tuple(sorted(set(store_roots) & LEGACY_REMOVAL_STORE_ROOTS))
        ):
            raise review_error(_SHAPE_CHANGED)
        instance_members = members["instance_state"]
        try:
            has_operations = classify_management_members(
                desired_members=members["desired_state"],
                instance_members=instance_members,
                lock_members=members["lock_history"],
                has_binding=True,
                allow_retirement=True,
                allow_retired_runtime=True,
                error_type=operation_error,
                label=f"{label} old",
            )
        except operation_error as exc:
            raise review_error(_SHAPE_CHANGED) from exc
        require_empty_lock_markers(
            read_member,
            (
                (domain, name)
                for domain in _JOURNAL_DOMAINS
                for name in members[domain]
                if name.endswith(".lock")
            ),
            error_type=review_error,
            message="Old removal journal lock changed",
        )
        return cls(
            read_member,
            instance_members,
            store_roots,
            has_operations,
            before_fence,
            review_error,
            operation_error,
            label,
        )

    def prove(
        self,
        *,
        desired_path: Path,
        management_paths: LegacyManagementCapturePaths,
        product_id: str,
        scope_id: str,
        builtin_ids: Set[str],
        maximum_bindings: int,
        inventory_error: type[ValueError],
        lock_error: type[ValueError],
        desired_error: type[ValueError],
        instance_error: type[ValueError],
    ) -> LegacyRemovalFacts:
        read = self._read_member
        lock_max = LEGACY_BINDING_CAPTURE_MAX_BYTES
        desired_max = LEGACY_DESIRED_CAPTURE_MAX_BYTES
        defaults = self._before_fence
        lock_raw = read(
            domain="binding_history",
            member_name="package-lock.json",
            **({} if defaults else {"maximum_bytes": lock_max}),
        )
        desired_raw = read(
            domain="desired_state",
            member_name="desired-state.jsonl",
            **({} if defaults else {"maximum_bytes": desired_max}),
        )
        if lock_raw is None or desired_raw is None:
            raise self._review_error("Old removal evidence is missing")
        bindings = decode_legacy_local_binding_heads(
            lock_raw,
            maximum_bytes=lock_max,
            error_type=lock_error,
            label=f"{self._label} legacy",
        )
        desired, desired_digest, transitions = decode_legacy_desired_evidence(
            desired_raw,
            path=desired_path,
            product_id=product_id,
            scope_id=scope_id,
            maximum_bytes=desired_max,
            error_type=desired_error,
            label=f"{self._label} legacy",
        )

        def check_management_history() -> str | None:
            return read_settled_management_history(
                read,
                paths=management_paths,
                instance_members=self._instance_members,
                desired_snapshot=desired,
                desired_transitions=transitions,
                error_type=self._review_error,
                missing_messages=(
                    "Old management operation evidence is missing",
                    "Old retirement evidence is missing",
                    "Old Instance evidence is missing",
                ),
                operation_error=self._operation_error,
                operation_label=f"{self._label} old",
                instance_error=instance_error,
                operation_maximum_bytes=None
                if defaults
                else LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
                retain_operation_digest=not defaults,
            )

        operation_digest = (
            check_management_history() if self.has_operations and not defaults else None
        )
        if not isinstance(scope_id, str) or not scope_id.startswith("workspace:"):
            raise ValueError(f"{self._label} legacy workspace scope is invalid")
        inventory = classify_legacy_installations(
            bindings,
            desired,
            product_id=product_id,
            scope_id=scope_id,
            builtin_ids=builtin_ids,
            error_type=inventory_error,
            label=f"{self._label} legacy",
        )
        removed = prove_removed_legacy_bindings(
            bindings,
            transitions,
            unselected_source_identities=inventory.unselected_source_identities,
            removed_plugin_ids=inventory.removed_plugin_ids,
            builtin_ids=builtin_ids,
            maximum_bindings=maximum_bindings,
            error_type=inventory_error,
            label=f"{self._label} old local removal",
        )
        if self.has_operations and defaults:
            check_management_history()
        return LegacyRemovalFacts(inventory, removed, desired_digest, operation_digest)
