"""Windows Package GC must account for every Worker-owned state-root name."""

from __future__ import annotations

import pytest

from loushang.coding.package_product_worker_windows_gc_history import (
    _require_known_windows_worker_state_names,
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
        "worker-payload-" + "ab" * 16,
    ),
)
def test_windows_worker_gc_rejects_unknown_or_staged_owner(name: str) -> None:
    with pytest.raises(ValueError, match="state owner is unrecognized"):
        _require_known_windows_worker_state_names((name,))
