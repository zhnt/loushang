"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_disabled_review as _binding


def review_disabled_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: _binding.SettingsManager,
) -> _binding.CodingLegacyDisabledOnlyReviewV1:
    """Review only the immutable first-fence snapshot, never live settings."""

    if not isinstance(settings_manager, _binding.SettingsManager):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_001"])
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if not isinstance(global_path, _binding.Path) or not isinstance(
        project_path, _binding.Path
    ):
        raise _binding.CodingLegacyDisabledOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_002"]
        )
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    if fence is None or switch is None:
        raise _binding.CodingLegacyDisabledOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_003"]
        )
    source = _binding.read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    if (
        not source.classification.disabled_plugins
        or source.classification.configured_source_keys
    ):
        raise _binding.CodingLegacyDisabledOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_004"]
        )
    for domain in _binding._OLD_STATE_DOMAINS:
        if _binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        ):
            raise _binding.CodingLegacyDisabledOnlyReviewError(
                _binding._LEGACY_PROGRAM_VALUES["value_005"]
            )
    epoch_runtime.assert_current()
    return _binding.CodingLegacyDisabledOnlyReviewV1(
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
        source_projection_digest=source.projection_digest,
        disabled_plugins=source.classification.disabled_plugins,
    )


def decode_review(
    cls: type[_binding.CodingLegacyDisabledOnlyReviewV1], value: object
) -> _binding.CodingLegacyDisabledOnlyReviewV1:
    if type(value) is not dict or set(value) != {
        "reviewId",
        "storeId",
        "namespaceId",
        "scopeId",
        "firstFenceId",
        "snapshotReceiptId",
        "sourceProjectionDigest",
        "reviewVersion",
        "disabledPlugins",
    }:
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_001"])
    disabled = value["disabledPlugins"]
    if not isinstance(disabled, list) or any(
        type(item) is not dict
        or set(item) != {"scope", "pluginId"}
        or item["scope"] not in ("global", "project")
        or not isinstance(item["pluginId"], str)
        or not item["pluginId"]
        for item in disabled
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_002"])
    for name in (
        "namespaceId",
        "firstFenceId",
        "snapshotReceiptId",
        "sourceProjectionDigest",
        "reviewId",
    ):
        if (
            not isinstance(value[name], str)
            or _binding._SHA256.fullmatch(value[name]) is None
        ):
            raise ValueError(_binding._LEGACY_RECORD_VALUES["value_006"])
    for name in ("storeId", "scopeId"):
        if not isinstance(value[name], str) or not value[name]:
            raise ValueError(_binding._LEGACY_RECORD_VALUES["value_007"])
    if type(value["reviewVersion"]) is not int or value["reviewVersion"] != 1:
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_003"])
    if len({(item["scope"], item["pluginId"]) for item in disabled}) != len(disabled):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_004"])
    review = cls(
        store_id=value["storeId"],
        namespace_id=value["namespaceId"],
        scope_id=value["scopeId"],
        first_fence_id=value["firstFenceId"],
        snapshot_receipt_id=value["snapshotReceiptId"],
        source_projection_digest=value["sourceProjectionDigest"],
        disabled_plugins=tuple(
            _binding.CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
            for item in disabled
        ),
    )
    if review.review_id != value["reviewId"]:
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_005"])
    return review
