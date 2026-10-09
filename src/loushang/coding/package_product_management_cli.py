"""One-shot Coding CLI ports bound to the current fenced B management owners."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management import (
    PluginInstallationKeyV1,
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationPorts,
    PluginManagementApplicationResultV1,
    PluginManagementCommandApplication,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
    PluginManagementReadModelProjector,
    PluginManagementSourceRecordV1,
    PluginManagementSourceSnapshotV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandAuthorityV1,
    PluginDesiredRepairResultV1,
    resume_plugin_desired_operation,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationProjector,
    PluginOperationExplanationV1,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_operation_explanation import (
    PackageOperationExplanationProjector,
    PackageOperationExplanationV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffReceiptV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_external_data_wheel import (
    CodingExternalDataWheelBindingV1,
    CodingExternalDataWheelCatalog,
    CodingExternalDataWheelError,
)
from .package_product_runtime import open_coding_package_product_state

CODING_CLI_MANAGEMENT_ACTOR_ID = "coding:cli"
CODING_CLI_MANAGEMENT_POLICY_REVISION = "coding-plugin-management-cli-v1"


def coding_fenced_product_exists(layout: CodingPluginLifecycleStateLayout) -> bool:
    """Only an existing fence selects B; malformed existing B fails closed later."""

    epoch = resolve_coding_package_epoch_layout(layout)
    try:
        (epoch.control_root / "epoch.jsonl").lstat()
    except FileNotFoundError:
        return False
    return True


def explain_coding_fenced_package_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PackageOperationExplanationV1:
    """Read an existing A2 operation without activating or repairing Product."""

    runtime, _ports = _ProductCliOwner(layout).open(read_only=True)
    try:
        result = PackageOperationExplanationProjector(
            PackageLifecycleJournal(
                runtime.control_root / "product-state" / "lifecycle.jsonl"
            )
        ).explain_operation(operation_id)
        runtime.assert_current()
        return result
    finally:
        runtime.close()


def explain_coding_fenced_plugin_operation(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
    *,
    correlation_id: str,
    workspace_guard: Callable[[], None] | None = None,
) -> PluginOperationExplanationV1:
    """Observe A2, handoff, and A1 within one inert fenced Product lease."""

    runtime, ports = _ProductCliOwner(layout, workspace_guard).open(read_only=True)
    try:
        state_root = runtime.control_root / "product-state"
        result = PluginOperationExplanationProjector(
            package_operations=PackageLifecycleJournal(state_root / "lifecycle.jsonl"),
            management_commands=ports.commands,
            handoffs=PackageRetentionHandoffJournal(state_root / "handoff.jsonl"),
        ).explain_operation(operation_id, correlation_id=correlation_id)
        runtime.assert_current()
        if workspace_guard is not None:
            workspace_guard()
        return result
    finally:
        runtime.close()


def read_coding_fenced_package_handoff(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> PackageRetentionHandoffReceiptV1 | None:
    """Observe one exact A2 handoff receipt without repairing its owner."""

    runtime, _ports = _ProductCliOwner(layout).open(read_only=True)
    try:
        result = PackageRetentionHandoffJournal(
            runtime.control_root / "product-state" / "handoff.jsonl"
        ).read_operation(operation_id)
        runtime.assert_current()
        return result
    finally:
        runtime.close()


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
) -> tuple[
    int, dict[str, object], Literal["owner_receipt", "verified_transition"]
] | None:
    """Prove an exact Desired commit even before handoff settlement is journaled."""

    desired_request = handoff.request.desired_request
    if handoff.desired_receipt is not None:
        return (
            handoff.desired_receipt.inventory_revision,
            desired_request.root_ref.to_dict(),
            "owner_receipt",
        )
    if handoff.state != "dependency_pinned":
        return None
    transition = read_coding_fenced_desired_transition(
        layout, desired_request.command_id
    )
    if transition is None:
        return None
    key = transition.mutation.installation_key
    selected = transition.committed_state.selection.package_revision
    if (
        transition.mutation.expected_inventory_revision
        != desired_request.expected_inventory_revision
        or transition.inventory_revision
        != desired_request.expected_inventory_revision + 1
        or (key.product_id, key.scope_id, key.plugin_id)
        != (
            desired_request.product_id,
            desired_request.scope_id,
            desired_request.plugin_id,
        )
        or selected is None
        or selected.plugin_version != desired_request.root_ref.version
        or selected.package_content_digest
        != desired_request.root_ref.artifact_digest
    ):
        return None
    return (
        transition.inventory_revision,
        desired_request.root_ref.to_dict(),
        "verified_transition",
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
        from .package_private_data_backup import CodingArchPrivateDataBackupReadSource

        self.assert_workspace_current()
        epoch = resolve_coding_package_epoch_layout(self.layout)
        runtime = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
            read_only=read_only,
        )
        try:
            self.assert_workspace_current()
            state_root = runtime.control_root / "product-state"
            if read_only:
                try:
                    state_metadata = state_root.lstat()
                except FileNotFoundError as exc:
                    raise ValueError(
                        "Fenced Product management state is absent"
                    ) from exc
                if (
                    not stat.S_ISDIR(state_metadata.st_mode)
                    or stat.S_IMODE(state_metadata.st_mode) & 0o077
                    or state_metadata.st_uid != os.geteuid()
                ):
                    raise ValueError("Fenced Product management state is unsafe")
                load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)
                gate = PluginPackageGcReservationJournal(
                    state_root / "gc-reservations.jsonl", load_policy=load_policy
                )
                desired = PluginDesiredStateLedger(
                    state_root / "desired-state.jsonl",
                    gc_gate=gate,
                    load_policy=load_policy,
                )
                management = PluginManagementService(
                    desired_state=desired,
                    operation_journal_path=state_root / "management-operations.jsonl",
                    load_policy=load_policy,
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


@dataclass(frozen=True, slots=True)
class _ProductSources:
    catalog: CodingExternalDataWheelCatalog
    desired_state: PluginDesiredStateLedger

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        all_bindings = self.catalog.records()
        selected = {
            item.installation_key.plugin_id: item.selection.package_revision
            for item in self.desired_state.snapshot().installations
            if item.installation_key.product_id == "coding"
            and item.installation_key.scope_id == self.catalog.scope_id
        }
        latest: dict[str, CodingExternalDataWheelBindingV1] = {}
        for item in all_bindings:
            prior = latest.get(item.plugin_id)
            if prior is None or item.record_revision > prior.record_revision:
                latest[item.plugin_id] = item
        for item in all_bindings:
            revision = selected.get(item.plugin_id)
            if (
                revision is not None
                and revision.package_source_identity
                == str(self.catalog.source_root / item.wheel_filename)
                and revision.package_content_digest == item.artifact_digest
            ):
                latest[item.plugin_id] = item
        records = []
        for item in latest.values():
            availability: Literal["available", "unavailable"]
            try:
                self.catalog.verify_record(item)
            except (CodingExternalDataWheelError, OSError):
                availability = "unavailable"
            else:
                availability = "available"
            records.append(
                PluginManagementSourceRecordV1(
                    installation_key=PluginInstallationKeyV1(
                        product_id="coding",
                        installation_scope="workspace",
                        scope_id=item.scope_id,
                        plugin_id=item.plugin_id,
                    ),
                    source_identity=f"local:{self.catalog.source_root / item.wheel_filename}",
                    source_kind="local",
                    availability=availability,
                    source_location=item.original_source,
                    plugin_version=item.version,
                    manifest_enabled_default=None,
                )
            )
        ordered = tuple(sorted(records, key=lambda value: value.installation_key))
        owner_revision = sha256(
            canonical_json_bytes(
                {
                    "bindings": [item.to_dict() for item in all_bindings],
                    "selected": [item.to_dict() for item in ordered],
                }
            )
        ).hexdigest()
        return PluginManagementSourceSnapshotV1(
            owner_revision=f"coding-product-source:{owner_revision}",
            records=ordered,
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
        runtime, ports = self.owner.open(read_only=True)
        try:
            self.owner.assert_workspace_current()
            result = ports.queries.snapshot(query)
            runtime.assert_current()
            self.owner.assert_workspace_current()
            return result
        finally:
            runtime.close()


@dataclass(frozen=True, slots=True)
class _ProductCliCommands:
    owner: _ProductCliOwner

    def submit(
        self, request: PluginManagementApplicationCommandV1
    ) -> PluginManagementApplicationResultV1:
        runtime, ports = self.owner.open(read_only=False)
        try:
            self.owner.assert_workspace_current()
            result = ports.commands.submit(request)
            runtime.assert_current()
            self.owner.assert_workspace_current()
            return result
        finally:
            runtime.close()

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        runtime, ports = self.owner.open(read_only=True)
        try:
            self.owner.assert_workspace_current()
            result = ports.commands.operation(
                operation_id, correlation_id=correlation_id
            )
            runtime.assert_current()
            self.owner.assert_workspace_current()
            return result
        finally:
            runtime.close()


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
