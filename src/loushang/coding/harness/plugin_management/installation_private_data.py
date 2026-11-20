"""Admission and native directory preparation for Installation private data."""

from __future__ import annotations

from loushang.coding.package import installation_private_data as _binding


def prepare_session_root(
    layout: _binding.CodingPluginLifecycleStateLayout,
    runtime: _binding.PackageProductRuntimeBindingV1,
    *,
    session_id: str,
    product_id: str,
    plugin_id: str,
    label: str,
) -> _binding.Path:
    """Prepare one exact selected Installation's Session directory."""

    if (
        not isinstance(layout, _binding.CodingPluginLifecycleStateLayout)
        or not isinstance(runtime, _binding.PackageProductRuntimeBindingV1)
        or runtime.product_id != product_id
        or (runtime.session_id != session_id)
        or (not isinstance(session_id, str))
        or (not session_id)
    ):
        raise ValueError(f"{label} private-data Product session changed")
    key = _binding.PluginInstallationKeyV1(
        product_id=product_id,
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id=plugin_id,
    )
    selected = runtime.capture_plugin_desired_selection_for(plugin_id)
    if (
        selected.installation_key != key
        or selected.desired_state != "installed_enabled"
    ):
        raise ValueError(f"{label} private-data Installation is not selected")
    selected_root = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=64, max_total_bytes=1024 * 1024
    )
    source = _binding.Path(
        selected_root.snapshot.package_revision.package_source_identity
    )
    epoch = _binding.resolve_coding_package_epoch_layout(layout)
    if (
        selected_root.snapshot.installation_key != key
        or source.parent != epoch.control_root / "product-sources"
    ):
        raise ValueError(f"{label} private-data Product authority changed")
    root = _binding.coding_arch_session_private_data_root(
        layout, key, session_id=session_id
    )
    if _binding.os.name == "nt":
        installation_root = _binding.coding_arch_installation_private_data_root(
            layout, key
        )
        bound_identity = _binding._bind_windows_arch_installation_root(
            layout, key, state_root=epoch.control_root / "product-state"
        )
        _binding.prepare_windows_product_private_directory_chain(
            installation_root,
            *root.relative_to(installation_root).parts,
            inherit_leaf=True,
        )
        if (
            _binding._bind_windows_arch_installation_root(
                layout, key, state_root=epoch.control_root / "product-state"
            )
            != bound_identity
        ):
            raise ValueError(f"{label} private-data Installation root changed")
        runtime.capture_selected_plugin_manifest_for(
            plugin_id, max_files=64, max_total_bytes=1024 * 1024
        )
    else:
        _binding._prepare_private_tree(
            root, private_base=layout.private_data_base, label="data"
        )
    return root


def require_windows_state_root(
    layout: _binding.CodingPluginLifecycleStateLayout,
    key: _binding.PluginInstallationKeyV1,
    state_root: _binding.Path,
    *,
    changed: str,
) -> _binding.Path:
    """Check the Product state location before borrowing the Windows owner."""

    root = _binding.coding_arch_installation_private_data_root(layout, key)
    epoch = _binding.resolve_coding_package_epoch_layout(layout)
    if state_root != epoch.control_root / "product-state":
        raise ValueError(changed)
    return root
