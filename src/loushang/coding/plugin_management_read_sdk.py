"""Local read-only Coding Plugin management SDK over scoped Harness queries.

This module is separate from the public Plugin *author* SDK. Opening a client
does not activate Product state, create a Session, or grant command authority.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_management_cli import (
    build_coding_fenced_product_management_cli_ports,
)
from loushang.coding.plugin_management_cli import (
    build_coding_plugin_management_cli_read_binding,
)
from loushang.coding.plugin_management_explanation import (
    bind_coding_plugin_operation_explanation_query,
)
from loushang.coding.plugin_management_preview import (
    bind_coding_current_preview_query,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.plugin_management.application import (
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewRequestV1,
    project_plugin_current_preview,
)
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationRequestV1,
    project_plugin_operation_explanation,
)


class CodingPluginManagementReadSdkError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPluginManagementReadClientV1:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_identity: tuple[int, int]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace, Path)
            or not self.workspace.is_absolute()
            or self.workspace != self.workspace.resolve(strict=True)
            or not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or self.layout
            != resolve_coding_plugin_lifecycle_state_layout(self.workspace)
            or type(self.workspace_identity) is not tuple
            or len(self.workspace_identity) != 2
            or any(
                type(item) is not int or item < 0 for item in self.workspace_identity
            )
        ):
            raise ValueError("Coding management read workspace is invalid")

    @property
    def product_id(self) -> str:
        return CODING_PRODUCT_ID

    @property
    def installation_scope(self) -> Literal["workspace"]:
        return "workspace"

    @property
    def scope_id(self) -> str:
        return self.layout.scope_id

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        if (
            not isinstance(query, PluginManagementQueryV1)
            or query.product_id != CODING_PRODUCT_ID
            or query.installation_scope != "workspace"
            or query.scope_id != self.layout.scope_id
        ):
            raise ValueError("Plugin management read changed workspace scope")
        self._assert_workspace_identity()
        projection = build_coding_fenced_product_management_cli_ports(
            self.layout, workspace_guard=self._assert_workspace_identity
        ).queries.snapshot(query)
        self._assert_workspace_identity()
        return projection

    def management_snapshot(
        self,
        *,
        correlation_id: str,
        settings_manager: object | None = None,
        plugin_ids: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Read the management owner projection without startup or repair."""

        self._assert_workspace_identity()
        binding = build_coding_plugin_management_cli_read_binding(
            self.workspace,
            settings_manager,
            workspace_identity=self.workspace_identity,
        )
        if binding.scope_id != self.layout.scope_id:
            raise ValueError("Plugin management read changed workspace scope")
        projection = binding.query(
            correlation_id=correlation_id,
            plugin_ids=plugin_ids,
        ).to_dict()
        self._assert_workspace_identity()
        return projection

    def preview_current(
        self,
        *,
        correlation_id: str,
        composition_set_id: str = "coding-standard",
    ) -> dict[str, object]:
        self._assert_workspace_identity()
        preview = project_plugin_current_preview(
            bind_coding_current_preview_query(
                self.workspace, workspace_guard=self._assert_workspace_identity
            ),
            PluginCurrentPreviewRequestV1(
                correlation_id=correlation_id,
                product_id=CODING_PRODUCT_ID,
                scope_id=self.layout.scope_id,
                composition_set_id=composition_set_id,
            ),
        )
        self._assert_workspace_identity()
        return preview

    def support_status(
        self,
        *,
        correlation_id: str,
        composition_set_id: str = "coding-standard",
    ) -> dict[str, object]:
        """Join management and Product preview without asserting Session use."""

        from loushang.coding.plugin_support_status import (
            project_coding_plugin_support_status,
        )

        before = self.management_snapshot(correlation_id=f"{correlation_id}:before")
        preview = self.preview_current(
            correlation_id=f"{correlation_id}:preview",
            composition_set_id=composition_set_id,
        )
        after = self.management_snapshot(correlation_id=f"{correlation_id}:after")
        policy_revision, authority_revision, settings_revision = (
            bind_coding_current_preview_query(
                self.workspace, workspace_guard=self._assert_workspace_identity
            ).owner_revisions()
        )
        def desired_revision(document: dict[str, object]) -> int:
            revisions = document.get("ownerRevisions")
            value = revisions.get("desiredState") if isinstance(revisions, dict) else None
            if type(value) is not int:
                raise ValueError("Plugin support Desired State revision is invalid")
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
                raise ValueError("Plugin support Product evidence gaps are invalid")
            preview = {
                **preview,
                "evidenceGaps": sorted(set(gaps) | drift | {"stale_snapshot"}),
            }
        return project_coding_plugin_support_status(
            after, preview, correlation_id=correlation_id
        )

    def explain_operation(
        self,
        operation_id: str,
        *,
        correlation_id: str,
    ) -> dict[str, object]:
        self._assert_workspace_identity()
        explanation = project_plugin_operation_explanation(
            bind_coding_plugin_operation_explanation_query(
                self.workspace, workspace_guard=self._assert_workspace_identity
            ),
            PluginOperationExplanationRequestV1(
                correlation_id=correlation_id,
                product_id=CODING_PRODUCT_ID,
                scope_id=self.layout.scope_id,
                operation_id=operation_id,
            ),
        )
        self._assert_workspace_identity()
        return explanation

    def _assert_workspace_identity(self) -> None:
        try:
            metadata = self.workspace.lstat()
            current = self.workspace.resolve(strict=True)
        except OSError as exc:
            raise CodingPluginManagementReadSdkError(
                "Coding management workspace changed",
                code="coding_management_workspace_changed",
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or current != self.workspace
            or (metadata.st_dev, metadata.st_ino) != self.workspace_identity
        ):
            raise CodingPluginManagementReadSdkError(
                "Coding management workspace changed",
                code="coding_management_workspace_changed",
            )

    def assert_workspace_current(self) -> None:
        """Keep the original workspace identity across a CLI or RPC operation."""

        self._assert_workspace_identity()


def open_coding_plugin_management_read_client(
    workspace: str | Path,
    *,
    expected_workspace_identity: tuple[int, int] | None = None,
) -> CodingPluginManagementReadClientV1:
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Plugin management workspace is unavailable")
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Plugin management workspace is unavailable")
    identity = (metadata.st_dev, metadata.st_ino)
    if expected_workspace_identity is not None and identity != expected_workspace_identity:
        raise CodingPluginManagementReadSdkError(
            "Coding management workspace changed",
            code="coding_management_workspace_changed",
        )
    client = CodingPluginManagementReadClientV1(
        workspace=root,
        layout=resolve_coding_plugin_lifecycle_state_layout(root),
        workspace_identity=identity,
    )
    client.assert_workspace_current()
    return client


def bind_coding_plugin_management_rpc_query(
    workspace: str | Path,
) -> CodingPluginManagementReadClientV1:
    return open_coding_plugin_management_read_client(workspace)


__all__ = [
    "CodingPluginManagementReadClientV1",
    "CodingPluginManagementReadSdkError",
    "bind_coding_plugin_management_rpc_query",
    "open_coding_plugin_management_read_client",
]
