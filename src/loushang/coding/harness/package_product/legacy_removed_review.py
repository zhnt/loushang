"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING

from loushang.coding.harness.package_product.legacy_management_evidence import (
    read_settled_management_history,
)
from loushang.coding.package import legacy_removed_review as _binding

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
    for domain in ("desired_state", "instance_state", "lock_history"):
        for name in members[domain]:
            if (
                name.endswith(".lock")
                and read_member(domain=domain, member_name=name, maximum_bytes=8)
                != b"\0"
            ):
                raise _binding.CodingLegacyRemovedReviewError(
                    _binding._LEGACY_PROGRAM_VALUES["value_013"]
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
    return read_settled_management_history(
        lifecycle=lifecycle,
        instance_members=instance_members,
        desired=desired,
        read_member=read_member,
        receiver=_binding,
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


def validate_entry(self: _binding.CodingLegacyRemovedReviewEntryV1) -> None:
    if (
        type(self.plugin_id) is not str
        or _binding._SAFE_ID.fullmatch(self.plugin_id) is None
        or type(self.source_identity) is not str
        or not self.source_identity.startswith("local:/")
        or any(
            type(value) is not str or _binding._SHA256.fullmatch(value) is None
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
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal entry is invalid"
        )


def entry_from_evidence(
    cls: type[_binding.CodingLegacyRemovedReviewEntryV1],
    item: _binding.CodingLegacyRemovedLocalInstallationV1,
    *,
    review_version: int,
) -> _binding.CodingLegacyRemovedReviewEntryV1:
    if review_version not in {1, 2} or (
        review_version == 1 and item.head_transition_kind == "update"
    ):
        raise _binding.CodingLegacyRemovedReviewError(
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


def decode_entry(
    cls: type[_binding.CodingLegacyRemovedReviewEntryV1], value: object
) -> _binding.CodingLegacyRemovedReviewEntryV1:
    keys = _binding._ENTRY_SCHEMA.keys
    if type(value) is not dict or set(value) not in (
        keys,
        keys | {"headOperationId", "headTransitionKind"},
    ):
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal entry is invalid"
        )
    if "headOperationId" in value and (
        type(value["headOperationId"]) is not str
        or type(value["headTransitionKind"]) is not str
    ):
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal entry is invalid"
        )
    return cls(
        **_binding._ENTRY_SCHEMA.decode(dict, value),
        head_operation_id=value.get("headOperationId"),
        head_transition_kind=value.get("headTransitionKind"),
    )


def validate_review(self: _binding.CodingLegacyRemovedReviewV1) -> None:
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
        or _binding._SAFE_ID.fullmatch(self.store_id) is None
        or type(self.scope_id) is not str
        or not self.scope_id.startswith("workspace:")
        or type(self.review_version) is not int
        or self.review_version not in {1, 2}
        or type(self.retained_store_roots) is not tuple
        or any(
            type(root) is not str or root not in _binding._RETAINED_STORE_ROOTS
            for root in self.retained_store_roots
        )
        or self.retained_store_roots != tuple(sorted(set(self.retained_store_roots)))
        or (
            self.operation_journal_digest is not None
            and (
                self.review_version != 2
                or type(self.operation_journal_digest) is not str
                or _binding._SHA256.fullmatch(self.operation_journal_digest) is None
            )
        )
        or any(
            type(value) is not str or _binding._SHA256.fullmatch(value) is None
            for value in digests
        )
        or not 0 < len(self.removed_local) <= 16
        or any(
            not isinstance(item, _binding.CodingLegacyRemovedReviewEntryV1)
            for item in self.removed_local
        )
        or tuple(item.plugin_id for item in self.removed_local)
        != tuple(sorted({item.plugin_id for item in self.removed_local}))
        or any(
            item.plugin_id in _binding._BUILTINS
            or not item.source_identity.startswith("local:/")
            for item in self.removed_local
        )
        or (
            self.review_version == 1
            and any(item.head_operation_id is not None for item in self.removed_local)
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
        or any(
            item not in _binding._REMOVABLE_BUILTINS
            for item in self.removed_builtin_ids
        )
        or tuple(sorted(set(self.removed_builtin_ids))) != self.removed_builtin_ids
        or any(item.plugin_id not in _binding._BUILTINS for item in self.builtin_intent)
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
            not isinstance(item, _binding.CodingScopedLegacyDisableV1)
            or item.scope not in ("global", "project")
            or _binding._SAFE_ID.fullmatch(item.plugin_id) is None
            for item in self.disabled_plugins
        )
        or len({(item.scope, item.plugin_id) for item in self.disabled_plugins})
        != len(self.disabled_plugins)
        or any(
            item.plugin_id
            not in _binding._BUILTINS
            | {local.plugin_id for local in self.removed_local}
            for item in self.disabled_plugins
        )
    ):
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal review is invalid"
        )
    object.__setattr__(
        self,
        "review_id",
        _binding.sha256(_binding.canonical_json_bytes(self._identity())).hexdigest(),
    )


def decode_review(
    cls: type[_binding.CodingLegacyRemovedReviewV1], value: object
) -> _binding.CodingLegacyRemovedReviewV1:
    expected = _binding._REVIEW_SCHEMA.keys | {
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
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal review is invalid"
        )
    if (
        "operationJournalDigest" in value
        and type(value["operationJournalDigest"]) is not str
    ):
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal review is invalid"
        )
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
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal entries are invalid"
        )
    try:
        review = cls(
            **_binding._REVIEW_SCHEMA.decode(dict, value),
            disabled_plugins=tuple(
                _binding.CodingScopedLegacyDisableV1(item["scope"], item["pluginId"])
                for item in disabled
            ),
            builtin_intent=tuple(
                _binding.CodingLegacyBuiltinIntentV1(
                    item["pluginId"], item["desiredState"]
                )
                for item in builtins
            ),
            removed_builtin_ids=tuple(removed_builtin),
            removed_local=tuple(
                _binding.CodingLegacyRemovedReviewEntryV1.from_dict(item)
                for item in removed_local
            ),
            review_version=value["reviewVersion"],
            operation_journal_digest=value.get("operationJournalDigest"),
            retained_store_roots=tuple(retained_store),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal review is invalid"
        ) from exc
    if review.review_id != value["reviewId"]:
        raise _binding.CodingLegacyRemovedReviewError(
            "Old local removal review ID changed"
        )
    return review
