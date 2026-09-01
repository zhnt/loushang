from __future__ import annotations

import inspect
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

IMPLEMENTED_B1_MANIFEST_CASES = (
    "B-CLASS-PLUGIN",
    "B-CLASS-NONPLUGIN",
    "B-CLASS-INDETERMINATE",
    "B-CLASS-SPOOF",
    "B-CRASH-ACCEPTED",
    "B-CRASH-CLASSIFIED",
    "B-CONCUR-CONFLICT",
    "B-ENTRY-DISABLED",
)


@dataclass
class _Authority:
    facts: PackageClassificationFactsV1

    def classification_facts(
        self,
        _request: object,
    ) -> PackageClassificationFactsV1:
        return self.facts


def _facts(*present: str) -> PackageClassificationFactsV1:
    present_set = set(present)
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
                present=kind in present_set,
                authority_id=f"authority:{kind}",
                owner_revision=f"revision:{kind}:1",
            )
            for kind in kinds
        ),
        policy_revision="classification-policy:1",
        classifier_epoch=1,
    )


def _request(
    *,
    source: str = "https://packages.example.test/acme.whl",
) -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id="manifest-operation",
        action="install",
        product_id="coding",
        scope_id="workspace:manifest",
        requested_package="acme==1.0",
        requested_plugin_id="acme.plugin",
        source_locator=source,
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint="e" * 64,
    )


def _owner(
    tmp_path: Path,
    *,
    facts: PackageClassificationFactsV1,
    enabled: bool = True,
) -> tuple[PackageLifecycleOwner, PackageLifecycleJournal]:
    journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    return (
        PackageLifecycleOwner(
            journal=journal,
            classification_authority=_Authority(facts),
            enabled=enabled,
        ),
        journal,
    )


@pytest.mark.parametrize("case_id", IMPLEMENTED_B1_MANIFEST_CASES)
def test_manifest_case(case_id: str, tmp_path: Path) -> None:
    if case_id == "B-CLASS-PLUGIN":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        status = owner.submit(_request())
        _assert_classification(status, decision="plugin_bound", code=None)
        _assert_replay_is_single_owner(owner, journal)
    elif case_id == "B-CLASS-NONPLUGIN":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("independent_non_plugin_authority"),
        )
        status = owner.submit(_request())
        _assert_classification(status, decision="non_plugin", code=None)
        _assert_replay_is_single_owner(owner, journal)
    elif case_id == "B-CLASS-INDETERMINATE":
        owner, journal = _owner(tmp_path, facts=_facts())
        status = owner.submit(_request())
        _assert_classification(
            status,
            decision="indeterminate",
            code="package_target_classification_indeterminate",
        )
        _assert_replay_is_single_owner(owner, journal)
    elif case_id == "B-CLASS-SPOOF":
        assert "plugin_bound" not in inspect.signature(
            PackageLifecycleIngressRequestV1
        ).parameters
        owner, journal = _owner(tmp_path, facts=_facts())
        status = owner.submit(_request())
        _assert_classification(
            status,
            decision="indeterminate",
            code="package_target_classification_indeterminate",
        )
        _assert_replay_is_single_owner(owner, journal)
    elif case_id in {"B-CRASH-ACCEPTED", "B-CRASH-CLASSIFIED"}:
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        accepted = owner.accept(_request())
        current = accepted
        if case_id == "B-CRASH-CLASSIFIED":
            current = owner.classify(
                accepted.operation_id,
                expected_journal_revision=accepted.journal_revision,
                expected_attempt_epoch=accepted.attempt_epoch,
            )
        interrupted = owner.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
        record_count = len(journal.records())
        replay = owner.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
        assert replay == interrupted
        assert len(journal.records()) == record_count
        assert interrupted.disposition == "retryable_failure"
        assert interrupted.failure is not None
        assert interrupted.failure.code == "package_operation_interrupted"
        assert interrupted.request_fingerprint == current.request_fingerprint
    elif case_id == "B-CONCUR-CONFLICT":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(owner.submit, _request()),
                executor.submit(
                    owner.submit,
                    _request(source="https://packages.example.test/changed.whl"),
                ),
            )
            statuses = tuple(future.result() for future in futures)
        accepted = next(status for status in statuses if status.disposition == "active")
        conflict = next(
            status for status in statuses if status.disposition == "rejected"
        )
        assert conflict.disposition == "rejected"
        assert conflict.failure is not None
        assert conflict.failure.code == "package_operation_identity_conflict"
        assert journal.status(accepted.operation_id) == accepted
        assert len(journal.records()) == 2
    elif case_id == "B-ENTRY-DISABLED":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
            enabled=False,
        )
        status = owner.submit(_request())
        assert status.phase == "classified"
        assert status.disposition == "rejected"
        assert status.failure is not None
        assert status.failure.code == "package_route_unavailable"
        assert journal.records() == ()
        assert not journal.path.exists()
    else:  # pragma: no cover - the parametrization is deliberately closed
        raise AssertionError(f"Unhandled PLC9B1 manifest case: {case_id}")

    _assert_no_capability_side_effect(tmp_path)


def _assert_classification(status: object, *, decision: str, code: str | None) -> None:
    assert getattr(status, "phase") == "classified"
    classification = getattr(status, "classification")
    assert classification is not None
    assert classification.decision == decision
    failure = getattr(status, "failure")
    if code is None:
        assert getattr(status, "disposition") == "active"
        assert failure is None
    else:
        assert getattr(status, "disposition") == "rejected"
        assert failure is not None
        assert failure.code == code


def _assert_replay_is_single_owner(
    owner: PackageLifecycleOwner,
    journal: PackageLifecycleJournal,
) -> None:
    current = journal.status("manifest-operation")
    records = journal.records()
    assert owner.submit(_request()) == current
    assert journal.records() == records


def _assert_no_capability_side_effect(tmp_path: Path) -> None:
    names = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert names <= {"package-lifecycle.jsonl", "package-lifecycle.jsonl.lock"}
