"""Replayable Product Desired adoption for a reviewed old builtin-only state."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_builtin_acceptance import (
    CodingLegacyBuiltinOnlyAcceptanceV1,
    accept_coding_first_b_builtin_only,
)
from .package_product_runtime import (
    CodingFencedProductApplicationOwner,
    _bootstrap_coding_builtin_plugin,
    open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


def adopt_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool = False,
) -> CodingLegacyBuiltinOnlyAcceptanceV1:
    """Accept the old review once and seed only its builtin Product choices."""

    if type(windows_candidate) is not bool:
        raise TypeError("Windows builtin migration candidate must be explicit")
    if os.name == "nt" and not windows_candidate:
        raise RuntimeError("Windows builtin migration candidate is not admitted")
    if os.name != "nt" and windows_candidate:
        raise ValueError("Windows builtin migration candidate requires Windows")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        PackageProductWindowsFencedRuntimeOwner
        if os.name == "nt"
        else PackageProductPosixFencedRuntimeOwner
    )
    epoch_runtime = epoch_owner_type.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        receipt = accept_coding_first_b_builtin_only(
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
        windows_candidate=windows_candidate,
    )
    try:
        product = owner.runtime_owner.product_owner
        disabled = {item.plugin_id for item in receipt.review.disabled_plugins}
        disabled.update(
            item.plugin_id
            for item in receipt.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        for plugin_id in receipt.review.removed_builtin_ids:
            _preserve_removed_builtin(owner, receipt, plugin_id)
        for plugin_id in _BUILTINS:
            if plugin_id in receipt.review.removed_builtin_ids:
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


def _require_bootstrap_history(
    owner: CodingFencedProductApplicationOwner,
    plugin_id: str,
    history: tuple[object, ...],
) -> None:
    product = owner.runtime_owner.product_owner
    operation_id = (
        "coding-builtin-bootstrap:"
        + sha256(
            f"{owner.epoch_runtime.registry.store_id}:{plugin_id}".encode()
        ).hexdigest()
    )
    command_id = product.settled_install_command_id(
        operation_id=operation_id, plugin_id=plugin_id
    )
    first = history[0]
    mutation = getattr(first, "mutation", None)
    committed = getattr(first, "committed_state", None)
    selection = getattr(committed, "selection", None)
    if (
        command_id is None
        or not isinstance(mutation, PluginDesiredStateMutationV1)
        or mutation.operation_id != command_id
        or mutation.actor_id != product.actor_id
        or getattr(selection, "desired_state", None) != "installed_disabled"
        or getattr(selection, "package_revision", None) is None
    ):
        raise RuntimeError("Coding builtin-only Product bootstrap history changed")
    if len(history) > 1:
        second = history[1]
        second_mutation = getattr(second, "mutation", None)
        second_selection = getattr(
            getattr(second, "committed_state", None), "selection", None
        )
        if getattr(second_mutation, "actor_id", None) == product.actor_id and (
            not isinstance(second_mutation, PluginDesiredStateMutationV1)
            or not second_mutation.operation_id.startswith(
                "coding-builtin-bootstrap-enable:"
            )
            or getattr(second_selection, "desired_state", None) != "installed_enabled"
            or getattr(second_selection, "package_revision", None)
            != getattr(selection, "package_revision", None)
        ):
            raise RuntimeError("Coding builtin-only Product enable history changed")


def _key(
    owner: CodingFencedProductApplicationOwner, plugin_id: str
) -> PluginInstallationKeyV1:
    product = owner.runtime_owner.product_owner
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )


def _preserve_removed_builtin(
    owner: CodingFencedProductApplicationOwner,
    receipt: CodingLegacyBuiltinOnlyAcceptanceV1,
    plugin_id: str,
) -> None:
    product = owner.runtime_owner.product_owner
    key = _key(owner, plugin_id)
    operation_id = receipt.review.removed_builtin_operation_id(plugin_id)
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
            raise RuntimeError("Coding removed builtin Product history changed")
        return
    command = PluginManagementCommandV1(
        action="remove",
        mutation=PluginDesiredStateMutationV1(
            operation_id=operation_id,
            idempotency_key=operation_id,
            expected_inventory_revision=(
                product.desired_state.snapshot().inventory_revision
            ),
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id=product.actor_id,
            policy_revision=product.desired_policy_revision,
        ),
    )
    result = product.management.submit(command)
    if result.result is None or result.result.disposition != "succeeded":
        raise RuntimeError("Coding removed builtin Product tombstone refused")


__all__ = ["adopt_coding_first_b_builtin_only"]
