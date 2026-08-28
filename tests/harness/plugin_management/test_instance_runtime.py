from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import Literal

import pytest

from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginSecurityRetirementEvidence,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
    PluginInstanceLedgerContinuitySecurityRetirementAuthority,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceActivationV1,
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceLeaseMemberV1,
    PluginInstanceRetirementCompletionV1,
    PluginInstanceRevocationV1,
    PluginInstanceRuntimeEventV1,
    PluginInstanceRuntimeRecordCodecError,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeError,
    PluginInstanceRuntimeLedger,
    PluginInstanceRuntimeSnapshotV1,
)
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
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginOwnerRetirementPlanV1,
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_instance_runtime_records_are_strict_derived_and_round_trip() -> None:
    key = _key("plugin.a")
    instance = PluginInstanceRevisionRef(
        instance_id="instance-a",
        plugin_id="plugin.a",
        revision=1,
    )
    package = _package("plugin.a", "a")
    activation = PluginInstanceActivationV1.create(
        installation_key=key,
        instance_revision_ref=instance,
        package_revision=package,
        source_inventory_revision=2,
        operation_id="activate-a",
        idempotency_key="activate-request-a",
        direct_host_reference="host:a",
    )
    member = activation.direct_host_family.members[0]
    release = _release(activation.direct_host_family, sequence="host")
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=instance,
        operation_id="revoke-a",
        idempotency_key="revoke-request-a",
        authority_reference="security:a",
        reason_code="source_revoked",
    )
    completion = PluginInstanceRetirementCompletionV1.create(
        completion_kind="security",
        coordination_id=revocation.revocation_id,
        installation_key=key,
        instance_revision_ref=instance,
        operation_id="complete-a",
        idempotency_key="complete-request-a",
        completion_reference="completion:a",
    )
    event = PluginInstanceRuntimeEventV1.activated(
        journal_revision=1,
        activation=activation,
    )

    for record_type, value in (
        (PluginInstanceLeaseMemberV1, member),
        (PluginInstanceLeaseFamilyV1, activation.direct_host_family),
        (PluginInstanceActivationV1, activation),
        (PluginInstanceLeaseFamilyReleaseV1, release),
        (PluginInstanceRevocationV1, revocation),
        (PluginInstanceRetirementCompletionV1, completion),
        (PluginInstanceRuntimeEventV1, event),
    ):
        assert record_type.from_dict(value.to_dict()) == value
        with pytest.raises(PluginInstanceRuntimeRecordCodecError) as caught:
            record_type.from_dict({**value.to_dict(), "unknown": True})
        assert caught.value.code == "invalid_plugin_instance_runtime_record"

    unsupported = event.to_dict()
    unsupported["recordVersion"] = 2
    with pytest.raises(PluginInstanceRuntimeRecordCodecError) as caught:
        PluginInstanceRuntimeEventV1.from_dict(unsupported)
    assert caught.value.code == "unsupported_plugin_instance_runtime_record_version"

    with pytest.raises(ValueError, match="does not match"):
        replace(member, lease_id="0" * 64)
    with pytest.raises(ValueError, match="must be a positive integer"):
        replace(activation.direct_host_family, source_inventory_revision=0)
    with pytest.raises(ValueError, match="not structural"):
        replace(revocation, reason_code="Source revoked!")


def test_continuity_security_retirement_adapter_durably_accepts_before_revoking(
    tmp_path: Path,
) -> None:
    asyncio.run(_continuity_security_retirement_adapter_durably_accepts(tmp_path))


def test_continuity_security_acceptance_source_is_sealed_by_durable_identity(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias_root = tmp_path / "alias"
    alias_root.symlink_to(real_root, target_is_directory=True)
    context = _context(real_root)
    path = context.security_acceptances.path
    alias = PluginContinuitySecurityRetirementJournal.for_instance_runtime(
        alias_root / "instance-runtime.jsonl"
    )
    assert alias.path == path
    restarted_through_alias = PluginInstanceRuntimeLedger(
        alias_root / "instance-runtime.jsonl",
        management_operation_journal_path=alias_root / "operations.jsonl",
        desired_state=context.desired,
        retirement_intents=context.intents,
        retirement_sets=context.sets,
        security_acceptances=alias,
    )
    assert restarted_through_alias.path == context.runtime.path
    assert (
        restarted_through_alias.management_operation_journal_path
        == context.runtime.management_operation_journal_path
    )

    context.runtime.bind_security_acceptance_source(alias)
    context.runtime.bind_security_acceptance_source(
        PluginContinuitySecurityRetirementJournal(path)
    )
    with pytest.raises(ValueError, match="canonical path"):
        context.runtime.bind_security_acceptance_source(
            PluginContinuitySecurityRetirementJournal(
                tmp_path / "other-security-acceptance.jsonl"
            )
        )


def test_instance_runtime_restart_cannot_omit_or_replace_security_identity(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    with pytest.raises(TypeError, match="security_acceptances"):
        PluginInstanceRuntimeLedger(  # type: ignore[call-arg]
            context.runtime.path,
            management_operation_journal_path=(
                context.runtime.management_operation_journal_path
            ),
            desired_state=context.desired,
            retirement_intents=context.intents,
            retirement_sets=context.sets,
        )
    with pytest.raises(ValueError, match="canonical path"):
        PluginInstanceRuntimeLedger(
            context.runtime.path,
            management_operation_journal_path=(
                context.runtime.management_operation_journal_path
            ),
            desired_state=context.desired,
            retirement_intents=context.intents,
            retirement_sets=context.sets,
            security_acceptances=PluginContinuitySecurityRetirementJournal(
                tmp_path / "replacement-security-acceptances.jsonl"
            ),
        )


def test_continuity_security_acceptance_linearizes_before_new_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _continuity_security_acceptance_linearizes_before_new_acquisition(
            tmp_path,
            monkeypatch,
        )
    )


def test_continuity_security_aliases_share_one_cross_process_lock_identity(
    tmp_path: Path,
) -> None:
    asyncio.run(_continuity_security_aliases_share_one_lock_identity(tmp_path))


async def _continuity_security_aliases_share_one_lock_identity(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias_root = tmp_path / "alias"
    alias_root.symlink_to(real_root, target_is_directory=True)
    context = _context(real_root)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    active = _activate(context, key, "continuity-alias")
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="continuity-alias-revoke",
        idempotency_key="continuity-alias-revoke-request",
        authority_reference="security:continuity",
        reason_code="source_revoked",
    )
    alias_journal = PluginContinuitySecurityRetirementJournal.for_instance_runtime(
        alias_root / "instance-runtime.jsonl"
    )
    assert alias_journal.path == context.security_acceptances.path
    first = PluginInstanceLedgerContinuitySecurityRetirementAuthority(
        ledger=context.runtime,
        acceptance_journal=context.security_acceptances,
        revocations=(revocation,),
    )
    second = PluginInstanceLedgerContinuitySecurityRetirementAuthority(
        ledger=context.runtime,
        acceptance_journal=alias_journal,
        revocations=(revocation,),
    )

    first_evidence, second_evidence = await asyncio.gather(
        first.accept_revocation(),
        second.accept_revocation(),
    )

    assert first_evidence.evidence_fingerprint == second_evidence.evidence_fingerprint
    assert len(context.security_acceptances.records()) == 1


async def _continuity_security_acceptance_linearizes_before_new_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    active = _activate(context, key, "continuity-race")
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="continuity-race-revoke",
        idempotency_key="continuity-race-revoke-request",
        authority_reference="security:continuity",
        reason_code="source_revoked",
    )
    journal = context.security_acceptances
    authority = PluginInstanceLedgerContinuitySecurityRetirementAuthority(
        ledger=context.runtime,
        acceptance_journal=journal,
        revocations=(revocation,),
    )
    appended = Event()
    allow_accept_return = Event()
    original_accept = journal._accept

    def blocking_accept(revocations):  # type: ignore[no-untyped-def]
        record = original_accept(revocations)
        appended.set()
        assert allow_accept_return.wait(timeout=5)
        return record

    monkeypatch.setattr(journal, "_accept", blocking_accept)
    acceptance = asyncio.create_task(authority.accept_revocation())
    assert await asyncio.to_thread(appended.wait, 5)
    acquisition = asyncio.create_task(
        asyncio.to_thread(
            context.runtime.acquire_current_family,
            (key,),
            lease_kind="owner_generation",
            operation_id="continuity-racing-acquire",
            idempotency_key="continuity-racing-acquire-request",
            holder_reference="continuity:racing",
        )
    )
    await asyncio.sleep(0.05)
    assert not acquisition.done()

    allow_accept_return.set()
    assert (await acceptance).phase == "accepted"
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        await acquisition
    assert caught.value.code == "plugin_instance_acquisition_unavailable"


async def _continuity_security_retirement_adapter_durably_accepts(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    active = _activate(context, key, "continuity-security")
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="continuity-security-revoke",
        idempotency_key="continuity-security-revoke-request",
        authority_reference="security:continuity",
        reason_code="source_revoked",
    )
    journal = context.security_acceptances
    authority = PluginInstanceLedgerContinuitySecurityRetirementAuthority(
        ledger=context.runtime,
        acceptance_journal=journal,
        revocations=(revocation,),
    )

    acceptance = await authority.accept_revocation()
    assert isinstance(acceptance, ContinuityPluginSecurityRetirementEvidence)
    assert acceptance.phase == "accepted"
    assert journal.records()[0].revocations == (revocation,)
    assert context.runtime.snapshot().instance(active.instance_revision_ref).state == (
        "ACTIVE"
    )
    assert (await authority.accept_revocation()).evidence_fingerprint == (
        acceptance.evidence_fingerprint
    )

    # Simulate a crash after acceptance fsync but before the live publication
    # enters REVOKING.  The durable source bars acquisition immediately, and
    # startup reconciliation idempotently advances the Instance ledger.
    restarted = PluginInstanceRuntimeLedger(
        context.runtime.path,
        management_operation_journal_path=(
            context.runtime.management_operation_journal_path
        ),
        desired_state=context.desired,
        retirement_intents=context.intents,
        retirement_sets=context.sets,
        security_acceptances=journal,
    )
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        restarted.acquire_current_family(
            (key,),
            lease_kind="owner_generation",
            operation_id="continuity-after-acceptance",
            idempotency_key="continuity-after-acceptance-request",
            holder_reference="continuity:restarted",
        )
    assert caught.value.code == "plugin_instance_acquisition_unavailable"
    recovered = journal.reconcile(restarted)
    assert recovered[0].state == "REVOKING"

    evidence = await authority.enter_revoking(acceptance)
    assert evidence.phase == "revoking"
    retired = context.runtime.snapshot().instance(active.instance_revision_ref)
    assert retired is not None
    assert retired.state == "REVOKING"
    assert retired.revocation == revocation
    assert (await authority.enter_revoking(acceptance)).evidence_fingerprint == (
        evidence.evidence_fingerprint
    )


def test_activation_requires_current_enabled_selection_and_is_idempotent(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    context.service.submit(_command(key, "install", revision=0, operation=1))

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.activate_current(
            key,
            operation_id="activate-a",
            idempotency_key="activate-request-a",
            direct_host_reference="host:a",
        )
    assert caught.value.code == "plugin_instance_acquisition_unavailable"

    context.service.submit(_command(key, "enable", revision=1, operation=2))
    active = context.runtime.activate_current(
        key,
        operation_id="activate-a",
        idempotency_key="activate-request-a",
        direct_host_reference="host:a",
    )
    repeated = context.runtime.activate_current(
        key,
        operation_id="activate-a",
        idempotency_key="activate-request-a",
        direct_host_reference="host:a",
    )

    assert repeated == active
    assert active.state == "ACTIVE"
    assert active.open_lease_count == 1
    assert active.activation.direct_host_family.lease_kind == "direct_host"
    assert context.runtime.snapshot().journal_revision == 1

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.activate_current(
            key,
            operation_id="activate-a",
            idempotency_key="activate-request-a",
            direct_host_reference="host:changed",
        )
    assert caught.value.code == "plugin_instance_runtime_conflict"


def test_root_membership_acquisition_is_atomic_and_canonical(tmp_path: Path) -> None:
    context = _context(tmp_path)
    first = _key("plugin.a")
    second = _key("plugin.b")
    _install_enable(context, first, start_revision=0, start_operation=1)
    _install_enable(context, second, start_revision=2, start_operation=3)
    _activate(context, first, "a")
    _activate(context, second, "b")

    family = context.runtime.acquire_current_family(
        (second, first),
        lease_kind="session_membership",
        operation_id="session-family",
        idempotency_key="session-family-request",
        holder_reference="session:1",
    )

    assert tuple(member.installation_key for member in family.members) == (
        first,
        second,
    )
    assert family.source_inventory_revision == 4
    assert context.runtime.snapshot().journal_revision == 3

    before = context.runtime.path.read_bytes()
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.acquire_current_family(
            (first, _key("plugin.missing")),
            lease_kind="session_membership",
            operation_id="bad-family",
            idempotency_key="bad-family-request",
            holder_reference="session:bad",
        )
    assert caught.value.code == "plugin_instance_acquisition_unavailable"
    assert context.runtime.path.read_bytes() == before

    context.runtime.release_family(_release(family, sequence="session-two"))
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.acquire_current_family(
            (second, first),
            lease_kind="session_membership",
            operation_id="session-family",
            idempotency_key="session-family-request",
            holder_reference="session:1",
        )
    assert caught.value.code == "invalid_plugin_instance_runtime_transition"


def test_drain_allows_derived_agent_but_blocks_roots_and_early_retirement(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    active = _activate(context, key, "a")
    session = context.runtime.acquire_current_family(
        (key,),
        lease_kind="session_membership",
        operation_id="session-family",
        idempotency_key="session-family-request",
        holder_reference="session:1",
    )
    context.service.submit(_command(key, "disable", revision=2, operation=3))
    intent = context.intents.snapshot().intents[0]

    draining = context.runtime.begin_drain(intent)
    assert draining.state == "DRAINING"
    assert context.runtime.begin_drain(intent) == draining

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.acquire_current_family(
            (key,),
            lease_kind="independent",
            operation_id="late-root",
            idempotency_key="late-root-request",
            holder_reference="late:root",
        )
    assert caught.value.code == "plugin_instance_acquisition_unavailable"

    agent = context.runtime.derive_agent_membership(
        session.family_id,
        operation_id="agent-family",
        idempotency_key="agent-family-request",
        holder_reference="agent:1",
    )
    assert agent.parent_family_id == session.family_id

    context.sets.commit_plan(
        PluginOwnerRetirementPlanV1.create(
            retirement_id=intent.retirement_id,
            owner_closure_reference="closure:empty",
            targets=(),
        )
    )
    completion = _completion(
        active,
        coordination_id=intent.retirement_id,
        kind="graceful",
    )
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.complete_retirement(completion)
    assert caught.value.code == "invalid_plugin_instance_runtime_transition"

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.release_family(_release(session, sequence="session"))
    assert caught.value.code == "invalid_plugin_instance_runtime_transition"

    context.runtime.release_family(_release(agent, sequence="agent"))
    context.runtime.release_family(_release(session, sequence="session"))
    context.runtime.release_family(
        _release(active.activation.direct_host_family, sequence="host")
    )
    retired = context.runtime.complete_retirement(completion)

    assert retired.state == "RETIRED"
    assert retired.open_lease_count == 0
    assert context.runtime.complete_retirement(completion) == retired
    unexpected_revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="late-revoke",
        idempotency_key="late-revoke-request",
        authority_reference="security:late",
        reason_code="source_revoked",
    )
    with pytest.raises(ValueError, match="without revocation"):
        replace(retired, revocation=unexpected_revocation)


def test_retirement_intent_cannot_manufacture_activation(tmp_path: Path) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    context.service.submit(_command(key, "disable", revision=2, operation=3))
    intent = context.intents.snapshot().intents[0]

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.begin_drain(intent)
    assert caught.value.code == "invalid_plugin_instance_runtime_transition"
    assert context.runtime.snapshot().journal_revision == 0


def test_old_revision_must_drain_before_reenabled_revision_can_activate(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    old = _activate(context, key, "old")
    context.service.submit(_command(key, "disable", revision=2, operation=3))
    intent = context.intents.snapshot().intents[0]
    context.service.submit(_command(key, "enable", revision=3, operation=4))

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        _activate(context, key, "new")
    assert caught.value.code == "invalid_plugin_instance_runtime_transition"

    context.runtime.begin_drain(intent)
    new = _activate(context, key, "new")
    snapshot = context.runtime.snapshot()
    old_snapshot = snapshot.instance(old.instance_revision_ref)
    new_snapshot = snapshot.instance(new.instance_revision_ref)

    assert old.instance_revision_ref.revision == 1
    assert new.instance_revision_ref.revision == 2
    assert old_snapshot is not None
    assert old_snapshot.state == "DRAINING"
    assert new_snapshot is not None
    assert new_snapshot.state == "ACTIVE"


def test_security_revoke_rejects_every_new_family_and_retires_at_zero(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    active = _activate(context, key, "a")
    session = context.runtime.acquire_current_family(
        (key,),
        lease_kind="session_membership",
        operation_id="session-family",
        idempotency_key="session-family-request",
        holder_reference="session:1",
    )
    context.service.submit(_command(key, "disable", revision=2, operation=3))
    intent = context.intents.snapshot().intents[0]
    assert context.runtime.begin_drain(intent).state == "DRAINING"
    revocation = PluginInstanceRevocationV1.create(
        installation_key=key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="revoke-a",
        idempotency_key="revoke-request-a",
        authority_reference="security:a",
        reason_code="digest_compromised",
    )

    revoking = context.runtime.begin_revoke(revocation)
    assert revoking.state == "REVOKING"
    assert context.runtime.begin_revoke(revocation) == revoking

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.derive_agent_membership(
            session.family_id,
            operation_id="late-agent",
            idempotency_key="late-agent-request",
            holder_reference="agent:late",
        )
    assert caught.value.code == "invalid_plugin_instance_runtime_transition"

    context.runtime.release_family(_release(session, sequence="session"))
    context.runtime.release_family(
        _release(active.activation.direct_host_family, sequence="host")
    )
    completion = _completion(
        active,
        coordination_id=revocation.revocation_id,
        kind="security",
    )
    assert context.runtime.complete_retirement(completion).state == "RETIRED"


def test_runtime_journal_repairs_tail_and_rejects_complete_corruption(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    _activate(context, key, "a")
    committed = context.runtime.path.read_bytes()

    with context.runtime.path.open("ab") as handle:
        handle.write(b'{"recordVersion":')
    assert context.runtime.snapshot().journal_revision == 1
    assert context.runtime.path.read_bytes() == committed

    duplicate = json.loads(committed)
    duplicate["journalRevision"] = 2
    with context.runtime.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(duplicate, sort_keys=True) + "\n")
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.snapshot()
    assert caught.value.code == "plugin_instance_runtime_journal_corrupt"


def test_management_cutover_serializes_against_root_acquisition(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    _activate(context, key, "a")
    committed = Event()
    continue_handoff = Event()
    acquisition_started = Event()
    blocking_desired = _BlockAfterDisableCommit(
        context.desired,
        committed=committed,
        continue_handoff=continue_handoff,
    )
    blocking_service = PluginManagementService(
        desired_state=blocking_desired,
        operation_journal_path=context.service.operation_journal_path,
        retirement_intents=context.intents,
        retirement_sets=context.sets,
    )

    def acquire_after_cutover():
        acquisition_started.set()
        return context.runtime.acquire_current_family(
            (key,),
            lease_kind="independent",
            operation_id="racing-root",
            idempotency_key="racing-root-request",
            holder_reference="root:racing",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        disable = executor.submit(
            blocking_service.submit,
            _command(key, "disable", revision=2, operation=3),
        )
        assert committed.wait(timeout=5)
        acquisition = executor.submit(acquire_after_cutover)
        assert acquisition_started.wait(timeout=5)
        assert not acquisition.done()
        continue_handoff.set()
        assert disable.result(timeout=5).status == "terminal"
        with pytest.raises(PluginInstanceRuntimeError) as caught:
            acquisition.result(timeout=5)

    assert caught.value.code == "plugin_instance_acquisition_unavailable"
    assert context.runtime.snapshot().journal_revision == 1


@dataclass(frozen=True, slots=True)
class _Context:
    desired: PluginDesiredStateLedger
    intents: PluginRetirementIntentLedger
    sets: PluginRetirementSetLedger
    service: PluginManagementService
    runtime: PluginInstanceRuntimeLedger
    security_acceptances: PluginContinuitySecurityRetirementJournal


class _BlockAfterDisableCommit:
    def __init__(
        self,
        desired: PluginDesiredStateLedger,
        *,
        committed: Event,
        continue_handoff: Event,
    ) -> None:
        self._desired = desired
        self._committed = committed
        self._continue_handoff = continue_handoff

    @property
    def path(self) -> Path:
        return self._desired.path

    def commit(self, mutation):
        transition = self._desired.commit(mutation)
        if transition.transition_kind == "disable":
            self._committed.set()
            if not self._continue_handoff.wait(timeout=5):
                raise RuntimeError("test did not release management handoff")
        return transition

    def commit_update(self, mutation):
        return self._desired.commit_update(mutation)

    def snapshot(self):
        return self._desired.snapshot()

    def transitions(self):
        return self._desired.transitions()


def _context(tmp_path: Path) -> _Context:
    operation_path = tmp_path / "operations.jsonl"
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=_instance_id_factory(),
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
    )
    return _Context(
        desired=desired,
        intents=intents,
        sets=sets,
        service=service,
        runtime=runtime,
        security_acceptances=security_acceptances,
    )


def _instance_id_factory() -> Callable[[], str]:
    issued = 0

    def issue() -> str:
        nonlocal issued
        issued += 1
        return f"instance-{issued}"

    return issue


def _install_enable(
    context: _Context,
    key: PluginInstallationKeyV1,
    *,
    start_revision: int,
    start_operation: int,
) -> None:
    context.service.submit(
        _command(
            key,
            "install",
            revision=start_revision,
            operation=start_operation,
        )
    )
    context.service.submit(
        _command(
            key,
            "enable",
            revision=start_revision + 1,
            operation=start_operation + 1,
        )
    )


def _activate(
    context: _Context,
    key: PluginInstallationKeyV1,
    suffix: str,
) -> PluginInstanceRuntimeSnapshotV1:
    return context.runtime.activate_current(
        key,
        operation_id=f"activate-{suffix}",
        idempotency_key=f"activate-request-{suffix}",
        direct_host_reference=f"host:{suffix}",
    )


def _release(
    family: PluginInstanceLeaseFamilyV1,
    *,
    sequence: str,
) -> PluginInstanceLeaseFamilyReleaseV1:
    return PluginInstanceLeaseFamilyReleaseV1(
        family_id=family.family_id,
        operation_id=f"release-{sequence}",
        idempotency_key=f"release-request-{sequence}",
        release_reference=f"released:{sequence}",
    )


def _completion(
    active: PluginInstanceRuntimeSnapshotV1,
    *,
    coordination_id: str,
    kind: Literal["graceful", "security"],
) -> PluginInstanceRetirementCompletionV1:
    return PluginInstanceRetirementCompletionV1.create(
        completion_kind=kind,
        coordination_id=coordination_id,
        installation_key=active.installation_key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id=f"complete-{kind}",
        idempotency_key=f"complete-request-{kind}",
        completion_reference=f"completion:{kind}",
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
    digest_character = "a" if key.plugin_id == "plugin.a" else "b"
    return PluginDesiredStateMutationV1(
        operation_id=f"management-{operation}",
        idempotency_key=f"management-request-{operation}",
        expected_inventory_revision=revision,
        installation_key=key,
        desired_state=desired_states[action],
        package_revision=(
            _package(key.plugin_id, digest_character) if action == "install" else None
        ),
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


def test_runtime_fails_closed_when_desired_or_retirement_source_disappears(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    key = _key("plugin.a")
    _install_enable(context, key, start_revision=0, start_operation=1)
    active = _activate(context, key, "a")
    desired_bytes = context.desired.path.read_bytes()

    context.desired.path.write_text("", encoding="utf-8")
    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.snapshot()
    assert caught.value.code == "plugin_instance_runtime_journal_corrupt"

    context.desired.path.write_bytes(desired_bytes)
    context.service.submit(_command(key, "disable", revision=2, operation=3))
    intent = context.intents.snapshot().intents[0]
    context.runtime.begin_drain(intent)
    assert active.state == "ACTIVE"
    context.sets.path.write_text("", encoding="utf-8")

    with pytest.raises(PluginInstanceRuntimeError) as caught:
        context.runtime.snapshot()
    assert caught.value.code == "plugin_instance_runtime_journal_corrupt"
