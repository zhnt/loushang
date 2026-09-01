from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    BoundedAcquisitionReceiptV1,
    PackageAcquisitionBudgetV1,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
    PackageArtifactEvidenceJournalError,
    PackageArtifactEvidenceRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)


def _acquired(*, digest: str = "b" * 64) -> BoundedAcquisitionReceiptV1:
    return BoundedAcquisitionReceiptV1(
        operation_id="operation-evidence",
        attempt_epoch=1,
        node_id="root",
        envelope_fingerprint="a" * 64,
        actual_byte_digest=digest,
        actual_byte_count=100,
        request_count=1,
        redirect_count=0,
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=1000,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
        sink_identity="c" * 64,
        adapter_result=SourceAdapterResultV1(disposition="complete"),
    )


def _verified(*, digest: str = "b" * 64) -> VerifiedWheelArtifactV1:
    return VerifiedWheelArtifactV1(
        operation_id="operation-evidence",
        attempt_epoch=1,
        node_id="root",
        distribution="acme-plugin",
        version="1.0",
        wheel_filename="acme_plugin-1.0-py3-none-any.whl",
        compatible_tags=("py3-none-any",),
        artifact_digest=digest,
        artifact_size=100,
        wheel_metadata_digest="d" * 64,
        package_metadata_digest="e" * 64,
        record_digest="f" * 64,
        record_verified=True,
        entry_count=4,
        expanded_byte_count=500,
        extraction_tree_digest="1" * 64,
    )


def test_phase_evidence_is_append_once_typed_and_replayable(tmp_path: Path) -> None:
    journal = PackageArtifactEvidenceJournal(tmp_path / "artifact-evidence.jsonl")

    acquired = journal.append(request_fingerprint="9" * 64, evidence=_acquired())
    assert (
        journal.append(request_fingerprint="9" * 64, evidence=_acquired()) == acquired
    )
    verified = journal.append(request_fingerprint="9" * 64, evidence=_verified())

    assert acquired.phase == "acquired"
    assert acquired.prior_evidence_revision == 0
    assert verified.phase == "extracted"
    assert verified.prior_evidence_revision == acquired.record_revision
    assert PackageArtifactEvidenceRecordV1.from_dict(verified.to_dict()) == verified
    reopened = PackageArtifactEvidenceJournal(journal.path)
    assert reopened.records() == (acquired, verified)
    assert (
        reopened.find(
            operation_id="operation-evidence",
            attempt_epoch=1,
            node_id="root",
            kind="verified_wheel",
        )
        == verified
    )


def test_changed_evidence_and_orphan_verified_wheel_fail_closed(
    tmp_path: Path,
) -> None:
    journal = PackageArtifactEvidenceJournal(tmp_path / "artifact-evidence.jsonl")
    journal.append(request_fingerprint="9" * 64, evidence=_acquired())

    with pytest.raises(PackageArtifactEvidenceJournalError) as conflict:
        journal.append(
            request_fingerprint="9" * 64,
            evidence=_acquired(digest="8" * 64),
        )
    assert conflict.value.code == "package_operation_identity_conflict"
    assert len(journal.records()) == 1

    with pytest.raises(PackageArtifactEvidenceJournalError) as changed_parent:
        journal.append(
            request_fingerprint="9" * 64,
            evidence=_verified(digest="8" * 64),
        )
    assert changed_parent.value.code == "package_operation_identity_conflict"
    assert len(journal.records()) == 1

    orphan = PackageArtifactEvidenceJournal(tmp_path / "orphan.jsonl")
    with pytest.raises(PackageArtifactEvidenceJournalError) as missing:
        orphan.append(request_fingerprint="9" * 64, evidence=_verified())
    assert missing.value.code == "package_operation_phase_conflict"
    assert orphan.records() == ()


def test_evidence_journal_rejects_duplicate_keys_without_secret_echo(
    tmp_path: Path,
) -> None:
    journal = PackageArtifactEvidenceJournal(tmp_path / "artifact-evidence.jsonl")
    journal.append(request_fingerprint="9" * 64, evidence=_acquired())
    line = journal.path.read_text(encoding="utf-8")
    journal.path.write_text(
        line.replace("{", '{"recordVersion":1,', 1),
        encoding="utf-8",
    )

    with pytest.raises(PackageArtifactEvidenceJournalError) as corrupt:
        journal.records()
    assert corrupt.value.code == "package_artifact_evidence_journal_corrupt"
    assert "recordVersion" not in str(corrupt.value)
