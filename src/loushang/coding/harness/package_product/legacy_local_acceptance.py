"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_local_acceptance as _binding
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    legacy_source_wheel_prefix,
)

from .epoch_identity import matches_epoch_layout
from .legacy_local_review import observe_frozen_local_source

_RESOURCE_KIND_VERSION = {"skill": 1, "prompt": 2, "theme": 3}


def require_frozen_review(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    review: _binding.CodingLegacyLocalAdoptionReviewV1,
    *,
    plugin_id: str,
    policy_revision: str,
) -> None:
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    inventory = _binding.read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    )
    selected = next(
        (
            item
            for item in inventory.inventory.active_local
            if item.binding.plugin_id == plugin_id
        ),
        None,
    )
    if fence is None or switch is None or selected is None:
        raise _acceptance_error("acceptance lost its first-B Installation")
    binding = selected.binding
    legacy_state, source, configured = observe_frozen_local_source(
        lifecycle,
        epoch_runtime,
        fence,
        inventory,
        binding.source_identity,
        missing_source=lambda: _acceptance_error(
            "acceptance lost its Source configuration"
        ),
    )
    expected_prefix = legacy_source_wheel_prefix(plugin_id, binding.content_digest)
    if (
        review.store_id != fence.store_id
        or review.namespace_id != switch.namespace_id
        or review.scope_id != lifecycle.scope_id
        or review.first_fence_id != inventory.first_fence_id
        or review.snapshot_receipt_id != inventory.snapshot_receipt_id
        or review.legacy_root_identity != legacy_state.legacy_root_identity
        or review.legacy_state_evidence_id != legacy_state.evidence_id
        or review.legacy_state_digest != legacy_state.state_digest
        or review.legacy_entry_count != legacy_state.entry_count
        or review.legacy_byte_count != legacy_state.byte_count
        or review.plugin_id != plugin_id
        or review.desired_state != selected.desired_state
        or review.legacy_source_identity != binding.source_identity
        or review.legacy_binding_digest != binding.binding_digest
        or review.legacy_lockfile_digest != binding.lockfile_digest
        or review.legacy_desired_journal_digest
        != inventory.inventory.desired_journal_digest
        or review.source_content_digest != binding.content_digest
        or review.manifest_digest != binding.manifest_digest
        or review.dependency_lock_digest != binding.dependency_lock.digest
        or review.wheel_filename != f"{expected_prefix}-1-py3-none-any.whl"
        or review.policy_revision != policy_revision
        or review.disabled_plugins != source.disabled_plugins
        or review.builtin_intent != inventory.inventory.builtin_intent
        or review.removed_builtin_ids
        != tuple(
            item
            for item in inventory.inventory.removed_plugin_ids
            if item in _binding._BUILTINS
        )
        or review.configured_plugin_source_scope
        != (None if configured is None else configured.scope)
    ):
        raise _acceptance_error("acceptance changed first-B evidence")


def accept_local_review(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
    accepted_review_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> _binding.CodingLegacyLocalAcceptanceV1:
    """Accept one exact current review while that Installation is untouched in B."""

    review = _binding.review_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )
    if accepted_review_id != review.review_id:
        raise _acceptance_error("review ID changed")
    _require_current_epoch(lifecycle, epoch_runtime)
    proposed = _binding.CodingLegacyLocalAcceptanceV1.create(
        review, resource_kind=resource_kind
    )

    def require_current_review() -> None:
        require_live_resource_kind(
            lifecycle, epoch_runtime, plugin_id=plugin_id, resource_kind=resource_kind
        )
        if (
            _binding.review_coding_legacy_installed_local_source(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                policy_revision=policy_revision,
            )
            != review
        ):
            raise _acceptance_error("review changed before acceptance")

    return _binding._acceptance_protocol(epoch_runtime).accept(
        proposed,
        plugin_id=review.plugin_id,
        installation_key=lambda: _binding.PluginInstallationKeyV1(
            product_id=_binding._PRODUCT_ID,
            installation_scope="workspace",
            scope_id=review.scope_id,
            plugin_id=review.plugin_id,
        ),
        require_current_review=require_current_review,
    )


def reopen_local_acceptance(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> _binding.CodingLegacyLocalAcceptanceV1 | None:
    """Reopen a receipt against frozen first-B evidence without live Source."""

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError(f"{_binding._ACCEPTANCE_LABEL} Plugin identity is required")
    _require_current_epoch(lifecycle, epoch_runtime)
    record = _binding._acceptance_protocol(epoch_runtime).reopen(plugin_id)
    if record is None:
        return None
    require_frozen_review(
        lifecycle,
        epoch_runtime,
        record.review,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    epoch_runtime.assert_current()
    return record


def read_local_acceptance(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> _binding.CodingLegacyLocalAcceptanceV1 | None:
    """Additionally require that the original live Source still matches."""

    record = reopen_local_acceptance(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    if record is None:
        return None
    review = _binding.review_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )
    if record != _binding.CodingLegacyLocalAcceptanceV1.create(
        review, resource_kind=record.resource_kind
    ):
        raise _acceptance_error("acceptance conflicts with current review")
    epoch_runtime.assert_current()
    return record


def _require_current_epoch(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
) -> None:
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if not matches_epoch_layout(epoch_runtime, epoch):
        raise _acceptance_error("Product epoch changed")


def _acceptance_error(reason: str) -> _binding.CodingLegacyLocalAcceptanceError:
    return _binding.CodingLegacyLocalAcceptanceError(
        f"{_binding._ACCEPTANCE_LABEL} {reason}"
    )


def validate_acceptance(self: _binding.CodingLegacyLocalAcceptanceV1) -> None:
    if (
        not isinstance(self.review, _binding.CodingLegacyLocalAdoptionReviewV1)
        or type(self.acceptance_version) is not int
        or _RESOURCE_KIND_VERSION.get(self.resource_kind) != self.acceptance_version
    ):
        raise ValueError(f"{_binding._ACCEPTANCE_LABEL} acceptance record is invalid")
    if self.acceptance_id != _acceptance_id(
        self.review, self.acceptance_version, self.resource_kind
    ):
        raise ValueError(f"{_binding._ACCEPTANCE_LABEL} acceptance identity changed")


def create_acceptance(
    cls: type[_binding.CodingLegacyLocalAcceptanceV1],
    review: _binding.CodingLegacyLocalAdoptionReviewV1,
    *,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> _binding.CodingLegacyLocalAcceptanceV1:
    if not isinstance(review, _binding.CodingLegacyLocalAdoptionReviewV1):
        raise TypeError(f"{_binding._ACCEPTANCE_LABEL} review is required")
    if any(
        item.plugin_id not in _binding._BUILTINS for item in review.disabled_plugins
    ):
        raise ValueError("Legacy local adoption supports built-in disables only")
    acceptance_version = _RESOURCE_KIND_VERSION.get(resource_kind)
    if acceptance_version is None:
        raise ValueError("Unsupported legacy local Resource type")
    return cls(
        review,
        _acceptance_id(review, acceptance_version, resource_kind),
        acceptance_version=acceptance_version,
        resource_kind=resource_kind,
    )


def _acceptance_id(
    review: _binding.CodingLegacyLocalAdoptionReviewV1,
    acceptance_version: int,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> str:
    identity = {
        "acceptanceVersion": acceptance_version,
        "reviewId": review.review_id,
        "pluginId": review.plugin_id,
    }
    if acceptance_version >= 2:
        identity["resourceKind"] = resource_kind
    return _binding.sha256(_binding.canonical_json_bytes(identity)).hexdigest()


def decode_acceptance(
    cls: type[_binding.CodingLegacyLocalAcceptanceV1], value: object
) -> _binding.CodingLegacyLocalAcceptanceV1:
    if type(value) is not dict or set(value) not in (
        {"acceptanceId", "acceptanceVersion", "review"},
        {"acceptanceId", "acceptanceVersion", "review", "resourceKind"},
    ):
        raise _binding.JournalCodecError(
            f"Invalid {_binding._ACCEPTANCE_LABEL} acceptance",
            code=_binding._ACCEPTANCE_CODEC_ERROR_CODE,
        )
    try:
        if type(value["acceptanceVersion"]) is not int:
            raise ValueError(
                f"Unsupported {_binding._ACCEPTANCE_LABEL} acceptance version"
            )
        resource_kind: Literal["skill", "prompt", "theme"]
        if value["acceptanceVersion"] == 1 and "resourceKind" not in value:
            resource_kind = "skill"
        elif value["acceptanceVersion"] == 2 and value.get("resourceKind") == "prompt":
            resource_kind = "prompt"
        elif value["acceptanceVersion"] == 3 and value.get("resourceKind") == "theme":
            resource_kind = "theme"
        else:
            raise ValueError(
                f"Unsupported {_binding._ACCEPTANCE_LABEL} acceptance type"
            )
        record = cls.create(
            _binding.CodingLegacyLocalAdoptionReviewV1.from_dict(value["review"]),
            resource_kind=resource_kind,
        )
        if record.acceptance_id != value["acceptanceId"]:
            raise ValueError(
                f"{_binding._ACCEPTANCE_LABEL} acceptance identity changed"
            )
        return record
    except (TypeError, ValueError) as exc:
        raise _binding.JournalCodecError(
            f"Invalid {_binding._ACCEPTANCE_LABEL} acceptance",
            code=_binding._ACCEPTANCE_CODEC_ERROR_CODE,
        ) from exc


def require_live_resource_kind(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    # Keep the cutover inspector out of the acceptance codec's import path.
    from loushang.coding.package.legacy_reacquisition import (
        reacquire_coding_legacy_installed_local_source,
    )
    from loushang.coding.package.legacy_skill_cutover_admission import (
        inspect_coding_legacy_local_data_wheel,
    )

    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    try:
        inspected = inspect_coding_legacy_local_data_wheel(reacquired.wheel)
    except (OSError, ValueError) as exc:
        raise _acceptance_error("Resource type is unsupported") from exc
    if inspected.resource_kind != resource_kind:
        raise _acceptance_error("Resource type differs from accepted route")
