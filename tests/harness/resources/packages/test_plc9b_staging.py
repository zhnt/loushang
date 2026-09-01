from __future__ import annotations

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
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
    PackageArtifactStagingJournalError,
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)

OPERATION_ID = "operation-artifact-staging"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64
ROOT_ARTIFACT_DIGEST = "6" * 64
ROOT_TREE_DIGEST = "5" * 64
DEPENDENCY_ARTIFACT_DIGEST = "4" * 64
DEPENDENCY_TREE_DIGEST = "3" * 64


def _plan(*, attempt_epoch: int = 1) -> VerifiedClosurePlanV2:
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
        attempt_epoch=attempt_epoch,
        root_node_id=root.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root, dependency),
        max_depth=1,
    )


def _pin(
    plan: VerifiedClosurePlanV2 | None = None,
) -> PackageTransactionPinReceiptV1:
    request = PackageTransactionPinRequestV1.create(
        plan or _plan(),
        request_fingerprint=REQUEST_FINGERPRINT,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        recovery_identity="recovery-artifact-staging",
    )
    return PackageTransactionPinReceiptV1.acquire(
        request,
        pin_id="f" * 64,
        owner_identity="retention-owner",
        owner_revision=7,
        lease_id="lease-artifact-staging",
        lease_revision=3,
    )


def _target() -> PackagePluginRootTargetV1:
    return PackagePluginRootTargetV1.create(
        operation_id=OPERATION_ID,
        request_fingerprint=REQUEST_FINGERPRINT,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        authority_id="plugin-target-authority",
        authority_revision="target-revision:1",
    )


def _request(node_id: str) -> PackageArtifactStagingRequestV1:
    return PackageArtifactStagingRequestV1.create(
        _plan(),
        node_id=node_id,
        request_fingerprint=REQUEST_FINGERPRINT,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        pin_receipt=_pin(),
        root_target=_target() if node_id == "root" else None,
    )


def _dependency_ref(
    *, store_revision: str = "revision:dependency:1"
) -> VerifiedArtifactRefV1:
    return VerifiedArtifactRefV1.create(
        store_identity="dependency-store",
        store_revision=store_revision,
        distribution="dependency",
        version="2.0",
        artifact_digest=DEPENDENCY_ARTIFACT_DIGEST,
        extraction_tree_digest=DEPENDENCY_TREE_DIGEST,
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


def _receipt(node_id: str) -> PackageArtifactStagingReceiptV1:
    return PackageArtifactStagingReceiptV1.create(
        _request(node_id),
        stable_ref=_root_ref() if node_id == "root" else _dependency_ref(),
    )


def test_staging_requests_and_receipts_are_exact_role_safe_round_trips() -> None:
    dependency = _receipt("dependency-node")
    root = _receipt("root")

    assert PackagePluginRootTargetV1.from_dict(_target().to_dict()) == _target()
    assert (
        PackageArtifactStagingRequestV1.from_dict(dependency.staging_request.to_dict())
        == dependency.staging_request
    )
    assert PackageArtifactStagingReceiptV1.from_dict(dependency.to_dict()) == dependency
    assert PackageArtifactStagingReceiptV1.from_dict(root.to_dict()) == root
    assert dependency.staging_request.root_target is None
    assert root.staging_request.root_target == _target()
    assert isinstance(dependency.stable_ref, VerifiedArtifactRefV1)
    assert isinstance(root.stable_ref, PluginRevisionRefV1)


def test_staging_request_requires_exact_acquired_graph_wide_pin() -> None:
    plan = _plan()
    released = PackageTransactionPinReceiptV1.transition(
        _pin(plan),
        state="released",
        owner_revision=8,
        lease_revision=4,
        transition_evidence_ref="d" * 64,
    )
    with pytest.raises(ValueError, match="acquired transaction pin"):
        PackageArtifactStagingRequestV1.create(
            plan,
            node_id="dependency-node",
            request_fingerprint=REQUEST_FINGERPRINT,
            classification_fingerprint=CLASSIFICATION_FINGERPRINT,
            pin_receipt=released,
        )

    with pytest.raises(ValueError, match="does not cover"):
        PackageArtifactStagingRequestV1.create(
            plan,
            node_id="dependency-node",
            request_fingerprint="0" * 64,
            classification_fingerprint=CLASSIFICATION_FINGERPRINT,
            pin_receipt=_pin(plan),
        )


def test_staging_request_requires_authoritative_root_target_only_for_root() -> None:
    with pytest.raises(TypeError, match="target identity"):
        PackageArtifactStagingRequestV1.create(
            _plan(),
            node_id="root",
            request_fingerprint=REQUEST_FINGERPRINT,
            classification_fingerprint=CLASSIFICATION_FINGERPRINT,
            pin_receipt=_pin(),
        )
    with pytest.raises(ValueError, match="Dependency staging"):
        PackageArtifactStagingRequestV1.create(
            _plan(),
            node_id="dependency-node",
            request_fingerprint=REQUEST_FINGERPRINT,
            classification_fingerprint=CLASSIFICATION_FINGERPRINT,
            pin_receipt=_pin(),
            root_target=_target(),
        )


def test_staging_receipt_rejects_role_or_plugin_identity_confusion() -> None:
    with pytest.raises(ValueError, match="root requires"):
        PackageArtifactStagingReceiptV1.create(
            _request("root"),
            stable_ref=_dependency_ref(),
        )
    changed_root = PluginRevisionRefV1.create(
        store_identity="plugin-revision-store",
        store_revision="revision:plugin:1",
        installation_id="installation-other",
        plugin_id="plugin-test",
        distribution="root-plugin",
        version="1.0",
        artifact_digest=ROOT_ARTIFACT_DIGEST,
        extraction_tree_digest=ROOT_TREE_DIGEST,
    )
    with pytest.raises(ValueError, match="target identity"):
        PackageArtifactStagingReceiptV1.create(
            _request("root"),
            stable_ref=changed_root,
        )


def test_staging_wire_is_credential_path_handle_free_and_strict() -> None:
    serialized = repr(_receipt("root").to_dict()).lower()
    for forbidden in (
        "credential",
        "password",
        "token",
        "pathname",
        "filehandle",
        "/tmp/",
    ):
        assert forbidden not in serialized

    extended = _receipt("root").to_dict()
    extended["publishedPath"] = "/tmp/forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageArtifactStagingReceiptV1.from_dict(extended)

    forged = deepcopy(_target().to_dict())
    forged["targetId"] = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        PackagePluginRootTargetV1.from_dict(forged)


def test_staging_journal_records_exact_nodes_and_replays_after_restart(
    tmp_path: Path,
) -> None:
    journal = PackageArtifactStagingJournal(tmp_path / "artifact-staging.jsonl")
    root = _receipt("root")
    dependency = _receipt("dependency-node")

    assert journal.append(root) == root
    assert journal.append(dependency) == dependency
    assert journal.append(root) == root
    assert journal.current(operation_id=OPERATION_ID, node_id="root") == root
    assert journal.receipts(OPERATION_ID) == (dependency, root)
    records = journal.records()
    assert tuple(record.record_revision for record in records) == (1, 2)
    assert PackageArtifactStagingJournal(journal.path).records() == records


def test_staging_journal_rejects_changed_ref_without_mutation(tmp_path: Path) -> None:
    journal = PackageArtifactStagingJournal(tmp_path / "artifact-staging.jsonl")
    accepted = _receipt("dependency-node")
    journal.append(accepted)
    before = journal.records()
    changed = PackageArtifactStagingReceiptV1.create(
        accepted.staging_request,
        stable_ref=_dependency_ref(store_revision="revision:dependency:2"),
    )

    with pytest.raises(PackageArtifactStagingJournalError) as caught:
        journal.append(changed)

    assert caught.value.code == "package_operation_identity_conflict"
    assert journal.records() == before


def test_staging_journal_repairs_partial_tail_and_rejects_duplicate_keys(
    tmp_path: Path,
) -> None:
    journal = PackageArtifactStagingJournal(tmp_path / "artifact-staging.jsonl")
    journal.append(_receipt("root"))
    with journal.path.open("ab") as stream:
        stream.write(b'{"recordRevision":')

    assert len(PackageArtifactStagingJournal(journal.path).records()) == 1

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"recordRevision":1,"recordRevision":1}\n',
        encoding="utf-8",
    )
    with pytest.raises(PackageArtifactStagingJournalError) as corrupt:
        PackageArtifactStagingJournal(duplicate).records()
    assert corrupt.value.code == "package_artifact_staging_journal_corrupt"
