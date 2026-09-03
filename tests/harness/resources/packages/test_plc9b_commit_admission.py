from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitAdmissionOwner,
    PackageCommitAdmissionRequestV1,
    PackageCommitAdmissionResultV1,
    PackageCommitEvidenceError,
    PackageCommitLifecycleOwner,
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    DependencyClosureLockV2,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)

REQUEST_FINGERPRINT = "9" * 64
ENVIRONMENT_FINGERPRINT = "8" * 64
ROOT_ARTIFACT_DIGEST = "7" * 64
ROOT_TREE_DIGEST = "6" * 64
DEPENDENCY_ARTIFACT_DIGEST = "5" * 64
DEPENDENCY_TREE_DIGEST = "4" * 64


class _Authority:
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


def _plan(operation_id: str, attempt_epoch: int) -> VerifiedClosurePlanV2:
    dependency = VerifiedClosurePlanNodeV2(
        node_id="dependency-node",
        role="dependency",
        distribution="dependency",
        version="2.0",
        canonical_source_identity="https://packages.example.test/dependency.whl",
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
        expected_source_identity=dependency.canonical_source_identity,
        expected_artifact_digest=dependency.artifact_digest,
    )
    root = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="acme-plugin",
        version="1.0",
        canonical_source_identity="https://packages.example.test/acme.whl",
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
        operation_id=operation_id,
        attempt_epoch=attempt_epoch,
        root_node_id=root.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root, dependency),
        max_depth=1,
    )


def _root_ref(*, store_revision: str = "revision:plugin:1") -> PluginRevisionRefV1:
    return PluginRevisionRefV1.create(
        store_identity="plugin-revision-store",
        store_revision=store_revision,
        installation_id="installation-test",
        plugin_id="acme.plugin",
        distribution="acme-plugin",
        version="1.0",
        artifact_digest=ROOT_ARTIFACT_DIGEST,
        extraction_tree_digest=ROOT_TREE_DIGEST,
    )


def _dependency_ref() -> VerifiedArtifactRefV1:
    return VerifiedArtifactRefV1.create(
        store_identity="dependency-store",
        store_revision="revision:dependency:1",
        distribution="dependency",
        version="2.0",
        artifact_digest=DEPENDENCY_ARTIFACT_DIGEST,
        extraction_tree_digest=DEPENDENCY_TREE_DIGEST,
    )


@dataclass(frozen=True)
class _AdmissionFixture:
    kernel: PackageLifecycleOwner
    committed_sets: PackageCommittedSetJournal
    pin_journal: PackageTransactionPinJournal
    pin_receipt: PackageTransactionPinReceiptV1
    commit_owner: PackageCommitLifecycleOwner
    admission_owner: PackageCommitAdmissionOwner


def _fixture(tmp_path: Path) -> _AdmissionFixture:
    lifecycle_journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=_Authority(),
        enabled=True,
    )
    status = kernel.submit(
        PackageLifecycleIngressRequestV1(
            operation_id="operation-admission",
            action="install",
            product_id="coding",
            scope_id="workspace:test",
            requested_package="acme-plugin==1.0",
            requested_plugin_id="acme.plugin",
            source_locator="https://packages.example.test/acme.whl",
            policy_revision="package-policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        )
    )
    assert status.classification is not None
    for phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
        "transaction_pinned",
        "staging",
    ):
        prior = status.phase
        status = kernel.advance(
            status.operation_id,
            next_phase=phase,  # type: ignore[arg-type]
            expected_phase=prior,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    plan = _plan(status.operation_id, status.attempt_epoch)
    pin_request = PackageTransactionPinRequestV1.create(
        plan,
        request_fingerprint=status.request_fingerprint,
        classification_fingerprint=status.classification.evidence_ref,
        recovery_identity="commit-admission-recovery",
    )
    pin_receipt = PackageTransactionPinReceiptV1.acquire(
        pin_request,
        pin_id="d" * 64,
        owner_identity="retention-owner",
        owner_revision=1,
        lease_id="lease-admission",
        lease_revision=1,
    )
    pin_journal = PackageTransactionPinJournal(tmp_path / "pins.jsonl")
    pin_journal.append(pin_receipt)

    lock = DependencyClosureLockV2.create(
        plan,
        stable_refs={"root": _root_ref(), "dependency-node": _dependency_ref()},
    )
    committed_sets = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")
    committed_sets.publish(
        lock,
        request_fingerprint=status.request_fingerprint,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="acme.plugin",
        classification_fingerprint=status.classification.evidence_ref,
    )
    status = kernel.advance(
        status.operation_id,
        next_phase="set_published",
        expected_phase="staging",
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    assert status.phase == "set_published"

    commit_owner = PackageCommitLifecycleOwner(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    )
    admission_owner = PackageCommitAdmissionOwner(
        lifecycle_journal=lifecycle_journal,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    )
    return _AdmissionFixture(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
        pin_receipt=pin_receipt,
        commit_owner=commit_owner,
        admission_owner=admission_owner,
    )


def _request_from_receipt(
    receipt: PackagePublicationReceiptV1,
    **changes: object,
) -> PackageCommitAdmissionRequestV1:
    values: dict[str, object] = {
        "operation_id": receipt.operation_id,
        "request_fingerprint": receipt.request_fingerprint,
        "product_id": receipt.product_id,
        "scope_id": receipt.scope_id,
        "installation_id": receipt.installation_id,
        "plugin_id": receipt.plugin_id,
        "claimed_root_ref": receipt.committed_set.root_ref,
        "committed_set_id": receipt.committed_set.set_id,
        "closure_lock_digest": receipt.committed_set.closure_lock_digest,
        "publication_receipt": receipt,
    }
    values.update(changes)
    return PackageCommitAdmissionRequestV1.create(**values)  # type: ignore[arg-type]


def test_commit_owner_durably_closes_set_and_reconstructs_exact_receipt(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    receipt = fixture.commit_owner.commit("operation-admission")
    journal_size = len(fixture.kernel.journal.records())
    replay = PackageCommitLifecycleOwner(
        kernel=fixture.kernel,
        committed_sets=PackageCommittedSetJournal(fixture.committed_sets.path),
        pin_journal=PackageTransactionPinJournal(fixture.pin_journal.path),
    ).commit("operation-admission")

    assert replay == receipt
    assert len(fixture.kernel.journal.records()) == journal_size
    assert fixture.kernel.status("operation-admission").disposition == "committed"  # type: ignore[union-attr]
    assert PackagePublicationReceiptV1.from_dict(receipt.to_dict()) == receipt
    assert receipt.transaction_pin_receipt_id == fixture.pin_receipt.receipt_id


def test_exact_committed_root_is_admitted_without_store_or_state_capability(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    receipt = fixture.commit_owner.commit("operation-admission")
    lifecycle_before = fixture.kernel.journal.records()
    sets_before = fixture.committed_sets.records()
    pins_before = fixture.pin_journal.records()

    request = _request_from_receipt(receipt)
    assert PackageCommitAdmissionRequestV1.from_dict(request.to_dict()) == request

    result = fixture.admission_owner.admit(request)

    assert result.code == "ok"
    assert result.disposition == "admitted"
    assert result.receipt is not None
    assert result.receipt.root_ref == receipt.committed_set.root_ref
    assert PackageCommitAdmissionResultV1.from_dict(result.to_dict()) == result
    assert fixture.kernel.journal.records() == lifecycle_before
    assert fixture.committed_sets.records() == sets_before
    assert fixture.pin_journal.records() == pins_before
    serialized = repr(result.to_dict()).lower()
    for forbidden in ("path", "handle", "credential", "password", "token"):
        assert forbidden not in serialized


def test_concurrent_exact_commit_converges_to_one_terminal_receipt(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = tuple(
            pool.map(
                lambda _index: fixture.commit_owner.commit("operation-admission"),
                range(16),
            )
        )

    assert len(set(receipts)) == 1
    assert fixture.kernel.status("operation-admission").disposition == "committed"  # type: ignore[union-attr]
    assert len(fixture.kernel.journal.records()) == 12


def test_commit_refuses_terminal_pin_before_cas_without_partial_commit(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    released = PackageTransactionPinReceiptV1.transition(
        fixture.pin_receipt,
        state="released",
        owner_revision=2,
        lease_revision=2,
        transition_evidence_ref="e" * 64,
    )
    fixture.pin_journal.append(released)
    before = fixture.kernel.journal.records()

    with pytest.raises(PackageCommitEvidenceError) as caught:
        fixture.commit_owner.commit("operation-admission")

    assert caught.value.code == "package_operation_identity_conflict"
    assert fixture.kernel.journal.records() == before
    assert fixture.kernel.status("operation-admission").phase == "set_published"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("case_id", "changes"),
    [
        ("dependency-as-root", {"claimed_root_ref": _dependency_ref()}),
        (
            "wrong-set",
            {"committed_set_id": "0" * 64, "claimed_root_ref": _root_ref(store_revision="revision:plugin:2")},
        ),
        ("wrong-request", {"request_fingerprint": "0" * 64}),
        ("wrong-operation", {"operation_id": "operation-other"}),
        ("wrong-scope", {"scope_id": "workspace:other"}),
        ("wrong-plugin", {"plugin_id": "other.plugin"}),
        ("digest-tamper", {"closure_lock_digest": "0" * 64}),
    ],
)
def test_commit_admission_rejects_cross_context_claims_without_any_mutation(
    tmp_path: Path,
    case_id: str,
    changes: dict[str, object],
) -> None:
    fixture = _fixture(tmp_path)
    receipt = fixture.commit_owner.commit("operation-admission")
    lifecycle_before = fixture.kernel.journal.records()
    sets_before = fixture.committed_sets.records()
    pins_before = fixture.pin_journal.records()

    result = fixture.admission_owner.admit(
        _request_from_receipt(receipt, **changes)
    )

    assert result.code == "package_commit_admission_denied", case_id
    assert result.disposition == "rejected"
    assert result.receipt is None
    assert result.failure is not None
    assert fixture.kernel.journal.records() == lifecycle_before
    assert fixture.committed_sets.records() == sets_before
    assert fixture.pin_journal.records() == pins_before


def test_stable_ref_without_durable_commit_receipt_is_never_admitted(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    record = fixture.committed_sets.current("operation-admission")
    status = fixture.kernel.status("operation-admission")
    assert record is not None
    assert status is not None and status.phase == "set_published"
    request = PackageCommitAdmissionRequestV1.create(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="acme.plugin",
        claimed_root_ref=record.committed_set.root_ref,
        committed_set_id=record.committed_set.set_id,
        closure_lock_digest=record.closure_lock.lock_digest,
        publication_receipt=None,
    )
    lifecycle_before = fixture.kernel.journal.records()

    result = fixture.admission_owner.admit(request)

    assert result.code == "package_commit_admission_denied"
    assert result.disposition == "rejected"
    assert result.receipt is None
    assert PackageCommitAdmissionResultV1.from_dict(result.to_dict()) == result
    assert fixture.kernel.journal.records() == lifecycle_before
    assert fixture.pin_journal.current_for_operation(status.operation_id).state == "acquired"  # type: ignore[union-attr]


def test_admission_fails_closed_after_transaction_pin_is_no_longer_live(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    receipt = fixture.commit_owner.commit("operation-admission")
    released = PackageTransactionPinReceiptV1.transition(
        fixture.pin_receipt,
        state="released",
        owner_revision=2,
        lease_revision=2,
        transition_evidence_ref="e" * 64,
    )
    fixture.pin_journal.append(released)

    result = fixture.admission_owner.admit(_request_from_receipt(receipt))

    assert result.code == "package_commit_admission_denied"
    assert result.receipt is None


def test_admission_records_reject_extensions_and_forged_fingerprints(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    receipt = fixture.commit_owner.commit("operation-admission")
    request = _request_from_receipt(receipt)

    forged_receipt = receipt.to_dict()
    forged_receipt["receiptId"] = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        PackagePublicationReceiptV1.from_dict(forged_receipt)

    extended = request.to_dict()
    extended["reopenPath"] = "/tmp/forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageCommitAdmissionRequestV1.from_dict(extended)
