"""Complete private-data programs using existing storage/history owners.

Temporary Product binding imports preserve original nominal and fault seams;
they are tracked intermediate dependencies, not final Harness neutrality.
"""

from __future__ import annotations

from loushang.coding.package import private_data_deletion_owner as _binding


def plan_for(
    self: _binding.CodingArchPrivateDataDeletionOwner,
    key: _binding.PluginInstallationKeyV1,
) -> _binding.PluginPrivateDataDeletionPlanV1:
    root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    with self._preview._offline():
        pending = self.journal.current_start()
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


def delete_confirmed(
    self: _binding.CodingArchPrivateDataDeletionOwner,
    plan: _binding.PluginPrivateDataDeletionPlanV1,
    confirmation: _binding.PluginPrivateDataDeletionConfirmationV1,
) -> _binding.PluginPrivateDataDeletionReceiptV1:
    if (
        not isinstance(plan, _binding.PluginPrivateDataDeletionPlanV1)
        or not isinstance(
            confirmation, _binding.PluginPrivateDataDeletionConfirmationV1
        )
        or plan.owner_id != _binding._OWNER_ID
        or confirmation.plan_fingerprint != plan.fingerprint
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_01"])
    root = _binding.coding_arch_installation_private_data_root(
        self.layout, plan.installation_key
    )
    with self._preview._offline():
        if not self.confirmations.is_confirmed(plan, confirmation):
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_02"])
        if (
            self.product.desired_state.snapshot()
            .installation(plan.installation_key)
            .selection.desired_state
            != "absent"
        ):
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_03"])
        return self.journal.execute_deletion(
            plan,
            confirmation,
            capture_target=lambda: _binding._capture_target_snapshot(
                root, private_base=self.layout.private_data_base
            ),
            remove_started=lambda started: _binding._delete_started(
                root, started, self.layout.private_data_base, self.journal
            ),
            receipt_id=lambda: _binding._receipt_id(plan, confirmation),
            stale_message=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_04"],
            unfinished_message="Another private-data deletion is unfinished",
        )
