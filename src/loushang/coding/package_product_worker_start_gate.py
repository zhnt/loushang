"""Product custody for one durable, identity-bound Linux Worker start gate.

The caller must keep this owner alive until Hosting returns an exact gated
child lease. A failed release closes the gate and leaves a conservative debt.
"""

from __future__ import annotations

import os
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker._native_profile_bridge import _require_exact_binding
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.gated_start import WorkerGatedStartWitnessV1
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_start_gate_journal import CodingWorkerStartGateJournal


class CodingWorkerStartGateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingProductWorkerStartGate:
    """Single-use Product-held write authority for an exact gated H6 child."""

    def __init__(
        self,
        *,
        receipt_owner: CodingWorkerProductReceiptOwner,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        attempt_id: str,
    ) -> None:
        if not isinstance(receipt_owner, CodingWorkerProductReceiptOwner):
            raise TypeError("Coding Worker receipt owner is required")
        _require_exact_binding(receipt=receipt, worker_request=worker_request)
        if attempt_id != worker_request.identity.attempt_id:
            raise CodingWorkerStartGateError("coding_worker_start_gate_attempt_mismatch")
        product = receipt_owner.product_owner
        self._read_fd = -1
        self._write_fd = -1
        self._released = False
        self._receipt_owner = receipt_owner
        self._receipt = receipt
        self._worker_identity_fingerprint = worker_request.identity.fingerprint
        self._attempt_id = attempt_id
        self._journal = CodingWorkerStartGateJournal(product)
        with product.gc_gate.guard(require_write=True):
            self._recheck()
            self._native_closure_digest = self._current_closure_digest()
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
            self._read_fd, self._write_fd = read_fd, write_fd
            try:
                os.set_blocking(write_fd, False)
                self._journal.append(
                    phase="intent",
                    attempt_id=attempt_id,
                    worker_identity_fingerprint=self._worker_identity_fingerprint,
                    receipt_fingerprint=receipt.fingerprint,
                    policy_fingerprint=receipt.policy.fingerprint,
                    scope_id=receipt.policy.product_scope_id,
                    native_closure_digest=self._native_closure_digest,
                )
            except BaseException:
                self.close()
                raise

    @property
    def start_gate_read_fd(self) -> int:
        if self._read_fd < 0 or self._write_fd < 0 or self._released:
            raise CodingWorkerStartGateError("coding_worker_start_gate_closed")
        return self._read_fd

    @property
    def receipt_owner(self) -> CodingWorkerProductReceiptOwner:
        return self._receipt_owner

    @property
    def receipt_fingerprint(self) -> str:
        return self._receipt.fingerprint

    @property
    def worker_identity_fingerprint(self) -> str:
        return self._worker_identity_fingerprint

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    def release(self, witness: WorkerGatedStartWitnessV1) -> None:
        """Persist exact native identity before allowing the captured child to exec."""

        if self._read_fd < 0 or self._write_fd < 0 or self._released:
            raise CodingWorkerStartGateError("coding_worker_start_gate_closed")
        try:
            with self._receipt_owner.product_owner.gc_gate.guard(
                require_write=True
            ):
                self._recheck()
                if self._current_closure_digest() != self._native_closure_digest:
                    raise CodingWorkerStartGateError(
                        "coding_worker_start_gate_native_closure_changed"
                    )
                if type(witness) is not WorkerGatedStartWitnessV1:
                    raise CodingWorkerStartGateError(
                        "coding_worker_start_gate_witness_invalid"
                    )
                gate = os.fstat(self._read_fd)
                if (witness.gate_device, witness.gate_inode) != (
                    gate.st_dev,
                    gate.st_ino,
                ):
                    raise CodingWorkerStartGateError(
                        "coding_worker_start_gate_child_mismatch"
                    )
                self._journal.append(
                    phase="bound",
                    attempt_id=self._attempt_id,
                    worker_identity_fingerprint=self._worker_identity_fingerprint,
                    receipt_fingerprint=self._receipt.fingerprint,
                    policy_fingerprint=self._receipt.policy.fingerprint,
                    scope_id=self._receipt.policy.product_scope_id,
                    native_closure_digest=self._native_closure_digest,
                    identity=witness.native_identity,
                )
                if os.write(self._write_fd, b"S") != 1:
                    raise CodingWorkerStartGateError(
                        "coding_worker_start_gate_release_failed"
                    )
                self._released = True
        finally:
            self.close()

    def close(self) -> None:
        for name in ("_write_fd", "_read_fd"):
            descriptor = getattr(self, name, -1)
            if descriptor >= 0:
                setattr(self, name, -1)
                os.close(descriptor)

    def _recheck(self) -> None:
        if self._receipt_owner.current_witness(self._receipt) != (
            self._receipt.authority_witness
        ):
            raise CodingWorkerStartGateError("coding_worker_start_gate_receipt_stale")

    def _current_closure_digest(self) -> str:
        material = self._receipt_owner.current_native_launch_material(self._receipt)
        return sha256(canonical_json_bytes(material.closure.to_dict())).hexdigest()


__all__ = ["CodingProductWorkerStartGate", "CodingWorkerStartGateError"]
