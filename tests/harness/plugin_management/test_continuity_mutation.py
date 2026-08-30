from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace

import pytest

from loushang.harness.continuity.mutation import (
    ContinuityDeletionPlanV1,
    ContinuityDeletionReceiptV1,
    prepare_authorized_continuity_deletion,
)
from loushang.harness.continuity.types import (
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
)
from loushang.harness.journal import JournalCodecError
from loushang.harness.plugin_management.continuity_mutation import (
    PluginContinuityDeletionAuthority,
    PluginContinuityDeletionEventV1,
    PluginContinuityDeletionJournal,
    PluginContinuityDeletionJournalError,
    plugin_continuity_deletion_journal_path,
)


def test_durable_authority_records_exact_success_and_reloads(tmp_path) -> None:
    asyncio.run(_durable_authority_records_success(tmp_path))


async def _durable_authority_records_success(tmp_path) -> None:
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    authority = PluginContinuityDeletionAuthority(journal)
    events: list[str] = []
    candidate = _Candidate(_plan(), events)

    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )
    receipt = await lease.consume()

    assert receipt.disposition == "applied"
    assert events == ["commit", "close"]
    records = PluginContinuityDeletionJournal(journal.path).records()
    assert tuple(item.event_kind for item in records) == ("accepted", "completed")
    assert records[0].plan == _plan()
    assert records[0].source == _source()
    assert records[1].receipt == receipt
    assert await authority.pending_deletions() == ()


def test_startup_authority_recovers_accepted_operation_without_new_identity(
    tmp_path,
) -> None:
    asyncio.run(_startup_authority_recovers_accepted_operation(tmp_path))


async def _startup_authority_recovers_accepted_operation(tmp_path) -> None:
    path = tmp_path / "deletions.jsonl"
    accepted = PluginContinuityDeletionJournal(path).accept(_plan(), _source())

    recovered = PluginContinuityDeletionAuthority(PluginContinuityDeletionJournal(path))
    pending = await recovered.pending_deletions()
    assert len(pending) == 1
    assert pending[0].plan == _plan()
    assert pending[0].source == _source()

    lease = await prepare_authorized_continuity_deletion(
        _Candidate(_plan(), []),
        source=_source(),
        authority=recovered,
    )
    assert lease.authorization_id == accepted.authorization_id
    await lease.consume()
    assert await recovered.pending_deletions() == ()


def test_cancelled_authorization_reopens_as_new_attempt_and_old_evidence_is_stale(
    tmp_path,
) -> None:
    asyncio.run(_cancelled_authorization_reopens(tmp_path))


async def _cancelled_authorization_reopens(tmp_path) -> None:
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    first = await authority.authorize_delete(_plan(), _source())
    await authority.cancel_delete(first)
    second = await authority.authorize_delete(_plan(), _source())

    assert first.authorization_id != second.authorization_id
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "cancelled",
        "accepted",
    )
    with pytest.raises(PluginContinuityDeletionJournalError) as caught:
        await authority.cancel_delete(first)
    assert caught.value.code == "plugin_continuity_deletion_authorization_unknown"
    await authority.cancel_delete(second)


def test_concurrent_authorizations_serialize_until_terminal_transition(
    tmp_path,
) -> None:
    asyncio.run(_concurrent_authorizations_serialize_until_terminal(tmp_path))


async def _concurrent_authorizations_serialize_until_terminal(tmp_path) -> None:
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    first = await authority.authorize_delete(_plan(), _source())
    second_task = asyncio.create_task(authority.authorize_delete(_plan(), _source()))
    await asyncio.sleep(0.01)
    assert not second_task.done()

    await authority.cancel_delete(first)
    second = await second_task
    assert first.authorization_id != second.authorization_id
    await authority.cancel_delete(second)
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "cancelled",
        "accepted",
        "cancelled",
    )


def test_process_single_flight_is_shared_across_authority_instances(tmp_path) -> None:
    asyncio.run(_process_single_flight_is_shared_across_authorities(tmp_path))


async def _process_single_flight_is_shared_across_authorities(tmp_path) -> None:
    path = tmp_path / "deletions.jsonl"
    leader = PluginContinuityDeletionAuthority(PluginContinuityDeletionJournal(path))
    follower = PluginContinuityDeletionAuthority(PluginContinuityDeletionJournal(path))
    authorization = await leader.authorize_delete(_plan(), _source())
    follower_events: list[str] = []
    follower_lease = asyncio.create_task(
        prepare_authorized_continuity_deletion(
            _Candidate(_plan(), follower_events),
            source=_source(),
            authority=follower,
        )
    )
    await asyncio.sleep(0.01)
    assert not follower_lease.done()

    receipt = _receipt("applied")
    await leader.complete_delete(authorization, receipt)
    lease = await follower_lease

    assert await lease.consume() == receipt
    assert follower_events == ["abort", "close"]
    assert tuple(item.event_kind for item in leader.journal.records()) == (
        "accepted",
        "completed",
    )


def test_event_codec_and_journal_fail_closed(tmp_path) -> None:
    event = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl").accept(
        _plan(), _source()
    )
    raw = (
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
        .records()[0]
        .to_dict()
    )
    raw["extension"] = True
    with pytest.raises(JournalCodecError):
        PluginContinuityDeletionEventV1.from_dict(raw)

    path = tmp_path / "corrupt.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PluginContinuityDeletionJournalError) as caught:
        PluginContinuityDeletionJournal(path).records()
    assert caught.value.code == "plugin_continuity_deletion_journal_corrupt"
    assert event.state == "accepted"


def test_journal_reads_phase5e_source_without_recovery_fingerprint(tmp_path) -> None:
    path = tmp_path / "legacy-deletions.jsonl"
    legacy_source = replace(_source(), owner_recovery_fingerprint=None)
    accepted = PluginContinuityDeletionJournal(path).accept(_plan(), legacy_source)

    [wire_record] = path.read_text(encoding="utf-8").splitlines()
    assert "ownerRecoveryFingerprint" not in wire_record
    [reloaded] = PluginContinuityDeletionJournal(path).records()

    assert reloaded.authorization_id == accepted.authorization_id
    assert reloaded.source == legacy_source


@pytest.mark.parametrize("second_revision", (2, 3), ids=("transition", "revision-gap"))
def test_journal_rejects_duplicate_acceptance_and_revision_gap(
    tmp_path,
    second_revision: int,
) -> None:
    path = tmp_path / "deletions.jsonl"
    journal = PluginContinuityDeletionJournal(path)
    journal.accept(_plan(), _source())
    [accepted] = journal.records()
    forged = PluginContinuityDeletionEventV1(
        journal_revision=second_revision,
        event_kind="accepted",
        authorization_id=accepted.authorization_id,
        attempt=accepted.attempt,
        plan=accepted.plan,
        source=accepted.source,
    )
    path.write_text(
        "\n".join(
            json.dumps(
                item.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            for item in (accepted, forged)
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PluginContinuityDeletionJournalError) as caught:
        journal.records()
    assert caught.value.code == "plugin_continuity_deletion_journal_corrupt"


def test_journal_repairs_partial_tail_without_losing_accepted_intent(tmp_path) -> None:
    path = tmp_path / "deletions.jsonl"
    journal = PluginContinuityDeletionJournal(path)
    accepted = journal.accept(_plan(), _source())
    accepted_bytes = path.read_bytes()
    with path.open("ab") as stream:
        stream.write(b'{"attempt":')

    [record] = journal.records()
    assert record.authorization_id == accepted.authorization_id
    assert path.read_bytes() == accepted_bytes


def test_changed_completion_receipt_conflicts(tmp_path) -> None:
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    accepted = journal.accept(_plan(), _source())
    applied = _receipt("applied")
    journal.complete(accepted.authorization_id, applied)

    with pytest.raises(PluginContinuityDeletionJournalError) as caught:
        journal.complete(accepted.authorization_id, _receipt("not_found"))
    assert caught.value.code == "plugin_continuity_deletion_journal_conflict"
    assert journal.authorization(accepted.authorization_id).receipt == applied


def test_completed_deletion_cannot_be_cancelled(tmp_path) -> None:
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    accepted = journal.accept(_plan(), _source())
    journal.complete(accepted.authorization_id, _receipt("applied"))
    before = journal.records()

    with pytest.raises(PluginContinuityDeletionJournalError) as caught:
        journal.cancel(accepted.authorization_id)
    assert caught.value.code == "plugin_continuity_deletion_journal_conflict"
    assert journal.records() == before


def test_cancelled_deletion_cannot_be_completed(tmp_path) -> None:
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    accepted = journal.accept(_plan(), _source())
    journal.cancel(accepted.authorization_id)
    before = journal.records()

    with pytest.raises(PluginContinuityDeletionJournalError) as caught:
        journal.complete(accepted.authorization_id, _receipt("applied"))
    assert caught.value.code == "plugin_continuity_deletion_journal_conflict"
    assert journal.records() == before


def test_concurrent_terminal_transitions_leave_one_exact_result(tmp_path) -> None:
    asyncio.run(_concurrent_terminal_transitions_leave_one_result(tmp_path))


async def _concurrent_terminal_transitions_leave_one_result(tmp_path) -> None:
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    authorization = await authority.authorize_delete(_plan(), _source())
    results = await asyncio.gather(
        authority.complete_delete(authorization, _receipt("applied")),
        authority.cancel_delete(authorization),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1
    assert isinstance(errors[0], PluginContinuityDeletionJournalError)
    records = authority.journal.records()
    assert tuple(item.event_kind for item in records) in {
        ("accepted", "completed"),
        ("accepted", "cancelled"),
    }


def test_instance_runtime_path_factory_is_canonical_and_sidecar_scoped(
    tmp_path,
) -> None:
    runtime_path = tmp_path / "state" / "instance-runtime.jsonl"

    expected = runtime_path.parent / "instance-runtime.jsonl.continuity-deletions.jsonl"
    assert plugin_continuity_deletion_journal_path(runtime_path) == expected
    assert PluginContinuityDeletionJournal.for_instance_runtime(runtime_path).path == (
        expected
    )
    assert (
        plugin_continuity_deletion_journal_path(
            tmp_path / "other" / "instance-runtime.jsonl"
        )
        != expected
    )
    assert (
        plugin_continuity_deletion_journal_path(runtime_path.with_suffix(""))
        != expected
    )


@dataclass(slots=True)
class _Candidate:
    plan: ContinuityDeletionPlanV1
    events: list[str]
    _receipt: ContinuityDeletionReceiptV1 | None = field(default=None, init=False)

    @property
    def target(self) -> ContinuityTarget:
        return self.plan.target

    async def commit(
        self,
        plan: ContinuityDeletionPlanV1,
    ) -> ContinuityDeletionReceiptV1:
        if self._receipt is None:
            self.events.append("commit")
            self._receipt = ContinuityDeletionReceiptV1(
                target=plan.target,
                plan_fingerprint=plan.fingerprint,
                disposition="applied",
            )
        return self._receipt

    async def abort(self) -> None:
        self.events.append("abort")

    async def close(self) -> None:
        self.events.append("close")


def _plan() -> ContinuityDeletionPlanV1:
    return ContinuityDeletionPlanV1(
        ContinuityTarget("plugin.sessions", "session-1", "revision-1")
    )


def _receipt(disposition: str) -> ContinuityDeletionReceiptV1:
    plan = _plan()
    return ContinuityDeletionReceiptV1(
        target=plan.target,
        plan_fingerprint=plan.fingerprint,
        disposition=disposition,  # type: ignore[arg-type]
    )


def _source() -> ContinuityProviderSourceDescriptor:
    return ContinuityProviderSourceDescriptor(
        provider_id="plugin.sessions",
        source="plugin",
        source_id="e" * 64,
        implementation="plugin:example:sessions",
        implementation_version=1,
        plugin_id="example",
        contribution_id="sessions",
        instance_id="example@workspace:test",
        instance_revision=1,
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        owner_binding_fingerprint="f" * 64,
        owner_recovery_fingerprint="a" * 64,
    )
