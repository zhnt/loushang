"""Windows Worker attempt custody at the existing Package Product boundary.

GC/currentness stay with the original Product. Original Resource receipt IO
and Worker provisioning/C5 journals retain all physical facts and writers.
These fixed logical operations add no authority, descriptors or replay state.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Generic, Protocol, Self, TypeVar, cast
from weakref import WeakKeyDictionary

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_stat_at,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.worker._native_profile_bridge import (
    _WINDOWS_LPAC_PROFILE_ID,
    _rebuild_windows_lpac_cleanup_spec,
    _recover_windows_lpac_containment_cleanup,
    _windows_lpac_provisioning_identity,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker._windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.history._receipts import _ReceiptRecordMethods
from loushang.harness.worker.history._windows_launch_intent_base import (
    WindowsLaunchIntentMethods,
)
from loushang.harness.worker.history._windows_product_journals import (
    WindowsActivationStateJournal,
    WindowsSupervisorJournal,
)
from loushang.harness.worker.history._windows_recovery import (
    WINDOWS_STAGE_RETIREMENT_RECEIPT_MAX_BYTES,
    WindowsRecoveryAdmission,
    WindowsRecoveryAttemptV1,
    project_windows_recovery_attempts,
)
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_BASE_FILES,
    WINDOWS_WORKER_HISTORY_CHECKPOINT_MAX_BYTES,
    WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME,
    WINDOWS_WORKER_HISTORY_CUTOVER_MAX_BYTES,
    WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
    WINDOWS_WORKER_LAUNCH_INTENT_NAME,
    WINDOWS_WORKER_LAUNCH_INTENT_PREFIX,
    WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES,
    WindowsHistoryNames,
    windows_worker_launch_intent_name,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    WINDOWS_STAGE_REVIEW_MAX_BYTES,
    _WindowsPartialStageReviewMethods,
    _WindowsReservedStageReviewMethods,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._selected_payload import (
    _PendingPayload,
    require_current_pending_launch,
    worker_identity_from_receipt,
)
from loushang.harness.worker.payload._windows_stage_io import (
    FileIdentity,
    LaunchIntent,
    WindowsStageInspection,
    create_windows_payload_stage,
    marker_bytes,
    require_payload_root,
    require_payload_streams,
)
from loushang.harness.worker.payload._windows_stage_io import identity as _file_identity
from loushang.harness.worker.payload._windows_stage_retirement import close_opened
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1
from loushang.hosting import observe_windows_worker_job_absent
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_PLATFORM_IMPORTS,
    WindowsBackendMaterialExpectationV1,
    verify_windows_backend_material_expectation,
)

from ._worker_history_access import windows_product_worker_quiescence
from ._worker_product_authority import _WindowsWorkerProductReceiptAuthority
from .product_worker_candidate import (
    ProductWorkerSelectedPayloadFacts,
    verify_product_selected_worker_candidate,
)

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
            if names.count(WINDOWS_WORKER_HISTORY_CUTOVER_NAME) != 1:
                raise ValueError("Windows Worker cutover marker is absent")
            known_names = tuple(
                name for name in names if name != WINDOWS_WORKER_HISTORY_CUTOVER_NAME
            )
        else:
            known_names = names
        history_names.require_known(known_names)
        if any(name.casefold().endswith(".stage") for name in names):
            raise ValueError("Windows Worker persisted stage remains")
        checkpoint_raw = io._read_file(
            root,
            acl,
            WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME,
            maximum_bytes=WINDOWS_WORKER_HISTORY_CHECKPOINT_MAX_BYTES,
        )
        if checkpoint_raw is None:
            raise ValueError("Windows Worker persisted checkpoint is absent")
        checkpoint = decode_checkpoint(checkpoint_raw)
        raw_bases = tuple(
            io._read_file(
                root, acl, name, maximum_bytes=WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES
            )
            for _, name in WINDOWS_WORKER_BASE_FILES
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
                WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
                maximum_bytes=WINDOWS_WORKER_HISTORY_CUTOVER_MAX_BYTES,
            )
            if cutover_raw is None:
                raise ValueError("Windows Worker cutover marker is absent")
            cutover = decode_cutover(cutover_raw, result)
        if (
            io._read_file(
                root,
                acl,
                WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME,
                maximum_bytes=WINDOWS_WORKER_HISTORY_CHECKPOINT_MAX_BYTES,
            )
            != checkpoint_raw
            or tuple(
                io._read_file(
                    root,
                    acl,
                    name,
                    maximum_bytes=WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES,
                )
                for _, name in WINDOWS_WORKER_BASE_FILES
            )
            != raw_bases
            or (
                require_cutover
                and io._read_file(
                    root,
                    acl,
                    WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
                    maximum_bytes=WINDOWS_WORKER_HISTORY_CUTOVER_MAX_BYTES,
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
    review_maximum_bytes: int = WINDOWS_STAGE_REVIEW_MAX_BYTES
    receipt_maximum_bytes: int = WINDOWS_STAGE_RETIREMENT_RECEIPT_MAX_BYTES
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

    def publish_start(
        self, path: Path, review: _RetirementReviewT, *, write: _ReceiptWriter
    ) -> None:
        write(path, review.to_bytes(), maximum_bytes=self.review_maximum_bytes)

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


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerIntentRecords(Generic[IntentT]):
    """Publish and read the exact launch intent using the current Product root."""

    _product_id: str
    _io: WindowsPrivateReceiptIO
    _record_type: type[IntentT]
    _maximum_bytes: int
    _maximum_attempts: int
    _error_type: type[RuntimeError]
    _error_prefix: str
    _write_maximum_bytes: int

    def _failure(self, suffix: str) -> RuntimeError:
        return self._error_type(self._error_prefix + "_" + suffix)

    def _require_product(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if not is_windows_product(product, self._product_id, os.name):
            raise OSError("Windows Worker launch intent requires a Product owner")

    @staticmethod
    def _require_attempt(attempt_id: str) -> None:
        if not is_attempt_id(attempt_id):
            raise ValueError("Windows Worker launch intent attempt ID is invalid")

    def _path(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> Path:
        self._require_attempt(attempt_id)
        return product.state_root / windows_worker_launch_intent_name(attempt_id)

    def read(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> IntentT | None:
        self._require_product(product)
        self._require_attempt(attempt_id)
        with product.gc_gate.read_guard():
            return self.read_under_guard(product, attempt_id)

    def read_under_guard(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        attempt_id: str,
        *,
        allow_unpublished_stage: bool = False,
    ) -> IntentT | None:
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor():
            raw = self._io.read_private_receipt(
                self._path(product, attempt_id),
                maximum_bytes=self._maximum_bytes,
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
        product.assert_root_gc_authority_current()
        return intent

    def inspect(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> tuple[IntentT, ...]:
        self._require_product(product)
        with product.gc_gate.read_guard():
            return self.inspect_under_guard(product)

    def inspect_under_guard(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> tuple[IntentT, ...]:
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            names = windows_listdir_at(root)
            prefixed = {
                name for name in names
                if name.casefold().startswith(WINDOWS_WORKER_LAUNCH_INTENT_PREFIX)
            }
            histories = {
                name for name in prefixed if WINDOWS_WORKER_LAUNCH_INTENT_NAME.fullmatch(name)
            }
            if prefixed != histories or len(histories) > self._maximum_attempts:
                raise self._failure("inventory_unsafe")
            intents = []
            for name in sorted(histories):
                match = WINDOWS_WORKER_LAUNCH_INTENT_NAME.fullmatch(name)
                assert match is not None
                intent = self.read_under_guard(product, match.group(1))
                if intent is None:
                    raise self._failure("inventory_unsafe")
                intents.append(intent)
            if set(windows_listdir_at(root)) != set(names):
                raise self._failure("inventory_changed")
        product.assert_root_gc_authority_current()
        return tuple(intents)

    def commit_bound(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        receipt_owner: _WindowsWorkerProductReceiptAuthority[
            _PayloadReceiptT, _SelectedPayloadT
        ],
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        payload_lease: WindowsWorkerLaunchPayload,
        payload_program: WindowsProductWorkerPayload[
            _WindowsPayloadT, _WindowsPendingT, _PayloadAttemptT
        ],
    ) -> IntentT:
        self._require_product(product)
        if (
            type(receipt_owner) is not payload_program.receipt_owner_type
            or receipt_owner.product_owner is not product
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(request) is not ManagedWorkerLaunchRequestV1
            or type(payload_lease) is not payload_program.lease_type
            or request.identity.product_id != self._product_id
            or receipt.policy.product_id != self._product_id
            or request.identity.scope_id != receipt.policy.product_scope_id
            or request.identity.plugin_id != receipt.policy.plugin_id
            or request.identity.plugin_revision_digest
            != receipt.policy.plugin_revision_digest
            or (request.identity.contribution_id != receipt.policy.contribution_id)
            or (
                request.identity.owner_generation
                != receipt.policy.owner_selection_generation
            )
            or (
                request.identity.declaration_fingerprint
                != receipt.policy.declaration_fingerprint
            )
            or (
                request.identity.worker_configuration_fingerprint
                != receipt.policy.worker_configuration_fingerprint
            )
            or (request.identity.attempt_id != payload_lease.attempt_id)
            or (request.identity.owner_id != payload_lease.owner_id)
            or (request.runtime != payload_lease.runtime)
            or (receipt.fingerprint != payload_lease.receipt_fingerprint)
            or (request.runtime.executable_digest != payload_lease.payload_digest)
            or (
                (request.runtime.cwd_device, request.runtime.cwd_inode)
                != payload_lease.stage_identity
            )
        ):
            raise self._failure("binding_mismatch")
        intent = cast(Callable[..., IntentT], self._record_type)(
            attempt_id=payload_lease.attempt_id,
            stage_identity=payload_lease.stage_identity,
            receipt_fingerprint=receipt.fingerprint,
            request_fingerprint=request.fingerprint,
            identity_fingerprint=request.identity.fingerprint,
            runtime_fingerprint=request.runtime.fingerprint,
            payload_digest=payload_lease.payload_digest,
            owner_id=payload_lease.owner_id,
            supervisor_epoch=request.identity.supervisor_epoch,
        )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            payload_program.require_bound(
                receipt_owner=receipt_owner,
                receipt=receipt,
                payload_lease=payload_lease,
                request=request,
            )
            selected = receipt_owner.current_selected_payload(receipt)
            owner_id = receipt_owner.current_worker_owner_id(receipt)
            if (
                selected.digest != payload_lease.payload_digest
                or selected.configuration.fingerprint
                != request.runtime.worker_configuration_fingerprint
                or len(selected.body) != request.runtime.executable_size
                or owner_id != payload_lease.owner_id
            ):
                raise self._failure("selection_stale")
            payload_program.verify_stage(
                receipt_owner=receipt_owner,
                receipt=receipt,
                payload_lease=payload_lease,
                entrypoint=selected.configuration.entrypoint,
                initial=True,
            )
            request.runtime.verify()
            request.validate_current()
            existing = self.read_under_guard(
                product, intent.attempt_id, allow_unpublished_stage=True
            )
            if existing is not None:
                raise self._failure("attempt_reused")
            with product.epoch_runtime.borrow_product_state_root_descriptor():
                self._io.write_private_receipt(
                    self._path(product, intent.attempt_id),
                    intent.to_bytes(),
                    maximum_bytes=self._write_maximum_bytes,
                )
                if self.read_under_guard(product, intent.attempt_id) != intent:
                    raise self._failure("publication_changed")
            product.assert_root_gc_authority_current()
            return intent


class WindowsProductWorkerProvisioningAccess:
    """Load/CAS on the original actual Code object; policy hooks keep its rules.

    Binding, intent validation and stale native cleanup use the original
    selection, payload recovery and Journal owners, including exact constructor
    admission. The Product supplies its Profile; no parallel state is introduced.
    """

    _product: WindowsLocalWheelProductSessionOwner
    _runtime: PackageProductRuntimeBindingV1
    _receipt: ProductWorkerActivationReceiptV1
    _worker_request: ManagedWorkerLaunchRequestV1
    _journal: WindowsWorkerProvisioningStateJournal

    _product_id: str
    _provisioning_journal_type: type[WindowsWorkerProvisioningStateJournal]
    _selected: PackageProductSelectedPluginManifestV1

    @staticmethod
    def _session_scope_id(session_id: str) -> str:
        raise NotImplementedError("the Product session scope Profile is required")

    _read_launch_intent: Callable[
        [WindowsLocalWheelProductSessionOwner, str], WindowsLaunchIntentMethods | None
    ]

    def _recovery_payload(
        self,
    ) -> WindowsProductWorkerPayload[
        WindowsWorkerLaunchPayload, _PendingPayload, WindowsRecoveryAttemptV1
    ]:
        raise NotImplementedError("the existing Product recovery owner is required")

    def __init__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
    ) -> None:
        if os.name != "nt" or type(product) is not WindowsLocalWheelProductSessionOwner:
            raise OSError("Windows Worker Product provisioning owner is unavailable")
        if (
            type(selected) is not PackageProductSelectedPluginManifestV1
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(worker_request) is not ManagedWorkerLaunchRequestV1
            or (type(plan) is not _WindowsLpacProductWorkerProfilePlan)
        ):
            raise ValueError("Windows Worker Product selection is invalid")
        if (
            type(runtime) is not PackageProductRuntimeBindingV1
            or runtime.product_id != self._product_id
            or (not runtime.lifecycle.active)
            or (runtime.session_id != receipt.policy.session_id)
            or (runtime.product_runtime_id != receipt.policy.product_runtime_id)
        ):
            raise ValueError("Windows Worker Product runtime binding is invalid")
        self._bind_provisioning_attempt(
            product,
            runtime=runtime,
            selected=selected,
            receipt=receipt,
            worker_request=worker_request,
            plan=plan,
        )

    def _bind_provisioning_attempt(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
    ) -> None:
        assert runtime.session_id is not None
        session_scope_id = self._session_scope_id(runtime.session_id)
        product.assert_session_runtime_current(runtime)
        runtime.assert_selected_plugin_manifest_current(selected)
        selected_candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=receipt.policy.contribution_id,
            native_platform="windows-amd64",
        )
        candidate = (
            tuple(
                binding
                for binding in product.policy.bindings
                if binding.source_trust_class == "local-worker-candidate"
                and binding.plugin_id == receipt.policy.plugin_id
                and binding.artifact_digest == receipt.policy.plugin_revision_digest
                and binding.worker_admission is not None
                and binding.worker_admission.contribution_id
                == receipt.policy.contribution_id
                and binding.worker_admission.owner_id
                == worker_request.identity.owner_id
                and binding.worker_admission.native_platform == "windows-amd64"
            )
            if type(receipt) is ProductWorkerActivationReceiptV1
            and type(worker_request) is ManagedWorkerLaunchRequestV1
            else ()
        )
        if (
            type(receipt) is not ProductWorkerActivationReceiptV1
            or type(worker_request) is not ManagedWorkerLaunchRequestV1
            or type(plan) is not _WindowsLpacProductWorkerProfilePlan
            or product.policy.product_id != self._product_id
            or len(candidate) != 1
            or candidate[0].source_identity
            != selected.snapshot.package_revision.package_source_identity
            or candidate[0].artifact_digest
            != selected.snapshot.root_ref.artifact_digest
            or receipt.policy.product_id != self._product_id
            or not receipt.policy.enabled
            or receipt.policy.product_scope_id != session_scope_id
            or receipt.policy.native_profile_id != _WINDOWS_LPAC_PROFILE_ID
            or receipt.policy.native_profile_catalog_revision
            != plan.native_profile_catalog_revision
            or worker_request.identity.product_id != self._product_id
            or worker_request.identity.scope_id != session_scope_id
            or worker_request.identity.plugin_id != receipt.policy.plugin_id
            or worker_request.identity.plugin_revision_digest
            != receipt.policy.plugin_revision_digest
            or worker_request.identity.contribution_id != receipt.policy.contribution_id
            or worker_request.identity.owner_generation
            != receipt.policy.owner_selection_generation
            or worker_request.identity.declaration_fingerprint
            != receipt.policy.declaration_fingerprint
            or worker_request.identity.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
            or selected_candidate.plugin_id != receipt.policy.plugin_id
            or selected_candidate.owner_id != worker_request.identity.owner_id
            or selected_candidate.reservation_fingerprint
            != receipt.policy.reservation_fingerprint
            or selected_candidate.declaration_fingerprint
            != receipt.policy.declaration_fingerprint
            or selected_candidate.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
            or selected_candidate.executable_digest
            != worker_request.runtime.executable_digest
            or selected_candidate.executable_size
            != worker_request.runtime.executable_size
            or plan.worker_request_fingerprint != worker_request.fingerprint
            or plan.expected_native_policy_closure_fingerprint
            != receipt.policy.expected_native_policy_closure_fingerprint
        ):
            raise ValueError("Windows Worker Product provisioning binding is invalid")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard():
            self._require_launch_intent(
                product, receipt=receipt, worker_request=worker_request
            )
        identity = _windows_lpac_provisioning_identity(
            receipt=receipt,
            worker_request=worker_request,
            plan=plan,
        )
        attempt_id = worker_request.identity.attempt_id
        self._product = product
        self._runtime = runtime
        self._selected = selected
        self._receipt = receipt
        self._worker_request = worker_request
        self._journal = self._provisioning_journal_type(
            product.state_root / f"worker-native-provisioning-{attempt_id}.jsonl",
            identity=identity,
        )
        product.assert_root_gc_authority_current()

    def _require_launch_intent(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
    ) -> None:
        intent = self._read_launch_intent(product, worker_request.identity.attempt_id)
        if (
            intent is None
            or intent.receipt_fingerprint != receipt.fingerprint
            or intent.request_fingerprint != worker_request.fingerprint
            or intent.identity_fingerprint != worker_request.identity.fingerprint
            or intent.runtime_fingerprint != worker_request.runtime.fingerprint
            or intent.payload_digest != worker_request.runtime.executable_digest
            or intent.stage_identity
            != (
                worker_request.runtime.cwd_device,
                worker_request.runtime.cwd_inode,
            )
            or intent.owner_id != worker_request.identity.owner_id
            or intent.supervisor_epoch != worker_request.identity.supervisor_epoch
        ):
            raise ValueError("Windows Worker Product launch intent is invalid")

    def _require_store_current(
        self, *, desired_phase: object | None = None, write: bool = False
    ) -> None:
        try:
            self._runtime.assert_selected_plugin_manifest_current(self._selected)
            self._worker_request.validate_current()
            return
        except (PackageProductRuntimeReadError, WorkerBindingError) as stale:
            # Disable or update invalidates Product selection. A terminal
            # Supervisor may still be waiting for Hosting to close native
            # preparation before it can record physical process settlement.
            # Only this exact retained attempt may write cleanup phases.

            try:
                if write and desired_phase not in {
                    "debt",
                    "cleaning",
                    "revoke_effect",
                    "grants_revoked",
                    "delete_effect",
                    "profile_deleted",
                    "settled",
                }:
                    raise ValueError("Windows Worker stale write is not native cleanup")
                recovery = self._recovery_payload()
                inventory = recovery.inspect_inventory(self._product)
                inventory = recovery.current_attempts(
                    self._product,
                    inventory,
                    attempt_id=self._worker_request.identity.attempt_id,
                )
                recovery.admission.require_native_release(
                    inventory,
                    attempt_id=self._worker_request.identity.attempt_id,
                    payload_directory_identity=(
                        self._worker_request.runtime.cwd_device,
                        self._worker_request.runtime.cwd_inode,
                    ),
                    request_fingerprint=self._worker_request.fingerprint,
                    receipt_fingerprint=self._receipt.fingerprint,
                    identity_fingerprint=self._worker_request.identity.fingerprint,
                )
                self._worker_request.runtime.verify()
            except (OSError, RuntimeError, ValueError) as error:
                raise stale from error

    @property
    def path(self) -> Path:
        return self._journal.path

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


def review_windows_product_worker_offline(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    active_error: Callable[[], Exception],
    review: Callable[[PackageWindowsRuntimeQuiescenceV1], _ReviewT],
) -> _ReviewT:
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise active_error()
        with product.gc_gate.read_guard():
            return review(quiescence)


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
_PartialReviewT = TypeVar("_PartialReviewT", bound=_WindowsPartialStageReviewMethods)
_ReservedReviewT = TypeVar("_ReservedReviewT", bound=_WindowsReservedStageReviewMethods)
_PAYLOAD_MARKER = "worker-payload.json"
_PAYLOAD_MARKER_MAX_BYTES = 1024


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


def _open_windows_worker_stage(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    stage_name: str,
    inspection: WindowsStageInspection,
    acl: WindowsPrivateDirectoryAcl,
    *,
    error_type: type[Exception],
    error_prefix: str,
) -> int:
    """Verify the pinned Product root before opening the stage without write access."""
    inspection.require_direct(root, acl, directory=True)
    if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
        raise error_type(f"{error_prefix}_root_changed")
    return open_windows_directory(
        stage_name, dir_fd=root, share_delete=False, read_control=True
    )


def capture_windows_product_worker_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: _StageCaptureIntent,
    inspect: Callable[[], WindowsStageInspection],
) -> CapturedWindowsWorkerStage:
    """Capture the live tree against the exact Product launch-intent type."""
    inspection = inspect()
    if type(intent) is not inspection.intent_type:
        raise inspection.error_type(inspection.error_prefix + "_intent_invalid")
    return _capture_windows_product_worker_stage(
        product,
        attempt_id=attempt_id,
        expected_stage=expected_stage,
        intent=intent,
        inspection=inspection,
        max_payload_bytes=inspection.max_payload_bytes,
        error_type=inspection.error_type,
        error_prefix=inspection.error_prefix,
        result_factory=lambda captured: captured,
    )


def _capture_windows_product_worker_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: _StageCaptureIntent,
    inspection: WindowsStageInspection,
    max_payload_bytes: int,
    error_type: type[Exception],
    error_prefix: str,
    result_factory: Callable[[CapturedWindowsWorkerStage], StageReviewT],
) -> StageReviewT:
    """Construct the caller's pure result before the original root scopes exit."""
    stage_name = "worker-payload-" + attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            stage = _open_windows_worker_stage(
                product, root, stage_name, inspection, acl,
                error_type=error_type, error_prefix=error_prefix,
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
                    _PAYLOAD_MARKER,
                    acl,
                    maximum_bytes=_PAYLOAD_MARKER_MAX_BYTES,
                )
                entrypoint, marker_payload_size = inspection.verify_marker(
                    raw_marker, intent=intent, stage_identity=expected_stage
                )
                parts = entrypoint.split("/")
                if set(windows_listdir_at(stage)) != {_PAYLOAD_MARKER, parts[0]}:
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
                    or set(windows_listdir_at(stage)) != {_PAYLOAD_MARKER, parts[0]}
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


def capture_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int] | None,
    lease_owner_revision: int,
    record_type: type[_PartialReviewT],
    inspect: Callable[[], WindowsStageInspection],
    error_prefix: str,
) -> _PartialReviewT:
    """Capture a marker-absent stage without granting deletion authority."""
    inspection = inspect()
    max_payload_bytes = record_type._payload_maximum()
    max_depth = record_type._depth_maximum()
    error_type = record_type._record_error
    stage_name = "worker-payload-" + attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            stage = _open_windows_worker_stage(
                product, root, stage_name, inspection, acl,
                error_type=error_type, error_prefix=error_prefix,
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
                        name.casefold() == _PAYLOAD_MARKER for name in names
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
                    return cast(Callable[..., _PartialReviewT], record_type)(
                        attempt_id=attempt_id,
                        lease_owner_revision=lease_owner_revision,
                        stage_identity=stage_identity,
                        directory_identities=tuple(directories),
                        entrypoint=entrypoint,
                        executable_identity=executable_identity,
                        executable_digest=executable_digest,
                    )
                finally:
                    close_opened(opened)
            finally:
                os.close(stage)


def capture_windows_product_worker_reserved_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    intent: WindowsLaunchIntentMethods,
    native_revision: int | None,
    lease_owner_revision: int,
    record_type: type[_ReservedReviewT],
    inspection: Callable[[], WindowsStageInspection],
    error_prefix: str,
) -> _ReservedReviewT:
    """Capture the exact stage whose native reservation had no launch effect."""
    if native_revision not in (1, 2):
        raise record_type._record_error(error_prefix + "_history_unverified")
    build = cast(Callable[..., _ReservedReviewT], record_type)
    return _capture_windows_product_worker_stage(
        product,
        attempt_id=intent.attempt_id,
        expected_stage=intent.stage_identity,
        intent=intent,
        inspection=inspection(),
        max_payload_bytes=record_type._payload_maximum(),
        error_type=record_type._record_error,
        error_prefix=error_prefix,
        result_factory=lambda stage: build(
            attempt_id=intent.attempt_id,
            intent_fingerprint=intent.fingerprint,
            lease_owner_revision=lease_owner_revision,
            native_revision=native_revision,
            stage_identity=stage.stage_identity,
            directory_identities=stage.directory_identities,
            marker_identity=stage.marker_identity,
            executable_identity=stage.executable_identity,
            executable_digest=stage.executable_digest,
            entrypoint=stage.entrypoint,
        ),
    )


class _PinnedRecoveryStore:
    def __init__(
        self, journal: WindowsWorkerProvisioningStateJournal, root: int
    ) -> None:
        self._journal = journal
        self._root = root

    def load(self) -> Mapping[str, object] | None:
        return self._journal.load(directory_fd=self._root)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        return self._journal.compare_and_swap(
            expected_revision=expected_revision,
            document=document,
            directory_fd=self._root,
        )


def settle_windows_product_worker_native_cleanup(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    stage_name: str,
    attempt_id: str,
    identity: Mapping[str, object],
    expected_stage_identity: tuple[int, int],
    material_expectation: WindowsBackendMaterialExpectationV1,
    settlement_type: Callable[..., _ReviewT],
) -> _ReviewT:
    """Settle native debt only after the caller joins its Product recovery proof.

    The caller retains its Package orphan guard and writable GC guard. Keep
    the stage and pinned journal alive through final authority recheck and
    nominal result construction; no launch, lease repair or stage deletion.
    """
    verify_windows_backend_material_expectation(material_expectation)
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        stage = open_windows_directory(
            stage_name,
            dir_fd=root,
            share_delete=False,
            writable=False,
            read_control=True,
        )
        try:
            observed = os.fstat(stage)
            visible = windows_stat_at(root, stage_name)
            if (
                observed.st_dev,
                observed.st_ino,
            ) != expected_stage_identity or not os.path.samestat(observed, visible):
                raise ValueError("Windows Worker crash payload stage changed")
            spec = _rebuild_windows_lpac_cleanup_spec(
                identity=identity,
                runtime_root=product.state_root / stage_name,
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                owner_private_ancestors=True,
            )
            if (
                observe_windows_worker_job_absent(cast(str, identity["jobObjectName"]))
                is not True
            ):
                raise ValueError("Windows Worker crash Job is still present")
            journal = WindowsWorkerProvisioningStateJournal(
                product.state_root / f"worker-native-provisioning-{attempt_id}.jsonl",
                identity=identity,
            )
            _recover_windows_lpac_containment_cleanup(
                identity=identity,
                provision_spec=spec,
                provisioning_state_store=_PinnedRecoveryStore(journal, root),
            )
            latest = journal.load(directory_fd=root)
            if (
                latest is None
                or latest["phase"] != "settled"
                or not isinstance(latest["witness"], dict)
                or latest["witness"]["state"] != "SETTLED"
            ):
                raise ValueError("Windows Worker native cleanup did not settle")
            product.assert_root_gc_authority_current()
            return settlement_type(
                attempt_id=attempt_id,
                native_revision=cast(int, latest["stateRevision"]),
                spec_fingerprint=cast(str, identity["specFingerprint"]),
            )
        finally:
            os.close(stage)


@contextmanager
def windows_product_worker_offline_write(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    active_error: type[Exception],
    active_message: str,
) -> Iterator[PackageWindowsRuntimeQuiescenceV1]:
    """Hold Package quiescence then writable GC for an admitted mutation."""
    with windows_product_worker_quiescence(
        product, active_error=active_error, active_message=active_message
    ) as (_, quiescence):
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            yield quiescence


_PayloadReceiptT = TypeVar("_PayloadReceiptT", bound=_ReceiptRecordMethods)
_SelectedPayloadT = TypeVar(
    "_SelectedPayloadT", bound=ProductWorkerSelectedPayloadFacts
)
_WindowsPendingT = TypeVar("_WindowsPendingT", bound=_PendingPayload)
_PayloadAttemptT = TypeVar("_PayloadAttemptT", bound=WindowsRecoveryAttemptV1)


class WindowsWorkerLaunchPayload(_StageCaptureIntent, Protocol):
    @property
    def runtime(self) -> WorkerRuntimeBindingV1: ...


_WindowsPayloadT = TypeVar("_WindowsPayloadT", bound=WindowsWorkerLaunchPayload)


class _PayloadStageName(Protocol):
    @property
    def attempt_id(self) -> str: ...


class _CodedPayloadError(Protocol):
    @property
    def code(self) -> str: ...


_BOUND_REQUESTS_LOCK = threading.Lock()
_BOUND_REQUESTS: WeakKeyDictionary[
    Callable[[], None], tuple[int, str, str, tuple[int, int]]
] = WeakKeyDictionary()


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerPayload(
    Generic[_WindowsPayloadT, _WindowsPendingT, _PayloadAttemptT]
):
    """Original complete launch binding; the sole live request registry is preserved."""

    receipt_owner_type: type[object]
    lease_type: Callable[..., _WindowsPayloadT]
    pending_type: type[_WindowsPendingT]
    inspect_inventory: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[_PayloadAttemptT, ...]
    ]
    current_attempts: Callable[..., tuple[_PayloadAttemptT, ...]]
    inspect_payload: Callable[..., tuple[_PayloadStageName, ...]]
    supervisor_journal: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsSupervisorJournal
    ]
    admission: WindowsRecoveryAdmission[_PayloadAttemptT]
    limits: Callable[[], tuple[int, int]]
    marker_name: str
    error_type: type[RuntimeError]
    error_prefix: str
    stale_errors: tuple[type[Exception], ...]
    stale_message: str

    def _require_attempt(
        self,
        receipt_owner: object,
        receipt: object,
        attempt_id: str,
        message: str,
    ) -> None:
        if (
            os.name != "nt"
            or type(receipt_owner) is not self.receipt_owner_type
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(attempt_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}\Z", attempt_id) is None
        ):
            raise ValueError(message)

    def plan(
        self,
        *,
        receipt_owner: _WindowsWorkerProductReceiptAuthority[
            _PayloadReceiptT, _SelectedPayloadT
        ],
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
    ) -> _WindowsPendingT:
        """Pin a current Windows Worker identity before any payload or process."""
        self._require_attempt(
            receipt_owner,
            receipt,
            attempt_id,
            "Windows Worker pending launch request is invalid",
        )
        product = receipt_owner.product_owner
        with product.gc_gate.guard():
            if receipt_owner.current_witness(receipt) != receipt.authority_witness:
                raise self.error_type(self.error_prefix + "_selection_stale")
            selected, owner_id = receipt_owner.current_payload_and_worker_owner_id(
                receipt
            )
            if (
                selected.configuration.fingerprint
                != receipt.policy.worker_configuration_fingerprint
            ):
                raise self.error_type(self.error_prefix + "_selection_stale")
            receipt_owner.current_backend_capture_expectation(receipt)
            if any(
                (
                    item.attempt_id == attempt_id
                    for item in self.inspect_inventory(product)
                )
            ):
                raise self.error_type(self.error_prefix + "_attempt_reused")
            identity = worker_identity_from_receipt(
                receipt=receipt,
                owner_id=owner_id,
                attempt_id=attempt_id,
                supervisor_epoch=1,
                session_nonce=secrets.token_hex(32),
            )
            journal = self.supervisor_journal(product)
            if journal.status(attempt_id) is not None:
                raise self.error_type(self.error_prefix + "_attempt_reused")
            epoch = journal.next_supervisor_epoch(identity)
            product.assert_root_gc_authority_current()
            return cast(Callable[..., _WindowsPendingT], self.pending_type)(
                receipt_fingerprint=receipt.fingerprint,
                identity=replace(identity, supervisor_epoch=epoch),
            )

    def materialize(
        self,
        *,
        receipt_owner: _WindowsWorkerProductReceiptAuthority[
            _PayloadReceiptT, _SelectedPayloadT
        ],
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
    ) -> _WindowsPayloadT:
        """Copy one current selected PE to a fresh, Product-private attempt stage.

        A failure after directory creation deliberately leaves all bytes in place
        as recovery debt. Retrying the same attempt ID never overwrites them.
        """
        self._require_attempt(
            receipt_owner,
            receipt,
            attempt_id,
            "Windows Worker payload request is invalid",
        )
        product = receipt_owner.product_owner
        stage_name = "worker-payload-" + attempt_id
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            payload, owner_id = receipt_owner.current_payload_and_worker_owner_id(
                receipt
            )
            if (
                not 0 < len(payload.body) <= self.limits()[0]
                or sha256(payload.body).hexdigest() != payload.digest
            ):
                raise self.error_type(self.error_prefix + "_digest_changed")
            entrypoint = canonical_plugin_relative_path(
                payload.configuration.entrypoint
            ).as_posix()
            parts = entrypoint.split("/")
            if (
                entrypoint != payload.configuration.entrypoint
                or self.marker_name in parts
            ):
                raise self.error_type(self.error_prefix + "_entrypoint_invalid")
            retained = self.inspect_inventory(product)
            previous = next(
                (item for item in retained if item.attempt_id == attempt_id), None
            )
            if previous is not None:
                raise self.error_type(
                    self.error_prefix + "_attempt_reused"
                    if previous.payload_directory_identity is None
                    or previous.native_phase is not None
                    or previous.supervisor_phase is not None
                    or (previous.launch_request_fingerprint is not None)
                    else self.error_prefix + "_attempt_debt"
                )
            if len(retained) >= self.limits()[1]:
                raise self.error_type(self.error_prefix + "_capacity")
            with WindowsPrivateDirectoryAcl() as acl:
                with (
                    product.epoch_runtime.borrow_product_state_root_descriptor() as root
                ):
                    acl.validate(root)
                    require_payload_root(
                        product.state_root,
                        root,
                        error_type=self.error_type,
                        error_prefix=self.error_prefix,
                    )
                    inventory = self.inspect_payload(
                        product.state_root, directory_fd=root
                    )
                    if any((item.attempt_id == attempt_id for item in inventory)):
                        raise self.error_type(self.error_prefix + "_attempt_debt")
                    if len(inventory) >= self.limits()[1]:
                        raise self.error_type(self.error_prefix + "_capacity")

                    def complete(
                        runtime: WorkerRuntimeBindingV1, stage_identity: tuple[int, int]
                    ) -> _WindowsPayloadT:
                        if (
                            receipt_owner.current_witness(receipt)
                            != receipt.authority_witness
                        ):
                            raise self.error_type(
                                self.error_prefix + "_selection_stale"
                            )
                        product.assert_root_gc_authority_current()
                        return self.lease_type(
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
                        marker_name=self.marker_name,
                        complete=complete,
                        error_type=self.error_type,
                        error_prefix=self.error_prefix,
                    )

    def bind(
        self,
        *,
        receipt_owner: _WindowsWorkerProductReceiptAuthority[
            _PayloadReceiptT, _SelectedPayloadT
        ],
        receipt: ProductWorkerActivationReceiptV1,
        payload_lease: _WindowsPayloadT,
        supervisor_epoch: int,
        pending_launch: _WindowsPendingT | None = None,
    ) -> ManagedWorkerLaunchRequestV1:
        """Build an exact request for a staged PE; no process effect occurs here."""
        if (
            os.name != "nt"
            or type(receipt_owner) is not self.receipt_owner_type
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(payload_lease) is not self.lease_type
        ):
            raise self.error_type(self.error_prefix + "_binding_mismatch")
        if (
            type(supervisor_epoch) is not int
            or supervisor_epoch < 1
            or payload_lease.receipt_fingerprint != receipt.fingerprint
            or (
                payload_lease.runtime.package_root
                != receipt_owner.product_owner.state_root
                / ("worker-payload-" + payload_lease.attempt_id)
            )
        ):
            raise self.error_type(self.error_prefix + "_binding_mismatch")
        product = receipt_owner.product_owner
        bound_request: ManagedWorkerLaunchRequestV1 | None = None

        def verify_current(*, initial: bool) -> None:
            with product.gc_gate.guard():
                product.assert_root_gc_authority_current()
                if initial != (bound_request is None):
                    raise self.error_type(self.error_prefix + "_binding_mismatch")
                inventory = self.inspect_inventory(product)
                try:
                    inventory = self.current_attempts(
                        product, inventory, attempt_id=payload_lease.attempt_id
                    )
                    self.admission.require_current(
                        inventory,
                        attempt_id=payload_lease.attempt_id,
                        payload_directory_identity=payload_lease.stage_identity,
                        initial=initial,
                        request_fingerprint=None
                        if bound_request is None
                        else bound_request.fingerprint,
                        receipt_fingerprint=None if initial else receipt.fingerprint,
                        identity_fingerprint=None
                        if bound_request is None
                        else bound_request.identity.fingerprint,
                    )
                except self.admission.error_type as exc:
                    raise self.error_type(cast(_CodedPayloadError, exc).code) from exc
                selected, owner_id = receipt_owner.current_payload_and_worker_owner_id(
                    receipt
                )
                if (
                    selected.digest != payload_lease.payload_digest
                    or selected.configuration.fingerprint
                    != payload_lease.runtime.worker_configuration_fingerprint
                    or len(selected.body) != payload_lease.runtime.executable_size
                    or (owner_id != payload_lease.owner_id)
                ):
                    raise self.error_type(self.error_prefix + "_binding_mismatch")
                self.verify_stage(
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
                require_current_pending_launch(
                    pending_launch,
                    pending_type=self.pending_type,
                    receipt=receipt,
                    owner_id=payload_lease.owner_id,
                    attempt_id=payload_lease.attempt_id,
                    supervisor_epoch=supervisor_epoch,
                    supervisor=partial(self.supervisor_journal, product),
                    error_type=self.error_type,
                    error_prefix=self.error_prefix,
                )

        def validate_current() -> None:
            try:
                verify_current(initial=False)
            except self.stale_errors as exc:
                raise WorkerBindingError(
                    self.stale_message, code="worker_product_selection_stale"
                ) from exc

        identity = (
            pending_launch.identity
            if pending_launch is not None
            else worker_identity_from_receipt(
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

    def require_bound(
        self,
        *,
        receipt_owner: object,
        receipt: ProductWorkerActivationReceiptV1,
        payload_lease: WindowsWorkerLaunchPayload,
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
            raise self.error_type(self.error_prefix + "_request_unbound")

    def verify_stage(
        self,
        *,
        receipt_owner: _WindowsWorkerProductReceiptAuthority[
            _PayloadReceiptT, _SelectedPayloadT
        ],
        receipt: ProductWorkerActivationReceiptV1,
        payload_lease: WindowsWorkerLaunchPayload,
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
            marker_name=self.marker_name,
            error_type=self.error_type,
            error_prefix=self.error_prefix,
        )


_ATTEMPT_ID = re.compile(r"[0-9a-f]{32}\Z")


def is_windows_product(
    product: WindowsLocalWheelProductSessionOwner,
    product_id: str,
    platform: str,
    owner_type: type[WindowsLocalWheelProductSessionOwner] = (
        WindowsLocalWheelProductSessionOwner
    ),
) -> bool:
    return not (
        platform != "nt"
        or type(product) is not owner_type
        or product.policy.product_id != product_id
    )


def is_attempt_id(attempt_id: object) -> bool:
    return type(attempt_id) is str and _ATTEMPT_ID.fullmatch(attempt_id) is not None
