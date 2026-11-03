"""No-effect V2 proof must preserve the exact cross-stream closure."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from loushang.coding.package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
    CodingWorkerNoEffectProofV2,
)
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
)
from loushang.coding.package_product_worker_policy import CodingWorkerOptInV1
from loushang.coding.package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
)
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)
from tests.harness.worker.test_product_activation import _policy, _receipt


def _proof() -> CodingWorkerNoEffectProofV2:
    policy = replace(
        _policy(),
        product_scope_id="scope",
        plugin_id="plugin-a",
        owner_selection_generation=1,
        kill_switch_generation=0,
    )
    receipt = replace(
        _receipt(policy=policy), issue_sequence=1, issue_nonce="no-effect-proof"
    )
    allow = CodingWorkerOptInDecisionV1.create(
        journal_revision=1,
        scope_id="scope",
        plugin_id="plugin-a",
        operation_id="allow-a1",
        generation=1,
        kill_switch_generation=0,
        action="allow",
        opt_in=CodingWorkerOptInV1(
            plugin_id="plugin-a",
            contribution_id="query-provider",
            owner_id="coding",
            artifact_digest="d" * 64,
            native_platform="linux-x86_64",
            owner_selection_generation=1,
            kill_switch_generation=0,
            require_worker=True,
        ),
    )
    receipt_record = CodingWorkerReceiptRecordV1.create(
        journal_revision=1,
        scope_id="scope",
        opt_in_decision_digest=allow.decision_digest,
        receipt=receipt,
    )
    attempt_id = "a" * 32
    gate = CodingWorkerStartGateRecordV1.create(
        journal_revision=1,
        phase="intent",
        attempt_id=attempt_id,
        worker_identity_fingerprint="b" * 64,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=policy.fingerprint,
        scope_id="scope",
        native_closure_digest="c" * 64,
        identity=None,
    )
    activation = CodingProductWorkerRetainedAttemptV1(
        attempt_id=attempt_id,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=policy.fingerprint,
        owner_generation=1,
        cleanup_contract_version=1,
        host_identity="host-a",
        boot_identity="boot-a",
        phase="settled",
        last_seen_revision=2,
        current=True,
        no_effect=True,
    )
    return CodingWorkerNoEffectProofV2(
        gate=gate,
        receipt=receipt_record,
        activation=activation,
        historical_allow=allow,
        repair_intent_digest="e" * 64,
    )


def test_no_effect_archive_round_trips_and_refuses_changed_cross_stream_proof() -> None:
    proof = _proof()
    archive = CodingWorkerNoEffectArchiveV2(
        scope_id="scope",
        store_id="store",
        checkpoint_digest="f" * 64,
        proofs=(proof,),
    )
    assert CodingWorkerNoEffectArchiveV2.from_bytes(archive.to_bytes()) == archive

    with pytest.raises(ValueError, match="no-effect V2 proof is invalid"):
        replace(proof, activation=replace(proof.activation, no_effect=False))
    revoke = CodingWorkerOptInDecisionV1.create(
        journal_revision=2,
        scope_id="scope",
        plugin_id="plugin-a",
        operation_id="revoke-a2",
        generation=2,
        kill_switch_generation=1,
        action="revoke",
        opt_in=None,
    )
    with pytest.raises(ValueError, match="no-effect V2 proof is invalid"):
        replace(proof, historical_allow=revoke)

    with pytest.raises(ValueError, match="archive bytes are invalid"):
        CodingWorkerNoEffectArchiveV2.from_bytes(
            json.dumps(json.loads(archive.to_bytes())).encode("utf-8")
        )
