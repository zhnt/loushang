"""Closed Product backup kinds for the current Coding Plugin release.

Coding's retained backup owner archives only Arch Installation private data.
No Product route can retain a Worker attempt in this release. A later Worker
backup kind must change this authority before its writer can be admitted; a
checkpoint can then refuse an earlier topology revision on reopen.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.package_product._backup_topology import read_backup_topology
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from .package_legacy_windows_receipt import (
    _receipt_io as _windows_receipt_io,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_ARCH_BACKUP_KIND = "arch_private_data"
_WORKER_BACKUP_KIND = "worker_attempt"
_SUPPORTED_BACKUP_KINDS = (_ARCH_BACKUP_KIND,)
_FILE_NAME = "coding-backup-types.json"
_MAX_BYTES = 4096
_MAX_INVENTORY = 131072
_OWNER_REVISION = re.compile(r"coding-product-backup-types:[0-9a-f]{64}\Z")


def _topology_bytes(scope_id: str) -> bytes:
    if type(scope_id) is not str or not scope_id or len(scope_id) > 128:
        raise ValueError("Coding backup topology scope is invalid")
    return canonical_json_bytes(
        {
            "productId": "coding",
            "scopeId": scope_id,
            "supportedKinds": list(_SUPPORTED_BACKUP_KINDS),
            "version": 1,
        }
    )


def ensure_coding_product_backup_types(
    *,
    state_root: Path,
    scope_id: str,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    gc_gate: PluginPackageGcReservationJournal,
    before_load: Callable[[], None] | None = None,
    require_current_admission: Callable[[], None] | None = None,
) -> None:
    """Publish the closed backup owner set before any Worker history exists."""

    if not isinstance(gc_gate, PluginPackageGcReservationJournal):
        raise TypeError("Coding backup topology requires the Product GC gate")
    from .package_product_runtime import _require_current_coding_product_admission

    _require_current_coding_product_admission(require_current_admission)
    with gc_gate.guard(before_load=before_load, require_write=True):
        _require_current_coding_product_admission(require_current_admission)
        _read_topology(
            state_root=state_root,
            scope_id=scope_id,
            epoch_runtime=epoch_runtime,
            create_if_new=before_load is None,
        )


def _read_topology(
    *,
    state_root: Path,
    scope_id: str,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    create_if_new: bool,
) -> str:
    raw = read_backup_topology(
        state_root=state_root,
        epoch_runtime=epoch_runtime,
        expected=_topology_bytes(scope_id),
        create_if_new=create_if_new,
        file_name=_FILE_NAME,
        maximum_bytes=_MAX_BYTES,
        maximum_inventory=_MAX_INVENTORY,
        blocking_history_prefix="worker-",
        label="Coding backup topology",
        absent_message="Coding backup topology is absent after Worker history",
        windows_receipts=_windows_receipt_io,
    )
    return (
        "coding-product-backup-types:"
        + sha256(b"loushang.coding-product-backup-types/v1\0" + raw).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerBackupReferenceObservationV1:
    """Product backup topology observation, with no pruning authority."""

    attempt_id: str
    owner_revision: str
    worker_backup_supported: Literal[False]
    references: tuple[()]

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.owner_revision) is not str
            or _OWNER_REVISION.fullmatch(self.owner_revision) is None
            or self.worker_backup_supported is not False
            or self.references != ()
        ):
            raise ValueError("Coding Worker backup observation is invalid")


def require_coding_arch_backup_writer(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
) -> None:
    """Bind every current Coding backup writer to the closed Arch kind."""

    _require_coding_product(product)
    with product.gc_gate.read_guard():
        _read_topology(
            state_root=product.state_root,
            scope_id=product.policy.project_scope_id,
            epoch_runtime=product.epoch_runtime,
            create_if_new=False,
        )
    if _ARCH_BACKUP_KIND not in _SUPPORTED_BACKUP_KINDS:
        raise ValueError("Coding Arch backup kind is not admitted")


def observe_coding_worker_backup_references_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> CodingWorkerBackupReferenceObservationV1:
    """Attest that the current Product has no Worker-attempt backup writer.

    The caller holds Product quiescence and the GC/Desired State gate. This
    attests only the current versioned Product backup topology, not external
    workspace copies or any future Worker backup kind.
    """

    _require_coding_product(product)
    if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker backup attempt is invalid")
    product.assert_root_gc_authority_current()
    owner_revision = _read_topology(
        state_root=product.state_root,
        scope_id=product.policy.project_scope_id,
        epoch_runtime=product.epoch_runtime,
        create_if_new=False,
    )
    if _WORKER_BACKUP_KIND in _SUPPORTED_BACKUP_KINDS:
        raise ValueError("Coding Worker backup references need an owner inventory")
    return CodingWorkerBackupReferenceObservationV1(
        attempt_id=attempt_id,
        owner_revision=owner_revision,
        worker_backup_supported=False,
        references=(),
    )


def _require_coding_product(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
) -> None:
    if (
        not isinstance(
            product,
            (PosixLocalWheelProductSessionOwner, WindowsLocalWheelProductSessionOwner),
        )
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding backup requires a Product owner")


__all__ = [
    "CodingWorkerBackupReferenceObservationV1",
    "ensure_coding_product_backup_types",
    "observe_coding_worker_backup_references_under_gc_guard",
    "require_coding_arch_backup_writer",
]
