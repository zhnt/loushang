"""Windows Package GC must account for every Worker-owned state-root name."""

from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from loushang.coding.package_product_worker_windows_gc_history import (
    _require_c5_gc_history,
    _require_known_windows_worker_state_names,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)


def test_windows_worker_gc_accepts_current_owned_state_names() -> None:
    attempt_id = "ab" * 16
    _require_known_windows_worker_state_names(
        (
            "worker-opt-in.jsonl",
            "worker-opt-in.jsonl.lock",
            "worker-native-release-approvals.jsonl",
            "worker-native-release-approvals.jsonl.lock",
            "worker-native-backend-release-v1.whl",
            "worker-activation-receipts.jsonl",
            "worker-activation-receipts.jsonl.lock",
            "worker-activation-state.jsonl",
            "worker-activation-state.jsonl.lock",
            "worker-activation-state.h00000001.json",
            "worker-supervisor.jsonl",
            "worker-supervisor.jsonl.lock",
            f"worker-launch-intent-{attempt_id}.json",
            f"worker-native-provisioning-{attempt_id}.jsonl",
            f"worker-native-provisioning-{attempt_id}.jsonl.lock",
            f"worker-stage-retired-{attempt_id}.json",
            "committed-sets.jsonl",
        )
    )


@pytest.mark.parametrize(
    "name",
    (
        "worker-future-reference.json",
        "worker-native-release-v1",
        ".worker-future-reference.json.stage",
        "worker-opt-in.jsonl.stage",
        "worker-native-provisioning-" + "ab" * 16 + ".jsonl.stage",
        "worker-activation-state.h00000001.json.stage",
        "worker-activation-state.h0000001.json",
        "worker-payload-" + "ab" * 16,
    ),
)
def test_windows_worker_gc_rejects_unknown_or_staged_owner(name: str) -> None:
    with pytest.raises(ValueError, match="state owner is unrecognized"):
        _require_known_windows_worker_state_names((name,))


def test_windows_worker_gc_requires_settled_c5_to_match_launched_attempt_and_receipt() -> (
    None
):
    retained = CodingProductWorkerRetainedAttemptV1(
        attempt_id="a" * 32,
        receipt_fingerprint="r",
        policy_fingerprint="p",
        owner_generation=1,
        host_identity="host",
        boot_identity="boot",
        phase="settled",
        last_seen_revision=3,
        current=False,
    )
    launched = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=retained.attempt_id,
        payload_directory_identity=None,
        native_phase=None,
        native_revision=None,
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
        native_job_name="job",
        launch_request_fingerprint="request",
        launch_receipt_fingerprint="r",
    )
    state: dict[str, object] = {"attempts": {}, "publications": {}}
    jobs = {retained.attempt_id: True}
    _require_c5_gc_history(state, (retained,), (launched,), {"r": "p"}, jobs)
    retired_before_launch = replace(
        launched,
        attempt_id="b" * 32,
        native_job_name=None,
        launch_request_fingerprint=None,
        launch_receipt_fingerprint=None,
    )
    _require_c5_gc_history(
        state, (retained,), (launched, retired_before_launch), {"r": "p"}, jobs
    )
    with pytest.raises(ValueError, match="C5 owner is incomplete"):
        _require_c5_gc_history(None, (retained,), (launched,), {"r": "p"}, jobs)
    with pytest.raises(ValueError, match="C5 activation remains active"):
        _require_c5_gc_history(
            {"attempts": {}, "publications": {"p": {}}},
            (retained,),
            (launched,),
            {"r": "p"},
            jobs,
        )
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(state, (), (launched,), {"r": "p"}, jobs)
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(state, (retained,), (launched,), {"r": "changed"}, jobs)
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(
            state, (replace(retained, phase="retired"),), (launched,), {"r": "p"}, jobs
        )
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(
            state,
            (retained,),
            (replace(launched, launch_receipt_fingerprint="changed"),),
            {"r": "p"},
            jobs,
        )
    for native_observation in (False, None):
        with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
            _require_c5_gc_history(
                state,
                (retained,),
                (launched,),
                {"r": "p"},
                {retained.attempt_id: native_observation},
            )
