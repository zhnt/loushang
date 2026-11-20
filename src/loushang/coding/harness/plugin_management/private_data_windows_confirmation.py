"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import private_data_windows_confirmation as _binding


def record_confirmation(
    self: _binding.CodingWindowsArchPrivateDataConfirmationOwner,
    plan: _binding.PluginPrivateDataDeletionPlanV1,
    confirmation: _binding.PluginPrivateDataDeletionConfirmationV1,
    *,
    actor_id: str,
    policy_revision: str,
) -> _binding.PluginPrivateDataConfirmationRecordV1:
    """Accept one unchanged preview under the offline Product fence."""

    self._require_plan(plan, confirmation)
    preview = _binding.CodingWindowsArchPrivateDataReadPreview(
        self.layout, self.product
    )
    with preview._offline():
        state = self.product.desired_state.snapshot().installation(
            plan.installation_key
        )
        if state.latest_instance_revision_ref is None:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
        # Avoid nesting the native quiescence gate through plan_for().
        root = _binding.coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        expected_root = _binding.inspect_coding_windows_arch_installation_root(
            self.layout,
            plan.installation_key,
            state_root=self.product.state_root,
        )
        current = (
            _binding.CodingArchPrivateDataTargetSnapshotV1(
                root_path_digest=_binding.sha256(
                    _binding.os.fsencode(str(root))
                ).hexdigest(),
                root_identity=None,
                members=(),
            )
            if expected_root is None
            else _binding._capture_windows_target_snapshot(
                root, expected_root=expected_root
            )
        )
        if (
            current.target_id != plan.target_id
            or _binding.inspect_coding_windows_arch_installation_root(
                self.layout,
                plan.installation_key,
                state_root=self.product.state_root,
            )
            != expected_root
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        record = _binding.PluginPrivateDataConfirmationRecordV1(
            record_revision=1,
            plan=plan,
            confirmation=confirmation,
            actor_id=actor_id,
            policy_revision=policy_revision,
        )
        payload = _binding.canonical_json_bytes(record.to_dict()) + b"\n"
        if len(payload) > _binding._MAX_CONFIRMATION_BYTES:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
        path = self._record_path(confirmation)
        with self.product.epoch_runtime.borrow_product_state_root_descriptor():
            return _binding.accept_windows_private_confirmation(
                path,
                payload,
                record,
                io=_binding._receipt_io,
                maximum_bytes=_binding._MAX_CONFIRMATION_BYTES,
                write_maximum_bytes=_binding._MAX_RECEIPT_BYTES,
                decode=self._decode,
                label=_binding._PRIVATE_DATA_FLOW_VALUES["message_04"],
            )


def is_confirmed(
    self: _binding.CodingWindowsArchPrivateDataConfirmationOwner,
    plan: _binding.PluginPrivateDataDeletionPlanV1,
    confirmation: _binding.PluginPrivateDataDeletionConfirmationV1,
) -> bool:
    """Read one exact private receipt through the current Product root."""

    self._require_plan(plan, confirmation)
    self.product.assert_private_data_read_authority_current()
    with self.product.epoch_runtime.borrow_product_state_root_descriptor():
        raw = _binding.read_windows_private_receipt(
            self._record_path(confirmation),
            maximum_bytes=_binding._MAX_CONFIRMATION_BYTES,
        )
        record = None if raw is None else self._decode(raw)
        result = record is not None and (
            record.plan == plan and record.confirmation == confirmation
        )
    self.product.assert_private_data_read_authority_current()
    return result
