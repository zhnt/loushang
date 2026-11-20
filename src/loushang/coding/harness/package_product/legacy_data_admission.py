"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_skill_cutover_admission as _binding

from . import legacy_management_evidence as _management_evidence
from .legacy_reacquisition import reacquire_bound_wheel
from .legacy_source_matching import index_configured_sources


def admit_local_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    prepared: _binding.CodingPreBSnapshotPreparation,
    snapshot: _binding.PackageEpochCutoverSnapshotReceiptV1,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    """Verify the whole old data Resource set while cutover holds quiescence.

    The function name predates multi-Skill admission; ``plugin_id`` must name
    one member of the verified set before its review command continues.
    """

    if not isinstance(lifecycle, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_001"])
    if not isinstance(prepared, _binding.CodingPreBSnapshotPreparation):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_002"])
    if not isinstance(snapshot, _binding.PackageEpochCutoverSnapshotReceiptV1):
        raise TypeError(_binding._LEGACY_PROGRAM_VALUES["value_003"])
    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_004"])
    if resource_kind not in {
        _binding._LEGACY_PROGRAM_VALUES["value_005"],
        _binding._LEGACY_PROGRAM_VALUES["value_006"],
        _binding._LEGACY_PROGRAM_VALUES["value_007"],
    }:
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_008"])
    owner = prepared.owner
    receipt_id = snapshot.receipt_id
    try:
        evidence = owner.snapshot(receipt_id)
        if (
            evidence is None
            or evidence.snapshot != snapshot
            or prepared.legacy_classification.kind != "legacy_state"
            or owner.list_domain_members(receipt_id, domain="binding_history")
            != (_binding._LEGACY_PROGRAM_VALUES["value_013"],)
            or owner.list_domain_members(receipt_id, domain="source_configuration")
            != (_binding._LEGACY_PROGRAM_VALUES["value_012"],)
            or owner.list_domain_members(receipt_id, domain="enablement_state") != ()
        ):
            raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_009"])
        lock_members = (
            owner.list_domain_members(receipt_id, domain="lock_history") or ()
        )
        instance_members = (
            owner.list_domain_members(receipt_id, domain="instance_state") or ()
        )
        has_operations = _binding.classify_coding_legacy_management_members(
            desired_members=owner.list_domain_members(
                receipt_id, domain="desired_state"
            )
            or (),
            instance_members=instance_members,
            lock_members=lock_members,
            allow_retirement=True,
            allow_retired_runtime=True,
        )
        if (
            _binding._LEGACY_PROGRAM_VALUES["value_010"] in lock_members
            and owner.read_regular_member(
                receipt_id,
                domain="lock_history",
                member_name=_binding._LEGACY_PROGRAM_VALUES["value_010"],
                maximum_bytes=8,
            )
            != b"\0"
        ):
            raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_011"])
        source_raw = owner.read_regular_member(
            receipt_id,
            domain="source_configuration",
            member_name=_binding._LEGACY_PROGRAM_VALUES["value_012"],
        )
        lock_raw = owner.read_regular_member(
            receipt_id,
            domain="binding_history",
            member_name=_binding._LEGACY_PROGRAM_VALUES["value_013"],
        )
        desired_raw = owner.read_regular_member(
            receipt_id,
            domain="desired_state",
            member_name=_binding._LEGACY_PROGRAM_VALUES["value_014"],
        )
        if source_raw is None or lock_raw is None or desired_raw is None:
            raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_015"])
        source = _binding.json.loads(source_raw)
        bindings = _binding.parse_coding_legacy_local_binding_heads(lock_raw)
        desired = _binding.parse_coding_legacy_desired_evidence(
            desired_raw, lifecycle=lifecycle
        )
        if has_operations:
            _management_evidence.verify_settled_history(
                lifecycle=lifecycle,
                instance_members=instance_members,
                desired=desired,
                read_member=lambda **fields: owner.read_regular_member(
                    receipt_id, **fields
                ),
                receiver=_binding,
                error_type=ValueError,
                messages=(
                    _binding._LEGACY_PROGRAM_VALUES["value_025"],
                    _binding._LEGACY_PROGRAM_VALUES["value_031"],
                    _binding._LEGACY_PROGRAM_VALUES["value_033"],
                    _binding._LEGACY_PROGRAM_VALUES["value_034"],
                ),
            )
        inventory = _binding.classify_coding_legacy_installations(
            bindings, desired, scope_id=lifecycle.scope_id
        )
        removed_local = (
            _binding.classify_coding_legacy_removed_local_installations(
                bindings, desired, scope_id=lifecycle.scope_id
            )
            if inventory.unselected_source_identities
            else ()
        )
        removed_local_ids = {item.binding.plugin_id for item in removed_local}
        if (
            not 0 < len(inventory.active_local) <= _binding._MAX_LOCAL_DATA_PLUGINS
            or plugin_id
            not in {item.binding.plugin_id for item in inventory.active_local}
            or any(
                item not in _binding._REMOVABLE_BUILTIN_PLUGIN_IDS | removed_local_ids
                for item in inventory.removed_plugin_ids
            )
        ):
            raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_018"])
        canonical_names: set[tuple[str, str]] = set()
        source_identities = tuple(
            item.binding.source_identity for item in inventory.active_local
        )
        for index, installation in enumerate(inventory.active_local):
            binding = installation.binding
            if not binding.source_identity.startswith("local:/"):
                raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_026"])
            if index == 0:
                # Every Source is checked together before reading any live bytes.
                index_configured_sources(source, source_identities)
            wheel = reacquire_bound_wheel(
                lifecycle, installation, staging_prefix="loushang-legacy-pre-fence-"
            )
            inspected = _binding.inspect_coding_legacy_local_data_wheel(wheel)
            if (
                binding.plugin_id == plugin_id
                and inspected.resource_kind != resource_kind
            ):
                raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_027"])
            identity = (inspected.resource_kind, inspected.canonical_name)
            if identity in canonical_names:
                raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_028"])
            canonical_names.add(identity)
    except _binding.PackagePosixEpochCutoverError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        _binding.zipfile.BadZipFile,
    ) as exc:
        raise _binding.PackagePosixEpochCutoverError(
            _binding._LEGACY_PROGRAM_VALUES["value_019"],
            code=(
                _binding._LEGACY_PROGRAM_VALUES["value_035"]
                if resource_kind == _binding._LEGACY_PROGRAM_VALUES["value_005"]
                else (
                    _binding._LEGACY_PROGRAM_VALUES["value_036"]
                    if resource_kind == _binding._LEGACY_PROGRAM_VALUES["value_006"]
                    else _binding._LEGACY_PROGRAM_VALUES["value_037"]
                )
            ),
        ) from exc


def require_fenced_local_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> None:
    """Check frozen old inputs without depending on the original live Source."""

    checks: tuple[tuple[_binding.CodingLegacyInventoryDomain, tuple[str, ...]], ...] = (
        ("binding_history", (_binding._LEGACY_PROGRAM_VALUES["value_013"],)),
        ("source_configuration", (_binding._LEGACY_PROGRAM_VALUES["value_012"],)),
        ("enablement_state", ()),
    )
    for domain, expected in checks:
        if (
            _binding.list_coding_first_b_snapshot_domain_members(
                lifecycle, epoch_runtime, domain=domain
            )
            != expected
        ):
            raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_040"])
    _binding.classify_coding_legacy_management_members(
        desired_members=_binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="desired_state"
        ),
        instance_members=_binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="instance_state"
        ),
        lock_members=_binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="lock_history"
        ),
        allow_retirement=True,
        allow_retired_runtime=True,
    )
    source_raw = _binding.read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name=_binding._LEGACY_PROGRAM_VALUES["value_012"],
        maximum_bytes=2 * 1024 * 1024,
    )
    if source_raw is None:
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_038"])
    source = _binding.json.loads(source_raw)
    inventory = _binding.read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    ).inventory
    removed_local_ids: set[str] = set()
    if inventory.unselected_source_identities:
        desired = _binding.read_coding_legacy_desired_evidence(lifecycle, epoch_runtime)
        if desired is None:
            raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_041"])
        removed_local_ids = {
            item.binding.plugin_id
            for item in _binding.classify_coding_legacy_removed_local_installations(
                _binding.read_coding_legacy_local_binding_heads(
                    lifecycle, epoch_runtime
                ),
                desired,
                scope_id=lifecycle.scope_id,
            )
        }
    if (
        not 0 < len(inventory.active_local) <= _binding._MAX_LOCAL_DATA_PLUGINS
        or plugin_id not in {item.binding.plugin_id for item in inventory.active_local}
        or any(
            item not in _binding._REMOVABLE_BUILTIN_PLUGIN_IDS | removed_local_ids
            for item in inventory.removed_plugin_ids
        )
    ):
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_039"])
    source_identities = tuple(
        item.binding.source_identity for item in inventory.active_local
    )
    index_configured_sources(source, source_identities)
    epoch_runtime.assert_current()


def require_data_kind(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    """Reacquire exact live bytes and enforce the operator's selected type."""

    if resource_kind not in {
        _binding._LEGACY_CHAIN_VALUES["value_001"],
        _binding._LEGACY_CHAIN_VALUES["value_002"],
        _binding._LEGACY_CHAIN_VALUES["value_003"],
    }:
        raise ValueError(_binding._LEGACY_CHAIN_VALUES["value_004"])

    _binding.require_coding_fenced_single_legacy_skill_snapshot(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    reacquired = _binding.reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    inspected = _binding.inspect_coding_legacy_local_data_wheel(reacquired.wheel)
    if inspected.resource_kind != resource_kind:
        raise ValueError(_binding._LEGACY_CHAIN_VALUES["value_005"])
    epoch_runtime.assert_current()
