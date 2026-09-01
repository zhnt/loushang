from __future__ import annotations

import base64
import csv
import io
import os
import stat
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AcquiredPackageCandidate,
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageAuthenticatedSourceEvidenceV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV1,
    PluginBoundPackageClassificationV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
    PackageArtifactLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)

WHEEL_FILENAME = "acme_plugin-1.0-py3-none-any.whl"


class _ClassificationAuthority:
    def classification_facts(
        self, _request: PackageLifecycleIngressRequestV1
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
class _Recheck:
    changed: bool = False

    def recheck(
        self,
        _request: PackageLifecycleRequestV1,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1:
        if not self.changed:
            return prior
        return PluginBoundPackageClassificationV1(
            decision="indeterminate",
            request_fingerprint=prior.request_fingerprint,
            basis_facts=prior.basis_facts,
            policy_revision=prior.policy_revision,
            classifier_epoch=prior.classifier_epoch,
            canonical_source_identity=prior.canonical_source_identity,
        )


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    payload: bytes
    store: PackageQuarantineStore | None = None
    inject_residue: bool = False

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        if self.inject_residue:
            assert self.store is not None
            attempt = self.store.root / self.store.attempt_names()[0]
            (attempt / "acquisition-cleanup-debt").write_bytes(b"bounded")
        sink.write(self.payload)
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _SourceAuthority:
    payload: bytes
    denied: bool = False
    store: PackageQuarantineStore | None = None
    inject_residue: bool = False

    def authorize(self, request: PackageAcquisitionRequestV1) -> _Stream:
        if self.denied:
            raise PackageAcquisitionError(
                "private registry detail must not escape",
                code="package_source_unauthorized",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            )
        return _Stream(
            envelope=AuthenticatedSourceEnvelopeV1(
                operation_id=request.operation_id,
                node_id=request.node_id,
                canonical_source_identity=request.canonical_source_identity,
                origin_kind="https",
                authentication_decision="authorized",
                authority_id="source-authority:test",
                requested_locator_digest=request.requested_locator_digest,
                expected_artifact_digest=sha256(self.payload).hexdigest(),
                redirect_policy_revision="redirect-policy:1",
                policy_revision=request.policy_revision,
                capture_epoch=1,
            ),
            payload=self.payload,
            store=self.store,
            inject_residue=self.inject_residue,
        )


class _ResidueWheelVerifier(PackageWheelVerifier):
    def __init__(self, store: PackageQuarantineStore) -> None:
        super().__init__()
        self._store = store

    def verify(
        self,
        candidate: AcquiredPackageCandidate,
        *,
        wheel_filename: str,
        supported_tags: frozenset[str],
        budgets: PackageInspectionBudgetV1,
    ) -> VerifiedWheelCandidate:
        attempt = self._store.root / self._store.attempt_names()[0]
        (attempt / "injected-cleanup-debt").write_bytes(b"bounded")
        return super().verify(
            candidate,
            wheel_filename=wheel_filename,
            supported_tags=supported_tags,
            budgets=budgets,
        )


def _wheel_bytes() -> bytes:
    dist_info = "acme_plugin-1.0.dist-info"
    files = {
        "acme_plugin/__init__.py": b"VALUE = 1\n",
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
        f"{dist_info}/METADATA": (
            b"Metadata-Version: 2.1\nName: acme-plugin\nVersion: 1.0\n\n"
        ),
    }
    rows = []
    for name, payload in files.items():
        digest = base64.urlsafe_b64encode(sha256(payload).digest()).rstrip(b"=")
        rows.append((name, "sha256=" + digest.decode(), str(len(payload))))
    rows.append((f"{dist_info}/RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def _ingress(secret: str = "secret-token") -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id="artifact-operation",
        action="install",
        product_id="coding",
        scope_id="workspace:artifact",
        requested_package="acme-plugin==1.0",
        requested_plugin_id="acme.plugin",
        source_locator=(
            f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
            f"?token={secret}#{secret}"
        ),
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint="e" * 64,
    )


def _owners(
    tmp_path: Path,
    *,
    payload: bytes,
    denied: bool = False,
    max_transport_bytes: int = 128 * 1024,
    recheck: _Recheck | None = None,
    residue_on_rejection: bool = False,
    residue_during_acquisition: bool = False,
):
    lifecycle_journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    store = PackageQuarantineStore(tmp_path / "quarantine")
    evidence = PackageArtifactEvidenceJournal(tmp_path / "evidence.jsonl")
    cleanup = PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl")
    cleanup_owner = PackageQuarantineCleanupOwner(journal=cleanup, store=store)
    artifact_owner = PackageArtifactLifecycleOwner(
        kernel=kernel,
        classification_recheck=recheck or _Recheck(),
        acquisition_owner=PackageAcquisitionOwner(
            source_authority=_SourceAuthority(
                payload=payload,
                denied=denied,
                store=store,
                inject_residue=residue_during_acquisition,
            ),
            quarantine_store=store,
        ),
        evidence_journal=evidence,
        cleanup_owner=cleanup_owner,
        wheel_verifier=(
            _ResidueWheelVerifier(store)
            if residue_on_rejection
            else PackageWheelVerifier()
        ),
        acquisition_budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=max_transport_bytes,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
        inspection_budgets=PackageInspectionBudgetV1(),
        supported_tags=frozenset({"py3-none-any"}),
    )
    return kernel, artifact_owner, lifecycle_journal, evidence, cleanup_owner, store


def _execute_request(status, secret: str = "credential-ref-secret"):
    return PackageArtifactExecutionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_attempt_epoch=status.attempt_epoch,
        wheel_filename=WHEEL_FILENAME,
        credential_reference=secret,
    )


def _land_source_evidence_without_acquisition(
    kernel: PackageLifecycleOwner,
    owner: PackageArtifactLifecycleOwner,
    evidence: PackageArtifactEvidenceJournal,
):
    classified = kernel.submit(_ingress())
    acquiring = kernel.advance(
        classified.operation_id,
        next_phase="acquiring",
        expected_phase="classified",
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    request = kernel.journal.request(acquiring.operation_id)
    assert request is not None
    acquisition_request = PackageAcquisitionRequestV1(
        operation_id=request.operation_id,
        attempt_epoch=acquiring.attempt_epoch,
        node_id="root",
        canonical_source_identity=request.canonical_source_identity,
        request_fingerprint=request.request_fingerprint,
        requested_locator_digest=sha256(
            request.canonical_source_identity.encode("utf-8")
        ).hexdigest(),
        policy_revision=request.policy_revision,
    )
    authorized = owner._acquisition_owner.authorize_source(acquisition_request)
    evidence.append(
        request_fingerprint=request.request_fingerprint,
        evidence=PackageAuthenticatedSourceEvidenceV1(
            attempt_epoch=acquiring.attempt_epoch,
            envelope=authorized.envelope,
        ),
    )
    return acquiring, acquisition_request, authorized


def _land_acquired_evidence_without_phase_advance(
    kernel: PackageLifecycleOwner,
    owner: PackageArtifactLifecycleOwner,
    evidence: PackageArtifactEvidenceJournal,
):
    acquiring, acquisition_request, authorized = (
        _land_source_evidence_without_acquisition(kernel, owner, evidence)
    )
    request = kernel.journal.request(acquiring.operation_id)
    assert request is not None
    candidate = owner._acquisition_owner.acquire_authorized(
        acquisition_request,
        authorized,
        budgets=owner._acquisition_budgets,
    )
    evidence.append(
        request_fingerprint=request.request_fingerprint,
        evidence=candidate.receipt,
    )
    return acquiring, candidate


def test_dark_artifact_owner_journals_exact_phases_and_typed_evidence(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes()
    kernel, owner, journal, evidence, _cleanup, store = _owners(
        tmp_path, payload=payload
    )
    classified = kernel.submit(_ingress())

    result = owner.execute(_execute_request(classified))

    assert result.status.phase == "extracted"
    assert result.status.disposition == "active"
    assert result.candidate is not None
    assert [record.status.phase for record in journal.records()] == [
        "accepted",
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
    ]
    assert [record.evidence_kind for record in evidence.records()] == [
        "authenticated_source",
        "bounded_acquisition",
        "verified_wheel",
    ]
    assert result.candidate.evidence.artifact_digest == sha256(payload).hexdigest()
    result.candidate.cleanup()
    assert store.attempt_names() == ()


def test_acquired_evidence_is_adopted_without_reauthorizing_source(
    tmp_path: Path,
) -> None:
    kernel, owner, journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, candidate = _land_acquired_evidence_without_phase_advance(
        kernel,
        owner,
        evidence,
    )
    candidate.suspend_for_recovery()
    owner._acquisition_owner._source_authority.denied = True

    recovered = owner.execute(_execute_request(acquiring))

    assert recovered.status.phase == "extracted"
    assert recovered.candidate is not None
    assert [record.status.phase for record in journal.records()] == [
        "accepted",
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
    ]
    assert len(evidence.records()) == 3
    recovered.candidate.cleanup()
    assert store.attempt_names() == ()


def test_source_evidence_reauthorizes_exactly_before_first_byte_transfer(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, _request, _authorized = _land_source_evidence_without_acquisition(
        kernel,
        owner,
        evidence,
    )

    recovered = owner.execute(_execute_request(acquiring))

    assert recovered.status.phase == "extracted"
    assert recovered.candidate is not None
    assert [record.evidence_kind for record in evidence.records()] == [
        "authenticated_source",
        "bounded_acquisition",
        "verified_wheel",
    ]
    recovered.candidate.cleanup()
    assert store.attempt_names() == ()


def test_source_evidence_replay_rejects_changed_authority_before_quarantine(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, _request, _authorized = _land_source_evidence_without_acquisition(
        kernel,
        owner,
        evidence,
    )
    owner._acquisition_owner._source_authority.payload = b"changed-after-capture"

    rejected = owner.execute(_execute_request(acquiring))

    assert rejected.status.phase == "acquiring"
    assert rejected.status.disposition == "rejected"
    assert rejected.status.failure is not None
    assert rejected.status.failure.code == "package_source_provenance_changed"
    assert [record.evidence_kind for record in evidence.records()] == [
        "authenticated_source"
    ]
    assert store.attempt_names() == ()


def test_verified_evidence_is_reverified_and_adopted_without_source_access(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, candidate = _land_acquired_evidence_without_phase_advance(
        kernel,
        owner,
        evidence,
    )
    acquired = kernel.advance(
        acquiring.operation_id,
        next_phase="acquired",
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )
    inspecting = kernel.advance(
        acquired.operation_id,
        next_phase="inspecting",
        expected_phase="acquired",
        expected_journal_revision=acquired.journal_revision,
        expected_attempt_epoch=acquired.attempt_epoch,
    )
    verified = owner._wheel_verifier.verify(
        candidate,
        wheel_filename=WHEEL_FILENAME,
        supported_tags=owner._supported_tags,
        budgets=owner._inspection_budgets,
    )
    evidence.append(
        request_fingerprint=inspecting.request_fingerprint,
        evidence=verified.evidence,
    )
    durable_evidence = verified.evidence
    verified.suspend_for_recovery()
    owner._acquisition_owner._source_authority.denied = True

    recovered = owner.execute(_execute_request(inspecting))

    assert recovered.status.phase == "extracted"
    assert recovered.candidate is not None
    assert recovered.candidate.evidence == durable_evidence
    assert len(evidence.records()) == 3
    recovered.candidate.cleanup()
    assert store.attempt_names() == ()


def test_partial_extraction_is_removed_root_relatively_before_local_reverify(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, candidate = _land_acquired_evidence_without_phase_advance(
        kernel,
        owner,
        evidence,
    )
    acquired = kernel.advance(
        acquiring.operation_id,
        next_phase="acquired",
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )
    inspecting = kernel.advance(
        acquired.operation_id,
        next_phase="inspecting",
        expected_phase="acquired",
        expected_journal_revision=acquired.journal_revision,
        expected_attempt_epoch=acquired.attempt_epoch,
    )
    writer = candidate._attempt._begin_extraction()
    partial = writer._open_file(("partial", "entry"))
    partial.write(b"interrupted")
    partial.close()
    writer._abort()
    candidate.suspend_for_recovery()
    owner._acquisition_owner._source_authority.denied = True

    recovered = owner.execute(_execute_request(inspecting))

    assert recovered.status.phase == "extracted"
    assert recovered.candidate is not None
    assert len(evidence.records()) == 3
    recovered.candidate.cleanup()
    assert store.attempt_names() == ()


def test_recovery_tree_swap_records_cleanup_debt_without_traversing_outside(
    tmp_path: Path,
) -> None:
    if os.name != "posix":
        pytest.skip("native Windows reparse recovery is a later PLC9B2 gate")
    kernel, owner, _journal, evidence, cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, candidate = _land_acquired_evidence_without_phase_advance(
        kernel,
        owner,
        evidence,
    )
    acquired = kernel.advance(
        acquiring.operation_id,
        next_phase="acquired",
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )
    inspecting = kernel.advance(
        acquired.operation_id,
        next_phase="inspecting",
        expected_phase="acquired",
        expected_journal_revision=acquired.journal_revision,
        expected_attempt_epoch=acquired.attempt_epoch,
    )
    candidate.suspend_for_recovery()
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    attempt = store.root / store.attempt_names()[0]
    (attempt / "tree").symlink_to(outside, target_is_directory=True)
    owner._acquisition_owner._source_authority.denied = True

    rejected = owner.execute(_execute_request(inspecting))

    assert rejected.status.phase == "inspecting"
    assert rejected.status.disposition == "rejected"
    assert rejected.status.failure is not None
    assert rejected.status.failure.code == "package_artifact_identity_changed"
    assert rejected.cleanup_status is not None
    assert rejected.cleanup_status.disposition == "cleanup_retryable"
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    repaired = cleanup.repair(
        rejected.cleanup_status.target.cleanup_id,
        expected_cleanup_revision=rejected.cleanup_status.cleanup_revision,
    )
    assert repaired.disposition == "cleanup_complete"
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert store.attempt_names() == ()


def test_extracted_phase_reconstructs_process_local_candidate_idempotently(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    classified = kernel.submit(_ingress())
    initial = owner.execute(_execute_request(classified))
    assert initial.candidate is not None
    initial.candidate.suspend_for_recovery()
    owner._acquisition_owner._source_authority.denied = True

    recovered = owner.execute(_execute_request(initial.status))

    assert recovered.status == initial.status
    assert recovered.candidate is not None
    assert len(evidence.records()) == 3
    recovered.candidate.cleanup()
    assert store.attempt_names() == ()


def test_recovery_rejects_artifact_replacement_without_source_or_outside_delete(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
    )
    acquiring, candidate = _land_acquired_evidence_without_phase_advance(
        kernel,
        owner,
        evidence,
    )
    candidate.suspend_for_recovery()
    attempt = store.root / store.attempt_names()[0]
    artifact = next(path for path in attempt.iterdir() if path.is_file())
    original = artifact.read_bytes()
    artifact.unlink()
    artifact.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    outside = tmp_path / "outside-sentinel"
    outside.write_text("preserve", encoding="utf-8")
    owner._acquisition_owner._source_authority.denied = True

    rejected = owner.execute(_execute_request(acquiring))

    assert rejected.status.phase == "acquired"
    assert rejected.status.disposition == "rejected"
    assert rejected.status.failure is not None
    assert rejected.status.failure.code == "package_artifact_identity_changed"
    assert len(evidence.records()) == 2
    assert outside.read_text(encoding="utf-8") == "preserve"
    assert store.attempt_names() == ()


def test_source_and_archive_failures_have_one_typed_response_and_no_residue(
    tmp_path: Path,
) -> None:
    kernel, owner, journal, evidence, _cleanup, store = _owners(
        tmp_path / "denied", payload=_wheel_bytes(), denied=True
    )
    classified = kernel.submit(_ingress())
    denied = owner.execute(_execute_request(classified))
    assert denied.status.phase == "acquiring"
    assert denied.status.disposition == "rejected"
    assert denied.status.failure is not None
    assert denied.status.failure.code == "package_source_unauthorized"
    assert evidence.records() == ()
    assert store.attempt_names() == ()
    assert len(journal.records()) == 4

    kernel, owner, journal, evidence, _cleanup, store = _owners(
        tmp_path / "malformed", payload=b"not-a-wheel"
    )
    classified = kernel.submit(_ingress())
    malformed = owner.execute(_execute_request(classified))
    assert malformed.status.phase == "inspecting"
    assert malformed.status.disposition == "rejected"
    assert malformed.status.failure is not None
    assert malformed.status.failure.code == "package_archive_malformed"
    assert len(evidence.records()) == 2
    assert store.attempt_names() == ()
    assert journal.records()[-1].status == malformed.status


def test_acquisition_limit_is_attempt_retryable_and_secrets_never_persist(
    tmp_path: Path,
) -> None:
    secret = "never-persist-this-secret"
    kernel, owner, journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
        max_transport_bytes=32,
    )
    classified = kernel.submit(_ingress(secret))

    limited = owner.execute(_execute_request(classified, secret))

    assert limited.status.phase == "acquiring"
    assert limited.status.disposition == "retryable_failure"
    assert limited.status.failure is not None
    assert limited.status.failure.code == "package_acquisition_limit_exceeded"
    assert limited.status.failure.retry_domain == "operation"
    assert (
        limited.status.journal_revision == journal.records()[-2].status.journal_revision
    )
    assert [record.evidence_kind for record in evidence.records()] == [
        "authenticated_source"
    ]
    assert store.attempt_names() == ()
    assert secret not in journal.path.read_text(encoding="utf-8")
    assert secret not in evidence.path.read_text(encoding="utf-8")
    assert secret not in repr(_execute_request(classified, secret))


def test_classification_recheck_changes_fail_before_source_or_quarantine(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, _cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
        recheck=_Recheck(changed=True),
    )
    classified = kernel.submit(_ingress())

    changed = owner.execute(_execute_request(classified))

    assert changed.status.phase == "classified"
    assert changed.status.disposition == "rejected"
    assert changed.status.failure is not None
    assert changed.status.failure.code == "package_target_classification_changed"
    assert evidence.records() == ()
    assert store.attempt_names() == ()


def test_cleanup_debt_preserves_original_rejection_and_repairs_separately(
    tmp_path: Path,
) -> None:
    kernel, owner, journal, evidence, cleanup, store = _owners(
        tmp_path,
        payload=b"not-a-wheel",
        residue_on_rejection=True,
    )
    classified = kernel.submit(_ingress())

    result = owner.execute(_execute_request(classified))

    assert result.status.phase == "inspecting"
    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_archive_malformed"
    assert result.cleanup_status is not None
    assert result.cleanup_status.disposition == "cleanup_retryable"
    assert result.cleanup_status.failure is not None
    assert result.cleanup_status.failure.retry_domain == "cleanup"
    assert len(evidence.records()) == 2
    assert len(cleanup.journal.records()) == 1
    assert len(store.attempt_names()) == 1
    assert journal.records()[-1].status.failure == result.status.failure

    repaired = cleanup.repair(
        result.cleanup_status.target.cleanup_id,
        expected_cleanup_revision=result.cleanup_status.cleanup_revision,
    )
    assert repaired.disposition == "cleanup_complete"
    assert store.attempt_names() == ()
    assert journal.records()[-1].status == result.status


def test_acquisition_cleanup_debt_keeps_retry_in_attempt_domain(
    tmp_path: Path,
) -> None:
    kernel, owner, journal, evidence, cleanup, store = _owners(
        tmp_path,
        payload=_wheel_bytes(),
        max_transport_bytes=32,
        residue_during_acquisition=True,
    )
    classified = kernel.submit(_ingress())

    result = owner.execute(_execute_request(classified))

    assert result.status.phase == "acquiring"
    assert result.status.disposition == "retryable_failure"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_acquisition_limit_exceeded"
    assert result.status.failure.retry_domain == "operation"
    assert result.cleanup_status is not None
    assert result.cleanup_status.failure is not None
    assert result.cleanup_status.failure.retry_domain == "cleanup"
    assert [record.evidence_kind for record in evidence.records()] == [
        "authenticated_source"
    ]
    assert len(cleanup.journal.records()) == 1
    assert len(store.attempt_names()) == 1
    assert journal.records()[-1].record_kind == "attempt"

    repaired = cleanup.repair(
        result.cleanup_status.target.cleanup_id,
        expected_cleanup_revision=result.cleanup_status.cleanup_revision,
    )
    assert repaired.disposition == "cleanup_complete"
    assert store.attempt_names() == ()
