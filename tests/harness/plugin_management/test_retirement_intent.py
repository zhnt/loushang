from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import (
    PluginManagementAction,
    PluginManagementCommandV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredState,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementError,
    PluginRetirementIntentLedger,
    PluginRetirementIntentRecordV1,
    PluginRetirementIntentV1,
    PluginRetirementRecordCodecError,
    retirement_id_for,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateMutationV1,
    PluginManagementUpdateCommandV2,
    migration_fence_for,
)


def test_retirement_intent_is_exact_derived_evidence_and_replays(
    tmp_path: Path,
) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    retirement_path = tmp_path / "retirements.jsonl"
    retirements = PluginRetirementIntentLedger(retirement_path)
    install = desired.commit(_mutation("install", revision=0, operation=1))
    enable = desired.commit(_mutation("enable", revision=1, operation=2))
    disable = desired.commit(_mutation("disable", revision=2, operation=3))

    assert retirements.request_for(install) is None
    assert retirements.request_for(enable) is None
    intent = retirements.request_for(disable)

    assert intent is not None
    assert intent.retirement_id == retirement_id_for(disable)
    assert intent.trigger == "disable"
    assert intent.mode == "graceful"
    assert intent.source_transition == disable
    assert intent.instance_revision_ref == enable.committed_state.selection.instance_revision_ref
    assert intent.package_revision == _package(1)
    assert retirements.request_for(disable) == intent
    assert len(retirement_path.read_text(encoding="utf-8").splitlines()) == 1

    reopened = PluginRetirementIntentLedger(retirement_path)
    assert reopened.snapshot().journal_revision == 1
    assert reopened.snapshot().intents == (intent,)
    assert reopened.snapshot().intent_for_operation("operation-3") == intent


def test_retirement_intent_transition_matrix(tmp_path: Path) -> None:
    retirements = PluginRetirementIntentLedger(tmp_path / "retirements.jsonl")

    remove_desired = PluginDesiredStateLedger(
        tmp_path / "remove-desired.jsonl",
        instance_id_factory=lambda: "instance-remove",
    )
    remove_desired.commit(_mutation("install", revision=0, operation=1))
    remove_desired.commit(_mutation("enable", revision=1, operation=2))
    remove = remove_desired.commit(_mutation("remove", revision=2, operation=3))
    remove_intent = retirements.request_for(remove)
    assert remove_intent is not None
    assert remove_intent.trigger == "remove"
    assert remove_intent.instance_revision_ref.revision == 1

    update_desired = PluginDesiredStateLedger(
        tmp_path / "update-desired.jsonl",
        instance_id_factory=lambda: "instance-update",
    )
    update_desired.commit(_mutation("install", revision=0, operation=4))
    enabled = update_desired.commit(_mutation("enable", revision=1, operation=5))
    update = update_desired.commit_update(
        _update_mutation(revision=2, operation="operation-6", enabled=True)
    )
    update_intent = retirements.request_for(update)
    assert update_intent is not None
    assert update_intent.trigger == "update"
    assert update_intent.instance_revision_ref == (
        enabled.committed_state.selection.instance_revision_ref
    )
    assert update_intent.package_revision == _package(1)

    disabled_desired = PluginDesiredStateLedger(
        tmp_path / "disabled-desired.jsonl"
    )
    install = disabled_desired.commit(
        _mutation("install", revision=0, operation=7)
    )
    disabled_update = disabled_desired.commit_update(
        _update_mutation(revision=1, operation="operation-8", enabled=False)
    )
    disabled_remove = disabled_desired.commit(
        _mutation("remove", revision=2, operation=9)
    )
    assert retirements.request_for(install) is None
    assert retirements.request_for(disabled_update) is None
    assert retirements.request_for(disabled_remove) is None
    assert retirements.snapshot().journal_revision == 2


def test_retirement_records_are_strict_and_derived(tmp_path: Path) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    desired.commit(_mutation("install", revision=0, operation=1))
    desired.commit(_mutation("enable", revision=1, operation=2))
    transition = desired.commit(_mutation("disable", revision=2, operation=3))
    retirements = PluginRetirementIntentLedger(tmp_path / "retirements.jsonl")
    intent = retirements.request_for(transition)
    assert intent is not None
    record = retirements.records()[0]

    assert PluginRetirementIntentV1.from_dict(intent.to_dict()) == intent
    assert PluginRetirementIntentRecordV1.from_dict(record.to_dict()) == record
    for record_type, value in (
        (PluginRetirementIntentV1, intent),
        (PluginRetirementIntentRecordV1, record),
    ):
        with pytest.raises(PluginRetirementRecordCodecError) as caught:
            record_type.from_dict({**value.to_dict(), "unknown": True})
        assert caught.value.code == "invalid_plugin_retirement_record"

    unsupported = record.to_dict()
    unsupported["recordVersion"] = 2
    with pytest.raises(PluginRetirementRecordCodecError) as caught:
        PluginRetirementIntentRecordV1.from_dict(unsupported)
    assert caught.value.code == "unsupported_plugin_retirement_record_version"

    with pytest.raises(ValueError, match="does not match"):
        PluginRetirementIntentV1(
            retirement_id=intent.retirement_id,
            trigger=intent.trigger,
            mode=intent.mode,
            instance_revision_ref=replace(intent.instance_revision_ref, revision=99),
            package_revision=intent.package_revision,
            source_transition=intent.source_transition,
        )


def test_retirement_ledger_repairs_tail_and_rejects_duplicate_subject(
    tmp_path: Path,
) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    desired.commit(_mutation("install", revision=0, operation=1))
    desired.commit(_mutation("enable", revision=1, operation=2))
    transition = desired.commit(_mutation("disable", revision=2, operation=3))
    path = tmp_path / "retirements.jsonl"
    retirements = PluginRetirementIntentLedger(path)
    retirements.request_for(transition)
    committed = path.read_bytes()

    with path.open("ab") as handle:
        handle.write(b'{"recordVersion":')
    assert retirements.snapshot().journal_revision == 1
    assert path.read_bytes() == committed

    first = json.loads(committed)
    first["journalRevision"] = 2
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(first, sort_keys=True) + "\n")
    with pytest.raises(PluginRetirementError) as caught:
        retirements.snapshot()
    assert caught.value.code == "plugin_retirement_journal_corrupt"


def test_retirement_ledger_rejects_second_intent_for_same_instance(
    tmp_path: Path,
) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    desired.commit(_mutation("install", revision=0, operation=1))
    desired.commit(_mutation("enable", revision=1, operation=2))
    transition = desired.commit(_mutation("disable", revision=2, operation=3))
    retirements = PluginRetirementIntentLedger(tmp_path / "retirements.jsonl")
    retirements.request_for(transition)
    conflicting = replace(
        transition,
        mutation=replace(
            transition.mutation,
            operation_id="operation-other",
            idempotency_key="request-other",
        ),
    )

    with pytest.raises(PluginRetirementError) as caught:
        retirements.request_for(conflicting)
    assert caught.value.code == "plugin_retirement_intent_conflict"


def test_management_service_hands_off_disable_remove_and_update_intents(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    retirement_path = tmp_path / "retirements.jsonl"
    desired = PluginDesiredStateLedger(
        desired_path,
        instance_id_factory=lambda: "instance-1",
    )
    retirements = PluginRetirementIntentLedger(retirement_path)
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
        retirement_intents=retirements,
    )
    service.submit(_command("install", revision=0, operation=1))
    service.submit(_command("enable", revision=1, operation=2))
    update_terminal = service.submit(_update_command(revision=2, operation=3))
    disable_terminal = service.submit(_command("disable", revision=3, operation=4))
    service.submit(_command("remove", revision=4, operation=5))

    intents = retirements.snapshot().intents
    assert len(intents) == 2
    assert tuple(intent.trigger for intent in intents) == ("update", "disable")
    assert tuple(intent.instance_revision_ref.revision for intent in intents) == (1, 2)
    assert update_terminal.result is not None
    assert update_terminal.result.disposition == "restart_required"
    assert disable_terminal.result is not None
    assert disable_terminal.result.disposition == "succeeded"
    assert service.operations()[-1].command.operation_id == "operation-5"


def test_recovery_writes_missing_intent_after_desired_cutover(tmp_path: Path) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    retirement_path = tmp_path / "retirements.jsonl"
    desired = PluginDesiredStateLedger(
        desired_path,
        instance_id_factory=lambda: "instance-1",
    )
    retirements = PluginRetirementIntentLedger(retirement_path)
    setup = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=retirements,
    )
    setup.submit(_command("install", revision=0, operation=1))
    setup.submit(_command("enable", revision=1, operation=2))
    crashing = PluginManagementService(
        desired_state=_CommitThenCrashOnRetirementTransition(desired),
        operation_journal_path=operation_path,
        retirement_intents=retirements,
    )

    with pytest.raises(RuntimeError, match="after desired retirement cutover"):
        crashing.submit(_command("disable", revision=2, operation=3))
    assert desired.snapshot().inventory_revision == 3
    assert retirements.snapshot().journal_revision == 0

    fresh = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=retirements,
    )
    terminal = fresh.recover()[0]
    assert terminal.result is not None
    assert terminal.result.disposition == "succeeded"
    assert retirements.snapshot().journal_revision == 1
    assert len(desired.transitions()) == 3


def test_recovery_does_not_duplicate_intent_after_intent_append(
    tmp_path: Path,
) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    operation_path = tmp_path / "operations.jsonl"
    retirement_path = tmp_path / "retirements.jsonl"
    retirements = PluginRetirementIntentLedger(retirement_path)
    setup = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=retirements,
    )
    setup.submit(_command("install", revision=0, operation=1))
    setup.submit(_command("enable", revision=1, operation=2))
    crashing = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=_AppendIntentThenCrash(retirements),
    )

    with pytest.raises(RuntimeError, match="after retirement intent append"):
        crashing.submit(_command("disable", revision=2, operation=3))
    assert retirements.snapshot().journal_revision == 1

    fresh = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=retirements,
    )
    terminal = fresh.recover()[0]
    assert terminal.result is not None
    assert terminal.result.disposition == "succeeded"
    assert retirements.snapshot().journal_revision == 1


def test_terminal_retirement_cross_log_contradictions_fail_closed(
    tmp_path: Path,
) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    retirement_path = tmp_path / "retirements.jsonl"
    desired = PluginDesiredStateLedger(
        desired_path,
        instance_id_factory=lambda: "instance-1",
    )
    retirements = PluginRetirementIntentLedger(retirement_path)
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=retirements,
    )
    service.submit(_command("install", revision=0, operation=1))
    service.submit(_command("enable", revision=1, operation=2))
    service.submit(_command("disable", revision=2, operation=3))
    retirement_bytes = retirement_path.read_bytes()

    retirement_path.write_text("", encoding="utf-8")
    with pytest.raises(PluginRetirementError) as caught:
        service.operations()
    assert caught.value.code == "plugin_retirement_journal_corrupt"

    retirement_path.write_bytes(retirement_bytes)
    desired_path.write_bytes(b"".join(desired_path.read_bytes().splitlines(keepends=True)[:2]))
    with pytest.raises(PluginRetirementError) as caught:
        service.operations()
    assert caught.value.code == "plugin_retirement_journal_corrupt"


def test_two_services_serialize_one_exact_retirement_handoff(tmp_path: Path) -> None:
    desired_path = tmp_path / "desired.jsonl"
    operation_path = tmp_path / "operations.jsonl"
    retirement_path = tmp_path / "retirements.jsonl"
    desired = PluginDesiredStateLedger(
        desired_path,
        instance_id_factory=lambda: "instance-1",
    )
    setup = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=PluginRetirementIntentLedger(retirement_path),
    )
    setup.submit(_command("install", revision=0, operation=1))
    setup.submit(_command("enable", revision=1, operation=2))
    command = _command("disable", revision=2, operation=3)
    barrier = Barrier(2)

    def submit():
        service = PluginManagementService(
            desired_state=PluginDesiredStateLedger(desired_path),
            operation_journal_path=operation_path,
            retirement_intents=PluginRetirementIntentLedger(retirement_path),
        )
        barrier.wait()
        return service.submit(command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(submit) for _ in range(2))
        results = tuple(future.result() for future in futures)

    assert results[0] == results[1]
    assert PluginRetirementIntentLedger(retirement_path).snapshot().journal_revision == 1
    assert PluginDesiredStateLedger(desired_path).snapshot().inventory_revision == 3


class _CommitThenCrashOnRetirementTransition:
    def __init__(self, desired: PluginDesiredStateLedger) -> None:
        self._desired = desired
        self._crashed = False

    @property
    def path(self) -> Path:
        return self._desired.path

    def commit(self, mutation):
        transition = self._desired.commit(mutation)
        if transition.transition_kind == "disable" and not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated crash after desired retirement cutover")
        return transition

    def commit_update(self, mutation):
        return self._desired.commit_update(mutation)

    def snapshot(self):
        return self._desired.snapshot()

    def transitions(self):
        return self._desired.transitions()


class _AppendIntentThenCrash:
    def __init__(self, retirements: PluginRetirementIntentLedger) -> None:
        self._retirements = retirements
        self._crashed = False

    @property
    def path(self) -> Path:
        return self._retirements.path

    def request_for(self, transition):
        intent = self._retirements.request_for(transition)
        if intent is not None and not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated crash after retirement intent append")
        return intent

    def snapshot(self):
        return self._retirements.snapshot()


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


def _mutation(
    action: PluginManagementAction,
    *,
    revision: int,
    operation: int,
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
        package_revision=_package(1) if action == "install" else None,
        actor_id="operator-1",
        policy_revision="policy-1",
    )


def _command(
    action: PluginManagementAction, *, revision: int, operation: int
) -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action=action,
        mutation=_mutation(action, revision=revision, operation=operation),
    )


def _update_mutation(
    *, revision: int, operation: str, enabled: bool
) -> PluginDesiredStateUpdateMutationV1:
    command = PluginManagementUpdateCommandV2(
        operation_id=operation,
        idempotency_key=f"request-{operation}",
        expected_inventory_revision=revision,
        installation_key=_key(),
        expected_package_revision=_package(1),
        staged_package_revision=_package(2),
        actor_id="operator-1",
        policy_revision="policy-1",
    )
    return PluginDesiredStateUpdateMutationV1(
        command=command,
        desired_state="installed_enabled" if enabled else "installed_disabled",
        migration_fence=migration_fence_for(command),
    )


def _update_command(
    *, revision: int, operation: int
) -> PluginManagementUpdateCommandV2:
    return PluginManagementUpdateCommandV2(
        operation_id=f"operation-{operation}",
        idempotency_key=f"request-{operation}",
        expected_inventory_revision=revision,
        installation_key=_key(),
        expected_package_revision=_package(1),
        staged_package_revision=_package(2),
        actor_id="operator-1",
        policy_revision="policy-1",
    )
