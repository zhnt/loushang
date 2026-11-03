"""Windows Worker receipt cutover preserves historical allow and old IDs."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.coding.package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from loushang.coding.package_product_worker_policy import (
    CodingWorkerOptInV1,
    coding_worker_session_scope_id,
)
from loushang.coding.package_product_worker_receipt import CodingWorkerReceiptRecordV1
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)


def _semantic_read() -> CodingWindowsWorkerHistorySemanticReadV1:
    scope = "scope-a"
    allow = CodingWorkerOptInDecisionV1.create(
        journal_revision=1,
        scope_id=scope,
        plugin_id="reviewworker",
        operation_id="allow-1",
        generation=1,
        kill_switch_generation=0,
        action="allow",
        opt_in=CodingWorkerOptInV1(
            plugin_id="reviewworker",
            contribution_id="query-provider",
            owner_id="coding",
            artifact_digest=sha256(b"wheel").hexdigest(),
            native_platform="windows-amd64",
            owner_selection_generation=1,
            kill_switch_generation=0,
            require_worker=False,
        ),
    )
    revoke = CodingWorkerOptInDecisionV1.create(
        journal_revision=2,
        scope_id=scope,
        plugin_id="reviewworker",
        operation_id="revoke-2",
        generation=2,
        kill_switch_generation=1,
        action="revoke",
        opt_in=None,
    )
    digest = sha256(b"fact").hexdigest()
    policy = ProductWorkerActivationPolicyV1(
        product_id="coding",
        product_runtime_id="runtime-a",
        product_scope_id=coding_worker_session_scope_id("session-a"),
        session_id="session-a",
        session_route="new",
        selected_locator_fingerprint=None,
        selected_locator_revision="new-session",
        plugin_id="reviewworker",
        plugin_revision_digest=allow.opt_in.artifact_digest,
        contribution_id="query-provider",
        reservation_fingerprint=digest,
        declaration_fingerprint=digest,
        worker_configuration_fingerprint=digest,
        declared_required=False,
        effective_required=False,
        enabled=True,
        allowed_product_ids=("coding",),
        allowed_contribution_ids=("query-provider",),
        requested_owner="hosting",
        owner_selection_generation=1,
        no_fallback=True,
        native_profile_id="windows-lpac-contained-pe-v1",
        native_profile_catalog_revision="catalog-a",
        allowed_native_profile_ids=("windows-lpac-contained-pe-v1",),
        expected_native_policy_closure_fingerprint=digest,
        product_policy_revision="policy-a",
        kill_switch_generation=0,
    )
    receipt = ProductWorkerActivationReceiptV1(
        policy=policy, issue_sequence=1, issue_nonce="receipt-a"
    )
    record = CodingWorkerReceiptRecordV1.create(
        journal_revision=1,
        scope_id=scope,
        opt_in_decision_digest=allow.decision_digest,
        receipt=receipt,
    )
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id=scope,
        store_id="store-a",
        lease_owner_revision=4,
        files=tuple(
            CodingWindowsWorkerHistorySourceFileV1(
                name=name, size=1, sha256_digest=sha256(name.encode()).hexdigest()
            )
            for name in ("worker-activation-receipts.jsonl", "worker-opt-in.jsonl")
        ),
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=4,
        attempts=(),
        opt_in_decisions=(allow, revoke),
        receipt_records=(record,),
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


def test_windows_receipt_base_keeps_historical_allow_after_revoke() -> None:
    semantic = _semantic_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    base = CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(
        prepared, semantic
    )
    assert base.last_issue_sequence == 1
    assert base.retired_receipt_fingerprints == (
        semantic.offline_recovery.receipt_records[0].receipt.fingerprint,
    )
    assert CodingWindowsWorkerReceiptSemanticBaseV1.from_bytes(base.to_bytes()) == base
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((semantic.offline_recovery.receipt_records[0],))


def test_windows_receipt_base_refuses_missing_source() -> None:
    semantic = _semantic_read()
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=4,
        files=(semantic.source_snapshot.files[-1],),
    )
    changed = CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source, offline_recovery=semantic.offline_recovery
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed)
    with pytest.raises(ValueError, match="source is absent"):
        CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(prepared, changed)


def test_windows_receipt_base_refuses_revoke_as_original_allow() -> None:
    semantic = _semantic_read()
    record = semantic.offline_recovery.receipt_records[0]
    revoked = semantic.offline_recovery.opt_in_decisions[-1]
    changed = replace(
        semantic,
        offline_recovery=replace(
            semantic.offline_recovery,
            receipt_records=(
                CodingWorkerReceiptRecordV1.create(
                    journal_revision=1,
                    scope_id="scope-a",
                    opt_in_decision_digest=revoked.decision_digest,
                    receipt=record.receipt,
                ),
            ),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed)
    with pytest.raises(ValueError, match="receipt history is invalid"):
        CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(prepared, changed)


def test_windows_receipt_base_refuses_policy_artifact_mismatch() -> None:
    semantic = _semantic_read()
    record = semantic.offline_recovery.receipt_records[0]
    wrong_policy = replace(
        record.receipt.policy,
        plugin_revision_digest=sha256(b"wrong-wheel").hexdigest(),
    )
    wrong_receipt = replace(record.receipt, policy=wrong_policy)
    changed = replace(
        semantic,
        offline_recovery=replace(
            semantic.offline_recovery,
            receipt_records=(
                CodingWorkerReceiptRecordV1.create(
                    journal_revision=1,
                    scope_id="scope-a",
                    opt_in_decision_digest=record.opt_in_decision_digest,
                    receipt=wrong_receipt,
                ),
            ),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed)
    with pytest.raises(ValueError, match="receipt history is invalid"):
        CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(prepared, changed)
