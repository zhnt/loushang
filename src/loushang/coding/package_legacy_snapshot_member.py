"""Bind Coding migration reads to one authenticated first-B snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.harness.package_product._legacy_runtime import _LegacyFirstSnapshot
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout

CodingLegacyEvidenceDomain = Literal[
    "binding_history",
    "desired_state",
    "instance_state",
    "lock_history",
    "source_configuration",
]
CodingLegacyInventoryDomain = (
    CodingLegacyEvidenceDomain | Literal["enablement_state", "store_bytes"]
)
CodingFencedEpochRuntime: TypeAlias = (
    PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
)


class CodingLegacySnapshotError(ValueError):
    """The current Product fence cannot authorize a migration evidence read."""


@dataclass(frozen=True, slots=True)
class CodingFirstBLegacyStateObserver:
    """Observe the complete immutable old state for Harness adoption checks."""

    lifecycle: CodingPluginLifecycleStateLayout
    epoch_runtime: CodingFencedEpochRuntime

    def observe(
        self, *, store_id: str, legacy_root_identity: str
    ) -> PackageLegacyStateEvidenceV1:
        return _snapshot_binding(self.lifecycle, self.epoch_runtime).observe(
            store_id=store_id, legacy_root_identity=legacy_root_identity
        )


def read_coding_first_b_snapshot_member(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    domain: CodingLegacyEvidenceDomain,
    member_name: str,
    maximum_bytes: int,
) -> bytes | None:
    """Read an exact Coding member without reopening mutable pre-B roots."""

    if domain not in (
        "binding_history",
        "desired_state",
        "instance_state",
        "lock_history",
        "source_configuration",
    ):
        raise ValueError("Coding legacy evidence domain is unsupported")
    return _snapshot_binding(lifecycle, epoch_runtime).read_member(
        domain=domain, member_name=member_name, maximum_bytes=maximum_bytes
    )


def list_coding_first_b_snapshot_domain_members(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    domain: CodingLegacyInventoryDomain,
) -> tuple[str, ...]:
    """Enumerate one authenticated pre-B domain under the same first fence."""

    if domain not in (
        "binding_history",
        "desired_state",
        "enablement_state",
        "instance_state",
        "lock_history",
        "source_configuration",
        "store_bytes",
    ):
        raise ValueError("Coding legacy evidence domain is unsupported")
    return _snapshot_binding(lifecycle, epoch_runtime).list_members(domain=domain)


def _snapshot_binding(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
) -> _LegacyFirstSnapshot:
    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(
        epoch_runtime,
        (
            PackageProductPosixFencedRuntimeOwner,
            PackageProductWindowsFencedRuntimeOwner,
        ),
    ):
        raise TypeError("Fenced Product epoch owner is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    return _LegacyFirstSnapshot.open(
        epoch_runtime,
        store_id=epoch.store_id,
        control_root=epoch.control_root,
        snapshot_root=epoch.snapshot_root,
        error_type=CodingLegacySnapshotError,
        label="Coding legacy Package",
    )


__all__ = [
    "CodingFencedEpochRuntime",
    "CodingLegacyEvidenceDomain",
    "CodingLegacyInventoryDomain",
    "CodingLegacySnapshotError",
    "CodingFirstBLegacyStateObserver",
    "list_coding_first_b_snapshot_domain_members",
    "read_coding_first_b_snapshot_member",
]
