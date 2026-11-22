"""Frozen review for old local Installations removed before Product cutover."""

from __future__ import annotations

import json as json
import re
from dataclasses import dataclass, field, fields
from hashlib import sha256 as sha256
from pathlib import Path as Path
from typing import cast

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_removed_review import (
    LEGACY_REMOVAL_STORE_ROOTS,
    LegacyRemovalFacts,
    LegacyRemovalSnapshot,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverError as PackagePosixEpochCutoverError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_classification import CodingScopedLegacyDisableV1
from .legacy_configured_source import _index_configured_sources
from .legacy_desired_evidence import CodingLegacyDesiredError
from .legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence as parse_coding_legacy_desired_evidence,
)
from .legacy_installation_inventory import (
    _BUILTINS,
    _MAX_REMOVAL_BINDINGS,
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInventoryError,
    CodingLegacyRemovedLocalInstallationV1,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_installations as classify_coding_legacy_installations,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_removed_local_installations as classify_coding_legacy_removed_local_installations,
)
from .legacy_instance_evidence import (
    CodingLegacyInstanceEvidenceError,
    _management_capture_paths,
)
from .legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture as parse_coding_legacy_retired_instance_capture,
)
from .legacy_lock_evidence import (
    CodingLegacyLocalBindingEvidenceV1,
    CodingLegacyLockError,
)
from .legacy_lock_evidence import (
    parse_coding_legacy_local_binding_heads as parse_coding_legacy_local_binding_heads,
)
from .legacy_operation_evidence import (
    CodingLegacyOperationEvidenceError as CodingLegacyOperationEvidenceError,
)
from .legacy_operation_evidence import (
    CodingLegacyRetirementCaptureV1 as CodingLegacyRetirementCaptureV1,
)
from .legacy_operation_evidence import (
    classify_coding_legacy_management_members as classify_coding_legacy_management_members,
)
from .legacy_operation_evidence import (
    parse_coding_legacy_operation_evidence as parse_coding_legacy_operation_evidence,
)
from .legacy_snapshot_member import _snapshot_reader
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)
from .legacy_source_evidence import (
    read_coding_legacy_source_evidence as read_coding_legacy_source_evidence,
)
from .pre_b_snapshot import CodingPreBSnapshotPreparation
from .source_snapshot import _PROJECTION_NAME

_REMOVABLE_BUILTINS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


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
        result = cast(dict[str, str], _ENTRY_SCHEMA.encode(self))
        if self.head_operation_id is not None:
            assert self.head_transition_kind is not None
            result["headOperationId"] = self.head_operation_id
            result["headTransitionKind"] = self.head_transition_kind
        return result

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyRemovedReviewEntryV1:
        keys = _ENTRY_SCHEMA.keys
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
            **_ENTRY_SCHEMA.decode(dict, value),
            head_operation_id=value.get("headOperationId"),
            head_transition_kind=value.get("headTransitionKind"),
        )


_ENTRY_SCHEMA = RecordSchema(
    lambda value: value,
    tuple(
        RecordField(item.name)
        for item in fields(CodingLegacyRemovedReviewEntryV1)
        if item.name not in {"head_operation_id", "head_transition_kind"}
    ),
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
                type(root) is not str or root not in LEGACY_REMOVAL_STORE_ROOTS
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
            **_REVIEW_SCHEMA.encode(self),
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
        expected = _REVIEW_SCHEMA.keys | {
            "reviewId",
            "removedLocal",
            "reviewVersion",
            "removedBuiltinIds",
            "builtinIntent",
            "disabledPlugins",
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
                **_REVIEW_SCHEMA.decode(dict, value),
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


_REVIEW_SCHEMA = RecordSchema(
    lambda value: value,
    tuple(
        RecordField(item.name)
        for item in fields(CodingLegacyRemovedReviewV1)
        if item.name
        not in {
            "disabled_plugins",
            "builtin_intent",
            "removed_builtin_ids",
            "removed_local",
            "review_version",
            "operation_journal_digest",
            "retained_store_roots",
            "review_id",
        }
    ),
)


def admit_coding_removed_local_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    prepared: CodingPreBSnapshotPreparation,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
) -> None:
    """Check the entire old removal set before the first irreversible fence."""

    try:
        classification = prepared.legacy_classification
        capture = LegacyRemovalSnapshot.before_fence(
            prepared.owner,
            snapshot,
            eligible=classification.kind == "legacy_state"
            and not classification.configured_source_keys,
            source_member=_PROJECTION_NAME,
            review_error=CodingLegacyRemovedReviewError,
            operation_error=CodingLegacyOperationEvidenceError,
            label="Coding",
        )
        facts = _prove_removal(capture, lifecycle)
        if facts.inventory.active_local:
            raise CodingLegacyRemovedReviewError(
                "Old removal preparation requires no active local Installation"
            )
        _require_supported_disabled_plugins(classification.disabled_plugins, facts)
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
    capture = LegacyRemovalSnapshot.after_fence(
        _snapshot_reader(lifecycle, epoch_runtime),
        source_member=_PROJECTION_NAME,
        review_error=CodingLegacyRemovedReviewError,
        operation_error=CodingLegacyOperationEvidenceError,
        label="Coding",
    )
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
    facts = _prove_removal(capture, lifecycle)
    inventory = facts.inventory
    active_identities = tuple(
        binding.source_identity for binding, _, _ in inventory.active_local
    )
    if active_identities:
        _index_configured_sources(
            json.loads(source.projection_bytes), active_identities
        )
    elif source.classification.configured_source_keys:
        raise CodingLegacyRemovedReviewError("Old removal Source set is unsupported")
    disables = source.classification.disabled_plugins
    _require_supported_disabled_plugins(disables, facts)
    review_version = (
        2
        if capture.has_operations
        or any(item.head_transition_kind == "update" for item in facts.removed)
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
        lockfile_digest=facts.removed[0].binding.lockfile_digest,
        desired_journal_digest=facts.desired_digest,
        disabled_plugins=disables,
        builtin_intent=tuple(
            CodingLegacyBuiltinIntentV1(*item) for item in inventory.builtin_intent
        ),
        removed_builtin_ids=tuple(
            item for item in inventory.removed_plugin_ids if item in _REMOVABLE_BUILTINS
        ),
        removed_local=tuple(
            CodingLegacyRemovedReviewEntryV1.from_evidence(
                CodingLegacyRemovedLocalInstallationV1(
                    CodingLegacyLocalBindingEvidenceV1(*item.binding),
                    item.install_operation_id,
                    item.remove_operation_id,
                    item.head_operation_id,
                    item.head_transition_kind,
                ),
                review_version=review_version,
            )
            for item in facts.removed
        ),
        review_version=review_version,
        operation_journal_digest=facts.operation_digest,
        retained_store_roots=capture.retained_store_roots,
    )


def _prove_removal(
    capture: LegacyRemovalSnapshot, lifecycle: CodingPluginLifecycleStateLayout
) -> LegacyRemovalFacts:
    return capture.prove(
        desired_path=lifecycle.desired_state,
        management_paths=_management_capture_paths(lifecycle),
        product_id="coding",
        scope_id=lifecycle.scope_id,
        builtin_ids=_BUILTINS,
        maximum_bindings=_MAX_REMOVAL_BINDINGS,
        inventory_error=CodingLegacyInventoryError,
        lock_error=CodingLegacyLockError,
        desired_error=CodingLegacyDesiredError,
        instance_error=CodingLegacyInstanceEvidenceError,
    )


def _require_supported_disabled_plugins(
    disables: tuple[CodingScopedLegacyDisableV1, ...], facts: LegacyRemovalFacts
) -> None:
    allowed = _BUILTINS | {item.binding.plugin_id for item in facts.removed}
    if any(item.plugin_id not in allowed for item in disables):
        raise CodingLegacyRemovedReviewError("Old disable set is unsupported")


__all__ = [
    "CodingLegacyRemovedReviewEntryV1",
    "CodingLegacyRemovedReviewError",
    "CodingLegacyRemovedReviewV1",
    "admit_coding_removed_local_snapshot",
    "review_coding_first_b_removed_local",
]
