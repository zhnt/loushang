"""Frozen review for old local Installations removed before Product cutover."""

from __future__ import annotations

import json as json
import re
from dataclasses import dataclass, field, fields
from hashlib import sha256 as sha256
from pathlib import Path as Path
from typing import cast

from loushang.coding.harness.package_product import legacy_removed_review as _programs
from loushang.coding.harness.package_product import (
    legacy_removed_review as _record_programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
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
from .legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source as match_coding_legacy_local_skill_configured_source,
)
from .legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence as parse_coding_legacy_desired_evidence,
)
from .legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyRemovedLocalInstallationV1,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_installations as classify_coding_legacy_installations,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_removed_local_installations as classify_coding_legacy_removed_local_installations,
)
from .legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture as parse_coding_legacy_retired_instance_capture,
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
from .legacy_snapshot_member import (
    CodingLegacyInventoryDomain,
)
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


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Old removal snapshot shape changed",
    "value_002": "package-lock.json",
    "value_003": "desired-state.jsonl",
    "value_004": "Old removal evidence is missing",
    "value_007": "Old removal preparation requires no active local Installation",
    "value_008": "Old disable set is unsupported",
    "value_009": "Coding removed local snapshot cannot be admitted before first fence",
    "value_011": "Old management operation evidence is missing",
    "value_012": "coding_legacy_removed_snapshot_refused",
    "value_013": "Old removal journal lock changed",
    "value_015": "Old retirement evidence is missing",
    "value_016": "Old Instance evidence is missing",
    "value_017": "Coding first-B fence is missing",
    "value_018": "Old settings paths are unavailable",
    "value_019": "Old removal Source set is unsupported",
}


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
        return _record_programs.validate_entry(self)

    @classmethod
    def from_evidence(
        cls, item: CodingLegacyRemovedLocalInstallationV1, *, review_version: int = 1
    ) -> CodingLegacyRemovedReviewEntryV1:
        return _record_programs.entry_from_evidence(
            cls, item, review_version=review_version
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
        return _record_programs.decode_entry(cls, value)


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
        return _record_programs.validate_review(self)

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
        return _record_programs.decode_review(cls, value)


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

    return _programs.admit_removed_snapshot(lifecycle, prepared, snapshot)


def review_coding_first_b_removed_local(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyRemovedReviewV1:
    """Project one authenticated old removal set without Product mutation."""

    return _programs.review_removed_snapshot(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )


__all__ = [
    "CodingLegacyRemovedReviewEntryV1",
    "CodingLegacyRemovedReviewError",
    "CodingLegacyRemovedReviewV1",
    "admit_coding_removed_local_snapshot",
    "review_coding_first_b_removed_local",
]
