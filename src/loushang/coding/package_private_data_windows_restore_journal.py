"""Native Product-private start/completion receipts for Windows Arch restore.

The journal records recovery state under one offline Product gate. It never
publishes archive bytes or creates a private-data root by itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_restore_windows import (
    WindowsPrivateRestoreTransaction,
)
from loushang.harness.plugin_management.private_data_deletion import (
    latest_deleted_target_receipt,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    _prepare_windows_arch_restore_generation_intent,
    _publish_windows_arch_restored_root_receipt,
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_legacy_windows_receipt import (
    _MAX_RECEIPT_BYTES,
    _receipt_io,
)
from .package_private_data_backup_records import backup_parent
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
)
from .package_private_data_restore_records import CodingArchPrivateDataRestorePlanV1
from .package_private_data_windows_backup import (
    _archive_io,
)
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _native_io,
)

_EVENT_PREFIX = "arch-private-restore-"
_EVENT_NAME = re.compile(r"arch-private-restore-([0-9]{8})\.json(\.stage)?\Z")
_MAX_EVENTS = 4096
_MAX_EVENT_BYTES = 16 * 1024
_PUBLICATION_PREFIX = "arch-restore-publication-"
_PUBLICATION_MAX_BYTES = 4096
_CONFIRM_PREFIX = "arch-restore-confirmation-"
_CONFIRM_NAME = re.compile(r"arch-restore-confirmation-([0-9]{8})\.json(\.stage)?\Z")
_CONFIRM_MAX_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchRestorePublicationV1:
    restore_id: str
    started_digest: str
    plan_fingerprint: str
    desired_inventory_revision: int
    generation_number: int
    stage_identity: tuple[int, int, int, int, int]
    parent_identity: tuple[int, int]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.restore_id, str)
            or not re.fullmatch(r"arch-restore:[0-9a-f]{64}", self.restore_id)
            or not isinstance(self.started_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.started_digest)
            or not isinstance(self.plan_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.plan_fingerprint)
            or type(self.desired_inventory_revision) is not int
            or self.desired_inventory_revision < 0
            or type(self.generation_number) is not int
            or not 2 <= self.generation_number <= 4097
            or type(self.stage_identity) is not tuple
            or len(self.stage_identity) != 5
            or any(type(value) is not int or value < 0 for value in self.stage_identity)
            or type(self.parent_identity) is not tuple
            or len(self.parent_identity) != 2
            or any(
                type(value) is not int or value < 0 for value in self.parent_identity
            )
        ):
            raise ValueError("Windows Coding Arch restore publication is invalid")

    @property
    def stage_name(self) -> str:
        return ".arch-restore-" + self.restore_id.split(":", 1)[1] + ".staging"

    def to_dict(self) -> dict[str, object]:
        return {
            "desiredInventoryRevision": self.desired_inventory_revision,
            "generationNumber": self.generation_number,
            "parentIdentity": list(self.parent_identity),
            "planFingerprint": self.plan_fingerprint,
            "restoreId": self.restore_id,
            "stageIdentity": list(self.stage_identity),
            "startedDigest": self.started_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsArchRestorePublicationV1:
        if type(value) is not dict or set(value) != {
            "desiredInventoryRevision",
            "generationNumber",
            "parentIdentity",
            "planFingerprint",
            "restoreId",
            "stageIdentity",
            "startedDigest",
        }:
            raise ValueError("Windows Coding Arch restore publication fields changed")
        parent = value["parentIdentity"]
        stage = value["stageIdentity"]
        if type(parent) is not list or type(stage) is not list:
            raise ValueError("Windows Coding Arch restore publication identity changed")
        return cls(
            restore_id=value["restoreId"],
            started_digest=value["startedDigest"],
            plan_fingerprint=value["planFingerprint"],
            desired_inventory_revision=value["desiredInventoryRevision"],
            generation_number=value["generationNumber"],
            stage_identity=tuple(stage),
            parent_identity=tuple(parent),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestoreJournal:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        if (
            self.product.state_root
            != resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        ):
            raise ValueError("Windows Coding Arch restore Product state changed")

    @contextmanager
    def transaction(self) -> Iterator[CodingWindowsArchPrivateDataRestoreTransaction]:
        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Windows Coding Arch restore runtime is active")
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard(require_write=True):
                with (
                    self.product.epoch_runtime.borrow_product_state_root_descriptor() as fd
                ):
                    transaction = CodingWindowsArchPrivateDataRestoreTransaction(
                        self.layout, self.product, fd
                    )
                    try:
                        yield transaction
                    finally:
                        transaction._close()
            self.product.assert_root_gc_authority_current()


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestoreTransaction(
    WindowsPrivateRestoreTransaction[
        CodingArchPrivateDataRestorePlanV1,
        CodingArchPrivateDataRestoreEventV1,
        CodingArchPrivateDataRestoreConfirmationV1,
        CodingArchPrivateDataTargetSnapshotV1,
        CodingWindowsArchRestorePublicationV1,
    ]
):
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner
    state_fd: int
    _active: bool = field(default=True, init=False, repr=False, compare=False)

    _label: ClassVar[str] = "Windows Coding Arch"
    _event_prefix: ClassVar[str] = _EVENT_PREFIX
    _event_name: ClassVar[re.Pattern[str]] = _EVENT_NAME
    _publication_prefix: ClassVar[str] = _PUBLICATION_PREFIX
    _confirmation_prefix: ClassVar[str] = _CONFIRM_PREFIX
    _confirmation_name: ClassVar[re.Pattern[str]] = _CONFIRM_NAME
    _restore_stage_prefix: ClassVar[str] = ".arch-restore-"
    _restore_stage_suffix: ClassVar[str] = ".staging"
    _max_events: ClassVar[int] = _MAX_EVENTS
    _max_event_bytes: ClassVar[int] = _MAX_EVENT_BYTES
    _publication_max_bytes: ClassVar[int] = _PUBLICATION_MAX_BYTES
    _confirmation_max_bytes: ClassVar[int] = _CONFIRM_MAX_BYTES
    _writer_max_bytes: ClassVar[int] = _MAX_RECEIPT_BYTES
    _receipt_io: ClassVar[WindowsPrivateReceiptIO] = _receipt_io
    _tree_io: ClassVar[PrivateWindowsTreeIO] = _native_io

    @property
    def _state_root(self) -> Path:
        return self.product.state_root

    @property
    def _plan_type(self) -> type[CodingArchPrivateDataRestorePlanV1]:
        return CodingArchPrivateDataRestorePlanV1

    @property
    def _event_type(self) -> type[CodingArchPrivateDataRestoreEventV1]:
        return CodingArchPrivateDataRestoreEventV1

    @property
    def _confirmation_type(self) -> type[CodingArchPrivateDataRestoreConfirmationV1]:
        return CodingArchPrivateDataRestoreConfirmationV1

    @property
    def _source_type(self) -> type[CodingArchPrivateDataTargetSnapshotV1]:
        return CodingArchPrivateDataTargetSnapshotV1

    @property
    def _publication_type(self) -> type[CodingWindowsArchRestorePublicationV1]:
        return CodingWindowsArchRestorePublicationV1

    def _root_for(self, key: PluginInstallationKeyV1) -> Path:
        return coding_arch_installation_private_data_root(self.layout, key)

    def _inspect_bound_root(
        self, key: PluginInstallationKeyV1
    ) -> tuple[int, int] | None:
        return inspect_coding_windows_arch_installation_root(
            self.layout, key, state_root=self.product.state_root
        )

    def _capture_root(
        self, root: Path, *, expected_root: tuple[int, int]
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        return _capture_windows_target_snapshot(root, expected_root=expected_root)

    def _require_plan_current(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        desired, transitions = self.product.desired_state.capture()
        state = desired.installation(plan.installation_key)
        if (
            state.latest_instance_revision_ref is None
            or state.selection.desired_state != "absent"
            or desired.inventory_revision < plan.desired_inventory_revision
            or any(
                transition.inventory_revision > plan.desired_inventory_revision
                and transition.mutation.installation_key == plan.installation_key
                for transition in transitions
            )
        ):
            raise ValueError("Windows Coding Arch restore Product state changed")
        deletion = CodingWindowsArchPrivateDataDeletionTransaction(
            self.product.state_root, self.state_fd
        )
        try:
            events = deletion.events()
        finally:
            deletion._close()
        if events and events[-1].phase != "completed":
            raise ValueError("Windows Coding Arch deletion is unfinished")
        receipt = _latest_deletion_receipt(events, plan)
        if receipt != plan.deletion_receipt_id:
            raise ValueError("Windows Coding Arch restore deletion changed")
        return self._verify_plan_archive(plan)

    def _verify_plan_archive(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        return _archive_io.read_restore_source(
            backup_parent(self.layout, plan.installation_key),
            plan.backup_id,
            plan.installation_key,
            label=self._label,
            source_matches=lambda source: source.target_id == plan.source_target_id,
        )

    def _prepare_root_generation(self, plan: CodingArchPrivateDataRestorePlanV1) -> int:
        return _prepare_windows_arch_restore_generation_intent(
            self.layout,
            plan.installation_key,
            state_root=self.product.state_root,
            deletion_receipt_id=plan.deletion_receipt_id,
        )

    def _publish_root_generation(
        self,
        plan: CodingArchPrivateDataRestorePlanV1,
        publication: CodingWindowsArchRestorePublicationV1,
    ) -> None:
        _publish_windows_arch_restored_root_receipt(
            self.layout,
            plan.installation_key,
            state_root=self.product.state_root,
            generation_number=publication.generation_number,
            deletion_receipt_id=plan.deletion_receipt_id,
            expected_identity=publication.stage_identity[:2],
        )

    def _copy_archive_to_stage(
        self,
        plan: CodingArchPrivateDataRestorePlanV1,
        source: CodingArchPrivateDataTargetSnapshotV1,
        stage_fd: int,
    ) -> None:
        _archive_io.copy_restore_source(
            backup_parent(self.layout, plan.installation_key),
            plan.backup_id,
            source,
            stage_fd,
            label=self._label,
        )


def _latest_deletion_receipt(
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...],
    plan: CodingArchPrivateDataRestorePlanV1,
) -> str | None:
    receipt = latest_deleted_target_receipt(
        events, plan.installation_key, plan.source_target_id
    )
    return None if receipt is None else receipt.receipt_id


__all__ = [
    "CodingWindowsArchPrivateDataRestoreJournal",
    "CodingWindowsArchPrivateDataRestoreTransaction",
]
