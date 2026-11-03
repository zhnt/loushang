"""Read-only proof that an explicitly accepted old Skill finished Product adoption."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.records import (
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_data_trust import trust_class_for_legacy_data_resource
from .package_legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_skill_snapshot,
)
from .package_legacy_source_consumption import (
    coding_accepted_legacy_local_source_consumed,
)
from .package_product_preview import CodingFencedProductReadOnlyPreviewOwner
from .package_product_runtime import CODING_PACKAGE_PRODUCT_POLICY_REVISION

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


def coding_legacy_local_skill_adoption_settled(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: Path,
) -> bool:
    """Join frozen acceptance to Product handoffs and Desired history only.

    A later operator disable or remove does not erase a completed adoption.
    Missing or partial evidence returns false; corrupt evidence raises.
    """

    return coding_legacy_local_data_adoption_settled(
        lifecycle, plugin_id=plugin_id, workspace=workspace, resource_kind="skill"
    )


def coding_legacy_local_data_adoption_settled(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: Path,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> bool:
    """Check one typed old local adoption without mutating Product state."""

    if resource_kind not in {"skill", "prompt", "theme"}:
        raise ValueError("Unsupported legacy Resource type")

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        require_coding_fenced_single_legacy_skill_snapshot(
            lifecycle, runtime, plugin_id=plugin_id
        )
        accepted = reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            runtime,
            plugin_id=plugin_id,
            policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        source_consumed = (
            False
            if accepted is None or accepted.resource_kind != resource_kind
            else coding_accepted_legacy_local_source_consumed(
                lifecycle,
                runtime,
                accepted,
                SettingsManager(
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                ),
            )
        )
    finally:
        runtime.close()
    if accepted is None or not source_consumed:
        return False

    with CodingFencedProductReadOnlyPreviewOwner.open(lifecycle) as preview:
        matches = tuple(
            item
            for item in preview.policy.bindings
            if item.plugin_id == plugin_id
            and item.source_trust_class
            == trust_class_for_legacy_data_resource(resource_kind)
        )
        if (
            len(matches) != 1
            or matches[0].artifact_digest != accepted.review.wheel_artifact_digest
            or Path(matches[0].source_identity).name != accepted.review.wheel_filename
        ):
            return False
        handoffs = PackageRetentionHandoffJournal(
            epoch.control_root / "product-state" / "handoff.jsonl"
        )
        desired = preview.selected_manifests.root_reader.desired_state
        before, history = desired.capture_read_only()

        def transitions_for(selected_plugin: str):
            key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=selected_plugin,
            )
            return tuple(
                item for item in history if item.mutation.installation_key == key
            )

        old_install_id = (
            "coding-legacy-local-install:"
            + sha256(
                f"{accepted.review.store_id}\0{accepted.acceptance_id}".encode()
            ).hexdigest()
        )
        command_id = _settled_command(
            handoffs,
            operation_id=old_install_id,
            plugin_id=plugin_id,
            scope_id=lifecycle.scope_id,
        )
        old_events = transitions_for(plugin_id)
        if (
            command_id is None
            or not old_events
            or not isinstance(old_events[0], PluginDesiredStateTransitionV1)
            or old_events[0].mutation.operation_id != command_id
            or old_events[0].committed_state.selection.desired_state
            != "installed_disabled"
            or old_events[0].committed_state.selection.package_revision is None
            or old_events[
                0
            ].committed_state.selection.package_revision.package_source_identity
            != matches[0].source_identity
        ):
            return False
        if accepted.review.desired_state == "installed_enabled":
            enable_id = (
                "coding-legacy-local-enable:"
                + sha256(
                    f"{accepted.review.store_id}\0{accepted.acceptance_id}".encode()
                ).hexdigest()
            )
            if (
                len(old_events) < 2
                or not isinstance(old_events[1], PluginDesiredStateTransitionV1)
                or old_events[1].mutation.operation_id != enable_id
                or old_events[1].committed_state.selection.desired_state
                != "installed_enabled"
                or old_events[1].committed_state.selection.package_revision
                != old_events[0].committed_state.selection.package_revision
            ):
                return False

        disabled_builtins = {
            item.plugin_id for item in accepted.review.disabled_plugins
        }
        disabled_builtins.update(
            item.plugin_id
            for item in accepted.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        for builtin_id in _BUILTINS:
            events = transitions_for(builtin_id)
            if builtin_id in accepted.review.removed_builtin_ids:
                if (
                    not events
                    or events[0].mutation.operation_id
                    != accepted.review.removed_builtin_operation_id(builtin_id)
                    or events[0].committed_state.selection.desired_state != "absent"
                    or any(
                        event.mutation.operation_id.startswith(
                            "coding-builtin-bootstrap:"
                        )
                        for event in events[1:]
                    )
                ):
                    return False
                continue
            operation_id = (
                "coding-builtin-bootstrap:"
                + sha256(f"{epoch.store_id}:{builtin_id}".encode()).hexdigest()
            )
            command_id = _settled_command(
                handoffs,
                operation_id=operation_id,
                plugin_id=builtin_id,
                scope_id=lifecycle.scope_id,
            )
            builtin_source = tuple(
                item.source_identity
                for item in preview.policy.bindings
                if item.plugin_id == builtin_id
            )
            if (
                command_id is None
                or len(builtin_source) != 1
                or not events
                or not isinstance(events[0], PluginDesiredStateTransitionV1)
                or events[0].mutation.operation_id != command_id
                or events[0].committed_state.selection.desired_state
                != "installed_disabled"
                or events[0].committed_state.selection.package_revision is None
                or events[
                    0
                ].committed_state.selection.package_revision.package_source_identity
                != builtin_source[0]
            ):
                return False
            if builtin_id in disabled_builtins:
                if any(
                    event.mutation.operation_id.startswith(
                        "coding-builtin-bootstrap-enable:"
                    )
                    for event in events[1:]
                ):
                    return False
            elif (
                len(events) < 2
                or not isinstance(events[1], PluginDesiredStateTransitionV1)
                or events[1].committed_state.selection.desired_state
                != "installed_enabled"
                or events[1].committed_state.selection.package_revision
                != events[0].committed_state.selection.package_revision
            ):
                return False
        after, later_history = desired.capture_read_only()
        preview.epoch_runtime.assert_current()
        return before == after and history == later_history


def _settled_command(
    handoffs: PackageRetentionHandoffJournal,
    *,
    operation_id: str,
    plugin_id: str,
    scope_id: str,
) -> str | None:
    receipt = handoffs.read_operation(operation_id)
    if receipt is None or receipt.state != "settled":
        return None
    request = receipt.request.desired_request
    if (
        receipt.desired_receipt is None
        or receipt.desired_receipt.request != request
        or request.operation_id != operation_id
        or request.plugin_id != plugin_id
        or request.product_id != "coding"
        or request.scope_id != scope_id
    ):
        raise ValueError("Coding legacy adoption handoff changed")
    return request.command_id


__all__ = [
    "coding_legacy_local_data_adoption_settled",
    "coding_legacy_local_skill_adoption_settled",
]
