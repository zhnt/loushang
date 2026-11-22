"""Frozen review for old local Installations removed before Product cutover."""

from __future__ import annotations

import json as json
from dataclasses import dataclass, field
from hashlib import sha256 as sha256
from pathlib import Path as Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_removed_review import (
    LegacyRemovalEntryRecord,
    LegacyRemovalFacts,
    LegacyRemovalReviewRecord,
    LegacyRemovalSnapshot,
)
from loushang.harness.package_product._legacy_runtime import (
    legacy_review_fence_identity,
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


class CodingLegacyRemovedReviewError(ValueError):
    """The old removal set cannot be reviewed for Product adoption."""


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedReviewEntryV1(LegacyRemovalEntryRecord):
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

    _error_type = CodingLegacyRemovedReviewError

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


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedReviewV1(LegacyRemovalReviewRecord):
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

    _error_type = CodingLegacyRemovedReviewError
    _entry_type = CodingLegacyRemovedReviewEntryV1
    _disable_type = CodingScopedLegacyDisableV1
    _builtin_intent_type = CodingLegacyBuiltinIntentV1
    _builtin_ids = _BUILTINS
    _removable_builtin_ids = _REMOVABLE_BUILTINS
    _maximum_entries = _MAX_REMOVAL_BINDINGS


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

    identity = legacy_review_fence_identity(
        epoch_runtime,
        missing=CodingLegacyRemovedReviewError("Coding first-B fence is missing"),
    )
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
        **identity,
        scope_id=lifecycle.scope_id,
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
