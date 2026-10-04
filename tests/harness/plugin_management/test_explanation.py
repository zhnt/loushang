from __future__ import annotations

import json
from dataclasses import replace

from loushang.harness.plugin_management.application import (
    PluginManagementInstallationViewV1,
    PluginManagementOwnerRevisionsV1,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.explanation import (
    PluginManagementExplanationProjector,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="example",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="reviewpack",
    )


def _projection() -> PluginManagementProjectionV1:
    key = _key()
    revision = PluginPackageRevisionRefV1(
        plugin_id=key.plugin_id,
        plugin_version="2",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity="/private/home/alice/secret-wheel.whl",
    )
    return PluginManagementProjectionV1(
        correlation_id="test:explain",
        owner_revisions=PluginManagementOwnerRevisionsV1(
            desired_state=4,
            operations=5,
            enablement_migration=None,
            source=None,
            instances=None,
            packages=None,
            retirement=None,
            unsupported_dimensions=("instances", "packages", "private_data"),
        ),
        installations=(
            PluginManagementInstallationViewV1(
                installation_key=key,
                source=None,
                desired_state="installed_enabled",
                enablement_migration_phase=None,
                selected_package_revision=revision,
                selected_instance_revision_ref=None,
                operations=(),
                instances=(),
                retirement_states=(),
                cleanup_debt_ids=(),
                convergence="unknown",
                unknown_dimensions=("worker_process",),
            ),
        ),
        skew=(),
    )


class _FixedQueries:
    def __init__(self, projection: PluginManagementProjectionV1) -> None:
        self.projection = projection
        self.queries: list[PluginManagementQueryV1] = []

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        self.queries.append(query)
        return replace(self.projection, correlation_id=query.correlation_id)


def test_management_explanation_reports_partial_evidence_without_private_source() -> None:
    queries = _FixedQueries(_projection())
    explanation = PluginManagementExplanationProjector(
        queries, clock_ns=lambda: 123
    ).explain_installation(_key(), correlation_id="test:explain")

    assert len(queries.queries) == 1
    assert queries.queries[0].plugin_ids == ("reviewpack",)
    assert explanation.management_status == "observed"
    assert explanation.desired_state == "installed_enabled"
    assert explanation.selected_package_content_digest == "a" * 64
    assert explanation.snapshot_status == "partial_evidence"
    assert "product_selection" in explanation.evidence_gaps
    assert "resource_catalog" in explanation.evidence_gaps
    encoded = json.dumps(explanation.to_dict(), sort_keys=True)
    assert "secret-wheel" not in encoded
    assert "/private/home" not in encoded


def test_management_explanation_keeps_absent_row_unknown() -> None:
    queries = _FixedQueries(replace(_projection(), installations=()))
    explanation = PluginManagementExplanationProjector(
        queries, clock_ns=lambda: 123
    ).explain_installation(_key(), correlation_id="test:missing")

    assert explanation.management_status == "unknown"
    assert explanation.desired_state is None
    assert explanation.selected_package_content_digest is None
    assert "management_installation" in explanation.evidence_gaps
