"""Original read-only/native custody over borrowed existing authorities.

Product factories, nominal types and diagnostics remain explicit temporary
binding dependencies. Resource and transaction instances stay single-owned.
"""

from __future__ import annotations

from contextlib import contextmanager

from loushang.coding.package import private_data_read_owner as _binding

from . import private_data_backup, private_data_restore_confirmation


def assert_current(self: _binding.CodingArchPrivateDataReadOwner) -> None:
    _binding._assert_workspace(self.workspace, self.workspace_identity)
    self.epoch_runtime.assert_current()
    metadata = self.state_root.lstat()
    if (
        not _binding.stat.S_ISDIR(metadata.st_mode)
        or _binding.stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != _binding.os.geteuid()
        or (metadata.st_dev, metadata.st_ino) != self.state_identity
    ):
        raise ValueError(_binding._PRIVATE_DATA_CUSTODY_VALUES["message_01"])


@contextmanager
def offline(self: _binding.CodingArchPrivateDataReadOwner) -> _binding.Iterator[None]:
    """Keep runtime and GC references fixed without creating lock files."""

    self.assert_current()
    registry = self.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id, read_only=True
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError(_binding._PRIVATE_DATA_CUSTODY_VALUES["message_02"])
        self.assert_current()
        with self.gc_gate.read_guard():
            self.assert_current()
            self.desired_state.capture_read_only()
            try:
                yield
            finally:
                self.assert_current()


def open_read_scope(
    cls: type[_binding.CodingArchPrivateDataReadOwner],
    *,
    layout: _binding.CodingPluginLifecycleStateLayout,
    workspace: _binding.Path,
    workspace_identity: tuple[int, int],
) -> _binding.CodingArchPrivateDataReadOwner:
    _binding._assert_workspace(workspace, workspace_identity)
    if layout != _binding.resolve_coding_plugin_lifecycle_state_layout(workspace):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    epoch_layout = _binding.resolve_coding_package_epoch_layout(layout)
    epoch = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch_layout.fenced_runtime_open_kwargs(), read_only=True
    )
    try:
        _binding._assert_workspace(workspace, workspace_identity)
        state_root = epoch.control_root / "product-state"
        metadata = state_root.lstat()
        if (
            not _binding.stat.S_ISDIR(metadata.st_mode)
            or _binding.stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_uid != _binding.os.geteuid()
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        desired_binding = _binding.bind_plugin_desired_state(
            state_root / "gc-reservations.jsonl",
            state_root / "desired-state.jsonl",
            load_policy=_binding._READ_POLICY,
        )
        epoch.assert_current()
        _binding._assert_workspace(workspace, workspace_identity)
        owner = cls(
            layout=layout,
            workspace=workspace,
            workspace_identity=workspace_identity,
            epoch_runtime=epoch,
            state_root=state_root,
            state_identity=(metadata.st_dev, metadata.st_ino),
            gc_gate=desired_binding.gc_reservations,
            desired_state=desired_binding.desired,
        )
        owner.assert_current()
        return owner
    except BaseException:
        epoch.close()
        raise


def verify_backup(
    self: _binding.CodingArchPrivateDataReadOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    _binding.coding_arch_installation_private_data_root(self.layout, key)
    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_QUERY_VALUES["message_01"])
    with self.offline():
        return private_data_backup.verify_retained_archive(
            self.layout.private_data_base,
            _binding._backup_parent(self.layout, key),
            key,
            backup_id,
        )


def deletion_preview(
    self: _binding.CodingArchPrivateDataReadOwner, key: _binding.PluginInstallationKeyV1
) -> _binding.PluginPrivateDataDeletionPlanV1:
    root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    with self.offline():
        pending = _binding.CodingArchPrivateDataDeletionJournal(
            self.state_root
        ).current_start()
        if pending is not None:
            if pending.plan.installation_key != key:
                raise ValueError("Another private-data deletion is unfinished")
            return pending.plan
        target = _binding._capture_target_snapshot(
            root, private_base=self.layout.private_data_base
        )
        return _binding.PluginPrivateDataDeletionPlanV1(
            installation_key=key,
            owner_id=_binding._OWNER_ID,
            target_id=target.target_id,
        )


def verify_restore_confirmation(
    self: _binding.CodingArchPrivateDataReadOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
) -> _binding.CodingArchPrivateDataRestoreConfirmationV1:
    with self.offline():
        completion, target_id = self._current_completed_restore(key, backup_id)
        return private_data_restore_confirmation.require_current_confirmation(
            self.state_root,
            confirmation_id,
            key,
            backup_id,
            completion,
            target_id,
            message=_binding._PRIVATE_DATA_QUERY_VALUES["message_03"],
        )
