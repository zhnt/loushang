"""Windows Worker opt-in cutover preserves current decisions and old IDs."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Literal

import pytest

from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
)
from loushang.coding.package_product_worker_policy import CodingWorkerOptInV1
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_opt_in_base import (
    CodingWindowsWorkerOptInSemanticBaseV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
)


def _opt_in(revision: int, *, kill: int) -> CodingWorkerOptInV1:
    return CodingWorkerOptInV1(
        plugin_id="reviewworker",
        contribution_id="query-provider",
        owner_id="coding",
        artifact_digest=sha256(b"worker-wheel").hexdigest(),
        native_platform="windows-amd64",
        owner_selection_generation=revision,
        kill_switch_generation=kill,
        require_worker=False,
    )


def _decision(
    revision: int,
    *,
    action: Literal["allow", "revoke"],
    kill: int,
    operation_id: str | None = None,
) -> CodingWorkerOptInDecisionV1:
    return CodingWorkerOptInDecisionV1.create(
        journal_revision=revision,
        scope_id="scope-a",
        plugin_id="reviewworker",
        operation_id=operation_id or f"operation-{revision}",
        generation=revision,
        kill_switch_generation=kill,
        action=action,
        opt_in=_opt_in(revision, kill=kill) if action == "allow" else None,
    )


def _semantic_read() -> CodingWindowsWorkerHistorySemanticReadV1:
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=3,
        files=(
            CodingWindowsWorkerHistorySourceFileV1(
                name="worker-opt-in.jsonl",
                size=1,
                sha256_digest=sha256(b"x").hexdigest(),
            ),
        ),
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=3,
        attempts=(),
        opt_in_decisions=(
            _decision(1, action="allow", kill=0),
            _decision(2, action="revoke", kill=1),
        ),
        receipt_records=(),
        supervisor_records=(),
        activation_state_owner_present=False,
        activation_state_revision=0,
        retained_activation_attempts=(),
        native_job_absence=(),
        gc_reservation_revision=0,
        gc_revision_refs=frozenset(),
        worker_backup_observations=(),
    )
    return CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source, offline_recovery=recovery
    )


def test_windows_opt_in_base_replays_after_exact_cutoff() -> None:
    semantic = _semantic_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    base = CodingWindowsWorkerOptInSemanticBaseV1.from_semantic_read(prepared, semantic)
    assert base.cutoff_revision == 2
    assert base.latest_decisions == (semantic.offline_recovery.opt_in_decisions[-1],)
    assert base.retired_operation_ids == ("operation-1", "operation-2")
    assert CodingWindowsWorkerOptInSemanticBaseV1.from_bytes(base.to_bytes()) == base
    replay = base.replay((_decision(3, action="allow", kill=1),))
    assert replay.last_revision == 3
    assert replay.latest_decisions[0].action == "allow"
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((_decision(3, action="allow", kill=1, operation_id="operation-1"),))


def test_windows_opt_in_base_refuses_changed_preparation() -> None:
    semantic = _semantic_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    changed = replace(
        semantic,
        offline_recovery=replace(semantic.offline_recovery, gc_reservation_revision=1),
    )
    with pytest.raises(ValueError, match="semantic read changed"):
        CodingWindowsWorkerOptInSemanticBaseV1.from_semantic_read(prepared, changed)


def test_windows_opt_in_base_requires_source_for_retained_decisions() -> None:
    semantic = _semantic_read()
    missing_source = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=3,
            files=(),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(missing_source)
    with pytest.raises(ValueError, match="source is absent"):
        CodingWindowsWorkerOptInSemanticBaseV1.from_semantic_read(
            prepared, missing_source
        )
