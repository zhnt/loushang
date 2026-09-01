from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureBudgetV1,
    PackageResolutionEnvironmentV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
    PackageClosureResolutionJournalError,
    PackageClosureResolutionRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionRequestV1,
    PackageDependencySelectionV1,
)

OPERATION_ID = "operation-closure-journal"
REQUEST_FINGERPRINT = "9" * 64
DEPENDENCY_SOURCE = "https://packages.example.test/dependency.whl"
DEPENDENCY_DIGEST = "7" * 64
POLICY_REVISION = "package-policy:1"
QUOTA_PROFILE_REVISION = "quota:1"


def _environment() -> PackageResolutionEnvironmentV1:
    return PackageResolutionEnvironmentV1.from_mapping(
        {
            "implementation_name": "cpython",
            "implementation_version": "3.11.10",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "platform_release": "fixture",
            "platform_system": "Linux",
            "platform_version": "fixture",
            "python_full_version": "3.11.10",
            "python_version": "3.11",
            "sys_platform": "linux",
        },
        supported_tags=("py3-none-any",),
    )


ENVIRONMENT_FINGERPRINT = _environment().fingerprint


def _basis(
    *,
    environment: PackageResolutionEnvironmentV1 | None = None,
    budgets: PackageClosureBudgetV1 | None = None,
    root_extras: tuple[str, ...] = (),
) -> PackageClosureResolutionBasisV1:
    return PackageClosureResolutionBasisV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        request_fingerprint=REQUEST_FINGERPRINT,
        policy_revision=POLICY_REVISION,
        quota_profile_revision=QUOTA_PROFILE_REVISION,
        resolution_environment=environment or _environment(),
        budgets=budgets or PackageClosureBudgetV1(),
        root_extras=root_extras,
    )


def _request(
    requirement: str = "dependency==2.0",
) -> PackageDependencySelectionRequestV1:
    return PackageDependencySelectionRequestV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        parent_node_id="root",
        request_fingerprint=REQUEST_FINGERPRINT,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        requirement=NormalizedPackageRequirementV1.parse(requirement),
    )


def _selection(
    request: PackageDependencySelectionRequestV1 | None = None,
) -> PackageDependencySelectionV1:
    request = request or _request()
    return PackageDependencySelectionV1(
        operation_id=request.operation_id,
        attempt_epoch=request.attempt_epoch,
        parent_node_id=request.parent_node_id,
        request_fingerprint=request.request_fingerprint,
        resolution_environment_fingerprint=(request.resolution_environment_fingerprint),
        requirement_fingerprint=request.requirement_fingerprint,
        project_name="dependency",
        version="2.0",
        canonical_source_identity=DEPENDENCY_SOURCE,
        wheel_filename="dependency-2.0-py3-none-any.whl",
        expected_artifact_digest=DEPENDENCY_DIGEST,
        resolver_id="resolver:test",
        resolver_revision="resolver-revision:1",
    )


def _plan() -> VerifiedClosurePlanV2:
    requirement = ResolvedPackageRequirementV1(
        requirement=_request().requirement,
        marker_applies=True,
        selected_node_id="dependency-node",
        expected_source_identity=DEPENDENCY_SOURCE,
        expected_artifact_digest=DEPENDENCY_DIGEST,
    )
    dependency = VerifiedClosurePlanNodeV2(
        node_id="dependency-node",
        role="dependency",
        distribution="dependency",
        version="2.0",
        canonical_source_identity=DEPENDENCY_SOURCE,
        source_envelope_fingerprint="1" * 64,
        acquisition_receipt_fingerprint="2" * 64,
        wheel_evidence_fingerprint="3" * 64,
        artifact_digest=DEPENDENCY_DIGEST,
        extraction_tree_digest="4" * 64,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
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
        artifact_digest="d" * 64,
        extraction_tree_digest="e" * 64,
        selected_extras=(),
        requirements=(requirement,),
        selected_edges=("dependency-node",),
    )
    return VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        root_node_id="root",
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(dependency, root),
        max_depth=1,
    )


def test_resolution_journal_appends_selection_then_exact_plan_and_replays(
    tmp_path: Path,
) -> None:
    journal = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    request = _request()
    selection = _selection(request)
    plan = _plan()

    assert journal.bind_basis(_basis()) == _basis()
    assert journal.bind_basis(_basis()) == _basis()
    assert journal.append_selection(request, selection) == selection
    assert journal.append_selection(request, selection) == selection
    assert journal.selection(request) == selection
    assert (
        journal.append_plan(
            request_fingerprint=REQUEST_FINGERPRINT,
            plan=plan,
        )
        == plan
    )
    assert (
        journal.append_plan(
            request_fingerprint=REQUEST_FINGERPRINT,
            plan=plan,
        )
        == plan
    )

    records = journal.records()
    assert len(records) == 3
    assert records[0].evidence_kind == "resolution_basis"
    assert records[0].prior_resolution_revision == 0
    assert records[1].evidence_kind == "selection"
    assert records[1].prior_resolution_revision == records[0].record_revision
    assert records[2].evidence_kind == "verified_plan"
    assert records[2].prior_resolution_revision == records[1].record_revision
    assert (
        PackageClosureResolutionRecordV1.from_dict(records[2].to_dict()) == records[2]
    )
    reopened = PackageClosureResolutionJournal(journal.path)
    assert reopened.records() == records
    assert reopened.plan(operation_id=OPERATION_ID, attempt_epoch=1) == plan


def test_resolution_journal_rejects_changed_selection_and_post_plan_append(
    tmp_path: Path,
) -> None:
    journal = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    request = _request()
    selection = _selection(request)
    journal.bind_basis(_basis())
    journal.append_selection(request, selection)

    with pytest.raises(PackageClosureResolutionJournalError) as changed:
        journal.append_selection(
            request,
            replace(selection, expected_artifact_digest="6" * 64),
        )
    assert changed.value.code == "package_operation_identity_conflict"

    changed_request = replace(request, request_fingerprint="4" * 64)
    with pytest.raises(PackageClosureResolutionJournalError) as request_conflict:
        journal.selection(changed_request)
    assert request_conflict.value.code == "package_operation_identity_conflict"
    with pytest.raises(PackageClosureResolutionJournalError) as append_conflict:
        journal.append_selection(
            changed_request,
            replace(selection, request_fingerprint="4" * 64),
        )
    assert append_conflict.value.code == "package_operation_identity_conflict"

    journal.append_plan(request_fingerprint=REQUEST_FINGERPRINT, plan=_plan())
    extra_request = _request("extra-dependency==1")
    extra_selection = replace(
        _selection(extra_request),
        project_name="extra-dependency",
        version="1",
        canonical_source_identity="https://packages.example.test/extra.whl",
        wheel_filename="extra_dependency-1-py3-none-any.whl",
        expected_artifact_digest="5" * 64,
    )
    with pytest.raises(PackageClosureResolutionJournalError) as late:
        journal.append_selection(extra_request, extra_selection)
    assert late.value.code == "package_operation_phase_conflict"
    assert len(journal.records()) == 3


def test_verified_plan_requires_exact_complete_selection_set(tmp_path: Path) -> None:
    journal = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    journal.bind_basis(_basis())

    with pytest.raises(PackageClosureResolutionJournalError) as missing:
        journal.append_plan(
            request_fingerprint=REQUEST_FINGERPRINT,
            plan=_plan(),
        )
    assert missing.value.code == "package_operation_identity_conflict"
    assert len(journal.records()) == 1

    request = _request()
    changed = replace(_selection(request), version="2.1")
    journal.append_selection(request, changed)
    with pytest.raises(PackageClosureResolutionJournalError) as mismatch:
        journal.append_plan(
            request_fingerprint=REQUEST_FINGERPRINT,
            plan=_plan(),
        )
    assert mismatch.value.code == "package_operation_identity_conflict"
    assert len(journal.records()) == 2


def test_resolution_basis_is_required_and_changed_inputs_fail_closed(
    tmp_path: Path,
) -> None:
    journal = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    request = _request()

    with pytest.raises(PackageClosureResolutionJournalError) as missing:
        journal.append_selection(request, _selection(request))
    assert missing.value.code == "package_operation_identity_conflict"
    assert journal.records() == ()

    basis = _basis()
    journal.bind_basis(basis)
    for changed in (
        replace(basis, budgets=replace(basis.budgets, max_nodes=1)),
        replace(basis, root_extras=("fast",)),
        replace(
            basis,
            resolution_environment=PackageResolutionEnvironmentV1.from_mapping(
                basis.resolution_environment.as_marker_mapping()
                | {"python_full_version": "3.12.0", "python_version": "3.12"},
                supported_tags=basis.resolution_environment.supported_tags,
            ),
        ),
    ):
        with pytest.raises(PackageClosureResolutionJournalError) as conflict:
            journal.bind_basis(changed)
        assert conflict.value.code == "package_operation_identity_conflict"
    assert journal.records()[0].evidence == basis


def test_resolution_journal_rejects_corrupt_duplicate_keys_without_echo(
    tmp_path: Path,
) -> None:
    journal = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    journal.bind_basis(_basis())
    journal.append_selection(_request(), _selection())
    content = journal.path.read_text(encoding="utf-8")
    journal.path.write_text(
        content.replace("{", '{"recordVersion":1,', 1),
        encoding="utf-8",
    )

    with pytest.raises(PackageClosureResolutionJournalError) as corrupt:
        journal.records()
    assert corrupt.value.code == "package_closure_resolution_journal_corrupt"
    assert "recordVersion" not in str(corrupt.value)
