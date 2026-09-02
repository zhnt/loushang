from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Lock

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyAdoptionFailureV1,
    PackageLegacyAdoptionOwner,
    PackageLegacyAdoptionReceiptV1,
    PackageLegacyAdoptionRequestV1,
    PackageLegacyAdoptionResultV1,
    PackageLegacyAdoptionTransactionResultV1,
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitLifecycleOwner,
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    DependencyClosureLockV2,
    PluginRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)

STORE_ID = "package-store:adoption"
LEGACY_ROOT_ID = "1" * 64
CURRENT_ROOT_ID = "2" * 64
STATE_DIGEST = "3" * 64
ENVIRONMENT_DIGEST = "4" * 64
ROOT_ARTIFACT_DIGEST = "5" * 64
ROOT_TREE_DIGEST = "6" * 64


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
                    present=kind == "existing_plugin_history",
                    authority_id=f"authority:{kind}",
                    owner_revision=f"revision:{kind}:1",
                )
                for kind in kinds
            ),
            policy_revision="classification-policy:1",
            classifier_epoch=1,
        )


@dataclass
class _Fences:
    receipts: tuple[PackageEpochFenceReceiptV1 | None, ...]
    calls: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)

    def current(self, _store_id: str) -> PackageEpochFenceReceiptV1 | None:
        with self.lock:
            index = min(self.calls, len(self.receipts) - 1)
            self.calls += 1
            return self.receipts[index]


@dataclass
class _LegacyState:
    evidence: tuple[PackageLegacyStateEvidenceV1, ...]
    calls: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)

    def observe(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
    ) -> PackageLegacyStateEvidenceV1:
        assert store_id == STORE_ID
        assert legacy_root_identity == LEGACY_ROOT_ID
        with self.lock:
            index = min(self.calls, len(self.evidence) - 1)
            self.calls += 1
            return self.evidence[index]


@dataclass
class _Transaction:
    result: PackageLegacyAdoptionTransactionResultV1
    calls: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)

    def adopt(
        self,
        _request: PackageLegacyAdoptionRequestV1,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        with self.lock:
            self.calls += 1
            return self.result


@dataclass(frozen=True)
class _Fixture:
    fence: PackageEpochFenceReceiptV1
    legacy: PackageLegacyStateEvidenceV1
    request: PackageLegacyAdoptionRequestV1
    committed: PackageLifecycleStatusV1
    publication: PackagePublicationReceiptV1


def _fence(
    *,
    current_root_identity: str = CURRENT_ROOT_ID,
    legacy_root_identity: str = LEGACY_ROOT_ID,
) -> PackageEpochFenceReceiptV1:
    return PackageEpochFenceReceiptV1.create(
        PackageEpochFenceRequestV1.create(
            store_id=STORE_ID,
            prior_fence=None,
            legacy_root_identity=legacy_root_identity,
            fenced_root_identity=current_root_identity,
            namespace_id="7" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id="8" * 64,
            snapshot_receipt_id="9" * 64,
            root_switch_receipt_id="a" * 64,
        )
    )


def _publication(tmp_path: Path) -> tuple[PackageLifecycleStatusV1, PackagePublicationReceiptV1]:
    lifecycle_journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=_Authority(),
        enabled=True,
    )
    status = kernel.submit(
        PackageLifecycleIngressRequestV1(
            operation_id="adoption-operation",
            action="install",
            product_id="coding",
            scope_id="workspace:adoption",
            requested_package="acme-plugin==1.0",
            requested_plugin_id="acme.plugin",
            source_locator="https://packages.example.test/acme.whl",
            policy_revision="package-policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=ENVIRONMENT_DIGEST,
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
    node = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="acme-plugin",
        version="1.0",
        canonical_source_identity="https://packages.example.test/acme.whl",
        source_envelope_fingerprint="b" * 64,
        acquisition_receipt_fingerprint="c" * 64,
        wheel_evidence_fingerprint="d" * 64,
        artifact_digest=ROOT_ARTIFACT_DIGEST,
        extraction_tree_digest=ROOT_TREE_DIGEST,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    plan = VerifiedClosurePlanV2.create(
        operation_id=status.operation_id,
        attempt_epoch=status.attempt_epoch,
        root_node_id=node.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_DIGEST,
        nodes=(node,),
        max_depth=0,
    )
    pin_request = PackageTransactionPinRequestV1.create(
        plan,
        request_fingerprint=status.request_fingerprint,
        classification_fingerprint=status.classification.evidence_ref,
        recovery_identity="legacy-adoption-recovery",
    )
    pin = PackageTransactionPinReceiptV1.acquire(
        pin_request,
        pin_id="e" * 64,
        owner_identity="adoption-retention-owner",
        owner_revision=1,
        lease_id="adoption-lease",
        lease_revision=1,
    )
    pin_journal = PackageTransactionPinJournal(tmp_path / "pins.jsonl")
    pin_journal.append(pin)
    root_ref = PluginRevisionRefV1.create(
        store_identity="plugin-revision-store",
        store_revision="plugin-revision:adoption",
        installation_id="installation-adoption",
        plugin_id="acme.plugin",
        distribution=node.distribution,
        version=node.version,
        artifact_digest=node.artifact_digest,
        extraction_tree_digest=node.extraction_tree_digest,
    )
    closure_lock = DependencyClosureLockV2.create(
        plan,
        stable_refs={node.node_id: root_ref},
    )
    committed_sets = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")
    committed_sets.publish(
        closure_lock,
        request_fingerprint=status.request_fingerprint,
        product_id="coding",
        scope_id="workspace:adoption",
        installation_id="installation-adoption",
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
    publication = PackageCommitLifecycleOwner(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    ).commit(status.operation_id)
    committed = kernel.status(status.operation_id)
    assert committed is not None
    return committed, publication


def _fixture(tmp_path: Path) -> _Fixture:
    fence = _fence()
    legacy = PackageLegacyStateEvidenceV1.create(
        store_id=STORE_ID,
        legacy_root_identity=LEGACY_ROOT_ID,
        state_digest=STATE_DIGEST,
        entry_count=9,
        byte_count=4096,
    )
    committed, publication = _publication(tmp_path)
    request = PackageLegacyAdoptionRequestV1.create(
        current_fence=fence,
        legacy_state=legacy,
        operation_id=publication.operation_id,
        transaction_request_fingerprint=publication.request_fingerprint,
        expected_classification_fingerprint=publication.classification_fingerprint,
        expected_attempt_epoch=publication.attempt_epoch,
        product_id=publication.product_id,
        scope_id=publication.scope_id,
        installation_id=publication.installation_id,
        plugin_id=publication.plugin_id,
    )
    return _Fixture(
        fence=fence,
        legacy=legacy,
        request=request,
        committed=committed,
        publication=publication,
    )


def _transaction_result(
    fixture: _Fixture,
    *,
    status: PackageLifecycleStatusV1 | None = None,
    adoption_request_id: str | None = None,
) -> PackageLegacyAdoptionTransactionResultV1:
    selected = fixture.committed if status is None else status
    return PackageLegacyAdoptionTransactionResultV1(
        adoption_request_id=adoption_request_id or fixture.request.request_id,
        status=selected,
        publication=(fixture.publication if selected.disposition == "committed" else None),
    )


def _owner(
    fixture: _Fixture,
    *,
    fences: _Fences | None = None,
    legacy: _LegacyState | None = None,
    transaction: _Transaction | None = None,
) -> tuple[PackageLegacyAdoptionOwner, _Fences, _LegacyState, _Transaction]:
    fence_owner = fences or _Fences((fixture.fence,))
    legacy_owner = legacy or _LegacyState((fixture.legacy,))
    transaction_owner = transaction or _Transaction(_transaction_result(fixture))
    return (
        PackageLegacyAdoptionOwner(
            store_id=STORE_ID,
            fences=fence_owner,
            legacy_state=legacy_owner,
            transaction=transaction_owner,
        ),
        fence_owner,
        legacy_owner,
        transaction_owner,
    )


def _failed_status(
    fixture: _Fixture,
    *,
    code: str,
    retryable: bool,
) -> PackageLifecycleStatusV1:
    details = ("condition:no_acquired_digest",) if retryable and code == "package_operation_timed_out" else ()
    failure = PackageLifecycleFailureV1.for_operation(
        code,
        stage="acquiring",
        operation_id=fixture.request.operation_id,
        evidence_ref=fixture.request.transaction_request_fingerprint,
        details=details,
    )
    return replace(
        fixture.committed,
        phase="acquiring",
        disposition="retryable_failure" if retryable else "rejected",
        failure=failure,
    )


def test_adoption_protocol_replays_exact_committed_receipt_without_legacy_mutation(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    owner, fences, legacy, transaction = _owner(fixture)

    result = owner.adopt(fixture.request)
    replay = owner.adopt(fixture.request)

    assert replay == result
    assert result.disposition == "adopted"
    assert result.code == "ok"
    assert result.receipt is not None
    assert result.receipt.publication == fixture.publication
    assert result.receipt.publication.transaction_pin_receipt_id
    assert result.receipt.matches(fixture.request)
    assert fences.calls == 4
    assert legacy.calls == 4
    assert transaction.calls == 2
    assert PackageLegacyStateEvidenceV1.from_dict(fixture.legacy.to_dict()) == fixture.legacy
    assert PackageLegacyAdoptionRequestV1.from_dict(fixture.request.to_dict()) == fixture.request
    assert PackageLegacyAdoptionTransactionResultV1.from_dict(
        _transaction_result(fixture).to_dict()
    ) == _transaction_result(fixture)
    assert PackageLegacyAdoptionReceiptV1.from_dict(
        result.receipt.to_dict()
    ) == result.receipt
    assert PackageLegacyAdoptionResultV1.from_dict(result.to_dict()) == result
    serialized = repr(result).lower()
    for forbidden in ("path", "handle", "credential", "password", "token"):
        assert forbidden not in serialized


def test_adoption_protocol_rejects_stale_fence_before_legacy_or_transaction(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    owner, fences, legacy, transaction = _owner(
        fixture,
        fences=_Fences((_fence(current_root_identity="f" * 64),)),
    )

    result = owner.adopt(fixture.request)

    assert result.disposition == "rejected"
    assert result.code == "package_runtime_epoch_unsupported"
    assert fences.calls == 1
    assert legacy.calls == 0
    assert transaction.calls == 0


def test_adoption_request_rejects_legacy_root_outside_current_fence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(ValueError, match="authority changed"):
        PackageLegacyAdoptionRequestV1.create(
            current_fence=_fence(legacy_root_identity="f" * 64),
            legacy_state=fixture.legacy,
            operation_id=fixture.publication.operation_id,
            transaction_request_fingerprint=(
                fixture.publication.request_fingerprint
            ),
            expected_classification_fingerprint=(
                fixture.publication.classification_fingerprint
            ),
            expected_attempt_epoch=fixture.publication.attempt_epoch,
            product_id=fixture.publication.product_id,
            scope_id=fixture.publication.scope_id,
            installation_id=fixture.publication.installation_id,
            plugin_id=fixture.publication.plugin_id,
        )


def test_adoption_protocol_rejects_changed_legacy_before_transaction(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    changed = PackageLegacyStateEvidenceV1.create(
        store_id=STORE_ID,
        legacy_root_identity=LEGACY_ROOT_ID,
        state_digest="f" * 64,
        entry_count=fixture.legacy.entry_count,
        byte_count=fixture.legacy.byte_count,
    )
    owner, _fences, legacy, transaction = _owner(
        fixture,
        legacy=_LegacyState((changed,)),
    )

    result = owner.adopt(fixture.request)

    assert result.code == "package_operation_identity_conflict"
    assert legacy.calls == 1
    assert transaction.calls == 0


def test_adoption_protocol_rejects_changed_classification_evidence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    request = PackageLegacyAdoptionRequestV1.create(
        current_fence=fixture.fence,
        legacy_state=fixture.legacy,
        operation_id=fixture.publication.operation_id,
        transaction_request_fingerprint=fixture.publication.request_fingerprint,
        expected_classification_fingerprint="f" * 64,
        expected_attempt_epoch=fixture.publication.attempt_epoch,
        product_id=fixture.publication.product_id,
        scope_id=fixture.publication.scope_id,
        installation_id=fixture.publication.installation_id,
        plugin_id=fixture.publication.plugin_id,
    )
    transaction = _Transaction(
        PackageLegacyAdoptionTransactionResultV1(
            adoption_request_id=request.request_id,
            status=fixture.committed,
            publication=fixture.publication,
        )
    )
    owner, fences, legacy, transaction = _owner(
        fixture,
        transaction=transaction,
    )

    result = owner.adopt(request)

    assert result.code == "package_operation_identity_conflict"
    assert fences.calls == 2
    assert legacy.calls == 2
    assert transaction.calls == 1


def test_adoption_protocol_rejects_legacy_drift_after_transaction(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    changed = PackageLegacyStateEvidenceV1.create(
        store_id=STORE_ID,
        legacy_root_identity=LEGACY_ROOT_ID,
        state_digest="f" * 64,
        entry_count=9,
        byte_count=4096,
    )
    owner, fences, legacy, transaction = _owner(
        fixture,
        legacy=_LegacyState((fixture.legacy, changed)),
    )

    result = owner.adopt(fixture.request)

    assert result.code == "package_operation_identity_conflict"
    assert fences.calls == 1
    assert legacy.calls == 2
    assert transaction.calls == 1


def test_adoption_protocol_rejects_fence_drift_after_transaction(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    owner, fences, legacy, transaction = _owner(
        fixture,
        fences=_Fences(
            (fixture.fence, _fence(current_root_identity="f" * 64)),
        ),
    )

    result = owner.adopt(fixture.request)

    assert result.code == "package_runtime_epoch_unsupported"
    assert fences.calls == 2
    assert legacy.calls == 2
    assert transaction.calls == 1


@pytest.mark.parametrize(
    ("code", "retryable", "disposition"),
    (
        ("package_source_unauthorized", False, "rejected"),
        ("package_operation_timed_out", True, "retryable_failure"),
        ("package_operation_interrupted", True, "retryable_failure"),
    ),
)
def test_adoption_protocol_preserves_transaction_failure_semantics(
    tmp_path: Path,
    code: str,
    retryable: bool,
    disposition: str,
) -> None:
    fixture = _fixture(tmp_path)
    status = _failed_status(fixture, code=code, retryable=retryable)
    owner, _fences, _legacy, _transaction_owner = _owner(
        fixture,
        transaction=_Transaction(_transaction_result(fixture, status=status)),
    )

    result = owner.adopt(fixture.request)

    assert result.disposition == disposition
    assert result.code == code
    assert result.receipt is None
    assert result.failure is not None
    assert result.failure.transaction_failure == status.failure
    assert PackageLegacyAdoptionFailureV1.from_dict(
        result.failure.to_dict()
    ) == result.failure
    assert PackageLegacyAdoptionResultV1.from_dict(result.to_dict()) == result


def test_adoption_protocol_preserves_cancelled_transaction_as_rejection(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    failure = PackageLifecycleFailureV1.for_operation(
        "package_operation_cancelled",
        stage="acquiring",
        operation_id=fixture.request.operation_id,
        evidence_ref=fixture.request.transaction_request_fingerprint,
    )
    cancelled = replace(
        fixture.committed,
        phase="acquiring",
        disposition="cancelled",
        failure=failure,
    )
    owner, _fences, _legacy, _transaction_owner = _owner(
        fixture,
        transaction=_Transaction(_transaction_result(fixture, status=cancelled)),
    )

    result = owner.adopt(fixture.request)

    assert result.disposition == "rejected"
    assert result.code == "package_operation_cancelled"
    assert result.failure is not None
    assert result.failure.transaction_failure == failure


def test_adoption_protocol_rejects_cross_request_transaction_result(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    owner, fences, legacy, transaction = _owner(
        fixture,
        transaction=_Transaction(
            _transaction_result(fixture, adoption_request_id="f" * 64)
        ),
    )

    result = owner.adopt(fixture.request)

    assert result.code == "package_operation_identity_conflict"
    assert fences.calls == 2
    assert legacy.calls == 2
    assert transaction.calls == 1


def test_adoption_protocol_concurrent_replay_converges_to_one_receipt(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    owner, fences, legacy, transaction = _owner(fixture)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(
            executor.map(lambda _index: owner.adopt(fixture.request), range(16))
        )

    assert len(set(results)) == 1
    assert results[0].receipt is not None
    assert fences.calls == 32
    assert legacy.calls == 32
    assert transaction.calls == 16


def test_adoption_protocol_rejects_extended_wire_objects(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    transaction = _transaction_result(fixture)
    adopted = PackageLegacyAdoptionResultV1.adopted(
        fixture.request,
        fixture.publication,
    )
    assert adopted.receipt is not None
    failed_status = _failed_status(
        fixture,
        code="package_source_unauthorized",
        retryable=False,
    )
    failure = PackageLegacyAdoptionFailureV1.from_status(
        fixture.request,
        failed_status,
    )
    rejected = PackageLegacyAdoptionResultV1.rejected(fixture.request, failure)
    records: tuple[
        tuple[Callable[[object], object], dict[str, object]], ...
    ] = (
        (PackageLegacyStateEvidenceV1.from_dict, fixture.legacy.to_dict()),
        (PackageLegacyAdoptionRequestV1.from_dict, fixture.request.to_dict()),
        (PackageLegacyAdoptionTransactionResultV1.from_dict, transaction.to_dict()),
        (PackageLegacyAdoptionReceiptV1.from_dict, adopted.receipt.to_dict()),
        (PackageLegacyAdoptionFailureV1.from_dict, failure.to_dict()),
        (PackageLegacyAdoptionResultV1.from_dict, adopted.to_dict()),
        (PackageLegacyAdoptionResultV1.from_dict, rejected.to_dict()),
    )

    for factory, wire in records:
        with pytest.raises(ValueError, match="versioned schema"):
            factory({**wire, "extra": True})

    forged = fixture.request.to_dict()
    forged["operationId"] = "different-operation"
    with pytest.raises(ValueError, match="does not match"):
        PackageLegacyAdoptionRequestV1.from_dict(forged)
