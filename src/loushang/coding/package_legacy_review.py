"""Build an inert, snapshot-bound review record for one old local Installation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_classification import (
    CodingScopedLegacyDisableV1,
    classify_coding_legacy_source_configuration,
)
from .package_legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source,
)
from .package_legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstalledState,
    CodingLegacyInventoryError,
    read_coding_legacy_installation_inventory,
)
from .package_legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source,
)
from .package_legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver,
    read_coding_first_b_snapshot_member,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_WHEEL_NAME = re.compile(r"loushang_legacy_[0-9a-f]{24}-1-py3-none-any\.whl\Z")
_REVIEW_WIRE_KEYS = frozenset(
    {
        "reviewId",
        "storeId",
        "namespaceId",
        "scopeId",
        "firstFenceId",
        "snapshotReceiptId",
        "legacyRootIdentity",
        "legacyStateEvidenceId",
        "legacyStateDigest",
        "legacyEntryCount",
        "legacyByteCount",
        "pluginId",
        "desiredState",
        "legacySourceIdentity",
        "legacyBindingDigest",
        "legacyLockfileDigest",
        "legacyDesiredJournalDigest",
        "sourceContentDigest",
        "manifestDigest",
        "dependencyLockDigest",
        "wheelFilename",
        "wheelArtifactDigest",
        "policyRevision",
    }
)


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalAdoptionReviewV1:
    """Exact inputs to show an operator; this grants no publication authority."""

    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    legacy_root_identity: str
    legacy_state_evidence_id: str
    legacy_state_digest: str
    legacy_entry_count: int
    legacy_byte_count: int
    plugin_id: str
    desired_state: CodingLegacyInstalledState
    legacy_source_identity: str
    legacy_binding_digest: str
    legacy_lockfile_digest: str
    legacy_desired_journal_digest: str
    source_content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    wheel_filename: str
    wheel_artifact_digest: str
    policy_revision: str
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...] = ()
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...] = ()
    removed_builtin_ids: tuple[str, ...] = ()
    configured_plugin_source_scope: str | None = None
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
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
            type(value) is not str or _SHA256.fullmatch(value) is None
            for value in digests
        ):
            raise ValueError("Coding legacy review digest is invalid")
        if any(
            type(value) is not int or value < 0
            for value in (self.legacy_entry_count, self.legacy_byte_count)
        ):
            raise ValueError("Coding legacy review count is invalid")
        if (
            type(self.store_id) is not str
            or _SAFE_ID.fullmatch(self.store_id) is None
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.plugin_id) is not str
            or _SAFE_ID.fullmatch(self.plugin_id) is None
            or self.desired_state not in ("installed_disabled", "installed_enabled")
            or type(self.legacy_source_identity) is not str
            or not self.legacy_source_identity.startswith("local:/")
            or type(self.wheel_filename) is not str
            or _WHEEL_NAME.fullmatch(self.wheel_filename) is None
            or type(self.policy_revision) is not str
            or _SAFE_ID.fullmatch(self.policy_revision) is None
        ):
            raise ValueError("Coding legacy review authority is invalid")
        if any(
            not isinstance(item, CodingScopedLegacyDisableV1)
            or item.scope not in ("global", "project")
            or _SAFE_ID.fullmatch(item.plugin_id) is None
            for item in self.disabled_plugins
        ) or len(
            {(item.scope, item.plugin_id) for item in self.disabled_plugins}
        ) != len(self.disabled_plugins):
            raise ValueError("Coding legacy review disabled Plugins are invalid")
        if (
            any(
                not isinstance(item, CodingLegacyBuiltinIntentV1)
                or item.plugin_id
                not in {"coding.base", "coding.lsp.default", "coding.arch.default"}
                or item.desired_state
                not in ("installed_disabled", "installed_enabled")
                for item in self.builtin_intent
            )
            or tuple(item.plugin_id for item in self.builtin_intent)
            != tuple(sorted({item.plugin_id for item in self.builtin_intent}))
        ):
            raise ValueError("Coding legacy review builtin intent is invalid")
        if (
            any(
                type(item) is not str
                or item
                not in {"coding.base", "coding.lsp.default", "coding.arch.default"}
                for item in self.removed_builtin_ids
            )
            or self.removed_builtin_ids
            != tuple(sorted(set(self.removed_builtin_ids)))
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
        ):
            raise ValueError("Coding legacy review removed builtin IDs are invalid")
        if self.configured_plugin_source_scope not in (None, "global", "project"):
            raise ValueError("Coding legacy review configured Source scope is invalid")
        object.__setattr__(
            self,
            "review_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, object]:
        identity: dict[str, object] = {
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "firstFenceId": self.first_fence_id,
            "snapshotReceiptId": self.snapshot_receipt_id,
            "legacyRootIdentity": self.legacy_root_identity,
            "legacyStateEvidenceId": self.legacy_state_evidence_id,
            "legacyStateDigest": self.legacy_state_digest,
            "legacyEntryCount": self.legacy_entry_count,
            "legacyByteCount": self.legacy_byte_count,
            "pluginId": self.plugin_id,
            "desiredState": self.desired_state,
            "legacySourceIdentity": self.legacy_source_identity,
            "legacyBindingDigest": self.legacy_binding_digest,
            "legacyLockfileDigest": self.legacy_lockfile_digest,
            "legacyDesiredJournalDigest": self.legacy_desired_journal_digest,
            "sourceContentDigest": self.source_content_digest,
            "manifestDigest": self.manifest_digest,
            "dependencyLockDigest": self.dependency_lock_digest,
            "wheelFilename": self.wheel_filename,
            "wheelArtifactDigest": self.wheel_artifact_digest,
            "policyRevision": self.policy_revision,
        }
        if self.disabled_plugins:
            identity["disabledPlugins"] = [
                {"scope": item.scope, "pluginId": item.plugin_id}
                for item in self.disabled_plugins
            ]
        if self.builtin_intent:
            identity["builtinIntent"] = [
                {"pluginId": item.plugin_id, "desiredState": item.desired_state}
                for item in self.builtin_intent
            ]
        if self.removed_builtin_ids:
            identity["removedBuiltinIds"] = list(self.removed_builtin_ids)
        if self.configured_plugin_source_scope is not None:
            identity["configuredPluginSourceScope"] = (
                self.configured_plugin_source_scope
            )
        return identity

    def to_dict(self) -> dict[str, object]:
        return {"reviewId": self.review_id, **self._identity_dict()}

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        """Stable Product tombstone command for a reviewed old removal."""

        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is absent from the legacy review")
        return shared_coding_legacy_builtin_removal_operation_id(
            self.first_fence_id, plugin_id
        )

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyLocalAdoptionReviewV1:
        optional_keys = {
            "disabledPlugins",
            "builtinIntent",
            "removedBuiltinIds",
            "configuredPluginSourceScope",
        }
        if (
            type(value) is not dict
            or not _REVIEW_WIRE_KEYS.issubset(value)
            or not set(value).issubset(_REVIEW_WIRE_KEYS | optional_keys)
        ):
            raise ValueError("Coding legacy review record is invalid")
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
            raise ValueError("Coding legacy review disabled Plugins are invalid")
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
            raise ValueError("Coding legacy review builtin intent is invalid")
        removed_builtin_ids = document.get("removedBuiltinIds", [])
        if (
            not isinstance(removed_builtin_ids, list)
            or ("removedBuiltinIds" in document and not removed_builtin_ids)
            or any(type(item) is not str for item in removed_builtin_ids)
        ):
            raise ValueError("Coding legacy review removed builtin IDs are invalid")
        scalar_keys = _REVIEW_WIRE_KEYS - {"legacyEntryCount", "legacyByteCount"}
        if any(type(document[key]) is not str for key in scalar_keys):
            raise ValueError("Coding legacy review record is invalid")
        review = cls(
            store_id=document["storeId"],
            namespace_id=document["namespaceId"],
            scope_id=document["scopeId"],
            first_fence_id=document["firstFenceId"],
            snapshot_receipt_id=document["snapshotReceiptId"],
            legacy_root_identity=document["legacyRootIdentity"],
            legacy_state_evidence_id=document["legacyStateEvidenceId"],
            legacy_state_digest=document["legacyStateDigest"],
            legacy_entry_count=document["legacyEntryCount"],
            legacy_byte_count=document["legacyByteCount"],
            plugin_id=document["pluginId"],
            desired_state=document["desiredState"],
            legacy_source_identity=document["legacySourceIdentity"],
            legacy_binding_digest=document["legacyBindingDigest"],
            legacy_lockfile_digest=document["legacyLockfileDigest"],
            legacy_desired_journal_digest=document["legacyDesiredJournalDigest"],
            source_content_digest=document["sourceContentDigest"],
            manifest_digest=document["manifestDigest"],
            dependency_lock_digest=document["dependencyLockDigest"],
            wheel_filename=document["wheelFilename"],
            wheel_artifact_digest=document["wheelArtifactDigest"],
            policy_revision=document["policyRevision"],
            disabled_plugins=tuple(
                CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                for item in disabled
            ),
            builtin_intent=tuple(
                CodingLegacyBuiltinIntentV1(item["pluginId"], item["desiredState"])
                for item in builtin_intent
            ),
            removed_builtin_ids=tuple(removed_builtin_ids),
            configured_plugin_source_scope=document.get("configuredPluginSourceScope"),
        )
        if document["reviewId"] != review.review_id:
            raise ValueError("Coding legacy review identity changed")
        return review


def shared_coding_legacy_builtin_removal_operation_id(
    first_fence_id: str, plugin_id: str
) -> str:
    """Use one tombstone across separately reviewed active local Installations."""

    if (
        not isinstance(first_fence_id, str)
        or _SHA256.fullmatch(first_fence_id) is None
        or plugin_id
        not in {"coding.base", "coding.lsp.default", "coding.arch.default"}
    ):
        raise ValueError("Coding legacy builtin removal identity is invalid")
    return "coding-legacy-builtin-remove:" + sha256(
        b"loushang.coding-legacy-builtin-removal/v1\0"
        + first_fence_id.encode("ascii")
        + b"\0"
        + plugin_id.encode("ascii")
    ).hexdigest()


def review_coding_legacy_installed_local_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAdoptionReviewV1:
    """Fetch the original Source again before producing a review identity."""

    if (
        not isinstance(policy_revision, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", policy_revision) is None
    ):
        raise ValueError("Coding Product policy revision is required")
    epoch_runtime.assert_current()
    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    inventory = read_coding_legacy_installation_inventory(lifecycle, epoch_runtime)
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
        or sha256(wheel.wheel_bytes).hexdigest() != wheel.artifact_digest
        or inventory.inventory.lockfile_digest != binding.lockfile_digest
        or inventory.inventory.desired_journal_digest is None
    ):
        raise CodingLegacyInventoryError(
            "Coding legacy review inputs differ from the first-B Installation"
        )
    legacy_state = CodingFirstBLegacyStateObserver(lifecycle, epoch_runtime).observe(
        store_id=fence.store_id,
        legacy_root_identity=fence.request.legacy_root_identity,
    )
    source_raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name="coding-source-configuration.json",
        maximum_bytes=2 * 1024 * 1024,
    )
    if source_raw is None:
        raise CodingLegacyInventoryError(
            "Coding legacy Source configuration is missing from first B"
        )
    source_projection = json.loads(source_raw)
    source = classify_coding_legacy_source_configuration(source_projection)
    configured_source = match_coding_legacy_local_skill_configured_source(
        source_projection,
        source_identity=binding.source_identity,
        installed_source_identities=tuple(
            item.binding.source_identity for item in inventory.inventory.active_local
        ),
    )
    epoch_runtime.assert_current()
    return CodingLegacyLocalAdoptionReviewV1(
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
            if item in {"coding.base", "coding.lsp.default", "coding.arch.default"}
        ),
        configured_plugin_source_scope=(
            None if configured_source is None else configured_source.scope
        ),
    )


__all__ = [
    "CodingLegacyLocalAdoptionReviewV1",
    "review_coding_legacy_installed_local_source",
]
