"""One-shot Coding CLI ports bound to the current fenced B management owners."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
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
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
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


def coding_fenced_product_exists(layout: CodingPluginLifecycleStateLayout) -> bool:
    """Only an existing fence selects B; malformed existing B fails closed later."""

    epoch = resolve_coding_package_epoch_layout(layout)
    try:
        (epoch.control_root / "epoch.jsonl").lstat()
    except FileNotFoundError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _ProductCliOwner:
    layout: CodingPluginLifecycleStateLayout

    def open(
        self, *, read_only: bool
    ) -> tuple[
        PackageProductPosixFencedRuntimeOwner,
        PluginManagementApplicationPorts,
    ]:
        epoch = resolve_coding_package_epoch_layout(self.layout)
        runtime = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
        )
        try:
            state_root = runtime.control_root / "product-state"
            if read_only and not state_root.is_dir():
                raise ValueError("Fenced Product management state is absent")
            runtime.prepare_product_state_root()
            if read_only:
                load_policy = JournalLoadPolicy(partial_tail="raise")
                gate = PluginPackageGcReservationJournal(
                    state_root / "gc-reservations.jsonl", load_policy=load_policy
                )
                desired = PluginDesiredStateLedger(
                    state_root / "desired-state.jsonl", gc_gate=gate,
                    load_policy=load_policy,
                )
                management = PluginManagementService(
                    desired_state=desired,
                    operation_journal_path=state_root / "management-operations.jsonl",
                    load_policy=load_policy,
                )
            else:
                state = open_coding_package_product_state(self.layout, runtime)
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
                    source=_product_sources(self.layout, runtime, desired),
                ),
            )
            runtime.assert_current()
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
) -> _ProductSources:
    switch = runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError("Fenced Product Source namespace is unavailable")
    source_root = runtime.control_root / "product-sources"
    if not source_root.is_dir():
        raise ValueError("Fenced Product Source root is absent")
    runtime.prepare_product_source_root()
    return _ProductSources(
        CodingExternalDataWheelCatalog(
            runtime.control_root / "product-state" / "external-data-wheel-bindings.jsonl",
            source_root=source_root,
            store_id=runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=layout.scope_id,
        ),
        desired_state,
    )


@dataclass(frozen=True, slots=True)
class _ProductCliQueries:
    owner: _ProductCliOwner

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        runtime, ports = self.owner.open(read_only=True)
        try:
            result = ports.queries.snapshot(query)
            runtime.assert_current()
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
            result = ports.commands.submit(request)
            runtime.assert_current()
            return result
        finally:
            runtime.close()

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        runtime, ports = self.owner.open(read_only=True)
        try:
            result = ports.commands.operation(
                operation_id, correlation_id=correlation_id
            )
            runtime.assert_current()
            return result
        finally:
            runtime.close()


def build_coding_fenced_product_management_cli_ports(
    layout: CodingPluginLifecycleStateLayout,
) -> PluginManagementApplicationPorts:
    owner = _ProductCliOwner(layout)
    return PluginManagementApplicationPorts(
        commands=_ProductCliCommands(owner), queries=_ProductCliQueries(owner)
    )


__all__ = [
    "build_coding_fenced_product_management_cli_ports",
    "coding_fenced_product_exists",
]
