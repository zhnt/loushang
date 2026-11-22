"""One-shot Coding CLI ports bound to the current fenced B management owners."""

from __future__ import annotations

import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._application_runtime import (
    FencedProductManagementApplication,
    private_product_state_identity,
    verify_handoff_desired_commit,
)
from loushang.harness.plugin_management import (
    PluginBackupRetentionProjectionSourcePort,
    PluginManagementApplicationPorts,
    PluginManagementSourceSnapshotV1,
)
from loushang.harness.plugin_management import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.plugin_management import (
    PluginManagementCommandApplication as PluginManagementCommandApplication,
)
from loushang.harness.plugin_management import (
    PluginManagementReadModelProjector as PluginManagementReadModelProjector,
)
from loushang.harness.plugin_management import (
    PluginManagementSourceRecordV1 as PluginManagementSourceRecordV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandAuthorityV1 as PluginDesiredCommandAuthorityV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredRepairResultV1,
)
from loushang.harness.plugin_management.desired_command import (
    resume_plugin_desired_operation as resume_plugin_desired_operation,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationV1,
)
from loushang.harness.plugin_management.package_operation_explanation import (
    PackageOperationExplanationV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger as PluginRetirementIntentLedger,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetLedger as PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffReceiptV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    coding_fenced_product_exists as coding_fenced_product_exists,
)
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .external_data_wheel import (
    CodingExternalDataWheelCatalog,
)
from .external_data_wheel import (
    CodingExternalDataWheelError as CodingExternalDataWheelError,
)
from .product_runtime import (
    open_coding_package_product_state as open_coding_package_product_state,
)

CODING_CLI_MANAGEMENT_ACTOR_ID = "coding:cli"
CODING_CLI_MANAGEMENT_POLICY_REVISION = "coding-plugin-management-cli-v1"


def explain_coding_fenced_package_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PackageOperationExplanationV1:
    """Read an existing A2 operation without activating or repairing Product."""

    return _ProductCliOwner(layout).explain_package_operation(operation_id)


def explain_coding_fenced_plugin_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
    *,
    correlation_id: str,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginOperationExplanationV1:
    """Observe A2, handoff, and A1 within one inert fenced Product lease."""

    return _ProductCliOwner(layout, workspace_guard).explain_plugin_operation(
        operation_id, correlation_id=correlation_id
    )


def read_coding_fenced_package_handoff(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PackageRetentionHandoffReceiptV1 | None:
    """Observe one exact A2 handoff receipt without repairing its owner."""

    return _ProductCliOwner(layout).read_package_handoff(operation_id)


def read_coding_fenced_desired_transition(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PluginDesiredStateJournalTransition | None:
    """Read one exact Desired commit without repairing management or Product state."""

    return _ProductCliOwner(layout).read_desired_transition(operation_id)


def read_coding_fenced_handoff_desired_commit(
    layout: CodingPluginLifecycleStateLayout,
    handoff: PackageRetentionHandoffReceiptV1,
) -> (
    tuple[int, dict[str, object], Literal["owner_receipt", "verified_transition"]]
    | None
):
    """Prove an exact Desired commit even before handoff settlement is journaled."""

    return verify_handoff_desired_commit(
        handoff,
        read_transition=lambda command_id: read_coding_fenced_desired_transition(
            layout, command_id
        ),
    )


@dataclass(frozen=True, slots=True)
class _ProductCliOwner(FencedProductManagementApplication):
    layout: CodingPluginLifecycleStateLayout
    workspace_guard: Callable[[], None] | None = None

    def _open_epoch(self, *, read_only: bool) -> PackageProductPosixFencedRuntimeOwner:
        epoch = resolve_coding_package_epoch_layout(self.layout)
        return PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs(), read_only=read_only
        )

    def _open_write_state(
        self, runtime: PackageProductPosixFencedRuntimeOwner
    ) -> tuple[PluginDesiredStateLedger, PluginManagementService]:
        state = open_coding_package_product_state(
            self.layout, runtime, before_recovery=self.assert_workspace_current
        )
        return state.desired_state, state.management

    def _source(
        self,
        runtime: PackageProductPosixFencedRuntimeOwner,
        desired: PluginDesiredStateLedger,
        *,
        read_only: bool,
    ) -> _ProductSources:
        return _product_sources(self.layout, runtime, desired, read_only=read_only)

    def _backup_retention(
        self, runtime: PackageProductPosixFencedRuntimeOwner
    ) -> PluginBackupRetentionProjectionSourcePort:
        from .private_data_backup import CodingArchPrivateDataBackupReadSource

        return CodingArchPrivateDataBackupReadSource(self.layout, runtime)


@dataclass(frozen=True, slots=True)
class _ProductSources:
    catalog: CodingExternalDataWheelCatalog
    desired_state: PluginDesiredStateLedger

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        return self.catalog.project_management_source_snapshot(
            self.desired_state,
            owner_revision_prefix="coding-product-source:",
            verify_record=self.catalog.verify_record,
            verification_error=CodingExternalDataWheelError,
        )


def _product_sources(
    layout: CodingPluginLifecycleStateLayout,
    runtime: PackageProductPosixFencedRuntimeOwner,
    desired_state: PluginDesiredStateLedger,
    *,
    read_only: bool = False,
) -> _ProductSources:
    switch = runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError("Fenced Product Source namespace is unavailable")
    source_root = runtime.control_root / "product-sources"
    try:
        private_product_state_identity(
            source_root, unsafe_message="Fenced Product Source root is unsafe"
        )
    except FileNotFoundError as exc:
        raise ValueError("Fenced Product Source root is absent") from exc
    if not read_only:
        runtime.prepare_product_source_root()
    return _ProductSources(
        CodingExternalDataWheelCatalog(
            runtime.control_root
            / "product-state"
            / "external-data-wheel-bindings.jsonl",
            source_root=source_root,
            store_id=runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=layout.scope_id,
            read_only=read_only,
        ),
        desired_state,
    )


def build_coding_fenced_product_management_cli_ports(
    layout: CodingPluginLifecycleStateLayout,
    *,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginManagementApplicationPorts:
    return _ProductCliOwner(layout, workspace_guard).bind_ports()


def repair_coding_fenced_cli_desired_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
    *,
    workspace: Path,
    correlation_id: str,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginDesiredRepairResultV1:
    """Resume only a pending Desired State command issued by this CLI owner."""

    if workspace_guard is not None:
        workspace_guard()
    if not coding_fenced_product_exists(layout):
        raise ValueError("coding_product_not_fenced")
    identity = workspace.lstat()
    if (
        not stat.S_ISDIR(identity.st_mode)
        or workspace.resolve(strict=True) != workspace
    ):
        raise ValueError("coding_management_workspace_changed")

    def assert_workspace_current() -> None:
        if workspace_guard is not None:
            workspace_guard()
        try:
            current = workspace.lstat()
            if (current.st_dev, current.st_ino) != (
                identity.st_dev,
                identity.st_ino,
            ) or workspace.resolve(strict=True) != workspace:
                raise ValueError("coding_management_workspace_changed")
        except OSError as error:
            raise ValueError("coding_management_workspace_changed") from error
        if workspace_guard is not None:
            workspace_guard()

    return resume_plugin_desired_operation(
        build_coding_fenced_product_management_cli_ports(
            layout, workspace_guard=assert_workspace_current
        ),
        PluginDesiredCommandAuthorityV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=layout.scope_id,
            actor_id=CODING_CLI_MANAGEMENT_ACTOR_ID,
            policy_revision=CODING_CLI_MANAGEMENT_POLICY_REVISION,
        ),
        operation_id=operation_id,
        correlation_id=correlation_id,
    )


__all__ = [
    "CODING_CLI_MANAGEMENT_ACTOR_ID",
    "CODING_CLI_MANAGEMENT_POLICY_REVISION",
    "build_coding_fenced_product_management_cli_ports",
    "coding_fenced_product_exists",
    "explain_coding_fenced_package_operation",
    "explain_coding_fenced_plugin_operation",
    "read_coding_fenced_package_handoff",
    "read_coding_fenced_desired_transition",
    "read_coding_fenced_handoff_desired_commit",
    "repair_coding_fenced_cli_desired_operation",
]
