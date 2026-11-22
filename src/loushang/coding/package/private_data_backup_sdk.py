"""Offline Coding management client for one Arch Installation backup.

This client reopens the fenced Product and uses the same backup owner as the
operator CLI. Its methods require runtime quiescence; an active Session cannot
use it as an RPC command.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from loushang.coding.package.epoch_layout import (
    coding_fenced_product_exists,
    resolve_coding_package_epoch_layout,
)
from loushang.coding.package.installation_private_data import (
    coding_arch_workspace_installation_key,
)
from loushang.coding.package.private_data_backup import (
    CodingArchPrivateDataBackupOwner,
    CodingArchPrivateDataBackupReadSource,
    CodingArchPrivateDataBackupReceiptV1,
)
from loushang.coding.package.private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryOwner,
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package.private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from loushang.coding.package.private_data_read_owner import (
    CodingArchPrivateDataReadOwner,
)
from loushang.coding.package.private_data_restore import (
    CodingArchPrivateDataRestoreOwner,
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)
from loushang.coding.package.private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from loushang.coding.package.product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    matches_coding_workspace_layout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.package_product._application_runtime import handoff_product_open
from loushang.harness.package_product._private_data_custody import (
    hold_private_data_product,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionRecordV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.workspace.paths import (
    assert_workspace_directory_identity,
    capture_workspace_directory_identity,
    is_workspace_directory_identity,
)

_EXPIRY_POLICY_REVISION = "coding-arch-backup-expiry-sdk:1"


class CodingArchPrivateDataBackupSdkError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupClientV1:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_identity: tuple[int, int]

    def __post_init__(self) -> None:
        if not matches_coding_workspace_layout(
            self.workspace, self.layout
        ) or not is_workspace_directory_identity(self.workspace_identity):
            raise ValueError("Coding Arch backup workspace is invalid")

    @property
    def installation_key(self) -> PluginInstallationKeyV1:
        return coding_arch_workspace_installation_key(self.layout.scope_id)

    def retain(self) -> CodingArchPrivateDataBackupReceiptV1:
        """Retain or replay the archive for the current exact source snapshot."""

        with self._product() as product:
            return CodingArchPrivateDataBackupOwner(self.layout, product).retain(
                self.installation_key
            )

    def verify(self, backup_id: str) -> CodingArchPrivateDataBackupReceiptV1:
        """Reopen and verify one retained archive by its exact digest."""

        with self._reader() as reader:
            return reader.verify_backup(self.installation_key, backup_id)

    def _preview_deletion(self) -> PluginPrivateDataDeletionPlanV1:
        with self._reader() as reader:
            return reader.deletion_preview(self.installation_key)

    def restore_preview(self, backup_id: str) -> CodingArchPrivateDataRestorePlanV1:
        """Read a removed Installation's exact restore plan."""

        with self._reader() as reader:
            return reader.restore_preview(self.installation_key, backup_id)

    def restore(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Apply one explicitly supplied plan under the offline Product fence."""

        if (
            not isinstance(plan, CodingArchPrivateDataRestorePlanV1)
            or plan.installation_key != self.installation_key
        ):
            raise ValueError("Coding Arch restore plan is foreign")
        with self._product() as product:
            return CodingArchPrivateDataRestoreOwner(self.layout, product).restore(
                self.installation_key, plan.backup_id, expected_plan=plan
            )

    def confirm_restore(
        self, backup_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Verify a completed restore and record its exact confirmation."""

        with self._product() as product:
            return CodingArchPrivateDataRestoreOwner(self.layout, product).confirm(
                self.installation_key, backup_id
            )

    def verify_restore_confirmation(
        self, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Reopen a confirmation against current restored and archive bytes."""

        with self._reader() as reader:
            return reader.verify_restore_confirmation(
                self.installation_key, backup_id, confirmation_id
            )

    def expiry_preview(
        self, backup_id: str, restore_confirmation_id: str
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        """Read the exact archive-expiry plan after a confirmed restore."""

        with self._reader() as reader:
            return reader.expiry_preview(
                self.installation_key, backup_id, restore_confirmation_id
            )

    def confirm_expiry(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        """Record a separate local-operator acceptance of one current plan."""

        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or plan.installation_key != self.installation_key
        ):
            raise ValueError("Coding Arch backup expiry plan is foreign")
        with self._product() as product:
            return CodingArchPrivateDataBackupExpiryOwner(self.layout, product).confirm(
                plan,
                actor_id=f"local-uid:{os.geteuid()}",
                policy_revision=_EXPIRY_POLICY_REVISION,
            )

    def expire(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        """Expire only one independently confirmed archive with durable replay."""

        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or plan.installation_key != self.installation_key
        ):
            raise ValueError("Coding Arch backup expiry plan is foreign")
        with self._product() as product:
            return CodingArchPrivateDataBackupExpiryOwner(self.layout, product).expire(
                plan, confirmation
            )

    def status(self) -> PluginBackupRetentionRecordV1:
        """Read the backup owner's typed status without changing retention."""

        self._assert_workspace_identity()
        _require_backup_product_route(self.layout)
        layout = resolve_coding_package_epoch_layout(self.layout)
        with PackageProductPosixFencedRuntimeOwner.open(
            **layout.fenced_runtime_open_kwargs(), read_only=True
        ) as epoch:
            self._assert_workspace_identity()
            [record] = CodingArchPrivateDataBackupReadSource(
                self.layout, epoch
            ).snapshot().records
            if record.installation_key != self.installation_key:
                raise ValueError("Coding Arch backup status changed Installation")
            self._assert_workspace_identity()
            return record

    def _open_application(self) -> CodingFencedProductApplicationOwner:
        self._assert_workspace_identity()
        _require_backup_product_route(self.layout)
        application = open_coding_fenced_product_application_owner(
            self.layout,
            workspace=self.workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        with handoff_product_open(
            application, cleanup_note="Coding Arch backup Product cleanup also failed"
        ):
            self._assert_workspace_identity()
        return application

    def _assert_workspace_identity(self) -> None:
        assert_workspace_directory_identity(
            self.workspace,
            self.workspace_identity,
            changed=lambda: CodingArchPrivateDataBackupSdkError(
                "Coding Arch backup workspace changed",
                code="coding_arch_backup_workspace_changed",
            ),
        )

    @contextmanager
    def _reader(self) -> Iterator[CodingArchPrivateDataReadOwner]:
        self._assert_workspace_identity()
        _require_backup_product_route(self.layout)
        reader = CodingArchPrivateDataReadOwner.open(
            layout=self.layout,
            workspace=self.workspace,
            workspace_identity=self.workspace_identity,
        )
        try:
            yield reader
        finally:
            try:
                self._assert_workspace_identity()
            finally:
                reader.close()

    @contextmanager
    def _product(self) -> Iterator[PosixLocalWheelProductSessionOwner]:
        with hold_private_data_product(
            self._open_application(),
            PosixLocalWheelProductSessionOwner,
            PackageProductPosixFencedRuntimeOwner,
            error="Coding Arch backup Product owner is unsupported",
        ) as product:
            yield product


def _require_backup_product_route(layout: CodingPluginLifecycleStateLayout) -> None:
    if (
        os.name != "posix"
        or not sys.platform.startswith("linux")
        or not coding_fenced_product_exists(layout)
    ):
        raise ValueError("Coding Arch backup Product route is unavailable")


def open_coding_arch_private_data_backup_client(
    workspace: str | Path,
) -> CodingArchPrivateDataBackupClientV1:
    root = Path(workspace).expanduser().resolve(strict=True)
    identity = capture_workspace_directory_identity(
        root, unavailable="Coding Arch backup workspace is unavailable"
    )
    return CodingArchPrivateDataBackupClientV1(
        workspace=root,
        layout=resolve_coding_plugin_lifecycle_state_layout(root),
        workspace_identity=identity,
    )


__all__ = [
    "CodingArchPrivateDataBackupClientV1",
    "CodingArchPrivateDataBackupSdkError",
    "open_coding_arch_private_data_backup_client",
]
