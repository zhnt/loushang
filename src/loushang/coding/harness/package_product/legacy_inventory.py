"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from functools import partial

from loushang.coding.package import legacy_installation_inventory as _binding
from loushang.coding.package.legacy_instance_evidence import _read_management_history
from loushang.harness.package_product._legacy_management_evidence import (
    require_empty_lock_markers,
    require_service_lock_markers,
)


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
            require_empty_lock_markers(
                read_member,
                (("lock_history", package_lock),),
                error_type=_binding.CodingLegacyInventoryError,
                message=_binding._LEGACY_PROGRAM_VALUES["value_009"],
            )
        if has_operations:
            require_service_lock_markers(
                read_member,
                instance_members,
                error_type=_binding.CodingLegacyInventoryError,
                message=_binding._LEGACY_PROGRAM_VALUES["value_020"],
            )
            _read_management_history(
                lifecycle,
                instance_members,
                desired,
                read_member,
                error_type=_binding.CodingLegacyInventoryError,
                missing_messages=(
                    _binding._LEGACY_PROGRAM_VALUES["value_017"],
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
