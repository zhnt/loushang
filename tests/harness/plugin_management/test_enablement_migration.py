from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginEnablementCompatibilityProjector,
    PluginEnablementFinalizationEvidenceV1,
    PluginEnablementMigrationCoordinator,
    PluginEnablementMigrationError,
    PluginEnablementMigrationJournal,
    PluginEnablementMigrationRequestV1,
    PluginInstallationKeyV1,
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationResultV1,
    PluginManagementCommandApplication,
    PluginManagementCommandPort,
    PluginManagementCommandV1,
    PluginManagementService,
    PluginPackageRevisionRefV1,
)


@pytest.mark.parametrize(
    ("legacy_disabled", "manifest_enabled", "expected", "transition_count"),
    (
        (True, True, "installed_disabled", 1),
        (False, False, "installed_disabled", 1),
        (False, True, "installed_enabled", 2),
    ),
)
def test_never_seen_enablement_is_seeded_once_from_frozen_precedence(
    tmp_path: Path,
    legacy_disabled: bool,
    manifest_enabled: bool,
    expected: str,
    transition_count: int,
) -> None:
    desired, service, journal, coordinator = _migration(tmp_path)
    request = _request(
        legacy_disabled=legacy_disabled,
        manifest_enabled=manifest_enabled,
    )

    migrated = coordinator.migrate(request)
    repeated = coordinator.migrate(request)

    assert migrated.phase == "compatibility_window"
    assert migrated.disposition == "seeded"
    assert migrated.committed_desired_transition_revision == transition_count
    assert len(migrated.operation_ids) == transition_count
    assert repeated == migrated
    assert desired.snapshot().installation(_key()).selection.desired_state == expected
    assert len(desired.transitions()) == transition_count
    assert len(service.operations()) == transition_count
    assert tuple(event.phase for event in journal.records()) == (
        "accepted",
        "desired_committed",
        "compatibility_window",
    )


@pytest.mark.parametrize(
    "existing_state",
    ("installed_disabled", "installed_enabled", "absent"),
)
def test_any_existing_desired_history_wins_over_conflicting_legacy_input(
    tmp_path: Path,
    existing_state: str,
) -> None:
    desired, service, _journal, coordinator = _migration(tmp_path)
    _prepare_existing(service, desired, state=existing_state)
    before = desired.transitions()

    migrated = coordinator.migrate(
        _request(legacy_disabled=existing_state == "installed_enabled")
    )

    assert migrated.disposition == "already_authoritative"
    assert migrated.prior_desired_history_revision == before[-1].inventory_revision
    assert migrated.committed_desired_transition_revision is None
    assert migrated.operation_ids == ()
    assert desired.transitions() == before


@pytest.mark.parametrize(
    "crash_phase",
    ("accepted", "desired_committed", "compatibility_window"),
)
def test_crash_after_each_migration_edge_resumes_without_second_mutation(
    tmp_path: Path,
    crash_phase: str,
) -> None:
    desired, service, journal, _coordinator = _migration(tmp_path)
    request = _request()

    def crash(phase: str) -> None:
        if phase == crash_phase:
            raise _Crash(phase)

    crashing = PluginEnablementMigrationCoordinator(
        journal=journal,
        desired_state=desired,
        commands=PluginManagementCommandApplication(service),
        phase_observer=crash,
    )
    with pytest.raises(_Crash, match=crash_phase):
        crashing.migrate(request)
    transitions_after_crash = desired.transitions()

    resumed = PluginEnablementMigrationCoordinator(
        journal=journal,
        desired_state=desired,
        commands=PluginManagementCommandApplication(service),
    ).migrate(request)

    assert resumed.phase == "compatibility_window"
    assert resumed.disposition == "seeded"
    assert len(desired.transitions()) == 2
    assert desired.transitions()[: len(transitions_after_crash)] == (
        transitions_after_crash
    )
    assert len(service.operations()) == 2


def test_global_cas_race_retries_without_claiming_peer_installation(
    tmp_path: Path,
) -> None:
    desired, service, journal, _coordinator = _migration(tmp_path)
    commands = PluginManagementCommandApplication(service)
    racing = _OneShotGlobalRace(commands=commands, service=service)
    coordinator = PluginEnablementMigrationCoordinator(
        journal=journal,
        desired_state=desired,
        commands=racing,
    )

    migrated = coordinator.migrate(_request())

    assert migrated.disposition == "seeded"
    assert desired.snapshot().installation(_key()).selection.desired_state == (
        "installed_enabled"
    )
    assert desired.snapshot().installation(_other_key()).selection.desired_state == (
        "installed_disabled"
    )
    assert all("global-race" not in item for item in migrated.operation_ids)


def test_compatibility_projection_is_derived_and_peer_mutation_is_rejected(
    tmp_path: Path,
) -> None:
    desired, _service, journal, coordinator = _migration(tmp_path)
    migrated = coordinator.migrate(_request(legacy_disabled=True))
    projector = PluginEnablementCompatibilityProjector(
        journal=journal,
        desired_state=desired,
    )

    projection = projector.snapshot(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
    )

    assert projection.disabled_plugin_ids == ("coding.base",)
    assert projection.desired_inventory_revision == 1
    assert projection.migration_journal_revision == migrated.journal_revision
    with pytest.raises(PluginEnablementMigrationError) as rejected:
        journal.assert_legacy_mutation_allowed(_key())
    assert rejected.value.code == "plugin_enablement_legacy_mutation_rejected"


def test_finalization_requires_recovery_evidence_and_fences_downgrade(
    tmp_path: Path,
) -> None:
    _desired, _service, journal, coordinator = _migration(tmp_path)
    migrated = coordinator.migrate(_request())
    evidence = PluginEnablementFinalizationEvidenceV1(
        minimum_runtime_version="1.0.0",
        minimum_migration_epoch=2,
        backup_receipt="backup:verified",
        restore_test_receipt="restore:test:passed",
        roll_forward_procedure="runbook:plugin-enable:v1",
    )

    finalized = coordinator.finalize(migrated.migration_id, evidence)

    assert finalized.phase == "finalized"
    assert finalized.finalization_evidence == evidence
    journal.assert_runtime_compatible(supported_migration_epoch=2)
    with pytest.raises(PluginEnablementMigrationError) as downgrade:
        journal.assert_runtime_compatible(supported_migration_epoch=1)
    assert downgrade.value.code == "plugin_enablement_migration_epoch_unsupported"
    journal.assert_runtime_compatible(supported_migration_epoch=2)


def test_finalization_crash_replays_exact_receipt(tmp_path: Path) -> None:
    desired, service, journal, coordinator = _migration(tmp_path)
    migrated = coordinator.migrate(_request())
    evidence = PluginEnablementFinalizationEvidenceV1(
        minimum_runtime_version="1.0.0",
        minimum_migration_epoch=1,
        backup_receipt="backup:verified",
        restore_test_receipt="restore:test:passed",
        roll_forward_procedure="runbook:plugin-enable:v1",
    )
    crashing = PluginEnablementMigrationCoordinator(
        journal=journal,
        desired_state=desired,
        commands=PluginManagementCommandApplication(service),
        phase_observer=lambda phase: (
            _raise_crash(phase) if phase == "finalized" else None
        ),
    )

    with pytest.raises(_Crash, match="finalized"):
        crashing.finalize(migrated.migration_id, evidence)

    assert journal.snapshot(_key()).phase == "finalized"  # type: ignore[union-attr]
    assert coordinator.finalize(migrated.migration_id, evidence).phase == "finalized"


def test_future_epoch_and_changed_accepted_input_fail_closed(tmp_path: Path) -> None:
    desired, _service, journal, coordinator = _migration(tmp_path)
    accepted = journal.accept(
        _request(migration_epoch=2),
        accepted_desired_inventory_revision=0,
        prior_desired_history_revision=None,
    )
    assert accepted.phase == "accepted"

    with pytest.raises(PluginEnablementMigrationError) as old_runtime:
        journal.assert_runtime_compatible(supported_migration_epoch=1)
    assert old_runtime.value.code == "plugin_enablement_migration_epoch_unsupported"
    journal.assert_runtime_compatible(supported_migration_epoch=2)
    with pytest.raises(PluginEnablementMigrationError) as changed:
        journal.accept(
            _request(migration_epoch=2, fingerprint="f" * 64),
            accepted_desired_inventory_revision=desired.snapshot().inventory_revision,
            prior_desired_history_revision=None,
        )
    assert changed.value.code == "plugin_enablement_migration_request_conflict"
    with pytest.raises(PluginEnablementMigrationError) as unsupported:
        coordinator.migrate(_request())
    assert unsupported.value.code == "plugin_enablement_migration_epoch_unsupported"


def test_migration_journal_codec_rejects_unknown_fields(tmp_path: Path) -> None:
    _desired, _service, journal, coordinator = _migration(tmp_path)
    coordinator.migrate(_request())
    path = journal.path
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0][:-1] + ',"unknown":true}'
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(PluginEnablementMigrationError) as corrupt:
        journal.records()

    assert corrupt.value.code == "plugin_enablement_migration_journal_corrupt"


class _Crash(RuntimeError):
    pass


def _raise_crash(phase: str) -> None:
    raise _Crash(phase)


@dataclass
class _OneShotGlobalRace(PluginManagementCommandPort):
    commands: PluginManagementCommandApplication
    service: PluginManagementService
    fired: bool = False

    def submit(
        self,
        request: PluginManagementApplicationCommandV1,
    ) -> PluginManagementApplicationResultV1:
        if not self.fired:
            self.fired = True
            self.service.submit(
                PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="global-race",
                        idempotency_key="global-race",
                        expected_inventory_revision=0,
                        installation_key=_other_key(),
                        desired_state="installed_disabled",
                        package_revision=_package("other.plugin"),
                        actor_id="operator",
                        policy_revision="policy",
                    ),
                )
            )
        return self.commands.submit(request)

    def operation(
        self,
        operation_id: str,
        *,
        correlation_id: str,
    ) -> PluginManagementApplicationResultV1 | None:
        return self.commands.operation(operation_id, correlation_id=correlation_id)


def _migration(
    tmp_path: Path,
) -> tuple[
    PluginDesiredStateLedger,
    PluginManagementService,
    PluginEnablementMigrationJournal,
    PluginEnablementMigrationCoordinator,
]:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    journal = PluginEnablementMigrationJournal(tmp_path / "migration.jsonl")
    return (
        desired,
        service,
        journal,
        PluginEnablementMigrationCoordinator(
            journal=journal,
            desired_state=desired,
            commands=PluginManagementCommandApplication(service),
        ),
    )


def _prepare_existing(
    service: PluginManagementService,
    desired: PluginDesiredStateLedger,
    *,
    state: str,
) -> None:
    _submit(
        service,
        action="install",
        state="installed_disabled",
        revision=0,
        operation=1,
        package=_package(),
    )
    if state == "installed_enabled":
        _submit(
            service,
            action="enable",
            state="installed_enabled",
            revision=1,
            operation=2,
        )
    elif state == "absent":
        _submit(
            service,
            action="remove",
            state="absent",
            revision=1,
            operation=2,
        )
    assert desired.snapshot().installation(_key()).selection.desired_state == state


def _submit(
    service: PluginManagementService,
    *,
    action: str,
    state: str,
    revision: int,
    operation: int,
    package: PluginPackageRevisionRefV1 | None = None,
) -> None:
    event = service.submit(
        PluginManagementCommandV1(
            action=action,  # type: ignore[arg-type]
            mutation=PluginDesiredStateMutationV1(
                operation_id=f"existing-{operation}",
                idempotency_key=f"existing-{operation}",
                expected_inventory_revision=revision,
                installation_key=_key(),
                desired_state=state,  # type: ignore[arg-type]
                package_revision=package,
                actor_id="operator",
                policy_revision="policy",
            ),
        )
    )
    assert event.result is not None
    assert event.result.disposition == "succeeded"


def _request(
    *,
    legacy_disabled: bool = False,
    manifest_enabled: bool = True,
    migration_epoch: int = 1,
    fingerprint: str | None = None,
) -> PluginEnablementMigrationRequestV1:
    return PluginEnablementMigrationRequestV1(
        installation_key=_key(),
        package_revision=_package(),
        legacy_disabled=legacy_disabled,
        manifest_enabled_default=manifest_enabled,
        legacy_input_fingerprint=fingerprint or hashlib.sha256(b"legacy").hexdigest(),
        migration_epoch=migration_epoch,
    )


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="coding.base",
    )


def _other_key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="other.plugin",
    )


def _package(plugin_id: str = "coding.base") -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        package_content_digest=("1" if plugin_id == "coding.base" else "3") * 64,
        dependency_lock_digest=("2" if plugin_id == "coding.base" else "4") * 64,
        package_source_identity=f"embedded:{plugin_id}",
    )
