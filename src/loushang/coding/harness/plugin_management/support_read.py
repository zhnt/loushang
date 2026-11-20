"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import read_sdk as _binding


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
