"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_review as _binding


def review_local_source(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> _binding.CodingLegacyLocalAdoptionReviewV1:
    """Fetch the original Source again before producing a review identity."""

    if (
        not isinstance(policy_revision, str)
        or _binding.re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", policy_revision)
        is None
    ):
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_001"])
    epoch_runtime.assert_current()
    reacquired = _binding.reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    inventory = _binding.read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    )
    selected = reacquired.installation
    binding = selected.binding
    wheel = reacquired.wheel
    if (
        fence is None
        or switch is None
        or inventory != reacquired.inventory_evidence
        or inventory.first_fence_id != fence.fence_id
        or inventory.snapshot_receipt_id != fence.request.snapshot_receipt_id
        or selected not in inventory.inventory.active_local
        or wheel.plugin_id != binding.plugin_id
        or wheel.original_source_identity != binding.source_identity
        or wheel.source_content_digest != binding.content_digest
        or wheel.manifest_digest != binding.manifest_digest
        or _binding.sha256(wheel.wheel_bytes).hexdigest() != wheel.artifact_digest
        or inventory.inventory.lockfile_digest != binding.lockfile_digest
        or inventory.inventory.desired_journal_digest is None
    ):
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_002"]
        )
    legacy_state = _binding.CodingFirstBLegacyStateObserver(
        lifecycle, epoch_runtime
    ).observe(
        store_id=fence.store_id,
        legacy_root_identity=fence.request.legacy_root_identity,
    )
    source_raw = _binding.read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name=_binding._LEGACY_PROGRAM_VALUES["value_003"],
        maximum_bytes=2 * 1024 * 1024,
    )
    if source_raw is None:
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_004"]
        )
    source_projection = _binding.json.loads(source_raw)
    source = _binding.classify_coding_legacy_source_configuration(source_projection)
    configured_source = _binding.match_coding_legacy_local_skill_configured_source(
        source_projection,
        source_identity=binding.source_identity,
        installed_source_identities=tuple(
            item.binding.source_identity for item in inventory.inventory.active_local
        ),
    )
    epoch_runtime.assert_current()
    return _binding.CodingLegacyLocalAdoptionReviewV1(
        store_id=epoch_runtime.registry.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=inventory.first_fence_id,
        snapshot_receipt_id=inventory.snapshot_receipt_id,
        legacy_root_identity=legacy_state.legacy_root_identity,
        legacy_state_evidence_id=legacy_state.evidence_id,
        legacy_state_digest=legacy_state.state_digest,
        legacy_entry_count=legacy_state.entry_count,
        legacy_byte_count=legacy_state.byte_count,
        plugin_id=binding.plugin_id,
        desired_state=selected.desired_state,
        legacy_source_identity=binding.source_identity,
        legacy_binding_digest=binding.binding_digest,
        legacy_lockfile_digest=binding.lockfile_digest,
        legacy_desired_journal_digest=inventory.inventory.desired_journal_digest,
        source_content_digest=binding.content_digest,
        manifest_digest=binding.manifest_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        wheel_filename=wheel.filename,
        wheel_artifact_digest=wheel.artifact_digest,
        policy_revision=policy_revision,
        disabled_plugins=source.disabled_plugins,
        builtin_intent=inventory.inventory.builtin_intent,
        removed_builtin_ids=tuple(
            item
            for item in inventory.inventory.removed_plugin_ids
            if item
            in {
                _binding._LEGACY_PROGRAM_VALUES["value_005"],
                _binding._LEGACY_PROGRAM_VALUES["value_006"],
                _binding._LEGACY_PROGRAM_VALUES["value_007"],
            }
        ),
        configured_plugin_source_scope=(
            None if configured_source is None else configured_source.scope
        ),
    )


def validate_review(self: _binding.CodingLegacyLocalAdoptionReviewV1) -> None:
    digests = (
        self.namespace_id,
        self.first_fence_id,
        self.snapshot_receipt_id,
        self.legacy_root_identity,
        self.legacy_state_evidence_id,
        self.legacy_state_digest,
        self.legacy_binding_digest,
        self.legacy_lockfile_digest,
        self.legacy_desired_journal_digest,
        self.source_content_digest,
        self.manifest_digest,
        self.dependency_lock_digest,
        self.wheel_artifact_digest,
    )
    if any(
        type(value) is not str or _binding._SHA256.fullmatch(value) is None
        for value in digests
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_001"])
    if any(
        type(value) is not int or value < 0
        for value in (self.legacy_entry_count, self.legacy_byte_count)
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_002"])
    if (
        type(self.store_id) is not str
        or _binding._SAFE_ID.fullmatch(self.store_id) is None
        or type(self.scope_id) is not str
        or not self.scope_id.startswith("workspace:")
        or type(self.plugin_id) is not str
        or _binding._SAFE_ID.fullmatch(self.plugin_id) is None
        or self.desired_state not in ("installed_disabled", "installed_enabled")
        or type(self.legacy_source_identity) is not str
        or not self.legacy_source_identity.startswith("local:/")
        or type(self.wheel_filename) is not str
        or _binding._WHEEL_NAME.fullmatch(self.wheel_filename) is None
        or type(self.policy_revision) is not str
        or _binding._SAFE_ID.fullmatch(self.policy_revision) is None
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_003"])
    if any(
        not isinstance(item, _binding.CodingScopedLegacyDisableV1)
        or item.scope not in ("global", "project")
        or _binding._SAFE_ID.fullmatch(item.plugin_id) is None
        for item in self.disabled_plugins
    ) or len({(item.scope, item.plugin_id) for item in self.disabled_plugins}) != len(
        self.disabled_plugins
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_004"])
    if any(
        not isinstance(item, _binding.CodingLegacyBuiltinIntentV1)
        or item.plugin_id
        not in {
            _binding._LEGACY_RECORD_VALUES["value_008"],
            _binding._LEGACY_RECORD_VALUES["value_009"],
            _binding._LEGACY_RECORD_VALUES["value_010"],
        }
        or item.desired_state not in ("installed_disabled", "installed_enabled")
        for item in self.builtin_intent
    ) or tuple(item.plugin_id for item in self.builtin_intent) != tuple(
        sorted({item.plugin_id for item in self.builtin_intent})
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_005"])
    if (
        any(
            type(item) is not str
            or item
            not in {
                _binding._LEGACY_RECORD_VALUES["value_008"],
                _binding._LEGACY_RECORD_VALUES["value_009"],
                _binding._LEGACY_RECORD_VALUES["value_010"],
            }
            for item in self.removed_builtin_ids
        )
        or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
        or set(self.removed_builtin_ids).intersection(
            item.plugin_id for item in self.builtin_intent
        )
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_006"])
    if self.configured_plugin_source_scope not in (None, "global", "project"):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_007"])
    object.__setattr__(
        self,
        "review_id",
        _binding.sha256(
            _binding.canonical_json_bytes(self._identity_dict())
        ).hexdigest(),
    )


def decode_review(
    cls: type[_binding.CodingLegacyLocalAdoptionReviewV1], value: object
) -> _binding.CodingLegacyLocalAdoptionReviewV1:
    optional_keys = {
        "disabledPlugins",
        "builtinIntent",
        "removedBuiltinIds",
        "configuredPluginSourceScope",
    }
    if (
        type(value) is not dict
        or not _binding._REVIEW_WIRE_KEYS.issubset(value)
        or not set(value).issubset(_binding._REVIEW_WIRE_KEYS | optional_keys)
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_011"])
    document = value
    disabled = document.get("disabledPlugins", [])
    if (
        not isinstance(disabled, list)
        or ("disabledPlugins" in document and not disabled)
        or any(
            type(item) is not dict
            or set(item) != {"scope", "pluginId"}
            or item["scope"] not in ("global", "project")
            or not isinstance(item["pluginId"], str)
            for item in disabled
        )
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_004"])
    builtin_intent = document.get("builtinIntent", [])
    if (
        not isinstance(builtin_intent, list)
        or ("builtinIntent" in document and not builtin_intent)
        or any(
            type(item) is not dict
            or set(item) != {"pluginId", "desiredState"}
            or type(item["pluginId"]) is not str
            or type(item["desiredState"]) is not str
            for item in builtin_intent
        )
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_005"])
    removed_builtin_ids = document.get("removedBuiltinIds", [])
    if (
        not isinstance(removed_builtin_ids, list)
        or ("removedBuiltinIds" in document and not removed_builtin_ids)
        or any(type(item) is not str for item in removed_builtin_ids)
    ):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_006"])
    scalar_keys = _binding._REVIEW_WIRE_KEYS - {"legacyEntryCount", "legacyByteCount"}
    if any(type(document[key]) is not str for key in scalar_keys):
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_011"])
    review = cls(
        **_binding._REVIEW_SCHEMA.decode(dict, document),
        disabled_plugins=tuple(
            _binding.CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
            for item in disabled
        ),
        builtin_intent=tuple(
            _binding.CodingLegacyBuiltinIntentV1(item["pluginId"], item["desiredState"])
            for item in builtin_intent
        ),
        removed_builtin_ids=tuple(removed_builtin_ids),
        configured_plugin_source_scope=document.get("configuredPluginSourceScope"),
    )
    if document["reviewId"] != review.review_id:
        raise ValueError(_binding._LEGACY_RECORD_VALUES["value_012"])
    return review
