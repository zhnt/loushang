from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

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
    PluginRetirementIntentLedger,
    PluginRetirementIntentV1,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginOwnerRetirementOutcomeV1,
    PluginOwnerRetirementPlanV1,
    PluginOwnerRetirementTargetV1,
    PluginRetirementSetError,
    PluginRetirementSetEventV1,
    PluginRetirementSetLedger,
    PluginRetirementSetRecordCodecError,
)
from loushang.harness.plugin_management.service import PluginManagementService


def test_retirement_set_records_are_strict_derived_and_round_trip(
    tmp_path: Path,
) -> None:
    intent, _, _ = _retirement_evidence(tmp_path)
    target = _target("a")
    plan = _plan(intent, target)
    outcome = _outcome(intent, target, attempt=1, disposition="succeeded")
    event = PluginRetirementSetEventV1.opened(
        journal_revision=1,
        intent=intent,
    )

    assert PluginOwnerRetirementTargetV1.from_dict(target.to_dict()) == target
    assert PluginOwnerRetirementPlanV1.from_dict(plan.to_dict()) == plan
    assert PluginOwnerRetirementOutcomeV1.from_dict(outcome.to_dict()) == outcome
    assert PluginRetirementSetEventV1.from_dict(event.to_dict()) == event

    for record_type, value in (
        (PluginOwnerRetirementTargetV1, target),
        (PluginOwnerRetirementPlanV1, plan),
        (PluginOwnerRetirementOutcomeV1, outcome),
        (PluginRetirementSetEventV1, event),
    ):
        with pytest.raises(PluginRetirementSetRecordCodecError) as caught:
            record_type.from_dict({**value.to_dict(), "unknown": True})
        assert caught.value.code == "invalid_plugin_retirement_set_record"

    unsupported = event.to_dict()
    unsupported["recordVersion"] = 2
    with pytest.raises(PluginRetirementSetRecordCodecError) as caught:
        PluginRetirementSetEventV1.from_dict(unsupported)
    assert caught.value.code == "unsupported_plugin_retirement_set_record_version"

    with pytest.raises(ValueError, match="does not match"):
        replace(target, retirement_handle="changed")
    with pytest.raises(ValueError, match="not structural"):
        replace(outcome, result_code="Owner said no")


def test_retirement_plan_is_complete_sorted_and_exact() -> None:
    first = _target("a")
    second = _target("b")
    targets = tuple(sorted((first, second), key=lambda item: item.target_id))
    retirement_id = "1" * 64

    plan = PluginOwnerRetirementPlanV1.create(
        retirement_id=retirement_id,
        owner_closure_reference="closure:1",
        targets=targets,
    )
    assert plan.targets == targets

    with pytest.raises(ValueError, match="sorted"):
        PluginOwnerRetirementPlanV1.create(
            retirement_id=retirement_id,
            owner_closure_reference="closure:1",
            targets=tuple(reversed(targets)),
        )

    duplicate_owner_generation = PluginOwnerRetirementTargetV1.create(
        owner_reference=first.owner_reference,
        owner_generation_reference=first.owner_generation_reference,
        retirement_handle="retirement:other",
        contribution_ids=("contribution:other",),
    )
    duplicate_targets = tuple(
        sorted((first, duplicate_owner_generation), key=lambda item: item.target_id)
    )
    with pytest.raises(ValueError, match="owner generation pairs"):
        PluginOwnerRetirementPlanV1.create(
            retirement_id=retirement_id,
            owner_closure_reference="closure:1",
            targets=duplicate_targets,
        )


def test_retirement_set_open_is_source_checked_and_idempotent(
    tmp_path: Path,
) -> None:
    intent, intents, ledger = _retirement_evidence(tmp_path)

    opened = ledger.open_set(intent)
    assert opened.intent == intent
    assert opened.plan is None
    assert opened.state == "collecting"
    assert ledger.open_set(intent) == opened
    assert ledger.snapshot().journal_revision == 1

    unrelated_intents = PluginRetirementIntentLedger(tmp_path / "other-intents.jsonl")
    unrelated_sets = PluginRetirementSetLedger(
        tmp_path / "other-sets.jsonl",
        retirement_intents=unrelated_intents,
    )
    with pytest.raises(PluginRetirementSetError) as caught:
        unrelated_sets.open_set(intent)
    assert caught.value.code == "plugin_retirement_set_journal_corrupt"
    assert intents.snapshot().intents == (intent,)


def test_empty_owner_plan_succeeds_without_claiming_instance_retirement(
    tmp_path: Path,
) -> None:
    intent, _, ledger = _retirement_evidence(tmp_path)
    ledger.open_set(intent)

    plan = PluginOwnerRetirementPlanV1.create(
        retirement_id=intent.retirement_id,
        owner_closure_reference="closure:empty",
        targets=(),
    )
    sealed = ledger.commit_plan(plan)

    assert sealed.state == "succeeded"
    assert sealed.latest_outcomes == ()
    assert ledger.commit_plan(plan) == sealed
    assert ledger.snapshot().journal_revision == 2


def test_owner_results_aggregate_only_when_every_exact_target_succeeds(
    tmp_path: Path,
) -> None:
    intent, _, ledger = _retirement_evidence(tmp_path)
    ledger.open_set(intent)
    targets = tuple(
        sorted((_target("a"), _target("b")), key=lambda item: item.target_id)
    )
    plan = PluginOwnerRetirementPlanV1.create(
        retirement_id=intent.retirement_id,
        owner_closure_reference="closure:two",
        targets=targets,
    )

    assert ledger.commit_plan(plan).state == "retiring"
    first = ledger.record_outcome(
        _outcome(intent, targets[0], attempt=1, disposition="succeeded")
    )
    assert first.state == "retiring"
    completed = ledger.record_outcome(
        _outcome(
            intent,
            targets[1],
            attempt=1,
            disposition="succeeded",
        )
    )
    assert completed.state == "succeeded"
    assert tuple(item.target_id for item in completed.latest_outcomes) == tuple(
        item.target_id for item in targets
    )


def test_retryable_owner_result_requires_contiguous_attempt_then_can_recover(
    tmp_path: Path,
) -> None:
    intent, _, ledger = _retirement_evidence(tmp_path)
    ledger.open_set(intent)
    target = _target("a")
    ledger.commit_plan(_plan(intent, target))
    retryable = _outcome(
        intent,
        target,
        attempt=1,
        disposition="retryable_failure",
    )

    assert ledger.record_outcome(retryable).state == "retryable_failure"
    assert ledger.record_outcome(retryable).state == "retryable_failure"
    assert ledger.snapshot().journal_revision == 3

    with pytest.raises(PluginRetirementSetError) as caught:
        ledger.record_outcome(
            _outcome(
                intent,
                target,
                attempt=3,
                disposition="succeeded",
                sequence=3,
            )
        )
    assert caught.value.code == "invalid_plugin_retirement_set_transition"

    recovered = ledger.record_outcome(
        _outcome(
            intent,
            target,
            attempt=2,
            disposition="succeeded",
            sequence=2,
        )
    )
    assert recovered.state == "succeeded"

    with pytest.raises(PluginRetirementSetError) as caught:
        ledger.record_outcome(
            _outcome(
                intent,
                target,
                attempt=3,
                disposition="succeeded",
                sequence=3,
            )
        )
    assert caught.value.code == "invalid_plugin_retirement_set_transition"

    with pytest.raises(PluginRetirementSetError) as caught:
        ledger.record_outcome(replace(retryable, operation_id="owner-operation-new"))
    assert caught.value.code == "plugin_retirement_set_conflict"


def test_terminal_owner_failure_is_not_retryable(tmp_path: Path) -> None:
    intent, _, ledger = _retirement_evidence(tmp_path)
    ledger.open_set(intent)
    target = _target("a")
    ledger.commit_plan(_plan(intent, target))

    terminal = ledger.record_outcome(
        _outcome(intent, target, attempt=1, disposition="terminal_failure")
    )
    assert terminal.state == "terminal_failure"

    with pytest.raises(PluginRetirementSetError) as caught:
        ledger.record_outcome(
            _outcome(
                intent,
                target,
                attempt=2,
                disposition="succeeded",
                sequence=2,
            )
        )
    assert caught.value.code == "invalid_plugin_retirement_set_transition"


def test_retirement_set_repairs_partial_tail_and_rejects_complete_corruption(
    tmp_path: Path,
) -> None:
    intent, _, ledger = _retirement_evidence(tmp_path)
    path = ledger.path
    ledger.open_set(intent)
    committed = path.read_bytes()

    with path.open("ab") as handle:
        handle.write(b'{"recordVersion":')
    assert ledger.snapshot().journal_revision == 1
    assert path.read_bytes() == committed

    duplicate = json.loads(committed)
    duplicate["journalRevision"] = 2
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(duplicate, sort_keys=True) + "\n")
    with pytest.raises(PluginRetirementSetError) as caught:
        ledger.snapshot()
    assert caught.value.code == "plugin_retirement_set_journal_corrupt"


def test_retirement_set_fails_closed_when_source_intent_disappears(
    tmp_path: Path,
) -> None:
    intent, intents, ledger = _retirement_evidence(tmp_path)
    ledger.open_set(intent)
    intents.path.write_text("", encoding="utf-8")

    with pytest.raises(PluginRetirementSetError) as caught:
        ledger.snapshot()
    assert caught.value.code == "plugin_retirement_set_journal_corrupt"


@pytest.mark.parametrize("action", ["disable", "remove"])
def test_management_handoff_opens_collecting_set_without_owner_execution(
    tmp_path: Path,
    action: PluginManagementAction,
) -> None:
    service, intents, sets = _management(tmp_path)
    service.submit(_command("install", revision=0, operation=1))
    service.submit(_command("enable", revision=1, operation=2))
    terminal = service.submit(_command(action, revision=2, operation=3))

    assert terminal.status == "terminal"
    assert intents.snapshot().journal_revision == 1
    snapshot = sets.snapshot()
    assert snapshot.journal_revision == 1
    assert len(snapshot.sets) == 1
    assert snapshot.sets[0].state == "collecting"
    assert snapshot.sets[0].plan is None
    assert snapshot.sets[0].intent.trigger == action
    assert service.retirement_set_journal_path == sets.path


def test_disabled_installation_remove_does_not_fabricate_retirement_set(
    tmp_path: Path,
) -> None:
    service, intents, sets = _management(tmp_path)
    service.submit(_command("install", revision=0, operation=1))
    service.submit(_command("remove", revision=1, operation=2))

    assert intents.snapshot().journal_revision == 0
    assert sets.snapshot().journal_revision == 0


def test_recovery_opens_missing_set_after_intent_handoff(tmp_path: Path) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    operations = tmp_path / "operations.jsonl"
    intents = PluginRetirementIntentLedger(tmp_path / "intents.jsonl")
    sets = PluginRetirementSetLedger(
        tmp_path / "sets.jsonl",
        retirement_intents=intents,
    )
    setup = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    setup.submit(_command("install", revision=0, operation=1))
    setup.submit(_command("enable", revision=1, operation=2))
    crashing = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operations,
        retirement_intents=intents,
        retirement_sets=_CrashBeforeOpen(sets),
    )

    with pytest.raises(RuntimeError, match="before retirement set open"):
        crashing.submit(_command("disable", revision=2, operation=3))
    assert intents.snapshot().journal_revision == 1
    assert sets.snapshot().journal_revision == 0

    recovered = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operations,
        retirement_intents=intents,
        retirement_sets=sets,
    ).recover()
    assert recovered[0].status == "terminal"
    assert sets.snapshot().journal_revision == 1


def test_recovery_does_not_duplicate_set_after_open_append(tmp_path: Path) -> None:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    operations = tmp_path / "operations.jsonl"
    intents = PluginRetirementIntentLedger(tmp_path / "intents.jsonl")
    sets = PluginRetirementSetLedger(
        tmp_path / "sets.jsonl",
        retirement_intents=intents,
    )
    setup = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    setup.submit(_command("install", revision=0, operation=1))
    setup.submit(_command("enable", revision=1, operation=2))
    crashing = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operations,
        retirement_intents=intents,
        retirement_sets=_AppendOpenThenCrash(sets),
    )

    with pytest.raises(RuntimeError, match="after retirement set open"):
        crashing.submit(_command("disable", revision=2, operation=3))
    assert sets.snapshot().journal_revision == 1

    recovered = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operations,
        retirement_intents=intents,
        retirement_sets=sets,
    ).recover()
    assert recovered[0].status == "terminal"
    assert sets.snapshot().journal_revision == 1


def test_terminal_management_evidence_requires_exact_retirement_set(
    tmp_path: Path,
) -> None:
    service, _, sets = _management(tmp_path)
    service.submit(_command("install", revision=0, operation=1))
    service.submit(_command("enable", revision=1, operation=2))
    service.submit(_command("disable", revision=2, operation=3))
    sets.path.write_text("", encoding="utf-8")

    with pytest.raises(PluginRetirementSetError) as caught:
        service.operations()
    assert caught.value.code == "plugin_retirement_set_journal_corrupt"


class _CrashBeforeOpen:
    def __init__(self, sets: PluginRetirementSetLedger) -> None:
        self._sets = sets
        self._crashed = False

    @property
    def path(self) -> Path:
        return self._sets.path

    def open_set(self, intent):
        if not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated crash before retirement set open")
        return self._sets.open_set(intent)

    def snapshot(self):
        return self._sets.snapshot()


class _AppendOpenThenCrash:
    def __init__(self, sets: PluginRetirementSetLedger) -> None:
        self._sets = sets
        self._crashed = False

    @property
    def path(self) -> Path:
        return self._sets.path

    def open_set(self, intent):
        opened = self._sets.open_set(intent)
        if not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated crash after retirement set open")
        return opened

    def snapshot(self):
        return self._sets.snapshot()


def _retirement_evidence(
    tmp_path: Path,
) -> tuple[
    PluginRetirementIntentV1,
    PluginRetirementIntentLedger,
    PluginRetirementSetLedger,
]:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    desired.commit(_mutation("install", revision=0, operation=1))
    desired.commit(_mutation("enable", revision=1, operation=2))
    transition = desired.commit(_mutation("disable", revision=2, operation=3))
    intents = PluginRetirementIntentLedger(tmp_path / "intents.jsonl")
    intent = intents.request_for(transition)
    assert intent is not None
    return (
        intent,
        intents,
        PluginRetirementSetLedger(
            tmp_path / "sets.jsonl",
            retirement_intents=intents,
        ),
    )


def _management(
    tmp_path: Path,
) -> tuple[
    PluginManagementService,
    PluginRetirementIntentLedger,
    PluginRetirementSetLedger,
]:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    intents = PluginRetirementIntentLedger(tmp_path / "intents.jsonl")
    sets = PluginRetirementSetLedger(
        tmp_path / "sets.jsonl",
        retirement_intents=intents,
    )
    return (
        PluginManagementService(
            desired_state=desired,
            operation_journal_path=tmp_path / "operations.jsonl",
            retirement_intents=intents,
            retirement_sets=sets,
        ),
        intents,
        sets,
    )


def _target(suffix: str) -> PluginOwnerRetirementTargetV1:
    return PluginOwnerRetirementTargetV1.create(
        owner_reference=f"owner:{suffix}",
        owner_generation_reference=f"generation:{suffix}",
        retirement_handle=f"retirement:{suffix}",
        contribution_ids=(f"contribution:{suffix}",),
    )


def _plan(
    intent: PluginRetirementIntentV1,
    target: PluginOwnerRetirementTargetV1,
) -> PluginOwnerRetirementPlanV1:
    return PluginOwnerRetirementPlanV1.create(
        retirement_id=intent.retirement_id,
        owner_closure_reference="closure:one",
        targets=(target,),
    )


def _outcome(
    intent: PluginRetirementIntentV1,
    target: PluginOwnerRetirementTargetV1,
    *,
    attempt: int,
    disposition: str,
    sequence: int = 1,
) -> PluginOwnerRetirementOutcomeV1:
    return PluginOwnerRetirementOutcomeV1(
        retirement_id=intent.retirement_id,
        target_id=target.target_id,
        operation_id=f"owner-operation-{sequence}",
        idempotency_key=f"owner-request-{sequence}",
        attempt=attempt,
        disposition=disposition,  # type: ignore[arg-type]
        result_code=f"owner_retirement_{disposition}",
        owner_outcome_reference=f"outcome:{sequence}",
    )


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
    action: PluginManagementAction,
    *,
    revision: int,
    operation: int,
) -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action=action,
        mutation=_mutation(action, revision=revision, operation=operation),
    )
