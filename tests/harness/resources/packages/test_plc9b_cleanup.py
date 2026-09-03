from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineCleanupTargetV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupStatusV1,
)


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    payload: bytes

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        sink.write(self.payload)
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _Authority:
    stream: _Stream

    def authorize(self, _request: PackageAcquisitionRequestV1) -> _Stream:
        return self.stream


def _candidate(tmp_path: Path):
    payload = b"rejected-artifact"
    request = PackageAcquisitionRequestV1(
        operation_id="cleanup-operation",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity="https://packages.example.test/rejected.whl",
        request_fingerprint="a" * 64,
        requested_locator_digest="b" * 64,
        policy_revision="source-policy:1",
    )
    envelope = AuthenticatedSourceEnvelopeV1(
        operation_id=request.operation_id,
        node_id=request.node_id,
        canonical_source_identity=request.canonical_source_identity,
        origin_kind="https",
        authentication_decision="authorized",
        authority_id="source-authority:test",
        requested_locator_digest=request.requested_locator_digest,
        expected_artifact_digest=sha256(payload).hexdigest(),
        redirect_policy_revision="redirect-policy:1",
        policy_revision=request.policy_revision,
        capture_epoch=1,
    )
    store = PackageQuarantineStore(tmp_path / "quarantine")
    owner = PackageAcquisitionOwner(
        source_authority=_Authority(_Stream(envelope=envelope, payload=payload)),
        quarantine_store=store,
    )
    candidate = owner.acquire(
        request,
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=1024,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
    )
    return candidate, store


def _pending(tmp_path: Path):
    candidate, store = _candidate(tmp_path)
    attempt = store.root / store.attempt_names()[0]
    (attempt / "unexpected-residue").write_bytes(b"bounded-debt")
    with pytest.raises(OSError):
        candidate.cleanup()
    target = candidate.defer_cleanup()
    journal = PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl")
    status = journal.append_pending(
        target,
        rejection_code="package_archive_malformed",
        rejection_stage="inspecting",
    )
    return journal, status, store, attempt


def test_cleanup_tombstone_is_pathless_append_once_and_exactly_repairable(
    tmp_path: Path,
) -> None:
    journal, pending, store, _attempt = _pending(tmp_path)

    assert pending.disposition == "cleanup_retryable"
    assert pending.failure is not None
    assert pending.failure.code == "package_quarantine_cleanup_retryable"
    assert pending.failure.retry_domain == "cleanup"
    assert pending.failure.subject_id == pending.target.cleanup_id
    assert str(store.root) not in str(pending.to_dict())
    assert "path" not in str(pending.target.to_dict()).lower()
    assert (
        PackageQuarantineCleanupTargetV1.from_dict(pending.target.to_dict())
        == pending.target
    )
    assert PackageQuarantineCleanupStatusV1.from_dict(pending.to_dict()) == pending
    record_count = len(journal.records())
    assert (
        journal.append_pending(
            pending.target,
            rejection_code="package_archive_malformed",
            rejection_stage="inspecting",
        )
        == pending
    )
    assert len(journal.records()) == record_count

    completed = journal.repair(
        pending.target.cleanup_id,
        expected_cleanup_revision=pending.cleanup_revision,
        store=store,
    )

    assert completed.disposition == "cleanup_complete"
    assert completed.failure is None
    assert store.attempt_names() == ()
    assert (
        journal.repair(
            pending.target.cleanup_id,
            expected_cleanup_revision=pending.cleanup_revision,
            store=store,
        )
        == completed
    )
    assert len(journal.records()) == 2


def test_cleanup_repair_refuses_replaced_attempt_and_preserves_tombstone(
    tmp_path: Path,
) -> None:
    journal, pending, store, attempt = _pending(tmp_path)
    displaced = store.root / "displaced-owner-attempt"
    attempt.rename(displaced)
    attempt.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_bytes(b"must-survive")

    with pytest.raises(OSError, match="identity changed"):
        journal.repair(
            pending.target.cleanup_id,
            expected_cleanup_revision=pending.cleanup_revision,
            store=store,
        )

    assert outside.read_bytes() == b"must-survive"
    assert journal.status(pending.target.cleanup_id) == pending
    assert len(journal.records()) == 1
    attempt.rmdir()
    displaced.rename(attempt)
    completed = journal.repair(
        pending.target.cleanup_id,
        expected_cleanup_revision=pending.cleanup_revision,
        store=store,
    )
    assert completed.disposition == "cleanup_complete"
    assert store.attempt_names() == ()


def test_cleanup_repair_adopts_delete_completed_before_journal_append(
    tmp_path: Path,
) -> None:
    journal, pending, store, _attempt = _pending(tmp_path)

    store._repair(pending.target)
    assert store.attempt_names() == ()
    assert journal.status(pending.target.cleanup_id) == pending

    completed = journal.repair(
        pending.target.cleanup_id,
        expected_cleanup_revision=pending.cleanup_revision,
        store=store,
    )

    assert completed.disposition == "cleanup_complete"
    assert len(journal.records()) == 2
