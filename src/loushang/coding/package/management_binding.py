"""One-shot Coding CLI ports bound to the current fenced B management owners."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256 as sha256
from pathlib import Path
from typing import Literal

from loushang.coding.harness.package_product import management as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.plugin_management import (
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationPorts,
    PluginManagementApplicationResultV1,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
    PluginManagementSourceSnapshotV1,
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
from loushang.harness.plugin_management.assembly import (
    bind_plugin_desired_state as bind_plugin_desired_state,
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
    PluginOperationExplanationProjector,
    PluginOperationExplanationV1,
)
from loushang.harness.plugin_management.package_operation_explanation import (
    PackageOperationExplanationProjector,
    PackageOperationExplanationV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger as PluginRetirementIntentLedger,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetLedger as PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import (
    PluginManagementService as PluginManagementService,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
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
    CodingExternalDataWheelBindingV1 as CodingExternalDataWheelBindingV1,
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


_RUNTIME_PROGRAM_VALUES = {
    "value_001": "Fenced Product management state is unsafe",
    "value_002": "Fenced Product management state is absent",
    "value_003": "gc-reservations.jsonl",
    "value_004": "desired-state.jsonl",
    "value_005": "management-operations.jsonl",
    "value_006": "coding-product-source:",
    "value_007": "coding",
    "value_008": "coding_product_not_fenced",
    "value_009": "coding_management_workspace_changed",
}


def explain_coding_fenced_package_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PackageOperationExplanationV1:
    """Read an existing A2 operation without activating or repairing Product."""

    with _programs.ManagementScope(_ProductCliOwner(layout), read_only=True) as (runtime, _):
        return PackageOperationExplanationProjector(
            PackageLifecycleJournal(
                runtime.control_root / "product-state" / "lifecycle.jsonl"
            )
        ).explain_operation(operation_id)


def explain_coding_fenced_plugin_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
    *,
    correlation_id: str,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginOperationExplanationV1:
    """Observe A2, handoff, and A1 within one inert fenced Product lease."""

    owner = _ProductCliOwner(layout, workspace_guard)
    with _programs.ManagementScope(owner, read_only=True) as (runtime, ports):
        state_root = runtime.control_root / "product-state"
        return PluginOperationExplanationProjector(
            package_operations=PackageLifecycleJournal(state_root / "lifecycle.jsonl"),
            management_commands=ports.commands,
            handoffs=PackageRetentionHandoffJournal(state_root / "handoff.jsonl"),
        ).explain_operation(operation_id, correlation_id=correlation_id)


def read_coding_fenced_package_handoff(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PackageRetentionHandoffReceiptV1 | None:
    """Observe one exact A2 handoff receipt without repairing its owner."""

    with _programs.ManagementScope(_ProductCliOwner(layout), read_only=True) as (runtime, _):
        return PackageRetentionHandoffJournal(
            runtime.control_root / "product-state" / "handoff.jsonl"
        ).read_operation(operation_id)


def read_coding_fenced_desired_transition(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PluginDesiredStateJournalTransition | None:
    """Read one exact Desired commit without repairing management or Product state."""

    runtime, _ports = _ProductCliOwner(layout).open(read_only=True)
    try:
        desired = PluginDesiredStateLedger(
            runtime.control_root / "product-state" / "desired-state.jsonl",
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        )
        _snapshot, transitions = desired.capture_read_only()
        matches = [
            transition
            for transition in transitions
            if transition.mutation.operation_id == operation_id
        ]
        runtime.assert_current()
        if len(matches) > 1:
            raise ValueError("Desired operation identity is ambiguous")
        return matches[0] if matches else None
    finally:
        runtime.close()


def read_coding_fenced_handoff_desired_commit(
    layout: CodingPluginLifecycleStateLayout,
    handoff: PackageRetentionHandoffReceiptV1,
) -> (
    tuple[int, dict[str, object], Literal["owner_receipt", "verified_transition"]]
    | None
):
    """Prove an exact Desired commit even before handoff settlement is journaled."""

    return _programs.read_handoff_desired_commit(layout, handoff)


@dataclass(frozen=True, slots=True)
class _ProductCliOwner:
    layout: CodingPluginLifecycleStateLayout
    workspace_guard: Callable[[], None] | None = None

    def assert_workspace_current(self) -> None:
        if self.workspace_guard is not None:
            self.workspace_guard()

    def open(
        self, *, read_only: bool
    ) -> tuple[
        PackageProductPosixFencedRuntimeOwner,
        PluginManagementApplicationPorts,
    ]:
        return _programs.open_management(self, read_only=read_only)


@dataclass(frozen=True, slots=True)
class _ProductSources:
    catalog: CodingExternalDataWheelCatalog
    desired_state: PluginDesiredStateLedger

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        return _programs.source_snapshot(self)


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
        source_metadata = source_root.lstat()
    except FileNotFoundError as exc:
        raise ValueError("Fenced Product Source root is absent") from exc
    if (
        not stat.S_ISDIR(source_metadata.st_mode)
        or stat.S_IMODE(source_metadata.st_mode) & 0o077
        or source_metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Fenced Product Source root is unsafe")
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


@dataclass(frozen=True, slots=True)
class _ProductCliQueries:
    owner: _ProductCliOwner

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        with _programs.ManagementScope(self.owner, read_only=True) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.queries.snapshot(query)


@dataclass(frozen=True, slots=True)
class _ProductCliCommands:
    owner: _ProductCliOwner

    def submit(
        self, request: PluginManagementApplicationCommandV1
    ) -> PluginManagementApplicationResultV1:
        with _programs.ManagementScope(self.owner, read_only=False) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.commands.submit(request)

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        with _programs.ManagementScope(self.owner, read_only=True) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.commands.operation(
                operation_id, correlation_id=correlation_id
            )


def build_coding_fenced_product_management_cli_ports(
    layout: CodingPluginLifecycleStateLayout,
    *,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginManagementApplicationPorts:
    owner = _ProductCliOwner(layout, workspace_guard)
    return PluginManagementApplicationPorts(
        commands=_ProductCliCommands(owner), queries=_ProductCliQueries(owner)
    )


def repair_coding_fenced_cli_desired_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
    *,
    workspace: Path,
    correlation_id: str,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginDesiredRepairResultV1:
    """Resume only a pending Desired State command issued by this CLI owner."""

    return _programs.repair_desired_operation(
        layout,
        operation_id,
        workspace=workspace,
        correlation_id=correlation_id,
        workspace_guard=workspace_guard,
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
