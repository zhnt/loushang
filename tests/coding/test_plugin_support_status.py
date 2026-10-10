from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding.plugin_management_read_sdk import (
    CodingPluginManagementReadClientV1,
)
from loushang.coding.plugin_operation_guidance import (
    project_coding_plugin_operation_guidance,
)
from loushang.coding.plugin_support_status import project_coding_plugin_support_status
from loushang.coding.ui.product_binding import (
    _format_coding_plugin_operation_explanation,
    _format_coding_plugin_support_status,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1


def _owner_documents() -> tuple[dict[str, object], dict[str, object]]:
    management: dict[str, object] = {
        "projectionVersion": 1,
        "ownerRevisions": {"desiredState": 2},
        "installations": [
            {
                "installationKey": {
                    "productId": "coding",
                    "installationScope": "workspace",
                    "scopeId": "workspace:test",
                    "pluginId": "reviewpack",
                    "schemaVersion": 1,
                },
                "desiredState": "installed_enabled",
                "unknownDimensions": [],
            }
        ],
    }
    preview: dict[str, object] = {
        "previewVersion": 1,
        "productId": "coding",
        "scopeId": "workspace:test",
        "snapshotStatus": "partial_evidence",
        "observedAtUnixNs": 123,
        "productPolicyRevision": "policy:old",
        "productAuthorityRevision": "authority:old",
        "disabledSkillSettingsRevision": "settings:old",
        "desiredInventoryRevision": 2,
        "compiledPluginIds": ["reviewpack"],
        "admittedResources": [
            {"pluginId": "reviewpack", "resourceKind": "skill"}
        ],
        "catalogResources": [
            {"resourceKind": "skill", "name": "review", "sourceKind": "external_package"}
        ],
        "evidenceGaps": ["session_catalog_generation"],
        "disposition": "projected",
        "blockingCode": None,
    }
    return management, preview


def test_support_status_refuses_to_promote_stale_or_blocked_preview() -> None:
    management, preview = _owner_documents()
    preview["desiredInventoryRevision"] = 1
    stale = project_coding_plugin_support_status(
        management, preview, correlation_id="test:stale"
    )
    assert stale["snapshotStatus"] == "stale_evidence"
    [installation] = stale["installations"]
    assert installation["productAdmission"] == "not_checked"
    assert installation["productSelection"] == "stale_evidence"
    assert installation["productUse"] == "not_checked"
    assert "stale_snapshot" in stale["evidenceGaps"]

    preview["desiredInventoryRevision"] = 2
    preview["disposition"] = "blocked"
    preview["blockingCode"] = "duplicate_owner_contribution_identity"
    blocked = project_coding_plugin_support_status(
        management, preview, correlation_id="test:blocked"
    )
    [installation] = blocked["installations"]
    assert installation["productAdmission"] == "not_checked"
    assert installation["productSelection"] == "blocked"
    assert installation["reasonCodes"] == ["duplicate_owner_contribution_identity"]
    assert "reasons=duplicate_owner_contribution_identity" in (
        _format_coding_plugin_support_status(blocked)
    )


def test_support_status_refuses_foreign_product_scope() -> None:
    management, preview = _owner_documents()
    preview["scopeId"] = "workspace:foreign"
    with pytest.raises(ValueError, match="scope"):
        project_coding_plugin_support_status(
            management, preview, correlation_id="test:foreign"
        )


def test_support_status_requires_exact_catalog_and_package_identity() -> None:
    management, preview = _owner_documents()
    package = {
        "dependencyLockDigest": "a" * 64,
        "packageContentDigest": "b" * 64,
        "packageSourceIdentity": "author:reviewpack",
        "pluginId": "reviewpack",
        "pluginVersion": "1.0",
        "schemaVersion": 1,
    }
    instance = {"instanceId": "reviewpack-1", "pluginId": "reviewpack", "revision": 1}
    [installation] = management["installations"]
    installation["selectedPackageRevision"] = package
    installation["selectedInstanceRevisionRef"] = instance
    preview["catalogGeneration"] = 1
    preview["catalogSnapshotFingerprint"] = "c" * 64
    preview["selectedResources"] = [
        {
            "installationKey": installation["installationKey"],
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                PluginPackageRevisionRefV1.from_dict(package)
            ),
            "instanceRevisionRef": instance,
            "contributionId": "review-skill",
            "resourceKind": "skill",
            "admissionFingerprint": "d" * 64,
            "candidateFingerprint": "e" * 64,
            "catalogGeneration": 1,
            "catalogSnapshotFingerprint": preview["catalogSnapshotFingerprint"],
        }
    ]
    result = project_coding_plugin_support_status(
        management, preview, correlation_id="test:exact"
    )
    assert result["supportStatusVersion"] == 2
    assert result["installations"][0]["productSelection"] == "selected"
    assert result["installations"][0]["selectedContributions"] == ["review-skill"]

    no_policy = project_coding_plugin_support_status(
        management,
        {**preview, "productPolicyRevision": None},
        correlation_id="test:no-policy",
    )
    assert no_policy["installations"][0]["productSelection"] == "unknown"
    assert "owner_revision_missing" in no_policy["evidenceGaps"]

    installation["selectedPackageRevision"] = {
        **package,
        "packageContentDigest": "f" * 64,
    }
    mismatch = project_coding_plugin_support_status(
        management, preview, correlation_id="test:mismatch"
    )
    assert mismatch["installations"][0]["productSelection"] == "unknown"
    assert "selection_identity_mismatch" in mismatch["installations"][0]["reasonCodes"]

    installation["selectedPackageRevision"] = package
    preview["selectedResources"].append(
        {
            **preview["selectedResources"][0],
            "packageRevisionFingerprint": "f" * 64,
            "candidateFingerprint": "1" * 64,
        }
    )
    mixed = project_coding_plugin_support_status(
        management, preview, correlation_id="test:mixed-revisions"
    )
    assert mixed["installations"][0]["productSelection"] == "unknown"
    assert mixed["installations"][0]["productAdmission"] == "not_checked"
    assert mixed["installations"][0]["selectedContributions"] == []
    preview["selectedResources"].pop()

    preview["evidenceGaps"] = ["stale_snapshot", "product_policy_drift"]
    stale = project_coding_plugin_support_status(
        management, preview, correlation_id="test:policy-drift"
    )
    assert stale["snapshotStatus"] == "stale_evidence"
    assert stale["installations"][0]["productSelection"] == "stale_evidence"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("catalogGeneration", True),
        ("catalogSnapshotFingerprint", "not-a-digest"),
        ("admissionFingerprint", ""),
        ("candidateFingerprint", ""),
        ("contributionId", ""),
    ],
)
def test_support_status_rejects_malformed_catalog_selection(
    field: str, value: object
) -> None:
    management, preview = _owner_documents()
    [installation] = management["installations"]
    package = {
        "dependencyLockDigest": "a" * 64,
        "packageContentDigest": "b" * 64,
        "packageSourceIdentity": "author:reviewpack",
        "pluginId": "reviewpack",
        "pluginVersion": "1.0",
        "schemaVersion": 1,
    }
    instance = {"instanceId": "one", "pluginId": "reviewpack", "revision": 1}
    installation["selectedPackageRevision"] = package
    installation["selectedInstanceRevisionRef"] = instance
    preview["catalogGeneration"] = 1
    preview["catalogSnapshotFingerprint"] = "c" * 64
    receipt = {
        "installationKey": installation["installationKey"],
        "packageRevisionFingerprint": plugin_package_revision_fingerprint(
            PluginPackageRevisionRefV1.from_dict(package)
        ),
        "instanceRevisionRef": instance,
        "contributionId": "review-skill",
        "resourceKind": "skill",
        "admissionFingerprint": "d" * 64,
        "candidateFingerprint": "e" * 64,
        "catalogGeneration": 1,
        "catalogSnapshotFingerprint": "c" * 64,
    }
    if field == "catalogSnapshotFingerprint":
        preview[field] = value
    else:
        receipt[field] = value
    preview["selectedResources"] = [receipt]
    with pytest.raises(ValueError, match="Catalog"):
        project_coding_plugin_support_status(
            management, preview, correlation_id="test:malformed"
        )


def test_support_status_preserves_pending_operation_actor_across_surfaces() -> None:
    management, preview = _owner_documents()
    [installation] = management["installations"]
    installation["operations"] = [
        {"operationId": "a1:cli:7", "actorId": "coding:cli", "status": "running"},
        {"operationId": "a1:tui:8", "actorId": "coding:tui", "status": "accepted"},
    ]
    installation["cleanupDebtIds"] = ["debt:7"]
    installation["retirementStates"] = ["retirement_pending"]
    status = project_coding_plugin_support_status(
        management, preview, correlation_id="test:pending"
    )
    pending = status["installations"][0]["pendingOperations"]
    assert pending == [
        {
            "operationKind": "a1_desired",
            "operationId": "a1:cli:7",
            "actorId": "coding:cli",
            "repairCommand": "loushang --repair-plugin-desired-operation a1:cli:7",
        },
        {
            "operationKind": "a1_desired",
            "operationId": "a1:tui:8",
            "actorId": "coding:tui",
            "repairCommand": "/plugins repair a1:tui:8",
        },
    ]
    rendered = _format_coding_plugin_support_status(status)
    assert "pending a1_desired a1:cli:7 (actor=coding:cli)" in rendered
    assert "repair: loushang --repair-plugin-desired-operation a1:cli:7" in rendered
    assert "pending a1_desired a1:tui:8 (actor=coding:tui)" in rendered
    assert "cleanup-debt=debt:7" in rendered
    assert "retirement=retirement_pending" in rendered


def test_catalog_name_or_content_summary_cannot_claim_package_selection() -> None:
    management, preview = _owner_documents()
    preview["catalogResources"] = [
        {"resourceKind": "skill", "name": "review", "sourceKind": "project_local"},
        {"resourceKind": "skill", "name": "review", "sourceKind": "external_package"},
    ]
    preview["catalogGeneration"] = 1
    preview["catalogSnapshotFingerprint"] = "a" * 64
    preview["selectedResources"] = []
    status = project_coding_plugin_support_status(
        management, preview, correlation_id="test:catalog-collision"
    )
    assert status["installations"][0]["productSelection"] == "projected"
    assert status["installations"][0]["productUse"] == "not_checked"


@pytest.mark.parametrize(
    ("owner_revisions", "expected_gap"),
    [
        (("policy:new", "authority:old", "settings:old"), "product_policy_drift"),
        (("policy:old", "authority:new", "settings:old"), "product_authority_drift"),
        (("policy:old", "authority:old", "settings:new"), "disabled_skill_settings_drift"),
    ],
)
def test_read_sdk_rechecks_non_desired_owner_revisions(
    monkeypatch: pytest.MonkeyPatch,
    owner_revisions: tuple[str, str, str],
    expected_gap: str,
) -> None:
    management, preview = _owner_documents()
    preview["productPolicyRevision"] = "policy:old"
    preview["productAuthorityRevision"] = "authority:old"
    preview["disabledSkillSettingsRevision"] = "settings:old"

    class FakeRead:
        workspace = Path("/inert")

        def management_snapshot(self, **_kwargs: object) -> dict[str, object]:
            return management

        def preview_current(self, **_kwargs: object) -> dict[str, object]:
            return preview

        def _assert_workspace_identity(self) -> None:
            pass

    class FakeOwner:
        def owner_revisions(self) -> tuple[str, str, str]:
            return owner_revisions

    monkeypatch.setattr(
        "loushang.coding.plugin_management_read_sdk.bind_coding_current_preview_query",
        lambda *_args, **_kwargs: FakeOwner(),
    )
    status = CodingPluginManagementReadClientV1.support_status(
        FakeRead(), correlation_id="test:drift"
    )
    assert status["snapshotStatus"] == "stale_evidence"
    assert expected_gap in status["evidenceGaps"]
    assert status["installations"][0]["productSelection"] == "stale_evidence"


def test_read_sdk_detects_management_operation_drift_without_desired_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    management, preview = _owner_documents()
    before = {**management, "ownerRevisions": {"desiredState": 2, "operations": 3}}
    after = {**management, "ownerRevisions": {"desiredState": 2, "operations": 4}}

    class FakeRead:
        workspace = Path("/inert")
        calls = 0

        def management_snapshot(self, **_kwargs: object) -> dict[str, object]:
            self.calls += 1
            return before if self.calls == 1 else after

        def preview_current(self, **_kwargs: object) -> dict[str, object]:
            return preview

        def _assert_workspace_identity(self) -> None:
            pass

    class FakeOwner:
        def owner_revisions(self) -> tuple[str, str, str]:
            return ("policy:old", "authority:old", "settings:old")

    monkeypatch.setattr(
        "loushang.coding.plugin_management_read_sdk.bind_coding_current_preview_query",
        lambda *_args, **_kwargs: FakeOwner(),
    )
    status = CodingPluginManagementReadClientV1.support_status(
        FakeRead(), correlation_id="test:management-drift"
    )
    assert status["snapshotStatus"] == "stale_evidence"
    assert "management_owner_drift" in status["evidenceGaps"]


def test_explanation_repair_is_bound_to_a1_actor_and_status() -> None:
    document: dict[str, object] = {
        "operationId": "test:pending",
        "operationKind": "a1_desired",
        "explanationVersion": 1,
        "snapshotStatus": "partial_evidence",
        "package": {
            "operationId": "test:pending",
            "status": "unknown",
            "phase": None,
            "disposition": None,
            "failureCode": None,
            "operatorAction": None,
        },
        "managementStatus": "observed",
        "managementProgressCode": "command_accepted",
        "managementDisposition": None,
        "managementActorId": "coding:cli",
        "handoffEvidence": "not_queried",
        "joinStatus": "management_only",
        "evidenceGaps": [],
    }
    cli = project_coding_plugin_operation_guidance(document)
    assert cli["repairCommand"] == (
        "loushang --repair-plugin-desired-operation test:pending"
    )
    assert "Repair: loushang --repair-plugin-desired-operation test:pending" in (
        _format_coding_plugin_operation_explanation(
            cli, operation_id="test:pending"
        )
    )
    tui = project_coding_plugin_operation_guidance(
        {**document, "managementActorId": "coding:tui"}
    )
    assert tui["repairCommand"] == "/plugins repair test:pending"
    completed = project_coding_plugin_operation_guidance(
        {**document, "managementDisposition": "succeeded"}
    )
    assert completed["repairCommand"] is None

    a2 = project_coding_plugin_operation_guidance(
        {
            **document,
            "operationKind": "a2_package",
            "package": {
                "operationId": "test:pending",
                "status": "observed",
                "disposition": "committed",
            },
            "managementDisposition": None,
            "managementActorId": "product:coding",
            "handoffEvidence": "incomplete",
            "joinStatus": "same_identity",
            "desiredCommitEvidence": "verified_transition",
        }
    )
    assert a2["repairCommand"] == (
        "loushang-package-repair repair-handoff test:pending"
    )
    conflict = project_coding_plugin_operation_guidance(
        {**a2, "joinStatus": "identity_conflict"}
    )
    assert conflict["repairCommand"] is None
    no_commit = project_coding_plugin_operation_guidance(
        {**a2, "desiredCommitEvidence": "not_checked"}
    )
    assert no_commit["repairCommand"] is None
