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
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from weakref import WeakKeyDictionary

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
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
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker payload request is invalid")
    product = receipt_owner.product_owner
    stage_name = "worker-payload-" + attempt_id
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        payload = receipt_owner.current_selected_payload(receipt)
        owner_id = receipt_owner.current_worker_owner_id(receipt)
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
                or previous.launch_request_fingerprint is not None
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
                if any(item.attempt_id == attempt_id for item in inventory):
                    raise CodingWindowsWorkerPayloadMaterializationError(
                        "coding_worker_payload_attempt_debt"
                    )
                if len(inventory) >= _MAX_RETAINED_ATTEMPTS:
                    raise CodingWindowsWorkerPayloadMaterializationError(
                        "coding_worker_payload_capacity"
                    )
                stage = open_windows_directory(
                    stage_name,
                    dir_fd=root,
                    create_new=True,
                    share_delete=False,
                    security_descriptor=acl.security_descriptor,
                    read_control=True,
                )
                try:
                    acl.validate(stage)
                    _require_no_named_streams(stage, directory=True)
                    stage_stat = os.fstat(stage)
                    stage_identity = (stage_stat.st_dev, stage_stat.st_ino)
                    windows_flush_directory(root)
                    current = stage
                    children: list[int] = []
                    try:
                        for name in parts[:-1]:
                            child = open_windows_directory(
                                name,
                                dir_fd=current,
                                create_new=True,
                                share_delete=False,
                                security_descriptor=acl.security_descriptor,
                                read_control=True,
                            )
                            children.append(child)
                            acl.validate(child)
                            _require_no_named_streams(child, directory=True)
                            windows_flush_directory(current)
                            current = child
                        executable = open_windows_regular_file_at(
                            current,
                            parts[-1],
                            create_new=True,
                            write=True,
                            security_descriptor=acl.security_descriptor,
                            read_control=True,
                        )
                        try:
                            acl.validate(executable)
                            _require_no_named_streams(executable, directory=False)
                            _write_all(executable, payload.body)
                            windows_flush_file(executable)
                        finally:
                            os.close(executable)
                        windows_flush_directory(current)
                    finally:
                        for child in reversed(children):
                            os.close(child)
                    marker = _marker_bytes(
                        attempt_id=attempt_id,
                        entrypoint=entrypoint,
                        owner_id=owner_id,
                        payload_digest=payload.digest,
                        payload_size=len(payload.body),
                        receipt_fingerprint=receipt.fingerprint,
                        stage_identity=stage_identity,
                    )
                    marker_fd = open_windows_regular_file_at(
                        stage,
                        _MARKER,
                        create_new=True,
                        write=True,
                        security_descriptor=acl.security_descriptor,
                        read_control=True,
                    )
                    try:
                        acl.validate(marker_fd)
                        _require_no_named_streams(marker_fd, directory=False)
                        _write_all(marker_fd, marker)
                        windows_flush_file(marker_fd)
                    finally:
                        os.close(marker_fd)
                    windows_flush_directory(stage)
                    _require_root(product.state_root, root)
                    if (
                        os.fstat(stage).st_dev,
                        os.fstat(stage).st_ino,
                    ) != stage_identity or not os.path.samestat(
                        windows_stat_at(root, stage_name), os.fstat(stage)
                    ):
                        raise CodingWindowsWorkerPayloadMaterializationError(
                            "coding_worker_payload_stage_changed"
                        )
                    runtime = WorkerRuntimeBindingV1.capture(
                        package_root=product.state_root / stage_name,
                        configuration=payload.configuration,
                    )
                    if (
                        runtime.executable_digest != payload.digest
                        or runtime.executable_size != len(payload.body)
                        or (runtime.cwd_device, runtime.cwd_inode) != stage_identity
                        or receipt_owner.current_witness(receipt)
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
                finally:
                    os.close(stage)


def bind_coding_windows_product_worker_launch_request(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
    supervisor_epoch: int,
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
            selected = receipt_owner.current_selected_payload(receipt)
            owner_id = receipt_owner.current_worker_owner_id(receipt)
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

    identity = WorkerLaunchIdentityV1(
        plugin_id=receipt.policy.plugin_id,
        plugin_revision_digest=receipt.policy.plugin_revision_digest,
        contribution_id=receipt.policy.contribution_id,
        owner_id=payload_lease.owner_id,
        product_id=receipt.policy.product_id,
        scope_id=receipt.policy.product_scope_id,
        owner_generation=receipt.policy.owner_selection_generation,
        declaration_fingerprint=receipt.policy.declaration_fingerprint,
        worker_configuration_fingerprint=(
            receipt.policy.worker_configuration_fingerprint
        ),
        attempt_id=payload_lease.attempt_id,
        supervisor_epoch=supervisor_epoch,
        session_nonce=secrets.token_hex(32),
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
    product = receipt_owner.product_owner
    stage_name = "worker-payload-" + payload_lease.attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            acl.validate(root)
            _require_root(product.state_root, root)
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                if initial:
                    acl.validate(stage)
                _require_no_named_streams(stage, directory=True)
                if (
                    os.fstat(stage).st_dev,
                    os.fstat(stage).st_ino,
                ) != payload_lease.stage_identity or not os.path.samestat(
                    windows_stat_at(root, stage_name), os.fstat(stage)
                ):
                    raise CodingWindowsWorkerPayloadMaterializationError(
                        "coding_worker_payload_stage_changed"
                    )
                top_name = entrypoint.split("/", 1)[0]
                if set(windows_listdir_at(stage)) != {_MARKER, top_name}:
                    raise CodingWindowsWorkerPayloadMaterializationError(
                        "coding_worker_payload_stage_changed"
                    )
                parts = entrypoint.split("/")
                current = stage
                children: list[int] = []
                try:
                    for index, name in enumerate(parts[:-1]):
                        child = open_windows_directory(
                            name,
                            dir_fd=current,
                            share_delete=False,
                            read_control=True,
                        )
                        children.append(child)
                        if initial:
                            acl.validate(child)
                        _require_no_named_streams(child, directory=True)
                        if set(windows_listdir_at(child)) != {parts[index + 1]}:
                            raise CodingWindowsWorkerPayloadMaterializationError(
                                "coding_worker_payload_stage_changed"
                            )
                        current = child
                    executable = open_windows_regular_file_at(
                        current,
                        parts[-1],
                        create_new=False,
                        write=False,
                        read_control=True,
                    )
                    try:
                        if initial:
                            acl.validate(executable)
                        _require_no_named_streams(executable, directory=False)
                        if (
                            os.fstat(executable).st_size
                            != payload_lease.runtime.executable_size
                        ):
                            raise CodingWindowsWorkerPayloadMaterializationError(
                                "coding_worker_payload_stage_changed"
                            )
                    finally:
                        os.close(executable)
                finally:
                    for child in reversed(children):
                        os.close(child)
                marker = open_windows_regular_file_at(
                    stage, _MARKER, create_new=False, write=False, read_control=True
                )
                try:
                    if initial:
                        acl.validate(marker)
                    _require_no_named_streams(marker, directory=False)
                    expected = _marker_bytes(
                        attempt_id=payload_lease.attempt_id,
                        entrypoint=entrypoint,
                        owner_id=payload_lease.owner_id,
                        payload_digest=payload_lease.payload_digest,
                        payload_size=payload_lease.runtime.executable_size,
                        receipt_fingerprint=receipt.fingerprint,
                        stage_identity=payload_lease.stage_identity,
                    )
                    if os.read(marker, len(expected) + 1) != expected:
                        raise CodingWindowsWorkerPayloadMaterializationError(
                            "coding_worker_payload_marker_changed"
                        )
                finally:
                    os.close(marker)
                _require_root(product.state_root, root)
            finally:
                os.close(stage)


def _marker_bytes(
    *,
    attempt_id: str,
    entrypoint: str,
    owner_id: str,
    payload_digest: str,
    payload_size: int,
    receipt_fingerprint: str,
    stage_identity: tuple[int, int],
) -> bytes:
    return canonical_json_bytes(
        {
            "attemptId": attempt_id,
            "entrypoint": entrypoint,
            "ownerId": owner_id,
            "payloadDigest": payload_digest,
            "payloadSize": payload_size,
            "receiptFingerprint": receipt_fingerprint,
            "stageDevice": stage_identity[0],
            "stageInode": stage_identity[1],
            "version": 1,
        }
    )


def _require_root(state_root: Path, descriptor: int) -> None:
    if not os.path.samestat(os.fstat(descriptor), state_root.lstat()):
        raise CodingWindowsWorkerPayloadMaterializationError(
            "coding_worker_payload_state_root_changed"
        )


def _require_no_named_streams(descriptor: int, *, directory: bool) -> None:
    streams = (
        windows_directory_stream_names(descriptor)
        if directory
        else windows_regular_file_stream_names(descriptor)
    )
    if any(stream.casefold() != "::$data" for stream in streams):
        raise CodingWindowsWorkerPayloadMaterializationError(
            "coding_worker_payload_stream_invalid"
        )


def _write_all(descriptor: int, body: bytes) -> None:
    remaining = memoryview(body)
    while remaining:
        written = os.write(descriptor, remaining)
        if written < 1:
            raise OSError("Windows Worker payload write made no progress")
        remaining = remaining[written:]


__all__ = [
    "CodingWindowsWorkerPayloadLeaseV1",
    "CodingWindowsWorkerPayloadMaterializationError",
    "bind_coding_windows_product_worker_launch_request",
    "materialize_coding_windows_product_worker_payload",
]
