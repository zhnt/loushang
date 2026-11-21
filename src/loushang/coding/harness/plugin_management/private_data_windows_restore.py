"""Original read-only/native custody over borrowed existing authorities.

Product factories, nominal types and diagnostics remain explicit temporary
binding dependencies. Resource and transaction instances stay single-owned.
"""

from __future__ import annotations

from loushang.coding.package import private_data_windows_restore_journal as _binding


def validate_publication(self: _binding.CodingWindowsArchRestorePublicationV1) -> None:
    if (
        not isinstance(self.restore_id, str)
        or not _binding.re.fullmatch(
            _binding._PRIVATE_DATA_RECORD_VALUES["value_02"], self.restore_id
        )
        or not isinstance(self.started_digest, str)
        or not _binding.re.fullmatch(r"[0-9a-f]{64}", self.started_digest)
        or not isinstance(self.plan_fingerprint, str)
        or not _binding.re.fullmatch(r"[0-9a-f]{64}", self.plan_fingerprint)
        or type(self.desired_inventory_revision) is not int
        or self.desired_inventory_revision < 0
        or type(self.generation_number) is not int
        or not 2 <= self.generation_number <= 4097
        or type(self.stage_identity) is not tuple
        or len(self.stage_identity) != 5
        or any(type(value) is not int or value < 0 for value in self.stage_identity)
        or type(self.parent_identity) is not tuple
        or len(self.parent_identity) != 2
        or any(type(value) is not int or value < 0 for value in self.parent_identity)
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_01"])


def decode_publication(
    cls: type[_binding.CodingWindowsArchRestorePublicationV1], value: object
) -> _binding.CodingWindowsArchRestorePublicationV1:
    if type(value) is not dict or set(value) != {
        "desiredInventoryRevision",
        "generationNumber",
        "parentIdentity",
        "planFingerprint",
        "restoreId",
        "stageIdentity",
        "startedDigest",
    }:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_03"])
    parent = value["parentIdentity"]
    stage = value["stageIdentity"]
    if type(parent) is not list or type(stage) is not list:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_04"])
    return cls(
        restore_id=value["restoreId"],
        started_digest=value["startedDigest"],
        plan_fingerprint=value["planFingerprint"],
        desired_inventory_revision=value["desiredInventoryRevision"],
        generation_number=value["generationNumber"],
        stage_identity=tuple(stage),
        parent_identity=tuple(parent),
    )


def require_plan_current(
    self: _binding.CodingWindowsArchPrivateDataRestoreTransaction,
    plan: _binding.CodingArchPrivateDataRestorePlanV1,
) -> _binding.CodingArchPrivateDataTargetSnapshotV1:
    desired, transitions = self.product.desired_state.capture()
    state = desired.installation(plan.installation_key)
    if (
        state.latest_instance_revision_ref is None
        or state.selection.desired_state != "absent"
        or desired.inventory_revision < plan.desired_inventory_revision
        or any(
            transition.inventory_revision > plan.desired_inventory_revision
            and transition.mutation.installation_key == plan.installation_key
            for transition in transitions
        )
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_05"])
    deletion = _binding.CodingWindowsArchPrivateDataDeletionTransaction(
        self.product.state_root, self.state_fd
    )
    try:
        events = deletion.events()
    finally:
        deletion._close()
    if events and events[-1].phase != "completed":
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_06"])
    receipt = _binding._latest_deletion_receipt(events, plan)
    if receipt != plan.deletion_receipt_id:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_07"])
    return self._verify_plan_archive(plan)
