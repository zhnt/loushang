"""Offline Coding management client for one Arch Installation backup.

This client reopens the fenced Product and uses the same backup owner as the
operator CLI. Its methods require runtime quiescence; an active Session cannot
use it as an RPC command.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_private_data_backup import (
    CodingArchPrivateDataBackupOwner,
    CodingArchPrivateDataBackupReadSource,
    CodingArchPrivateDataBackupReceiptV1,
)
from loushang.coding.package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryOwner,
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from loushang.coding.package_private_data_read_owner import (
    CodingArchPrivateDataReadOwner,
)
from loushang.coding.package_private_data_restore import (
    CodingArchPrivateDataRestoreOwner,
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)
from loushang.coding.package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from loushang.coding.package_product_management_cli import (
    coding_fenced_product_exists,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionRecordV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

_PLUGIN_ID = "coding.arch.default"
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
        if (
            not isinstance(self.workspace, Path)
            or not self.workspace.is_absolute()
            or self.workspace != self.workspace.resolve(strict=True)
            or not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or self.layout
            != resolve_coding_plugin_lifecycle_state_layout(self.workspace)
            or type(self.workspace_identity) is not tuple
            or len(self.workspace_identity) != 2
            or any(
                type(item) is not int or item < 0 for item in self.workspace_identity
            )
        ):
            raise ValueError("Coding Arch backup workspace is invalid")

    @property
    def installation_key(self) -> PluginInstallationKeyV1:
        return PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=_PLUGIN_ID,
        )

    def retain(self) -> CodingArchPrivateDataBackupReceiptV1:
        """Retain or replay the archive for the current exact source snapshot."""

        with self._product() as product:
            return CodingArchPrivateDataBackupOwner(
                self.layout, product
            ).retain(self.installation_key)

    def verify(self, backup_id: str) -> CodingArchPrivateDataBackupReceiptV1:
        """Reopen and verify one retained archive by its exact digest."""

        with self._reader() as reader:
            return reader.verify_backup(self.installation_key, backup_id)

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
        if (
            os.name != "posix"
            or not sys.platform.startswith("linux")
            or not coding_fenced_product_exists(self.layout)
        ):
            raise ValueError("Coding Arch backup Product route is unavailable")
        layout = resolve_coding_package_epoch_layout(self.layout)
        epoch = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=layout.authority_root,
            control_root=layout.control_root,
            store_id=layout.store_id,
            epochs_root_name=layout.epochs_root_name,
            read_only=True,
        )
        try:
            self._assert_workspace_identity()
            [record] = (
                CodingArchPrivateDataBackupReadSource(self.layout, epoch)
                .snapshot()
                .records
            )
            if record.installation_key != self.installation_key:
                raise ValueError("Coding Arch backup status changed Installation")
            self._assert_workspace_identity()
            return record
        finally:
            epoch.close()

    def _open_application(self) -> CodingFencedProductApplicationOwner:
        self._assert_workspace_identity()
        if (
            os.name != "posix"
            or not sys.platform.startswith("linux")
            or not coding_fenced_product_exists(self.layout)
        ):
            raise ValueError("Coding Arch backup Product route is unavailable")
        application = open_coding_fenced_product_application_owner(
            self.layout,
            workspace=self.workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            self._assert_workspace_identity()
        except BaseException as error:
            try:
                application.close()
            except BaseException:
                error.add_note("Coding Arch backup Product cleanup also failed")
            raise
        return application

    def _assert_workspace_identity(self) -> None:
        try:
            metadata = self.workspace.lstat()
            current = self.workspace.resolve(strict=True)
        except OSError as exc:
            raise CodingArchPrivateDataBackupSdkError(
                "Coding Arch backup workspace changed",
                code="coding_arch_backup_workspace_changed",
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or current != self.workspace
            or (metadata.st_dev, metadata.st_ino) != self.workspace_identity
        ):
            raise CodingArchPrivateDataBackupSdkError(
                "Coding Arch backup workspace changed",
                code="coding_arch_backup_workspace_changed",
            )

    @contextmanager
    def _reader(self) -> Iterator[CodingArchPrivateDataReadOwner]:
        self._assert_workspace_identity()
        if (
            os.name != "posix"
            or not sys.platform.startswith("linux")
            or not coding_fenced_product_exists(self.layout)
        ):
            raise ValueError("Coding Arch backup Product route is unavailable")
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
        application = self._open_application()
        try:
            product = application.runtime_owner.product_owner
            if not isinstance(
                product, PosixLocalWheelProductSessionOwner
            ) or not isinstance(
                application.epoch_runtime, PackageProductPosixFencedRuntimeOwner
            ):
                raise ValueError("Coding Arch backup Product owner is unsupported")
            yield product
        finally:
            application.close()


def open_coding_arch_private_data_backup_client(
    workspace: str | Path,
) -> CodingArchPrivateDataBackupClientV1:
    root = Path(workspace).expanduser().resolve(strict=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Coding Arch backup workspace is unavailable")
    return CodingArchPrivateDataBackupClientV1(
        workspace=root,
        layout=resolve_coding_plugin_lifecycle_state_layout(root),
        workspace_identity=(metadata.st_dev, metadata.st_ino),
    )


__all__ = [
    "CodingArchPrivateDataBackupClientV1",
    "CodingArchPrivateDataBackupSdkError",
    "open_coding_arch_private_data_backup_client",
]
