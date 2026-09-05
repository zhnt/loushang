from __future__ import annotations

import gc
import json
import threading
from contextlib import AbstractContextManager
from dataclasses import replace

import pytest

import loushang.harness.worker.product_activation as activation_module
from loushang.harness.worker import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    WorkerCleanupDebtV1,
    WorkerCleanupDebtV2,
    WorkerCleanupSettlementV1,
    WorkerCleanupSettlementV2,
    _ActivationReason,
    _ActivationRejected,
    _CleanupDebtReason,
    _CleanupDebtReasonV2,
    _MemoryActivationStateStore,
    _transition_attempt,
)

PLC9C5_C51_CASES = (
    "C51-CURRENT-REQUIREDNESS",
    "C51-INVALID-RECEIPT",
    "C51-STALE-RECEIPT",
    "C51-FOREIGN-RECEIPT",
    "C51-POLICY-CLOSURE-CODEC",
    "C51-PREACQUIRE-FRESHNESS",
    "C51-PREPUBLISH-ATOMIC-CAS",
    "C51-KILLSWITCH-PUBLISH-BLOCKED",
    "C51-RECEIPT-ATTEMPT-CLOSURE",
    "C51-EXACT-RETIRE-CAS",
    "C51-KILLSWITCH-ADMISSION-BLOCKED",
    "C51-RESTART-LATCH",
    "C51-CLEANUP-SETTLED",
    "C51-CLEANUP-DEBT",
    "C51-STICKY-OWNER",
    "C51-NO-FALLBACK",
    "C51-REQUIRED-SUCCESS",
    "C51-OPTIONAL-DEGRADED",
    "C51-PUBLICATION-FENCE",
    "C51-SENTINEL-REDACTION",
)

PLC9C5_C51_HARDENING_CASES = (
    "C51-MONOTONIC-SETTLEMENT",
    "C51-DURABLE-POLICY-BUDGET",
    "C51-CAPACITY-PREWRITE",
    "C51-KILLSWITCH-DURABLE-RETRY",
    "C51-GATE-RELEASE-IMMEDIATE",
    "C51-NOEFFECT-NORMAL",
    "C51-NOEFFECT-EXCEPTION",
    "C51-NOEFFECT-EXPLICIT",
    "C51-EFFECT-EXCEPTION",
    "C51-COMMIT-BEFORE-RETURN",
    "C51-DUAL-COORDINATOR-CAS",
    "C51-PUBLISH-THEN-KILL-RACE",
    "C51-KILL-THEN-PUBLISH-RACE",
    "C51-DYNAMIC-PORT-REENTRY",
    "C51-PORT-FAULTS",
    "C51-COUNTERFEIT-EVIDENCE",
    "C51-REGISTERED-RECOVERY",
    "C51-GATE-RELEASE-PREFAULT",
    "C51-GATE-RELEASE-POSTFAULT",
    "C51-CROSS-THREAD-AUTHORITY-REENTRY",
    "C51-CROSS-THREAD-STORE-REENTRY",
    "C51-CROSS-THREAD-EVIDENCE-REENTRY",
    "C51-RELEASE-DEBT-PUBLISH",
    "C51-RELEASE-DEBT-ADMISSION-VALIDATION",
    "C51-RELEASE-DEBT-ADMISSION-CAS",
    "C51-RELEASE-DEBT-DRAIN-JOIN",
    "C51-SHARED-AUTHORITY-DOMAIN",
    "C51-SHARED-STORE-DOMAIN",
    "C51-SHARED-EVIDENCE-DOMAIN",
    "C51-DISJOINT-OWNER-PARALLEL",
    "C51-SHARED-RELEASE-DEBT-DRAIN",
    "C51-CROSS-OWNER-CALLBACK-FENCE",
    "C51-SHARED-DOMAIN-WRAPPERS",
    "C51-DOMAIN-TOKEN-WEAKREF",
    "C51-ENTER-AMBIGUITY-CLEANUP",
    "C51-EXIT-CALLBACK-DRAIN-REENTRY",
    "C51-RETIRE-RELEASE-PREFAULT",
    "C51-RETIRE-RELEASE-POSTFAULT",
    "C51-LATCH-RELEASE-PREFAULT",
    "C51-LATCH-RELEASE-POSTFAULT",
    "C51-HELD-GATE-NO-EARLY-RELEASE",
    "C51-RESERVED-GATE-NO-DRAIN",
    "C51-RELEASING-RETRY-FAILFAST",
    "C51-RELEASE-FAULT-RETRY-TAKEOVER",
    "C51-SHARED-EXIT-CALLBACK-RETRY-REJECT",
)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_EVIDENCE_AUTHORITY_ID = "test-cleanup-evidence-v1"
_EVIDENCE_AUTHORITY_FINGERPRINT = "e" * 64
_ATTEMPT_A = "1" * 32
_ATTEMPT_B = "2" * 32


class _Authority:
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        self._lock = threading.RLock()
        self.witness = receipt.authority_witness
        self.events: list[str] = []
        self.in_gate = False
        self.evidence_authority = _CleanupEvidenceOwner(receipt)

    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self

        class _Gate(AbstractContextManager[None]):
            def __enter__(self) -> None:
                authority._lock.acquire()
                assert not authority.in_gate
                authority.in_gate = True
                authority.events.append("gate-enter")

            def __exit__(self, *args: object) -> None:
                authority.events.append("gate-exit")
                authority.in_gate = False
                authority._lock.release()

        return _Gate()

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        assert self.in_gate
        self.events.append("witness")
        return self.witness

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        assert self.in_gate
        self.events.append("latch")
        if self.witness[-1] == expected_generation:
            self.witness = (*self.witness[:-1], expected_generation + 1)
        elif self.witness[-1] != expected_generation + 1:
            raise AssertionError("unexpected kill-switch generation")
        return expected_generation + 1


class _CleanupEvidenceOwner:
    authority_id = _EVIDENCE_AUTHORITY_ID
    authority_fingerprint = _EVIDENCE_AUTHORITY_FINGERPRINT

    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        self.receipt = receipt
        self.tree_witness = object()
        self.native_containment_witness = object()
        self.changed_boot_witness = object()
        self.registered_witness = object()

    def verify_tree_settlement(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return (
            witness is self.tree_witness
            and receipt_fingerprint == self.receipt.fingerprint
            and attempt_id == _ATTEMPT_A
            and owner_generation == 1
            and host_identity == "host-1"
            and boot_identity == "boot-1"
            and evidence_authority_id == self.authority_id
            and evidence_authority_fingerprint == self.authority_fingerprint
        )

    def verify_native_containment_settlement(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return (
            witness is self.native_containment_witness
            and receipt_fingerprint == self.receipt.fingerprint
            and attempt_id == _ATTEMPT_A
            and owner_generation == 1
            and host_identity == "host-1"
            and boot_identity == "boot-1"
            and evidence_authority_id == self.authority_id
            and evidence_authority_fingerprint == self.authority_fingerprint
        )

    def verify_changed_boot_absence(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        current_boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return (
            witness is self.changed_boot_witness
            and receipt_fingerprint == self.receipt.fingerprint
            and attempt_id == _ATTEMPT_A
            and owner_generation == 1
            and host_identity == "host-1"
            and boot_identity == "boot-1"
            and current_boot_identity == "boot-2"
            and evidence_authority_id == self.authority_id
            and evidence_authority_fingerprint == self.authority_fingerprint
        )

    def verify_registered_lease_expired(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        current_boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return (
            witness is self.registered_witness
            and receipt_fingerprint == self.receipt.fingerprint
            and attempt_id in {_ATTEMPT_A, _ATTEMPT_B}
            and owner_generation in {1, 2}
            and host_identity == "host-1"
            and boot_identity == "boot-1"
            and current_boot_identity == "boot-2"
            and evidence_authority_id == self.authority_id
            and evidence_authority_fingerprint == self.authority_fingerprint
        )


def _policy(
    *,
    product_id: str = "coding",
    required: bool = True,
    enabled: bool = True,
    requested_owner: str = "hosting",
) -> ProductWorkerActivationPolicyV1:
    return ProductWorkerActivationPolicyV1(
        product_id=product_id,
        product_runtime_id="runtime-1",
        product_scope_id="scope-1",
        session_id="session-1",
        session_route="selected",
        selected_locator_fingerprint=_DIGEST_A,
        selected_locator_revision="locator-1",
        plugin_id="plugin.one",
        plugin_revision_digest=_DIGEST_A,
        contribution_id="capability.query",
        reservation_fingerprint=_DIGEST_A,
        declaration_fingerprint=_DIGEST_A,
        worker_configuration_fingerprint=_DIGEST_A,
        declared_required=required,
        effective_required=required,
        enabled=enabled,
        allowed_product_ids=(product_id,),
        allowed_contribution_ids=("capability.query",),
        requested_owner=requested_owner,  # type: ignore[arg-type]
        owner_selection_generation=4,
        no_fallback=True,
        native_profile_id="posix-static-contained-elf-v1",
        native_profile_catalog_revision="native-catalog-1",
        allowed_native_profile_ids=("posix-static-contained-elf-v1",),
        expected_native_policy_closure_fingerprint=_DIGEST_B,
        product_policy_revision="policy-1",
        kill_switch_generation=7,
    )


def _receipt(
    policy: ProductWorkerActivationPolicyV1 | None = None,
) -> ProductWorkerActivationReceiptV1:
    return ProductWorkerActivationReceiptV1(
        policy=policy or _policy(),
        issue_sequence=11,
        issue_nonce="receipt-nonce-1",
    )


def _coordinator(
    *,
    receipt: ProductWorkerActivationReceiptV1 | None = None,
    store: _MemoryActivationStateStore | None = None,
    restart_budget: int = 3,
    authority_domain_token: object | None = None,
    store_domain_token: object | None = None,
    evidence_domain_token: object | None = None,
) -> tuple[ProductWorkerActivationCoordinator, _Authority]:
    receipt = receipt or _receipt()
    authority = _Authority(receipt)
    return (
        ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=(
                authority.evidence_authority.authority_id
            ),
            trusted_evidence_authority_fingerprint=(
                authority.evidence_authority.authority_fingerprint
            ),
            state_store=store,
            restart_budget=restart_budget,
            _authority_domain_token=authority_domain_token,
            _store_domain_token=store_domain_token,
            _evidence_domain_token=evidence_domain_token,
        ),
        authority,
    )


def _begin(
    coordinator: ProductWorkerActivationCoordinator,
    receipt: ProductWorkerActivationReceiptV1,
    *,
    attempt_id: str = _ATTEMPT_A,
    owner_generation: int = 1,
    cleanup_contract_version: int = 1,
) -> None:
    with coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=attempt_id,
        owner_generation=owner_generation,
        host_identity="host-1",
        boot_identity="boot-1",
        cleanup_contract_version=cleanup_contract_version,
    ) as admission:
        admission.begin_effect()


def _publish(
    coordinator: ProductWorkerActivationCoordinator,
    receipt: ProductWorkerActivationReceiptV1,
    *,
    attempt_id: str = _ATTEMPT_A,
    owner_generation: int = 1,
) -> dict[str, object]:
    return dict(
        coordinator.publish(
            receipt=receipt,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            realized_native_policy_closure_fingerprint=(
                receipt.policy.expected_native_policy_closure_fingerprint
            ),
            native_profile_catalog_revision=(
                receipt.policy.native_profile_catalog_revision
            ),
            native_profile_id=receipt.policy.native_profile_id,
        )
    )


def _retire_and_terminal(
    coordinator: ProductWorkerActivationCoordinator,
    receipt: ProductWorkerActivationReceiptV1,
    *,
    attempt_id: str = _ATTEMPT_A,
    owner_generation: int = 1,
) -> None:
    coordinator.record_protocol_terminal(
        receipt=receipt,
        attempt_id=attempt_id,
        owner_generation=owner_generation,
    )
    coordinator.retire_exact(
        receipt=receipt,
        attempt_id=attempt_id,
        owner_generation=owner_generation,
    )


def _settlement(receipt: ProductWorkerActivationReceiptV1) -> WorkerCleanupSettlementV1:
    return WorkerCleanupSettlementV1(
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
        protocol_terminal=True,
        domain_retired=True,
        tree_settled=True,
    )


def _pending_release_count(coordinator: ProductWorkerActivationCoordinator) -> int:
    return len(coordinator._authority.callback_domain.pending_releases)


@pytest.mark.parametrize("case_id", PLC9C5_C51_CASES, ids=PLC9C5_C51_CASES)
def test_plc9c5_c51_contract_case(case_id: str) -> None:
    policy = _policy()
    receipt = _receipt(policy)

    if case_id == "C51-CURRENT-REQUIREDNESS":
        coordinator, authority = _coordinator(receipt=receipt)
        missing = coordinator.evaluate(policy, None)
        assert missing["reason"] == "policy_required_unavailable"
        current = _policy(required=False, enabled=False, requested_owner="current")
        assert coordinator.evaluate(current, None)["reason"] == "disabled_by_policy"

    elif case_id == "C51-INVALID-RECEIPT":
        document = receipt.to_dict()
        document["unexpected"] = "sentinel"
        with pytest.raises(ValueError, match="invalid fields"):
            ProductWorkerActivationReceiptV1.from_dict(document)
        document = receipt.to_dict()
        document["receiptFingerprint"] = _DIGEST_A
        with pytest.raises(ValueError, match="fingerprint mismatch"):
            ProductWorkerActivationReceiptV1.from_dict(document)

    elif case_id == "C51-STALE-RECEIPT":
        coordinator, authority = _coordinator(receipt=receipt)
        authority.witness = (*receipt.authority_witness[:-1], 99)
        with pytest.raises(_ActivationRejected) as rejected:
            _begin(coordinator, receipt)
        assert rejected.value.reason is _ActivationReason.STALE_AUTHORITY
        assert coordinator.active_attempts() == ()

    elif case_id == "C51-FOREIGN-RECEIPT":
        coordinator, _ = _coordinator(receipt=receipt)
        foreign = _receipt(_policy(product_id="work"))
        decision = coordinator.evaluate(policy, foreign)
        assert decision["reason"] == "foreign_receipt"

    elif case_id == "C51-POLICY-CLOSURE-CODEC":
        closure = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
            native_profile_catalog_revision="catalog-1",
            native_profile_id="profile-1",
            payload_sha256=_DIGEST_A,
            containment_launcher_sha256=_DIGEST_B,
            containment_profile_sha256=None,
        )
        repeated = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
            native_profile_catalog_revision="catalog-1",
            native_profile_id="profile-1",
            payload_sha256=_DIGEST_A,
            containment_launcher_sha256=_DIGEST_B,
            containment_profile_sha256=None,
        )
        changed = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
            native_profile_catalog_revision="catalog-1",
            native_profile_id="profile-1",
            payload_sha256=_DIGEST_B,
            containment_launcher_sha256=_DIGEST_B,
            containment_profile_sha256=None,
        )
        assert closure == repeated
        assert closure != changed
        assert len(closure) == 64

    elif case_id == "C51-PREACQUIRE-FRESHNESS":
        coordinator, authority = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        assert authority.events == ["gate-enter", "witness", "gate-exit"]
        assert coordinator.active_attempts()[0]["phase"] == "effect_started"

    elif case_id == "C51-PREPUBLISH-ATOMIC-CAS":
        coordinator, authority = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        authority.events.clear()
        status = _publish(coordinator, receipt)
        assert status["reason"] == "published"
        assert authority.events == ["gate-enter", "witness", "gate-exit"]
        assert len(coordinator.snapshot()["publications"]) == 1  # type: ignore[arg-type]

    elif case_id == "C51-KILLSWITCH-PUBLISH-BLOCKED":
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        active = coordinator.latch_kill_switch(expected_generation=7)
        assert active[0]["attemptId"] == _ATTEMPT_A
        with pytest.raises(_ActivationRejected) as rejected:
            _publish(coordinator, receipt)
        assert rejected.value.reason is _ActivationReason.KILL_SWITCH_LATCHED
        assert coordinator.snapshot()["publications"] == {}

    elif case_id == "C51-RECEIPT-ATTEMPT-CLOSURE":
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        with pytest.raises(_ActivationRejected) as rejected:
            _publish(coordinator, receipt, attempt_id=_ATTEMPT_B)
        assert rejected.value.reason is _ActivationReason.INVALID_RECEIPT
        with pytest.raises(_ActivationRejected):
            _publish(coordinator, receipt, owner_generation=2)

    elif case_id == "C51-EXACT-RETIRE-CAS":
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        _publish(coordinator, receipt)
        with pytest.raises(_ActivationRejected):
            coordinator.retire_exact(
                receipt=receipt,
                attempt_id=_ATTEMPT_A,
                owner_generation=2,
            )
        status = coordinator.retire_exact(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
        )
        assert status["reason"] == "retired"
        assert coordinator.snapshot()["publications"] == {}

    elif case_id == "C51-KILLSWITCH-ADMISSION-BLOCKED":
        coordinator, _ = _coordinator(receipt=receipt)
        coordinator.latch_kill_switch(expected_generation=7)
        with pytest.raises(_ActivationRejected) as rejected:
            _begin(coordinator, receipt)
        assert rejected.value.reason is _ActivationReason.KILL_SWITCH_LATCHED
        assert coordinator.active_attempts() == ()

    elif case_id == "C51-RESTART-LATCH":
        store = _MemoryActivationStateStore()
        coordinator, authority = _coordinator(receipt=receipt, store=store)
        coordinator.latch_kill_switch(expected_generation=7)
        restarted = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=store,
        )
        assert restarted.snapshot()["killSwitchState"] == "completed"
        with pytest.raises(_ActivationRejected):
            _begin(restarted, receipt)

    elif case_id == "C51-CLEANUP-SETTLED":
        coordinator, authority = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        _retire_and_terminal(coordinator, receipt)
        evidence = authority.evidence_authority
        status = coordinator.record_cleanup_settlement(
            _settlement(receipt),
            witness=evidence.tree_witness,
        )
        assert status["reason"] == "cleanup_settled"
        assert coordinator.claim_restart(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
        )["reason"] == "restart_ready"

    elif case_id == "C51-CLEANUP-DEBT":
        coordinator, authority = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        _retire_and_terminal(coordinator, receipt)
        debt = WorkerCleanupDebtV1(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            host_identity="host-1",
            boot_identity="boot-1",
            reason=_CleanupDebtReason.SAME_BOOT_UNKNOWN_TREE,
        )
        coordinator.record_cleanup_debt(debt)
        evidence = authority.evidence_authority
        with pytest.raises(_ActivationRejected) as blocked:
            coordinator.claim_restart(
                receipt=receipt,
                attempt_id=_ATTEMPT_A,
                owner_generation=1,
            )
        assert blocked.value.reason is _ActivationReason.CLEANUP_DEBT
        with pytest.raises(_ActivationRejected):
            coordinator.settle_changed_boot_absence(
                receipt=receipt,
                attempt_id=_ATTEMPT_A,
                owner_generation=1,
                current_boot_identity="boot-1",
                witness=evidence.changed_boot_witness,
            )
        with pytest.raises(_ActivationRejected) as forged:
            coordinator.settle_changed_boot_absence(
                receipt=receipt,
                attempt_id=_ATTEMPT_A,
                owner_generation=1,
                current_boot_identity="boot-2",
                witness=object(),
            )
        assert forged.value.reason is _ActivationReason.CLEANUP_DEBT
        coordinator.settle_changed_boot_absence(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            current_boot_identity="boot-2",
            witness=evidence.changed_boot_witness,
        )

    elif case_id == "C51-STICKY-OWNER":
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        active = coordinator.latch_kill_switch(expected_generation=7)
        assert active == (
            {
                "attemptId": _ATTEMPT_A,
                "owner": "hosting",
                "ownerGeneration": 1,
                "phase": "effect_started",
                "readiness": "pending",
                "receiptFingerprint": receipt.fingerprint,
                "required": True,
            },
        )

    elif case_id == "C51-NO-FALLBACK":
        coordinator, authority = _coordinator(receipt=receipt)
        authority.witness = (*receipt.authority_witness[:-1], 99)
        with pytest.raises(_ActivationRejected):
            _begin(coordinator, receipt)
        serialized = json.dumps(coordinator.snapshot(), sort_keys=True)
        assert "current" not in serialized
        assert coordinator.active_attempts() == ()

    elif case_id == "C51-REQUIRED-SUCCESS":
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        status = _publish(coordinator, receipt)
        assert status["reason"] == "published"
        assert status["required"] is True
        assert coordinator.active_attempts()[0]["readiness"] == "ready"

    elif case_id == "C51-OPTIONAL-DEGRADED":
        optional = _policy(required=False)
        optional_receipt = _receipt(optional)
        coordinator, _ = _coordinator(receipt=optional_receipt)
        conflicting = replace(optional, product_scope_id="other-scope")
        decision = coordinator.evaluate(conflicting, optional_receipt)
        assert decision["reason"] == "optional_degraded"
        assert decision["required"] is False

    elif case_id == "C51-PUBLICATION-FENCE":
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        _begin(coordinator, receipt, attempt_id=_ATTEMPT_B, owner_generation=2)
        _publish(coordinator, receipt)
        with pytest.raises(_ActivationRejected) as fenced:
            _publish(
                coordinator,
                receipt,
                attempt_id=_ATTEMPT_B,
                owner_generation=2,
            )
        assert fenced.value.reason is _ActivationReason.PUBLICATION_FENCED

    elif case_id == "C51-SENTINEL-REDACTION":
        sentinel = "/tmp/secret-path?TOKEN=credential"
        with pytest.raises(ValueError, match="opaque token"):
            replace(policy, product_runtime_id=sentinel)
        coordinator, _ = _coordinator(receipt=receipt)
        _begin(coordinator, receipt)
        _retire_and_terminal(coordinator, receipt)
        debt = WorkerCleanupDebtV1(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            host_identity="host-1",
            boot_identity="boot-1",
            reason=_CleanupDebtReason.SETTLEMENT_INCOMPLETE,
        )
        coordinator.record_cleanup_debt(debt)
        assert sentinel not in json.dumps(coordinator.snapshot(), sort_keys=True)

    else:  # pragma: no cover - the manifest/parameter equality guard owns this
        raise AssertionError(f"Unhandled PLC9C5 C5.1 case {case_id}")


class _FaultingLatchAuthority(_Authority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self.fail_once = True

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        generation = super().latch_kill_switch(
            expected_generation=expected_generation,
        )
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("injected authority failure")
        return generation


class _CommitThenRaiseStore(_MemoryActivationStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.raise_after_commit = False

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: object,
    ) -> bool:
        assert isinstance(document, dict)
        committed = super().compare_and_swap(
            expected_revision=expected_revision,
            document=document,
        )
        if committed and self.raise_after_commit:
            self.raise_after_commit = False
            raise RuntimeError("injected post-commit failure")
        return committed


class _RegistrationRaceStore(_MemoryActivationStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.registration_entered = threading.Event()
        self.registration_release = threading.Event()
        self.race_registration = False

class _RegistrationRaceStoreView(_MemoryActivationStateStore):
    """Independent callback owner over a shared, lock-only CAS document."""

    def __init__(self, backend: _RegistrationRaceStore) -> None:
        self.backend = backend

    def load(self) -> object:
        return self.backend.load()

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: object,
    ) -> bool:
        assert isinstance(document, dict)
        if self.backend.race_registration and expected_revision == 1:
            self.backend.registration_entered.set()
            assert self.backend.registration_release.wait(timeout=2)
        return self.backend.compare_and_swap(
            expected_revision=expected_revision,
            document=document,
        )


class _BlockingAuthority(_Authority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self.block_witness = False
        self.block_latch = False
        self.witness_entered = threading.Event()
        self.latch_entered = threading.Event()
        self.release = threading.Event()

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        if self.block_witness:
            self.witness_entered.set()
            assert self.release.wait(timeout=2)
        return super().current_witness(receipt)

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        if self.block_latch:
            self.latch_entered.set()
            assert self.release.wait(timeout=2)
        return super().latch_kill_switch(expected_generation=expected_generation)


class _ReentrantAuthority(_Authority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self.coordinator: ProductWorkerActivationCoordinator | None = None

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        assert self.coordinator is not None
        self.coordinator.snapshot()
        return super().current_witness(receipt)


class _FaultingWitnessAuthority(_Authority):
    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        raise RuntimeError("injected witness failure")


class _FaultingLoadStore(_MemoryActivationStateStore):
    def load(self) -> object:
        raise RuntimeError("injected store failure")


class _AlwaysTrueEvidenceAuthority:
    authority_id = "counterfeit-evidence-v1"
    authority_fingerprint = "f" * 64

    def verify_tree_settlement(self, **kwargs: object) -> bool:
        return True

    def verify_changed_boot_absence(self, **kwargs: object) -> bool:
        return True

    def verify_registered_lease_expired(self, **kwargs: object) -> bool:
        return True


class _OrphaningStore(_MemoryActivationStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.orphan_next_registration = False
        self._reject_auto_settlement = False

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: object,
    ) -> bool:
        assert isinstance(document, dict)
        if self.orphan_next_registration and expected_revision == 1:
            self.orphan_next_registration = False
            self._reject_auto_settlement = True
            super().compare_and_swap(
                expected_revision=expected_revision,
                document=document,
            )
            raise RuntimeError("injected registration post-commit failure")
        if self._reject_auto_settlement:
            self._reject_auto_settlement = False
            raise RuntimeError("injected auto-settlement pre-commit failure")
        return super().compare_and_swap(
            expected_revision=expected_revision,
            document=document,
        )


class _FaultingGateAuthority(_Authority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self._lock = threading.Lock()
        self.release_failure: str | None = None
        self.release_calls = 0
        self.block_release = False
        self.release_entered = threading.Event()
        self.allow_release = threading.Event()

    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self

        class _RetryableGate(AbstractContextManager[None]):
            def __init__(self) -> None:
                self.released = False

            def __enter__(self) -> None:
                authority._lock.acquire()
                assert not authority.in_gate
                authority.in_gate = True

            def __exit__(self, *args: object) -> None:
                authority.release_calls += 1
                if self.released:
                    return
                if authority.block_release:
                    authority.release_entered.set()
                    assert authority.allow_release.wait(timeout=2)
                if authority.release_failure == "pre":
                    authority.release_failure = None
                    raise RuntimeError("injected pre-release failure")
                authority.in_gate = False
                authority._lock.release()
                self.released = True
                if authority.release_failure == "post":
                    authority.release_failure = None
                    raise RuntimeError("injected post-release failure")

        return _RetryableGate()


class _RejectRegistrationStore(_MemoryActivationStateStore):
    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: object,
    ) -> bool:
        assert isinstance(document, dict)
        if expected_revision == 1:
            return False
        return super().compare_and_swap(
            expected_revision=expected_revision,
            document=document,
        )


class _ParallelWitnessAuthority(_Authority):
    def __init__(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        barrier: threading.Barrier,
    ) -> None:
        super().__init__(receipt)
        self.barrier = barrier

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        self.barrier.wait(timeout=2)
        return super().current_witness(receipt)


def _spawn_join_reentry(
    coordinator: ProductWorkerActivationCoordinator,
    observed: list[_ActivationReason],
) -> None:
    def enter() -> None:
        try:
            coordinator.snapshot()
        except _ActivationRejected as error:
            observed.append(error.reason)

    child = threading.Thread(target=enter)
    child.start()
    child.join(timeout=2)
    assert not child.is_alive()


class _SpawnJoinAuthority(_Authority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self.coordinator: ProductWorkerActivationCoordinator | None = None
        self.observed: list[_ActivationReason] = []

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        assert self.coordinator is not None
        _spawn_join_reentry(self.coordinator, self.observed)
        return super().current_witness(receipt)


class _SpawnJoinStore(_MemoryActivationStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.coordinator: ProductWorkerActivationCoordinator | None = None
        self.observed: list[_ActivationReason] = []

    def load(self) -> object:
        if self.coordinator is not None:
            _spawn_join_reentry(self.coordinator, self.observed)
        return super().load()

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: object,
    ) -> bool:
        assert isinstance(document, dict)
        if self.coordinator is not None:
            _spawn_join_reentry(self.coordinator, self.observed)
        return super().compare_and_swap(
            expected_revision=expected_revision,
            document=document,
        )


class _SpawnJoinEvidenceAuthority(_CleanupEvidenceOwner):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self.coordinator: ProductWorkerActivationCoordinator | None = None
        self.observed: list[_ActivationReason] = []

    def verify_tree_settlement(self, **kwargs: object) -> bool:
        assert self.coordinator is not None
        _spawn_join_reentry(self.coordinator, self.observed)
        return super().verify_tree_settlement(**kwargs)  # type: ignore[arg-type]


class _EnterAfterAcquireFaultAuthority(_FaultingGateAuthority):
    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self

        class _AmbiguousEnterGate(AbstractContextManager[None]):
            def __init__(self) -> None:
                self.acquired = False

            def __enter__(self) -> None:
                authority._lock.acquire()
                authority.in_gate = True
                self.acquired = True
                raise RuntimeError("injected post-acquire enter failure")

            def __exit__(self, *args: object) -> None:
                authority.release_calls += 1
                if authority.release_failure == "pre":
                    authority.release_failure = None
                    raise RuntimeError("injected pre-release failure")
                if self.acquired:
                    self.acquired = False
                    authority.in_gate = False
                    authority._lock.release()

        return _AmbiguousEnterGate()


class _ExitSpawnJoinAuthority(_FaultingGateAuthority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self.coordinator: ProductWorkerActivationCoordinator | None = None
        self.observed: list[_ActivationReason] = []

    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self
        delegate = super().serialized_admission()

        class _ExitCallbackGate(AbstractContextManager[None]):
            def __enter__(self) -> None:
                delegate.__enter__()

            def __exit__(self, *args: object) -> None:
                assert authority.coordinator is not None

                def retry() -> None:
                    try:
                        authority.coordinator.retry_pending_releases()
                    except _ActivationRejected as error:
                        authority.observed.append(error.reason)

                child = threading.Thread(target=retry)
                child.start()
                child.join(timeout=2)
                assert not child.is_alive()
                delegate.__exit__(*args)

        return _ExitCallbackGate()


class _DomainToken:
    pass


class _PauseFirstEnterAuthority(_Authority):
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        super().__init__(receipt)
        self._lock = threading.Lock()
        self._ordinal_lock = threading.Lock()
        self._next_ordinal = 1
        self.first_enter_called = threading.Event()
        self.allow_first_enter = threading.Event()
        self.exit_ordinals: list[int] = []

    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self
        with self._ordinal_lock:
            ordinal = self._next_ordinal
            self._next_ordinal += 1

        class _PausedGate(AbstractContextManager[None]):
            def __enter__(self) -> None:
                if ordinal == 1:
                    authority.first_enter_called.set()
                    assert authority.allow_first_enter.wait(timeout=2)
                authority._lock.acquire()
                assert not authority.in_gate
                authority.in_gate = True
                authority.events.append(f"gate-enter-{ordinal}")

            def __exit__(self, *args: object) -> None:
                authority.events.append(f"gate-exit-{ordinal}")
                authority.exit_ordinals.append(ordinal)
                authority.in_gate = False
                authority._lock.release()

        return _PausedGate()


@pytest.mark.parametrize("_case_id", ("C51-MONOTONIC-SETTLEMENT",))
def test_c51_monotonic_settlement_and_trusted_evidence_are_fail_closed(
    _case_id: str,
) -> None:
    receipt = _receipt()
    coordinator, authority = _coordinator(receipt=receipt)
    _begin(coordinator, receipt)
    _retire_and_terminal(coordinator, receipt)
    evidence = authority.evidence_authority
    settlement = _settlement(receipt)

    with pytest.raises(_ActivationRejected) as forged:
        coordinator.record_cleanup_settlement(
            settlement,
            witness=object(),
        )
    assert forged.value.reason is _ActivationReason.CLEANUP_DEBT
    first = coordinator.record_cleanup_settlement(
        settlement,
        witness=evidence.tree_witness,
    )
    assert coordinator.record_cleanup_settlement(
        settlement,
        witness=object(),
    ) == first
    coordinator.record_protocol_terminal(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
    )
    coordinator.retire_exact(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
    )
    debt = WorkerCleanupDebtV1(
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
        reason=_CleanupDebtReason.SETTLEMENT_INCOMPLETE,
    )
    with pytest.raises(_ActivationRejected) as late_debt:
        coordinator.record_cleanup_debt(debt)
    assert late_debt.value.reason is _ActivationReason.CLEANUP_SETTLED
    with pytest.raises(_ActivationRejected):
        _transition_attempt({"phase": "settled"}, "cleanup_debt")


@pytest.mark.parametrize("_case_id", ("C51-DURABLE-POLICY-BUDGET",))
def test_c51_restart_budget_and_attempt_policy_are_durable(_case_id: str) -> None:
    receipt = _receipt()
    store = _MemoryActivationStateStore()
    coordinator, authority = _coordinator(
        receipt=receipt,
        store=store,
        restart_budget=2,
    )
    _begin(coordinator, receipt)
    with pytest.raises(ValueError, match="restart budget differs"):
        ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=store,
            restart_budget=3,
        )

    document = store.load()
    assert isinstance(document, dict)
    attempt = next(iter(document["attempts"].values()))  # type: ignore[union-attr]
    assert isinstance(attempt, dict)
    attempt["policyFingerprint"] = _DIGEST_B
    assert store.compare_and_swap(
        expected_revision=document["stateRevision"],  # type: ignore[arg-type]
        document=document,
    )
    with pytest.raises(_ActivationRejected) as mismatch:
        _publish(coordinator, receipt)
    assert mismatch.value.reason is _ActivationReason.INVALID_RECEIPT


@pytest.mark.parametrize("_case_id", ("C51-CAPACITY-PREWRITE",))
def test_c51_capacity_is_rejected_before_an_unreadable_write(
    _case_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_DURABLE_ATTEMPTS", 1)
    receipt = _receipt()
    coordinator, _ = _coordinator(receipt=receipt)
    _begin(coordinator, receipt)
    with pytest.raises(_ActivationRejected) as full:
        _begin(coordinator, receipt, attempt_id=_ATTEMPT_B, owner_generation=2)
    assert full.value.reason is _ActivationReason.CAPACITY_EXHAUSTED
    assert len(coordinator.snapshot()["attempts"]) == 1  # type: ignore[arg-type]


@pytest.mark.parametrize("_case_id", ("C51-KILLSWITCH-DURABLE-RETRY",))
def test_c51_kill_switch_pending_is_durable_and_retryable(_case_id: str) -> None:
    receipt = _receipt()
    store = _MemoryActivationStateStore()
    authority = _FaultingLatchAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    )
    with pytest.raises(RuntimeError, match="authority failure"):
        coordinator.latch_kill_switch(expected_generation=7)
    assert coordinator.snapshot()["killSwitchState"] == "pending"
    with pytest.raises(_ActivationRejected) as closed:
        _begin(coordinator, receipt)
    assert closed.value.reason is _ActivationReason.KILL_SWITCH_LATCHED
    assert coordinator.latch_kill_switch(expected_generation=7) == ()
    assert coordinator.snapshot()["killSwitchState"] == "completed"


@pytest.mark.parametrize("_case_id", ("C51-GATE-RELEASE-IMMEDIATE",))
def test_c51_admission_decision_releases_gate_immediately_and_exit_is_once(
    _case_id: str,
) -> None:
    receipt = _receipt()
    coordinator, authority = _coordinator(receipt=receipt)
    with coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    ) as admission:
        admission.begin_effect()
        assert authority.in_gate is False
        assert _publish(coordinator, receipt)["reason"] == "published"
    assert authority.events.count("gate-exit") == 2


@pytest.mark.parametrize(
    "mode",
    ("normal", "exception", "explicit", "effect-error"),
    ids=(
        "C51-NOEFFECT-NORMAL",
        "C51-NOEFFECT-EXCEPTION",
        "C51-NOEFFECT-EXPLICIT",
        "C51-EFFECT-EXCEPTION",
    ),
)
def test_c51_no_effect_and_effect_exit_matrix(mode: str) -> None:
    receipt = _receipt()
    coordinator, authority = _coordinator(receipt=receipt)
    try:
        with coordinator.admission(
            policy=receipt.policy,
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            host_identity="host-1",
            boot_identity="boot-1",
        ) as admission:
            if mode == "explicit":
                admission.settle_without_effect()
                assert authority.in_gate is False
            elif mode == "effect-error":
                admission.begin_effect()
                raise RuntimeError("after effect")
            elif mode == "exception":
                raise RuntimeError("before effect")
    except RuntimeError:
        assert mode in {"exception", "effect-error"}
    phase = coordinator.snapshot()["attempts"]  # type: ignore[index]
    phase = next(iter(phase.values()))["phase"]  # type: ignore[union-attr,index]
    assert phase == ("effect_started" if mode == "effect-error" else "settled")
    assert authority.events.count("gate-exit") == 1


@pytest.mark.parametrize("_case_id", ("C51-COMMIT-BEFORE-RETURN",))
def test_c51_commit_before_return_preserves_registered_and_effect_state(
    _case_id: str,
) -> None:
    receipt = _receipt()
    store = _CommitThenRaiseStore()
    coordinator, authority = _coordinator(receipt=receipt, store=store)
    store.raise_after_commit = True
    lease = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    with pytest.raises(RuntimeError, match="post-commit"):
        lease.__enter__()
    first_attempt = next(iter(coordinator.snapshot()["attempts"].values()))  # type: ignore[union-attr]
    assert first_attempt["phase"] == "settled"  # type: ignore[index]
    assert coordinator.active_attempts() == ()
    assert authority.in_gate is False

    second = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_B,
        owner_generation=2,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    second.__enter__()
    store.raise_after_commit = True
    with pytest.raises(RuntimeError, match="post-commit"):
        second.begin_effect()
    assert authority.in_gate is False
    assert {item["phase"] for item in coordinator.active_attempts()} == {
        "effect_started",
    }


@pytest.mark.parametrize("_case_id", ("C51-DUAL-COORDINATOR-CAS",))
def test_c51_dual_coordinator_shared_cas_has_one_registration_winner(
    _case_id: str,
) -> None:
    receipt = _receipt()
    store = _RegistrationRaceStore()
    first, _ = _coordinator(
        receipt=receipt,
        store=_RegistrationRaceStoreView(store),
        store_domain_token=store,
    )
    second, _ = _coordinator(
        receipt=receipt,
        store=_RegistrationRaceStoreView(store),
        store_domain_token=store,
    )
    store.race_registration = True
    outcomes: list[str] = []

    def run(coordinator: ProductWorkerActivationCoordinator, attempt_id: str) -> None:
        try:
            _begin(coordinator, receipt, attempt_id=attempt_id)
            outcomes.append("committed")
        except _ActivationRejected as error:
            outcomes.append(error.reason.value)

    threads = [
        threading.Thread(target=run, args=(first, _ATTEMPT_A)),
        threading.Thread(target=run, args=(second, _ATTEMPT_B)),
    ]
    threads[0].start()
    assert store.registration_entered.wait(timeout=2)
    threads[1].start()
    threads[1].join(timeout=2)
    store.registration_release.set()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert sorted(outcomes) == ["committed", "reentrant_call"]
    assert len(first.active_attempts()) == 1


@pytest.mark.parametrize("_case_id", ("C51-PUBLISH-THEN-KILL-RACE",))
def test_c51_publish_then_kill_is_serialized(_case_id: str) -> None:
    receipt = _receipt()
    authority = _BlockingAuthority(receipt)
    store = _MemoryActivationStateStore()
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    )
    latch_coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    )
    _begin(coordinator, receipt)
    authority.block_witness = True
    published: list[object] = []
    latched: list[object] = []
    latch_failures: list[_ActivationReason] = []
    publish_thread = threading.Thread(
        target=lambda: published.append(_publish(coordinator, receipt)),
    )
    def latch_during_callback() -> None:
        try:
            latched.append(
                latch_coordinator.latch_kill_switch(expected_generation=7)
            )
        except _ActivationRejected as error:
            latch_failures.append(error.reason)

    latch_thread = threading.Thread(target=latch_during_callback)
    publish_thread.start()
    assert authority.witness_entered.wait(timeout=2)
    latch_thread.start()
    assert not authority.latch_entered.wait(timeout=0.05)
    authority.release.set()
    publish_thread.join(timeout=3)
    latch_thread.join(timeout=3)
    assert not publish_thread.is_alive() and not latch_thread.is_alive()
    assert published and latched == []
    assert latch_failures == [_ActivationReason.REENTRANT_CALL]

@pytest.mark.parametrize("_case_id", ("C51-KILL-THEN-PUBLISH-RACE",))
def test_c51_kill_then_publish_is_serialized(_case_id: str) -> None:
    receipt = _receipt()
    second_authority = _BlockingAuthority(receipt)
    second_authority.block_latch = True
    second_store = _MemoryActivationStateStore()
    second = ProductWorkerActivationCoordinator(
        authority=second_authority,
        evidence_authority=second_authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=second_store,
    )
    second_publisher = ProductWorkerActivationCoordinator(
        authority=second_authority,
        evidence_authority=second_authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=second_store,
    )
    _begin(second, receipt)
    failures: list[_ActivationReason] = []
    latch_thread = threading.Thread(
        target=lambda: second.latch_kill_switch(expected_generation=7),
    )

    def publish_late() -> None:
        try:
            _publish(second_publisher, receipt)
        except _ActivationRejected as error:
            failures.append(error.reason)

    publish_thread = threading.Thread(target=publish_late)
    latch_thread.start()
    assert second_authority.latch_entered.wait(timeout=2)
    publish_thread.start()
    second_authority.release.set()
    latch_thread.join(timeout=3)
    publish_thread.join(timeout=3)
    assert not latch_thread.is_alive() and not publish_thread.is_alive()
    assert failures == [_ActivationReason.REENTRANT_CALL]


@pytest.mark.parametrize("_case_id", ("C51-DYNAMIC-PORT-REENTRY",))
def test_c51_dynamic_ports_and_callback_reentry_fail_closed(_case_id: str) -> None:
    class _DynamicPort:
        def __getattr__(self, name: str) -> object:
            return lambda *args, **kwargs: None

    with pytest.raises(TypeError, match="static method"):
        ProductWorkerActivationCoordinator(
            authority=_DynamicPort(),  # type: ignore[arg-type]
            evidence_authority=_CleanupEvidenceOwner(_receipt()),
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )

    receipt = _receipt()
    ordinary_authority = _Authority(receipt)
    with pytest.raises(TypeError, match="static method"):
        ProductWorkerActivationCoordinator(
            authority=ordinary_authority,
            evidence_authority=ordinary_authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=_DynamicPort(),
        )
    shadowed_evidence = _CleanupEvidenceOwner(receipt)
    shadowed_evidence.verify_tree_settlement = lambda **kwargs: True  # type: ignore[method-assign]
    with pytest.raises(TypeError, match="static method"):
        ProductWorkerActivationCoordinator(
            authority=ordinary_authority,
            evidence_authority=shadowed_evidence,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )

    authority = _ReentrantAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    authority.coordinator = coordinator
    with pytest.raises(_ActivationRejected) as reentrant:
        _begin(coordinator, receipt)
    assert reentrant.value.reason is _ActivationReason.REENTRANT_CALL
    assert authority.in_gate is False
    assert coordinator.active_attempts() == ()


@pytest.mark.parametrize("_case_id", ("C51-PORT-FAULTS",))
def test_c51_authority_and_store_faults_do_not_admit(_case_id: str) -> None:
    receipt = _receipt()
    authority = _FaultingWitnessAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    with pytest.raises(RuntimeError, match="witness failure"):
        _begin(coordinator, receipt)
    assert authority.in_gate is False
    assert coordinator.active_attempts() == ()

    store_authority = _Authority(receipt)
    with pytest.raises(RuntimeError, match="store failure"):
        ProductWorkerActivationCoordinator(
            authority=store_authority,
            evidence_authority=store_authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=_FaultingLoadStore(),
        )


@pytest.mark.parametrize("_case_id", ("C51-COUNTERFEIT-EVIDENCE",))
def test_c51_counterfeit_evidence_authority_cannot_replace_pinned_owner(
    _case_id: str,
) -> None:
    receipt = _receipt()
    store = _MemoryActivationStateStore()
    coordinator, authority = _coordinator(receipt=receipt, store=store)
    _begin(coordinator, receipt)

    with pytest.raises(ValueError, match="not trusted"):
        ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=_AlwaysTrueEvidenceAuthority(),
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=store,
        )


@pytest.mark.parametrize("_case_id", ("C51-REGISTERED-RECOVERY",))
def test_c51_registered_orphan_recovery_is_exact_idempotent_and_frees_cap(
    _case_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_DURABLE_ATTEMPTS", 1)
    receipt = _receipt()
    store = _OrphaningStore()
    coordinator, authority = _coordinator(receipt=receipt, store=store)
    store.orphan_next_registration = True
    lease = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    with pytest.raises(RuntimeError, match="registration post-commit"):
        lease.__enter__()
    assert coordinator.active_attempts()[0]["phase"] == "registered"

    restarted = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    )
    with pytest.raises(_ActivationRejected):
        restarted.recover_registered_no_effect(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            current_boot_identity="boot-1",
            witness=authority.evidence_authority.registered_witness,
        )
    with pytest.raises(_ActivationRejected):
        restarted.recover_registered_no_effect(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            current_boot_identity="boot-2",
            witness=object(),
        )
    settled = restarted.recover_registered_no_effect(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        current_boot_identity="boot-2",
        witness=authority.evidence_authority.registered_witness,
    )
    assert restarted.recover_registered_no_effect(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        current_boot_identity="boot-2",
        witness=object(),
    ) == settled
    _begin(restarted, receipt, attempt_id=_ATTEMPT_B, owner_generation=2)
    assert restarted.active_attempts()[0]["attemptId"] == _ATTEMPT_B
    assert len(restarted.snapshot()["attempts"]) == 1  # type: ignore[arg-type]
    with pytest.raises(_ActivationRejected) as effect:
        restarted.recover_registered_no_effect(
            receipt=receipt,
            attempt_id=_ATTEMPT_B,
            owner_generation=2,
            current_boot_identity="boot-2",
            witness=authority.evidence_authority.registered_witness,
        )
    assert effect.value.reason is _ActivationReason.PUBLICATION_FENCED


@pytest.mark.parametrize(
    "fault",
    ("pre", "post"),
    ids=("C51-GATE-RELEASE-PREFAULT", "C51-GATE-RELEASE-POSTFAULT"),
)
def test_c51_gate_release_capability_is_retryable_after_ambiguous_fault(
    fault: str,
) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    lease = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    lease.__enter__()
    authority.release_failure = fault
    with pytest.raises(RuntimeError, match=f"{fault}-release failure"):
        lease.begin_effect()
    assert authority.in_gate is (fault == "pre")
    lease.retry_release()
    lease.retry_release()
    assert authority.in_gate is False
    assert authority.release_calls == 2
    assert coordinator.active_attempts()[0]["phase"] == "effect_started"


@pytest.mark.parametrize(
    "callback_owner",
    ("authority", "store", "evidence"),
    ids=(
        "C51-CROSS-THREAD-AUTHORITY-REENTRY",
        "C51-CROSS-THREAD-STORE-REENTRY",
        "C51-CROSS-THREAD-EVIDENCE-REENTRY",
    ),
)
def test_c51_external_callback_spawn_join_reentry_fails_without_deadlock(
    callback_owner: str,
) -> None:
    receipt = _receipt()
    if callback_owner == "authority":
        authority = _SpawnJoinAuthority(receipt)
        coordinator = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        authority.coordinator = coordinator
        _begin(coordinator, receipt)
        observed = authority.observed
    elif callback_owner == "store":
        authority = _Authority(receipt)
        store = _SpawnJoinStore()
        coordinator = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=store,
        )
        store.coordinator = coordinator
        _begin(coordinator, receipt)
        observed = store.observed
    else:
        authority = _Authority(receipt)
        evidence = _SpawnJoinEvidenceAuthority(receipt)
        coordinator = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=evidence,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        evidence.coordinator = coordinator
        _begin(coordinator, receipt)
        _retire_and_terminal(coordinator, receipt)
        coordinator.record_cleanup_settlement(
            _settlement(receipt),
            witness=evidence.tree_witness,
        )
        observed = evidence.observed
    assert observed
    assert set(observed) == {_ActivationReason.REENTRANT_CALL}


@pytest.mark.parametrize("_case_id", ("C51-RELEASE-DEBT-PUBLISH",))
def test_c51_serialized_publish_release_debt_is_retained_and_drainable(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    _begin(coordinator, receipt)
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="pre-release failure"):
        _publish(coordinator, receipt)
    assert authority.in_gate is True
    assert _pending_release_count(coordinator) == 1
    assert coordinator.snapshot()["publications"]
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="pre-release failure"):
        coordinator.retire_exact(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
        )
    assert authority.in_gate is True
    assert _pending_release_count(coordinator) == 1
    coordinator.retry_pending_releases()
    assert authority.in_gate is False
    assert _pending_release_count(coordinator) == 0


@pytest.mark.parametrize(
    "failure",
    ("validation", "cas"),
    ids=(
        "C51-RELEASE-DEBT-ADMISSION-VALIDATION",
        "C51-RELEASE-DEBT-ADMISSION-CAS",
    ),
)
def test_c51_failed_admission_retains_inline_release_debt(failure: str) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    store = _RejectRegistrationStore() if failure == "cas" else None
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    )
    if failure == "validation":
        authority.witness = (*receipt.authority_witness[:-1], 99)
    lease = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="pre-release failure"):
        lease.__enter__()
    assert lease._key is None or failure == "cas"
    assert authority.in_gate is True
    assert _pending_release_count(coordinator) == 1
    coordinator.retry_pending_releases()
    assert _pending_release_count(coordinator) == 0
    assert authority.in_gate is False


@pytest.mark.parametrize("_case_id", ("C51-RELEASE-DEBT-DRAIN-JOIN",))
def test_c51_concurrent_release_debt_drains_join_once(_case_id: str) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    lease = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    lease.__enter__()
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="pre-release failure"):
        lease.begin_effect()
    start = threading.Barrier(3)
    errors: list[BaseException] = []

    def drain() -> None:
        start.wait(timeout=2)
        try:
            coordinator.retry_pending_releases()
        except BaseException as error:  # pragma: no cover - asserted empty
            errors.append(error)

    workers = [threading.Thread(target=drain) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait(timeout=2)
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert errors == []
    assert _pending_release_count(coordinator) == 0
    assert authority.release_calls == 2


@pytest.mark.parametrize(
    "shared_owner",
    ("authority", "store", "evidence"),
    ids=(
        "C51-SHARED-AUTHORITY-DOMAIN",
        "C51-SHARED-STORE-DOMAIN",
        "C51-SHARED-EVIDENCE-DOMAIN",
    ),
)
def test_c51_callback_gate_spans_coordinators_sharing_owner(shared_owner: str) -> None:
    receipt = _receipt()
    if shared_owner == "authority":
        authority = _SpawnJoinAuthority(receipt)
        first = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        second = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        authority.coordinator = second
        _begin(first, receipt)
        observed = authority.observed
    elif shared_owner == "store":
        authority_one = _Authority(receipt)
        authority_two = _Authority(receipt)
        store = _SpawnJoinStore()
        first = ProductWorkerActivationCoordinator(
            authority=authority_one,
            evidence_authority=authority_one.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=store,
        )
        second = ProductWorkerActivationCoordinator(
            authority=authority_two,
            evidence_authority=authority_two.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            state_store=store,
        )
        store.coordinator = second
        _begin(first, receipt)
        observed = store.observed
    else:
        evidence = _SpawnJoinEvidenceAuthority(receipt)
        authority_one = _Authority(receipt)
        authority_two = _Authority(receipt)
        first = ProductWorkerActivationCoordinator(
            authority=authority_one,
            evidence_authority=evidence,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        second = ProductWorkerActivationCoordinator(
            authority=authority_two,
            evidence_authority=evidence,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        evidence.coordinator = second
        _begin(first, receipt)
        _retire_and_terminal(first, receipt)
        first.record_cleanup_settlement(
            _settlement(receipt),
            witness=evidence.tree_witness,
        )
        observed = evidence.observed
    assert observed
    assert set(observed) == {_ActivationReason.REENTRANT_CALL}


@pytest.mark.parametrize("_case_id", ("C51-DISJOINT-OWNER-PARALLEL",))
def test_c51_callback_domains_do_not_serialize_disjoint_owners(_case_id: str) -> None:
    receipt = _receipt()
    barrier = threading.Barrier(2)
    authorities = [
        _ParallelWitnessAuthority(receipt, barrier),
        _ParallelWitnessAuthority(receipt, barrier),
    ]
    coordinators = [
        ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        )
        for authority in authorities
    ]
    errors: list[BaseException] = []

    def activate(index: int) -> None:
        try:
            _begin(coordinators[index], receipt)
        except BaseException as error:  # pragma: no cover - asserted empty
            errors.append(error)

    workers = [threading.Thread(target=activate, args=(index,)) for index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert errors == []


@pytest.mark.parametrize("_case_id", ("C51-SHARED-RELEASE-DEBT-DRAIN",))
def test_c51_shared_authority_domain_drains_release_debt_cross_coordinator(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    first = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    second = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    _begin(first, receipt)
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="pre-release failure"):
        _publish(first, receipt)
    assert _pending_release_count(first) == _pending_release_count(second) == 1
    second.latch_kill_switch(expected_generation=7)
    assert _pending_release_count(first) == _pending_release_count(second) == 0
    assert authority.in_gate is False


@pytest.mark.parametrize("_case_id", ("C51-CROSS-OWNER-CALLBACK-FENCE",))
def test_c51_store_callback_marks_all_domains_before_cross_owner_reentry(
    _case_id: str,
) -> None:
    receipt = _receipt()
    shared_authority = _Authority(receipt)
    store = _SpawnJoinStore()
    first = ProductWorkerActivationCoordinator(
        authority=shared_authority,
        evidence_authority=shared_authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    )
    second_evidence = _CleanupEvidenceOwner(receipt)
    second = ProductWorkerActivationCoordinator(
        authority=shared_authority,
        evidence_authority=second_evidence,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    store.coordinator = second
    first.snapshot()
    assert store.observed == [_ActivationReason.REENTRANT_CALL]


@pytest.mark.parametrize("_case_id", ("C51-SHARED-DOMAIN-WRAPPERS",))
def test_c51_store_wrappers_over_one_backend_share_explicit_domain(
    _case_id: str,
) -> None:
    receipt = _receipt()
    backend = _RegistrationRaceStore()
    first, _ = _coordinator(
        receipt=receipt,
        store=_RegistrationRaceStoreView(backend),
        store_domain_token=backend,
    )
    second, _ = _coordinator(
        receipt=receipt,
        store=_RegistrationRaceStoreView(backend),
        store_domain_token=backend,
    )
    assert first._store.callback_domain is second._store.callback_domain


@pytest.mark.parametrize("_case_id", ("C51-DOMAIN-TOKEN-WEAKREF",))
def test_c51_domain_tokens_are_weak_and_unweakrefable_tokens_are_rejected(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _Authority(receipt)
    token = _DomainToken()
    token_id = id(token)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        _authority_domain_token=token,
    )
    assert token_id in activation_module._CALLBACK_DOMAINS
    assert coordinator.snapshot()["stateVersion"] == 2
    del token
    gc.collect()
    assert token_id in activation_module._CALLBACK_DOMAINS
    del coordinator
    gc.collect()
    assert token_id not in activation_module._CALLBACK_DOMAINS
    with pytest.raises(TypeError, match="weak-referenceable"):
        ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=authority.evidence_authority,
            trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
            trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
            _authority_domain_token=object(),
        )


@pytest.mark.parametrize("_case_id", ("C51-ENTER-AMBIGUITY-CLEANUP",))
def test_c51_gate_exit_is_registered_before_post_acquire_enter_error(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _EnterAfterAcquireFaultAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    lease = coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="post-acquire enter failure"):
        lease.__enter__()
    assert authority.in_gate is True
    assert authority.release_calls == 1
    assert _pending_release_count(coordinator) == 1
    coordinator.retry_pending_releases()
    assert authority.in_gate is False
    assert authority.release_calls == 2
    assert _pending_release_count(coordinator) == 0


@pytest.mark.parametrize("_case_id", ("C51-EXIT-CALLBACK-DRAIN-REENTRY",))
def test_c51_exit_callback_spawn_join_drain_fails_before_release_lock(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _ExitSpawnJoinAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    authority.coordinator = coordinator
    _begin(coordinator, receipt)
    assert authority.observed == [_ActivationReason.REENTRANT_CALL]
    assert _pending_release_count(coordinator) == 0


@pytest.mark.parametrize(
    "_case_id",
    ("C51-SHARED-EXIT-CALLBACK-RETRY-REJECT",),
)
def test_c51_exit_callback_spawn_join_peer_retry_fails_fast(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _ExitSpawnJoinAuthority(receipt)
    first = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    second = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    authority.coordinator = second
    _begin(first, receipt)
    assert authority.observed == [_ActivationReason.REENTRANT_CALL]
    assert _pending_release_count(first) == 0


@pytest.mark.parametrize(
    "fault",
    ("pre", "post"),
    ids=("C51-RETIRE-RELEASE-PREFAULT", "C51-RETIRE-RELEASE-POSTFAULT"),
)
def test_c51_retire_cas_retains_release_debt_across_exit_fault(fault: str) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    _begin(coordinator, receipt)
    _publish(coordinator, receipt)
    coordinator.record_protocol_terminal(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
    )
    authority.release_failure = fault
    with pytest.raises(RuntimeError, match=f"{fault}-release failure"):
        coordinator.retire_exact(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
        )
    attempt = coordinator.snapshot()["attempts"]
    assert next(iter(attempt.values()))["domainRetired"] is True  # type: ignore[union-attr]
    assert _pending_release_count(coordinator) == 1
    coordinator.retry_pending_releases()
    assert _pending_release_count(coordinator) == 0


@pytest.mark.parametrize(
    "fault",
    ("pre", "post"),
    ids=("C51-LATCH-RELEASE-PREFAULT", "C51-LATCH-RELEASE-POSTFAULT"),
)
def test_c51_latch_cas_retains_release_debt_across_exit_fault(fault: str) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    coordinator = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    authority.release_failure = fault
    with pytest.raises(RuntimeError, match=f"{fault}-release failure"):
        coordinator.latch_kill_switch(expected_generation=7)
    assert coordinator.snapshot()["killSwitchState"] == "completed"
    assert _pending_release_count(coordinator) == 1
    coordinator.retry_pending_releases()
    assert _pending_release_count(coordinator) == 0


@pytest.mark.parametrize("_case_id", ("C51-HELD-GATE-NO-EARLY-RELEASE",))
def test_c51_shared_authority_waiter_never_releases_live_held_gate(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _Authority(receipt)
    shared_token = _DomainToken()
    first = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        _authority_domain_token=shared_token,
    )
    second = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        _authority_domain_token=shared_token,
    )
    first_held = threading.Event()
    allow_first_release = threading.Event()
    errors: list[BaseException] = []

    def run_first() -> None:
        try:
            lease = first.admission(
                policy=receipt.policy,
                receipt=receipt,
                attempt_id=_ATTEMPT_A,
                owner_generation=1,
                host_identity="host-1",
                boot_identity="boot-1",
            )
            lease.__enter__()
            first_held.set()
            assert allow_first_release.wait(timeout=2)
            lease.begin_effect()
        except BaseException as error:  # pragma: no cover - asserted empty
            errors.append(error)

    def run_second() -> None:
        try:
            _begin(second, receipt, attempt_id=_ATTEMPT_B, owner_generation=2)
        except BaseException as error:  # pragma: no cover - asserted empty
            errors.append(error)

    first_thread = threading.Thread(target=run_first)
    second_thread = threading.Thread(target=run_second)
    first_thread.start()
    assert first_held.wait(timeout=2)
    second_thread.start()
    domain = first._authority.callback_domain
    with domain.release_condition:
        assert domain.release_condition.wait_for(
            lambda: len(domain.pending_releases) == 2,
            timeout=2,
        )
        assert sorted(item.phase for item in domain.pending_releases.values()) == [
            "held",
            "reserved",
        ]
    assert authority.events == ["gate-enter", "witness"]
    allow_first_release.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)
    assert not first_thread.is_alive() and not second_thread.is_alive()
    assert errors == []
    assert authority.events == [
        "gate-enter",
        "witness",
        "gate-exit",
        "gate-enter",
        "witness",
        "gate-exit",
    ]
    assert _pending_release_count(first) == 0


@pytest.mark.parametrize("_case_id", ("C51-RESERVED-GATE-NO-DRAIN",))
def test_c51_reserved_preenter_gate_is_not_drained_by_peer(
    _case_id: str,
) -> None:
    receipt = _receipt()
    authority = _PauseFirstEnterAuthority(receipt)
    first = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    second = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    errors: list[BaseException] = []

    def reserve_first() -> None:
        try:
            _begin(first, receipt)
        except BaseException as error:  # pragma: no cover - asserted empty
            errors.append(error)

    first_thread = threading.Thread(target=reserve_first)
    first_thread.start()
    assert authority.first_enter_called.wait(timeout=2)
    domain = first._authority.callback_domain
    with domain.release_condition:
        assert [item.phase for item in domain.pending_releases.values()] == [
            "reserved"
        ]
    second.retry_pending_releases()
    assert authority.exit_ordinals == []
    _begin(second, receipt, attempt_id=_ATTEMPT_B, owner_generation=2)
    assert authority.exit_ordinals == [2]
    with domain.release_condition:
        assert [item.phase for item in domain.pending_releases.values()] == [
            "reserved"
        ]
    authority.allow_first_enter.set()
    first_thread.join(timeout=2)
    assert not first_thread.is_alive()
    assert errors == []
    assert authority.exit_ordinals == [2, 1]
    assert _pending_release_count(first) == 0


@pytest.mark.parametrize(
    "release_fault",
    (False, True),
    ids=("C51-RELEASING-RETRY-FAILFAST", "C51-RELEASE-FAULT-RETRY-TAKEOVER"),
)
def test_c51_foreign_retry_fails_fast_while_releasing_then_retries(
    release_fault: bool,
) -> None:
    receipt = _receipt()
    authority = _FaultingGateAuthority(receipt)
    first = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    second = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
    )
    lease = first.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
    )
    lease.__enter__()
    authority.release_failure = "pre"
    with pytest.raises(RuntimeError, match="pre-release failure"):
        lease.begin_effect()
    assert _pending_release_count(first) == 1

    authority.block_release = True
    authority.release_entered.clear()
    authority.allow_release.clear()
    if release_fault:
        authority.release_failure = "pre"
    first_errors: list[BaseException] = []
    second_errors: list[BaseException] = []
    second_done = threading.Event()

    def first_retry() -> None:
        try:
            first.retry_pending_releases()
        except BaseException as error:
            first_errors.append(error)

    def second_retry() -> None:
        try:
            second.retry_pending_releases()
        except BaseException as error:  # pragma: no cover - asserted empty
            second_errors.append(error)
        finally:
            second_done.set()

    first_thread = threading.Thread(target=first_retry)
    second_thread = threading.Thread(target=second_retry)
    first_thread.start()
    assert authority.release_entered.wait(timeout=2)
    second_thread.start()
    assert second_done.wait(timeout=0.5)
    with first._authority.callback_domain.release_condition:
        pending = next(
            iter(first._authority.callback_domain.pending_releases.values())
        )
        assert pending.phase == "releasing"
    authority.allow_release.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)
    assert not first_thread.is_alive() and not second_thread.is_alive()
    if release_fault:
        assert len(first_errors) == 1
        assert isinstance(first_errors[0], RuntimeError)
    else:
        assert first_errors == []
    assert len(second_errors) == 1
    assert isinstance(second_errors[0], _ActivationRejected)
    assert second_errors[0].reason is _ActivationReason.REENTRANT_CALL
    second.retry_pending_releases()
    assert _pending_release_count(first) == 0
    assert authority.in_gate is False
    _begin(second, receipt, attempt_id=_ATTEMPT_B, owner_generation=2)


def test_cleanup_v2_requires_independent_tree_and_native_evidence() -> None:
    receipt = _receipt()
    coordinator, authority = _coordinator(receipt=receipt)
    _begin(coordinator, receipt, cleanup_contract_version=2)
    _retire_and_terminal(coordinator, receipt)
    settlement = WorkerCleanupSettlementV2(
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
        protocol_terminal=True,
        domain_retired=True,
        tree_settled=True,
        native_containment_settled=True,
    )
    evidence = authority.evidence_authority

    with pytest.raises(_ActivationRejected) as missing:
        coordinator.record_cleanup_settlement(
            settlement,
            witness=evidence.tree_witness,
        )
    assert missing.value.reason is _ActivationReason.CLEANUP_DEBT
    with pytest.raises(_ActivationRejected) as legacy:
        coordinator.record_cleanup_settlement(
            WorkerCleanupSettlementV1(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=_ATTEMPT_A,
                owner_generation=1,
                host_identity="host-1",
                boot_identity="boot-1",
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
            ),
            witness=evidence.tree_witness,
        )
    assert legacy.value.reason is _ActivationReason.INVALID_RECEIPT

    status = coordinator.record_cleanup_settlement(
        settlement,
        witness=evidence.tree_witness,
        native_containment_witness=evidence.native_containment_witness,
    )
    assert status["reason"] == "cleanup_settled"
    attempt = next(iter(coordinator.snapshot()["attempts"].values()))
    assert attempt["cleanupContractVersion"] == 2
    assert attempt["cleanupSettlement"]["nativeContainmentSettled"] is True


@pytest.mark.parametrize(
    ("tree_unknown", "native_unknown", "reason"),
    (
        (True, False, _CleanupDebtReasonV2.PROCESS_TREE_UNKNOWN),
        (False, True, _CleanupDebtReasonV2.NATIVE_CONTAINMENT_UNKNOWN),
        (True, True, _CleanupDebtReasonV2.TREE_AND_NATIVE_CONTAINMENT_UNKNOWN),
    ),
)
def test_cleanup_v2_debt_distinguishes_unsettled_edges(
    tree_unknown: bool,
    native_unknown: bool,
    reason: _CleanupDebtReasonV2,
) -> None:
    receipt = _receipt()
    debt = WorkerCleanupDebtV2(
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
        process_tree_unknown=tree_unknown,
        native_containment_unknown=native_unknown,
        reason=reason,
    )
    assert WorkerCleanupDebtV2.from_dict(debt.to_dict()) == debt


def test_cleanup_v2_changed_boot_still_requires_native_settlement() -> None:
    receipt = _receipt()
    coordinator, authority = _coordinator(receipt=receipt)
    _begin(coordinator, receipt, cleanup_contract_version=2)
    _retire_and_terminal(coordinator, receipt)
    coordinator.record_cleanup_debt(
        WorkerCleanupDebtV2(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            host_identity="host-1",
            boot_identity="boot-1",
            process_tree_unknown=True,
            native_containment_unknown=True,
            reason=_CleanupDebtReasonV2.TREE_AND_NATIVE_CONTAINMENT_UNKNOWN,
        )
    )
    evidence = authority.evidence_authority
    with pytest.raises(_ActivationRejected) as missing:
        coordinator.settle_changed_boot_absence(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            current_boot_identity="boot-2",
            witness=evidence.changed_boot_witness,
        )
    assert missing.value.reason is _ActivationReason.CLEANUP_DEBT

    status = coordinator.settle_changed_boot_absence(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        current_boot_identity="boot-2",
        witness=evidence.changed_boot_witness,
        native_containment_witness=evidence.native_containment_witness,
    )
    assert status["reason"] == "cleanup_settled"
    attempt = next(iter(coordinator.snapshot()["attempts"].values()))
    assert attempt["cleanupSettlement"]["settlementVersion"] == 2


def test_activation_state_v1_migrates_losslessly_to_cleanup_contract_v1() -> None:
    receipt = _receipt()
    store = _MemoryActivationStateStore()
    coordinator, authority = _coordinator(receipt=receipt, store=store)
    _begin(coordinator, receipt)
    legacy = json.loads(json.dumps(coordinator.snapshot()))
    legacy["stateVersion"] = 1
    for attempt in legacy["attempts"].values():
        del attempt["cleanupContractVersion"]
    store._document = legacy

    migrated = ProductWorkerActivationCoordinator(
        authority=authority,
        evidence_authority=authority.evidence_authority,
        trusted_evidence_authority_id=_EVIDENCE_AUTHORITY_ID,
        trusted_evidence_authority_fingerprint=_EVIDENCE_AUTHORITY_FINGERPRINT,
        state_store=store,
    ).snapshot()
    assert migrated["stateVersion"] == 2
    attempt = next(iter(migrated["attempts"].values()))
    assert attempt["cleanupContractVersion"] == 1


def test_cleanup_v2_no_effect_settles_without_native_side_effect_evidence() -> None:
    receipt = _receipt()
    coordinator, _ = _coordinator(receipt=receipt)
    with coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
        cleanup_contract_version=2,
    ):
        pass
    attempt = next(iter(coordinator.snapshot()["attempts"].values()))
    assert attempt["phase"] == "settled"
    assert attempt["cleanupSettlement"]["settlementVersion"] == 2
    assert attempt["cleanupSettlement"]["nativeContainmentSettled"] is True
