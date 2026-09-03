from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinJournalError,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
    PackageTransactionPinTargetV1,
)

OPERATION_ID = "operation-transaction-pin"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64
ROOT_ARTIFACT_DIGEST = "6" * 64
ROOT_TREE_DIGEST = "5" * 64
DEPENDENCY_ARTIFACT_DIGEST = "4" * 64
DEPENDENCY_TREE_DIGEST = "3" * 64


def _plan(*, attempt_epoch: int = 1) -> VerifiedClosurePlanV2:
    dependency_source = "https://packages.example.test/dependency.whl"
    dependency = VerifiedClosurePlanNodeV2(
        node_id="dependency-node",
        role="dependency",
        distribution="dependency",
        version="2.0",
        canonical_source_identity=dependency_source,
        source_envelope_fingerprint="1" * 64,
        acquisition_receipt_fingerprint="2" * 64,
        wheel_evidence_fingerprint="3" * 64,
        artifact_digest=DEPENDENCY_ARTIFACT_DIGEST,
        extraction_tree_digest=DEPENDENCY_TREE_DIGEST,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    requirement = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse("dependency==2.0"),
        marker_applies=True,
        selected_node_id=dependency.node_id,
        expected_source_identity=dependency_source,
        expected_artifact_digest=dependency.artifact_digest,
    )
    root = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="root-plugin",
        version="1.0",
        canonical_source_identity="https://packages.example.test/root.whl",
        source_envelope_fingerprint="a" * 64,
        acquisition_receipt_fingerprint="b" * 64,
        wheel_evidence_fingerprint="c" * 64,
        artifact_digest=ROOT_ARTIFACT_DIGEST,
        extraction_tree_digest=ROOT_TREE_DIGEST,
        selected_extras=(),
        requirements=(requirement,),
        selected_edges=(dependency.node_id,),
    )
    return VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=attempt_epoch,
        root_node_id=root.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root, dependency),
        max_depth=1,
    )


def _request(
    *,
    attempt_epoch: int = 1,
    recovery_identity: str = "recovery-transaction-pin",
) -> PackageTransactionPinRequestV1:
    return PackageTransactionPinRequestV1.create(
        _plan(attempt_epoch=attempt_epoch),
        request_fingerprint=REQUEST_FINGERPRINT,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        recovery_identity=recovery_identity,
    )


def _acquired(
    request: PackageTransactionPinRequestV1 | None = None,
) -> PackageTransactionPinReceiptV1:
    return PackageTransactionPinReceiptV1.acquire(
        request or _request(),
        pin_id="f" * 64,
        owner_identity="retention-owner",
        owner_revision=7,
        lease_id="lease-transaction-pin",
        lease_revision=3,
    )


def test_pin_request_derives_exact_canonical_targets_from_verified_plan() -> None:
    request = _request()

    assert PackageTransactionPinRequestV1.from_dict(request.to_dict()) == request
    assert tuple(target.node_id for target in request.targets) == (
        "dependency-node",
        "root",
    )
    assert tuple(target.role for target in request.targets) == (
        "dependency",
        "root",
    )
    assert request.root_target_id == request.targets[1].target_id
    assert request.verified_plan_fingerprint == _plan().fingerprint
    assert request.prepublication_graph_digest == _plan().graph_digest


def test_pin_targets_and_request_carry_no_path_credential_or_live_handle() -> None:
    serialized = repr(_request().to_dict()).lower()

    for forbidden in (
        "credential",
        "password",
        "token",
        "live-handle",
        "pathname",
        "/tmp/",
    ):
        assert forbidden not in serialized


def test_pin_receipt_acquire_release_and_transfer_are_strict_round_trips() -> None:
    acquired = _acquired()
    released = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )
    transferred = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="transferred",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="e" * 64,
    )

    assert PackageTransactionPinReceiptV1.from_dict(acquired.to_dict()) == acquired
    assert PackageTransactionPinReceiptV1.from_dict(released.to_dict()) == released
    assert PackageTransactionPinReceiptV1.from_dict(transferred.to_dict()) == (
        transferred
    )
    assert released.prior_receipt_id == acquired.receipt_id
    assert transferred.pin_request == acquired.pin_request


def test_pin_receipt_rejects_stale_or_chained_terminal_transition() -> None:
    acquired = _acquired()
    released = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )

    with pytest.raises(ValueError, match="owner revision"):
        PackageTransactionPinReceiptV1.transition(
            acquired,
            state="released",
            owner_revision=7,
            lease_revision=4,
            transition_evidence_ref="d" * 64,
        )
    with pytest.raises(ValueError, match="lease revision"):
        PackageTransactionPinReceiptV1.transition(
            acquired,
            state="released",
            owner_revision=8,
            lease_revision=3,
            transition_evidence_ref="d" * 64,
        )
    with pytest.raises(ValueError, match="already terminal"):
        PackageTransactionPinReceiptV1.transition(
            released,
            state="transferred",
            owner_revision=9,
            lease_revision=5,
            transition_evidence_ref="e" * 64,
        )


def test_pin_journal_appends_acquire_then_release_and_replays_after_restart(
    tmp_path: Path,
) -> None:
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    acquired = _acquired()
    released = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )

    assert journal.append(acquired) == acquired
    assert journal.append(acquired) == acquired
    assert (
        journal.current(
            operation_id=OPERATION_ID,
            pin_request_id=acquired.pin_request.pin_request_id,
        )
        == acquired
    )
    assert journal.append(released) == released
    assert journal.append(released) == released
    assert (
        journal.current(
            operation_id=OPERATION_ID,
            pin_request_id=acquired.pin_request.pin_request_id,
        )
        == released
    )

    records = journal.records()
    assert len(records) == 2
    assert records[0].prior_pin_revision == 0
    assert records[1].prior_pin_revision == records[0].record_revision
    assert PackageTransactionPinJournal(journal.path).records() == records


def test_pin_journal_rejects_changed_acquisition_without_mutation(
    tmp_path: Path,
) -> None:
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    acquired = _acquired()
    journal.append(acquired)
    before = journal.records()

    changed = _acquired(_request(recovery_identity="recovery-changed"))
    with pytest.raises(PackageTransactionPinJournalError) as caught:
        journal.append(changed)
    assert caught.value.code == "package_operation_identity_conflict"
    assert journal.records() == before


def test_pin_journal_rejects_release_without_acquire_or_wrong_predecessor(
    tmp_path: Path,
) -> None:
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    acquired = _acquired()
    released = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )

    with pytest.raises(PackageTransactionPinJournalError) as missing:
        journal.append(released)
    assert missing.value.code == "package_operation_phase_conflict"
    assert journal.records() == ()

    journal.append(acquired)
    other_acquired = PackageTransactionPinReceiptV1.acquire(
        acquired.pin_request,
        pin_id=acquired.pin_id,
        owner_identity=acquired.owner_identity,
        owner_revision=6,
        lease_id=acquired.lease_id,
        lease_revision=2,
    )
    wrong_prior = PackageTransactionPinReceiptV1.transition(
        other_acquired,
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )
    with pytest.raises(PackageTransactionPinJournalError) as wrong:
        journal.append(wrong_prior)
    assert wrong.value.code == "package_operation_identity_conflict"


def test_pin_journal_rejects_second_terminal_state_and_attempt_drift(
    tmp_path: Path,
) -> None:
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    acquired = _acquired()
    released = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )
    journal.append(acquired)
    journal.append(released)

    transferred = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="transferred",
        owner_revision=9,
        lease_revision=5,
        transition_evidence_ref="e" * 64,
    )
    with pytest.raises(PackageTransactionPinJournalError) as terminal:
        journal.append(transferred)
    assert terminal.value.code == "package_operation_phase_conflict"

    newer_attempt = _acquired(_request(attempt_epoch=2))
    with pytest.raises(PackageTransactionPinJournalError) as drift:
        journal.append(newer_attempt)
    assert drift.value.code == "package_operation_identity_conflict"


def test_pin_wire_records_reject_forgery_extensions_and_future_versions() -> None:
    target = _request().targets[0]
    target_document = target.to_dict()
    target_document["targetId"] = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        PackageTransactionPinTargetV1.from_dict(target_document)

    request_document = _request().to_dict()
    request_document["pinRequestVersion"] = 2
    with pytest.raises(ValueError, match="Unsupported"):
        PackageTransactionPinRequestV1.from_dict(request_document)

    receipt_document = _acquired().to_dict()
    receipt_document["holderPath"] = "/tmp/forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageTransactionPinReceiptV1.from_dict(receipt_document)


def test_pin_journal_repairs_partial_tail_but_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    journal = PackageTransactionPinJournal(tmp_path / "transaction-pins.jsonl")
    journal.append(_acquired())
    with journal.path.open("ab") as stream:
        stream.write(b'{"recordRevision":')

    assert len(PackageTransactionPinJournal(journal.path).records()) == 1

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"recordRevision":1,"recordRevision":1}\n',
        encoding="utf-8",
    )
    with pytest.raises(PackageTransactionPinJournalError) as corrupt:
        PackageTransactionPinJournal(duplicate).records()
    assert corrupt.value.code == "package_transaction_pin_journal_corrupt"
