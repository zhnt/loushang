"""Windows Worker attempt custody at the existing Package Product boundary.

GC/currentness stay with the original Product. Original Resource receipt IO
and Worker provisioning/C5 journals retain all physical facts and writers.
These fixed logical operations add no authority, descriptors or replay state.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Generic, Protocol, Self, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_stat_at,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.worker._windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.history._receipts import _ReceiptRecordMethods
from loushang.harness.worker.history._windows_product_journals import (
    WindowsActivationStateJournal,
)
from loushang.harness.worker.history._windows_recovery import (
    WindowsRecoveryAttemptV1,
    project_windows_recovery_attempts,
)
from loushang.harness.worker.history._windows_sources import WindowsHistoryNames
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._windows_stage_io import (
    FileIdentity,
    LaunchIntent,
    WindowsStageInspection,
    marker_bytes,
    require_payload_root,
    require_payload_streams,
)
from loushang.harness.worker.payload._windows_stage_io import identity as _file_identity
from loushang.harness.worker.payload._windows_stage_retirement import close_opened
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

_PersistedCheckpointT = TypeVar("_PersistedCheckpointT")
_PersistedBasesT = TypeVar("_PersistedBasesT")
_PersistedCutoverT = TypeVar("_PersistedCutoverT")


def read_windows_product_worker_persisted_bases(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    *,
    require_cutover: bool,
    io: WindowsPrivateReceiptIO,
    history_names: WindowsHistoryNames,
    checkpoint_name: str,
    base_files: tuple[tuple[str, str], ...],
    cutover_name: str,
    limits: Callable[[], tuple[int, int, int]],
    decode_checkpoint: Callable[[bytes], _PersistedCheckpointT],
    make_result: Callable[[_PersistedCheckpointT, tuple[bytes, ...]], _PersistedBasesT],
    cutover_codec: Callable[
        [], Callable[[bytes, _PersistedBasesT], _PersistedCutoverT]
    ],
) -> tuple[_PersistedBasesT, _PersistedCutoverT | None]:
    """Read and recheck fixed persisted history under the caller's GC gate."""

    product.assert_root_gc_authority_current()
    with WindowsPrivateDirectoryAcl() as acl:
        acl.validate(root)
        io._require_simple_attributes(os.fstat(root), directory=True)
        io._require_no_named_directory_streams(root)
        if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
            raise ValueError("Windows Worker persisted root changed")
        names = tuple(windows_listdir_at(root))
        if require_cutover:
            if names.count(cutover_name) != 1:
                raise ValueError("Windows Worker cutover marker is absent")
            known_names = tuple(name for name in names if name != cutover_name)
        else:
            known_names = names
        history_names.require_known(known_names)
        if any(name.casefold().endswith(".stage") for name in names):
            raise ValueError("Windows Worker persisted stage remains")
        checkpoint_raw = io._read_file(
            root, acl, checkpoint_name, maximum_bytes=limits()[0]
        )
        if checkpoint_raw is None:
            raise ValueError("Windows Worker persisted checkpoint is absent")
        checkpoint = decode_checkpoint(checkpoint_raw)
        raw_bases = tuple(
            io._read_file(root, acl, name, maximum_bytes=limits()[1])
            for _, name in base_files
        )
        if any(raw is None for raw in raw_bases):
            raise ValueError("Windows Worker persisted base is absent")
        opt_in, receipt, supervisor, c5, launch_intent, native = (
            raw for raw in raw_bases if raw is not None
        )
        result = make_result(
            checkpoint, (opt_in, receipt, supervisor, c5, launch_intent, native)
        )
        cutover = None
        cutover_raw = None
        if require_cutover:
            decode_cutover = cutover_codec()

            cutover_raw = io._read_file(
                root,
                acl,
                cutover_name,
                maximum_bytes=limits()[2],
            )
            if cutover_raw is None:
                raise ValueError("Windows Worker cutover marker is absent")
            cutover = decode_cutover(cutover_raw, result)
        if (
            io._read_file(
                root,
                acl,
                checkpoint_name,
                maximum_bytes=limits()[0],
            )
            != checkpoint_raw
            or tuple(
                io._read_file(root, acl, name, maximum_bytes=limits()[1])
                for _, name in base_files
            )
            != raw_bases
            or (
                require_cutover
                and io._read_file(
                    root,
                    acl,
                    cutover_name,
                    maximum_bytes=limits()[2],
                )
                != cutover_raw
            )
            or tuple(windows_listdir_at(root)) != names
            or not os.path.samestat(os.fstat(root), product.state_root.lstat())
        ):
            raise ValueError("Windows Worker persisted bases changed")
        acl.validate(root)
        io._require_simple_attributes(os.fstat(root), directory=True)
        io._require_no_named_directory_streams(root)
    product.assert_root_gc_authority_current()
    return result, cutover


class _IntentRecord(Protocol):
    @property
    def attempt_id(self) -> str: ...

    def to_bytes(self) -> bytes: ...

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self: ...


IntentT = TypeVar("IntentT", bound=_IntentRecord)


def decode_windows_worker_attempt_record(
    raw: bytes | None,
    record_type: type[IntentT],
    attempt_id: str,
    *,
    invalid_error: Callable[[], Exception],
) -> IntentT | None:
    """Decode retained bytes and require the caller's exact Worker attempt."""

    record = None if raw is None else record_type.from_bytes(raw)
    if record is not None and record.attempt_id != attempt_id:
        raise invalid_error()
    return record


_RetirementReviewT = TypeVar("_RetirementReviewT", bound=_IntentRecord)


class _ReceiptWriter(Protocol):
    def __call__(self, path: Path, payload: bytes, *, maximum_bytes: int) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowsWorkerRetirementRecords(Generic[_RetirementReviewT, IntentT]):
    stem: str
    review_type: type[_RetirementReviewT]
    receipt_type: type[IntentT]
    review_maximum_bytes: int
    receipt_maximum_bytes: int
    read_bytes: Callable[[Path, int], bytes | None]
    error_type: type[Exception]
    start_invalid: str
    root_intent_invalid: str
    receipt_invalid: str

    def start_path(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> Path:
        return product.state_root / f"{self.stem}-retire-{attempt_id}.json"

    def root_intent_path(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> Path:
        return product.state_root / f"{self.stem}-root-delete-{attempt_id}.json"

    def receipt_path(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> Path:
        return product.state_root / f"{self.stem}-retired-{attempt_id}.json"

    def read_start(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> _RetirementReviewT | None:
        return decode_windows_worker_attempt_record(
            self.read_bytes(
                self.start_path(product, attempt_id), self.review_maximum_bytes
            ),
            self.review_type,
            attempt_id,
            invalid_error=lambda: self.error_type(self.start_invalid),
        )

    def read_root_intent(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> IntentT | None:
        return decode_windows_worker_attempt_record(
            self.read_bytes(
                self.root_intent_path(product, attempt_id), self.receipt_maximum_bytes
            ),
            self.receipt_type,
            attempt_id,
            invalid_error=lambda: self.error_type(self.root_intent_invalid),
        )

    def read_receipt(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> IntentT | None:
        return decode_windows_worker_attempt_record(
            self.read_bytes(
                self.receipt_path(product, attempt_id), self.receipt_maximum_bytes
            ),
            self.receipt_type,
            attempt_id,
            invalid_error=lambda: self.error_type(self.receipt_invalid),
        )

    def ensure_root_delete_intent(
        self,
        receipt: IntentT,
        *,
        path: Callable[[], Path],
        read: Callable[[], IntentT | None],
        write: _ReceiptWriter,
        changed_message: str,
    ) -> None:
        if read() is None:
            write(path(), receipt.to_bytes(), maximum_bytes=self.receipt_maximum_bytes)
        if read() != receipt:
            raise self.error_type(changed_message)

    def publish_receipt(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _RetirementReviewT,
        receipt: IntentT,
        *,
        write: _ReceiptWriter,
        read: Callable[[WindowsLocalWheelProductSessionOwner, str], IntentT | None],
        changed_message: str,
    ) -> None:
        write(
            self.receipt_path(product, review.attempt_id),
            receipt.to_bytes(),
            maximum_bytes=self.receipt_maximum_bytes,
        )
        if read(product, review.attempt_id) != receipt:
            raise self.error_type(changed_message)
        product.assert_root_gc_authority_current()


class _PayloadSelection(Protocol):
    @property
    def digest(self) -> str: ...

    @property
    def configuration(self) -> PluginLocalWorkerConfiguration: ...

    @property
    def body(self) -> bytes: ...


class _SelectedPayloadAuthority(Protocol):
    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> _PayloadSelection: ...

    def current_worker_owner_id(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> str: ...


class _LaunchPayload(Protocol):
    @property
    def payload_digest(self) -> str: ...

    @property
    def owner_id(self) -> str: ...


class _MarkerVerifier(Protocol):
    def __call__(self, *, entrypoint: str) -> None: ...


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerIntentRecords(Generic[IntentT]):
    """Logical record operations using original IO; no cached path/epoch.

    read/inspect require the caller's original GC scope. commit acquires the
    original write guard. Layout/decoder/bounds are Product bindings; path and
    maximum getters run at the old operation points, inside the borrowed root.
    """

    _product: WindowsLocalWheelProductSessionOwner
    _io: WindowsPrivateReceiptIO
    _record_type: type[IntentT]
    _path: Callable[[str], Path]
    _prefix: str
    _name_pattern: re.Pattern[str]
    _maximum_bytes: Callable[[], int]
    _maximum_attempts: Callable[[], int]
    _error_type: type[RuntimeError]
    _error_prefix: str
    _write_maximum_bytes: int

    def _failure(self, suffix: str) -> RuntimeError:
        return self._error_type(self._error_prefix + "_" + suffix)

    def read(
        self, attempt_id: str, *, allow_unpublished_stage: bool = False
    ) -> IntentT | None:
        self._product.assert_root_gc_authority_current()
        with self._product.epoch_runtime.borrow_product_state_root_descriptor():
            raw = self._io.read_private_receipt(
                self._path(attempt_id),
                maximum_bytes=self._maximum_bytes(),
                allow_unpublished_stage=allow_unpublished_stage,
            )
        intent = (
            None
            if raw is None
            else decode_windows_worker_attempt_record(
                raw,
                self._record_type,
                attempt_id,
                invalid_error=lambda: self._failure("invalid"),
            )
        )
        self._product.assert_root_gc_authority_current()
        return intent

    def inspect(self) -> tuple[IntentT, ...]:
        self._product.assert_root_gc_authority_current()
        with self._product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            names = windows_listdir_at(root)
            prefixed = {
                name for name in names if name.casefold().startswith(self._prefix)
            }
            histories = {
                name for name in prefixed if self._name_pattern.fullmatch(name)
            }
            if prefixed != histories or len(histories) > self._maximum_attempts():
                raise self._failure("inventory_unsafe")
            intents = []
            for name in sorted(histories):
                match = self._name_pattern.fullmatch(name)
                assert match is not None
                intent = self.read(match.group(1))
                if intent is None:
                    raise self._failure("inventory_unsafe")
                intents.append(intent)
            if set(windows_listdir_at(root)) != set(names):
                raise self._failure("inventory_changed")
        self._product.assert_root_gc_authority_current()
        return tuple(intents)

    def commit(
        self,
        *,
        receipt_owner: _SelectedPayloadAuthority,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        payload_lease: _LaunchPayload,
        intent: IntentT,
        require_bound: Callable[[], None],
        verify_marker: _MarkerVerifier,
    ) -> IntentT:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            require_bound()
            selected = receipt_owner.current_selected_payload(receipt)
            owner_id = receipt_owner.current_worker_owner_id(receipt)
            if (
                selected.digest != payload_lease.payload_digest
                or selected.configuration.fingerprint
                != request.runtime.worker_configuration_fingerprint
                or len(selected.body) != request.runtime.executable_size
                or (owner_id != payload_lease.owner_id)
            ):
                raise self._failure("selection_stale")
            verify_marker(entrypoint=selected.configuration.entrypoint)
            request.runtime.verify()
            request.validate_current()
            existing = self.read(intent.attempt_id, allow_unpublished_stage=True)
            if existing is not None:
                raise self._failure("attempt_reused")
            with self._product.epoch_runtime.borrow_product_state_root_descriptor():
                self._io.write_private_receipt(
                    self._path(intent.attempt_id),
                    intent.to_bytes(),
                    maximum_bytes=self._write_maximum_bytes,
                )
                if self.read(intent.attempt_id) != intent:
                    raise self._failure("publication_changed")
            self._product.assert_root_gc_authority_current()
            return intent


class WindowsProductWorkerProvisioningAccess:
    """Load/CAS on the original actual Code object; policy hooks keep its rules.

    This base initializes no state. The real public object's constructor keeps
    the same Product/runtime/request/Journal references, and owns the precise
    selection and retained-cleanup policy at the two original hook points.
    """

    _product: WindowsLocalWheelProductSessionOwner
    _runtime: PackageProductRuntimeBindingV1
    _receipt: ProductWorkerActivationReceiptV1
    _worker_request: ManagedWorkerLaunchRequestV1
    _journal: WindowsWorkerProvisioningStateJournal

    @staticmethod
    def _require_launch_intent(
        product: WindowsLocalWheelProductSessionOwner,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
    ) -> None:
        raise NotImplementedError("the original Product intent policy is required")

    def _require_store_current(
        self, *, desired_phase: object | None = None, write: bool = False
    ) -> None:
        raise NotImplementedError("the original Product cleanup policy is required")

    def load(self) -> Mapping[str, object] | None:
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            self._require_launch_intent(
                self._product,
                receipt=self._receipt,
                worker_request=self._worker_request,
            )
            self._product.assert_session_runtime_current(self._runtime)
            self._require_store_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                current = self._journal.load(directory_fd=root)
            self._product.assert_root_gc_authority_current()
            return current

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            self._require_launch_intent(
                self._product,
                receipt=self._receipt,
                worker_request=self._worker_request,
            )
            self._product.assert_session_runtime_current(self._runtime)
            self._require_store_current(desired_phase=document.get("phase"), write=True)
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                committed = self._journal.compare_and_swap(
                    expected_revision=expected_revision,
                    document=document,
                    directory_fd=root,
                )
            self._product.assert_root_gc_authority_current()
            return committed


class _AttemptFact(Protocol):
    @property
    def attempt_id(self) -> str: ...


RuntimeT = TypeVar("RuntimeT")
RuntimeCo = TypeVar("RuntimeCo", covariant=True)
ActivationT = TypeVar("ActivationT", bound=_AttemptFact)


class _RuntimeReview(Protocol[RuntimeCo]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        orphans: tuple[PackageEpochRuntimeLeaseV1, ...],
    ) -> RuntimeCo: ...


def capture_windows_product_worker_cleanup(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    review_runtime: _RuntimeReview[RuntimeT],
    inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ],
    activation_journal: Callable[[], WindowsActivationStateJournal[ActivationT]],
) -> tuple[RuntimeT, WindowsWorkerProvisioningAttemptV1 | None, ActivationT | None]:
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        runtime = review_runtime(product, attempt_id=attempt_id, orphans=orphans)
        native = tuple(
            (item for item in inspect_native(product) if item.attempt_id == attempt_id)
        )
        retained = tuple(
            (
                item
                for item in activation_journal().retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
        )
        product.assert_root_gc_authority_current()
    return (
        runtime,
        native[0] if len(native) == 1 else None,
        retained[0] if len(retained) == 1 else None,
    )


_InventoryT = TypeVar("_InventoryT")
_RecoveryT = TypeVar("_RecoveryT", bound=WindowsRecoveryAttemptV1)
_ReceiptT = TypeVar("_ReceiptT", bound=_ReceiptRecordMethods)
_ReceiptCo = TypeVar("_ReceiptCo", bound=_ReceiptRecordMethods, covariant=True)
_ReviewT = TypeVar("_ReviewT")


class _ReceiptJournalReader(Protocol[_ReceiptCo]):
    def records(self, *, directory_fd: int) -> tuple[_ReceiptCo, ...]: ...


class _ReceiptJournalFactory(Protocol[_ReceiptCo]):
    def __call__(
        self, path: Path, *, scope_id: str
    ) -> _ReceiptJournalReader[_ReceiptCo]: ...


def read_windows_product_worker_attempts(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    inspect_attempts: Callable[[Path, int], tuple[_InventoryT, ...]],
) -> tuple[_InventoryT, ...]:
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            result = inspect_attempts(product.state_root, root)
        product.assert_root_gc_authority_current()
        return result


def inspect_windows_product_worker_recovery_inventory(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    inspect_retirements: Callable[
        [WindowsLocalWheelProductSessionOwner], frozenset[str]
    ],
    inspect_payloads: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[_AttemptFact, ...]
    ],
    inspect_intents: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[_AttemptFact, ...]
    ],
    inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ],
    inspect_supervisor: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[WorkerAttemptRecordV1, ...]
    ],
    record_type: type[_RecoveryT],
    native_attempts: tuple[WindowsWorkerProvisioningAttemptV1, ...] | None = None,
) -> tuple[_RecoveryT, ...]:
    """Acquire original owners in order; supplied empty native facts skip IO."""
    product.assert_root_gc_authority_current()
    retirement_attempts = inspect_retirements(product)
    payloads = {item.attempt_id: item for item in inspect_payloads(product)}
    intents = {item.attempt_id: item for item in inspect_intents(product)}
    native_source = (
        inspect_native(product) if native_attempts is None else native_attempts
    )
    native = {item.attempt_id: item for item in native_source}
    supervisor_records = inspect_supervisor(product)
    supervisor = {item.attempt_id: item for item in supervisor_records}
    attempts = project_windows_recovery_attempts(
        payloads,
        intents,
        native,
        supervisor,
        retirement_attempts,
        record_type=record_type,
    )
    product.assert_root_gc_authority_current()
    return tuple(attempts)


def capture_windows_product_worker_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    orphans: tuple[PackageEpochRuntimeLeaseV1, ...],
    inspect_inventory: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[_RecoveryT, ...]
    ],
    receipt_journal: _ReceiptJournalFactory[_ReceiptT],
    observe_job_absent: Callable[[str], bool],
    review_type: Callable[..., _ReviewT],
) -> _ReviewT:
    """Join under the caller's original registry-before-GC scope; no write authority."""
    product.assert_root_gc_authority_current()
    attempts = inspect_inventory(product)
    attempt = next((item for item in attempts if item.attempt_id == attempt_id), None)
    journal = receipt_journal(
        product.state_root / "worker-activation-receipts.jsonl",
        scope_id=product.policy.project_scope_id,
    )
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        receipts = journal.records(directory_fd=root)
    fingerprint = None if attempt is None else attempt.launch_receipt_fingerprint
    receipt = next(
        (
            item
            for item in receipts
            if fingerprint is not None and item.receipt.fingerprint == fingerprint
        ),
        None,
    )
    runtime_id = None if receipt is None else receipt.receipt.policy.product_runtime_id
    matching = (
        ()
        if runtime_id is None
        else tuple(item for item in orphans if item.runtime_id == runtime_id)
    )
    fence = product.epoch_runtime.cutover_result.fence
    if fence is None:
        raise ValueError("Windows Worker Product fence is unavailable")
    product.assert_root_gc_authority_current()
    return review_type(
        attempt_id=attempt_id,
        attempt=attempt,
        receipt_record=receipt,
        orphan_leases=matching,
        runtime_epoch=fence.epoch,
        store_root_identity=fence.fenced_root_identity,
        native_job_absent=(
            None
            if attempt is None or attempt.native_job_name is None
            else observe_job_absent(attempt.native_job_name)
        ),
    )


def require_windows_worker_retirement_root(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    inspection: Callable[[], WindowsStageInspection],
    error_type: type[Exception],
    changed_message: str,
) -> None:
    """Check the borrowed root and close the ACL before retirement work."""

    with WindowsPrivateDirectoryAcl() as acl:
        inspection().require_direct(root, acl, directory=True)
        if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
            raise error_type(changed_message)


def list_windows_worker_state_root_names(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[str, ...]:
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        names = windows_listdir_at(root)
    return names


def inspect_windows_product_worker_retirement_ids(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    inspect_names: Callable[[tuple[str, ...]], frozenset[str]],
    inspection: Callable[[], WindowsStageInspection],
    error_type: type[RuntimeError],
    error_prefix: str,
) -> frozenset[str]:
    """Read direct root facts; only the Product name grammar is supplied."""
    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        with WindowsPrivateDirectoryAcl() as acl:
            inspection().require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise error_type(error_prefix + "_root_changed")
            attempts = inspect_names(windows_listdir_at(root))
    product.assert_root_gc_authority_current()
    return attempts


@dataclass(frozen=True, slots=True)
class CapturedWindowsWorkerStage:
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str


class _StageCaptureIntent(LaunchIntent, Protocol):
    @property
    def stage_identity(self) -> tuple[int, int]: ...


StageReviewT = TypeVar("StageReviewT")


def verify_windows_product_worker_live_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: _StageCaptureIntent,
    runtime: WorkerRuntimeBindingV1,
    entrypoint: str,
    initial: bool,
    marker_name: str,
    error_type: type[RuntimeError],
    error_prefix: str,
) -> None:
    """Verify a live stage under the original Product root and ACL custody."""

    require_root = partial(
        require_payload_root, error_type=error_type, error_prefix=error_prefix
    )
    require_streams = partial(
        require_payload_streams, error_type=error_type, error_prefix=error_prefix
    )
    stage_name = "worker-payload-" + payload_lease.attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            acl.validate(root)
            require_root(product.state_root, root)
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                if initial:
                    acl.validate(stage)
                require_streams(stage, directory=True)
                if (
                    os.fstat(stage).st_dev,
                    os.fstat(stage).st_ino,
                ) != payload_lease.stage_identity or not os.path.samestat(
                    windows_stat_at(root, stage_name), os.fstat(stage)
                ):
                    raise error_type(error_prefix + "_stage_changed")
                top_name = entrypoint.split("/", 1)[0]
                if set(windows_listdir_at(stage)) != {marker_name, top_name}:
                    raise error_type(error_prefix + "_stage_changed")
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
                        require_streams(child, directory=True)
                        if set(windows_listdir_at(child)) != {parts[index + 1]}:
                            raise error_type(error_prefix + "_stage_changed")
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
                        require_streams(executable, directory=False)
                        if os.fstat(executable).st_size != runtime.executable_size:
                            raise error_type(error_prefix + "_stage_changed")
                    finally:
                        os.close(executable)
                finally:
                    for child in reversed(children):
                        os.close(child)
                marker = open_windows_regular_file_at(
                    stage, marker_name, create_new=False, write=False, read_control=True
                )
                try:
                    if initial:
                        acl.validate(marker)
                    require_streams(marker, directory=False)
                    expected = marker_bytes(
                        attempt_id=payload_lease.attempt_id,
                        entrypoint=entrypoint,
                        owner_id=payload_lease.owner_id,
                        payload_digest=payload_lease.payload_digest,
                        payload_size=runtime.executable_size,
                        receipt_fingerprint=receipt.fingerprint,
                        stage_identity=payload_lease.stage_identity,
                    )
                    if os.read(marker, len(expected) + 1) != expected:
                        raise error_type(error_prefix + "_marker_changed")
                finally:
                    os.close(marker)
                require_root(product.state_root, root)
            finally:
                os.close(stage)


def capture_windows_product_worker_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: _StageCaptureIntent,
    inspection: WindowsStageInspection,
    marker_name: str,
    max_marker_bytes: int,
    max_payload_bytes: int,
    error_type: type[RuntimeError],
    error_prefix: str,
    result_factory: Callable[[CapturedWindowsWorkerStage], StageReviewT],
) -> StageReviewT:
    """Construct the caller's pure result before the original root scopes exit."""
    stage_name = "worker-payload-" + attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            inspection.require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise error_type(f"{error_prefix}_root_changed")
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                stage_identity = inspection.require_direct(stage, acl, directory=True)
                if (
                    stage_identity[:2] != expected_stage
                    or stage_identity[:2] != intent.stage_identity
                    or _file_identity(windows_stat_at(root, stage_name))
                    != stage_identity
                ):
                    raise error_type(f"{error_prefix}_stage_changed")
                raw_marker, marker_identity = inspection.read_checked_file(
                    stage,
                    marker_name,
                    acl,
                    maximum_bytes=max_marker_bytes,
                )
                entrypoint, marker_payload_size = inspection.verify_marker(
                    raw_marker, intent=intent, stage_identity=expected_stage
                )
                parts = entrypoint.split("/")
                if set(windows_listdir_at(stage)) != {marker_name, parts[0]}:
                    raise error_type(f"{error_prefix}_tree_changed")
                current = stage
                children: list[int] = []
                directory_identities: list[tuple[str, FileIdentity]] = []
                try:
                    for index, name in enumerate(parts[:-1]):
                        child = open_windows_directory(
                            name,
                            dir_fd=current,
                            share_delete=False,
                            read_control=True,
                        )
                        children.append(child)
                        identity = inspection.require_direct(child, acl, directory=True)
                        if _file_identity(
                            windows_stat_at(current, name)
                        ) != identity or set(windows_listdir_at(child)) != {
                            parts[index + 1]
                        }:
                            raise error_type(f"{error_prefix}_tree_changed")
                        directory_identities.append(
                            ("/".join(parts[: index + 1]), identity)
                        )
                        current = child
                    executable, executable_identity = inspection.read_checked_file(
                        current,
                        parts[-1],
                        acl,
                        maximum_bytes=max_payload_bytes,
                    )
                    executable_digest = sha256(executable).hexdigest()
                    if (
                        executable_digest != intent.payload_digest
                        or len(executable) != marker_payload_size
                    ):
                        raise error_type(f"{error_prefix}_payload_changed")
                finally:
                    for child in reversed(children):
                        os.close(child)
                if (
                    _file_identity(os.fstat(stage)) != stage_identity
                    or _file_identity(windows_stat_at(root, stage_name))
                    != stage_identity
                    or set(windows_listdir_at(stage)) != {marker_name, parts[0]}
                ):
                    raise error_type(f"{error_prefix}_stage_changed")
                return result_factory(
                    CapturedWindowsWorkerStage(
                        entrypoint=entrypoint,
                        stage_identity=stage_identity,
                        directory_identities=tuple(directory_identities),
                        marker_identity=marker_identity,
                        executable_identity=executable_identity,
                        executable_digest=executable_digest,
                    )
                )
            finally:
                os.close(stage)


@dataclass(frozen=True, slots=True)
class CapturedWindowsWorkerPartialStage:
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    entrypoint: str | None
    executable_identity: FileIdentity | None
    executable_digest: str | None


def capture_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int] | None,
    inspection: WindowsStageInspection,
    max_payload_bytes: int,
    max_depth: int,
    marker_name: str,
    error_type: type[RuntimeError],
    error_prefix: str,
    result_factory: Callable[[CapturedWindowsWorkerPartialStage], StageReviewT],
) -> StageReviewT:
    """Build the public result at the original innermost resource boundary."""
    stage_name = "worker-payload-" + attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            inspection.require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise error_type(f"{error_prefix}_root_changed")
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                stage_identity = inspection.require_direct(stage, acl, directory=True)
                if (
                    expected_stage is None
                    or stage_identity[:2] != expected_stage
                    or _file_identity(windows_stat_at(root, stage_name))
                    != stage_identity
                ):
                    raise error_type(f"{error_prefix}_changed")
                directories: list[tuple[str, FileIdentity]] = []
                opened: list[int] = []
                observed: list[tuple[int, FileIdentity, tuple[str, ...]]] = []
                entrypoint = None
                executable_identity = None
                executable_digest = None
                current = stage
                names_before = tuple(windows_listdir_at(stage))
                try:
                    for depth in range(max_depth + 1):
                        names = tuple(windows_listdir_at(current))
                        if len(names) > 1 or any(
                            name.casefold() == marker_name for name in names
                        ):
                            raise error_type(f"{error_prefix}_shape_invalid")
                        if not names:
                            break
                        name = names[0]
                        prefix = directories[-1][0] if directories else ""
                        path = f"{prefix}/{name}" if prefix else name
                        try:
                            canonical = canonical_plugin_relative_path(path)
                        except ValueError as exc:
                            raise error_type(f"{error_prefix}_shape_invalid") from exc
                        if canonical.as_posix() != path:
                            raise error_type(f"{error_prefix}_shape_invalid")
                        metadata = windows_stat_at(current, name)
                        if stat.S_ISDIR(metadata.st_mode):
                            if depth == max_depth:
                                raise error_type(f"{error_prefix}_depth_exceeded")
                            child = open_windows_directory(
                                name,
                                dir_fd=current,
                                share_delete=False,
                                read_control=True,
                            )
                            opened.append(child)
                            identity = inspection.require_direct(
                                child, acl, directory=True
                            )
                            if (
                                _file_identity(windows_stat_at(current, name))
                                != identity
                            ):
                                raise error_type(f"{error_prefix}_changed")
                            directories.append((path, identity))
                            observed.append(
                                (child, identity, tuple(windows_listdir_at(child)))
                            )
                            current = child
                        elif stat.S_ISREG(metadata.st_mode):
                            raw, identity = inspection.read_checked_file(
                                current, name, acl, maximum_bytes=max_payload_bytes
                            )
                            entrypoint = path
                            executable_identity = identity
                            executable_digest = sha256(raw).hexdigest()
                            break
                        else:
                            raise error_type(f"{error_prefix}_shape_invalid")
                    if any(
                        inspection.require_direct(descriptor, acl, directory=True)
                        != identity
                        or tuple(windows_listdir_at(descriptor)) != names
                        for descriptor, identity, names in observed
                    ) or (
                        _file_identity(os.fstat(stage)) != stage_identity
                        or _file_identity(windows_stat_at(root, stage_name))
                        != stage_identity
                        or tuple(windows_listdir_at(stage)) != names_before
                    ):
                        raise error_type(f"{error_prefix}_changed")
                    return result_factory(
                        CapturedWindowsWorkerPartialStage(
                            stage_identity=stage_identity,
                            directory_identities=tuple(directories),
                            entrypoint=entrypoint,
                            executable_identity=executable_identity,
                            executable_digest=executable_digest,
                        )
                    )
                finally:
                    close_opened(opened)
            finally:
                os.close(stage)
