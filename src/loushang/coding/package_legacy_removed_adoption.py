"""Replay accepted old local removals into Product Desired State."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_builtin_adoption import _key, _require_bootstrap_history
from .package_legacy_removed_acceptance import (
    CodingLegacyRemovedAcceptanceV1,
    accept_coding_first_b_removed_local,
)
from .package_legacy_review import (
    shared_coding_legacy_builtin_removal_operation_id,
)
from .package_product_runtime import (
    CodingFencedProductApplicationOwner,
    _bootstrap_coding_builtin_plugin,
    open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


def adopt_coding_first_b_removed_local(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyRemovedAcceptanceV1:
    """Write the accepted absent choices and bootstrap current builtin choices."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        receipt = accept_coding_first_b_removed_local(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        )
    finally:
        epoch_runtime.close()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        product = owner.runtime_owner.product_owner
        removed_ids = {
            *(item.plugin_id for item in receipt.review.removed_local),
            *receipt.review.removed_builtin_ids,
        }
        for plugin_id in sorted(removed_ids):
            _preserve_removed(owner, receipt, plugin_id)
        disabled = {item.plugin_id for item in receipt.review.disabled_plugins}
        disabled.update(
            item.plugin_id
            for item in receipt.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        for plugin_id in _BUILTINS:
            if plugin_id in removed_ids:
                continue
            key = _key(owner, plugin_id)
            history = tuple(
                item
                for item in product.desired_state.transitions()
                if item.mutation.installation_key == key
            )
            if history:
                _require_bootstrap_history(owner, plugin_id, history)
                if getattr(history[-1].mutation, "actor_id", None) != product.actor_id:
                    continue
            _bootstrap_coding_builtin_plugin(
                owner, plugin_id, enable=plugin_id not in disabled
            )
        return receipt
    finally:
        owner.close()


def _removed_operation_id(
    receipt: CodingLegacyRemovedAcceptanceV1, plugin_id: str
) -> str:
    if plugin_id == "coding.base":
        # Base first becomes removable in this migration slice. Reuse the
        # active-local fence identity without changing old local/LSP/Arch IDs.
        return shared_coding_legacy_builtin_removal_operation_id(
            receipt.review.first_fence_id, plugin_id
        )
    return "coding-legacy-local-remove:" + sha256(
        f"{receipt.review.store_id}\0{receipt.review.review_id}\0{plugin_id}".encode()
    ).hexdigest()


def _preserve_removed(
    owner: CodingFencedProductApplicationOwner,
    receipt: CodingLegacyRemovedAcceptanceV1,
    plugin_id: str,
) -> None:
    product = owner.runtime_owner.product_owner
    key = _key(owner, plugin_id)
    operation_id = _removed_operation_id(receipt, plugin_id)
    history = tuple(
        item
        for item in product.desired_state.transitions()
        if item.mutation.installation_key == key
    )
    if history:
        first = history[0]
        if (
            first.mutation.operation_id != operation_id
            or not isinstance(first.mutation, PluginDesiredStateMutationV1)
            or first.mutation.actor_id != product.actor_id
            or first.committed_state.selection.desired_state != "absent"
        ):
            raise RuntimeError("Coding removed local Product history changed")
        return
    command = PluginManagementCommandV1(
        action="remove",
        mutation=PluginDesiredStateMutationV1(
            operation_id=operation_id,
            idempotency_key=operation_id,
            expected_inventory_revision=product.desired_state.snapshot().inventory_revision,
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id=product.actor_id,
            policy_revision=product.desired_policy_revision,
        ),
    )
    result = product.management.submit(command)
    if result.result is None or result.result.disposition != "succeeded":
        raise RuntimeError("Coding removed local Product tombstone refused")


__all__ = ["adopt_coding_first_b_removed_local"]
