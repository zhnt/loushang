"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from functools import partial

from loushang.coding.package import legacy_builtin_review as _binding
from loushang.harness.package_product._legacy_management_evidence import (
    SERVICE_LOCK_MARKERS,
    require_empty_lock_markers,
)


def admit_builtin_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    prepared: _binding.CodingPreBSnapshotPreparation,
    snapshot: _binding.PackageEpochCutoverSnapshotReceiptV1,
) -> None:
    """Refuse unsupported old state before the irreversible first fence."""

    try:
        owner = prepared.owner
        if (
            prepared.legacy_classification.kind != "legacy_state"
            or prepared.legacy_classification.configured_source_keys
            or any(
                item.plugin_id not in _binding._BUILTINS
                for item in prepared.legacy_classification.disabled_plugins
            )
            or (
                (evidence := owner.snapshot(snapshot.receipt_id)) is None
                or evidence.snapshot != snapshot
            )
            or any(
                owner.list_domain_members(snapshot.receipt_id, domain=domain)
                != _binding._EXPECTED[domain]
                for domain in _binding._DOMAINS
                if domain not in {"desired_state", "instance_state"}
            )
        ):
            raise _binding.CodingLegacyBuiltinOnlyReviewError(
                _binding._LEGACY_PROGRAM_VALUES["value_001"]
            )
        has_operations = _binding.classify_coding_legacy_management_members(
            desired_members=owner.list_domain_members(
                snapshot.receipt_id, domain="desired_state"
            )
            or (),
            instance_members=owner.list_domain_members(
                snapshot.receipt_id, domain="instance_state"
            )
            or (),
            lock_members=(),
            has_binding=False,
        )
        raw = owner.read_regular_member(
            snapshot.receipt_id,
            domain="desired_state",
            member_name=_binding._LEGACY_PROGRAM_VALUES["value_002"],
        )
        if raw is None:
            raise _binding.CodingLegacyBuiltinOnlyReviewError(
                _binding._LEGACY_PROGRAM_VALUES["value_003"]
            )
        desired = _binding.parse_coding_legacy_desired_evidence(
            raw, lifecycle=lifecycle
        )
        if has_operations:
            require_empty_lock_markers(
                partial(owner.read_regular_member, snapshot.receipt_id),
                SERVICE_LOCK_MARKERS,
                error_type=_binding.CodingLegacyBuiltinOnlyReviewError,
                message=_binding._LEGACY_PROGRAM_VALUES["value_012"],
            )
            operations_raw = owner.read_regular_member(
                snapshot.receipt_id,
                domain="desired_state",
                member_name=_binding._LEGACY_PROGRAM_VALUES["value_009"],
                maximum_bytes=2 * 1024 * 1024,
            )
            if operations_raw is None:
                raise _binding.CodingLegacyBuiltinOnlyReviewError(
                    _binding._LEGACY_PROGRAM_VALUES["value_010"]
                )
            _binding.parse_coding_legacy_operation_evidence(
                operations_raw,
                desired=desired,
                path=lifecycle.management_operations,
            )
        _binding._require_builtin_only_inventory(
            _binding.classify_coding_legacy_installations(
                (), desired, scope_id=lifecycle.scope_id
            )
        )
    except _binding.PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise _binding.PackagePosixEpochCutoverError(
            _binding._LEGACY_PROGRAM_VALUES["value_004"],
            code=_binding._LEGACY_PROGRAM_VALUES["value_011"],
        ) from exc


def review_builtin_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.CodingFencedEpochRuntime,
    *,
    settings_manager: _binding.SettingsManager,
) -> _binding.CodingLegacyBuiltinOnlyReviewV1:
    """Review only the authenticated snapshot and exact old builtin intent."""

    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if fence is None or switch is None:
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_013"]
        )
    if not isinstance(global_path, _binding.Path) or not isinstance(
        project_path, _binding.Path
    ):
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_014"]
        )
    if any(
        _binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        )
        != _binding._EXPECTED[domain]
        for domain in _binding._DOMAINS
        if domain not in {"desired_state", "instance_state"}
    ):
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_015"]
        )
    _binding.classify_coding_legacy_management_members(
        desired_members=_binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="desired_state"
        ),
        instance_members=_binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="instance_state"
        ),
        lock_members=(),
        has_binding=False,
    )
    source = _binding.read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    if source.classification.configured_source_keys:
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_016"]
        )
    inventory = _binding.read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    ).inventory
    _binding._require_builtin_only_inventory(inventory)
    epoch_runtime.assert_current()
    return _binding.CodingLegacyBuiltinOnlyReviewV1(
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
        source_projection_digest=source.projection_digest,
        desired_journal_digest=inventory.desired_journal_digest or "",
        disabled_plugins=source.classification.disabled_plugins,
        builtin_intent=inventory.builtin_intent,
        removed_builtin_ids=inventory.removed_plugin_ids,
    )


def validate_review(self: _binding.CodingLegacyBuiltinOnlyReviewV1) -> None:
    if (
        type(self.store_id) is not str
        or not self.store_id
        or type(self.scope_id) is not str
        or not self.scope_id.startswith("workspace:")
        or type(self.review_version) is not int
        or self.review_version != 1
        or type(self.disabled_plugins) is not tuple
        or type(self.builtin_intent) is not tuple
        or type(self.removed_builtin_ids) is not tuple
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in (
                self.namespace_id,
                self.first_fence_id,
                self.snapshot_receipt_id,
                self.source_projection_digest,
                self.desired_journal_digest,
            )
        )
        or any(
            not isinstance(item, _binding.CodingScopedLegacyDisableV1)
            or item.scope not in ("global", "project")
            or item.plugin_id not in _binding._BUILTINS
            for item in self.disabled_plugins
        )
        or len({(item.scope, item.plugin_id) for item in self.disabled_plugins})
        != len(self.disabled_plugins)
        or any(
            not isinstance(item, _binding.CodingLegacyBuiltinIntentV1)
            or item.plugin_id not in _binding._BUILTINS
            or item.desired_state not in ("installed_disabled", "installed_enabled")
            for item in self.builtin_intent
        )
        or tuple(item.plugin_id for item in self.builtin_intent)
        != tuple(sorted({item.plugin_id for item in self.builtin_intent}))
        or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
        or any(item not in _binding._REMOVABLE for item in self.removed_builtin_ids)
        or set(self.removed_builtin_ids).intersection(
            item.plugin_id for item in self.builtin_intent
        )
        or not (self.builtin_intent or self.removed_builtin_ids)
    ):
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            "Builtin-only review is invalid"
        )
    object.__setattr__(
        self,
        "review_id",
        _binding.sha256(_binding.canonical_json_bytes(self._identity())).hexdigest(),
    )


def decode_review(
    cls: type[_binding.CodingLegacyBuiltinOnlyReviewV1], value: object
) -> _binding.CodingLegacyBuiltinOnlyReviewV1:
    expected = _binding._REVIEW_SCHEMA.keys | {
        "reviewId",
        "reviewVersion",
        "removedBuiltinIds",
        "builtinIntent",
        "disabledPlugins",
    }
    if type(value) is not dict or set(value) != expected:
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            "Builtin-only review record is invalid"
        )
    disabled = value["disabledPlugins"]
    intent = value["builtinIntent"]
    removed = value["removedBuiltinIds"]
    if (
        not isinstance(disabled, list)
        or any(
            type(item) is not dict
            or set(item) != {"scope", "pluginId"}
            or item["scope"] not in ("global", "project")
            or type(item["pluginId"]) is not str
            for item in disabled
        )
        or not isinstance(intent, list)
        or any(
            type(item) is not dict
            or set(item) != {"pluginId", "desiredState"}
            or type(item["pluginId"]) is not str
            or item["desiredState"] not in ("installed_disabled", "installed_enabled")
            for item in intent
        )
        or not isinstance(removed, list)
        or any(type(item) is not str for item in removed)
    ):
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            "Builtin-only review entries are invalid"
        )
    try:
        review = cls(
            **_binding._REVIEW_SCHEMA.decode(dict, value),
            disabled_plugins=tuple(
                _binding.CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                for item in disabled
            ),
            builtin_intent=tuple(
                _binding.CodingLegacyBuiltinIntentV1(
                    item["pluginId"], item["desiredState"]
                )
                for item in intent
            ),
            removed_builtin_ids=tuple(removed),
            review_version=value["reviewVersion"],
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            "Builtin-only review record is invalid"
        ) from exc
    if review.review_id != value["reviewId"]:
        raise _binding.CodingLegacyBuiltinOnlyReviewError(
            "Builtin-only review identity changed"
        )
    return review
