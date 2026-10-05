"""Frozen first-B review for old Coding builtin-only Desired State."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_classification import CodingScopedLegacyDisableV1
from .package_legacy_desired_evidence import parse_coding_legacy_desired_evidence
from .package_legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInstallationInventoryV1,
    classify_coding_legacy_installations,
    read_coding_legacy_installation_inventory,
)
from .package_legacy_operation_evidence import (
    classify_coding_legacy_management_members,
    parse_coding_legacy_operation_evidence,
)
from .package_legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    CodingLegacyInventoryDomain,
    list_coding_first_b_snapshot_domain_members,
)
from .package_legacy_source_evidence import read_coding_legacy_source_evidence
from .package_pre_b_snapshot import CodingPreBSnapshotPreparation

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
_REMOVABLE = _BUILTINS
_DOMAINS: tuple[CodingLegacyInventoryDomain, ...] = (
    "binding_history",
    "desired_state",
    "source_configuration",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)
_EXPECTED = {
    "binding_history": (),
    "desired_state": ("desired-state.jsonl",),
    "source_configuration": ("coding-source-configuration.json",),
    "enablement_state": (),
    "instance_state": (),
    "lock_history": (),
    "store_bytes": (),
}


class CodingLegacyBuiltinOnlyReviewError(ValueError):
    """The frozen old snapshot cannot become a builtin-only Product review."""


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinOnlyReviewV1:
    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    source_projection_digest: str
    desired_journal_digest: str
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...]
    removed_builtin_ids: tuple[str, ...]
    review_version: int = 1
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
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
                not isinstance(item, CodingScopedLegacyDisableV1)
                or item.scope not in ("global", "project")
                or item.plugin_id not in _BUILTINS
                for item in self.disabled_plugins
            )
            or len({(item.scope, item.plugin_id) for item in self.disabled_plugins})
            != len(self.disabled_plugins)
            or any(
                not isinstance(item, CodingLegacyBuiltinIntentV1)
                or item.plugin_id not in _BUILTINS
                or item.desired_state not in ("installed_disabled", "installed_enabled")
                for item in self.builtin_intent
            )
            or tuple(item.plugin_id for item in self.builtin_intent)
            != tuple(sorted({item.plugin_id for item in self.builtin_intent}))
            or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
            or any(item not in _REMOVABLE for item in self.removed_builtin_ids)
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
            or not (self.builtin_intent or self.removed_builtin_ids)
        ):
            raise CodingLegacyBuiltinOnlyReviewError("Builtin-only review is invalid")
        object.__setattr__(
            self,
            "review_id",
            sha256(canonical_json_bytes(self._identity())).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        return {
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "firstFenceId": self.first_fence_id,
            "snapshotReceiptId": self.snapshot_receipt_id,
            "sourceProjectionDigest": self.source_projection_digest,
            "desiredJournalDigest": self.desired_journal_digest,
            "disabledPlugins": [
                {"scope": item.scope, "pluginId": item.plugin_id}
                for item in self.disabled_plugins
            ],
            "builtinIntent": [
                {"pluginId": item.plugin_id, "desiredState": item.desired_state}
                for item in self.builtin_intent
            ],
            "removedBuiltinIds": list(self.removed_builtin_ids),
            "reviewVersion": self.review_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "reviewId": self.review_id}

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyBuiltinOnlyReviewV1:
        expected = {
            "storeId",
            "namespaceId",
            "scopeId",
            "firstFenceId",
            "snapshotReceiptId",
            "sourceProjectionDigest",
            "desiredJournalDigest",
            "disabledPlugins",
            "builtinIntent",
            "removedBuiltinIds",
            "reviewVersion",
            "reviewId",
        }
        if type(value) is not dict or set(value) != expected:
            raise CodingLegacyBuiltinOnlyReviewError(
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
                or item["desiredState"]
                not in ("installed_disabled", "installed_enabled")
                for item in intent
            )
            or not isinstance(removed, list)
            or any(type(item) is not str for item in removed)
        ):
            raise CodingLegacyBuiltinOnlyReviewError(
                "Builtin-only review entries are invalid"
            )
        try:
            review = cls(
                store_id=value["storeId"],
                namespace_id=value["namespaceId"],
                scope_id=value["scopeId"],
                first_fence_id=value["firstFenceId"],
                snapshot_receipt_id=value["snapshotReceiptId"],
                source_projection_digest=value["sourceProjectionDigest"],
                desired_journal_digest=value["desiredJournalDigest"],
                disabled_plugins=tuple(
                    CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                    for item in disabled
                ),
                builtin_intent=tuple(
                    CodingLegacyBuiltinIntentV1(item["pluginId"], item["desiredState"])
                    for item in intent
                ),
                removed_builtin_ids=tuple(removed),
                review_version=value["reviewVersion"],
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise CodingLegacyBuiltinOnlyReviewError(
                "Builtin-only review record is invalid"
            ) from exc
        if review.review_id != value["reviewId"]:
            raise CodingLegacyBuiltinOnlyReviewError(
                "Builtin-only review identity changed"
            )
        return review

    def removed_builtin_operation_id(self, plugin_id: str) -> str:
        if plugin_id not in self.removed_builtin_ids:
            raise ValueError("Builtin removal is not reviewed")
        return (
            "coding-legacy-builtin-remove:"
            + sha256(
                f"{self.store_id}\0{self.review_id}\0{plugin_id}".encode()
            ).hexdigest()
        )


def _require_builtin_only_inventory(
    inventory: CodingLegacyInstallationInventoryV1,
) -> None:
    if (
        inventory.active_local
        or inventory.unselected_source_identities
        or inventory.lockfile_digest is not None
        or inventory.desired_journal_digest is None
        or not (inventory.builtin_intent or inventory.removed_plugin_ids)
        or any(item not in _REMOVABLE for item in inventory.removed_plugin_ids)
    ):
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding old Desired State is not builtin-only"
        )


def admit_coding_builtin_only_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    prepared: CodingPreBSnapshotPreparation,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
) -> None:
    """Refuse unsupported old state before the irreversible first fence."""

    try:
        owner = prepared.owner
        if (
            prepared.legacy_classification.kind != "legacy_state"
            or prepared.legacy_classification.configured_source_keys
            or any(
                item.plugin_id not in _BUILTINS
                for item in prepared.legacy_classification.disabled_plugins
            )
            or (
                (evidence := owner.snapshot(snapshot.receipt_id)) is None
                or evidence.snapshot != snapshot
            )
            or any(
                owner.list_domain_members(snapshot.receipt_id, domain=domain)
                != _EXPECTED[domain]
                for domain in _DOMAINS
                if domain not in {"desired_state", "instance_state"}
            )
        ):
            raise CodingLegacyBuiltinOnlyReviewError(
                "Coding old snapshot is not builtin-only"
            )
        has_operations = classify_coding_legacy_management_members(
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
            member_name="desired-state.jsonl",
        )
        if raw is None:
            raise CodingLegacyBuiltinOnlyReviewError(
                "Coding old Desired State is missing"
            )
        desired = parse_coding_legacy_desired_evidence(raw, lifecycle=lifecycle)
        if has_operations:
            for domain, name in (
                ("desired_state", "desired-state.jsonl.lock"),
                ("desired_state", "management-operations.jsonl.lock"),
                ("instance_state", "retirement-intents.jsonl.lock"),
                ("instance_state", "retirement-sets.jsonl.lock"),
            ):
                if (
                    owner.read_regular_member(
                        snapshot.receipt_id,
                        domain=domain,
                        member_name=name,
                        maximum_bytes=8,
                    )
                    != b"\0"
                ):
                    raise CodingLegacyBuiltinOnlyReviewError(
                        "Coding old management lock changed"
                    )
            operations_raw = owner.read_regular_member(
                snapshot.receipt_id,
                domain="desired_state",
                member_name="management-operations.jsonl",
                maximum_bytes=2 * 1024 * 1024,
            )
            if operations_raw is None:
                raise CodingLegacyBuiltinOnlyReviewError(
                    "Coding old management operations are missing"
                )
            parse_coding_legacy_operation_evidence(
                operations_raw,
                desired=desired,
                path=lifecycle.management_operations,
            )
        _require_builtin_only_inventory(
            classify_coding_legacy_installations(
                (), desired, scope_id=lifecycle.scope_id
            )
        )
    except PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PackagePosixEpochCutoverError(
            "Coding builtin-only snapshot cannot be admitted before first fence",
            code="coding_legacy_builtin_snapshot_refused",
        ) from exc


def review_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyBuiltinOnlyReviewV1:
    """Review only the authenticated snapshot and exact old builtin intent."""

    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if fence is None or switch is None:
        raise CodingLegacyBuiltinOnlyReviewError("Coding first-B fence is missing")
    if not isinstance(global_path, Path) or not isinstance(project_path, Path):
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding legacy settings paths are unavailable"
        )
    if any(
        list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        )
        != _EXPECTED[domain]
        for domain in _DOMAINS
        if domain not in {"desired_state", "instance_state"}
    ):
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding first-B snapshot is not builtin-only"
        )
    classify_coding_legacy_management_members(
        desired_members=list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="desired_state"
        ),
        instance_members=list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="instance_state"
        ),
        lock_members=(),
        has_binding=False,
    )
    source = read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    if source.classification.configured_source_keys:
        raise CodingLegacyBuiltinOnlyReviewError(
            "Coding first-B snapshot has configured Sources"
        )
    inventory = read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    ).inventory
    _require_builtin_only_inventory(inventory)
    epoch_runtime.assert_current()
    return CodingLegacyBuiltinOnlyReviewV1(
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


__all__ = [
    "CodingLegacyBuiltinOnlyReviewError",
    "CodingLegacyBuiltinOnlyReviewV1",
    "admit_coding_builtin_only_snapshot",
    "review_coding_first_b_builtin_only",
]
