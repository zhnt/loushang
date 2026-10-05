from __future__ import annotations

import pytest

from loushang.coding.plugin_support_status import project_coding_plugin_support_status


def _owner_documents() -> tuple[dict[str, object], dict[str, object]]:
    management: dict[str, object] = {
        "projectionVersion": 1,
        "ownerRevisions": {"desiredState": 2},
        "installations": [
            {
                "installationKey": {
                    "productId": "coding",
                    "scopeId": "workspace:test",
                    "pluginId": "reviewpack",
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


def test_support_status_refuses_foreign_product_scope() -> None:
    management, preview = _owner_documents()
    preview["scopeId"] = "workspace:foreign"
    with pytest.raises(ValueError, match="scope"):
        project_coding_plugin_support_status(
            management, preview, correlation_id="test:foreign"
        )
