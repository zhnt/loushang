"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from functools import partial

from loushang.coding.package import legacy_installation_inventory as _binding

from . import legacy_management_evidence as _management_evidence


def read_inventory(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.CodingFencedEpochRuntime,
) -> _binding.CodingLegacyInstallationInventoryEvidenceV1:
    """Join authenticated old lock and desired state under the current B fence."""

    if not isinstance(lifecycle, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_001"])
    if not isinstance(epoch_runtime, _binding.CodingFencedEpochRuntime):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_002"])
    epoch_runtime.assert_current()
    binding_members = _binding.list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="binding_history"
    )
    if binding_members not in ((), (_binding._LEGACY_PROGRAM_VALUES["value_006"],)):
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_003"]
        )
    unbound_state_domains: tuple[_binding.CodingLegacyInventoryDomain, ...] = (
        "store_bytes",
        "enablement_state",
    )
    if binding_members == () and any(
        _binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        )
        for domain in unbound_state_domains
    ):
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_004"]
        )
    bindings = (
        _binding.read_coding_legacy_local_binding_heads(lifecycle, epoch_runtime)
        if binding_members
        else ()
    )
    desired_members = _binding.list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="desired_state"
    )
    instance_members = _binding.list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="instance_state"
    )
    lock_members = _binding.list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="lock_history"
    )
    desired: _binding.CodingLegacyDesiredEvidenceV1 | None
    if (
        not binding_members
        and not desired_members
        and not instance_members
        and not lock_members
    ):
        desired = None
    else:
        has_operations = _binding.classify_coding_legacy_management_members(
            desired_members=desired_members,
            instance_members=instance_members,
            lock_members=lock_members,
            has_binding=bool(binding_members),
            allow_retirement=bool(binding_members),
            allow_retired_runtime=bool(binding_members),
        )
        desired = _binding.read_coding_legacy_desired_evidence(lifecycle, epoch_runtime)
        if desired is None:
            raise _binding.CodingLegacyInventoryError(
                _binding._LEGACY_PROGRAM_VALUES["value_007"]
            )
        read_member = partial(
            _binding.read_coding_first_b_snapshot_member, lifecycle, epoch_runtime
        )
        package_lock = _binding._LEGACY_PROGRAM_VALUES["value_008"]
        if package_lock in lock_members:
            _management_evidence.require_empty_lock_markers(
                read_member,
                (("lock_history", package_lock),),
                error_type=_binding.CodingLegacyInventoryError,
                message=_binding._LEGACY_PROGRAM_VALUES["value_009"],
            )
        if has_operations:
            _management_evidence.verify_settled_history(
                lifecycle=lifecycle,
                instance_members=instance_members,
                desired=desired,
                read_member=read_member,
                receiver=_binding,
                error_type=_binding.CodingLegacyInventoryError,
                messages=(
                    _binding._LEGACY_PROGRAM_VALUES["value_017"],
                    _binding._LEGACY_PROGRAM_VALUES["value_020"],
                    _binding._LEGACY_PROGRAM_VALUES["value_022"],
                    _binding._LEGACY_PROGRAM_VALUES["value_023"],
                ),
            )
    inventory = _binding.classify_coding_legacy_installations(
        bindings, desired, scope_id=lifecycle.scope_id
    )
    epoch_runtime.assert_current()
    fence = epoch_runtime.cutover_result.fence
    if fence is None:
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_005"]
        )
    return _binding.CodingLegacyInstallationInventoryEvidenceV1(
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
        inventory=inventory,
    )


def classify_installations(
    bindings: tuple[_binding.CodingLegacyLocalBindingEvidenceV1, ...],
    desired: _binding.CodingLegacyDesiredEvidenceV1 | None,
    *,
    scope_id: str,
) -> _binding.CodingLegacyInstallationInventoryV1:
    """List only exact installed local heads; preserve negative user intent."""

    if type(bindings) is not tuple or any(
        not isinstance(item, _binding.CodingLegacyLocalBindingEvidenceV1)
        for item in bindings
    ):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_024"])
    if desired is not None and not isinstance(
        desired, _binding.CodingLegacyDesiredEvidenceV1
    ):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_025"])
    if not isinstance(scope_id, str) or not scope_id.startswith("workspace:"):
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_026"])
    by_plugin: dict[str, _binding.CodingLegacyLocalBindingEvidenceV1] = {}
    source_ids: set[str] = set()
    lock_digests = {item.lockfile_digest for item in bindings}
    for binding in bindings:
        if (
            binding.plugin_id in by_plugin
            or binding.plugin_id in _binding._BUILTINS
            or binding.source_identity in source_ids
        ):
            raise _binding.CodingLegacyInventoryError(
                _binding._LEGACY_PROGRAM_VALUES["value_028"]
            )
        by_plugin[binding.plugin_id] = binding
        source_ids.add(binding.source_identity)
    if len(lock_digests) > 1:
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_027"]
        )

    active: list[_binding.CodingLegacyLocalInstallationV1] = []
    builtins: list[_binding.CodingLegacyBuiltinIntentV1] = []
    removed: list[str] = []
    selected_ids: set[str] = set()
    states = () if desired is None else desired.snapshot.installations
    for state in states:
        key = state.installation_key
        selection = state.selection
        if (
            key.product_id != _binding._LEGACY_PROGRAM_VALUES["value_029"]
            or key.installation_scope != "workspace"
            or key.scope_id != scope_id
        ):
            raise _binding.CodingLegacyInventoryError(
                _binding._LEGACY_PROGRAM_VALUES["value_030"]
            )
        plugin_id = key.plugin_id
        if selection.desired_state == "absent":
            removed.append(plugin_id)
            continue
        package = selection.package_revision
        if package is None or package.plugin_id != plugin_id:
            raise _binding.CodingLegacyInventoryError(
                _binding._LEGACY_PROGRAM_VALUES["value_031"]
            )
        if plugin_id in _binding._BUILTINS:
            if plugin_id in by_plugin or package.package_source_identity != (
                f"embedded:{plugin_id}"
            ):
                raise _binding.CodingLegacyInventoryError(
                    _binding._LEGACY_PROGRAM_VALUES["value_033"]
                )
            builtins.append(
                _binding.CodingLegacyBuiltinIntentV1(plugin_id, selection.desired_state)
            )
            continue
        matched = by_plugin.get(plugin_id)
        if (
            matched is None
            or package.package_source_identity != matched.source_identity
            or package.package_content_digest != matched.content_digest
            or package.dependency_lock_digest != matched.dependency_lock.digest
        ):
            raise _binding.CodingLegacyInventoryError(
                _binding._LEGACY_PROGRAM_VALUES["value_032"]
            )
        selected_ids.add(plugin_id)
        active.append(
            _binding.CodingLegacyLocalInstallationV1(
                binding=matched,
                desired_state=selection.desired_state,
                plugin_version=package.plugin_version,
            )
        )
    return _binding.CodingLegacyInstallationInventoryV1(
        active_local=tuple(sorted(active, key=lambda item: item.binding.plugin_id)),
        builtin_intent=tuple(sorted(builtins, key=lambda item: item.plugin_id)),
        removed_plugin_ids=tuple(sorted(removed)),
        unselected_source_identities=tuple(
            sorted(
                binding.source_identity
                for plugin_id, binding in by_plugin.items()
                if plugin_id not in selected_ids
            )
        ),
        desired_journal_digest=None if desired is None else desired.journal_digest,
        lockfile_digest=next(iter(lock_digests), None),
    )


def classify_removed_installations(
    bindings: tuple[_binding.CodingLegacyLocalBindingEvidenceV1, ...],
    desired: _binding.CodingLegacyDesiredEvidenceV1,
    *,
    scope_id: str,
) -> tuple[_binding.CodingLegacyRemovedLocalInstallationV1, ...]:
    """Prove each absent old local head was installed from this lock, then removed.

    A final absent row alone cannot prove that a lock head ever belonged to
    the Installation. The decoded journal has already verified the whole
    history; this check binds the lock head to the last install or update in
    the final installation epoch and its eventual removal.
    """

    if not isinstance(desired, _binding.CodingLegacyDesiredEvidenceV1):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_034"])
    inventory = _binding.classify_coding_legacy_installations(
        bindings, desired, scope_id=scope_id
    )
    by_plugin = {binding.plugin_id: binding for binding in bindings}
    removed_bindings = {
        plugin_id: binding
        for plugin_id, binding in by_plugin.items()
        if binding.source_identity in inventory.unselected_source_identities
    }
    if (
        not 0 < len(bindings) <= 16
        or not removed_bindings
        or set(inventory.unselected_source_identities)
        != {binding.source_identity for binding in removed_bindings.values()}
        or not set(removed_bindings) <= set(inventory.removed_plugin_ids)
        or any(
            plugin_id not in removed_bindings
            and plugin_id
            not in {
                _binding._LEGACY_PROGRAM_VALUES["value_038"],
                _binding._LEGACY_PROGRAM_VALUES["value_039"],
                _binding._LEGACY_PROGRAM_VALUES["value_040"],
            }
            for plugin_id in inventory.removed_plugin_ids
        )
        or not desired.transitions
    ):
        raise _binding.CodingLegacyInventoryError(
            _binding._LEGACY_PROGRAM_VALUES["value_035"]
        )
    removed: list[_binding.CodingLegacyRemovedLocalInstallationV1] = []
    for plugin_id, binding in sorted(removed_bindings.items()):
        history = tuple(
            item
            for item in desired.transitions
            if item.mutation.installation_key.plugin_id == plugin_id
        )
        proof = _binding.inspect_removed_installation_epoch(
            history,
            error_type=_binding.CodingLegacyInventoryError,
            label=_binding._LEGACY_PROGRAM_VALUES["value_036"],
            mismatch_message=_binding._LEGACY_PROGRAM_VALUES["value_037"],
        )
        installed = proof.package_revision
        if (
            installed.plugin_id != plugin_id
            or installed.package_source_identity != binding.source_identity
            or installed.package_content_digest != binding.content_digest
            or installed.dependency_lock_digest != binding.dependency_lock.digest
        ):
            raise _binding.CodingLegacyInventoryError(
                _binding._LEGACY_PROGRAM_VALUES["value_037"]
            )
        removed.append(
            _binding.CodingLegacyRemovedLocalInstallationV1(
                binding=binding,
                install_operation_id=proof.install.mutation.operation_id,
                remove_operation_id=proof.removal.mutation.operation_id,
                head_operation_id=proof.head.mutation.operation_id,
                head_transition_kind=proof.head_transition_kind,
            )
        )
    return tuple(removed)
