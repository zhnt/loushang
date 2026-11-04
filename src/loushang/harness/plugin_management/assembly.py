"""Internal ledger construction; callers retain admission and recovery order."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management.enablement_migration import (
    PluginEnablementMigrationJournal,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.retirement import PluginRetirementIntentLedger
from loushang.harness.plugin_management.retirement_sets import PluginRetirementSetLedger
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService


@dataclass(frozen=True, slots=True)
class PluginManagementCoreBindings:
    gc_reservations: PluginPackageGcReservationJournal
    desired: PluginDesiredStateLedger
    intents: PluginRetirementIntentLedger
    retirement_sets: PluginRetirementSetLedger
    management: PluginManagementService
    migration_journal: PluginEnablementMigrationJournal
    load_policy: JournalLoadPolicy | None


@dataclass(frozen=True, slots=True)
class PluginRuntimeLedgerBindings:
    security: PluginInstanceSecurityRetirementJournal
    instances: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger


def bind_plugin_management_core(
    *,
    gc_reservations_path: str | Path,
    desired_state_path: str | Path,
    operation_journal_path: str | Path,
    retirement_intents_path: str | Path,
    retirement_sets_path: str | Path,
    migration_journal_path: str | Path,
    load_policy: JournalLoadPolicy | None = None,
) -> PluginManagementCoreBindings:
    gc_reservations = PluginPackageGcReservationJournal(
        gc_reservations_path, load_policy=load_policy,
    )
    desired = PluginDesiredStateLedger(
        desired_state_path, gc_gate=gc_reservations, load_policy=load_policy,
    )
    intents = PluginRetirementIntentLedger(
        retirement_intents_path, load_policy=load_policy,
    )
    retirement_sets = PluginRetirementSetLedger(
        retirement_sets_path, retirement_intents=intents, load_policy=load_policy,
    )
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_journal_path,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
        load_policy=load_policy,
    )
    migration_journal = PluginEnablementMigrationJournal(
        migration_journal_path, load_policy=load_policy,
    )
    return PluginManagementCoreBindings(
        gc_reservations=gc_reservations,
        desired=desired,
        intents=intents,
        retirement_sets=retirement_sets,
        management=management,
        migration_journal=migration_journal,
        load_policy=load_policy,
    )


def bind_plugin_runtime_ledgers(
    core: PluginManagementCoreBindings,
    *,
    instance_runtime_path: str | Path,
    package_lifecycle_path: str | Path,
    startup_id: str,
    security_acceptances: PluginInstanceSecurityRetirementJournal | None = None,
) -> PluginRuntimeLedgerBindings:
    security = security_acceptances or (
        PluginInstanceSecurityRetirementJournal.for_instance_runtime(
            instance_runtime_path, load_policy=core.load_policy,
        )
    )
    instances = PluginInstanceRuntimeLedger(
        instance_runtime_path,
        management_operation_journal_path=core.management.operation_journal_path,
        desired_state=core.desired,
        retirement_intents=core.intents,
        retirement_sets=core.retirement_sets,
        security_acceptances=security,
        gc_gate=core.gc_reservations,
        load_policy=core.load_policy,
    )
    packages = PluginPackageLifecycleLedger(
        package_lifecycle_path,
        startup_id=startup_id,
        desired_state=core.desired,
        instance_runtime=instances,
        retirement_sets=core.retirement_sets,
        gc_gate=core.gc_reservations,
        load_policy=core.load_policy,
    )
    return PluginRuntimeLedgerBindings(
        security=security, instances=instances, packages=packages,
    )
