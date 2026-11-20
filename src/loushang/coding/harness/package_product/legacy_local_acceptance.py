"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_local_acceptance as _binding


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
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_PROGRAM_VALUES["value_001"]
        )
    legacy_state = _binding.CodingFirstBLegacyStateObserver(
        lifecycle, epoch_runtime
    ).observe(
        store_id=fence.store_id,
        legacy_root_identity=fence.request.legacy_root_identity,
    )
    binding = selected.binding
    source_raw = _binding.read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name=_binding._LEGACY_PROGRAM_VALUES["value_002"],
        maximum_bytes=2 * 1024 * 1024,
    )
    if source_raw is None:
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_PROGRAM_VALUES["value_003"]
        )
    source_projection = _binding.json.loads(source_raw)
    source = _binding.classify_coding_legacy_source_configuration(source_projection)
    configured = _binding.match_coding_legacy_local_skill_configured_source(
        source_projection,
        source_identity=binding.source_identity,
        installed_source_identities=tuple(
            item.binding.source_identity for item in inventory.inventory.active_local
        ),
    )
    expected_prefix = (
        "loushang_legacy_"
        + _binding.sha256(
            f"{plugin_id}\0{binding.content_digest}".encode()
        ).hexdigest()[:24]
    )
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
            if item
            in {
                _binding._LEGACY_PROGRAM_VALUES["value_005"],
                _binding._LEGACY_PROGRAM_VALUES["value_006"],
                _binding._LEGACY_PROGRAM_VALUES["value_007"],
            }
        )
        or review.configured_plugin_source_scope
        != (None if configured is None else configured.scope)
    ):
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_PROGRAM_VALUES["value_004"]
        )


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
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_001"]
        )
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    proposed = _binding.CodingLegacyLocalAcceptanceV1.create(
        review, resource_kind=resource_kind
    )

    def require_current_review() -> None:
        _binding._require_live_resource_kind(
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
            raise _binding.CodingLegacyLocalAcceptanceError(
                _binding._LEGACY_ADOPTION_VALUES["value_003"]
            )

    return _binding._acceptance_protocol(epoch_runtime).accept(
        proposed,
        plugin_id=review.plugin_id,
        installation_key=lambda: _binding.PluginInstallationKeyV1(
            product_id=_binding._LEGACY_ADOPTION_VALUES["value_004"],
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
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_005"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_002"]
        )
    record = _binding._acceptance_protocol(epoch_runtime).reopen(plugin_id)
    if record is None:
        return None
    _binding._require_frozen_review(
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

    record = _binding.reopen_coding_legacy_installed_local_acceptance(
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
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_ADOPTION_VALUES["value_006"]
        )
    epoch_runtime.assert_current()
    return record


def validate_acceptance(self: _binding.CodingLegacyLocalAcceptanceV1) -> None:
    if (
        not isinstance(self.review, _binding.CodingLegacyLocalAdoptionReviewV1)
        or type(self.acceptance_version) is not int
        or (self.acceptance_version, self.resource_kind)
        not in {
            (1, _binding._LEGACY_RECORD_SKILL),
            (2, _binding._LEGACY_RECORD_PROMPT),
            (3, _binding._LEGACY_RECORD_THEME),
        }
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_001"])
    identity = {
        "acceptanceVersion": self.acceptance_version,
        "reviewId": self.review.review_id,
        "pluginId": self.review.plugin_id,
    }
    if self.acceptance_version >= 2:
        identity["resourceKind"] = self.resource_kind
    if (
        self.acceptance_id
        != _binding.sha256(_binding.canonical_json_bytes(identity)).hexdigest()
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_002"])


def create_acceptance(
    cls: type[_binding.CodingLegacyLocalAcceptanceV1],
    review: _binding.CodingLegacyLocalAdoptionReviewV1,
    *,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> _binding.CodingLegacyLocalAcceptanceV1:
    if not isinstance(review, _binding.CodingLegacyLocalAdoptionReviewV1):
        raise TypeError(_binding._LEGACY_RECORD_VALUES["value_003"])
    if any(
        item.plugin_id not in _binding._BUILTINS for item in review.disabled_plugins
    ):
        raise ValueError("Legacy local adoption supports built-in disables only")
    if resource_kind not in {
        _binding._LEGACY_RECORD_SKILL,
        _binding._LEGACY_RECORD_PROMPT,
        _binding._LEGACY_RECORD_THEME,
    }:
        raise ValueError("Unsupported legacy local Resource type")
    acceptance_version = {
        _binding._LEGACY_RECORD_SKILL: 1,
        _binding._LEGACY_RECORD_PROMPT: 2,
        _binding._LEGACY_RECORD_THEME: 3,
    }[resource_kind]
    identity = {
        "acceptanceVersion": acceptance_version,
        "reviewId": review.review_id,
        "pluginId": review.plugin_id,
    }
    if acceptance_version >= 2:
        identity["resourceKind"] = resource_kind
    return cls(
        review,
        _binding.sha256(_binding.canonical_json_bytes(identity)).hexdigest(),
        acceptance_version=acceptance_version,
        resource_kind=resource_kind,
    )


def decode_acceptance(
    cls: type[_binding.CodingLegacyLocalAcceptanceV1], value: object
) -> _binding.CodingLegacyLocalAcceptanceV1:
    if type(value) is not dict or set(value) not in (
        {"acceptanceId", "acceptanceVersion", "review"},
        {"acceptanceId", "acceptanceVersion", "review", "resourceKind"},
    ):
        raise _binding.JournalCodecError(
            _binding._LEGACY_RECORD_VALUES["value_004"],
            code=_binding._LEGACY_RECORD_VALUES["value_005"],
        )
    try:
        if type(value["acceptanceVersion"]) is not int:
            raise ValueError(_binding._LEGACY_RECORD_VALUES["value_006"])
        resource_kind: Literal["skill", "prompt", "theme"]
        if value["acceptanceVersion"] == 1 and "resourceKind" not in value:
            resource_kind = _binding._LEGACY_RECORD_SKILL
        elif (
            value["acceptanceVersion"] == 2
            and value.get("resourceKind") == _binding._LEGACY_RECORD_PROMPT
        ):
            resource_kind = _binding._LEGACY_RECORD_PROMPT
        elif (
            value["acceptanceVersion"] == 3
            and value.get("resourceKind") == _binding._LEGACY_RECORD_THEME
        ):
            resource_kind = _binding._LEGACY_RECORD_THEME
        else:
            raise ValueError(_binding._LEGACY_RECORD_VALUES["value_007"])
        record = cls.create(
            _binding.CodingLegacyLocalAdoptionReviewV1.from_dict(value["review"]),
            resource_kind=resource_kind,
        )
        if record.acceptance_id != value["acceptanceId"]:
            raise ValueError(_binding._LEGACY_RECORD_VALUES["value_002"])
        return record
    except (TypeError, ValueError) as exc:
        raise _binding.JournalCodecError(
            _binding._LEGACY_RECORD_VALUES["value_004"],
            code=_binding._LEGACY_RECORD_VALUES["value_005"],
        ) from exc


def require_live_resource_kind(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
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
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_CHAIN_VALUES["value_002"]
        ) from exc
    if inspected.resource_kind != resource_kind:
        raise _binding.CodingLegacyLocalAcceptanceError(
            _binding._LEGACY_CHAIN_VALUES["value_001"]
        )
