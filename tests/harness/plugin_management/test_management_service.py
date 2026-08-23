from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import (
    PluginManagementAction,
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
    PluginManagementOperationResultV1,
    PluginManagementRecordCodecError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredState,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.service import (
    PluginManagementError,
    PluginManagementService,
)


def test_management_records_are_strict_and_command_actions_are_exact() -> None:
    command = _command(action="install", revision=0, package=_package())
    assert PluginManagementCommandV1.from_dict(command.to_dict()) == command
    assert command.to_dict() == {
        "action": "install",
        "commandVersion": 1,
        "mutation": command.mutation.to_dict(),
    }

    accepted = PluginManagementOperationEventV1.accepted(
        journal_revision=1,
        command=command,
    )
    running = PluginManagementOperationEventV1.running(
        journal_revision=2,
        command=command,
    )
    result = PluginManagementOperationResultV1.failed(
        error_code="plugin_inventory_revision_conflict"
    )
    terminal = PluginManagementOperationEventV1.terminal(
        journal_revision=3,
        command=command,
        result=result,
    )
    for record_type, value in (
        (PluginManagementOperationEventV1, accepted),
        (PluginManagementOperationEventV1, running),
        (PluginManagementOperationResultV1, result),
        (PluginManagementOperationEventV1, terminal),
    ):
        assert record_type.from_dict(value.to_dict()) == value

    with pytest.raises(ValueError, match="install"):
        PluginManagementCommandV1(
            action="install",
            mutation=_mutation(action="enable", revision=0),
        )
    with pytest.raises(ValueError, match="Package Revision"):
        PluginManagementCommandV1(
            action="enable",
            mutation=_mutation(
                action="enable",
                revision=0,
                package=_package(),
            ),
        )
    with pytest.raises(ValueError, match="terminal error code"):
        PluginManagementOperationResultV1.failed(error_code="arbitrary secret text")

    pending = {**accepted.to_dict(), "status": "pending_approval"}
    with pytest.raises(PluginManagementRecordCodecError) as caught:
        PluginManagementOperationEventV1.from_dict(pending)
    assert caught.value.code == "invalid_plugin_management_record"


def test_service_requires_distinct_operation_and_desired_journals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plugin-state.jsonl"
    with pytest.raises(ValueError, match="must be distinct"):
        PluginManagementService(
            desired_state=PluginDesiredStateLedger(path),
            operation_journal_path=path,
        )


@pytest.mark.parametrize(
    ("decoder", "document", "version_field"),
    [
        (
            PluginManagementCommandV1.from_dict,
            lambda: _command(
                action="install", revision=0, package=_package()
            ).to_dict(),
            "commandVersion",
        ),
        (
            PluginManagementOperationResultV1.from_dict,
            lambda: PluginManagementOperationResultV1.failed(
                error_code="plugin_inventory_revision_conflict"
            ).to_dict(),
            "resultVersion",
        ),
        (
            PluginManagementOperationEventV1.from_dict,
            lambda: PluginManagementOperationEventV1.accepted(
                journal_revision=1,
                command=_command(
                    action="install",
                    revision=0,
                    package=_package(),
                ),
            ).to_dict(),
            "recordVersion",
        ),
    ],
)
def test_management_records_reject_unknown_fields_and_versions(
    decoder: Callable[[object], object],
    document: Callable[[], dict[str, object]],
    version_field: str,
) -> None:
    value = document()
    with pytest.raises(PluginManagementRecordCodecError) as caught:
        decoder({**value, "unknown": True})
    assert caught.value.code == "invalid_plugin_management_record"

    with pytest.raises(PluginManagementRecordCodecError) as caught:
        decoder({**value, version_field: 2})
    assert caught.value.code == "unsupported_plugin_management_record_version"


def test_service_runs_install_enable_disable_remove_through_one_durable_core(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(
        desired_path,
        instance_id_factory=lambda: "instance-1",
    )
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    )

    install = service.submit(
        _command(action="install", revision=0, package=_package(), operation=1)
    )
    enable = service.submit(_command(action="enable", revision=1, operation=2))
    disable = service.submit(_command(action="disable", revision=2, operation=3))
    remove = service.submit(_command(action="remove", revision=3, operation=4))

    for snapshot in (install, enable, disable, remove):
        assert snapshot.status == "terminal"
        assert snapshot.result is not None
        assert snapshot.result.disposition == "succeeded"
        assert snapshot.result.transition is not None
        assert snapshot.operation_revision == 3
    assert install.result is not None and install.result.transition is not None
    assert enable.result is not None and enable.result.transition is not None
    assert disable.result is not None and disable.result.transition is not None
    assert remove.result is not None and remove.result.transition is not None
    assert install.result.transition.transition_kind == "install"
    assert enable.result.transition.transition_kind == "enable"
    assert disable.result.transition.transition_kind == "disable"
    assert remove.result.transition.transition_kind == "remove"
    assert desired.snapshot().inventory_revision == 4
    assert len(desired_path.read_text(encoding="utf-8").splitlines()) == 4
    assert len(operation_path.read_text(encoding="utf-8").splitlines()) == 12

    reopened = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    operations = reopened.operations()
    assert tuple(item.command.action for item in operations) == (
        "install",
        "enable",
        "disable",
        "remove",
    )
    assert reopened.operation("operation-4") == remove


def test_service_exact_retry_and_key_conflicts_do_not_append(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    command = _command(action="install", revision=0, package=_package())
    terminal = service.submit(command)
    desired_bytes = desired_path.read_bytes()
    operation_bytes = operation_path.read_bytes()

    assert service.submit(command) == terminal
    assert desired_path.read_bytes() == desired_bytes
    assert operation_path.read_bytes() == operation_bytes

    with pytest.raises(PluginManagementError) as caught:
        service.submit(
            replace(
                command,
                mutation=replace(command.mutation, operation_id="operation-other"),
            )
        )
    assert caught.value.code == "plugin_management_idempotency_conflict"

    with pytest.raises(PluginManagementError) as caught:
        service.submit(
            replace(
                command,
                mutation=replace(command.mutation, idempotency_key="request-other"),
            )
        )
    assert caught.value.code == "plugin_management_operation_conflict"
    assert desired_path.read_bytes() == desired_bytes
    assert operation_path.read_bytes() == operation_bytes


def test_expected_ledger_rejection_becomes_stable_terminal_failure(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    service.submit(_command(action="install", revision=0, package=_package()))
    stale = _command(action="enable", revision=0, operation=2)

    failed = service.submit(stale)
    assert failed.status == "terminal"
    assert failed.result is not None
    assert failed.result.disposition == "failed"
    assert failed.result.error_code == "plugin_inventory_revision_conflict"
    assert failed.result.transition is None
    assert service.submit(stale) == failed
    assert PluginDesiredStateLedger(desired_path).snapshot().inventory_revision == 1
    assert len(operation_path.read_text(encoding="utf-8").splitlines()) == 6


def test_install_never_disables_an_already_enabled_installation(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    service.submit(_command(action="install", revision=0, package=_package()))
    service.submit(_command(action="enable", revision=1, operation=2))

    repeated_install = service.submit(
        _command(
            action="install",
            revision=2,
            package=_package(),
            operation=3,
        )
    )
    assert repeated_install.result is not None
    assert repeated_install.result.disposition == "failed"
    assert repeated_install.result.error_code == "plugin_installation_already_enabled"
    snapshot = PluginDesiredStateLedger(desired_path).snapshot()
    assert snapshot.inventory_revision == 2
    assert snapshot.installation(_key()).selection.desired_state == "installed_enabled"


def test_recovery_completes_crash_after_desired_state_commit(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(desired_path)
    crashing = _CommitThenCrash(desired)
    service = PluginManagementService(
        desired_state=crashing,
        operation_journal_path=operation_path,
    )
    command = _command(action="install", revision=0, package=_package())

    with pytest.raises(RuntimeError, match="simulated process crash"):
        service.submit(command)
    running = service.operation(command.mutation.operation_id)
    assert running is not None
    assert running.status == "running"
    assert desired.snapshot().inventory_revision == 1
    assert len(operation_path.read_text(encoding="utf-8").splitlines()) == 2

    fresh = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
    )
    conflicting = _command(action="disable", revision=1, operation=2)
    with pytest.raises(PluginManagementError) as caught:
        fresh.submit(conflicting)
    assert caught.value.code == "plugin_management_installation_busy"

    recovered = fresh.recover()
    assert len(recovered) == 1
    terminal = recovered[0]
    assert terminal.status == "terminal"
    assert terminal.result is not None
    assert terminal.result.disposition == "succeeded"
    assert terminal.result.transition == desired.transitions()[0]
    assert fresh.submit(command) == terminal
    assert len(operation_path.read_text(encoding="utf-8").splitlines()) == 3
    assert len(desired_path.read_text(encoding="utf-8").splitlines()) == 1


def test_two_service_instances_serialize_one_exact_command(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    command = _command(action="install", revision=0, package=_package())
    barrier = Barrier(2)

    def submit() -> object:
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
    assert len(operation_path.read_text(encoding="utf-8").splitlines()) == 3
    assert len(desired_path.read_text(encoding="utf-8").splitlines()) == 1


def test_operation_journal_repairs_partial_tail_but_rejects_complete_corruption(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    service.submit(_command(action="install", revision=0, package=_package()))
    committed = operation_path.read_bytes()

    with operation_path.open("ab") as handle:
        handle.write(b'{"recordVersion":')
    assert len(service.operations()) == 1
    assert operation_path.read_bytes() == committed

    first = json.loads(committed.splitlines()[0])
    with operation_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(first, sort_keys=True) + "\n")
    with pytest.raises(PluginManagementError) as caught:
        service.operations()
    assert caught.value.code == "plugin_management_journal_corrupt"


def test_operation_success_must_match_the_durable_desired_transition(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(desired_path),
        operation_journal_path=operation_path,
    )
    service.submit(_command(action="install", revision=0, package=_package()))

    desired_path.write_text("", encoding="utf-8")
    with pytest.raises(PluginManagementError) as caught:
        service.operations()
    assert caught.value.code == "plugin_management_journal_corrupt"


class _CommitThenCrash:
    def __init__(self, desired: PluginDesiredStateLedger) -> None:
        self._desired = desired
        self._crashed = False

    @property
    def path(self) -> Path:
        return self._desired.path

    def commit(self, mutation: PluginDesiredStateMutationV1):
        transition = self._desired.commit(mutation)
        if not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated process crash")
        return transition

    def snapshot(self):
        return self._desired.snapshot()

    def transitions(self):
        return self._desired.transitions()


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1.0.0",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="coding.base",
    )


def _mutation(
    *,
    action: PluginManagementAction,
    revision: int,
    package: PluginPackageRevisionRefV1 | None = None,
    operation: int = 1,
) -> PluginDesiredStateMutationV1:
    desired_states: dict[PluginManagementAction, PluginDesiredState] = {
        "install": "installed_disabled",
        "enable": "installed_enabled",
        "disable": "installed_disabled",
        "remove": "absent",
    }
    return PluginDesiredStateMutationV1(
        operation_id=f"operation-{operation}",
        idempotency_key=f"request-{operation}",
        expected_inventory_revision=revision,
        installation_key=_key(),
        desired_state=desired_states[action],
        package_revision=package,
        actor_id="operator-1",
        policy_revision="policy-1",
    )


def _command(
    *,
    action: PluginManagementAction,
    revision: int,
    package: PluginPackageRevisionRefV1 | None = None,
    operation: int = 1,
) -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action=action,
        mutation=_mutation(
            action=action,
            revision=revision,
            package=package,
            operation=operation,
        ),
    )
