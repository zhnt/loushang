"""Closed Product backup kinds for the current Coding Plugin release.

Coding's retained backup owner archives only Arch Installation private data.
No Product route can retain a Worker attempt in this release. A later Worker
backup kind must change this authority before its writer can be admitted; a
checkpoint can then refuse an earlier topology revision on reopen.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.journal._rooted_io import RootedFileIO
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
    read_windows_private_receipt,
    write_windows_private_receipt,
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
        PackageProductPosixFencedRuntimeOwner
        | PackageProductWindowsFencedRuntimeOwner
    ),
    gc_gate: PluginPackageGcReservationJournal,
    before_load: Callable[[], None] | None = None,
) -> None:
    """Publish the closed backup owner set before any Worker history exists."""

    if not isinstance(gc_gate, PluginPackageGcReservationJournal):
        raise TypeError("Coding backup topology requires the Product GC gate")
    with gc_gate.guard(before_load=before_load, require_write=True):
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
        PackageProductPosixFencedRuntimeOwner
        | PackageProductWindowsFencedRuntimeOwner
    ),
    create_if_new: bool,
) -> str:
    expected = _topology_bytes(scope_id)
    epoch_runtime.assert_current()
    path = state_root / _FILE_NAME
    if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
            windows_listdir_at,
        )

        with epoch_runtime.borrow_product_state_root_descriptor() as root:
            raw = read_windows_private_receipt(
                path,
                maximum_bytes=_MAX_BYTES,
                allow_unpublished_stage=create_if_new,
            )
            if raw is None:
                if not create_if_new or any(
                    name.casefold().startswith("worker-")
                    for name in windows_listdir_at(root)
                ):
                    raise ValueError("Coding backup topology is absent after Worker history")
                write_windows_private_receipt(
                    path, expected, maximum_bytes=_MAX_BYTES
                )
                raw = read_windows_private_receipt(path, maximum_bytes=_MAX_BYTES)
    elif isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        metadata = state_root.lstat()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root_fd = os.open(state_root, flags)
        try:
            opened = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (metadata.st_dev, metadata.st_ino)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise ValueError("Coding backup topology state root changed")
            io = RootedFileIO(state_root, root_fd)
            try:
                with io.bind(path, durable=True) as rooted:
                    try:
                        raw = rooted.read_bytes(max_bytes=_MAX_BYTES)
                    except FileNotFoundError:
                        names, complete = rooted.scan_sibling_names(
                            limit=_MAX_INVENTORY
                        )
                        if not create_if_new or not complete or any(
                            name.startswith("worker-") for name in names
                        ):
                            raise ValueError(
                                "Coding backup topology is absent after Worker history"
                            ) from None
                        rooted.create_new(expected)
                        raw = rooted.read_bytes(max_bytes=_MAX_BYTES)
            finally:
                io.cleanup()
        finally:
            os.close(root_fd)
    else:
        raise TypeError("Coding backup topology requires a Product epoch")
    epoch_runtime.assert_current()
    if raw != expected:
        raise ValueError("Coding backup topology changed")
    return "coding-product-backup-types:" + sha256(
        b"loushang.coding-product-backup-types/v1\0" + raw
    ).hexdigest()


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
    if not isinstance(
        product,
        (PosixLocalWheelProductSessionOwner, WindowsLocalWheelProductSessionOwner),
    ) or product.policy.product_id != "coding":
        raise ValueError("Coding backup requires a Product owner")


__all__ = [
    "CodingWorkerBackupReferenceObservationV1",
    "ensure_coding_product_backup_types",
    "observe_coding_worker_backup_references_under_gc_guard",
    "require_coding_arch_backup_writer",
]
