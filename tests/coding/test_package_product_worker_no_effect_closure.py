"""A settled C5 no-effect record never licenses an unrelated native gate."""

from __future__ import annotations

from dataclasses import replace

from loushang.coding.package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from loushang.coding.package_product_worker_no_effect_closure import (
    is_coding_worker_no_effect_closure,
)
from loushang.coding.package_product_worker_history_retention import (
    _receipt_gate_reference_issue,
)
from loushang.coding.package_product_worker_receipt import CodingWorkerReceiptRecordV1
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)
from tests.harness.worker.test_product_activation import _receipt


def test_no_effect_closure_requires_exact_c5_receipt_and_unreleased_gate() -> None:
    receipt = _receipt()
    gate = CodingWorkerStartGateRecordV1.create(
        journal_revision=1,
        phase="intent",
        attempt_id="b" * 32,
        worker_identity_fingerprint="c" * 64,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=receipt.policy.fingerprint,
        scope_id=receipt.policy.product_scope_id,
        native_closure_digest="d" * 64,
        identity=None,
    )
    recorded = CodingWorkerReceiptRecordV1.create(
        journal_revision=receipt.issue_sequence,
        scope_id=receipt.policy.product_scope_id,
        opt_in_decision_digest="e" * 64,
        receipt=receipt,
    )
    activation = CodingProductWorkerRetainedAttemptV1(
        attempt_id=gate.attempt_id,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=receipt.policy.fingerprint,
        owner_generation=receipt.policy.owner_selection_generation,
        cleanup_contract_version=1,
        host_identity="host-1",
        boot_identity="boot-1",
        phase="settled",
        last_seen_revision=4,
        current=True,
        no_effect=True,
    )
    evidence = dict(gate=gate, activation=activation, supervisor=None, receipt=recorded)
    assert is_coding_worker_no_effect_closure(**evidence)
    assert (
        _receipt_gate_reference_issue(gate, recorded, None, "unobserved", activation)
        is None
    )
    assert _receipt_gate_reference_issue(gate, recorded, None, "unobserved") == (
        "receipt_reference_gate_unbound"
    )
    assert not is_coding_worker_no_effect_closure(
        **{**evidence, "activation": replace(activation, no_effect=False)}
    )
    assert not is_coding_worker_no_effect_closure(
        **{**evidence, "activation": replace(activation, phase="registered")}
    )
    assert not is_coding_worker_no_effect_closure(
        **{**evidence, "activation": replace(activation, owner_generation=99)}
    )
    assert not is_coding_worker_no_effect_closure(**{**evidence, "receipt": None})
