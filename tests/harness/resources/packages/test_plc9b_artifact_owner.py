from __future__ import annotations

import base64
import csv
import io
import stat
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
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

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        sink.write(self.payload)
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _SourceAuthority:
    payload: bytes
    denied: bool = False

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
):
    lifecycle_journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    store = PackageQuarantineStore(tmp_path / "quarantine")
    evidence = PackageArtifactEvidenceJournal(tmp_path / "evidence.jsonl")
    artifact_owner = PackageArtifactLifecycleOwner(
        kernel=kernel,
        classification_recheck=recheck or _Recheck(),
        acquisition_owner=PackageAcquisitionOwner(
            source_authority=_SourceAuthority(payload=payload, denied=denied),
            quarantine_store=store,
        ),
        evidence_journal=evidence,
        wheel_verifier=PackageWheelVerifier(),
        acquisition_budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=max_transport_bytes,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
        inspection_budgets=PackageInspectionBudgetV1(),
        supported_tags=frozenset({"py3-none-any"}),
    )
    return kernel, artifact_owner, lifecycle_journal, evidence, store


def _execute_request(status, secret: str = "credential-ref-secret"):
    return PackageArtifactExecutionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_attempt_epoch=status.attempt_epoch,
        wheel_filename=WHEEL_FILENAME,
        credential_reference=secret,
    )


def test_dark_artifact_owner_journals_exact_phases_and_typed_evidence(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes()
    kernel, owner, journal, evidence, store = _owners(tmp_path, payload=payload)
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
        "bounded_acquisition",
        "verified_wheel",
    ]
    assert result.candidate.evidence.artifact_digest == sha256(payload).hexdigest()
    result.candidate.cleanup()
    assert store.attempt_names() == ()


def test_source_and_archive_failures_have_one_typed_response_and_no_residue(
    tmp_path: Path,
) -> None:
    kernel, owner, journal, evidence, store = _owners(
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

    kernel, owner, journal, evidence, store = _owners(
        tmp_path / "malformed", payload=b"not-a-wheel"
    )
    classified = kernel.submit(_ingress())
    malformed = owner.execute(_execute_request(classified))
    assert malformed.status.phase == "inspecting"
    assert malformed.status.disposition == "rejected"
    assert malformed.status.failure is not None
    assert malformed.status.failure.code == "package_archive_malformed"
    assert len(evidence.records()) == 1
    assert store.attempt_names() == ()
    assert journal.records()[-1].status == malformed.status


def test_acquisition_limit_is_attempt_retryable_and_secrets_never_persist(
    tmp_path: Path,
) -> None:
    secret = "never-persist-this-secret"
    kernel, owner, journal, evidence, store = _owners(
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
    assert evidence.records() == ()
    assert store.attempt_names() == ()
    assert secret not in journal.path.read_text(encoding="utf-8")
    assert secret not in repr(_execute_request(classified, secret))


def test_classification_recheck_changes_fail_before_source_or_quarantine(
    tmp_path: Path,
) -> None:
    kernel, owner, _journal, evidence, store = _owners(
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
