"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import management_binding as _binding


def open_management(
    self: _binding._ProductCliOwner, *, read_only: bool
) -> tuple[
    _binding.PackageProductPosixFencedRuntimeOwner,
    _binding.PluginManagementApplicationPorts,
]:
    from loushang.coding.package.private_data_backup import (
        CodingArchPrivateDataBackupReadSource,
    )

    self.assert_workspace_current()
    epoch = _binding.resolve_coding_package_epoch_layout(self.layout)
    runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs(), read_only=read_only
    )
    try:
        self.assert_workspace_current()
        state_root = runtime.control_root / "product-state"
        if read_only:
            try:
                state_metadata = state_root.lstat()
            except FileNotFoundError as exc:
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_002"]) from exc
            if (
                not _binding.stat.S_ISDIR(state_metadata.st_mode)
                or _binding.stat.S_IMODE(state_metadata.st_mode) & 0o077
                or state_metadata.st_uid != _binding.os.geteuid()
            ):
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
            load_policy = _binding.JournalLoadPolicy(
                partial_tail="raise", create_lock=False
            )
            desired = _binding.bind_plugin_desired_state(
                state_root / _binding._RUNTIME_PROGRAM_VALUES["value_003"],
                state_root / _binding._RUNTIME_PROGRAM_VALUES["value_004"],
                load_policy=load_policy,
            ).desired
            management = _binding.PluginManagementService(
                desired_state=desired,
                operation_journal_path=state_root
                / _binding._RUNTIME_PROGRAM_VALUES["value_005"],
                load_policy=load_policy,
            )
        else:
            runtime.prepare_product_state_root()
            state = _binding.open_coding_package_product_state(
                self.layout, runtime, before_recovery=self.assert_workspace_current
            )
            desired = state.desired_state
            management = state.management
        retirement_intents = _binding.PluginRetirementIntentLedger(
            management.retirement_intent_journal_path,
            load_policy=load_policy if read_only else None,
        )
        retirement = _binding.PluginRetirementSetLedger(
            management.retirement_set_journal_path,
            retirement_intents=retirement_intents,
            load_policy=load_policy if read_only else None,
        )
        ports = _binding.PluginManagementApplicationPorts(
            commands=_binding.PluginManagementCommandApplication(management),
            queries=_binding.PluginManagementReadModelProjector(
                desired_state=desired,
                operations=management,
                retirement=retirement,
                source=_binding._product_sources(
                    self.layout, runtime, desired, read_only=read_only
                ),
                backup_retention=CodingArchPrivateDataBackupReadSource(
                    self.layout, runtime
                ),
            ),
        )
        runtime.assert_current()
        self.assert_workspace_current()
        return runtime, ports
    except BaseException:
        runtime.close()
        raise


def source_snapshot(
    self: _binding._ProductSources,
) -> _binding.PluginManagementSourceSnapshotV1:
    all_bindings = self.catalog.records()
    selected = {
        item.installation_key.plugin_id: item.selection.package_revision
        for item in self.desired_state.snapshot().installations
        if item.installation_key.product_id
        == _binding._RUNTIME_PROGRAM_VALUES["value_007"]
        and item.installation_key.scope_id == self.catalog.scope_id
    }
    latest: dict[str, _binding.CodingExternalDataWheelBindingV1] = {}
    for item in all_bindings:
        prior = latest.get(item.plugin_id)
        if prior is None or item.record_revision > prior.record_revision:
            latest[item.plugin_id] = item
    for item in all_bindings:
        revision = selected.get(item.plugin_id)
        if (
            revision is not None
            and revision.package_source_identity
            == str(self.catalog.source_root / item.wheel_filename)
            and revision.package_content_digest == item.artifact_digest
        ):
            latest[item.plugin_id] = item
    records = []
    for item in latest.values():
        availability: Literal["available", "unavailable"]
        try:
            self.catalog.verify_record(item)
        except (_binding.CodingExternalDataWheelError, OSError):
            availability = "unavailable"
        else:
            availability = "available"
        records.append(
            _binding.PluginManagementSourceRecordV1(
                installation_key=_binding.PluginInstallationKeyV1(
                    product_id=_binding._RUNTIME_PROGRAM_VALUES["value_007"],
                    installation_scope="workspace",
                    scope_id=item.scope_id,
                    plugin_id=item.plugin_id,
                ),
                source_identity=f"local:{self.catalog.source_root / item.wheel_filename}",
                source_kind="local",
                availability=availability,
                source_location=item.original_source,
                plugin_version=item.version,
                manifest_enabled_default=None,
            )
        )
    ordered = tuple(sorted(records, key=lambda value: value.installation_key))
    owner_revision = _binding.sha256(
        _binding.canonical_json_bytes(
            {
                "bindings": [item.to_dict() for item in all_bindings],
                "selected": [item.to_dict() for item in ordered],
            }
        )
    ).hexdigest()
    return _binding.PluginManagementSourceSnapshotV1(
        owner_revision=f"{_binding._RUNTIME_PROGRAM_VALUES['value_006']}{owner_revision}",
        records=ordered,
    )


def read_handoff_desired_commit(
    layout: _binding.CodingPluginLifecycleStateLayout,
    handoff: _binding.PackageRetentionHandoffReceiptV1,
) -> (
    tuple[int, dict[str, object], Literal["owner_receipt", "verified_transition"]]
    | None
):
    """Prove an exact Desired commit even before handoff settlement is journaled."""

    desired_request = handoff.request.desired_request
    if handoff.desired_receipt is not None:
        return (
            handoff.desired_receipt.inventory_revision,
            desired_request.root_ref.to_dict(),
            "owner_receipt",
        )
    if handoff.state != "dependency_pinned":
        return None
    transition = _binding.read_coding_fenced_desired_transition(
        layout, desired_request.command_id
    )
    if transition is None:
        return None
    key = transition.mutation.installation_key
    selected = transition.committed_state.selection.package_revision
    if (
        transition.mutation.expected_inventory_revision
        != desired_request.expected_inventory_revision
        or transition.inventory_revision
        != desired_request.expected_inventory_revision + 1
        or (key.product_id, key.scope_id, key.plugin_id)
        != (
            desired_request.product_id,
            desired_request.scope_id,
            desired_request.plugin_id,
        )
        or selected is None
        or selected.plugin_version != desired_request.root_ref.version
        or selected.package_content_digest != desired_request.root_ref.artifact_digest
    ):
        return None
    return (
        transition.inventory_revision,
        desired_request.root_ref.to_dict(),
        "verified_transition",
    )


def repair_desired_operation(
    layout: _binding.CodingPluginLifecycleStateLayout,
    operation_id: str,
    *,
    workspace: _binding.Path,
    correlation_id: str,
    workspace_guard: _binding.Callable[[], None] | None,
) -> _binding.PluginDesiredRepairResultV1:
    """Resume only a pending Desired State command issued by this CLI owner."""

    if workspace_guard is not None:
        workspace_guard()
    if not _binding.coding_fenced_product_exists(layout):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_008"])
    identity = workspace.lstat()
    if (
        not _binding.stat.S_ISDIR(identity.st_mode)
        or workspace.resolve(strict=True) != workspace
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_009"])

    def assert_workspace_current() -> None:
        if workspace_guard is not None:
            workspace_guard()
        try:
            current = workspace.lstat()
            if (current.st_dev, current.st_ino) != (
                identity.st_dev,
                identity.st_ino,
            ) or workspace.resolve(strict=True) != workspace:
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_009"])
        except OSError as error:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_009"]) from error
        if workspace_guard is not None:
            workspace_guard()

    return _binding.resume_plugin_desired_operation(
        _binding.build_coding_fenced_product_management_cli_ports(
            layout, workspace_guard=assert_workspace_current
        ),
        _binding.PluginDesiredCommandAuthorityV1(
            product_id=_binding._RUNTIME_PROGRAM_VALUES["value_007"],
            installation_scope="workspace",
            scope_id=layout.scope_id,
            actor_id=_binding.CODING_CLI_MANAGEMENT_ACTOR_ID,
            policy_revision=_binding.CODING_CLI_MANAGEMENT_POLICY_REVISION,
        ),
        operation_id=operation_id,
        correlation_id=correlation_id,
    )
