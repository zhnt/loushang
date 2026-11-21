"""Original read-only/native custody over borrowed existing authorities.

Product factories, nominal types and diagnostics remain explicit temporary
binding dependencies. Resource and transaction instances stay single-owned.
"""

from __future__ import annotations

from loushang.coding.package import private_data_windows_deletion_journal as _binding


def capture_current_target(
    owner: _binding.CodingWindowsArchPrivateDataConfirmationOwner,
    key: _binding.PluginInstallationKeyV1,
    *,
    allow_pending: bool = False,
) -> _binding.CodingArchPrivateDataTargetSnapshotV1:
    root = _binding.coding_arch_installation_private_data_root(owner.layout, key)
    if allow_pending:
        expected_root = _binding._windows_arch_current_root_generation(
            key,
            root,
            owner.product.state_root,
            _binding.inspect_windows_product_private_directory_identity(
                owner.layout.package_root
            ),
            allow_pending=True,
        ).identity
    else:
        expected_root = _binding.inspect_coding_windows_arch_installation_root(
            owner.layout, key, state_root=owner.product.state_root
        )
    if expected_root is None:
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        if (
            allow_pending
            and _binding._windows_arch_current_root_generation(
                key,
                root,
                owner.product.state_root,
                _binding.inspect_windows_product_private_directory_identity(
                    owner.layout.package_root
                ),
                allow_pending=True,
            ).identity
            is not None
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        return _binding.CodingArchPrivateDataTargetSnapshotV1(
            root_path_digest=_binding.sha256(
                _binding.os.fsencode(str(root))
            ).hexdigest(),
            root_identity=None,
            members=(),
        )
    target = _binding._capture_windows_target_snapshot(
        root, expected_root=expected_root
    )
    current_root = (
        _binding._windows_arch_current_root_generation(
            key,
            root,
            owner.product.state_root,
            _binding.inspect_windows_product_private_directory_identity(
                owner.layout.package_root
            ),
            allow_pending=True,
        ).identity
        if allow_pending
        else _binding.inspect_coding_windows_arch_installation_root(
            owner.layout, key, state_root=owner.product.state_root
        )
    )
    if current_root != expected_root:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    return target


def require_staged_start_target_unchanged(
    owner: _binding.CodingWindowsArchPrivateDataConfirmationOwner,
    key: _binding.PluginInstallationKeyV1,
    target: _binding.CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    """Recapture a staged start without reading its own unpublished journal."""

    root = _binding.coding_arch_installation_private_data_root(owner.layout, key)
    if (
        target.root_path_digest
        != _binding.sha256(_binding.os.fsencode(str(root))).hexdigest()
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
    if target.root_identity is None:
        try:
            root.lstat()
        except FileNotFoundError:
            return
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
    if (
        _binding._capture_windows_target_snapshot(
            root, expected_root=target.root_identity[:2]
        )
        != target
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])


def require_windows_tombstone(
    owner: _binding.CodingWindowsArchPrivateDataConfirmationOwner,
    started: _binding.CodingArchPrivateDataDeletionEventV1,
    *,
    present: bool,
) -> None:
    target_identity = started.target.root_identity
    if target_identity is None:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_04"])
    root = _binding.coding_arch_installation_private_data_root(
        owner.layout, started.plan.installation_key
    )
    parent_identity = _binding.inspect_windows_product_private_directory_identity(
        root.parent
    )
    generation = _binding._windows_arch_current_root_generation(
        started.plan.installation_key,
        root,
        owner.product.state_root,
        _binding.inspect_windows_product_private_directory_identity(
            owner.layout.package_root
        ),
        allow_pending=True,
    )
    if generation.receipt is None or generation.identity != target_identity[:2]:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_05"])
    _binding._native_io.require_tombstone_view(
        root,
        expected_parent=parent_identity,
        root_identity=target_identity,
        original=started.target,
        present=present,
        make_tombstone_name=lambda: _binding._tombstone_name(started),
        capture=lambda path: _binding._capture_windows_target_snapshot(
            path, expected_root=target_identity[:2]
        ),
    )
