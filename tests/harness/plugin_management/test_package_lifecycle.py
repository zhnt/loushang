from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.continuity.plugin_provider import (
    ContinuityPluginGenerationGate,
)
from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginInstanceFamilyLease,
    ContinuityPluginSecurityRetirementEvidence,
    _create_continuity_plugin_publication,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
    PluginInstanceLedgerContinuityFamilyAuthority,
    PluginInstanceLedgerContinuitySecurityRetirementAuthority,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRetirementCompletionV1,
    PluginInstanceRevocationV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeError,
    PluginInstanceRuntimeLedger,
    PluginInstanceRuntimeSnapshotV1,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementAction,
    PluginManagementCommandV1,
)
from loushang.harness.plugin_management.package_gc import PluginPackageGcReadModel
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationError,
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageGcCandidateV1,
    PluginPackageLifecycleError,
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.package_records import (
    PluginCleanupAttemptV1,
    PluginCleanupDisposition,
    PluginCleanupRepairDecisionV1,
    PluginCleanupTaskV1,
    PluginPackageLifecycleEventV1,
    PluginPackageLifecycleRecordCodecError,
    PluginPackagePinReleaseV1,
    PluginPackagePinV1,
    PluginPackageRecoveryBarrierV1,
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
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_plc9d1_gc_projection_cannot_import_store_or_deletion_authority() -> None:
    source = Path("src/loushang/harness/plugin_management/package_gc.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert imported <= {
        "__future__",
        "dataclasses",
        "typing",
        "loushang.harness.plugin_management.package_lifecycle",
        "loushang.harness.plugin_management.records",
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))


def test_plc9d2_gc_reservation_has_no_store_or_deletion_import() -> None:
    source = Path("src/loushang/harness/plugin_management/package_gc_reservation.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        module is not None and module.startswith("loushang.harness.resources.packages")
        for module in imported
    )
    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name in {"os", "shutil"} for alias in node.names)
        for node in ast.walk(tree)
    )


def test_continuity_publication_security_close_hands_off_package_cleanup(
    tmp_path: Path,
) -> None:
    asyncio.run(_continuity_publication_security_close_hands_off_cleanup(tmp_path))


def test_continuity_family_authority_rejects_mixed_durable_source_graph(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    colliding_packages = PluginPackageLifecycleLedger(
        context.security_acceptances.path,
        startup_id="startup-collision",
        desired_state=context.desired,
        instance_runtime=context.runtime,
        retirement_sets=context.sets,
    )
    with pytest.raises(ValueError, match="journals must be distinct"):
        PluginInstanceLedgerContinuityFamilyAuthority(
            ledger=context.runtime,
            package_lifecycle=colliding_packages,
            security_acceptance_journal=context.security_acceptances,
        )

    other_root = tmp_path / "other-runtime"
    other_root.mkdir()
    other = _context(other_root)
    with pytest.raises(ValueError, match="another Instance ledger"):
        PluginInstanceLedgerContinuityFamilyAuthority(
            ledger=context.runtime,
            package_lifecycle=other.packages,
            security_acceptance_journal=context.security_acceptances,
        )


async def _continuity_publication_security_close_hands_off_cleanup(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key)
    active = _activate(context, key)
    journal = context.security_acceptances
    family_authority = PluginInstanceLedgerContinuityFamilyAuthority(
        ledger=context.runtime,
        package_lifecycle=context.packages,
        security_acceptance_journal=journal,
    )
    family = await family_authority.acquire(
        active.instance_revision_ref,
        holder_reference="continuity-owner-generation:security-test",
    )
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="continuity-security-revoke",
        idempotency_key="continuity-security-revoke-request",
        authority_reference="security:continuity",
        reason_code="source_revoked",
    )
    retirement = PluginInstanceLedgerContinuitySecurityRetirementAuthority(
        ledger=context.runtime,
        acceptance_journal=journal,
        revocations=(revocation,),
    )
    generation = _ContinuitySecurityGeneration(
        family=family,
        instance_revision_ref=active.instance_revision_ref,
    )
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=_ContinuitySecurityHub(generation.events),  # type: ignore[arg-type]
    )

    await publication.security_revoke(
        retirement=retirement,
        quiesce_timeout=1.0,
    )

    assert journal.records()[0].revocations == (revocation,)
    instance = context.runtime.snapshot().instance(active.instance_revision_ref)
    assert instance is not None
    assert instance.state == "REVOKING"
    assert context.runtime.snapshot().family(family.family_id) is None
    [cleanup] = context.packages.snapshot().cleanup_tasks
    assert cleanup.task.coordination_kind == "security"
    assert cleanup.task.coordination_id == revocation.revocation_id
    assert cleanup.task.cleanup_kind == "continuity.owner.security_shutdown"
    assert cleanup.lease_open is True
    assert generation.events == ["hub-close", "security-handoff", "dispose"]


@dataclass(slots=True)
class _ContinuitySecurityGeneration:
    family: ContinuityPluginInstanceFamilyLease
    instance_revision_ref: PluginInstanceRevisionRef
    events: list[str] = field(default_factory=list)
    gate: ContinuityPluginGenerationGate = field(
        default_factory=ContinuityPluginGenerationGate
    )
    security_evidence: ContinuityPluginSecurityRetirementEvidence | None = None

    @property
    def resolved(self) -> object:
        candidate = SimpleNamespace(instance_revision_ref=self.instance_revision_ref)
        component = SimpleNamespace(admission=SimpleNamespace(candidate=candidate))
        return SimpleNamespace(resolved_set=SimpleNamespace(components=(component,)))

    def authorize_security_cleanup(
        self,
        evidence: ContinuityPluginSecurityRetirementEvidence,
    ) -> None:
        self.security_evidence = evidence

    async def dispose(self) -> None:
        assert self.security_evidence is not None
        await self.family.security_handoff(self.security_evidence)
        self.events.append("security-handoff")
        await self.family.close()
        self.events.append("dispose")


@dataclass(slots=True)
class _ContinuitySecurityHub:
    events: list[str]

    async def close(self) -> None:
        self.events.append("hub-close")


def test_package_lifecycle_records_are_strict_derived_and_round_trip() -> None:
    key = _key("plugin.a")
    instance = PluginInstanceRevisionRef(
        instance_id="instance-a",
        plugin_id="plugin.a",
        revision=1,
    )
    package = _package("plugin.a", "a")
    family = PluginInstanceLeaseFamilyV1.create(
        lease_kind="owner_generation",
        operation_id="owner-family",
        idempotency_key="owner-family-request",
        holder_reference="owner:a",
        parent_family_id=None,
        source_inventory_revision=2,
        member_subjects=((key, instance, package),),
    )
    pin = PluginPackagePinV1.create(
        package_revision=package,
        pin_kind="cold_resume",
        operation_id="pin-a",
        idempotency_key="pin-request-a",
        holder_reference="resume:a",
    )
    pin_release = _pin_release(pin, suffix="a")
    task = PluginCleanupTaskV1.create(
        source_runtime_revision=3,
        source_family=family,
        coordination_kind="graceful",
        coordination_id="a" * 64,
        retirement_target_id="b" * 64,
        cleanup_kind="owner.shutdown",
        operation_id="cleanup-a",
        idempotency_key="cleanup-request-a",
        cleanup_reference="cleanup:a",
    )
    attempt = _attempt(task, 1, "terminal_failure", suffix="terminal")
    repair = PluginCleanupRepairDecisionV1.create(
        cleanup_id=task.cleanup_id,
        repair_sequence=1,
        action="safe_abandon",
        operation_id="repair-a",
        idempotency_key="repair-request-a",
        authority_reference="operator:a",
        reason_code="effect.acknowledged",
    )
    barrier = PluginPackageRecoveryBarrierV1.create(
        startup_id="startup-a",
        operation_id="recover-a",
        idempotency_key="recover-request-a",
        recovery_reference="recovery:a",
        observed_desired_inventory_revision=2,
        observed_instance_runtime_revision=3,
        observed_package_journal_revision=5,
        open_pin_ids=(pin.pin_id,),
        open_cleanup_ids=(task.cleanup_id,),
    )
    event = PluginPackageLifecycleEventV1.for_payload(
        journal_revision=1,
        payload=pin,
    )

    for record_type, value in (
        (PluginPackagePinV1, pin),
        (PluginPackagePinReleaseV1, pin_release),
        (PluginCleanupTaskV1, task),
        (PluginCleanupAttemptV1, attempt),
        (PluginCleanupRepairDecisionV1, repair),
        (PluginPackageRecoveryBarrierV1, barrier),
        (PluginPackageLifecycleEventV1, event),
    ):
        assert record_type.from_dict(value.to_dict()) == value
        with pytest.raises(PluginPackageLifecycleRecordCodecError) as caught:
            record_type.from_dict({**value.to_dict(), "unknown": True})
        assert caught.value.code == "invalid_plugin_package_lifecycle_record"

    unsupported = event.to_dict()
    unsupported["recordVersion"] = 2
    with pytest.raises(PluginPackageLifecycleRecordCodecError) as caught:
        PluginPackageLifecycleEventV1.from_dict(unsupported)
    assert caught.value.code == "unsupported_plugin_package_lifecycle_record_version"

    candidate = PluginPackageGcCandidateV1.create(
        package_revision=package,
        desired_inventory_revision=3,
        instance_runtime_revision=9,
        package_journal_revision=6,
        recovery_barrier_id=barrier.barrier_id,
    )
    with pytest.raises(ValueError, match="does not match"):
        replace(candidate, candidate_id="0" * 64)
    with pytest.raises(ValueError, match="Terminal cleanup attempt"):
        replace(
            attempt,
            disposition="succeeded",
            retry_not_before_epoch_ms=1,
        )


def test_explicit_pin_recovery_restart_and_stale_acquisition(tmp_path: Path) -> None:
    context = _context(tmp_path, startup_id="startup-a")
    package = _package("plugin.a", "a")
    pin = context.packages.acquire_pin(
        package,
        pin_kind="forensic_retention",
        operation_id="pin-a",
        idempotency_key="pin-request-a",
        holder_reference="forensic:a",
    )
    assert (
        context.packages.acquire_pin(
            package,
            pin_kind="forensic_retention",
            operation_id="pin-a",
            idempotency_key="pin-request-a",
            holder_reference="forensic:a",
        )
        == pin
    )
    barrier = context.packages.complete_startup_recovery(
        operation_id="recover-a",
        idempotency_key="recover-request-a",
        recovery_reference="recovery:a",
    )
    restarted = _package_ledger(context, startup_id="startup-a")
    new_startup = _package_ledger(context, startup_id="startup-b")

    assert restarted.snapshot().recovery_barrier == barrier
    assert restarted.snapshot().open_pins == (pin,)
    assert not new_startup.snapshot().startup_recovered
    with pytest.raises(PluginPackageLifecycleError) as caught:
        new_startup.gc_candidates()
    assert caught.value.code == "plugin_package_recovery_incomplete"

    release = _pin_release(pin, suffix="a")
    assert context.packages.release_pin(release) == release
    assert context.packages.release_pin(release) == release
    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.acquire_pin(
            package,
            pin_kind="forensic_retention",
            operation_id="pin-a",
            idempotency_key="pin-request-a",
            holder_reference="forensic:a",
        )
    assert caught.value.code == "invalid_plugin_package_lifecycle_transition"
    assert context.packages.gc_candidates()[0].package_revision == package


def test_graceful_cleanup_handoff_is_write_ahead_and_retry_safe(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    prepared = _prepare_graceful_retirement(context)
    release = _family_release(prepared.owner_family, suffix="owner")
    task = context.packages.handoff_cleanup_and_release(
        prepared.owner_family.family_id,
        retirement_target_id=prepared.target.target_id,
        cleanup_kind="owner.shutdown",
        operation_id="cleanup-owner",
        idempotency_key="cleanup-owner-request",
        cleanup_reference="cleanup:owner",
        family_release=release,
    )

    assert context.packages.events()[0].cleanup_task == task
    assert context.runtime.snapshot().family(prepared.owner_family.family_id) is None
    cleanup = context.packages.snapshot().cleanup(task.cleanup_id)
    assert cleanup is not None
    assert cleanup.lease_open
    assert (
        context.packages.handoff_cleanup_and_release(
            prepared.owner_family.family_id,
            retirement_target_id=prepared.target.target_id,
            cleanup_kind="owner.shutdown",
            operation_id="cleanup-owner",
            idempotency_key="cleanup-owner-request",
            cleanup_reference="cleanup:owner",
            family_release=release,
        )
        == task
    )
    assert len(context.packages.events()) == 1

    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.handoff_cleanup_and_release(
            prepared.direct_family.family_id,
            retirement_target_id=prepared.target.target_id,
            cleanup_kind="host.shutdown",
            operation_id="cleanup-host-bad",
            idempotency_key="cleanup-host-bad-request",
            cleanup_reference="cleanup:host-bad",
            family_release=_family_release(prepared.direct_family, suffix="host-bad"),
        )
    assert caught.value.code == "invalid_plugin_package_lifecycle_transition"


def test_failed_family_release_leaves_cleanup_lease_pinned(tmp_path: Path) -> None:
    context = _context(tmp_path)
    prepared = _prepare_graceful_retirement(context)
    fail_once = _FailOnceRuntime(context.runtime)
    packages = PluginPackageLifecycleLedger(
        tmp_path / "package-fail.jsonl",
        startup_id="startup-fail",
        desired_state=context.desired,
        instance_runtime=fail_once,
        retirement_sets=context.sets,
    )
    release = _family_release(prepared.owner_family, suffix="owner-fail")

    with pytest.raises(RuntimeError, match="injected release failure"):
        packages.handoff_cleanup_and_release(
            prepared.owner_family.family_id,
            retirement_target_id=prepared.target.target_id,
            cleanup_kind="owner.shutdown",
            operation_id="cleanup-owner-fail",
            idempotency_key="cleanup-owner-fail-request",
            cleanup_reference="cleanup:owner-fail",
            family_release=release,
        )

    task = packages.snapshot().cleanup_tasks[0]
    assert task.lease_open
    assert (
        context.runtime.snapshot().family(prepared.owner_family.family_id) is not None
    )
    assert (
        packages.handoff_cleanup_and_release(
            prepared.owner_family.family_id,
            retirement_target_id=prepared.target.target_id,
            cleanup_kind="owner.shutdown",
            operation_id="cleanup-owner-fail",
            idempotency_key="cleanup-owner-fail-request",
            cleanup_reference="cleanup:owner-fail",
            family_release=release,
        ).cleanup_id
        == task.task.cleanup_id
    )
    assert context.runtime.snapshot().family(prepared.owner_family.family_id) is None


def test_graceful_cleanup_rejects_a_different_owner_generation(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    prepared = _prepare_graceful_retirement(
        context,
        target_generation="generation:other",
    )

    with pytest.raises(PluginPackageLifecycleError) as caught:
        _handoff_owner(context, prepared)
    assert caught.value.code == "invalid_plugin_package_lifecycle_transition"
    assert context.packages.snapshot().journal_revision == 0
    assert (
        context.runtime.snapshot().family(prepared.owner_family.family_id) is not None
    )


def test_cleanup_retry_terminal_repair_and_safe_abandon(tmp_path: Path) -> None:
    context = _context(tmp_path)
    prepared = _prepare_graceful_retirement(context)
    owner_task = _handoff_owner(context, prepared)
    host_task = context.packages.handoff_cleanup_and_release(
        prepared.direct_family.family_id,
        retirement_target_id=None,
        cleanup_kind="host.shutdown",
        operation_id="cleanup-host",
        idempotency_key="cleanup-host-request",
        cleanup_reference="cleanup:host",
        family_release=_family_release(prepared.direct_family, suffix="host"),
    )

    assert (
        context.packages.record_cleanup_attempt(
            _attempt(owner_task, 1, "retryable_failure", suffix="owner-retry")
        ).state
        == "retryable_failure"
    )
    assert (
        context.packages.record_cleanup_attempt(
            _attempt(owner_task, 2, "terminal_failure", suffix="owner-terminal")
        ).state
        == "terminal_failure"
    )
    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.record_cleanup_attempt(
            _attempt(owner_task, 3, "succeeded", suffix="owner-too-early")
        )
    assert caught.value.code == "invalid_plugin_package_lifecycle_transition"

    retry = PluginCleanupRepairDecisionV1.create(
        cleanup_id=owner_task.cleanup_id,
        repair_sequence=1,
        action="retry",
        operation_id="repair-owner",
        idempotency_key="repair-owner-request",
        authority_reference="operator:owner",
        reason_code="repair.approved",
    )
    assert context.packages.record_repair_decision(retry).state == "retry_permitted"
    assert (
        context.packages.record_cleanup_attempt(
            _attempt(owner_task, 3, "succeeded", suffix="owner-success")
        ).state
        == "succeeded"
    )

    assert (
        context.packages.record_cleanup_attempt(
            _attempt(host_task, 1, "terminal_failure", suffix="host-terminal")
        ).state
        == "terminal_failure"
    )
    operator_row = PluginPackageGcReadModel(context.packages).snapshot().packages[0]
    assert "terminal_cleanup_failure" in operator_row.blocker_codes
    assert operator_row.candidate is None
    host_status = next(
        item
        for item in operator_row.to_dict()["cleanupTasks"]
        if item["cleanupId"] == host_task.cleanup_id
    )
    assert host_status["state"] == "terminal_failure"
    assert host_status["lastResultCode"] == "cleanup.host-terminal"
    abandon = PluginCleanupRepairDecisionV1.create(
        cleanup_id=host_task.cleanup_id,
        repair_sequence=1,
        action="safe_abandon",
        operation_id="repair-host",
        idempotency_key="repair-host-request",
        authority_reference="operator:host",
        reason_code="effect.acknowledged",
    )
    abandoned = context.packages.record_repair_decision(abandon)
    assert abandoned.state == "safe_abandoned"
    assert not abandoned.lease_open
    operator_row = PluginPackageGcReadModel(context.packages).snapshot().packages[0]
    assert "terminal_cleanup_failure" not in operator_row.blocker_codes
    assert "cleanup_lease" not in operator_row.blocker_codes
    assert any(
        item["state"] == "safe_abandoned" and item["lastRepairAction"] == "safe_abandon"
        for item in operator_row.to_dict()["cleanupTasks"]
    )


def test_gc_candidate_requires_every_source_zero_and_revision_recheck(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    prepared = _prepare_graceful_retirement(context)
    owner_task = _handoff_owner(context, prepared)
    host_task = context.packages.handoff_cleanup_and_release(
        prepared.direct_family.family_id,
        retirement_target_id=None,
        cleanup_kind="host.shutdown",
        operation_id="cleanup-host",
        idempotency_key="cleanup-host-request",
        cleanup_reference="cleanup:host",
        family_release=_family_release(prepared.direct_family, suffix="host"),
    )
    before = context.packages.snapshot().package(prepared.active.package_revision)
    assert before is not None
    assert before.nonretired_instances == (prepared.active.instance_revision_ref,)
    assert set(before.open_cleanup_ids) == {
        owner_task.cleanup_id,
        host_task.cleanup_id,
    }

    context.sets.record_outcome(
        PluginOwnerRetirementOutcomeV1(
            retirement_id=prepared.intent.retirement_id,
            target_id=prepared.target.target_id,
            operation_id="retire-owner",
            idempotency_key="retire-owner-request",
            attempt=1,
            disposition="succeeded",
            result_code="owner.retired",
            owner_outcome_reference="outcome:owner",
        )
    )
    completion = PluginInstanceRetirementCompletionV1.create(
        completion_kind="graceful",
        coordination_id=prepared.intent.retirement_id,
        installation_key=prepared.active.installation_key,
        instance_revision_ref=prepared.active.instance_revision_ref,
        operation_id="complete-instance",
        idempotency_key="complete-instance-request",
        completion_reference="completion:instance",
    )
    assert context.runtime.complete_retirement(completion).state == "RETIRED"
    context.packages.record_cleanup_attempt(
        _attempt(owner_task, 1, "succeeded", suffix="owner-success")
    )
    context.packages.record_cleanup_attempt(
        _attempt(host_task, 1, "succeeded", suffix="host-success")
    )

    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.gc_candidates()
    assert caught.value.code == "plugin_package_recovery_incomplete"
    operator = PluginPackageGcReadModel(context.packages)
    before_recovery = operator.snapshot()
    assert not before_recovery.recovery_complete
    assert before_recovery.packages[0].blocker_codes == ("startup_recovery",)
    context.packages.complete_startup_recovery(
        operation_id="recover-a",
        idempotency_key="recover-request-a",
        recovery_reference="recovery:a",
    )
    candidate = context.packages.gc_candidates()[0]
    assert context.packages.recheck_gc_candidate(candidate) == candidate
    ready = operator.snapshot()
    assert ready.packages[0].candidate == candidate
    assert ready.packages[0].blocker_codes == ()
    assert ready.to_dict()["packages"][0]["candidate"]["candidateId"] == (
        candidate.candidate_id
    )

    pin = context.packages.acquire_pin(
        prepared.active.package_revision,
        pin_kind="dependency_lock",
        operation_id="pin-late",
        idempotency_key="pin-late-request",
        holder_reference="dependency:late",
    )
    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.recheck_gc_candidate(candidate)
    assert caught.value.code == "invalid_plugin_package_lifecycle_transition"
    pinned = operator.snapshot().packages[0]
    assert pinned.candidate is None
    assert pinned.blocker_codes == ("retention_pin",)
    context.packages.release_pin(_pin_release(pin, suffix="late"))
    replacement = context.packages.gc_candidates()[0]
    assert replacement.package_revision == candidate.package_revision
    assert replacement.package_journal_revision > candidate.package_journal_revision
    assert replacement.candidate_id != candidate.candidate_id


def test_gc_reservation_fences_new_references_and_survives_restart(
    tmp_path: Path,
) -> None:
    journal = PluginPackageGcReservationJournal(tmp_path / "gc-reservations.jsonl")
    context = _context(tmp_path, gc_gate=journal)
    key = _key("plugin.a")
    context.service.submit(_command(key, "install", revision=0, operation=1))
    context.service.submit(_command(key, "remove", revision=1, operation=2))
    context.packages.complete_startup_recovery(
        operation_id="recover-gc",
        idempotency_key="recover-gc-request",
        recovery_reference="recovery:gc",
    )
    candidate = context.packages.gc_candidates()[0]
    reservation = journal.reserve(
        candidate,
        lifecycle=context.packages,
        operation_id="reserve-gc",
        idempotency_key="reserve-gc-request",
    )
    assert (
        journal.reserve(
            candidate,
            lifecycle=context.packages,
            operation_id="reserve-gc",
            idempotency_key="reserve-gc-request",
        )
        == reservation
    )
    with pytest.raises(PluginPackageGcReservationError) as competing:
        journal.reserve(
            candidate,
            lifecycle=context.packages,
            operation_id="reserve-competing",
            idempotency_key="reserve-competing-request",
        )
    assert competing.value.code == "plugin_package_gc_conflict"

    with pytest.raises(PluginPackageLifecycleError) as pin_error:
        context.packages.acquire_pin(
            candidate.package_revision,
            pin_kind="forensic_retention",
            operation_id="pin-during-gc",
            idempotency_key="pin-during-gc-request",
            holder_reference="forensic:gc",
        )
    assert pin_error.value.code == "plugin_package_gc_reserved"
    with pytest.raises(PluginLifecycleError) as install_error:
        context.desired.commit(_mutation(key, "install", revision=2, operation=3))
    assert install_error.value.code == "plugin_package_gc_reserved"
    with pytest.raises(PluginLifecycleError) as service_error:
        context.service.submit(_command(key, "install", revision=2, operation=4))
    assert service_error.value.code == "plugin_package_gc_reserved"

    # A legacy writer without the injected gate can still select the revision.
    # The bound runtime refuses to turn that stale selection into a new Instance.
    legacy_writer = PluginDesiredStateLedger(context.desired.path)
    legacy_writer.commit(_mutation(key, "install", revision=2, operation=5))
    legacy_writer.commit(_mutation(key, "enable", revision=3, operation=6))
    with pytest.raises(
        PluginInstanceRuntimeError, match="reserved for GC"
    ) as runtime_error:
        context.runtime.activate_current(
            key,
            operation_id="activate-during-gc",
            idempotency_key="activate-during-gc-request",
            direct_host_reference="host:gc",
        )
    assert runtime_error.value.code == "plugin_package_gc_reserved"

    with journal.path.open("ab") as handle:
        handle.write(b'{"eventVersion":')
    reopened = PluginPackageGcReservationJournal(journal.path)
    assert reopened.snapshot().active == (reservation,)
    restarted = _context(tmp_path, startup_id="startup-reopened", gc_gate=reopened)
    with pytest.raises(PluginPackageLifecycleError) as restarted_error:
        restarted.packages.acquire_pin(
            candidate.package_revision,
            pin_kind="dependency_lock",
            operation_id="pin-after-restart",
            idempotency_key="pin-after-restart-request",
            holder_reference="dependency:gc",
        )
    assert restarted_error.value.code == "plugin_package_gc_reserved"
    cancelled = reopened.cancel(
        reservation.reservation_id,
        operation_id="cancel-gc",
        idempotency_key="cancel-gc-request",
        reason_code="operator.cancelled",
    )
    assert (
        reopened.cancel(
            reservation.reservation_id,
            operation_id="cancel-gc",
            idempotency_key="cancel-gc-request",
            reason_code="operator.cancelled",
        )
        == cancelled
    )
    assert reopened.snapshot().active == ()
    restarted.packages.acquire_pin(
        candidate.package_revision,
        pin_kind="dependency_lock",
        operation_id="pin-after-cancel",
        idempotency_key="pin-after-cancel-request",
        holder_reference="dependency:gc",
    )
    with pytest.raises(PluginPackageLifecycleError):
        reopened.reserve(
            candidate,
            lifecycle=restarted.packages,
            operation_id="reserve-stale",
            idempotency_key="reserve-stale-request",
        )


def test_gc_reservation_refuses_unbound_graph(tmp_path: Path) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    context.service.submit(_command(key, "install", revision=0, operation=1))
    context.service.submit(_command(key, "remove", revision=1, operation=2))
    context.packages.complete_startup_recovery(
        operation_id="recover-gc",
        idempotency_key="recover-gc-request",
        recovery_reference="recovery:gc",
    )
    journal = PluginPackageGcReservationJournal(tmp_path / "gc-reservations.jsonl")
    with pytest.raises(PluginPackageGcReservationError) as caught:
        journal.reserve(
            context.packages.gc_candidates()[0],
            lifecycle=context.packages,
            operation_id="reserve-unbound",
            idempotency_key="reserve-unbound-request",
        )
    assert caught.value.code == "plugin_package_gc_graph_unbound"
    assert not journal.path.exists()


def test_gc_reservation_corruption_fails_closed_for_bound_writers(
    tmp_path: Path,
) -> None:
    journal = PluginPackageGcReservationJournal(tmp_path / "gc-reservations.jsonl")
    context = _context(tmp_path, gc_gate=journal)
    journal.path.write_bytes(b"{}\n")
    key = _key("plugin.a")
    with pytest.raises(PluginPackageGcReservationError) as desired_error:
        context.desired.commit(_mutation(key, "install", revision=0, operation=1))
    with pytest.raises(PluginPackageGcReservationError) as pin_error:
        context.packages.acquire_pin(
            _package(key.plugin_id, "a"),
            pin_kind="dependency_lock",
            operation_id="pin-corrupt",
            idempotency_key="pin-corrupt-request",
            holder_reference="dependency:corrupt",
        )
    assert desired_error.value.code == "plugin_package_gc_journal_corrupt"
    assert pin_error.value.code == "plugin_package_gc_journal_corrupt"
    assert context.desired.snapshot().inventory_revision == 0
    assert context.packages.snapshot().journal_revision == 0


def test_security_cleanup_uses_revocation_without_graceful_target(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key)
    active = _activate(context, key)
    owner = context.runtime.acquire_current_family(
        (key,),
        lease_kind="owner_generation",
        operation_id="owner-family",
        idempotency_key="owner-family-request",
        holder_reference="generation:a",
    )
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="revoke-a",
        idempotency_key="revoke-request-a",
        authority_reference="security:a",
        reason_code="digest.compromised",
    )
    context.runtime.begin_revoke(revocation)

    task = context.packages.handoff_cleanup_and_release(
        owner.family_id,
        retirement_target_id=None,
        cleanup_kind="owner.security_shutdown",
        operation_id="cleanup-security",
        idempotency_key="cleanup-security-request",
        cleanup_reference="cleanup:security",
        family_release=_family_release(owner, suffix="security"),
    )
    assert task.coordination_kind == "security"
    assert task.coordination_id == revocation.revocation_id
    assert task.retirement_target_id is None


def test_shared_package_waits_for_every_desired_and_runtime_reference(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    first_key = _key("plugin.a")
    second_key = replace(first_key, scope_id="workspace-2")
    context.service.submit(_command(first_key, "install", revision=0, operation=1))
    context.service.submit(_command(first_key, "enable", revision=1, operation=2))
    first = context.runtime.activate_current(
        first_key,
        operation_id="activate-first",
        idempotency_key="activate-first-request",
        direct_host_reference="host:first",
    )
    context.service.submit(_command(second_key, "install", revision=2, operation=3))
    context.service.submit(_command(second_key, "enable", revision=3, operation=4))
    second = context.runtime.activate_current(
        second_key,
        operation_id="activate-second",
        idempotency_key="activate-second-request",
        direct_host_reference="host:second",
    )
    context.packages.complete_startup_recovery(
        operation_id="recover-shared",
        idempotency_key="recover-shared-request",
        recovery_reference="recovery:shared",
    )

    retained = context.packages.snapshot().package(first.package_revision)
    assert retained is not None
    assert retained.desired_installations == (first_key, second_key)
    assert set(retained.nonretired_instances) == {
        first.instance_revision_ref,
        second.instance_revision_ref,
    }
    assert retained.gc_candidate is None

    _retire_without_cleanup(
        context,
        first,
        expected_inventory_revision=4,
        management_operation=5,
        suffix="first",
    )
    retained = context.packages.snapshot().package(first.package_revision)
    assert retained is not None
    assert retained.desired_installations == (second_key,)
    assert retained.nonretired_instances == (second.instance_revision_ref,)
    assert retained.gc_candidate is None

    _retire_without_cleanup(
        context,
        second,
        expected_inventory_revision=5,
        management_operation=6,
        suffix="second",
    )
    candidate = context.packages.gc_candidates()[0]
    assert candidate.package_revision == first.package_revision


def test_package_journal_repairs_tail_and_source_loss_fails_closed(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    prepared = _prepare_graceful_retirement(context)
    _handoff_owner(context, prepared)
    committed = context.packages.path.read_bytes()

    with context.packages.path.open("ab") as handle:
        handle.write(b'{"recordVersion":')
    assert context.packages.snapshot().journal_revision == 1
    assert context.packages.path.read_bytes() == committed

    desired_bytes = context.desired.path.read_bytes()
    context.desired.path.write_text("", encoding="utf-8")
    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.snapshot()
    assert caught.value.code == "plugin_package_lifecycle_journal_corrupt"
    context.desired.path.write_bytes(desired_bytes)

    runtime_bytes = context.runtime.path.read_bytes()
    context.runtime.path.write_text("", encoding="utf-8")
    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.snapshot()
    assert caught.value.code == "plugin_package_lifecycle_journal_corrupt"
    context.runtime.path.write_bytes(runtime_bytes)

    duplicate = json.loads(committed)
    duplicate["journalRevision"] = 2
    with context.packages.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(duplicate, sort_keys=True) + "\n")
    with pytest.raises(PluginPackageLifecycleError) as caught:
        context.packages.snapshot()
    assert caught.value.code == "plugin_package_lifecycle_journal_corrupt"


@dataclass(frozen=True, slots=True)
class _Context:
    desired: PluginDesiredStateLedger
    intents: PluginRetirementIntentLedger
    sets: PluginRetirementSetLedger
    service: PluginManagementService
    runtime: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger
    security_acceptances: PluginContinuitySecurityRetirementJournal


@dataclass(frozen=True, slots=True)
class _PreparedGraceful:
    active: PluginInstanceRuntimeSnapshotV1
    owner_family: PluginInstanceLeaseFamilyV1
    direct_family: PluginInstanceLeaseFamilyV1
    intent: PluginRetirementIntentV1
    target: PluginOwnerRetirementTargetV1


class _FailOnceRuntime:
    def __init__(self, runtime: PluginInstanceRuntimeLedger) -> None:
        self._runtime = runtime
        self._fail = True

    @property
    def path(self) -> Path:
        return self._runtime.path

    def snapshot(self):
        return self._runtime.snapshot()

    def events(self):
        return self._runtime.events()

    def release_family(self, release):
        if self._fail:
            self._fail = False
            raise RuntimeError("injected release failure")
        return self._runtime.release_family(release)


def _context(
    tmp_path: Path,
    *,
    startup_id: str = "startup-1",
    gc_gate: PluginPackageGcReservationJournal | None = None,
) -> _Context:
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=_instance_id_factory(),
        gc_gate=gc_gate,
    )
    intents = PluginRetirementIntentLedger(tmp_path / "intents.jsonl")
    sets = PluginRetirementSetLedger(
        tmp_path / "sets.jsonl",
        retirement_intents=intents,
    )
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    runtime_path = tmp_path / "instance-runtime.jsonl"
    security_acceptances = (
        PluginContinuitySecurityRetirementJournal.for_instance_runtime(runtime_path)
    )
    runtime = PluginInstanceRuntimeLedger(
        runtime_path,
        management_operation_journal_path=operation_path,
        desired_state=desired,
        retirement_intents=intents,
        retirement_sets=sets,
        security_acceptances=security_acceptances,
        gc_gate=gc_gate,
    )
    packages = PluginPackageLifecycleLedger(
        tmp_path / "packages.jsonl",
        startup_id=startup_id,
        desired_state=desired,
        instance_runtime=runtime,
        retirement_sets=sets,
        gc_gate=gc_gate,
    )
    return _Context(
        desired,
        intents,
        sets,
        service,
        runtime,
        packages,
        security_acceptances,
    )


def _package_ledger(
    context: _Context,
    *,
    startup_id: str,
) -> PluginPackageLifecycleLedger:
    return PluginPackageLifecycleLedger(
        context.packages.path,
        startup_id=startup_id,
        desired_state=context.desired,
        instance_runtime=context.runtime,
        retirement_sets=context.sets,
    )


def _prepare_graceful_retirement(
    context: _Context,
    *,
    target_generation: str = "generation:a",
) -> _PreparedGraceful:
    key = _key("plugin.a")
    _install_enable(context, key)
    active = _activate(context, key)
    owner = context.runtime.acquire_current_family(
        (key,),
        lease_kind="owner_generation",
        operation_id="owner-family",
        idempotency_key="owner-family-request",
        holder_reference="generation:a",
    )
    context.service.submit(_command(key, "remove", revision=2, operation=3))
    intent = context.intents.snapshot().intents[0]
    context.runtime.begin_drain(intent)
    target = PluginOwnerRetirementTargetV1.create(
        owner_reference="owner:a",
        owner_generation_reference=target_generation,
        retirement_handle="retire:a",
        contribution_ids=("tool:a",),
    )
    context.sets.commit_plan(
        PluginOwnerRetirementPlanV1.create(
            retirement_id=intent.retirement_id,
            owner_closure_reference="closure:a",
            targets=(target,),
        )
    )
    return _PreparedGraceful(
        active=active,
        owner_family=owner,
        direct_family=active.activation.direct_host_family,
        intent=intent,
        target=target,
    )


def _handoff_owner(
    context: _Context,
    prepared: _PreparedGraceful,
) -> PluginCleanupTaskV1:
    return context.packages.handoff_cleanup_and_release(
        prepared.owner_family.family_id,
        retirement_target_id=prepared.target.target_id,
        cleanup_kind="owner.shutdown",
        operation_id="cleanup-owner",
        idempotency_key="cleanup-owner-request",
        cleanup_reference="cleanup:owner",
        family_release=_family_release(prepared.owner_family, suffix="owner"),
    )


def _retire_without_cleanup(
    context: _Context,
    active: PluginInstanceRuntimeSnapshotV1,
    *,
    expected_inventory_revision: int,
    management_operation: int,
    suffix: str,
) -> None:
    context.service.submit(
        _command(
            active.installation_key,
            "remove",
            revision=expected_inventory_revision,
            operation=management_operation,
        )
    )
    intent = next(
        item
        for item in context.intents.snapshot().intents
        if item.instance_revision_ref == active.instance_revision_ref
    )
    context.runtime.begin_drain(intent)
    context.sets.commit_plan(
        PluginOwnerRetirementPlanV1.create(
            retirement_id=intent.retirement_id,
            owner_closure_reference=f"closure:{suffix}",
            targets=(),
        )
    )
    context.runtime.release_family(
        _family_release(active.activation.direct_host_family, suffix=suffix)
    )
    completion = PluginInstanceRetirementCompletionV1.create(
        completion_kind="graceful",
        coordination_id=intent.retirement_id,
        installation_key=active.installation_key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id=f"complete-{suffix}",
        idempotency_key=f"complete-{suffix}-request",
        completion_reference=f"completion:{suffix}",
    )
    assert context.runtime.complete_retirement(completion).state == "RETIRED"


def _instance_id_factory() -> Callable[[], str]:
    issued = 0

    def issue() -> str:
        nonlocal issued
        issued += 1
        return f"instance-{issued}"

    return issue


def _install_enable(context: _Context, key: PluginInstallationKeyV1) -> None:
    context.service.submit(_command(key, "install", revision=0, operation=1))
    context.service.submit(_command(key, "enable", revision=1, operation=2))


def _activate(
    context: _Context,
    key: PluginInstallationKeyV1,
) -> PluginInstanceRuntimeSnapshotV1:
    return context.runtime.activate_current(
        key,
        operation_id="activate-a",
        idempotency_key="activate-request-a",
        direct_host_reference="host:a",
    )


def _family_release(
    family: PluginInstanceLeaseFamilyV1,
    *,
    suffix: str,
) -> PluginInstanceLeaseFamilyReleaseV1:
    return PluginInstanceLeaseFamilyReleaseV1(
        family_id=family.family_id,
        operation_id=f"release-{suffix}",
        idempotency_key=f"release-{suffix}-request",
        release_reference=f"released:{suffix}",
    )


def _pin_release(
    pin: PluginPackagePinV1,
    *,
    suffix: str,
) -> PluginPackagePinReleaseV1:
    return PluginPackagePinReleaseV1(
        pin_id=pin.pin_id,
        operation_id=f"release-pin-{suffix}",
        idempotency_key=f"release-pin-{suffix}-request",
        release_reference=f"released:pin:{suffix}",
    )


def _attempt(
    task: PluginCleanupTaskV1,
    attempt: int,
    disposition: PluginCleanupDisposition,
    *,
    suffix: str,
) -> PluginCleanupAttemptV1:
    return PluginCleanupAttemptV1(
        cleanup_id=task.cleanup_id,
        operation_id=f"attempt-{suffix}",
        idempotency_key=f"attempt-{suffix}-request",
        attempt=attempt,
        disposition=disposition,
        result_code=f"cleanup.{suffix}",
        retry_not_before_epoch_ms=(
            1000 if disposition == "retryable_failure" else None
        ),
        outcome_reference=f"outcome:{suffix}",
    )


def _key(plugin_id: str) -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id=plugin_id,
    )


def _package(plugin_id: str, digest_character: str) -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        package_content_digest=digest_character * 64,
        dependency_lock_digest="f" * 64,
        package_source_identity=f"embedded:{plugin_id}",
    )


def _mutation(
    key: PluginInstallationKeyV1,
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
        operation_id=f"management-{operation}",
        idempotency_key=f"management-request-{operation}",
        expected_inventory_revision=revision,
        installation_key=key,
        desired_state=desired_states[action],
        package_revision=_package(key.plugin_id, "a") if action == "install" else None,
        actor_id="operator-1",
        policy_revision="policy-1",
    )


def _command(
    key: PluginInstallationKeyV1,
    action: PluginManagementAction,
    *,
    revision: int,
    operation: int,
) -> PluginManagementCommandV1:
    return PluginManagementCommandV1(
        action=action,
        mutation=_mutation(
            key,
            action,
            revision=revision,
            operation=operation,
        ),
    )
