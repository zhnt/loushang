"""Selected Worker payload programs over the original physical storage.

Product authority retains scope/current/native facts; PayloadStorage retains
physical debt and repair IO. These fixed programs own their borrowed scope.
The guard, assert_current and supervisor factory are effectful Product/Journal
ports, invoked at the original points; receipt reads are not assumed pure."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Protocol, TypeVar

from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import (
    WorkerSupervisorJournal,
    WorkerSupervisorJournalError,
)
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationReceiptV1,
)

from ._records import (
    PayloadPlan,
)
from ._repair import _FILE_FLAGS as _FILE_FLAGS
from ._storage import _DIR_FLAGS, PayloadStorage

_NativeT = TypeVar("_NativeT", covariant=True)
_LeaseT = TypeVar("_LeaseT")
_PendingT = TypeVar("_PendingT")


class _PayloadContent(Protocol):
    @property
    def configuration(self) -> PluginLocalWorkerConfiguration: ...

    @property
    def body(self) -> bytes: ...

    @property
    def digest(self) -> str: ...


class _MaterializedPayload(Protocol[_NativeT]):
    @property
    def attempt_id(self) -> str: ...

    @property
    def runtime(self) -> WorkerRuntimeBindingV1: ...

    @property
    def native_material(self) -> _NativeT: ...

    @property
    def receipt_fingerprint(self) -> str: ...


class _PendingPayload(Protocol):
    @property
    def receipt_fingerprint(self) -> str: ...

    @property
    def identity(self) -> WorkerLaunchIdentityV1: ...


class _PayloadReceiptAuthority(Protocol[_NativeT]):
    def current_witness(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness: ...

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> _PayloadContent: ...

    def current_native_launch_material(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> _NativeT: ...

    def current_worker_owner_id(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> str: ...

    def current_runtime_binding(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[_PayloadContent, _NativeT, str]: ...


def worker_identity_from_receipt(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    owner_id: str,
    attempt_id: str,
    supervisor_epoch: int,
    session_nonce: str,
) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id=receipt.policy.plugin_id,
        plugin_revision_digest=receipt.policy.plugin_revision_digest,
        contribution_id=receipt.policy.contribution_id,
        owner_id=owner_id,
        product_id=receipt.policy.product_id,
        scope_id=receipt.policy.product_scope_id,
        owner_generation=receipt.policy.owner_selection_generation,
        declaration_fingerprint=receipt.policy.declaration_fingerprint,
        worker_configuration_fingerprint=receipt.policy.worker_configuration_fingerprint,
        attempt_id=attempt_id,
        supervisor_epoch=supervisor_epoch,
        session_nonce=session_nonce,
    )


@contextmanager
def materialize_selected_payload(
    storage: PayloadStorage,
    *,
    root: Path,
    authority: _PayloadReceiptAuthority[_NativeT],
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
    guard: Callable[[bool], AbstractContextManager[object]],
    assert_current: Callable[[], None],
    supervisor: Callable[[], WorkerSupervisorJournal],
    lease_factory: Callable[..., _LeaseT],
    error_prefix: str = "worker_payload",
) -> Iterator[_LeaseT]:
    root_fd = os.open(root, _DIR_FLAGS)
    stage_name = f"worker-payload-{attempt_id}"
    stage_fd = -1
    created = False
    cleanup_entrypoint: str | None = None
    cleanup_plan: PayloadPlan | None = None
    try:
        storage._require_private_visible_root(root, root_fd)
        with guard(True):
            assert_current()
            payload = authority.current_selected_payload(receipt)
            native_material = authority.current_native_launch_material(receipt)
            if sha256(payload.body).hexdigest() != payload.digest:
                raise storage.error_type(f"{error_prefix}_digest_changed")
            cleanup_entrypoint = payload.configuration.entrypoint
            try:
                os.stat(stage_name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise storage.error_type(f"{error_prefix}_attempt_debt")
            if supervisor().status(attempt_id) is not None:
                raise storage.error_type(f"{error_prefix}_attempt_reused")
            try:
                os.mkdir(stage_name, 448, dir_fd=root_fd)
            except FileExistsError as exc:
                raise storage.error_type(f"{error_prefix}_attempt_debt") from exc
            created = True
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            storage._write_payload(
                stage_fd, payload.configuration.entrypoint, payload.body
            )
            stage_stat = os.fstat(stage_fd)
            plan = storage.values.plan_type(
                attempt_id=attempt_id,
                entrypoint=payload.configuration.entrypoint,
                payload_digest=payload.digest,
                payload_size=len(payload.body),
                receipt_fingerprint=receipt.fingerprint,
                stage_device=stage_stat.st_dev,
                stage_inode=stage_stat.st_ino,
            )
            storage._write_marker(stage_fd, plan)
            cleanup_plan = plan
            stage_path = root / stage_name
            storage._require_visible_stage(stage_name, root_fd, stage_fd)
            binding = WorkerRuntimeBindingV1.capture(
                package_root=stage_path, configuration=payload.configuration
            )
            if (
                binding.executable_digest != payload.digest
                or binding.executable_size != len(payload.body)
                or authority.current_witness(receipt) != receipt.authority_witness
            ):
                raise storage.error_type(f"{error_prefix}_selection_stale")
            storage._require_visible_stage(stage_name, root_fd, stage_fd)
            lease = lease_factory(
                attempt_id=attempt_id,
                runtime=binding,
                native_material=native_material,
                receipt_fingerprint=receipt.fingerprint,
            )
        yield lease
    finally:
        try:
            if created:
                with guard(True):
                    storage._require_visible_stage(stage_name, root_fd, stage_fd)
                    if cleanup_plan is not None:
                        current = storage._verify_debt(root_fd, attempt_id)
                        if current != cleanup_plan:
                            raise storage.error_type(f"{error_prefix}_stage_changed")
                        attempt = supervisor().status(attempt_id)
                        if attempt is None or attempt.process_settled:
                            storage._remove_verified_stage(
                                root_fd, stage_fd, stage_name, cleanup_plan
                            )
                    elif stage_fd >= 0 and cleanup_entrypoint is not None:
                        storage._remove_partial_stage(
                            root_fd, stage_fd, stage_name, cleanup_entrypoint
                        )
        finally:
            if stage_fd >= 0:
                os.close(stage_fd)
            os.close(root_fd)


def plan_selected_payload_launch(
    storage: PayloadStorage,
    *,
    authority: _PayloadReceiptAuthority[_NativeT],
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
    guard: Callable[[bool], AbstractContextManager[object]],
    assert_current: Callable[[], None],
    supervisor: Callable[[], WorkerSupervisorJournal],
    pending_factory: Callable[..., _PendingT],
    error_prefix: str = "worker_payload",
) -> _PendingT:
    with guard(False):
        if authority.current_witness(receipt) != receipt.authority_witness:
            raise storage.error_type(f"{error_prefix}_selection_stale")
        selected = authority.current_selected_payload(receipt)
        if (
            selected.configuration.fingerprint
            != receipt.policy.worker_configuration_fingerprint
        ):
            raise storage.error_type(f"{error_prefix}_selection_stale")
        authority.current_native_launch_material(receipt)
        owner_id = authority.current_worker_owner_id(receipt)
        identity = worker_identity_from_receipt(
            receipt=receipt,
            owner_id=owner_id,
            attempt_id=attempt_id,
            supervisor_epoch=1,
            session_nonce=secrets.token_hex(32),
        )
        journal = supervisor()
        if journal.status(attempt_id) is not None:
            raise storage.error_type(f"{error_prefix}_attempt_reused")
        epoch = journal.next_supervisor_epoch(identity)
        assert_current()
        return pending_factory(
            receipt_fingerprint=receipt.fingerprint,
            identity=replace(identity, supervisor_epoch=epoch),
        )


def bind_selected_payload_request(
    storage: PayloadStorage,
    *,
    authority: _PayloadReceiptAuthority[_NativeT],
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: _MaterializedPayload[_NativeT],
    supervisor_epoch: int,
    pending_launch: _PendingPayload | None,
    pending_type: type[_PendingPayload],
    guard: Callable[[bool], AbstractContextManager[object]],
    supervisor: Callable[[], WorkerSupervisorJournal],
    receipt_error_type: type[Exception],
    stale_message: str = "Product Worker selection changed",
    error_prefix: str = "worker_payload",
) -> ManagedWorkerLaunchRequestV1:
    with guard(False):
        owner_id = authority.current_worker_owner_id(receipt)
        selected = authority.current_selected_payload(receipt)
        native = authority.current_native_launch_material(receipt)
        if (
            selected.digest != payload_lease.runtime.executable_digest
            or selected.configuration.fingerprint
            != payload_lease.runtime.worker_configuration_fingerprint
            or native != payload_lease.native_material
        ):
            raise storage.error_type(f"{error_prefix}_binding_mismatch")
        payload_lease.runtime.verify()
        if pending_launch is not None and (
            type(pending_launch) is not pending_type
            or pending_launch.receipt_fingerprint != receipt.fingerprint
            or pending_launch.identity
            != worker_identity_from_receipt(
                receipt=receipt,
                owner_id=owner_id,
                attempt_id=payload_lease.attempt_id,
                supervisor_epoch=supervisor_epoch,
                session_nonce=pending_launch.identity.session_nonce,
            )
            or (
                supervisor().next_supervisor_epoch(pending_launch.identity)
                != supervisor_epoch
            )
        ):
            raise storage.error_type(f"{error_prefix}_pending_launch_changed")

    def validate_current() -> None:
        try:
            with guard(False):
                current, current_native, current_owner_id = (
                    authority.current_runtime_binding(receipt)
                )
                if (
                    current.digest != payload_lease.runtime.executable_digest
                    or current_native != payload_lease.native_material
                    or current_owner_id != owner_id
                ):
                    raise storage.error_type(f"{error_prefix}_binding_mismatch")
                payload_lease.runtime.verify()
                attempt = supervisor().status(payload_lease.attempt_id)
                if attempt is not None and attempt.terminal:
                    raise storage.error_type(f"{error_prefix}_attempt_settled")
        except (
            receipt_error_type,
            storage.error_type,
            WorkerBindingError,
            WorkerSupervisorJournalError,
        ) as exc:
            raise WorkerBindingError(
                stale_message, code="worker_product_selection_stale"
            ) from exc

    identity = (
        pending_launch.identity
        if pending_launch is not None
        else worker_identity_from_receipt(
            receipt=receipt,
            owner_id=owner_id,
            attempt_id=payload_lease.attempt_id,
            supervisor_epoch=supervisor_epoch,
            session_nonce=secrets.token_hex(32),
        )
    )
    return ManagedWorkerLaunchRequestV1(
        identity=identity,
        runtime=payload_lease.runtime,
        validate_current=validate_current,
    )
