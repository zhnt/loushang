"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_runtime as _binding


def bootstrap_builtin_plugins(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    settings_manager: _binding.SettingsManager,
    *,
    workspace: _binding.Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool,
    require_current_admission: _binding.Callable[[], None] | None,
) -> bool:
    """Install and enable unseen first-party Plugins through the fenced Product.

    Only a disabled selection committed by this exact bootstrap installation
    may finish an interrupted enable. A later operator disable or remove is
    never converted back into a default install.
    """

    _binding.require_fresh_coding_product_inputs(lifecycle, settings_manager)
    owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )
    try:
        changed = False
        for plugin_id in (
            _binding._LIFECYCLE_PROGRAM_VALUES["value_001"],
            _binding._LIFECYCLE_PROGRAM_VALUES["value_002"],
            _binding._LIFECYCLE_PROGRAM_VALUES["value_003"],
        ):
            _binding._require_current_coding_product_admission(
                require_current_admission
            )
            changed = (
                _binding._bootstrap_coding_builtin_plugin(owner, plugin_id) or changed
            )
        return changed
    finally:
        owner.close()


def bootstrap_accepted_disabled_plugins(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    settings_manager: _binding.SettingsManager,
    *,
    workspace: _binding.Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> _binding.CodingLegacyDisabledOnlyAcceptanceV1:
    """Install builtins from an explicitly accepted, fenced Source snapshot."""

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs()
    )
    try:
        receipt = _binding.accept_coding_first_b_disabled_only(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        )
    finally:
        epoch_runtime.close()
    disabled = {item.plugin_id for item in receipt.review.disabled_plugins}
    owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        for plugin_id in (
            _binding._LIFECYCLE_PROGRAM_VALUES["value_001"],
            _binding._LIFECYCLE_PROGRAM_VALUES["value_002"],
            _binding._LIFECYCLE_PROGRAM_VALUES["value_003"],
        ):
            _binding._bootstrap_coding_builtin_plugin(
                owner, plugin_id, enable=plugin_id not in disabled
            )
        return receipt
    finally:
        owner.close()


def initialize_fresh_product(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    settings_manager: _binding.SettingsManager | None,
    windows_candidate: bool,
    require_current_admission: _binding.Callable[[], None] | None,
) -> None:
    """Use the Product's offline fresh cutover before ordinary Session writes."""

    if not (
        (_binding.os.name == "posix" and _binding.sys.platform.startswith("linux"))
        or (_binding.os.name == "nt" and windows_candidate)
    ):
        raise RuntimeError(_binding._LIFECYCLE_PROGRAM_VALUES["value_004"])
    if not workspace.is_dir():
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_005"])
    global_path = _binding.default_global_settings_path()
    project_path = _binding.default_project_settings_path(workspace)
    if settings_manager is not None:
        _binding.require_fresh_coding_product_inputs(
            lifecycle, settings_manager, roots_may_be_absent=True
        )
        global_path = settings_manager.global_settings_path or global_path
        project_path = settings_manager.project_settings_path or project_path
    _binding._require_current_coding_product_admission(require_current_admission)
    cutover_settings = _binding.SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = _binding._fresh_coding_product_namespace_id(epoch.store_id)
    # Import here because the cutover owner uses this module's Product bootstrap.
    from loushang.coding.package.pre_b_snapshot import (
        cutover_and_bootstrap_coding_package_product,
    )

    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        cutover_settings,
        workspace=workspace,
        namespace_id=namespace_id,
        runtime_version=_binding.version(
            _binding._LIFECYCLE_PROGRAM_VALUES["distribution_name"]
        ),
        runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )


def is_fresh_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    runtime: _binding.PackageProductPosixFencedRuntimeOwner
    | _binding.PackageProductWindowsFencedRuntimeOwner,
) -> bool:
    """Read the fenced first-B snapshot before retrying fresh builtin defaults."""

    if not isinstance(
        lifecycle, _binding.CodingPluginLifecycleStateLayout
    ) or not isinstance(
        runtime,
        (
            _binding.PackageProductPosixFencedRuntimeOwner,
            _binding.PackageProductWindowsFencedRuntimeOwner,
        ),
    ):
        raise TypeError(_binding._LIFECYCLE_PROGRAM_VALUES["value_006"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if (
        runtime.registry.store_id != epoch.store_id
        or runtime.control_root != epoch.control_root
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_007"])
    fence = runtime.cutover_result.fence
    if (
        fence is None
        or fence.request.namespace_id
        != _binding._fresh_coding_product_namespace_id(epoch.store_id)
    ):
        return False
    for domain in (
        "binding_history",
        "desired_state",
        "enablement_state",
        "instance_state",
        "lock_history",
        "store_bytes",
    ):
        if _binding.list_coding_first_b_snapshot_domain_members(
            lifecycle, runtime, domain=domain
        ):
            return False
    if _binding.list_coding_first_b_snapshot_domain_members(
        lifecycle, runtime, domain="source_configuration"
    ) != (_binding._LIFECYCLE_PROGRAM_VALUES["value_008"],):
        raise RuntimeError(_binding._LIFECYCLE_PROGRAM_VALUES["value_009"])
    raw = _binding.read_coding_first_b_snapshot_member(
        lifecycle,
        runtime,
        domain="source_configuration",
        member_name=_binding._LIFECYCLE_PROGRAM_VALUES["value_008"],
        maximum_bytes=_binding._LIFECYCLE_SNAPSHOT_MAX_BYTES,
    )
    if raw is None:
        raise RuntimeError(_binding._LIFECYCLE_PROGRAM_VALUES["value_010"])
    source = _binding.json.loads(raw)
    classification = _binding.classify_coding_legacy_source_configuration(source)
    if classification.disabled_plugins or classification.configured_source_keys:
        return False
    scopes = source["scopes"]
    return not any(
        any(patch.values())
        for patch in (
            scopes["global"]["sourcePatch"],
            scopes["project"]["sourcePatch"],
        )
    )


def retry_fresh_bootstrap(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    settings_manager: _binding.SettingsManager | None,
    windows_candidate: bool,
    require_current_admission: _binding.Callable[[], None] | None,
) -> None:
    """Resume only a proven fresh first-B cutover; preserve adopted B state."""

    if not (
        (_binding.os.name == "posix" and _binding.sys.platform.startswith("linux"))
        or (_binding.os.name == "nt" and windows_candidate)
    ):
        return
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    _binding._require_current_coding_product_admission(require_current_admission)
    runtime = (
        _binding.PackageProductWindowsFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs()
        )
        if _binding.os.name == "nt"
        else _binding.PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs(), read_only=True
        )
    )
    try:
        if not _binding.is_coding_fresh_first_b_snapshot(lifecycle, runtime):
            return
    finally:
        runtime.close()
    owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=_binding.version(
            _binding._LIFECYCLE_PROGRAM_VALUES["distribution_name"]
        ),
        runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )
    try:
        if _binding._fresh_coding_builtin_bootstrap_completed(owner):
            return
    finally:
        owner.close()
    global_path = _binding.default_global_settings_path()
    project_path = _binding.default_project_settings_path(workspace)
    if settings_manager is not None:
        global_path = settings_manager.global_settings_path or global_path
        project_path = settings_manager.project_settings_path or project_path
    _binding._require_current_coding_product_admission(require_current_admission)
    _binding.bootstrap_coding_builtin_product_plugins(
        lifecycle,
        _binding.SettingsManager(
            global_settings_path=global_path,
            project_settings_path=project_path,
        ),
        workspace=workspace,
        runtime_version=_binding.version(
            _binding._LIFECYCLE_PROGRAM_VALUES["distribution_name"]
        ),
        runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )
