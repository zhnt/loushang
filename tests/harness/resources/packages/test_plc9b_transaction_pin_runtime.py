from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleCancelRequestV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
    PackageLifecycleRetryRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pin_runtime import (
    PackageTransactionPinLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)

OPERATION_ID = "operation-transaction-pin-runtime"
ENVIRONMENT_FINGERPRINT = "7" * 64


class _ClassificationAuthority:
    def classification_facts(
        self,
        _request: PackageLifecycleIngressRequestV1,
    ) -> PackageClassificationFactsV1:
        kinds = (
            "explicit_plugin_intent",
            "existing_plugin_binding",
            "existing_plugin_history",
            "independent_non_plugin_authority",
        )
        return PackageClassificationFactsV1(
            facts=tuple(
                PackageClassificationBasisFactV1(
                    kind=kind,  # type: ignore[arg-type]
                    present=kind == "explicit_plugin_intent",
                    authority_id=f"authority:{kind}",
                    owner_revision=f"revision:{kind}:1",
                )
                for kind in kinds
            ),
            policy_revision="classification-policy:1",
            classifier_epoch=1,
        )


@dataclass
class _CandidateNode:
    suspended: bool = False

    def suspend_for_recovery(self) -> None:
        self.suspended = True

    def cleanup(self) -> None:
        self.suspended = True


@dataclass
class _RetentionOwner:
    receipts: dict[str, PackageTransactionPinReceiptV1] = field(default_factory=dict)
    calls: list[PackageTransactionPinRequestV1] = field(default_factory=list)
    after_acquire: Callable[[PackageTransactionPinRequestV1], None] | None = None
    returned_receipt: PackageTransactionPinReceiptV1 | None = None
    failure: Exception | None = None

    def acquire(
        self,
        request: PackageTransactionPinRequestV1,
    ) -> PackageTransactionPinReceiptV1:
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        if self.returned_receipt is not None:
            return self.returned_receipt
        existing = self.receipts.get(request.operation_id)
        if existing is not None:
            if existing.pin_request != request:
                raise RuntimeError("retention request changed")
            receipt = existing
        else:
            receipt = PackageTransactionPinReceiptV1.acquire(
                request,
                pin_id="f" * 64,
                owner_identity="retention-owner",
                owner_revision=7,
                lease_id="lease-transaction-pin",
                lease_revision=3,
            )
            self.receipts[request.operation_id] = receipt
        if self.after_acquire is not None:
            self.after_acquire(request)
        return receipt

    def release(
        self,
        receipt: PackageTransactionPinReceiptV1,
        *,
        transition_evidence_ref: str,
    ) -> PackageTransactionPinReceiptV1:
        return PackageTransactionPinReceiptV1.transition(
            receipt,
            state="released",
            owner_revision=receipt.owner_revision + 1,
            lease_revision=receipt.lease_revision + 1,
            transition_evidence_ref=transition_evidence_ref,
        )


@dataclass
class _ClosurePlans:
    plans: dict[int, VerifiedClosurePlanV2] = field(default_factory=dict)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def plan(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
    ) -> VerifiedClosurePlanV2 | None:
        self.calls.append((operation_id, attempt_epoch))
        return self.plans.get(attempt_epoch)


def _plan(*, attempt_epoch: int = 1) -> VerifiedClosurePlanV2:
    root = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="root-plugin",
        version="1.0",
        canonical_source_identity="https://packages.example.test/root.whl",
        source_envelope_fingerprint="a" * 64,
        acquisition_receipt_fingerprint="b" * 64,
        wheel_evidence_fingerprint="c" * 64,
        artifact_digest="d" * 64,
        extraction_tree_digest="e" * 64,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    return VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=attempt_epoch,
        root_node_id=root.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root,),
        max_depth=0,
    )


def _candidate(
    *,
    attempt_epoch: int = 1,
) -> tuple[VerifiedPackageClosureCandidate, _CandidateNode]:
    node = _CandidateNode()
    return (
        VerifiedPackageClosureCandidate(
            plan=_plan(attempt_epoch=attempt_epoch),
            candidates=(node,),  # type: ignore[arg-type]
        ),
        node,
    )


def _kernel(tmp_path: Path, *, closure_verified: bool = True) -> PackageLifecycleOwner:
    kernel = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    status = kernel.submit(
        PackageLifecycleIngressRequestV1(
            operation_id=OPERATION_ID,
            action="install",
            product_id="coding",
            scope_id="workspace:test",
            requested_package="root-plugin==1.0",
            requested_plugin_id="plugin-test",
            source_locator="https://packages.example.test/root.whl",
            policy_revision="package-policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        )
    )
    if not closure_verified:
        return kernel
    for phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
    ):
        status = kernel.advance(
            OPERATION_ID,
            next_phase=phase,  # type: ignore[arg-type]
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    return kernel


def _owner(
    tmp_path: Path,
    *,
    kernel: PackageLifecycleOwner | None = None,
    retention: _RetentionOwner | None = None,
    closure_plans: _ClosurePlans | None = None,
) -> tuple[
    PackageTransactionPinLifecycleOwner,
    PackageLifecycleOwner,
    _RetentionOwner,
    PackageTransactionPinJournal,
]:
    kernel = kernel or _kernel(tmp_path)
    retention = retention or _RetentionOwner()
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    return (
        PackageTransactionPinLifecycleOwner(
            kernel=kernel,
            closure_plans=closure_plans or _ClosurePlans(plans={1: _plan()}),
            retention=retention,
            pin_journal=journal,
        ),
        kernel,
        retention,
        journal,
    )


def _request(kernel: PackageLifecycleOwner) -> PackageTransactionPinRequestV1:
    status = kernel.status(OPERATION_ID)
    assert status is not None and status.classification is not None
    return PackageTransactionPinRequestV1.create(
        _plan(),
        request_fingerprint=status.request_fingerprint,
        classification_fingerprint=status.classification.evidence_ref,
        recovery_identity="recovery-transaction-pin-runtime",
    )


def test_pin_runtime_acquires_journals_advances_and_exactly_replays(
    tmp_path: Path,
) -> None:
    owner, _kernel_owner, retention, journal = _owner(tmp_path)
    candidate, node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )
    replay = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.status.phase == "transaction_pinned"
    assert result.status.disposition == "active"
    assert result.candidate is candidate
    assert result.receipt is not None
    assert replay.receipt == result.receipt
    assert replay.candidate is candidate
    assert len(retention.calls) == 2
    assert len(journal.records()) == 1
    assert node.suspended is False


def test_pin_runtime_recovers_external_acquire_before_local_receipt(
    tmp_path: Path,
) -> None:
    owner, kernel, retention, journal = _owner(tmp_path)
    external = retention.acquire(_request(kernel))
    candidate, _node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.receipt == external
    assert result.status.phase == "transaction_pinned"
    assert journal.records()[0].receipt == external
    assert len(retention.receipts) == 1


def test_pin_runtime_recovers_local_receipt_before_phase_cas(tmp_path: Path) -> None:
    owner, kernel, retention, journal = _owner(tmp_path)
    acquired = retention.acquire(_request(kernel))
    journal.append(acquired)
    candidate, _node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.receipt == acquired
    assert result.status.phase == "transaction_pinned"
    assert len(journal.records()) == 1


def test_pin_runtime_recovers_pinned_operation_without_live_candidate(
    tmp_path: Path,
) -> None:
    owner, kernel, retention, journal = _owner(tmp_path)
    candidate, node = _candidate()
    pinned = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )
    assert pinned.receipt is not None
    candidate.suspend_for_recovery()
    restarted = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=_ClosurePlans(plans={1: _plan()}),
        retention=retention,
        pin_journal=PackageTransactionPinJournal(journal.path),
    )

    recovered = restarted.recover(
        OPERATION_ID,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert recovered.status.phase == "transaction_pinned"
    assert recovered.status.disposition == "active"
    assert recovered.candidate is None
    assert recovered.receipt == pinned.receipt
    assert len(retention.receipts) == 1
    assert len(journal.records()) == 1
    assert node.suspended is True


def test_pin_runtime_recovers_interrupted_pinned_operation_and_visible_pin(
    tmp_path: Path,
) -> None:
    owner, kernel, retention, journal = _owner(tmp_path)
    candidate, _node = _candidate()
    pinned = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )
    assert pinned.receipt is not None
    interrupted = kernel.interrupt(
        OPERATION_ID,
        expected_phase="transaction_pinned",
        expected_journal_revision=pinned.status.journal_revision,
        expected_attempt_epoch=pinned.status.attempt_epoch,
    )
    restarted = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=_ClosurePlans(plans={1: _plan()}),
        retention=retention,
        pin_journal=PackageTransactionPinJournal(journal.path),
    )

    recovered = restarted.recover(
        OPERATION_ID,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert recovered.status == interrupted
    assert recovered.status.disposition == "retryable_failure"
    assert recovered.receipt == pinned.receipt
    assert recovered.candidate is None
    assert retention.receipts[OPERATION_ID] == pinned.receipt
    assert len(journal.records()) == 1


def test_pin_runtime_recovery_rejects_changed_identity_before_retention(
    tmp_path: Path,
) -> None:
    owner, kernel, retention, journal = _owner(tmp_path)
    candidate, _node = _candidate()
    pinned = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )
    assert pinned.receipt is not None
    calls = len(retention.calls)
    restarted = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=_ClosurePlans(plans={1: _plan()}),
        retention=retention,
        pin_journal=PackageTransactionPinJournal(journal.path),
    )

    recovered = restarted.recover(
        OPERATION_ID,
        recovery_identity="recovery-changed",
    )

    assert recovered.status.disposition == "rejected"
    assert recovered.status.phase == "transaction_pinned"
    assert recovered.status.failure is not None
    assert recovered.status.failure.code == "package_operation_identity_conflict"
    assert recovered.receipt is None
    assert len(retention.calls) == calls
    assert len(journal.records()) == 1


def test_pin_runtime_recovery_rejects_missing_local_receipt_before_retention(
    tmp_path: Path,
) -> None:
    owner, kernel, retention, _journal = _owner(tmp_path)
    candidate, _node = _candidate()
    pinned = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )
    assert pinned.receipt is not None
    calls = len(retention.calls)
    restarted = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=_ClosurePlans(plans={1: _plan()}),
        retention=retention,
        pin_journal=PackageTransactionPinJournal(
            tmp_path / "missing-transaction-pins.jsonl"
        ),
    )

    recovered = restarted.recover(
        OPERATION_ID,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert recovered.status.disposition == "rejected"
    assert recovered.status.phase == "transaction_pinned"
    assert recovered.status.failure is not None
    assert recovered.status.failure.code == "package_operation_identity_conflict"
    assert recovered.receipt is None
    assert len(retention.calls) == calls
    assert not (tmp_path / "missing-transaction-pins.jsonl").exists()


def test_pin_runtime_cancel_wins_phase_cas_without_releasing_visible_pin(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    retention = _RetentionOwner()

    def cancel(_request: PackageTransactionPinRequestV1) -> None:
        status = kernel.status(OPERATION_ID)
        assert status is not None
        kernel.cancel(
            PackageLifecycleCancelRequestV1(
                operation_id=OPERATION_ID,
                request_fingerprint=status.request_fingerprint,
                expected_phase="closure_verified",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
        )

    retention.after_acquire = cancel
    owner, _kernel_owner, _retention, journal = _owner(
        tmp_path,
        kernel=kernel,
        retention=retention,
    )
    candidate, node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.status.disposition == "cancelled"
    assert result.status.phase == "closure_verified"
    assert result.candidate is None
    assert result.receipt is not None
    assert result.receipt.state == "acquired"
    assert journal.records()[0].receipt == result.receipt
    assert len(retention.receipts) == 1
    assert node.suspended is True


def test_pin_runtime_rejects_changed_recovery_before_another_retention_call(
    tmp_path: Path,
) -> None:
    owner, _kernel_owner, retention, journal = _owner(tmp_path)
    first_candidate, _node = _candidate()
    accepted = owner.pin(
        first_candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )
    assert accepted.receipt is not None
    calls = len(retention.calls)
    changed_candidate, changed_node = _candidate()

    changed = owner.pin(
        changed_candidate,
        recovery_identity="recovery-changed",
    )

    assert changed.status.disposition == "rejected"
    assert changed.status.failure is not None
    assert changed.status.failure.code == "package_operation_identity_conflict"
    assert changed.receipt is None
    assert len(retention.calls) == calls
    assert len(journal.records()) == 1
    assert changed_node.suspended is True


def test_pin_runtime_rejects_invalid_external_receipt_without_phase_mutation(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    wrong_request = PackageTransactionPinRequestV1.create(
        _plan(),
        request_fingerprint="0" * 64,
        classification_fingerprint="1" * 64,
        recovery_identity="recovery-wrong",
    )
    retention = _RetentionOwner(
        returned_receipt=_RetentionOwner().acquire(wrong_request)
    )
    owner, _kernel_owner, _retention, journal = _owner(
        tmp_path,
        kernel=kernel,
        retention=retention,
    )
    candidate, node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.status.disposition == "rejected"
    assert result.status.phase == "closure_verified"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert result.receipt is None
    assert journal.records() == ()
    assert node.suspended is True


def test_pin_runtime_rejects_unjournaled_or_changed_closure_before_retention(
    tmp_path: Path,
) -> None:
    plans = _ClosurePlans()
    owner, _kernel_owner, retention, journal = _owner(
        tmp_path,
        closure_plans=plans,
    )
    candidate, node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert plans.calls == [(OPERATION_ID, 1)]
    assert retention.calls == []
    assert journal.records() == ()
    assert node.suspended is True


def test_pin_runtime_adopts_prior_attempt_pin_without_double_acquire(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    retention = _RetentionOwner()
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    acquired = retention.acquire(_request(kernel))
    journal.append(acquired)
    status = kernel.status(OPERATION_ID)
    assert status is not None
    interrupted = kernel.interrupt(
        OPERATION_ID,
        expected_phase="closure_verified",
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    retry = kernel.retry(
        PackageLifecycleRetryRequestV1(
            operation_id=OPERATION_ID,
            request_fingerprint=interrupted.request_fingerprint,
            expected_attempt_epoch=interrupted.attempt_epoch,
        )
    )
    assert retry.phase == "closure_verified"
    assert retry.attempt_epoch == 2
    owner = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=_ClosurePlans(plans={1: _plan(), 2: _plan(attempt_epoch=2)}),
        retention=retention,
        pin_journal=journal,
    )
    candidate, node = _candidate(attempt_epoch=2)

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.status.phase == "transaction_pinned"
    assert result.status.attempt_epoch == 2
    assert result.receipt == acquired
    assert result.receipt.pin_request.attempt_epoch == 1
    assert len(retention.receipts) == 1
    assert len(journal.records()) == 1
    assert node.suspended is False


def test_pin_runtime_suspends_candidate_when_retention_owner_fails(
    tmp_path: Path,
) -> None:
    retention = _RetentionOwner(failure=RuntimeError("retention unavailable"))
    owner, _kernel_owner, _retention, journal = _owner(
        tmp_path,
        retention=retention,
    )
    candidate, node = _candidate()

    with pytest.raises(RuntimeError, match="retention unavailable"):
        owner.pin(
            candidate,
            recovery_identity="recovery-transaction-pin-runtime",
        )

    assert journal.records() == ()
    assert node.suspended is True


def test_pin_runtime_refuses_preclosure_phase_without_retention_call(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path, closure_verified=False)
    owner, _kernel_owner, retention, journal = _owner(tmp_path, kernel=kernel)
    candidate, node = _candidate()

    result = owner.pin(
        candidate,
        recovery_identity="recovery-transaction-pin-runtime",
    )

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert retention.calls == []
    assert journal.records() == ()
    assert node.suspended is True
