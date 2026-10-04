"""Explicit, offline Windows candidate client for Coding Arch private data.

This entry point does not select the ordinary Windows management route. It
reopens the fenced Product for each operation. Deletion requires a separately
recorded confirmation; restore requires the exact preview plan. All writes
remain candidates until native Windows proof is accepted.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.application import PluginBackupRetentionRecordV1
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationRecordV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_backup_records import CodingArchPrivateDataBackupReceiptV1
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .package_private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)
from .package_private_data_windows_backup import CodingWindowsArchPrivateDataBackupOwner
from .package_private_data_windows_backup_expiry_owner import (
    CodingWindowsArchPrivateDataBackupExpiryOwner,
)
from .package_private_data_windows_backup_expiry_preview import (
    CodingWindowsArchPrivateDataBackupExpiryPreview,
)
from .package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from .package_private_data_windows_deletion_owner import (
    CodingWindowsArchPrivateDataDeletionOwner,
)
from .package_private_data_windows_restore_owner import (
    CodingWindowsArchPrivateDataRestoreOwner,
)
from .package_private_data_windows_restore_preview import (
    CodingWindowsArchPrivateDataRestorePreview,
)
from .package_product_management_cli import coding_fenced_product_exists
from .package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)

_DELETION_OWNER_ID = "coding.arch.private-data:windows-v1"


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupCandidateClientV1:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_identity: tuple[int, int]
    runtime_version: str
    runtime_protocol_epoch: int

    def __post_init__(self) -> None:
        if (
            os.name != "nt"
            or not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or self.layout.scope_id
            != resolve_coding_plugin_lifecycle_state_layout(self.workspace).scope_id
            or not self.workspace.is_absolute()
            or self.workspace != self.workspace.resolve(strict=True)
            or type(self.runtime_version) is not str
            or not self.runtime_version
            or type(self.runtime_protocol_epoch) is not int
            or self.runtime_protocol_epoch < 1
        ):
            raise ValueError("Windows Coding Arch backup candidate is unavailable")
        self._assert_workspace_identity()

    @property
    def installation_key(self) -> PluginInstallationKeyV1:
        return PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id="coding.arch.default",
        )

    def retain(self) -> CodingArchPrivateDataBackupReceiptV1:
        """Retain the current exact source under the Product offline gate."""

        with self._owner() as owner:
            return owner.retain(self.installation_key)

    def verify(self, backup_id: str) -> CodingArchPrivateDataBackupReceiptV1:
        """Reopen and verify one exact archive, even if source bytes are absent."""

        with self._owner() as owner:
            return owner.verify(self.installation_key, backup_id)

    def status(self) -> PluginBackupRetentionRecordV1:
        """Read the conservative Product backup projection."""

        with self._owner() as owner:
            [record] = owner.snapshot().records
            if record.installation_key != self.installation_key:
                raise ValueError("Windows Coding Arch backup status changed")
            return record

    def deletion_preview(self) -> PluginPrivateDataDeletionPlanV1:
        """Read one exact Arch deletion target through the fenced Product."""

        with self._owner() as owner:
            return CodingWindowsArchPrivateDataConfirmationOwner(
                owner.layout, owner.product
            ).plan_for(self.installation_key)

    def deletion_confirm(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> PluginPrivateDataConfirmationRecordV1:
        """Record separate operator acceptance of an unchanged target."""

        self._require_deletion_command(plan, confirmation)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataConfirmationOwner(
                owner.layout, owner.product
            ).record_confirmation(
                plan,
                confirmation,
                actor_id=actor_id,
                policy_revision=policy_revision,
            )

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        """Resume or finish only the separately confirmed removed Installation."""

        self._require_deletion_command(plan, confirmation)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataDeletionOwner(
                owner.layout, owner.product
            ).delete_confirmed(plan, confirmation)

    def restore_preview(self, backup_id: str) -> CodingArchPrivateDataRestorePlanV1:
        """Reopen Product and verify deletion, archive, and absent target."""

        with self._owner() as owner:
            return CodingWindowsArchPrivateDataRestorePreview(
                owner.layout, owner.product
            ).preview(self.installation_key, backup_id)

    def restore(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Write only the exact offline backup selected by a prior preview."""

        self._require_restore_plan(plan)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataRestoreOwner(
                owner.layout, owner.product
            ).restore(plan)

    def restore_confirm(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Independently confirm completed restore and current exact bytes."""

        self._require_restore_plan(plan)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataRestoreOwner(
                owner.layout, owner.product
            ).confirm(plan)

    def restore_confirm_verify(
        self, plan: CodingArchPrivateDataRestorePlanV1, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        self._require_restore_plan(plan)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataRestoreOwner(
                owner.layout, owner.product
            ).verify_confirmation(plan, confirmation_id)

    def backup_expiry_preview(
        self, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        """Read the exact archive and independent restore confirmation."""

        with self._owner() as owner:
            return CodingWindowsArchPrivateDataBackupExpiryPreview(
                owner.layout, owner.product
            ).preview(self.installation_key, backup_id, confirmation_id)

    def backup_expiry_confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        """Record separate operator acceptance of the exact current archive."""

        self._require_expiry_plan(plan)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataBackupExpiryOwner(
                owner.layout, owner.product
            ).confirm(plan, actor_id=actor_id, policy_revision=policy_revision)

    def backup_expire(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        """Resume or complete one independently confirmed archive expiry."""

        self._require_expiry_plan(plan)
        with self._owner() as owner:
            return CodingWindowsArchPrivateDataBackupExpiryOwner(
                owner.layout, owner.product
            ).expire(plan, confirmation)

    def _require_expiry_plan(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> None:
        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or plan.installation_key != self.installation_key
        ):
            raise ValueError("Windows Coding Arch backup expiry plan is foreign")

    def _require_deletion_command(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or plan.installation_key != self.installation_key
            or plan.owner_id != _DELETION_OWNER_ID
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch deletion command is foreign")

    def _require_restore_plan(self, plan: CodingArchPrivateDataRestorePlanV1) -> None:
        if (
            not isinstance(plan, CodingArchPrivateDataRestorePlanV1)
            or plan.installation_key != self.installation_key
            or plan.target_state != "absent"
        ):
            raise ValueError("Windows Coding Arch restore plan is foreign")

    @contextmanager
    def _owner(self) -> Iterator[CodingWindowsArchPrivateDataBackupOwner]:
        self._assert_workspace_identity()
        if not coding_fenced_product_exists(self.layout):
            raise ValueError("Windows Coding Arch backup Product fence is absent")
        application = open_coding_fenced_product_application_owner(
            self.layout,
            workspace=self.workspace,
            runtime_version=self.runtime_version,
            runtime_protocol_epoch=self.runtime_protocol_epoch,
            windows_candidate=True,
        )
        try:
            product = application.runtime_owner.product_owner
            if not isinstance(
                product, WindowsLocalWheelProductSessionOwner
            ) or not isinstance(
                application.epoch_runtime, PackageProductWindowsFencedRuntimeOwner
            ):
                raise ValueError("Windows Coding Arch backup Product owner changed")
            owner = CodingWindowsArchPrivateDataBackupOwner(self.layout, product)
            yield owner
            self._assert_workspace_identity()
        finally:
            application.close()

    def _assert_workspace_identity(self) -> None:
        metadata = self.workspace.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or self.workspace.resolve(strict=True) != self.workspace
            or (metadata.st_dev, metadata.st_ino) != self.workspace_identity
        ):
            raise ValueError("Windows Coding Arch backup workspace changed")


def open_coding_windows_arch_backup_candidate_client(
    workspace: str | Path,
    *,
    layout: CodingPluginLifecycleStateLayout | None = None,
    runtime_version: str | None = None,
    runtime_protocol_epoch: int = CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
) -> CodingWindowsArchBackupCandidateClientV1:
    root = Path(workspace).expanduser().resolve(strict=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Windows Coding Arch backup workspace is unavailable")
    return CodingWindowsArchBackupCandidateClientV1(
        workspace=root,
        layout=layout or resolve_coding_plugin_lifecycle_state_layout(root),
        workspace_identity=(metadata.st_dev, metadata.st_ino),
        runtime_version=runtime_version or version("loushang"),
        runtime_protocol_epoch=runtime_protocol_epoch,
    )


__all__ = [
    "CodingWindowsArchBackupCandidateClientV1",
    "open_coding_windows_arch_backup_candidate_client",
]
