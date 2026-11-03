"""Windows Worker receipts need the exact historical Desired selection."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_windows_desired_references import (
    CodingWindowsWorkerDesiredReferenceReviewV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    _coding_windows_worker_desired_history_digest,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from tests.coding.test_package_product_worker_windows_receipt_base import (
    _semantic_read,
)


def _desired_capture(
    tmp_path: Path, *, artifact_digest: str, remove_selection: bool = False
):
    ledger = PluginDesiredStateLedger(tmp_path / "desired.jsonl")
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="scope-a",
        plugin_id="reviewworker",
    )
    ledger.commit(
        PluginDesiredStateMutationV1(
            operation_id="operator:install-reviewworker",
            idempotency_key="operator:install-reviewworker",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="installed_disabled",
            package_revision=PluginPackageRevisionRefV1(
                plugin_id="reviewworker",
                plugin_version="1",
                package_content_digest=artifact_digest,
                dependency_lock_digest=sha256(b"lock").hexdigest(),
                package_source_identity="/private/source/reviewworker.whl",
            ),
            actor_id="operator",
            policy_revision="policy-a",
        )
    )
    if remove_selection:
        ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id="operator:remove-reviewworker",
                idempotency_key="operator:remove-reviewworker",
                expected_inventory_revision=1,
                installation_key=key,
                desired_state="absent",
                package_revision=None,
                actor_id="operator",
                policy_revision="policy-a",
            )
        )
    return ledger.capture_read_only()


def test_windows_desired_reference_review_joins_real_ledger_and_receipt(
    tmp_path: Path,
) -> None:
    semantic = _semantic_read()
    receipt = semantic.offline_recovery.receipt_records[0].receipt
    snapshot, transitions = _desired_capture(
        tmp_path, artifact_digest=receipt.policy.plugin_revision_digest
    )
    semantic = replace(
        semantic,
        desired_inventory_revision=snapshot.inventory_revision,
        desired_history_digest=_coding_windows_worker_desired_history_digest(
            snapshot, transitions
        ),
        desired_snapshot=snapshot,
        desired_transitions=transitions,
    )
    review = CodingWindowsWorkerDesiredReferenceReviewV1.from_semantic_read(
        CodingWindowsWorkerHistoryPreparationV1.create(semantic),
        semantic,
    )
    assert review.historical_package_revisions == (
        ("reviewworker", receipt.policy.plugin_revision_digest),
    )
    assert review.current_package_revisions == review.historical_package_revisions
    assert review.retained_receipt_revisions == (
        (receipt.fingerprint, "reviewworker", receipt.policy.plugin_revision_digest),
    )


def test_windows_desired_reference_review_refuses_unselected_receipt(
    tmp_path: Path,
) -> None:
    semantic = _semantic_read()
    snapshot, transitions = _desired_capture(
        tmp_path, artifact_digest=sha256(b"other wheel").hexdigest()
    )
    semantic = replace(
        semantic,
        desired_inventory_revision=snapshot.inventory_revision,
        desired_history_digest=_coding_windows_worker_desired_history_digest(
            snapshot, transitions
        ),
        desired_snapshot=snapshot,
        desired_transitions=transitions,
    )
    with pytest.raises(ValueError, match="receipt lacks Desired selection"):
        CodingWindowsWorkerDesiredReferenceReviewV1.from_semantic_read(
            CodingWindowsWorkerHistoryPreparationV1.create(semantic),
            semantic,
        )


def test_windows_desired_reference_review_keeps_retired_selection(
    tmp_path: Path,
) -> None:
    semantic = _semantic_read()
    receipt = semantic.offline_recovery.receipt_records[0].receipt
    snapshot, transitions = _desired_capture(
        tmp_path,
        artifact_digest=receipt.policy.plugin_revision_digest,
        remove_selection=True,
    )
    semantic = replace(
        semantic,
        desired_inventory_revision=snapshot.inventory_revision,
        desired_history_digest=_coding_windows_worker_desired_history_digest(
            snapshot, transitions
        ),
        desired_snapshot=snapshot,
        desired_transitions=transitions,
    )
    review = CodingWindowsWorkerDesiredReferenceReviewV1.from_semantic_read(
        CodingWindowsWorkerHistoryPreparationV1.create(semantic), semantic
    )
    assert review.current_package_revisions == ()
    assert review.historical_package_revisions == (
        ("reviewworker", receipt.policy.plugin_revision_digest),
    )
