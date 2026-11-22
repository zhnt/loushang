"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING

from loushang.coding.package import legacy_removed_review as _binding
from loushang.coding.package.legacy_instance_evidence import (
    _read_management_history as _read_coding_management_history,
)
from loushang.harness.package_product._legacy_management_evidence import (
    require_empty_lock_markers,
)

from .legacy_source_matching import index_configured_sources

if TYPE_CHECKING:
    from loushang.coding.package.legacy_desired_evidence import (
        CodingLegacyDesiredEvidenceV1,
    )
    from loushang.coding.package.legacy_lock_evidence import (
        CodingLegacyLocalBindingEvidenceV1,
    )
    from loushang.coding.package.legacy_snapshot_member import (
        CodingLegacyEvidenceDomain,
    )


def snapshot_has_operations(
    members: Mapping[_binding.CodingLegacyInventoryDomain, tuple[str, ...]],
) -> bool:
    if any(
        members[domain] != expected
        for domain, expected in _binding._EXPECTED.items()
        if domain
        not in {"desired_state", "instance_state", "lock_history", "store_bytes"}
    ) or members["store_bytes"] not in {
        (),
        ("installed",),
        ("plugin-revisions",),
        ("installed", "plugin-revisions"),
    }:
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_001"]
        )
    try:
        return _binding.classify_coding_legacy_management_members(
            desired_members=members["desired_state"],
            instance_members=members["instance_state"],
            lock_members=members["lock_history"],
            allow_retirement=True,
            allow_retired_runtime=True,
        )
    except _binding.CodingLegacyOperationEvidenceError as exc:
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_001"]
        ) from exc


def _require_journal_locks(
    members: Mapping[_binding.CodingLegacyInventoryDomain, tuple[str, ...]],
    read_member: Callable[..., bytes | None],
) -> None:
    domains: tuple[CodingLegacyEvidenceDomain, ...] = (
        "desired_state",
        "instance_state",
        "lock_history",
    )
    require_empty_lock_markers(
        read_member,
        (
            (domain, name)
            for domain in domains
            for name in members[domain]
            if name.endswith(".lock")
        ),
        error_type=_binding.CodingLegacyRemovedReviewError,
        message=_binding._LEGACY_PROGRAM_VALUES["value_013"],
    )


def _read_installation_evidence(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    read_member: Callable[..., bytes | None],
) -> tuple[
    tuple[CodingLegacyLocalBindingEvidenceV1, ...],
    CodingLegacyDesiredEvidenceV1,
]:
    lock_raw = read_member(
        domain="binding_history",
        member_name=_binding._LEGACY_PROGRAM_VALUES["value_002"],
    )
    desired_raw = read_member(
        domain="desired_state",
        member_name=_binding._LEGACY_PROGRAM_VALUES["value_003"],
    )
    if lock_raw is None or desired_raw is None:
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_004"]
        )
    return (
        _binding.parse_coding_legacy_local_binding_heads(lock_raw),
        _binding.parse_coding_legacy_desired_evidence(desired_raw, lifecycle=lifecycle),
    )


def _read_management_evidence(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    instance_members: tuple[str, ...],
    desired: CodingLegacyDesiredEvidenceV1,
    read_member: Callable[..., bytes | None],
    *,
    before_fence: bool,
) -> str | None:
    return _read_coding_management_history(
        lifecycle,
        instance_members,
        desired,
        read_member,
        error_type=_binding.CodingLegacyRemovedReviewError,
        missing_messages=(
            _binding._LEGACY_PROGRAM_VALUES["value_011"],
            _binding._LEGACY_PROGRAM_VALUES["value_015"],
            _binding._LEGACY_PROGRAM_VALUES["value_016"],
        ),
        operation_maximum_bytes=None if before_fence else 2 * 1024 * 1024,
        retain_operation_digest=not before_fence,
    )


def admit_removed_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    prepared: _binding.CodingPreBSnapshotPreparation,
    snapshot: _binding.PackageEpochCutoverSnapshotReceiptV1,
) -> None:
    """Check the entire old removal set before the first irreversible fence."""

    try:
        owner = prepared.owner
        evidence = owner.snapshot(snapshot.receipt_id)
        members: dict[_binding.CodingLegacyInventoryDomain, tuple[str, ...]] = {
            domain: owner.list_domain_members(snapshot.receipt_id, domain=domain) or ()
            for domain in _binding._EXPECTED
        }
        if (
            prepared.legacy_classification.kind != "legacy_state"
            or prepared.legacy_classification.configured_source_keys
            or evidence is None
            or evidence.snapshot != snapshot
        ):
            raise _binding.CodingLegacyRemovedReviewError(
                _binding._LEGACY_PROGRAM_VALUES["value_001"]
            )
        has_operations = snapshot_has_operations(members)

        def read_member(
            *, domain: str, member_name: str, **limits: int
        ) -> bytes | None:
            return owner.read_regular_member(
                snapshot.receipt_id, domain=domain, member_name=member_name, **limits
            )

        _require_journal_locks(members, read_member)
        bindings, desired = _read_installation_evidence(lifecycle, read_member)
        inventory = _binding.classify_coding_legacy_installations(
            bindings, desired, scope_id=lifecycle.scope_id
        )
        removed = _binding.classify_coding_legacy_removed_local_installations(
            bindings,
            desired,
            scope_id=lifecycle.scope_id,
        )
        if has_operations:
            _read_management_evidence(
                lifecycle,
                members["instance_state"],
                desired,
                read_member,
                before_fence=True,
            )
        if inventory.active_local:
            raise _binding.CodingLegacyRemovedReviewError(
                _binding._LEGACY_PROGRAM_VALUES["value_007"]
            )
        allowed = _binding._BUILTINS | {item.binding.plugin_id for item in removed}
        if any(
            item.plugin_id not in allowed
            for item in prepared.legacy_classification.disabled_plugins
        ):
            raise _binding.CodingLegacyRemovedReviewError(
                _binding._LEGACY_PROGRAM_VALUES["value_008"]
            )
    except _binding.PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise _binding.PackagePosixEpochCutoverError(
            _binding._LEGACY_PROGRAM_VALUES["value_009"],
            code=_binding._LEGACY_PROGRAM_VALUES["value_012"],
        ) from exc


def review_removed_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: _binding.SettingsManager,
) -> _binding.CodingLegacyRemovedReviewV1:
    """Project one authenticated old removal set without Product mutation."""

    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    if fence is None or switch is None:
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_017"]
        )
    members: dict[_binding.CodingLegacyInventoryDomain, tuple[str, ...]] = {
        domain: _binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        )
        for domain in _binding._EXPECTED
    }
    has_operations = snapshot_has_operations(members)

    def read_member(
        *, domain: CodingLegacyEvidenceDomain, member_name: str, maximum_bytes: int
    ) -> bytes | None:
        return _binding.read_coding_first_b_snapshot_member(
            lifecycle,
            epoch_runtime,
            domain=domain,
            member_name=member_name,
            maximum_bytes=maximum_bytes,
        )

    _require_journal_locks(members, read_member)
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if not isinstance(global_path, _binding.Path) or not isinstance(
        project_path, _binding.Path
    ):
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_018"]
        )
    source = _binding.read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    bindings, desired = _read_installation_evidence(
        lifecycle, partial(read_member, maximum_bytes=2 * 1024 * 1024)
    )
    operation_digest = None
    if has_operations:
        operation_digest = _read_management_evidence(
            lifecycle,
            members["instance_state"],
            desired,
            read_member,
            before_fence=False,
        )
    removed = _binding.classify_coding_legacy_removed_local_installations(
        bindings, desired, scope_id=lifecycle.scope_id
    )
    inventory = _binding.classify_coding_legacy_installations(
        bindings, desired, scope_id=lifecycle.scope_id
    )
    active_identities = tuple(
        item.binding.source_identity for item in inventory.active_local
    )
    if active_identities:
        index_configured_sources(
            _binding.json.loads(source.projection_bytes), active_identities
        )
    elif source.classification.configured_source_keys:
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_019"]
        )
    allowed = _binding._BUILTINS | {item.binding.plugin_id for item in removed}
    if any(
        item.plugin_id not in allowed for item in source.classification.disabled_plugins
    ):
        raise _binding.CodingLegacyRemovedReviewError(
            _binding._LEGACY_PROGRAM_VALUES["value_008"]
        )
    removed_builtin_ids = tuple(
        item
        for item in inventory.removed_plugin_ids
        if item in _binding._REMOVABLE_BUILTINS
    )
    review_version = (
        2
        if has_operations
        or any(item.head_transition_kind == "update" for item in removed)
        else 1
    )
    epoch_runtime.assert_current()
    return _binding.CodingLegacyRemovedReviewV1(
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
            _binding.CodingLegacyRemovedReviewEntryV1.from_evidence(
                item, review_version=review_version
            )
            for item in removed
        ),
        review_version=review_version,
        operation_journal_digest=operation_digest,
        retained_store_roots=members["store_bytes"],
    )
