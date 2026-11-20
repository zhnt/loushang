"""Acquire and read scoped Plugin management and Product support evidence."""

from __future__ import annotations

from pathlib import Path

from loushang.coding.plugin_manager import read_sdk as _binding
from loushang.harness.workspace.paths import (
    capture_workspace_directory_identity,
    require_workspace_directory,
)

_WORKSPACE_UNAVAILABLE = "Plugin management workspace is unavailable"


def support_status(
    self: _binding.CodingPluginManagementReadClientV1,
    *,
    correlation_id: str,
    composition_set_id: str,
) -> dict[str, object]:
    """Join management and Product preview without asserting Session use."""

    from loushang.coding.plugin_manager.support_status import (
        project_coding_plugin_support_status,
    )

    before = self.management_snapshot(correlation_id=f"{correlation_id}:before")
    preview = self.preview_current(
        correlation_id=f"{correlation_id}:preview",
        composition_set_id=composition_set_id,
    )
    after = self.management_snapshot(correlation_id=f"{correlation_id}:after")
    policy_revision, authority_revision, settings_revision = (
        _binding.bind_coding_current_preview_query(
            self.workspace, workspace_guard=self._assert_workspace_identity
        ).owner_revisions()
    )

    def desired_revision(document: dict[str, object]) -> int:
        revisions = document.get("ownerRevisions")
        value = revisions.get("desiredState") if isinstance(revisions, dict) else None
        if type(value) is not int:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
        return value

    first_revision = desired_revision(before)
    last_revision = desired_revision(after)
    drift: set[str] = set()
    if first_revision != last_revision:
        drift.add("desired_state_drift")
    if before.get("ownerRevisions") != after.get("ownerRevisions"):
        drift.add("management_owner_drift")
    if preview.get("productPolicyRevision") != policy_revision:
        drift.add("product_policy_drift")
    if preview.get("productAuthorityRevision") != authority_revision:
        drift.add("product_authority_drift")
    if preview.get("disabledSkillSettingsRevision") != settings_revision:
        drift.add("disabled_skill_settings_drift")
    if drift:
        gaps = preview.get("evidenceGaps")
        if not isinstance(gaps, list):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_002"])
        preview = {
            **preview,
            "evidenceGaps": sorted(set(gaps) | drift | {"stale_snapshot"}),
        }
    return project_coding_plugin_support_status(
        after, preview, correlation_id=correlation_id
    )


def open_read_client(
    workspace: str | Path,
    *,
    expected_workspace_identity: tuple[int, int] | None = None,
) -> _binding.CodingPluginManagementReadClientV1:
    root = require_workspace_directory(workspace, unavailable=_WORKSPACE_UNAVAILABLE)
    identity = capture_workspace_directory_identity(
        root, unavailable=_WORKSPACE_UNAVAILABLE
    )
    if (
        expected_workspace_identity is not None
        and identity != expected_workspace_identity
    ):
        raise _binding.CodingPluginManagementReadSdkError(
            "Coding management workspace changed",
            code="coding_management_workspace_changed",
        )
    client = _binding.CodingPluginManagementReadClientV1(
        workspace=root,
        layout=_binding.resolve_coding_plugin_lifecycle_state_layout(root),
        workspace_identity=identity,
    )
    client.assert_workspace_current()
    return client


def read_fenced_snapshot(
    self: _binding.CodingPluginManagementReadClientV1,
    query: _binding.PluginManagementQueryV1,
) -> _binding.PluginManagementProjectionV1:
    if (
        not isinstance(query, _binding.PluginManagementQueryV1)
        or query.product_id != _binding.CODING_PRODUCT_ID
        or query.installation_scope != "workspace"
        or query.scope_id != self.layout.scope_id
    ):
        raise ValueError("Plugin management read changed workspace scope")
    self._assert_workspace_identity()
    projection = _binding.build_coding_fenced_product_management_cli_ports(
        self.layout, workspace_guard=self._assert_workspace_identity
    ).queries.snapshot(query)
    self._assert_workspace_identity()
    return projection
