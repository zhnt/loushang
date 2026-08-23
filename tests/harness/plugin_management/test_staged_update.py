from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementRecordCodecError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.service import (
    PluginManagementError,
    PluginManagementService,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateMutationV1,
    PluginDesiredStateUpdateTransitionV2,
    PluginManagementUpdateCommandV2,
    PluginMigrationFenceV1,
    PluginUpdateOperationEventV2,
    PluginUpdateOperationResultV2,
    PluginUpdateRestartRequirementV1,
)


def test_disabled_update_stages_fences_and_atomically_cuts_over(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(desired_path)
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    )
    service.submit(_install_command())

    command = _update_command(revision=1)
    terminal = service.submit(command)

    assert isinstance(terminal, PluginUpdateOperationEventV2)
    assert terminal.operation_revision == 5
    assert terminal.progress_code == "desired_state_committed"
    assert terminal.result is not None
    assert terminal.result.disposition == "succeeded"
    assert terminal.result.restart_requirement is None
    assert terminal.result.transition is not None
    assert terminal.result.transition.transition_kind == "update"
    assert terminal.result.transition.record_version == 2
    assert terminal.migration_fence is not None
    assert terminal.migration_fence.disposition == "not_applicable_unbound"

    snapshot = desired.snapshot()
    installation = snapshot.installation(_key())
    assert snapshot.inventory_revision == 2
    assert installation.selection.desired_state == "installed_disabled"
    assert installation.selection.package_revision == _package(2)
    assert installation.latest_instance_revision_ref is None
    assert tuple(
        event.progress_code
        for event in _operation_history(operation_path)
        if event.command.operation_id == command.operation_id
    ) == (
        "command_accepted",
        "update_staged",
        "migration_fence_satisfied",
        "desired_state_committing",
        "desired_state_committed",
    )

    reopened = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    assert reopened.operation(command.operation_id) == terminal
    assert len(reopened.operations()) == 2


def test_enabled_update_advances_instance_and_returns_exact_restart_reason(
    tmp_path: Path,
) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    service.submit(_install_command())
    service.submit(_enable_command(revision=1))
    before = desired.snapshot().installation(_key())

    terminal = service.submit(_update_command(revision=2))

    assert isinstance(terminal, PluginUpdateOperationEventV2)
    assert terminal.result is not None
    assert terminal.result.disposition == "restart_required"
    assert terminal.progress_code == "update_restart_required"
    assert terminal.result.error_code is None
    assert terminal.result.restart_requirement == PluginUpdateRestartRequirementV1(
        changed_package_fields=(
            "pluginVersion",
            "packageContentDigest",
            "dependencyLockDigest",
            "packageSourceIdentity",
        )
    )
    after = desired.snapshot().installation(_key())
    assert after.selection.desired_state == "installed_enabled"
    assert after.selection.package_revision == _package(2)
    assert before.selection.instance_revision_ref is not None
    assert after.selection.instance_revision_ref is not None
    assert (
        after.selection.instance_revision_ref.instance_id
        == before.selection.instance_revision_ref.instance_id
    )
    assert after.selection.instance_revision_ref.revision == 2
    assert after.latest_instance_revision_ref == after.selection.instance_revision_ref


def test_update_records_are_strict_versioned_and_round_trip(tmp_path: Path) -> None:
    desired = PluginDesiredStateLedger(tmp_path / "desired.jsonl")
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    service.submit(_install_command())
    command = _update_command(revision=1)
    terminal = service.submit(command)
    assert isinstance(terminal, PluginUpdateOperationEventV2)
    assert terminal.migration_fence is not None
    assert terminal.result is not None
    assert terminal.result.transition is not None

    records = (
        (PluginManagementUpdateCommandV2, command, PluginManagementRecordCodecError),
        (
            PluginMigrationFenceV1,
            terminal.migration_fence,
            PluginManagementRecordCodecError,
        ),
        (
            PluginDesiredStateUpdateMutationV1,
            terminal.result.transition.mutation,
            PluginLifecycleCodecError,
        ),
        (
            PluginDesiredStateUpdateTransitionV2,
            terminal.result.transition,
            PluginLifecycleCodecError,
        ),
        (
            PluginUpdateOperationResultV2,
            terminal.result,
            PluginManagementRecordCodecError,
        ),
        (
            PluginUpdateOperationEventV2,
            terminal,
            PluginManagementRecordCodecError,
        ),
    )
    for record_type, record, error_type in records:
        assert record_type.from_dict(record.to_dict()) == record
        with pytest.raises(error_type) as caught:
            record_type.from_dict({**record.to_dict(), "unknown": True})
        assert getattr(caught.value, "code", None) in {
            "invalid_plugin_lifecycle_record",
            "invalid_plugin_management_record",
        }

    unsupported = terminal.to_dict()
    unsupported["recordVersion"] = 3
    with pytest.raises(Exception) as caught:
        PluginUpdateOperationEventV2.from_dict(unsupported)
    assert getattr(caught.value, "code", None) == (
        "unsupported_plugin_management_record_version"
    )


@pytest.mark.parametrize(
    ("setup", "command", "error_code"),
    [
        (
            (),
            lambda: _update_command(revision=0),
            "plugin_update_not_installed",
        ),
        (
            ("install",),
            lambda: _update_command(revision=0),
            "plugin_inventory_revision_conflict",
        ),
        (
            ("install",),
            lambda: replace(
                _update_command(revision=1),
                expected_package_revision=_package(3),
            ),
            "plugin_update_expected_package_mismatch",
        ),
        (
            ("install",),
            lambda: replace(
                _update_command(revision=1),
                staged_package_revision=_package(1),
            ),
            "plugin_update_target_not_new",
        ),
    ],
)
def test_update_precondition_failures_leave_desired_selection_unchanged(
    tmp_path: Path,
    setup: tuple[str, ...],
    command,
    error_code: str,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    desired = PluginDesiredStateLedger(desired_path)
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    if setup:
        service.submit(_install_command())
    before = desired_path.read_bytes() if desired_path.exists() else b""

    terminal = service.submit(command())

    assert isinstance(terminal, PluginUpdateOperationEventV2)
    assert terminal.result is not None
    assert terminal.result.disposition == "failed"
    assert terminal.result.error_code == error_code
    assert terminal.result.transition is None
    after = desired_path.read_bytes() if desired_path.exists() else b""
    assert after == before


def test_incomplete_update_keeps_old_selection_and_blocks_same_installation(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(desired_path)
    service = PluginManagementService(
        desired_state=_FailBeforeUpdateCutover(desired),
        operation_journal_path=operation_path,
    )
    service.submit(_install_command())
    command = _update_command(revision=1)

    with pytest.raises(RuntimeError, match="before update cutover"):
        service.submit(command)
    latest = service.operation(command.operation_id)
    assert isinstance(latest, PluginUpdateOperationEventV2)
    assert latest.operation_revision == 4
    assert latest.progress_code == "desired_state_committing"
    assert desired.snapshot().installation(_key()).selection.package_revision == _package(
        1
    )

    fresh = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    )
    with pytest.raises(PluginManagementError) as caught:
        fresh.submit(_disable_command(revision=1, operation=3))
    assert caught.value.code == "plugin_management_installation_busy"

    recovered = fresh.recover()
    assert len(recovered) == 1
    assert isinstance(recovered[0], PluginUpdateOperationEventV2)
    assert recovered[0].result is not None
    assert recovered[0].result.disposition == "succeeded"
    assert desired.snapshot().installation(_key()).selection.package_revision == _package(
        2
    )


def test_recovery_completes_crash_after_update_cutover(tmp_path: Path) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(desired_path)
    PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    ).submit(_install_command())
    crashing = PluginManagementService(
        desired_state=_CommitUpdateThenCrash(desired),
        operation_journal_path=operation_path,
    )
    command = _update_command(revision=1)

    with pytest.raises(RuntimeError, match="after update cutover"):
        crashing.submit(command)
    assert desired.snapshot().inventory_revision == 2
    assert len(desired.transitions()) == 2

    fresh = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    )
    recovered = fresh.recover()
    assert len(recovered) == 1
    terminal = recovered[0]
    assert isinstance(terminal, PluginUpdateOperationEventV2)
    assert terminal.result is not None
    assert terminal.result.disposition == "succeeded"
    assert terminal.result.transition == desired.transitions()[1]
    assert fresh.submit(command) == terminal
    assert len(desired.transitions()) == 2


def test_update_retry_conflicts_and_cross_log_validation(tmp_path: Path) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(desired_path)
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    )
    service.submit(_install_command())
    command = _update_command(revision=1)
    terminal = service.submit(command)
    desired_bytes = desired_path.read_bytes()
    operation_bytes = operation_path.read_bytes()

    assert service.submit(command) == terminal
    assert desired_path.read_bytes() == desired_bytes
    assert operation_path.read_bytes() == operation_bytes
    with pytest.raises(PluginManagementError) as caught:
        service.submit(replace(command, operation_id="operation-other"))
    assert caught.value.code == "plugin_management_idempotency_conflict"
    with pytest.raises(PluginManagementError) as caught:
        service.submit(replace(command, idempotency_key="request-other"))
    assert caught.value.code == "plugin_management_operation_conflict"

    desired_path.write_bytes(desired_bytes.splitlines(keepends=True)[0])
    with pytest.raises(PluginManagementError) as caught:
        service.operations()
    assert caught.value.code == "plugin_management_journal_corrupt"


def test_two_service_instances_serialize_one_exact_update(tmp_path: Path) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    ).submit(_install_command())
    command = _update_command(revision=1)
    barrier = Barrier(2)

    def submit():
        service = PluginManagementService(
            desired_state=PluginDesiredStateLedger(desired_path),
            operation_journal_path=operation_path,
        )
        barrier.wait()
        return service.submit(command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(submit) for _ in range(2))
        results = tuple(future.result() for future in futures)

    assert results[0] == results[1]
    assert len(operation_path.read_text(encoding="utf-8").splitlines()) == 8
    assert len(desired_path.read_text(encoding="utf-8").splitlines()) == 2


def test_mixed_operation_journal_repairs_partial_v2_tail(tmp_path: Path) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    service.submit(_install_command())
    service.submit(_update_command(revision=1))
    committed = operation_path.read_bytes()

    with operation_path.open("ab") as handle:
        handle.write(b'{"recordVersion":2')

    assert len(service.operations()) == 2
    assert operation_path.read_bytes() == committed


class _FailBeforeUpdateCutover:
    def __init__(self, desired: PluginDesiredStateLedger) -> None:
        self._desired = desired

    @property
    def path(self) -> Path:
        return self._desired.path

    def commit(self, mutation):
        return self._desired.commit(mutation)

    def commit_update(self, mutation):
        raise RuntimeError("simulated crash before update cutover")

    def snapshot(self):
        return self._desired.snapshot()

    def transitions(self):
        return self._desired.transitions()


class _CommitUpdateThenCrash:
    def __init__(self, desired: PluginDesiredStateLedger) -> None:
        self._desired = desired
        self._crashed = False

    @property
    def path(self) -> Path:
        return self._desired.path

    def commit(self, mutation):
        return self._desired.commit(mutation)

    def commit_update(self, mutation):
        transition = self._desired.commit_update(mutation)
        if not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated crash after update cutover")
        return transition

    def snapshot(self):
        return self._desired.snapshot()

    def transitions(self):
        return self._desired.transitions()


def _operation_history(path: Path):
    from loushang.harness.journal import (
        DURABLE_LOCKED_JOURNAL,
        SORTED_UNICODE_JSONL_FORMAT,
        JournalLoadPolicy,
        load_jsonl,
    )
    from loushang.harness.plugin_management.journal_codecs import (
        PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC,
    )

    return load_jsonl(
        path,
        record_codec=PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC,
        format_profile=SORTED_UNICODE_JSONL_FORMAT,
        durability=DURABLE_LOCKED_JOURNAL,
        load_policy=JournalLoadPolicy(partial_tail="raise"),
    ).records


def _package(revision: int) -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version=f"{revision}.0.0",
        package_content_digest=str(revision) * 64,
        dependency_lock_digest=str(revision + 3) * 64,
        package_source_identity=f"embedded:coding.base:{revision}",
    )


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="coding.base",
    )


def _install_command() -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action="install",
        mutation=PluginDesiredStateMutationV1(
            operation_id="operation-1",
            idempotency_key="request-1",
            expected_inventory_revision=0,
            installation_key=_key(),
            desired_state="installed_disabled",
            package_revision=_package(1),
            actor_id="operator-1",
            policy_revision="policy-1",
        ),
    )


def _enable_command(*, revision: int) -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action="enable",
        mutation=PluginDesiredStateMutationV1(
            operation_id="operation-2",
            idempotency_key="request-2",
            expected_inventory_revision=revision,
            installation_key=_key(),
            desired_state="installed_enabled",
            package_revision=None,
            actor_id="operator-1",
            policy_revision="policy-1",
        ),
    )


def _disable_command(*, revision: int, operation: int) -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action="disable",
        mutation=PluginDesiredStateMutationV1(
            operation_id=f"operation-{operation}",
            idempotency_key=f"request-{operation}",
            expected_inventory_revision=revision,
            installation_key=_key(),
            desired_state="installed_disabled",
            package_revision=None,
            actor_id="operator-1",
            policy_revision="policy-1",
        ),
    )


def _update_command(*, revision: int) -> PluginManagementUpdateCommandV2:
    return PluginManagementUpdateCommandV2(
        operation_id="operation-update",
        idempotency_key="request-update",
        expected_inventory_revision=revision,
        installation_key=_key(),
        expected_package_revision=_package(1),
        staged_package_revision=_package(2),
        actor_id="operator-1",
        policy_revision="policy-1",
    )
