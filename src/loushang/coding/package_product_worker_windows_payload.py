"""Product-owned Windows Worker PE materialization for one retained attempt.

The stage and marker are durable debt. This module neither starts a Worker nor
deletes a stage; native Job, Supervisor, and Package lease settlement must be
joined by a separate recovery owner before retirement is possible.
"""

from __future__ import annotations

import os
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from hashlib import sha256
from weakref import WeakKeyDictionary

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product._worker_windows_attempt import (
    verify_windows_product_worker_live_stage,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import WorkerSupervisorJournalError
from loushang.harness.worker.payload._selected_payload import (
    worker_identity_from_receipt,
)
from loushang.harness.worker.payload._windows_stage_io import (
    create_windows_payload_stage,
    require_payload_root,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .package_product_worker_receipt import CodingWorkerReceiptError
from .package_product_worker_windows_installed_backend import (
    CodingWindowsWorkerInstalledBackendError,
)
from .package_product_worker_windows_payload_inventory import (
    CodingWindowsWorkerPayloadInventoryError,
    inspect_windows_worker_payload_stages,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningStateJournalError,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAdmissionError,
    _current_after_verified_retirements_under_gc_guard,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
    require_coding_windows_worker_current_attempt,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_RETAINED_ATTEMPTS = 1024
_MARKER = "worker-payload.json"
_BOUND_REQUESTS_LOCK = threading.Lock()
_BOUND_REQUESTS: WeakKeyDictionary[
    Callable[[], None], tuple[int, str, str, tuple[int, int]]
] = WeakKeyDictionary()


class CodingWindowsWorkerPayloadMaterializationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPayloadLeaseV1:
    """Physical input only; it grants no Worker start or recovery authority."""

    attempt_id: str
    runtime: WorkerRuntimeBindingV1
    receipt_fingerprint: str
    payload_digest: str
    owner_id: str
    stage_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class CodingWindowsProductWorkerPendingLaunchV1:
    """Product-checked identity held before Windows payload materialization."""

    receipt_fingerprint: str
    identity: WorkerLaunchIdentityV1

    def __post_init__(self) -> None:
        if (
            type(self.receipt_fingerprint) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.receipt_fingerprint) is None
            or type(self.identity) is not WorkerLaunchIdentityV1
        ):
            raise ValueError("Windows Worker pending launch identity is invalid")


def plan_coding_windows_product_worker_pending_launch(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
) -> CodingWindowsProductWorkerPendingLaunchV1:
    """Pin a current Windows Worker identity before any payload or process."""

    if (
        os.name != "nt"
        or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker pending launch request is invalid")
    product = receipt_owner.product_owner
    with product.gc_gate.guard():
        if receipt_owner.current_witness(receipt) != receipt.authority_witness:
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_selection_stale"
            )
        selected, owner_id = receipt_owner.current_payload_and_worker_owner_id(receipt)
        if (
            selected.configuration.fingerprint
            != receipt.policy.worker_configuration_fingerprint
        ):
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_selection_stale"
            )
        receipt_owner.current_backend_capture_expectation(receipt)
        if any(
            item.attempt_id == attempt_id
            for item in _inspect_windows_worker_recovery_inventory_under_gc_guard(
                product
            )
        ):
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_attempt_reused"
            )
        identity = _windows_worker_identity(
            receipt=receipt,
            owner_id=owner_id,
            attempt_id=attempt_id,
            supervisor_epoch=1,
            session_nonce=secrets.token_hex(32),
        )
        journal = open_coding_windows_product_worker_supervisor_journal(product)
        if journal.status(attempt_id) is not None:
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_attempt_reused"
            )
        epoch = journal.next_supervisor_epoch(identity)
        product.assert_root_gc_authority_current()
        return CodingWindowsProductWorkerPendingLaunchV1(
            receipt_fingerprint=receipt.fingerprint,
            identity=replace(identity, supervisor_epoch=epoch),
        )


def materialize_coding_windows_product_worker_payload(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
) -> CodingWindowsWorkerPayloadLeaseV1:
    """Copy one current selected PE to a fresh, Product-private attempt stage.

    A failure after directory creation deliberately leaves all bytes in place
    as recovery debt. Retrying the same attempt ID never overwrites them.
    """
    if (
        os.name != "nt"
        or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or (type(attempt_id) is not str)
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError("Windows Worker payload request is invalid")
    product = receipt_owner.product_owner
    stage_name = "worker-payload-" + attempt_id
    with product.gc_gate.guard(require_write=True):
        product.assert_root_gc_authority_current()
        payload, owner_id = receipt_owner.current_payload_and_worker_owner_id(receipt)
        if (
            not 0 < len(payload.body) <= _MAX_PAYLOAD_BYTES
            or sha256(payload.body).hexdigest() != payload.digest
        ):
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_digest_changed"
            )
        entrypoint = canonical_plugin_relative_path(
            payload.configuration.entrypoint
        ).as_posix()
        parts = entrypoint.split("/")
        if entrypoint != payload.configuration.entrypoint or _MARKER in parts:
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_entrypoint_invalid"
            )
        retained = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
        previous = next(
            (item for item in retained if item.attempt_id == attempt_id), None
        )
        if previous is not None:
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_attempt_reused"
                if previous.payload_directory_identity is None
                or previous.native_phase is not None
                or previous.supervisor_phase is not None
                or (previous.launch_request_fingerprint is not None)
                else "coding_worker_payload_attempt_debt"
            )
        if len(retained) >= _MAX_RETAINED_ATTEMPTS:
            raise CodingWindowsWorkerPayloadMaterializationError(
                "coding_worker_payload_capacity"
            )
        with WindowsPrivateDirectoryAcl() as acl:
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                acl.validate(root)
                _require_root(product.state_root, root)
                inventory = inspect_windows_worker_payload_stages(
                    product.state_root, directory_fd=root
                )
                if any((item.attempt_id == attempt_id for item in inventory)):
                    raise CodingWindowsWorkerPayloadMaterializationError(
                        "coding_worker_payload_attempt_debt"
                    )
                if len(inventory) >= _MAX_RETAINED_ATTEMPTS:
                    raise CodingWindowsWorkerPayloadMaterializationError(
                        "coding_worker_payload_capacity"
                    )

                def complete(
                    runtime: WorkerRuntimeBindingV1, stage_identity: tuple[int, int]
                ) -> CodingWindowsWorkerPayloadLeaseV1:
                    if (
                        receipt_owner.current_witness(receipt)
                        != receipt.authority_witness
                    ):
                        raise CodingWindowsWorkerPayloadMaterializationError(
                            "coding_worker_payload_selection_stale"
                        )
                    product.assert_root_gc_authority_current()
                    return CodingWindowsWorkerPayloadLeaseV1(
                        attempt_id=attempt_id,
                        runtime=runtime,
                        receipt_fingerprint=receipt.fingerprint,
                        payload_digest=payload.digest,
                        owner_id=owner_id,
                        stage_identity=stage_identity,
                    )

                return create_windows_payload_stage(
                    root=root,
                    acl=acl,
                    root_path=lambda: product.state_root,
                    stage_name=stage_name,
                    parts=parts,
                    entrypoint=entrypoint,
                    body=payload.body,
                    configuration=payload.configuration,
                    attempt_id=attempt_id,
                    owner_id=owner_id,
                    payload_digest=payload.digest,
                    receipt_fingerprint=receipt.fingerprint,
                    marker_name=_MARKER,
                    complete=complete,
                    error_type=CodingWindowsWorkerPayloadMaterializationError,
                    error_prefix="coding_worker_payload",
                )


_windows_worker_identity = worker_identity_from_receipt


def bind_coding_windows_product_worker_launch_request(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
    supervisor_epoch: int,
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1 | None = None,
) -> ManagedWorkerLaunchRequestV1:
    """Build an exact request for a staged PE; no process effect occurs here."""

    if (
        os.name != "nt"
        or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or type(payload_lease) is not CodingWindowsWorkerPayloadLeaseV1
        or type(supervisor_epoch) is not int
        or supervisor_epoch < 1
        or payload_lease.receipt_fingerprint != receipt.fingerprint
        or payload_lease.runtime.package_root
        != receipt_owner.product_owner.state_root
        / ("worker-payload-" + payload_lease.attempt_id)
    ):
        raise CodingWindowsWorkerPayloadMaterializationError(
            "coding_worker_payload_binding_mismatch"
        )
    product = receipt_owner.product_owner
    bound_request: ManagedWorkerLaunchRequestV1 | None = None

    def verify_current(*, initial: bool) -> None:
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            if initial != (bound_request is None):
                raise CodingWindowsWorkerPayloadMaterializationError(
                    "coding_worker_payload_binding_mismatch"
                )
            inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(
                product
            )
            try:
                inventory = _current_after_verified_retirements_under_gc_guard(
                    product, inventory, attempt_id=payload_lease.attempt_id
                )
                require_coding_windows_worker_current_attempt(
                    inventory,
                    attempt_id=payload_lease.attempt_id,
                    payload_directory_identity=payload_lease.stage_identity,
                    initial=initial,
                    request_fingerprint=(
                        None if bound_request is None else bound_request.fingerprint
                    ),
                    receipt_fingerprint=(None if initial else receipt.fingerprint),
                    identity_fingerprint=(
                        None
                        if bound_request is None
                        else bound_request.identity.fingerprint
                    ),
                )
            except CodingWindowsWorkerRecoveryAdmissionError as exc:
                raise CodingWindowsWorkerPayloadMaterializationError(exc.code) from exc
            selected, owner_id = receipt_owner.current_payload_and_worker_owner_id(
                receipt
            )
            if (
                selected.digest != payload_lease.payload_digest
                or selected.configuration.fingerprint
                != payload_lease.runtime.worker_configuration_fingerprint
                or len(selected.body) != payload_lease.runtime.executable_size
                or owner_id != payload_lease.owner_id
            ):
                raise CodingWindowsWorkerPayloadMaterializationError(
                    "coding_worker_payload_binding_mismatch"
                )
            _verify_stage_marker(
                receipt_owner=receipt_owner,
                receipt=receipt,
                payload_lease=payload_lease,
                entrypoint=selected.configuration.entrypoint,
                initial=initial,
            )
            payload_lease.runtime.verify()
            product.assert_root_gc_authority_current()

    verify_current(initial=True)
    if pending_launch is not None:
        with product.gc_gate.guard():
            if (
                type(pending_launch) is not CodingWindowsProductWorkerPendingLaunchV1
                or pending_launch.receipt_fingerprint != receipt.fingerprint
                or pending_launch.identity
                != _windows_worker_identity(
                    receipt=receipt,
                    owner_id=payload_lease.owner_id,
                    attempt_id=payload_lease.attempt_id,
                    supervisor_epoch=supervisor_epoch,
                    session_nonce=pending_launch.identity.session_nonce,
                )
                or open_coding_windows_product_worker_supervisor_journal(
                    product
                ).next_supervisor_epoch(pending_launch.identity)
                != supervisor_epoch
            ):
                raise CodingWindowsWorkerPayloadMaterializationError(
                    "coding_worker_payload_pending_launch_changed"
                )

    def validate_current() -> None:
        try:
            verify_current(initial=False)
        except (
            CodingWorkerReceiptError,
            CodingWindowsWorkerInstalledBackendError,
            CodingWindowsWorkerPayloadMaterializationError,
            CodingWindowsWorkerPayloadInventoryError,
            WindowsWorkerProvisioningStateJournalError,
            WorkerSupervisorJournalError,
            WorkerBindingError,
            OSError,
            ValueError,
        ) as exc:
            raise WorkerBindingError(
                "Coding Windows Product Worker selection changed",
                code="worker_product_selection_stale",
            ) from exc

    identity = (
        pending_launch.identity
        if pending_launch is not None
        else _windows_worker_identity(
            receipt=receipt,
            owner_id=payload_lease.owner_id,
            attempt_id=payload_lease.attempt_id,
            supervisor_epoch=supervisor_epoch,
            session_nonce=secrets.token_hex(32),
        )
    )
    bound_request = ManagedWorkerLaunchRequestV1(
        identity=identity,
        runtime=payload_lease.runtime,
        validate_current=validate_current,
    )
    with _BOUND_REQUESTS_LOCK:
        _BOUND_REQUESTS[validate_current] = (
            id(receipt_owner),
            receipt.fingerprint,
            bound_request.fingerprint,
            payload_lease.stage_identity,
        )
    return bound_request


def _require_coding_windows_product_bound_request(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
    request: ManagedWorkerLaunchRequestV1,
) -> None:
    """Identify one live Product-minted request before publishing its intent."""

    with _BOUND_REQUESTS_LOCK:
        try:
            recorded = _BOUND_REQUESTS.get(request.validate_current)
        except TypeError:
            recorded = None
    if recorded != (
        id(receipt_owner),
        receipt.fingerprint,
        request.fingerprint,
        payload_lease.stage_identity,
    ):
        raise CodingWindowsWorkerPayloadMaterializationError(
            "coding_worker_payload_request_unbound"
        )


def _verify_stage_marker(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
    entrypoint: str,
    initial: bool,
) -> None:
    verify_windows_product_worker_live_stage(
        receipt_owner.product_owner,
        receipt=receipt,
        payload_lease=payload_lease,
        runtime=payload_lease.runtime,
        entrypoint=entrypoint,
        initial=initial,
        marker_name=_MARKER,
        error_type=CodingWindowsWorkerPayloadMaterializationError,
        error_prefix="coding_worker_payload",
    )


_require_root = partial(
    require_payload_root,
    error_type=CodingWindowsWorkerPayloadMaterializationError,
    error_prefix="coding_worker_payload",
)


__all__ = [
    "CodingWindowsProductWorkerPendingLaunchV1",
    "CodingWindowsWorkerPayloadLeaseV1",
    "CodingWindowsWorkerPayloadMaterializationError",
    "bind_coding_windows_product_worker_launch_request",
    "materialize_coding_windows_product_worker_payload",
    "plan_coding_windows_product_worker_pending_launch",
]
