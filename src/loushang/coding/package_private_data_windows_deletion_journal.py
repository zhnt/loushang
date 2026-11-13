"""Native, Product-bound Windows Arch private-data deletion event candidate.

One immutable private receipt records each phase. The Product's cross-process
offline gate covers the entire transaction, including future filesystem work.
An unpublished or malformed next event remains visible as recovery debt.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import ClassVar

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_deletion_windows import (
    WindowsPrivateDeletionTransaction,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    _windows_arch_current_root_generation,
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_legacy_windows_receipt import (
    _receipt_io,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_deletion_journal import (
    _tombstone_name as _tombstone_name,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _native_io,
)

_EVENT_NAME = re.compile(r"arch-private-deletion-([0-9]{8})\.json(\.stage)?\Z")
_EVENT_PREFIX = "arch-private-deletion-"
_MAX_EVENT_BYTES = 4 * 1024 * 1024
_MAX_EVENTS = 4096
_OWNER_ID = "coding.arch.private-data:windows-v1"


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataDeletionJournal:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        if (
            self.product.state_root
            != resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        ):
            raise ValueError("Windows Coding Arch deletion Product state changed")

    @contextmanager
    def transaction(self) -> Iterator[CodingWindowsArchPrivateDataDeletionTransaction]:
        """Hold one offline Product gate from start through physical effects."""

        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Windows Coding Arch deletion runtime is active")
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard(require_write=True):
                with (
                    self.product.epoch_runtime.borrow_product_state_root_descriptor() as fd
                ):
                    transaction = CodingWindowsArchPrivateDataDeletionTransaction(
                        self.product.state_root,
                        fd,
                        CodingWindowsArchPrivateDataConfirmationOwner(
                            self.layout, self.product
                        ),
                    )
                    try:
                        yield transaction
                    finally:
                        transaction._close()
            self.product.assert_root_gc_authority_current()


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataDeletionTransaction(
    WindowsPrivateDeletionTransaction[
        CodingArchPrivateDataTargetSnapshotV1, CodingArchPrivateDataDeletionEventV1
    ]
):
    state_root: Path
    state_fd: int
    confirmations: CodingWindowsArchPrivateDataConfirmationOwner | None = None
    _active: bool = field(default=True, init=False, repr=False, compare=False)
    _label: ClassVar[str] = "Windows Coding Arch"
    _owner_id: ClassVar[str] = _OWNER_ID
    _event_prefix: ClassVar[str] = _EVENT_PREFIX
    _event_name: ClassVar[re.Pattern[str]] = _EVENT_NAME
    _max_event_bytes: ClassVar[int] = _MAX_EVENT_BYTES
    _max_events: ClassVar[int] = _MAX_EVENTS
    _receipt_io: ClassVar[WindowsPrivateReceiptIO] = _receipt_io
    _event_type: ClassVar[type[CodingArchPrivateDataDeletionEventV1]] = (
        CodingArchPrivateDataDeletionEventV1
    )
    _target_type: ClassVar[type[CodingArchPrivateDataTargetSnapshotV1]] = (
        CodingArchPrivateDataTargetSnapshotV1
    )

    def _domain(self) -> _CodingWindowsDeletionDomain:
        owner = self.confirmations
        if owner is None:
            raise ValueError("Windows Coding Arch deletion Product owner is absent")
        return _CodingWindowsDeletionDomain(owner)

    def _receipt_id(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> str:
        return windows_arch_deletion_receipt_id(plan, confirmation)

    def _require_confirmation(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        owner = self.confirmations
        if owner is None or owner.is_confirmed(plan, confirmation) is not True:
            raise ValueError("Windows Coding Arch deletion confirmation is missing")


@dataclass(frozen=True, slots=True)
class _CodingWindowsDeletionDomain:
    owner: CodingWindowsArchPrivateDataConfirmationOwner

    def require_removed(self, key: PluginInstallationKeyV1) -> None:
        state = self.owner.product.desired_state.snapshot().installation(key)
        if (
            state.latest_instance_revision_ref is None
            or state.selection.desired_state != "absent"
        ):
            raise ValueError("Windows Coding Arch deletion requires Product removal")

    def root_for(self, key: PluginInstallationKeyV1) -> Path:
        return coding_arch_installation_private_data_root(self.owner.layout, key)

    def capture_current(
        self, key: PluginInstallationKeyV1, *, allow_pending: bool = False
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        return _capture_current_target(self.owner, key, allow_pending=allow_pending)

    def require_staged_unchanged(
        self,
        key: PluginInstallationKeyV1,
        target: CodingArchPrivateDataTargetSnapshotV1,
    ) -> None:
        _require_staged_start_target_unchanged(self.owner, key, target)

    def require_tombstone(
        self, event: CodingArchPrivateDataDeletionEventV1, *, present: bool
    ) -> None:
        _require_windows_tombstone(self.owner, event, present=present)


def windows_arch_deletion_receipt_id(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
) -> str:
    if confirmation.plan_fingerprint != plan.fingerprint:
        raise ValueError("Windows Coding Arch deletion receipt is foreign")
    return sha256(
        b"loushang.coding-arch-private-data-receipt/v1\0"
        + plan.fingerprint.encode("ascii")
        + b"\0"
        + confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()


def _capture_current_target(
    owner: CodingWindowsArchPrivateDataConfirmationOwner,
    key: PluginInstallationKeyV1,
    *,
    allow_pending: bool = False,
) -> CodingArchPrivateDataTargetSnapshotV1:
    root = coding_arch_installation_private_data_root(owner.layout, key)
    if allow_pending:
        expected_root = _windows_arch_current_root_generation(
            key,
            root,
            owner.product.state_root,
            inspect_windows_product_private_directory_identity(
                owner.layout.package_root
            ),
            allow_pending=True,
        ).identity
    else:
        expected_root = inspect_coding_windows_arch_installation_root(
            owner.layout, key, state_root=owner.product.state_root
        )
    if expected_root is None:
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Windows Coding Arch absent target changed")
        if (
            allow_pending
            and _windows_arch_current_root_generation(
                key,
                root,
                owner.product.state_root,
                inspect_windows_product_private_directory_identity(
                    owner.layout.package_root
                ),
                allow_pending=True,
            ).identity
            is not None
        ):
            raise ValueError("Windows Coding Arch absent target changed")
        return CodingArchPrivateDataTargetSnapshotV1(
            root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
            root_identity=None,
            members=(),
        )
    target = _capture_windows_target_snapshot(root, expected_root=expected_root)
    current_root = (
        _windows_arch_current_root_generation(
            key,
            root,
            owner.product.state_root,
            inspect_windows_product_private_directory_identity(
                owner.layout.package_root
            ),
            allow_pending=True,
        ).identity
        if allow_pending
        else inspect_coding_windows_arch_installation_root(
            owner.layout, key, state_root=owner.product.state_root
        )
    )
    if current_root != expected_root:
        raise ValueError("Windows Coding Arch deletion root changed")
    return target


def _require_staged_start_target_unchanged(
    owner: CodingWindowsArchPrivateDataConfirmationOwner,
    key: PluginInstallationKeyV1,
    target: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    """Recapture a staged start without reading its own unpublished journal."""

    root = coding_arch_installation_private_data_root(owner.layout, key)
    if target.root_path_digest != sha256(os.fsencode(str(root))).hexdigest():
        raise ValueError("Windows Coding Arch deletion target changed")
    if target.root_identity is None:
        try:
            root.lstat()
        except FileNotFoundError:
            return
        raise ValueError("Windows Coding Arch deletion target changed")
    if (
        _capture_windows_target_snapshot(root, expected_root=target.root_identity[:2])
        != target
    ):
        raise ValueError("Windows Coding Arch deletion target changed")


def _require_windows_tombstone(
    owner: CodingWindowsArchPrivateDataConfirmationOwner,
    started: CodingArchPrivateDataDeletionEventV1,
    *,
    present: bool,
) -> None:
    target_identity = started.target.root_identity
    if target_identity is None:
        raise ValueError("Windows Coding Arch tombstone requires a present target")
    root = coding_arch_installation_private_data_root(
        owner.layout, started.plan.installation_key
    )
    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    generation = _windows_arch_current_root_generation(
        started.plan.installation_key,
        root,
        owner.product.state_root,
        inspect_windows_product_private_directory_identity(owner.layout.package_root),
        allow_pending=True,
    )
    if generation.receipt is None or generation.identity != target_identity[:2]:
        raise ValueError("Windows Coding Arch tombstone root receipt changed")
    _native_io.require_tombstone_view(
        root,
        expected_parent=parent_identity,
        root_identity=target_identity,
        original=started.target,
        present=present,
        make_tombstone_name=lambda: _tombstone_name(started),
        capture=lambda path: _capture_windows_target_snapshot(
            path, expected_root=target_identity[:2]
        ),
    )


__all__ = [
    "CodingWindowsArchPrivateDataDeletionJournal",
    "CodingWindowsArchPrivateDataDeletionTransaction",
    "windows_arch_deletion_receipt_id",
]
