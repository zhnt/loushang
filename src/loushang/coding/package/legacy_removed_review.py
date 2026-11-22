"""Frozen review for old local Installations removed before Product cutover."""

from __future__ import annotations

import json as json
import re
from dataclasses import dataclass, field, fields
from hashlib import sha256 as sha256
from pathlib import Path as Path
from typing import cast

from loushang.coding.harness.package_product import legacy_removed_review as _programs
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
