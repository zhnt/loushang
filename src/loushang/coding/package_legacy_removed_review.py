"""Frozen review for old local Installations removed before Product cutover."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
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
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_classification import CodingScopedLegacyDisableV1
from .package_legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source,
)
from .package_legacy_desired_evidence import parse_coding_legacy_desired_evidence
from .package_legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyRemovedLocalInstallationV1,
    classify_coding_legacy_installations,
    classify_coding_legacy_removed_local_installations,
)
from .package_legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture,
)
from .package_legacy_lock_evidence import parse_coding_legacy_local_binding_heads
from .package_legacy_operation_evidence import (
    CodingLegacyOperationEvidenceError,
    CodingLegacyRetirementCaptureV1,
    classify_coding_legacy_management_members,
    parse_coding_legacy_operation_evidence,
)
from .package_legacy_snapshot_member import (
    CodingLegacyInventoryDomain,
    list_coding_first_b_snapshot_domain_members,
    read_coding_first_b_snapshot_member,
)
from .package_legacy_source_evidence import read_coding_legacy_source_evidence
from .package_pre_b_snapshot import CodingPreBSnapshotPreparation

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
_REMOVABLE_BUILTINS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_EXPECTED: dict[CodingLegacyInventoryDomain, tuple[str, ...]] = {
    "binding_history": ("package-lock.json",),
    "desired_state": ("desired-state.jsonl",),
    "source_configuration": ("coding-source-configuration.json",),
    "enablement_state": (),
    "instance_state": (),
    "lock_history": ("package-lock.json",),
    "store_bytes": (),
}
_RETAINED_STORE_ROOTS = frozenset({"installed", "plugin-revisions"})


def _removed_snapshot_has_operations(
    members: Mapping[CodingLegacyInventoryDomain, tuple[str, ...]],
) -> bool:
    if any(
        members[domain] != expected
        for domain, expected in _EXPECTED.items()
        if domain
        not in {"desired_state", "instance_state", "lock_history", "store_bytes"}
    ) or members["store_bytes"] not in {
        (),
        ("installed",),
        ("plugin-revisions",),
        ("installed", "plugin-revisions"),
    }:
        raise CodingLegacyRemovedReviewError("Old removal snapshot shape changed")
    try:
        return classify_coding_legacy_management_members(
            desired_members=members["desired_state"],
            instance_members=members["instance_state"],
            lock_members=members["lock_history"],
            allow_retirement=True,
            allow_retired_runtime=True,
        )
    except CodingLegacyOperationEvidenceError as exc:
        raise CodingLegacyRemovedReviewError(
            "Old removal snapshot shape changed"
        ) from exc


class CodingLegacyRemovedReviewError(ValueError):
    """The old removal set cannot be reviewed for Product adoption."""


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedReviewEntryV1:
    plugin_id: str
    source_identity: str
    content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    binding_digest: str
    install_operation_id: str
    remove_operation_id: str
    head_operation_id: str | None = None
    head_transition_kind: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.plugin_id) is not str
            or _SAFE_ID.fullmatch(self.plugin_id) is None
            or type(self.source_identity) is not str
            or not self.source_identity.startswith("local:/")
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.content_digest,
                    self.manifest_digest,
                    self.dependency_lock_digest,
                    self.binding_digest,
                )
            )
            or any(
                type(value) is not str or not value or len(value) > 1024
                for value in (self.install_operation_id, self.remove_operation_id)
            )
            or ((self.head_operation_id is None) != (self.head_transition_kind is None))
            or (
                self.head_operation_id is not None
                and (
                    type(self.head_operation_id) is not str
                    or not self.head_operation_id
                    or len(self.head_operation_id) > 1024
                    or self.head_transition_kind not in {"install", "update"}
                    or (
                        self.head_transition_kind == "install"
                        and self.head_operation_id != self.install_operation_id
                    )
                )
            )
        ):
            raise CodingLegacyRemovedReviewError("Old local removal entry is invalid")

    @classmethod
    def from_evidence(
        cls, item: CodingLegacyRemovedLocalInstallationV1, *, review_version: int = 1
    ) -> CodingLegacyRemovedReviewEntryV1:
        if review_version not in {1, 2} or (
            review_version == 1 and item.head_transition_kind == "update"
        ):
            raise CodingLegacyRemovedReviewError(
                "Old local removal review version is invalid"
            )
        binding = item.binding
        return cls(
            plugin_id=binding.plugin_id,
            source_identity=binding.source_identity,
            content_digest=binding.content_digest,
            manifest_digest=binding.manifest_digest,
            dependency_lock_digest=binding.dependency_lock.digest,
            binding_digest=binding.binding_digest,
            install_operation_id=item.install_operation_id,
            remove_operation_id=item.remove_operation_id,
            head_operation_id=(item.head_operation_id if review_version == 2 else None),
            head_transition_kind=(
                item.head_transition_kind if review_version == 2 else None
            ),
        )

    def to_dict(self) -> dict[str, str]:
        result = {
            "pluginId": self.plugin_id,
            "sourceIdentity": self.source_identity,
            "contentDigest": self.content_digest,
            "manifestDigest": self.manifest_digest,
            "dependencyLockDigest": self.dependency_lock_digest,
            "bindingDigest": self.binding_digest,
            "installOperationId": self.install_operation_id,
            "removeOperationId": self.remove_operation_id,
        }
        if self.head_operation_id is not None:
            assert self.head_transition_kind is not None
            result["headOperationId"] = self.head_operation_id
            result["headTransitionKind"] = self.head_transition_kind
        return result

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyRemovedReviewEntryV1:
        keys = {
            "pluginId",
            "sourceIdentity",
            "contentDigest",
            "manifestDigest",
            "dependencyLockDigest",
            "bindingDigest",
            "installOperationId",
            "removeOperationId",
        }
        if type(value) is not dict or set(value) not in (
            keys,
            keys | {"headOperationId", "headTransitionKind"},
        ):
            raise CodingLegacyRemovedReviewError("Old local removal entry is invalid")
        if "headOperationId" in value and (
            type(value["headOperationId"]) is not str
            or type(value["headTransitionKind"]) is not str
        ):
            raise CodingLegacyRemovedReviewError("Old local removal entry is invalid")
        return cls(
            plugin_id=value["pluginId"],
            source_identity=value["sourceIdentity"],
            content_digest=value["contentDigest"],
            manifest_digest=value["manifestDigest"],
            dependency_lock_digest=value["dependencyLockDigest"],
            binding_digest=value["bindingDigest"],
            install_operation_id=value["installOperationId"],
            remove_operation_id=value["removeOperationId"],
            head_operation_id=value.get("headOperationId"),
            head_transition_kind=value.get("headTransitionKind"),
        )


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedReviewV1:
    store_id: str
    namespace_id: str
    scope_id: str
    first_fence_id: str
    snapshot_receipt_id: str
    source_projection_digest: str
    lockfile_digest: str
    desired_journal_digest: str
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...]
    removed_builtin_ids: tuple[str, ...]
    removed_local: tuple[CodingLegacyRemovedReviewEntryV1, ...]
    review_version: int = 1
    operation_journal_digest: str | None = None
    retained_store_roots: tuple[str, ...] = ()
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
        digests = (
            self.namespace_id,
            self.first_fence_id,
            self.snapshot_receipt_id,
            self.source_projection_digest,
            self.lockfile_digest,
            self.desired_journal_digest,
        )
        if (
            type(self.store_id) is not str
            or _SAFE_ID.fullmatch(self.store_id) is None
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.review_version) is not int
            or self.review_version not in {1, 2}
            or type(self.retained_store_roots) is not tuple
            or any(
                type(root) is not str or root not in _RETAINED_STORE_ROOTS
                for root in self.retained_store_roots
            )
            or self.retained_store_roots
            != tuple(sorted(set(self.retained_store_roots)))
            or (
                self.operation_journal_digest is not None
                and (
                    self.review_version != 2
                    or type(self.operation_journal_digest) is not str
                    or _SHA256.fullmatch(self.operation_journal_digest) is None
                )
            )
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in digests
            )
            or not 0 < len(self.removed_local) <= 16
            or any(
                not isinstance(item, CodingLegacyRemovedReviewEntryV1)
                for item in self.removed_local
            )
            or tuple(item.plugin_id for item in self.removed_local)
            != tuple(sorted({item.plugin_id for item in self.removed_local}))
            or any(
                item.plugin_id in _BUILTINS
                or not item.source_identity.startswith("local:/")
                for item in self.removed_local
            )
            or (
                self.review_version == 1
                and any(
                    item.head_operation_id is not None for item in self.removed_local
                )
            )
            or (
                self.review_version == 2
                and (
                    any(item.head_operation_id is None for item in self.removed_local)
                    or (
                        not any(
                            item.head_transition_kind == "update"
                            for item in self.removed_local
                        )
                        and self.operation_journal_digest is None
                    )
                )
            )
            or any(item not in _REMOVABLE_BUILTINS for item in self.removed_builtin_ids)
            or tuple(sorted(set(self.removed_builtin_ids))) != self.removed_builtin_ids
            or any(item.plugin_id not in _BUILTINS for item in self.builtin_intent)
            or any(
                item.desired_state not in ("installed_disabled", "installed_enabled")
                for item in self.builtin_intent
            )
            or tuple(item.plugin_id for item in self.builtin_intent)
            != tuple(sorted({item.plugin_id for item in self.builtin_intent}))
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
            or any(
                not isinstance(item, CodingScopedLegacyDisableV1)
                or item.scope not in ("global", "project")
                or _SAFE_ID.fullmatch(item.plugin_id) is None
                for item in self.disabled_plugins
            )
            or len({(item.scope, item.plugin_id) for item in self.disabled_plugins})
            != len(self.disabled_plugins)
            or any(
                item.plugin_id
                not in _BUILTINS | {local.plugin_id for local in self.removed_local}
                for item in self.disabled_plugins
            )
        ):
            raise CodingLegacyRemovedReviewError("Old local removal review is invalid")
        object.__setattr__(
            self,
            "review_id",
            sha256(canonical_json_bytes(self._identity())).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        identity = {
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "firstFenceId": self.first_fence_id,
            "snapshotReceiptId": self.snapshot_receipt_id,
            "sourceProjectionDigest": self.source_projection_digest,
            "lockfileDigest": self.lockfile_digest,
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
            "removedLocal": [item.to_dict() for item in self.removed_local],
            "reviewVersion": self.review_version,
        }
        if self.operation_journal_digest is not None:
            identity["operationJournalDigest"] = self.operation_journal_digest
        if self.retained_store_roots:
            identity["retainedStoreRoots"] = list(self.retained_store_roots)
        return identity

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "reviewId": self.review_id}

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyRemovedReviewV1:
        expected = {
            "storeId",
            "namespaceId",
            "scopeId",
            "firstFenceId",
            "snapshotReceiptId",
            "sourceProjectionDigest",
            "lockfileDigest",
            "desiredJournalDigest",
            "disabledPlugins",
            "builtinIntent",
            "removedBuiltinIds",
            "removedLocal",
            "reviewVersion",
            "reviewId",
        }
        if (
            type(value) is not dict
            or not expected <= set(value)
            or set(value) - expected
            not in (
                set(),
                {"operationJournalDigest"},
                {"retainedStoreRoots"},
                {"operationJournalDigest", "retainedStoreRoots"},
            )
        ):
            raise CodingLegacyRemovedReviewError("Old local removal review is invalid")
        if (
            "operationJournalDigest" in value
            and type(value["operationJournalDigest"]) is not str
        ):
            raise CodingLegacyRemovedReviewError("Old local removal review is invalid")
        disabled = value["disabledPlugins"]
        builtins = value["builtinIntent"]
        removed_builtin = value["removedBuiltinIds"]
        removed_local = value["removedLocal"]
        retained_store = value.get("retainedStoreRoots", [])
        if (
            type(disabled) is not list
            or any(
                type(item) is not dict or set(item) != {"scope", "pluginId"}
                for item in disabled
            )
            or type(builtins) is not list
            or any(
                type(item) is not dict or set(item) != {"pluginId", "desiredState"}
                for item in builtins
            )
            or type(removed_builtin) is not list
            or type(removed_local) is not list
            or type(retained_store) is not list
            or ("retainedStoreRoots" in value and not retained_store)
        ):
            raise CodingLegacyRemovedReviewError(
                "Old local removal entries are invalid"
            )
        try:
            review = cls(
                store_id=value["storeId"],
                namespace_id=value["namespaceId"],
                scope_id=value["scopeId"],
                first_fence_id=value["firstFenceId"],
                snapshot_receipt_id=value["snapshotReceiptId"],
                source_projection_digest=value["sourceProjectionDigest"],
                lockfile_digest=value["lockfileDigest"],
                desired_journal_digest=value["desiredJournalDigest"],
                disabled_plugins=tuple(
                    CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                    for item in disabled
                ),
                builtin_intent=tuple(
                    CodingLegacyBuiltinIntentV1(item["pluginId"], item["desiredState"])
                    for item in builtins
                ),
                removed_builtin_ids=tuple(removed_builtin),
                removed_local=tuple(
                    CodingLegacyRemovedReviewEntryV1.from_dict(item)
                    for item in removed_local
                ),
                review_version=value["reviewVersion"],
                operation_journal_digest=value.get("operationJournalDigest"),
                retained_store_roots=tuple(retained_store),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CodingLegacyRemovedReviewError(
                "Old local removal review is invalid"
            ) from exc
        if review.review_id != value["reviewId"]:
            raise CodingLegacyRemovedReviewError("Old local removal review ID changed")
        return review


def admit_coding_removed_local_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    prepared: CodingPreBSnapshotPreparation,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
) -> None:
    """Check the entire old removal set before the first irreversible fence."""

    try:
        owner = prepared.owner
        evidence = owner.snapshot(snapshot.receipt_id)
        members: dict[CodingLegacyInventoryDomain, tuple[str, ...]] = {
            domain: owner.list_domain_members(snapshot.receipt_id, domain=domain) or ()
            for domain in _EXPECTED
        }
        if (
            prepared.legacy_classification.kind != "legacy_state"
            or prepared.legacy_classification.configured_source_keys
            or evidence is None
            or evidence.snapshot != snapshot
        ):
            raise CodingLegacyRemovedReviewError("Old removal snapshot shape changed")
        has_operations = _removed_snapshot_has_operations(members)
        for domain in ("desired_state", "instance_state", "lock_history"):
            for name in members[domain]:
                if (
                    name.endswith(".lock")
                    and owner.read_regular_member(
                        snapshot.receipt_id,
                        domain=domain,
                        member_name=name,
                        maximum_bytes=8,
                    )
                    != b"\0"
                ):
                    raise CodingLegacyRemovedReviewError(
                        "Old removal journal lock changed"
                    )
        lock_raw = owner.read_regular_member(
            snapshot.receipt_id,
            domain="binding_history",
            member_name="package-lock.json",
        )
        desired_raw = owner.read_regular_member(
            snapshot.receipt_id,
            domain="desired_state",
            member_name="desired-state.jsonl",
        )
        if lock_raw is None or desired_raw is None:
            raise CodingLegacyRemovedReviewError("Old removal evidence is missing")
        bindings = parse_coding_legacy_local_binding_heads(lock_raw)
        desired = parse_coding_legacy_desired_evidence(desired_raw, lifecycle=lifecycle)
        inventory = classify_coding_legacy_installations(
            bindings, desired, scope_id=lifecycle.scope_id
        )
        removed = classify_coding_legacy_removed_local_installations(
            bindings,
            desired,
            scope_id=lifecycle.scope_id,
        )
        if has_operations:
            operations_raw = owner.read_regular_member(
                snapshot.receipt_id,
                domain="desired_state",
                member_name="management-operations.jsonl",
            )
            if operations_raw is None:
                raise CodingLegacyRemovedReviewError(
                    "Old management operation evidence is missing"
                )
            retirements = None
            if "retirement-intents.jsonl" in members["instance_state"]:
                intents_raw = owner.read_regular_member(
                    snapshot.receipt_id,
                    domain="instance_state",
                    member_name="retirement-intents.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                sets_raw = owner.read_regular_member(
                    snapshot.receipt_id,
                    domain="instance_state",
                    member_name="retirement-sets.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                if intents_raw is None or sets_raw is None:
                    raise CodingLegacyRemovedReviewError(
                        "Old retirement evidence is missing"
                    )
                retirements = CodingLegacyRetirementCaptureV1(
                    intents_raw=intents_raw,
                    sets_raw=sets_raw,
                    intents_path=lifecycle.retirement_intents,
                    sets_path=lifecycle.retirement_sets,
                )
            parse_coding_legacy_operation_evidence(
                operations_raw,
                desired=desired,
                path=lifecycle.management_operations,
                retirements=retirements,
            )
            if "instance-runtime.jsonl" in members["instance_state"]:
                runtime_raw = owner.read_regular_member(
                    snapshot.receipt_id,
                    domain="instance_state",
                    member_name="instance-runtime.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                if runtime_raw is None or retirements is None:
                    raise CodingLegacyRemovedReviewError(
                        "Old Instance evidence is missing"
                    )
                parse_coding_legacy_retired_instance_capture(
                    runtime_raw,
                    intents_raw=retirements.intents_raw,
                    sets_raw=retirements.sets_raw,
                    desired=desired,
                    lifecycle=lifecycle,
                )
        if inventory.active_local:
            raise CodingLegacyRemovedReviewError(
                "Old removal preparation requires no active local Installation"
            )
        allowed = _BUILTINS | {item.binding.plugin_id for item in removed}
        if any(
            item.plugin_id not in allowed
            for item in prepared.legacy_classification.disabled_plugins
        ):
            raise CodingLegacyRemovedReviewError("Old disable set is unsupported")
    except PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PackagePosixEpochCutoverError(
            "Coding removed local snapshot cannot be admitted before first fence",
            code="coding_legacy_removed_snapshot_refused",
        ) from exc


def review_coding_first_b_removed_local(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyRemovedReviewV1:
    """Project one authenticated old removal set without Product mutation."""

    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    if fence is None or switch is None:
        raise CodingLegacyRemovedReviewError("Coding first-B fence is missing")
    members: dict[CodingLegacyInventoryDomain, tuple[str, ...]] = {
        domain: list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        )
        for domain in _EXPECTED
    }
    has_operations = _removed_snapshot_has_operations(members)
    for domain in ("desired_state", "instance_state", "lock_history"):
        for name in members[domain]:
            if (
                name.endswith(".lock")
                and read_coding_first_b_snapshot_member(
                    lifecycle,
                    epoch_runtime,
                    domain=domain,
                    member_name=name,
                    maximum_bytes=8,
                )
                != b"\0"
            ):
                raise CodingLegacyRemovedReviewError("Old removal journal lock changed")
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if not isinstance(global_path, Path) or not isinstance(project_path, Path):
        raise CodingLegacyRemovedReviewError("Old settings paths are unavailable")
    source = read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    lock_raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="binding_history",
        member_name="package-lock.json",
        maximum_bytes=2 * 1024 * 1024,
    )
    desired_raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="desired_state",
        member_name="desired-state.jsonl",
        maximum_bytes=2 * 1024 * 1024,
    )
    if lock_raw is None or desired_raw is None:
        raise CodingLegacyRemovedReviewError("Old removal evidence is missing")
    bindings = parse_coding_legacy_local_binding_heads(lock_raw)
    desired = parse_coding_legacy_desired_evidence(desired_raw, lifecycle=lifecycle)
    operation_digest: str | None = None
    if has_operations:
        operations_raw = read_coding_first_b_snapshot_member(
            lifecycle,
            epoch_runtime,
            domain="desired_state",
            member_name="management-operations.jsonl",
            maximum_bytes=2 * 1024 * 1024,
        )
        if operations_raw is None:
            raise CodingLegacyRemovedReviewError(
                "Old management operation evidence is missing"
            )
        retirements = None
        if "retirement-intents.jsonl" in members["instance_state"]:
            intents_raw = read_coding_first_b_snapshot_member(
                lifecycle,
                epoch_runtime,
                domain="instance_state",
                member_name="retirement-intents.jsonl",
                maximum_bytes=2 * 1024 * 1024,
            )
            sets_raw = read_coding_first_b_snapshot_member(
                lifecycle,
                epoch_runtime,
                domain="instance_state",
                member_name="retirement-sets.jsonl",
                maximum_bytes=2 * 1024 * 1024,
            )
            if intents_raw is None or sets_raw is None:
                raise CodingLegacyRemovedReviewError(
                    "Old retirement evidence is missing"
                )
            retirements = CodingLegacyRetirementCaptureV1(
                intents_raw=intents_raw,
                sets_raw=sets_raw,
                intents_path=lifecycle.retirement_intents,
                sets_path=lifecycle.retirement_sets,
            )
        operation_digest = parse_coding_legacy_operation_evidence(
            operations_raw,
            desired=desired,
            path=lifecycle.management_operations,
            retirements=retirements,
        ).journal_digest
        if "instance-runtime.jsonl" in members["instance_state"]:
            runtime_raw = read_coding_first_b_snapshot_member(
                lifecycle,
                epoch_runtime,
                domain="instance_state",
                member_name="instance-runtime.jsonl",
                maximum_bytes=2 * 1024 * 1024,
            )
            if runtime_raw is None or retirements is None:
                raise CodingLegacyRemovedReviewError("Old Instance evidence is missing")
            parse_coding_legacy_retired_instance_capture(
                runtime_raw,
                intents_raw=retirements.intents_raw,
                sets_raw=retirements.sets_raw,
                desired=desired,
                lifecycle=lifecycle,
            )
    removed = classify_coding_legacy_removed_local_installations(
        bindings, desired, scope_id=lifecycle.scope_id
    )
    inventory = classify_coding_legacy_installations(
        bindings, desired, scope_id=lifecycle.scope_id
    )
    active_identities = tuple(
        item.binding.source_identity for item in inventory.active_local
    )
    if active_identities:
        source_projection = json.loads(source.projection_bytes)
        for identity in active_identities:
            match_coding_legacy_local_skill_configured_source(
                source_projection,
                source_identity=identity,
                installed_source_identities=active_identities,
            )
    elif source.classification.configured_source_keys:
        raise CodingLegacyRemovedReviewError("Old removal Source set is unsupported")
    allowed = _BUILTINS | {item.binding.plugin_id for item in removed}
    if any(
        item.plugin_id not in allowed for item in source.classification.disabled_plugins
    ):
        raise CodingLegacyRemovedReviewError("Old disable set is unsupported")
    removed_builtin_ids = tuple(
        item for item in inventory.removed_plugin_ids if item in _REMOVABLE_BUILTINS
    )
    review_version = (
        2
        if has_operations
        or any(item.head_transition_kind == "update" for item in removed)
        else 1
    )
    epoch_runtime.assert_current()
    return CodingLegacyRemovedReviewV1(
        store_id=fence.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
        source_projection_digest=source.projection_digest,
        lockfile_digest=bindings[0].lockfile_digest,
        desired_journal_digest=desired.journal_digest,
        disabled_plugins=source.classification.disabled_plugins,
        builtin_intent=inventory.builtin_intent,
        removed_builtin_ids=removed_builtin_ids,
        removed_local=tuple(
            CodingLegacyRemovedReviewEntryV1.from_evidence(
                item, review_version=review_version
            )
            for item in removed
        ),
        review_version=review_version,
        operation_journal_digest=operation_digest,
        retained_store_roots=members["store_bytes"],
    )


__all__ = [
    "CodingLegacyRemovedReviewEntryV1",
    "CodingLegacyRemovedReviewError",
    "CodingLegacyRemovedReviewV1",
    "admit_coding_removed_local_snapshot",
    "review_coding_first_b_removed_local",
]
