from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    CommittedPackageSetRefV1,
    DependencyClosureLockV2,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
    PackageCommittedSetJournalError,
    PackageCommittedSetRecordV1,
)

OPERATION_ID = "operation-committed-set"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64
ROOT_ARTIFACT_DIGEST = "6" * 64
ROOT_TREE_DIGEST = "5" * 64
DEPENDENCY_ARTIFACT_DIGEST = "4" * 64
DEPENDENCY_TREE_DIGEST = "3" * 64


def _plan() -> VerifiedClosurePlanV2:
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
        attempt_epoch=1,
        root_node_id=root.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root, dependency),
        max_depth=1,
    )


def _root_ref() -> PluginRevisionRefV1:
    return PluginRevisionRefV1.create(
        store_identity="plugin-revision-store",
        store_revision="revision:plugin:1",
        installation_id="installation-test",
        plugin_id="plugin-test",
        distribution="root-plugin",
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


def _lock() -> DependencyClosureLockV2:
    return DependencyClosureLockV2.create(
        _plan(),
        stable_refs={"root": _root_ref(), "dependency-node": _dependency_ref()},
    )


def _publish(
    journal: PackageCommittedSetJournal,
    *,
    scope_id: str = "workspace:test",
):
    return journal.publish(
        _lock(),
        request_fingerprint=REQUEST_FINGERPRINT,
        product_id="coding",
        scope_id=scope_id,
        installation_id="installation-test",
        plugin_id="plugin-test",
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
    )


def test_committed_set_journal_atomically_records_lock_and_exact_set(
    tmp_path: Path,
) -> None:
    journal = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")

    committed = _publish(journal)
    replay = _publish(journal)

    assert replay == committed
    assert committed.commit_revision == 1
    assert committed.root_ref == _root_ref()
    assert committed.dependency_refs == (_dependency_ref(),)
    record = journal.current(OPERATION_ID)
    assert record is not None
    assert record.closure_lock == _lock()
    assert record.committed_set == committed
    assert PackageCommittedSetRecordV1.from_dict(record.to_dict()) == record
    assert PackageCommittedSetJournal(journal.path).records() == (record,)


def test_committed_set_journal_serializes_concurrent_exact_publication(
    tmp_path: Path,
) -> None:
    journal = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: _publish(journal), range(16)))

    assert len(set(results)) == 1
    assert len(journal.records()) == 1
    assert journal.records()[0].record_revision == 1


def test_committed_set_journal_rejects_changed_identity_without_mutation(
    tmp_path: Path,
) -> None:
    journal = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")
    accepted = _publish(journal)
    before = journal.records()

    with pytest.raises(PackageCommittedSetJournalError) as caught:
        _publish(journal, scope_id="workspace:changed")

    assert caught.value.code == "package_operation_identity_conflict"
    assert journal.records() == before
    current = journal.current(OPERATION_ID)
    assert current is not None
    assert current.committed_set == accepted


def test_committed_set_record_revalidates_full_lock_not_only_projection() -> None:
    journal_document: dict[str, object]
    lock = _lock()
    committed = CommittedPackageSetRefV1.create(
        lock,
        request_fingerprint=REQUEST_FINGERPRINT,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        commit_revision=1,
    )
    record = PackageCommittedSetRecordV1(
        record_revision=1,
        closure_lock=lock,
        committed_set=committed,
    )
    journal_document = deepcopy(record.to_dict())
    journal_document["closureLockDigest"] = "0" * 64

    with pytest.raises(ValueError, match="projection changed"):
        PackageCommittedSetRecordV1.from_dict(journal_document)

    changed_set = deepcopy(record.to_dict())
    nested = changed_set["committedSet"]
    assert isinstance(nested, dict)
    nested["scopeId"] = "workspace:changed"
    with pytest.raises(ValueError, match="does not match"):
        PackageCommittedSetRecordV1.from_dict(changed_set)


def test_committed_set_wire_is_credential_path_handle_free_and_strict(
    tmp_path: Path,
) -> None:
    journal = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")
    _publish(journal)
    record = journal.records()[0]
    serialized = repr(record.to_dict()).lower()
    for forbidden in (
        "credential",
        "password",
        "token",
        "pathname",
        "filehandle",
        "/tmp/",
    ):
        assert forbidden not in serialized

    extended = record.to_dict()
    extended["publicationPath"] = "/tmp/forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageCommittedSetRecordV1.from_dict(extended)


def test_committed_set_journal_repairs_partial_tail_and_rejects_duplicate_keys(
    tmp_path: Path,
) -> None:
    journal = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")
    _publish(journal)
    with journal.path.open("ab") as stream:
        stream.write(b'{"recordRevision":')

    assert len(PackageCommittedSetJournal(journal.path).records()) == 1

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"recordRevision":1,"recordRevision":1}\n',
        encoding="utf-8",
    )
    with pytest.raises(PackageCommittedSetJournalError) as corrupt:
        PackageCommittedSetJournal(duplicate).records()
    assert corrupt.value.code == "package_committed_set_journal_corrupt"
