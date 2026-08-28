from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from loushang.harness.continuity.mutation import (
    AuthorizedContinuityDeletionLease,
    ContinuityDeletionAuthorization,
    ContinuityDeletionPlanV1,
    ContinuityDeletionReceiptV1,
    ContinuityMutationCodecError,
    ContinuityMutationLifecycleError,
    ContinuityMutationPendingCleanup,
    consume_authorized_continuity_deletion,
    prepare_authorized_continuity_deletion,
)
from loushang.harness.continuity.types import (
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
)


class _Text(str):
    pass


class _PlanSubclass(ContinuityDeletionPlanV1):
    pass


class _ReceiptSubclass(ContinuityDeletionReceiptV1):
    pass


class _EqualityTarget:
    provider_id = "remote.sessions"

    def __eq__(self, _other: object) -> bool:
        return True


def test_deletion_plan_and_receipt_are_exact_bounded_records() -> None:
    target = ContinuityTarget("remote.sessions", "session-1", "revision-1")
    plan = ContinuityDeletionPlanV1(target)
    receipt = ContinuityDeletionReceiptV1(
        target=target,
        plan_fingerprint=plan.fingerprint,
        disposition="applied",
    )

    assert plan.to_dict()["mutationKind"] == "delete"
    assert len(plan.fingerprint) == 64
    assert receipt.to_dict()["planFingerprint"] == plan.fingerprint
    assert ContinuityDeletionPlanV1.from_dict(plan.to_dict()) == plan
    assert ContinuityDeletionReceiptV1.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(ValueError, match="exact target revision"):
        ContinuityDeletionPlanV1(ContinuityTarget("remote.sessions", "session-1"))
    with pytest.raises(ValueError, match="hard limit"):
        ContinuityDeletionPlanV1(
            ContinuityTarget("remote.sessions", "x" * 513, "revision-1")
        )
    with pytest.raises(ValueError, match="fingerprint"):
        ContinuityDeletionReceiptV1(
            target=target,
            plan_fingerprint="not-a-digest",
            disposition="applied",
        )
    with pytest.raises(TypeError, match="authority-issued"):
        ContinuityDeletionAuthorization()
    with pytest.raises(TypeError, match="owner-constructed"):
        AuthorizedContinuityDeletionLease()
    with pytest.raises(TypeError, match="owner-constructed"):
        ContinuityMutationPendingCleanup()
    with pytest.raises(ValueError, match="plan version"):
        ContinuityDeletionPlanV1(target, plan_version=True)
    with pytest.raises(ValueError, match="receipt version"):
        ContinuityDeletionReceiptV1(
            target=target,
            plan_fingerprint=plan.fingerprint,
            disposition="applied",
            receipt_version=True,
        )
    with pytest.raises(ValueError, match="exact target revision"):
        ContinuityDeletionReceiptV1(
            target=ContinuityTarget("remote.sessions", "session-1"),
            plan_fingerprint=plan.fingerprint,
            disposition="applied",
        )
    with pytest.raises(ValueError, match="valid UTF-8"):
        ContinuityDeletionPlanV1(
            ContinuityTarget("remote.sessions", "session-\ud800", "revision-1")
        )
    with pytest.raises(TypeError, match="built-in string"):
        ContinuityDeletionPlanV1(
            ContinuityTarget("remote.sessions", _Text("session-1"), "revision-1")
        )
    with pytest.raises(ValueError, match="disposition"):
        ContinuityDeletionReceiptV1(
            target=target,
            plan_fingerprint=plan.fingerprint,
            disposition=_Text("applied"),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (
            {
                "mutationKind": "delete",
                "planVersion": 2,
                "target": {
                    "providerId": "remote.sessions",
                    "opaqueId": "session-1",
                    "revision": "revision-1",
                },
            },
            "continuity_mutation_record_version_unsupported",
        ),
        (
            {
                "mutationKind": "delete",
                "planVersion": 1,
                "target": {
                    "providerId": "remote.sessions",
                    "opaqueId": "session-1",
                    "revision": "revision-1",
                },
                "extension": True,
            },
            "continuity_mutation_record_fields_mismatch",
        ),
    ],
)
def test_deletion_plan_codec_fails_closed(
    record: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(ContinuityMutationCodecError) as caught:
        ContinuityDeletionPlanV1.from_dict(record)
    assert caught.value.code == code


def test_deletion_receipt_codec_rejects_unknown_fields_and_disposition() -> None:
    receipt = ContinuityDeletionReceiptV1(
        target=_plan().target,
        plan_fingerprint=_plan().fingerprint,
        disposition="not_found",
    ).to_dict()
    receipt["extension"] = True
    with pytest.raises(ContinuityMutationCodecError) as caught:
        ContinuityDeletionReceiptV1.from_dict(receipt)
    assert caught.value.code == "continuity_mutation_record_fields_mismatch"

    receipt.pop("extension")
    receipt["disposition"] = "deleted"
    with pytest.raises(ContinuityMutationCodecError) as caught:
        ContinuityDeletionReceiptV1.from_dict(receipt)
    assert caught.value.code == (
        "continuity_mutation_record_disposition_unsupported"
    )


def test_authorized_deletion_is_idempotent_and_settles_after_source_commit() -> None:
    asyncio.run(_authorized_deletion_is_idempotent())


async def _authorized_deletion_is_idempotent() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    first = await consume_authorized_continuity_deletion(lease)
    second = await consume_authorized_continuity_deletion(lease)
    await lease.close()

    assert first is second
    assert first.disposition == "applied"
    assert lease.consumed is True
    assert candidate.commit_calls == 1
    assert authority.complete_calls == 1
    assert candidate.close_calls == 1
    assert events == ["authorize", "commit", "complete", "close"]


def test_completion_failure_retries_without_repeating_source_commit() -> None:
    asyncio.run(_completion_failure_retries_without_repeating_commit())


async def _completion_failure_retries_without_repeating_commit() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events, complete_failures=1)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_completion_retryable"
    assert "synthetic" not in str(caught.value)
    receipt = await lease.consume()

    assert receipt.disposition == "applied"
    assert candidate.commit_calls == 1
    assert authority.complete_calls == 2
    assert candidate.close_calls == 1
    assert events == ["authorize", "commit", "complete", "complete", "close"]


def test_abort_after_source_commit_only_retries_product_completion() -> None:
    asyncio.run(_abort_after_source_commit_only_retries_completion())


async def _abort_after_source_commit_only_retries_completion() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events, complete_failures=1)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_completion_retryable"
    await lease.abort()

    assert lease.consumed is True
    assert candidate.commit_calls == 1
    assert candidate.abort_calls == 0
    assert authority.complete_calls == 2
    assert authority.cancel_calls == 0
    assert candidate.close_calls == 1
    assert events == ["authorize", "commit", "complete", "complete", "close"]


def test_cancelled_consume_joins_owned_commit_and_later_replays_result() -> None:
    asyncio.run(_cancelled_consume_joins_owned_commit())


async def _cancelled_consume_joins_owned_commit() -> None:
    events: list[str] = []
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    candidate = _Candidate(
        _plan(),
        events,
        commit_started=commit_started,
        allow_commit=allow_commit,
    )
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )
    consuming = asyncio.create_task(lease.consume())
    await commit_started.wait()
    consuming.cancel()
    await asyncio.sleep(0)
    assert not consuming.done()

    allow_commit.set()
    with pytest.raises(asyncio.CancelledError):
        await consuming
    receipt = await lease.consume()

    assert lease.consumed is True
    assert receipt.disposition == "applied"
    assert candidate.commit_calls == 1
    assert authority.complete_calls == 1
    assert candidate.close_calls == 1


def test_concurrent_consumers_share_one_exact_transaction() -> None:
    asyncio.run(_concurrent_consumers_share_transaction())


async def _concurrent_consumers_share_transaction() -> None:
    events: list[str] = []
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    candidate = _Candidate(
        _plan(),
        events,
        commit_started=commit_started,
        allow_commit=allow_commit,
    )
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )
    first = asyncio.create_task(lease.consume())
    await commit_started.wait()
    second = asyncio.create_task(lease.consume())
    allow_commit.set()

    first_receipt, second_receipt = await asyncio.gather(first, second)

    assert first_receipt is second_receipt
    assert candidate.commit_calls == 1
    assert authority.complete_calls == 1
    assert candidate.close_calls == 1


def test_abort_intent_prevents_commit_and_cleanup_is_idempotent() -> None:
    asyncio.run(_abort_intent_prevents_commit())


async def _abort_intent_prevents_commit() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    await lease.abort()
    await lease.close()

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_lease_closed"
    assert candidate.commit_calls == 0
    assert candidate.abort_calls == 1
    assert authority.cancel_calls == 1
    assert candidate.close_calls == 1
    assert events == ["authorize", "cancel", "abort", "close"]


def test_abort_cleanup_retries_each_checkpoint_without_repeating_progress() -> None:
    asyncio.run(_abort_cleanup_retries_each_checkpoint())


async def _abort_cleanup_retries_each_checkpoint() -> None:
    events: list[str] = []
    candidate = _Candidate(
        _plan(),
        events,
        abort_failures=1,
        close_failures=1,
    )
    authority = _Authority(events, cancel_failures=1)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    for expected_code in (
        "continuity_mutation_cleanup_retryable",
        "continuity_mutation_cleanup_retryable",
        "continuity_mutation_release_retryable",
    ):
        with pytest.raises(ContinuityMutationLifecycleError) as caught:
            await lease.abort()
        assert caught.value.code == expected_code
        assert "/tmp/private" not in str(caught.value)
    await lease.close()

    assert authority.cancel_calls == 2
    assert candidate.abort_calls == 2
    assert candidate.close_calls == 2
    assert events == [
        "authorize",
        "cancel",
        "cancel",
        "abort",
        "abort",
        "close",
        "close",
    ]


def test_async_context_manager_releases_both_terminal_paths_once() -> None:
    asyncio.run(_async_context_manager_releases_terminal_paths())


async def _async_context_manager_releases_terminal_paths() -> None:
    aborted_events: list[str] = []
    aborted_candidate = _Candidate(_plan(), aborted_events)
    aborted_lease = await prepare_authorized_continuity_deletion(
        aborted_candidate,
        source=_source(),
        authority=_Authority(aborted_events),
    )
    with pytest.raises(ValueError, match="body failure"):
        async with aborted_lease:
            raise ValueError("body failure")
    assert aborted_events == ["authorize", "cancel", "abort", "close"]

    consumed_events: list[str] = []
    consumed_candidate = _Candidate(_plan(), consumed_events)
    consumed_lease = await prepare_authorized_continuity_deletion(
        consumed_candidate,
        source=_source(),
        authority=_Authority(consumed_events),
    )
    async with consumed_lease:
        assert (await consumed_lease.consume()).disposition == "applied"
    assert consumed_candidate.close_calls == 1
    assert consumed_events == ["authorize", "commit", "complete", "close"]


def test_cancelled_abort_joins_blocked_release_before_propagating() -> None:
    asyncio.run(_cancelled_abort_joins_blocked_release())


async def _cancelled_abort_joins_blocked_release() -> None:
    events: list[str] = []
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    candidate = _Candidate(
        _plan(),
        events,
        close_started=close_started,
        allow_close=allow_close,
    )
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=_Authority(events),
    )
    aborting = asyncio.create_task(lease.abort())
    await close_started.wait()
    aborting.cancel()
    await asyncio.sleep(0)
    assert not aborting.done()

    allow_close.set()
    with pytest.raises(asyncio.CancelledError):
        await aborting
    await lease.close()

    assert candidate.close_calls == 1
    assert events == ["authorize", "cancel", "abort", "close"]


def test_commit_linearized_before_abort_is_joined_not_cancelled() -> None:
    asyncio.run(_commit_linearized_before_abort_is_joined())


async def _commit_linearized_before_abort_is_joined() -> None:
    events: list[str] = []
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    candidate = _Candidate(
        _plan(),
        events,
        commit_started=commit_started,
        allow_commit=allow_commit,
    )
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )
    consuming = asyncio.create_task(lease.consume())
    await commit_started.wait()
    aborting = asyncio.create_task(lease.abort())
    await asyncio.sleep(0)
    assert not aborting.done()

    allow_commit.set()
    assert (await consuming).disposition == "applied"
    await aborting

    assert candidate.abort_calls == 0
    assert authority.cancel_calls == 0
    assert candidate.close_calls == 1
    assert events == ["authorize", "commit", "complete", "close"]


def test_preparation_failure_retains_opaque_retryable_cleanup() -> None:
    asyncio.run(_preparation_failure_retains_cleanup())


async def _preparation_failure_retains_cleanup() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events, abort_failures=1)
    authority = _Authority(events, authorize_failures=1)

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=authority,
        )
    assert caught.value.code == "continuity_mutation_preparation_cleanup_retryable"
    assert caught.value.pending_cleanup is not None

    await caught.value.pending_cleanup.retry()
    assert candidate.abort_calls == 2
    assert candidate.close_calls == 1
    assert events == ["authorize", "abort", "abort", "close"]


def test_cancelled_authorization_is_settled_before_cancellation_propagates() -> None:
    asyncio.run(_cancelled_authorization_is_settled())


async def _cancelled_authorization_is_settled() -> None:
    events: list[str] = []
    authorize_started = asyncio.Event()
    allow_authorize = asyncio.Event()
    candidate = _Candidate(_plan(), events)
    authority = _Authority(
        events,
        authorize_started=authorize_started,
        allow_authorize=allow_authorize,
    )
    preparing = asyncio.create_task(
        prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=authority,
        )
    )
    await authorize_started.wait()
    preparing.cancel()
    await asyncio.sleep(0)
    assert not preparing.done()

    allow_authorize.set()
    with pytest.raises(asyncio.CancelledError):
        await preparing

    assert authority.cancel_calls == 1
    assert candidate.abort_calls == 1
    assert candidate.close_calls == 1
    assert events == ["authorize", "cancel", "abort", "close"]


def test_mismatched_source_and_receipt_fail_closed() -> None:
    asyncio.run(_mismatched_source_and_receipt_fail_closed())


async def _mismatched_source_and_receipt_fail_closed() -> None:
    source_events: list[str] = []
    candidate = _Candidate(_plan(), source_events)
    authority = _Authority([])
    wrong_source = ContinuityProviderSourceDescriptor(
        provider_id="another.provider",
        source="product",
        source_id="product:other",
        implementation="tests.other",
        implementation_version=1,
    )
    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=wrong_source,
            authority=authority,
        )
    assert caught.value.code == "continuity_mutation_source_mismatch"
    assert candidate.abort_calls == 1
    assert candidate.close_calls == 1
    assert source_events == ["abort", "close"]

    events: list[str] = []
    bad_candidate = _Candidate(_plan(), events, wrong_receipt=True)
    lease = await prepare_authorized_continuity_deletion(
        bad_candidate,
        source=_source(),
        authority=_Authority(events),
    )
    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_receipt_mismatch"
    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.abort()
    assert caught.value.code == "continuity_mutation_receipt_mismatch"
    assert bad_candidate.commit_calls == 2
    assert bad_candidate.abort_calls == 0
    assert events == ["authorize", "commit"]


def test_foreign_authorization_is_cancelled_and_candidate_is_aborted() -> None:
    asyncio.run(_foreign_authorization_is_cleaned_up())


async def _foreign_authorization_is_cleaned_up() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _ForeignEvidenceAuthority(events, issuer=_Authority([]))

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=authority,
        )

    assert caught.value.code == "continuity_mutation_authorization_mismatch"
    assert authority.cancel_calls == 1
    assert candidate.abort_calls == 1
    assert candidate.close_calls == 1
    assert events == ["authorize", "cancel", "abort", "close"]


def test_same_authority_wrong_plan_evidence_fails_before_commit() -> None:
    asyncio.run(_same_authority_wrong_plan_is_cleaned_up())


async def _same_authority_wrong_plan_is_cleaned_up() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events, authorize_wrong_plan=True)

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=authority,
        )

    assert caught.value.code == "continuity_mutation_authorization_mismatch"
    assert candidate.commit_calls == 0
    assert authority.cancel_calls == 1
    assert events == ["authorize", "cancel", "abort", "close"]


def test_commit_error_after_effect_stays_on_completion_only_recovery_path() -> None:
    asyncio.run(_commit_error_after_effect_stays_pinned())


async def _commit_error_after_effect_stays_pinned() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events, commit_failures_after_apply=1)
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_source_commit_retryable"
    assert "synthetic" not in str(caught.value)
    await lease.abort()

    assert lease.consumed is True
    assert candidate.commit_calls == 2
    assert candidate.abort_calls == 0
    assert authority.cancel_calls == 0
    assert events == ["authorize", "commit", "complete", "close"]


def test_owned_failure_outranks_cancellation_and_remains_retryable() -> None:
    asyncio.run(_owned_failure_outranks_cancellation())


async def _owned_failure_outranks_cancellation() -> None:
    events: list[str] = []
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    candidate = _Candidate(
        _plan(),
        events,
        commit_started=commit_started,
        allow_commit=allow_commit,
        commit_failures_after_apply=1,
    )
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )
    consuming = asyncio.create_task(lease.consume())
    await commit_started.wait()
    consuming.cancel()
    allow_commit.set()

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await consuming
    assert caught.value.code == "continuity_mutation_source_commit_retryable"
    await lease.close()

    assert candidate.commit_calls == 2
    assert authority.cancel_calls == 0
    assert candidate.abort_calls == 0


def test_candidate_release_failure_retries_without_repeating_settlement() -> None:
    asyncio.run(_candidate_release_failure_retries())


async def _candidate_release_failure_retries() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events, close_failures=1)
    authority = _Authority(events)
    lease = await prepare_authorized_continuity_deletion(
        candidate,
        source=_source(),
        authority=authority,
    )

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_release_retryable"
    assert lease.consumed is True
    receipt = await lease.consume()

    assert receipt.disposition == "applied"
    assert candidate.commit_calls == 1
    assert authority.complete_calls == 1
    assert candidate.close_calls == 2
    assert events == ["authorize", "commit", "complete", "close", "close"]


def test_candidate_change_during_authorization_fails_before_commit() -> None:
    asyncio.run(_candidate_change_during_authorization_fails())


async def _candidate_change_during_authorization_fails() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events, mutate_candidate=candidate)

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=authority,
        )

    assert caught.value.code == "continuity_mutation_candidate_mismatch"
    assert candidate.commit_calls == 0
    assert authority.cancel_calls == 1
    assert events == ["authorize", "cancel", "abort", "close"]


def test_candidate_descriptor_failure_is_redacted_and_cleaned_up() -> None:
    asyncio.run(_candidate_descriptor_failure_is_redacted())


async def _candidate_descriptor_failure_is_redacted() -> None:
    events: list[str] = []
    candidate = _ExplodingCandidate(events)

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=_Authority(events),
        )

    assert caught.value.code == "continuity_mutation_candidate_mismatch"
    assert "/tmp/private" not in str(caught.value)
    assert events == ["abort", "close"]


def test_exact_candidate_types_reject_equality_and_record_subclass_tricks() -> None:
    asyncio.run(_exact_candidate_types_reject_tricks())


async def _exact_candidate_types_reject_tricks() -> None:
    fake_target_events: list[str] = []
    fake_target_candidate = _Candidate(
        _plan(),
        fake_target_events,
        target_override=_EqualityTarget(),
    )
    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            fake_target_candidate,
            source=_source(),
            authority=_Authority(fake_target_events),
        )
    assert caught.value.code == "continuity_mutation_candidate_mismatch"
    assert fake_target_events == ["abort", "close"]

    subclass_events: list[str] = []
    subclass_plan = _PlanSubclass(_plan().target)
    subclass_candidate = _Candidate(subclass_plan, subclass_events)
    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            subclass_candidate,
            source=_source(),
            authority=_Authority(subclass_events),
        )
    assert caught.value.code == "continuity_mutation_candidate_mismatch"
    assert subclass_events == ["abort", "close"]

    receipt_events: list[str] = []
    receipt_candidate = _Candidate(
        _plan(),
        receipt_events,
        subclass_receipt=True,
    )
    lease = await prepare_authorized_continuity_deletion(
        receipt_candidate,
        source=_source(),
        authority=_Authority(receipt_events),
    )
    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await lease.consume()
    assert caught.value.code == "continuity_mutation_receipt_mismatch"
    assert receipt_events == ["authorize", "commit"]


def test_authorization_failure_is_redacted_after_cleanup() -> None:
    asyncio.run(_authorization_failure_is_redacted())


async def _authorization_failure_is_redacted() -> None:
    events: list[str] = []
    candidate = _Candidate(_plan(), events)
    authority = _Authority(events, authorize_failures=1)

    with pytest.raises(ContinuityMutationLifecycleError) as caught:
        await prepare_authorized_continuity_deletion(
            candidate,
            source=_source(),
            authority=authority,
        )

    assert caught.value.code == "continuity_mutation_authorization_failed"
    assert "synthetic" not in str(caught.value)
    assert events == ["authorize", "abort", "close"]


@dataclass(slots=True)
class _Candidate:
    plan: ContinuityDeletionPlanV1
    events: list[str]
    commit_started: asyncio.Event | None = None
    allow_commit: asyncio.Event | None = None
    close_started: asyncio.Event | None = None
    allow_close: asyncio.Event | None = None
    abort_failures: int = 0
    close_failures: int = 0
    commit_failures_after_apply: int = 0
    wrong_receipt: bool = False
    subclass_receipt: bool = False
    target_override: object | None = None
    commit_calls: int = 0
    abort_calls: int = 0
    close_calls: int = 0
    _receipt: ContinuityDeletionReceiptV1 | None = field(default=None, init=False)

    @property
    def target(self) -> ContinuityTarget:
        if self.target_override is not None:
            return self.target_override  # type: ignore[return-value]
        return self.plan.target

    async def commit(
        self,
        plan: ContinuityDeletionPlanV1,
    ) -> ContinuityDeletionReceiptV1:
        self.commit_calls += 1
        if self._receipt is not None:
            return self._receipt
        self.events.append("commit")
        if self.commit_started is not None:
            self.commit_started.set()
        if self.allow_commit is not None:
            await self.allow_commit.wait()
        target = (
            ContinuityTarget("remote.sessions", "wrong", "revision-1")
            if self.wrong_receipt
            else plan.target
        )
        receipt_type = (
            _ReceiptSubclass
            if self.subclass_receipt
            else ContinuityDeletionReceiptV1
        )
        self._receipt = receipt_type(
            target=target,
            plan_fingerprint=plan.fingerprint,
            disposition="applied",
        )
        if self.commit_failures_after_apply:
            self.commit_failures_after_apply -= 1
            raise RuntimeError("synthetic commit failure with secret=/tmp/private")
        return self._receipt

    async def abort(self) -> None:
        self.abort_calls += 1
        self.events.append("abort")
        if self.abort_failures:
            self.abort_failures -= 1
            raise RuntimeError("synthetic abort failure")

    async def close(self) -> None:
        self.close_calls += 1
        self.events.append("close")
        if self.close_started is not None:
            self.close_started.set()
        if self.allow_close is not None:
            await self.allow_close.wait()
        if self.close_failures:
            self.close_failures -= 1
            raise RuntimeError("synthetic close failure with secret=/tmp/private")


@dataclass(slots=True)
class _ExplodingCandidate:
    events: list[str]

    @property
    def plan(self) -> ContinuityDeletionPlanV1:
        raise RuntimeError("secret=/tmp/private")

    @property
    def target(self) -> ContinuityTarget:
        return _plan().target

    async def commit(
        self,
        plan: ContinuityDeletionPlanV1,
    ) -> ContinuityDeletionReceiptV1:
        raise AssertionError("invalid candidate must not commit")

    async def abort(self) -> None:
        self.events.append("abort")

    async def close(self) -> None:
        self.events.append("close")


@dataclass(slots=True)
class _Authority:
    events: list[str]
    authorize_failures: int = 0
    complete_failures: int = 0
    cancel_failures: int = 0
    authorize_wrong_plan: bool = False
    authorize_started: asyncio.Event | None = None
    allow_authorize: asyncio.Event | None = None
    mutate_candidate: _Candidate | None = None
    authorize_calls: int = 0
    complete_calls: int = 0
    cancel_calls: int = 0

    async def authorize_delete(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> ContinuityDeletionAuthorization:
        self.authorize_calls += 1
        self.events.append("authorize")
        if self.authorize_started is not None:
            self.authorize_started.set()
        if self.allow_authorize is not None:
            await self.allow_authorize.wait()
        if self.authorize_failures:
            self.authorize_failures -= 1
            raise RuntimeError(
                "synthetic authorization failure with secret=/tmp/private"
            )
        if self.mutate_candidate is not None:
            self.mutate_candidate.plan = ContinuityDeletionPlanV1(
                ContinuityTarget("remote.sessions", "session-2", "revision-2")
            )
        authorized_plan = (
            ContinuityDeletionPlanV1(
                ContinuityTarget("remote.sessions", "wrong", "revision-1")
            )
            if self.authorize_wrong_plan
            else plan
        )
        return ContinuityDeletionAuthorization._issue(
            self,
            authorization_id="a" * 64,
            plan=authorized_plan,
            source=source,
        )

    async def complete_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
        receipt: ContinuityDeletionReceiptV1,
    ) -> None:
        assert authorization._authority is self
        assert receipt.plan_fingerprint == authorization.plan_fingerprint
        self.complete_calls += 1
        self.events.append("complete")
        if self.complete_failures:
            self.complete_failures -= 1
            raise RuntimeError("synthetic completion failure")

    async def cancel_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
    ) -> None:
        assert authorization._authority is self
        self.cancel_calls += 1
        self.events.append("cancel")
        if self.cancel_failures:
            self.cancel_failures -= 1
            raise RuntimeError("synthetic cancel failure with secret=/tmp/private")


@dataclass(slots=True)
class _ForeignEvidenceAuthority:
    events: list[str]
    issuer: _Authority
    cancel_calls: int = 0

    async def authorize_delete(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> ContinuityDeletionAuthorization:
        self.events.append("authorize")
        return ContinuityDeletionAuthorization._issue(
            self.issuer,
            authorization_id="b" * 64,
            plan=plan,
            source=source,
        )

    async def complete_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
        receipt: ContinuityDeletionReceiptV1,
    ) -> None:
        raise AssertionError("foreign evidence must not be completed")

    async def cancel_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
    ) -> None:
        self.cancel_calls += 1
        self.events.append("cancel")


def _plan() -> ContinuityDeletionPlanV1:
    return ContinuityDeletionPlanV1(
        ContinuityTarget("remote.sessions", "session-1", "revision-1")
    )


def _source() -> ContinuityProviderSourceDescriptor:
    return ContinuityProviderSourceDescriptor(
        provider_id="remote.sessions",
        source="product",
        source_id="product:remote-sessions",
        implementation="tests.remote_sessions",
        implementation_version=1,
    )
