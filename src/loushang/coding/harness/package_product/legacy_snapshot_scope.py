"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from contextlib import contextmanager

from loushang.coding.package import pre_b_snapshot as _binding


@contextmanager
def pre_snapshot_scope(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    settings_manager: _binding.SettingsManager,
    *,
    projection_parent: _binding.Path,
) -> _binding.Iterator[_binding.CodingPreBSnapshotPreparation]:
    """Pin real settings and map every deployed Coding pre-B state member."""

    if not isinstance(lifecycle, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._LEGACY_ADOPTION_VALUES["value_001"])
    if not isinstance(settings_manager, _binding.SettingsManager):
        raise TypeError(_binding._LEGACY_ADOPTION_VALUES["value_002"])
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if not isinstance(global_path, _binding.Path) or not isinstance(
        project_path, _binding.Path
    ):
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_003"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    with _binding.hold_coding_pre_b_source_configuration(
        settings_manager,
        global_settings_path=global_path,
        project_settings_path=project_path,
        projection_parent=projection_parent,
    ) as source_root:
        with _binding.hold_legacy_product_projection_root(
            projection_parent,
            prefix=_binding._LEGACY_ADOPTION_VALUES["value_004"],
            projection_name=_binding._PROJECTION_NAME,
            projection_label=_binding._LEGACY_ADOPTION_VALUES["value_005"],
        ) as pointer_root:
            package = _binding.resolve_coding_package_pre_b_store_members(lifecycle)
            state = _binding.resolve_coding_lifecycle_pre_b_members(lifecycle)
            source_projection = _binding.json.loads(
                _binding.read_legacy_product_projection(
                    source_root, name=_binding._PROJECTION_NAME
                )
            )
            legacy_classification = _binding.classify_coding_legacy_workspace(
                source_projection,
                lifecycle=state,
                package=package,
            )
            domain_roots = {
                "store_bytes": package.source_root,
                "binding_history": package.source_root,
                "lock_history": package.source_root,
                "desired_state": state.source_root,
                "enablement_state": state.source_root,
                "instance_state": state.source_root,
                "fence_record": epoch.control_root,
                "source_configuration": source_root,
                "legacy_root_pointer": pointer_root,
            }
            domain_members: dict[str, tuple[str, ...] | None] = {
                domain: None for domain in domain_roots
            }
            domain_members.update(package.domain_members())
            domain_members.update(state.domain_members())
            shared_members = (
                (
                    _binding.PackageProductPreBSnapshotSharedMemberV1(
                        source_root=package.source_root,
                        member_name=_binding._LEGACY_ADOPTION_VALUES["value_006"],
                        domains=("binding_history", "lock_history"),
                    ),
                )
                if package.binding_history
                else ()
            )
            owner_type = (
                _binding.PackageProductWindowsPreBSnapshotOwner
                if _binding.os.name == "nt"
                else _binding.PackageProductPreBSnapshotOwner
            )
            owner = owner_type(
                epoch.snapshot_root,
                store_id=epoch.store_id,
                domain_roots=domain_roots,
                domain_members=domain_members,
                legacy_root_pointer_name=epoch.legacy_root_name,
                shared_members=shared_members,
            )
            yield _binding.CodingPreBSnapshotPreparation(
                owner=owner,
                source_configuration_root=source_root,
                legacy_classification=legacy_classification,
            )


def cutover_store(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    settings_manager: _binding.SettingsManager,
    *,
    projection_parent: _binding.Path,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
    snapshot_admission: _binding.CodingCutoverSnapshotAdmission | None,
) -> _binding.CodingPackagePreBCutover:
    """Hold real Coding Source state until Product finishes the first B fence."""

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    with _binding.hold_coding_pre_b_snapshot_owner(
        lifecycle, settings_manager, projection_parent=projection_parent
    ) as prepared:
        attempt = prepared.owner.cutover_from_legacy(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            legacy_root_name=epoch.legacy_root_name,
            epochs_root_name=epoch.epochs_root_name,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            snapshot_admission=(
                None
                if snapshot_admission is None
                else lambda snapshot: snapshot_admission(prepared, snapshot)
            ),
        )
        return _binding.CodingPackagePreBCutover(
            attempt=attempt,
            snapshots=prepared.owner,
        )
