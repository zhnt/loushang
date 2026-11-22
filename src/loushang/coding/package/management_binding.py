"""One-shot Coding CLI ports bound to the current fenced B management owners."""

from __future__ import annotations

import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._application_runtime import (
    open_read_only_product_management_state,
    private_product_state_identity,
    read_fenced_product_desired_transition,
    verify_handoff_desired_commit,
)
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
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
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

    with _ProductCliOwner(layout).scope(read_only=True) as (runtime, _):
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
    with owner.scope(read_only=True) as (runtime, ports):
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

    with _ProductCliOwner(layout).scope(read_only=True) as (runtime, _):
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
        return read_fenced_product_desired_transition(runtime, operation_id)
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

    return verify_handoff_desired_commit(
        handoff,
        read_transition=lambda command_id: read_coding_fenced_desired_transition(
            layout, command_id
        ),
    )


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
        from .private_data_backup import CodingArchPrivateDataBackupReadSource

        self.assert_workspace_current()
        epoch = resolve_coding_package_epoch_layout(self.layout)
        runtime = PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs(), read_only=read_only
        )
        try:
            self.assert_workspace_current()
            state_root = runtime.control_root / "product-state"
            if read_only:
                desired, management, load_policy = (
                    open_read_only_product_management_state(state_root)
                )
            else:
                runtime.prepare_product_state_root()
                state = open_coding_package_product_state(
                    self.layout, runtime, before_recovery=self.assert_workspace_current
                )
                desired = state.desired_state
                management = state.management
            retirement_intents = PluginRetirementIntentLedger(
                management.retirement_intent_journal_path,
                load_policy=load_policy if read_only else None,
            )
            retirement = PluginRetirementSetLedger(
                management.retirement_set_journal_path,
                retirement_intents=retirement_intents,
                load_policy=load_policy if read_only else None,
            )
            ports = PluginManagementApplicationPorts(
                commands=PluginManagementCommandApplication(management),
                queries=PluginManagementReadModelProjector(
                    desired_state=desired,
                    operations=management,
                    retirement=retirement,
                    source=_product_sources(
                        self.layout, runtime, desired, read_only=read_only
                    ),
                    backup_retention=CodingArchPrivateDataBackupReadSource(
                        self.layout, runtime
                    ),
                ),
            )
            runtime.assert_current()
            self.assert_workspace_current()
            return runtime, ports
        except BaseException:
            runtime.close()
            raise

    @contextmanager
    def scope(
        self, *, read_only: bool
    ) -> Iterator[
        tuple[PackageProductPosixFencedRuntimeOwner, PluginManagementApplicationPorts]
    ]:
        runtime, ports = self.open(read_only=read_only)
        try:
            yield runtime, ports
            runtime.assert_current()
            self.assert_workspace_current()
        finally:
            runtime.close()


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


@dataclass(frozen=True, slots=True)
class _ProductCliQueries:
    owner: _ProductCliOwner

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        with self.owner.scope(read_only=True) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.queries.snapshot(query)


@dataclass(frozen=True, slots=True)
class _ProductCliCommands:
    owner: _ProductCliOwner

    def submit(
        self, request: PluginManagementApplicationCommandV1
    ) -> PluginManagementApplicationResultV1:
        with self.owner.scope(read_only=False) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.commands.submit(request)

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        with self.owner.scope(read_only=True) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.commands.operation(operation_id, correlation_id=correlation_id)


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
