"""Read the same first-fence evidence for local review and approval replay."""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING, ClassVar, NamedTuple, Self, TypedDict

from loushang.harness.package_product._legacy_binding_evidence import (
    LegacyLocalBindingEvidence,
)
from loushang.harness.package_product._legacy_inventory import (
    LEGACY_REVIEW_DIGEST,
    LEGACY_REVIEW_ID,
    LegacyInventoryEvidence,
    LegacyReviewWireSelections,
    _InstalledState,
    _LegacyBuiltinIntent,
    _LegacyFencedReviewRecord,
    reacquire_legacy_inventory_source,
    valid_legacy_builtin_intent,
    valid_legacy_disable_selections,
)
from loushang.harness.package_product._legacy_runtime import _LegacyFirstSnapshot
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceReceiptV1,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyLocalWheelFields,
    _LegacyWheelValues,
    legacy_source_wheel_prefix,
)


class LegacyLocalReviewIdentity(TypedDict):
    store_id: str
    namespace_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    legacy_root_identity: str
    legacy_state_evidence_id: str
    legacy_state_digest: str
    legacy_entry_count: int
    legacy_byte_count: int
    plugin_id: str
    desired_state: _InstalledState
    legacy_source_identity: str
    legacy_binding_digest: str
    legacy_lockfile_digest: str
    source_content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    wheel_filename: str


class LegacyLocalReviewEvidence(NamedTuple):
    identity: LegacyLocalReviewIdentity
    inventory: LegacyInventoryEvidence
    source_projection: object


_LOCAL_REVIEW_DIGEST_FIELDS = (
    "namespace_id", "first_fence_id", "snapshot_receipt_id", "legacy_root_identity",
    "legacy_state_evidence_id", "legacy_state_digest", "legacy_binding_digest",
    "legacy_lockfile_digest", "legacy_desired_journal_digest", "source_content_digest",
    "manifest_digest", "dependency_lock_digest", "wheel_artifact_digest",
)
_OPTIONAL_LOCAL_REVIEW_WIRE_KEYS = {
    "disabledPlugins", "builtinIntent", "removedBuiltinIds", "configuredPluginSourceScope",
}


class LegacyLocalReviewRecord(_LegacyFencedReviewRecord):
    """Authenticate and encode one snapshot-bound review over Product data."""

    __slots__ = ()
    _review_label: ClassVar[str]
    _wheel_name: ClassVar[Pattern[str]]
    _builtin_ids: ClassVar[frozenset[str]]
    _builtin_intent_type: ClassVar[type[_LegacyBuiltinIntent]]

    if TYPE_CHECKING:
        plugin_id: str
        desired_state: _InstalledState
        legacy_entry_count: int
        legacy_byte_count: int
        legacy_source_identity: str
        wheel_filename: str
        policy_revision: str
        builtin_intent: tuple[_LegacyBuiltinIntent, ...]
        removed_builtin_ids: tuple[str, ...]
        configured_plugin_source_scope: str | None

    def __post_init__(self) -> None:
        label = self._review_label
        if any(
            type(value) is not str or LEGACY_REVIEW_DIGEST.fullmatch(value) is None
            for value in (getattr(self, field) for field in _LOCAL_REVIEW_DIGEST_FIELDS)
        ):
            raise ValueError(f"{label} digest is invalid")
        if any(
            type(value) is not int or value < 0
            for value in (self.legacy_entry_count, self.legacy_byte_count)
        ):
            raise ValueError(f"{label} count is invalid")
        if (
            type(self.store_id) is not str
            or LEGACY_REVIEW_ID.fullmatch(self.store_id) is None
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.plugin_id) is not str
            or LEGACY_REVIEW_ID.fullmatch(self.plugin_id) is None
            or self.desired_state not in ("installed_disabled", "installed_enabled")
            or type(self.legacy_source_identity) is not str
            or not self.legacy_source_identity.startswith("local:/")
            or type(self.wheel_filename) is not str
            or self._wheel_name.fullmatch(self.wheel_filename) is None
            or type(self.policy_revision) is not str
            or LEGACY_REVIEW_ID.fullmatch(self.policy_revision) is None
        ):
            raise ValueError(f"{label} authority is invalid")
        if not valid_legacy_disable_selections(self.disabled_plugins, self._disable_type):
            raise ValueError(f"{label} disabled Plugins are invalid")
        if not valid_legacy_builtin_intent(
            self.builtin_intent, self._builtin_ids, intent_type=self._builtin_intent_type,
        ):
            raise ValueError(f"{label} builtin intent is invalid")
        if (
            any(type(item) is not str or item not in self._builtin_ids
                for item in self.removed_builtin_ids)
            or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
        ):
            raise ValueError(f"{label} removed builtin IDs are invalid")
        if self.configured_plugin_source_scope not in (None, "global", "project"):
            raise ValueError(f"{label} configured Source scope is invalid")
        self._seal_review(self._identity_dict())

    def _identity_dict(self) -> dict[str, object]:
        identity = self._selection_identity(
            self.builtin_intent, self.removed_builtin_ids,
            include_empty=False,
        )
        if self.configured_plugin_source_scope is not None:
            identity["configuredPluginSourceScope"] = self.configured_plugin_source_scope
        return identity

    def to_dict(self) -> dict[str, object]:
        return {"reviewId": self.review_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        label = cls._review_label
        keys = cls._schema.keys | {"reviewId"}
        allowed = keys | _OPTIONAL_LOCAL_REVIEW_WIRE_KEYS
        if type(value) is not dict or not keys <= value.keys() <= allowed:
            raise ValueError(f"{label} record is invalid")
        selections = LegacyReviewWireSelections.read(
            value,
            required=False,
            disabled_error=ValueError(f"{label} disabled Plugins are invalid"),
            intent_error=ValueError(f"{label} builtin intent is invalid"),
            removed_error=ValueError(f"{label} removed builtin IDs are invalid"),
        )
        scalar_keys = keys - {"legacyEntryCount", "legacyByteCount"}
        if any(type(value[key]) is not str for key in scalar_keys):
            raise ValueError(f"{label} record is invalid")
        create: Callable[..., Self] = cls
        review = create(
            **cls._schema.decode(dict, value),
            **selections.decode(cls._disable_type, cls._builtin_intent_type),
            configured_plugin_source_scope=value.get("configuredPluginSourceScope"),
        )
        if value["reviewId"] != review.review_id:
            raise ValueError(f"{label} identity changed")
        return review


def _read_evidence(
    reader: _LegacyFirstSnapshot,
    fence: PackageEpochFenceReceiptV1,
    inventory: LegacyInventoryEvidence,
    binding: LegacyLocalBindingEvidence,
    *,
    store_id: str,
    namespace_id: str,
    desired_state: _InstalledState,
    wheel_filename: str,
    source_member: str,
    missing_source: Exception,
) -> LegacyLocalReviewEvidence:
    state = reader.observe(
        store_id=fence.store_id, legacy_root_identity=fence.request.legacy_root_identity
    )
    raw = reader.read_member(
        domain="source_configuration",
        member_name=source_member,
        maximum_bytes=2 * 1024 * 1024,
    )
    if raw is None:
        raise missing_source
    return LegacyLocalReviewEvidence(
        LegacyLocalReviewIdentity(
            store_id=store_id,
            namespace_id=namespace_id,
            first_fence_id=inventory.first_fence_id,
            snapshot_receipt_id=inventory.snapshot_receipt_id,
            legacy_root_identity=state.legacy_root_identity,
            legacy_state_evidence_id=state.evidence_id,
            legacy_state_digest=state.state_digest,
            legacy_entry_count=state.entry_count,
            legacy_byte_count=state.byte_count,
            plugin_id=binding.plugin_id,
            desired_state=desired_state,
            legacy_source_identity=binding.source_identity,
            legacy_binding_digest=binding.binding_digest,
            legacy_lockfile_digest=binding.lockfile_digest,
            source_content_digest=binding.content_digest,
            manifest_digest=binding.manifest_digest,
            dependency_lock_digest=binding.dependency_lock.digest,
            wheel_filename=wheel_filename,
        ),
        inventory,
        json.loads(raw),
    )


def read_live_legacy_local_review(
    reader: _LegacyFirstSnapshot,
    read_inventory: Callable[[], LegacyInventoryEvidence],
    *,
    legacy_package_root: Path,
    plugin_id: str,
    source_member: str,
    staging_prefix: str,
    result_factory: Callable[[_LegacyWheelValues], _LegacyLocalWheelFields],
    inventory_error: type[ValueError],
    label: str,
) -> tuple[LegacyLocalReviewEvidence, str, str]:
    """Recapture the Wheel and verify it against the frozen Installation."""
    runtime = reader.runtime
    captured, index, wheel = reacquire_legacy_inventory_source(
        read_inventory,
        runtime,
        legacy_package_root=legacy_package_root,
        plugin_id=plugin_id,
        staging_prefix=staging_prefix,
        error_type=inventory_error,
        label=label,
        result_factory=result_factory,
    )
    fence = runtime.cutover_result.fence
    switch = runtime.cutover_result.switch_receipt
    runtime.assert_current()
    inventory = read_inventory()
    binding, desired_state, _ = captured.inventory.active_local[index]
    digest = inventory.desired_journal_digest
    if (
        fence is None
        or switch is None
        or inventory != captured
        or inventory.first_fence_id != fence.fence_id
        or inventory.snapshot_receipt_id != fence.request.snapshot_receipt_id
        or wheel.plugin_id != binding.plugin_id
        or wheel.original_source_identity != binding.source_identity
        or wheel.source_content_digest != binding.content_digest
        or wheel.manifest_digest != binding.manifest_digest
        or sha256(wheel.wheel_bytes).hexdigest() != wheel.artifact_digest
        or inventory.inventory.lockfile_digest != binding.lockfile_digest
        or digest is None
    ):
        raise inventory_error(
            f"{label} legacy review inputs differ from the first-B Installation"
        )
    evidence = _read_evidence(
        reader,
        fence,
        inventory,
        binding,
        store_id=runtime.registry.store_id,
        namespace_id=switch.namespace_id,
        desired_state=desired_state,
        wheel_filename=wheel.filename,
        source_member=source_member,
        missing_source=inventory_error(
            f"{label} legacy Source configuration is missing from first B"
        ),
    )
    return evidence, digest, wheel.artifact_digest


def read_frozen_legacy_local_review(
    reader: _LegacyFirstSnapshot,
    read_inventory: Callable[[], LegacyInventoryEvidence],
    *,
    plugin_id: str,
    source_member: str,
    error_type: type[Exception],
    label: str,
) -> LegacyLocalReviewEvidence:
    """Reopen the authenticated approval evidence without consulting live Source."""
    runtime = reader.runtime
    fence = runtime.cutover_result.fence
    switch = runtime.cutover_result.switch_receipt
    inventory = read_inventory()
    selected = next(
        (
            item
            for item in inventory.inventory.active_local
            if item[0].plugin_id == plugin_id
        ),
        None,
    )
    if fence is None or switch is None or selected is None:
        raise error_type(f"{label} acceptance lost its first-B Installation")
    binding, desired_state, _ = selected
    prefix = legacy_source_wheel_prefix(plugin_id, binding.content_digest)
    return _read_evidence(
        reader,
        fence,
        inventory,
        binding,
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        desired_state=desired_state,
        wheel_filename=f"{prefix}-1-py3-none-any.whl",
        source_member=source_member,
        missing_source=error_type(f"{label} acceptance lost its Source configuration"),
    )
