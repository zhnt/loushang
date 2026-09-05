"""Confined Product-to-H6 native profile binding.

The public protocol is deliberately authority-free and handle-free.  Trusted
Harness composition binds one immutable Product receipt and Worker request to
one private Linux H6 capture specification.  Hosting still owns every native
resource and the unique process effect.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import platform
import re
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from loushang.hosting import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)

from .contracts import ManagedWorkerLaunchRequestV1, WorkerBindingError
from .product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

_POSIX_CONTAINED_PROFILE_ID = "posix-static-contained-elf-v1"
_POSIX_PLATFORM_IDENTITY = "platform:linux-x86_64-syscall-abi"
_WINDOWS_LPAC_PROFILE_ID = "windows-lpac-contained-pe-v1"
_CONTAINMENT_ARGUMENT_PROTOCOL = "loushang-static-containment-launch/v1"
_EXECUTION_CLOSURE_DOMAIN = "loushang.worker.native-execution-closure/v1"
_WINDOWS_OPERATION_NONCE_DOMAIN = "loushang.worker.windows-lpac-operation/v1"
_WINDOWS_LIFECYCLE_DOMAIN = "loushang.worker.windows-lpac-lifecycle/v1"
_WINDOWS_JOURNAL_VERSION = 1
_WINDOWS_CLEANUP_CONTRACT_VERSION = 2
_SUPPORTED_MACHINES = frozenset({"amd64", "x86_64"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HEX32 = re.compile(r"[0-9a-f]{32}")
_MAX_PLATFORM_FACT_BYTES = 256

_PlatformProbe = Callable[[], tuple[str, str, str, str]]
_NativeCapture = Callable[[object], Awaitable[object]]


@runtime_checkable
class ProductWorkerNativeProfilePort(Protocol):
    """One receipt/request-bound, single-use native preparation capability.

    The capture result is opaque because it belongs to Hosting.  Product code
    may pass this capability to the Worker composition root but cannot inspect
    or manufacture native material.
    """

    @property
    def receipt_fingerprint(self) -> str: ...

    @property
    def worker_request_fingerprint(self) -> str: ...

    @property
    def native_profile_id(self) -> str: ...

    @property
    def native_profile_catalog_revision(self) -> str: ...

    @property
    def realized_native_policy_closure_fingerprint(self) -> str: ...

    @property
    def execution_closure_fingerprint(self) -> str: ...

    @property
    def cleanup_contract_version(self) -> int: ...

    async def capture_native(
        self,
        request: ProcessLaunchRequest,
        *,
        capture: _NativeCapture,
    ) -> object: ...

    async def verify_current(self) -> None: ...

    def native_containment_settlement_witness(self) -> object | None: ...

    async def close(self) -> None: ...


class _PosixStaticContainedProductWorkerProfile(ProductWorkerNativeProfilePort):
    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        native_profile_catalog_revision: str,
        launcher_path: Path,
        launcher_sha256: str,
        containment_profile_sha256: str,
        platform_probe: _PlatformProbe,
    ) -> None:
        _require_exact_binding(receipt=receipt, worker_request=worker_request)
        policy = receipt.policy
        if native_profile_catalog_revision != policy.native_profile_catalog_revision:
            raise WorkerBindingError(
                "Worker native profile catalog changed",
                code="worker_native_profile_catalog_mismatch",
            )
        if policy.native_profile_id != _POSIX_CONTAINED_PROFILE_ID:
            raise WorkerBindingError(
                "Worker native profile is unsupported",
                code="worker_native_profile_unsupported",
            )
        if (
            not launcher_path.is_absolute()
            or "\0" in str(launcher_path)
            or not str(launcher_path)
        ):
            raise ValueError("Worker native launcher path is invalid")
        _require_sha256(launcher_sha256, name="launcher")
        _require_sha256(containment_profile_sha256, name="containment profile")
        if not callable(platform_probe):
            raise TypeError("Worker native profile requires a platform probe")
        if worker_request.runtime.cwd_inode < 1:
            raise WorkerBindingError(
                "Worker native cwd identity is unavailable",
                code="worker_native_cwd_identity_unavailable",
            )

        realized_policy_closure = (
            ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
                native_profile_catalog_revision=native_profile_catalog_revision,
                native_profile_id=policy.native_profile_id,
                payload_sha256=worker_request.runtime.executable_digest,
                containment_launcher_sha256=launcher_sha256,
                containment_profile_sha256=containment_profile_sha256,
            )
        )
        if realized_policy_closure != policy.expected_native_policy_closure_fingerprint:
            raise WorkerBindingError(
                "Worker native policy closure changed",
                code="worker_native_policy_closure_mismatch",
            )

        execution_closure = (
            f"containment-launcher-static-elf:sha256:{launcher_sha256}",
            (f"payload-static-elf:sha256:{worker_request.runtime.executable_digest}"),
            (
                "cwd:posix:"
                f"{worker_request.runtime.cwd_device}:"
                f"{worker_request.runtime.cwd_inode}"
            ),
            f"containment-profile:sha256:{containment_profile_sha256}",
            f"invocation:{_CONTAINMENT_ARGUMENT_PROTOCOL}",
            _POSIX_PLATFORM_IDENTITY,
        )
        self._receipt = receipt
        self._worker_request = worker_request
        self._catalog_revision = native_profile_catalog_revision
        self._launcher_path = launcher_path
        self._launcher_sha256 = launcher_sha256
        self._containment_profile_sha256 = containment_profile_sha256
        self._platform_probe = platform_probe
        self._realized_policy_closure = realized_policy_closure
        self._execution_closure = execution_closure
        self._execution_closure_fingerprint = _closure_fingerprint(execution_closure)
        self._state = "ready"
        self._captured = False
        self._lock = threading.Lock()

    @property
    def receipt_fingerprint(self) -> str:
        return self._receipt.fingerprint

    @property
    def worker_request_fingerprint(self) -> str:
        return self._worker_request.fingerprint

    @property
    def native_profile_id(self) -> str:
        return self._receipt.policy.native_profile_id

    @property
    def native_profile_catalog_revision(self) -> str:
        return self._catalog_revision

    @property
    def realized_native_policy_closure_fingerprint(self) -> str:
        return self._realized_policy_closure

    @property
    def execution_closure_fingerprint(self) -> str:
        return self._execution_closure_fingerprint

    @property
    def cleanup_contract_version(self) -> int:
        return 1

    async def capture_native(
        self,
        request: ProcessLaunchRequest,
        *,
        capture: _NativeCapture,
    ) -> object:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("Worker native profile requires a process request")
        if not callable(capture):
            raise TypeError("Worker native profile requires a capture capability")
        with self._lock:
            if self._state != "ready":
                raise WorkerBindingError(
                    "Worker native profile is no longer available",
                    code="worker_native_profile_consumed",
                )
            _require_process_request(request, worker_request=self._worker_request)
            self._state = "capturing"

        try:
            _require_linux_x86_64(self._platform_probe)
            spec = self._capture_spec(request)
            binding = await capture(spec)
        except BaseException:
            with self._lock:
                if self._state == "capturing":
                    self._state = "faulted"
            raise

        with self._lock:
            if self._state != "capturing":
                raise WorkerBindingError(
                    "Worker native profile was closed during capture",
                    code="worker_native_profile_consumed",
                )
            self._state = "captured"
            self._captured = True
        return binding

    def _capture_spec(self, request: ProcessLaunchRequest) -> object:
        # These are the only private platform symbols this friend boundary may
        # load.  Loading occurs after Product selection and the non-WSL gate.
        from loushang.hosting._posix_launch_preparation import (
            _PosixStaticContainedLaunchCaptureSpec,
            _PosixStaticLaunchCaptureBackend,
        )

        if _PosixStaticLaunchCaptureBackend.backend_id != "posix-process-group-v1":
            raise WorkerBindingError(
                "Worker native backend identity changed",
                code="worker_native_backend_mismatch",
            )
        return _PosixStaticContainedLaunchCaptureSpec(
            request=request,
            profile_id=_POSIX_CONTAINED_PROFILE_ID,
            execution_closure=self._execution_closure,
            launcher_path=str(self._launcher_path),
            launcher_sha256=self._launcher_sha256,
            executable_sha256=self._worker_request.runtime.executable_digest,
            cwd_device=self._worker_request.runtime.cwd_device,
            cwd_inode=self._worker_request.runtime.cwd_inode,
            containment_profile_sha256=self._containment_profile_sha256,
        )

    async def verify_current(self) -> None:
        with self._lock:
            if self._state != "captured" or not self._captured:
                raise WorkerBindingError(
                    "Worker native profile is not captured",
                    code="worker_native_profile_not_captured",
                )
        _require_exact_binding(
            receipt=self._receipt,
            worker_request=self._worker_request,
        )

    def native_containment_settlement_witness(self) -> object | None:
        return None

    async def close(self) -> None:
        with self._lock:
            self._state = "closed"


def _bind_posix_static_contained_product_worker_profile(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    worker_request: ManagedWorkerLaunchRequestV1,
    native_profile_catalog_revision: str,
    launcher_path: str | Path,
    launcher_sha256: str,
    containment_profile_sha256: str,
    _platform_probe: _PlatformProbe | None = None,
) -> ProductWorkerNativeProfilePort:
    """Bind one trusted Linux profile without activating a Product route."""

    return _PosixStaticContainedProductWorkerProfile(
        receipt=receipt,
        worker_request=worker_request,
        native_profile_catalog_revision=native_profile_catalog_revision,
        launcher_path=Path(launcher_path),
        launcher_sha256=launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
        platform_probe=_platform_probe or _observe_platform,
    )


@dataclass(frozen=True, slots=True)
class _WindowsLpacProductWorkerProfilePlan:
    """Pathless, pre-effect policy input for one exact Windows attempt."""

    worker_request_fingerprint: str
    native_profile_catalog_revision: str
    containment_launcher_sha256: str
    containment_profile_sha256: str
    expected_native_policy_closure_fingerprint: str
    operation_nonce: str
    lifecycle_fingerprint: str

    def __post_init__(self) -> None:
        _require_sha256(self.worker_request_fingerprint, name="request")
        _require_opaque(
            self.native_profile_catalog_revision,
            name="profile catalog revision",
        )
        for name, value in (
            ("containment launcher", self.containment_launcher_sha256),
            ("containment profile", self.containment_profile_sha256),
            ("native policy closure", self.expected_native_policy_closure_fingerprint),
            ("operation nonce", self.operation_nonce),
            ("lifecycle", self.lifecycle_fingerprint),
        ):
            _require_sha256(value, name=name)


@dataclass(frozen=True, slots=True)
class _WindowsNativeContainmentSettlementWitness:
    """Pathless proof token minted only after the durable native join settles."""

    receipt_fingerprint: str
    worker_request_fingerprint: str
    attempt_id: str
    owner_generation: int
    journal_fingerprint: str

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_fingerprint, name="receipt")
        _require_sha256(self.worker_request_fingerprint, name="request")
        _require_sha256(self.journal_fingerprint, name="settlement journal")
        if (
            not isinstance(self.attempt_id, str)
            or _HEX32.fullmatch(self.attempt_id) is None
        ):
            raise ValueError("Worker native settlement attempt id is invalid")
        if type(self.owner_generation) is not int or self.owner_generation < 1:
            raise ValueError("Worker native settlement generation is invalid")


@dataclass(frozen=True, slots=True)
class _WindowsLpacRuntimeBindings:
    build_provision_spec: Callable[..., object]
    provisioner_factory: Callable[[], object]
    build_capture_spec: Callable[..., object]
    spec_fingerprint: Callable[..., str]
    witness_factory: Callable[..., object]
    profile_collision_type: type[BaseException]
    capture_backend_id: str


class _WindowsLpacProvisioningStateStore(Protocol):
    def load(self) -> Mapping[str, object] | None: ...

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: Mapping[str, object],
    ) -> bool: ...


class _WindowsLpacProvisionerPort(Protocol):
    def create_profile(
        self, spec: object, *, begin_effect: Callable[[], None]
    ) -> object: ...

    def apply_grants(
        self,
        spec: object,
        witness: object,
        *,
        begin_effect: Callable[[], None],
    ) -> object: ...

    def verify(self, spec: object, witness: object) -> object: ...

    def revoke_grants(
        self,
        spec: object,
        witness: object,
        *,
        begin_effect: Callable[[], None],
    ) -> object: ...

    def delete_profile(
        self,
        spec: object,
        witness: object,
        *,
        begin_effect: Callable[[], None],
    ) -> object: ...

    def settle(self, spec: object, witness: object) -> object: ...

    def mark_debt(self, spec: object, witness: object) -> object: ...

    def recover_cleanup_witness(self, spec: object) -> object: ...


_WINDOWS_JOURNAL_FIELDS = frozenset(
    {
        "attemptId",
        "journalVersion",
        "lifecycleFingerprint",
        "nativeProfileCatalogRevision",
        "nativeProfileId",
        "operationNonce",
        "ownerGeneration",
        "phase",
        "receiptFingerprint",
        "specFingerprint",
        "stateRevision",
        "witness",
        "workerRequestFingerprint",
    }
)
_WINDOWS_WITNESS_FIELDS = frozenset(
    {
        "attemptId",
        "grantDigest",
        "operationNonce",
        "platformIdentity",
        "privateStateFingerprint",
        "profileFingerprint",
        "sidFingerprint",
        "specFingerprint",
        "state",
    }
)
_WINDOWS_JOURNAL_PHASES = frozenset(
    {
        "reserved",
        "profile_effect",
        "profile_created",
        "grant_effect",
        "grants_applied",
        "verified",
        "active",
        "cleaning",
        "revoke_effect",
        "grants_revoked",
        "delete_effect",
        "profile_deleted",
        "debt",
        "settled",
    }
)
_WINDOWS_WITNESS_STATES = frozenset(
    {
        "PROFILE_CREATED",
        "GRANTS_APPLIED",
        "VERIFIED",
        "ACTIVE",
        "CLEANING",
        "GRANTS_REVOKED",
        "PROFILE_DELETED",
        "DEBT",
        "SETTLED",
    }
)
_WINDOWS_PHASE_WITNESS_STATES: Mapping[str, frozenset[str | None]] = {
    "reserved": frozenset({None}),
    "profile_effect": frozenset({None}),
    "profile_created": frozenset({"PROFILE_CREATED"}),
    "grant_effect": frozenset({"PROFILE_CREATED"}),
    "grants_applied": frozenset({"GRANTS_APPLIED"}),
    "verified": frozenset({"VERIFIED"}),
    "active": frozenset({"VERIFIED", "ACTIVE"}),
    "cleaning": frozenset({"DEBT", "CLEANING"}),
    "revoke_effect": frozenset({"DEBT", "CLEANING"}),
    "grants_revoked": frozenset({"GRANTS_REVOKED"}),
    "delete_effect": frozenset({"GRANTS_REVOKED"}),
    "profile_deleted": frozenset({"PROFILE_DELETED"}),
    "debt": frozenset({"DEBT"}),
    "settled": frozenset({None, "SETTLED"}),
}


class _WindowsLpacProvisioningJournal:
    """Strict pathless CAS record scoped to one Product-owned attempt store."""

    def __init__(
        self,
        *,
        store: _WindowsLpacProvisioningStateStore,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
    ) -> None:
        self._load = _bind_static_method(store, "load")
        self._compare_and_swap = _bind_static_method(store, "compare_and_swap")
        self._lock = threading.RLock()
        self._callback_lock = threading.RLock()
        self._callback_active = False
        self._identity = {
            "attemptId": worker_request.identity.attempt_id,
            "journalVersion": _WINDOWS_JOURNAL_VERSION,
            "lifecycleFingerprint": plan.lifecycle_fingerprint,
            "nativeProfileCatalogRevision": plan.native_profile_catalog_revision,
            "nativeProfileId": _WINDOWS_LPAC_PROFILE_ID,
            "operationNonce": plan.operation_nonce,
            "ownerGeneration": worker_request.identity.owner_generation,
            "receiptFingerprint": receipt.fingerprint,
            "specFingerprint": plan.containment_profile_sha256,
            "workerRequestFingerprint": worker_request.fingerprint,
        }
        loaded = self._call_store(self._load)
        if loaded is None:
            initial = {
                **self._identity,
                "phase": "reserved",
                "stateRevision": 1,
                "witness": None,
            }
            self._document = _validate_windows_journal(initial, self._identity)
            self._persisted = False
            self.resumed = False
        else:
            self._document = _validate_windows_journal(loaded, self._identity)
            self._persisted = True
            self.resumed = True

    def reserve(self) -> None:
        """Commit the no-native-effect fence immediately before first capture."""

        with self._lock:
            if self._persisted:
                return
            try:
                initialized = self._call_store(
                    self._compare_and_swap,
                    expected_revision=0,
                    document=self._document,
                )
            except BaseException:
                loaded = self._call_store(self._load)
                if loaded is None:
                    raise
                self._document = _validate_windows_journal(loaded, self._identity)
                self._persisted = True
                self.resumed = True
                return
            if initialized is True:
                self._persisted = True
                return
            loaded = self._call_store(self._load)
            if loaded is None:
                raise WorkerBindingError(
                    "Worker native provisioning reservation raced",
                    code="worker_native_provisioning_store_raced",
                )
            self._document = _validate_windows_journal(loaded, self._identity)
            self._persisted = True
            self.resumed = True

    @property
    def phase(self) -> str:
        with self._lock:
            current = self._reload() if self._persisted else self._document
            return cast(str, current["phase"])

    @property
    def witness_document(self) -> Mapping[str, object] | None:
        with self._lock:
            current = self._reload() if self._persisted else self._document
            value = current["witness"]
            return cast(Mapping[str, object] | None, _json_copy(value))

    def advance(
        self,
        *,
        expected: frozenset[str],
        phase: str,
        witness: object | None,
    ) -> None:
        if phase not in _WINDOWS_JOURNAL_PHASES:
            raise ValueError("Worker native provisioning phase is unsupported")
        with self._lock:
            if not self._persisted:
                raise WorkerBindingError(
                    "Worker native provisioning reservation is absent",
                    code="worker_native_provisioning_state_missing",
                )
            current = self._reload()
            witness_document = (
                None if witness is None else _windows_witness_document(witness)
            )
            desired = {
                **current,
                "phase": phase,
                "stateRevision": cast(int, current["stateRevision"]) + 1,
                "witness": witness_document,
            }
            desired = _validate_windows_journal(desired, self._identity)
            if current["phase"] == phase and current["witness"] == witness_document:
                self._document = current
                return
            if current["phase"] not in expected:
                raise WorkerBindingError(
                    "Worker native provisioning state changed",
                    code="worker_native_provisioning_state_changed",
                )
            try:
                committed = self._call_store(
                    self._compare_and_swap,
                    expected_revision=cast(int, current["stateRevision"]),
                    document=desired,
                )
            except BaseException:
                observed = self._reload()
                if (
                    observed["phase"] == phase
                    and observed["witness"] == witness_document
                ):
                    return
                raise
            if committed is True:
                self._document = desired
                return
            observed = self._reload()
            if observed["phase"] == phase and observed["witness"] == witness_document:
                return
            raise WorkerBindingError(
                "Worker native provisioning commit was ambiguous",
                code="worker_native_provisioning_commit_ambiguous",
            )

    def settlement_witness(self) -> _WindowsNativeContainmentSettlementWitness:
        with self._lock:
            current = self._reload()
            if current["phase"] != "settled":
                raise WorkerBindingError(
                    "Worker native containment is not settled",
                    code="worker_native_containment_unsettled",
                )
            return _WindowsNativeContainmentSettlementWitness(
                receipt_fingerprint=cast(str, current["receiptFingerprint"]),
                worker_request_fingerprint=cast(
                    str,
                    current["workerRequestFingerprint"],
                ),
                attempt_id=cast(str, current["attemptId"]),
                owner_generation=cast(int, current["ownerGeneration"]),
                journal_fingerprint=_document_fingerprint(
                    "loushang.worker.windows-lpac-settlement/v1",
                    current,
                ),
            )

    def _reload(self) -> dict[str, object]:
        loaded = self._call_store(self._load)
        if loaded is None:
            raise WorkerBindingError(
                "Worker native provisioning state disappeared",
                code="worker_native_provisioning_state_missing",
            )
        self._document = _validate_windows_journal(loaded, self._identity)
        return self._document

    def _call_store(
        self,
        callback: Callable[..., object],
        **arguments: object,
    ) -> object:
        with self._callback_lock:
            if self._callback_active:
                raise WorkerBindingError(
                    "Worker native provisioning store reentered",
                    code="worker_native_provisioning_store_reentered",
                )
            self._callback_active = True
            try:
                return callback(**arguments)
            finally:
                self._callback_active = False


class _WindowsLpacContainedProductWorkerProfile(ProductWorkerNativeProfilePort):
    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
        provision_spec: object,
        bindings: _WindowsLpacRuntimeBindings,
        journal: _WindowsLpacProvisioningJournal,
    ) -> None:
        self._receipt = receipt
        self._worker_request = worker_request
        self._plan = plan
        self._spec = provision_spec
        self._bindings = bindings
        self._journal = journal
        self._provisioner = cast(
            _WindowsLpacProvisionerPort,
            bindings.provisioner_factory(),
        )
        self._witness: object | None = None
        self._prepared_request: ProcessLaunchRequest | None = None
        self._execution_closure_fingerprint: str | None = None
        self._state = "ready"
        self._lock = threading.Lock()

    @property
    def receipt_fingerprint(self) -> str:
        return self._receipt.fingerprint

    @property
    def worker_request_fingerprint(self) -> str:
        return self._worker_request.fingerprint

    @property
    def native_profile_id(self) -> str:
        return _WINDOWS_LPAC_PROFILE_ID

    @property
    def native_profile_catalog_revision(self) -> str:
        return self._plan.native_profile_catalog_revision

    @property
    def realized_native_policy_closure_fingerprint(self) -> str:
        return self._plan.expected_native_policy_closure_fingerprint

    @property
    def execution_closure_fingerprint(self) -> str:
        value = self._execution_closure_fingerprint
        if value is None:
            raise WorkerBindingError(
                "Worker native profile has not been captured",
                code="worker_native_profile_not_captured",
            )
        return value

    @property
    def cleanup_contract_version(self) -> int:
        return _WINDOWS_CLEANUP_CONTRACT_VERSION

    async def capture_native(
        self,
        request: ProcessLaunchRequest,
        *,
        capture: _NativeCapture,
    ) -> object:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("Worker native profile requires a process request")
        if not callable(capture):
            raise TypeError("Worker native profile requires a capture capability")
        _require_process_request(request, worker_request=self._worker_request)
        with self._lock:
            if self._state != "ready":
                raise WorkerBindingError(
                    "Worker native profile is not a fresh attempt",
                    code="worker_native_profile_cleanup_required",
                )
            self._journal.reserve()
            if self._journal.resumed:
                raise WorkerBindingError(
                    "Worker native profile is not a fresh attempt",
                    code="worker_native_profile_cleanup_required",
                )
            self._state = "capturing"

        create_effect_started = False
        witness: object | None = None

        def begin_create() -> None:
            nonlocal create_effect_started
            self._journal.advance(
                expected=frozenset({"reserved"}),
                phase="profile_effect",
                witness=None,
            )
            create_effect_started = True

        try:
            witness = self._provisioner.create_profile(
                self._spec,
                begin_effect=begin_create,
            )
            self._witness = witness
            self._journal.advance(
                expected=frozenset({"profile_effect"}),
                phase="profile_created",
                witness=witness,
            )

            def begin_grants() -> None:
                self._journal.advance(
                    expected=frozenset({"profile_created"}),
                    phase="grant_effect",
                    witness=witness,
                )

            witness = self._provisioner.apply_grants(
                self._spec,
                witness,
                begin_effect=begin_grants,
            )
            self._witness = witness
            self._journal.advance(
                expected=frozenset({"grant_effect"}),
                phase="grants_applied",
                witness=witness,
            )
            witness = self._provisioner.verify(self._spec, witness)
            self._witness = witness
            self._journal.advance(
                expected=frozenset({"grants_applied"}),
                phase="verified",
                witness=witness,
            )
            capture_spec = self._bindings.build_capture_spec(
                getattr(self._spec, "request", None),
                provision=self._spec,
                witness=witness,
            )
            prepared_request = getattr(capture_spec, "request", None)
            execution_closure = getattr(capture_spec, "execution_closure", None)
            if not isinstance(prepared_request, ProcessLaunchRequest) or not isinstance(
                execution_closure,
                tuple,
            ):
                raise WorkerBindingError(
                    "Worker native capture profile is invalid",
                    code="worker_native_capture_profile_invalid",
                )
            self._prepared_request = prepared_request
            self._execution_closure_fingerprint = _closure_fingerprint(
                execution_closure
            )
            self._journal.advance(
                expected=frozenset({"verified"}),
                phase="active",
                witness=witness,
            )
            binding = await capture(capture_spec)
        except BaseException as error:
            with self._lock:
                self._state = "faulted"
            if isinstance(error, self._bindings.profile_collision_type):
                self._journal.advance(
                    expected=frozenset({"profile_effect"}),
                    phase="settled",
                    witness=None,
                )
            elif not create_effect_started:
                self._journal.advance(
                    expected=frozenset({"reserved"}),
                    phase="settled",
                    witness=None,
                )
            else:
                self._record_native_debt(witness)
            raise

        with self._lock:
            if self._state != "capturing":
                raise WorkerBindingError(
                    "Worker native profile was closed during capture",
                    code="worker_native_profile_consumed",
                )
            self._state = "captured"
        return binding

    async def verify_current(self) -> None:
        with self._lock:
            if self._state != "captured" or self._witness is None:
                raise WorkerBindingError(
                    "Worker native profile is not captured",
                    code="worker_native_profile_not_captured",
                )
            witness = self._witness
        _require_exact_binding(
            receipt=self._receipt,
            worker_request=self._worker_request,
        )
        self._provisioner.verify(self._spec, witness)

    async def close(self) -> None:
        with self._lock:
            if self._state == "capturing":
                raise WorkerBindingError(
                    "Worker native profile capture is still active",
                    code="worker_native_profile_cleanup_pending",
                )
            if self._state == "closed" and self._journal.phase == "settled":
                return
            self._state = "closing"
        try:
            self._close_native()
        except BaseException:
            self._record_native_debt(self._witness)
            with self._lock:
                self._state = "faulted"
            raise
        with self._lock:
            self._state = "closed"

    def native_containment_settlement_witness(self) -> object | None:
        with self._lock:
            if self._state != "closed":
                raise WorkerBindingError(
                    "Worker native containment is not settled",
                    code="worker_native_containment_unsettled",
                )
        return self._journal.settlement_witness()

    def prepared_request(self) -> ProcessLaunchRequest:
        request = self._prepared_request
        if request is None:
            raise WorkerBindingError(
                "Worker native prepared request is unavailable",
                code="worker_native_profile_not_captured",
            )
        return request

    def _record_native_debt(self, witness: object | None) -> None:
        try:
            debt = witness
            if debt is None:
                debt = self._provisioner.recover_cleanup_witness(self._spec)
            elif getattr(debt, "state", None) != "DEBT":
                debt = self._provisioner.mark_debt(self._spec, debt)
            self._witness = debt
            self._journal.advance(
                expected=_WINDOWS_JOURNAL_PHASES - frozenset({"settled"}),
                phase="debt",
                witness=debt,
            )
        except BaseException:
            # The earlier effect-state CAS remains a conservative durable fence.
            return

    def _close_native(self) -> None:
        self._journal.reserve()
        phase = self._journal.phase
        if phase == "settled":
            return
        if phase == "reserved":
            self._journal.advance(
                expected=frozenset({"reserved"}),
                phase="settled",
                witness=None,
            )
            return
        witness = self._witness
        if witness is None:
            document = self._journal.witness_document
            witness = (
                self._restore_witness(document)
                if document is not None
                else self._provisioner.recover_cleanup_witness(self._spec)
            )
        state = getattr(witness, "state", None)
        if state not in {"GRANTS_REVOKED", "PROFILE_DELETED", "SETTLED"}:
            if state != "DEBT":
                witness = self._provisioner.mark_debt(self._spec, witness)
            self._journal.advance(
                expected=_WINDOWS_JOURNAL_PHASES - frozenset({"settled"}),
                phase="cleaning",
                witness=witness,
            )

            def begin_revoke() -> None:
                self._journal.advance(
                    expected=frozenset({"cleaning", "debt", "revoke_effect"}),
                    phase="revoke_effect",
                    witness=witness,
                )

            witness = self._provisioner.revoke_grants(
                self._spec,
                witness,
                begin_effect=begin_revoke,
            )
            self._witness = witness
            self._journal.advance(
                expected=frozenset({"revoke_effect"}),
                phase="grants_revoked",
                witness=witness,
            )
        if getattr(witness, "state", None) == "GRANTS_REVOKED":

            def begin_delete() -> None:
                self._journal.advance(
                    expected=frozenset({"grants_revoked", "delete_effect"}),
                    phase="delete_effect",
                    witness=witness,
                )

            witness = self._provisioner.delete_profile(
                self._spec,
                witness,
                begin_effect=begin_delete,
            )
            self._witness = witness
            self._journal.advance(
                expected=frozenset({"delete_effect"}),
                phase="profile_deleted",
                witness=witness,
            )
        if getattr(witness, "state", None) == "PROFILE_DELETED":
            witness = self._provisioner.settle(self._spec, witness)
            self._witness = witness
            self._journal.advance(
                expected=frozenset({"profile_deleted"}),
                phase="settled",
                witness=witness,
            )
        if getattr(witness, "state", None) != "SETTLED":
            raise WorkerBindingError(
                "Worker native containment cleanup is incomplete",
                code="worker_native_containment_unsettled",
            )
        self._witness = witness

    def _restore_witness(self, document: Mapping[str, object]) -> object:
        strict = _strict_mapping(
            document,
            _WINDOWS_WITNESS_FIELDS,
            name="native provisioning witness",
        )
        return self._bindings.witness_factory(
            state=strict["state"],
            attempt_id=strict["attemptId"],
            operation_nonce=strict["operationNonce"],
            spec_fingerprint=strict["specFingerprint"],
            profile_fingerprint=strict["profileFingerprint"],
            sid_fingerprint=strict["sidFingerprint"],
            private_state_fingerprint=strict["privateStateFingerprint"],
            grant_digest=strict["grantDigest"],
            platform_identity=strict["platformIdentity"],
        )


def _plan_windows_lpac_product_worker_profile(
    *,
    worker_request: ManagedWorkerLaunchRequestV1,
    native_profile_catalog_revision: str,
    containment_launcher_sha256: str,
    platform_imports: tuple[str, ...],
    _platform_probe: _PlatformProbe | None = None,
    _runtime_bindings: _WindowsLpacRuntimeBindings | None = None,
) -> _WindowsLpacProductWorkerProfilePlan:
    plan, _ = _build_windows_lpac_product_worker_profile_plan(
        worker_request=worker_request,
        native_profile_catalog_revision=native_profile_catalog_revision,
        containment_launcher_sha256=containment_launcher_sha256,
        platform_imports=platform_imports,
        _platform_probe=_platform_probe,
        _runtime_bindings=_runtime_bindings,
    )
    return plan


def _build_windows_lpac_product_worker_profile_plan(
    *,
    worker_request: ManagedWorkerLaunchRequestV1,
    native_profile_catalog_revision: str,
    containment_launcher_sha256: str,
    platform_imports: tuple[str, ...],
    _platform_probe: _PlatformProbe | None = None,
    _runtime_bindings: _WindowsLpacRuntimeBindings | None = None,
) -> tuple[_WindowsLpacProductWorkerProfilePlan, object]:
    if not isinstance(worker_request, ManagedWorkerLaunchRequestV1):
        raise TypeError("Worker native plan requires a managed Worker request")
    _require_opaque(native_profile_catalog_revision, name="profile catalog revision")
    _require_sha256(containment_launcher_sha256, name="containment launcher")
    _require_windows_amd64(_platform_probe or _observe_platform)
    bindings = _runtime_bindings or _load_windows_lpac_bindings()
    if bindings.capture_backend_id != "windows-job-v1":
        raise WorkerBindingError(
            "Worker native backend identity changed",
            code="worker_native_backend_mismatch",
        )
    operation_nonce = _domain_values_fingerprint(
        _WINDOWS_OPERATION_NONCE_DOMAIN,
        (
            worker_request.fingerprint,
            native_profile_catalog_revision,
            worker_request.identity.attempt_id,
            str(worker_request.identity.owner_generation),
        ),
    )
    lifecycle_fingerprint = _domain_values_fingerprint(
        _WINDOWS_LIFECYCLE_DOMAIN,
        (
            worker_request.fingerprint,
            native_profile_catalog_revision,
            _WINDOWS_LPAC_PROFILE_ID,
        ),
    )
    provision_request = _windows_lpac_provision_request(worker_request)
    spec = bindings.build_provision_spec(
        provision_request,
        runtime_root=str(worker_request.runtime.package_root),
        platform_imports=platform_imports,
        attempt_id=worker_request.identity.attempt_id,
        operation_nonce=operation_nonce,
        lifecycle_fingerprint=lifecycle_fingerprint,
    )
    containment_profile_sha256 = bindings.spec_fingerprint(spec)
    _require_sha256(containment_profile_sha256, name="containment profile")
    expected = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
        native_profile_catalog_revision=native_profile_catalog_revision,
        native_profile_id=_WINDOWS_LPAC_PROFILE_ID,
        payload_sha256=worker_request.runtime.executable_digest,
        containment_launcher_sha256=containment_launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
    )
    return (
        _WindowsLpacProductWorkerProfilePlan(
            worker_request_fingerprint=worker_request.fingerprint,
            native_profile_catalog_revision=native_profile_catalog_revision,
            containment_launcher_sha256=containment_launcher_sha256,
            containment_profile_sha256=containment_profile_sha256,
            expected_native_policy_closure_fingerprint=expected,
            operation_nonce=operation_nonce,
            lifecycle_fingerprint=lifecycle_fingerprint,
        ),
        spec,
    )


def _bind_windows_lpac_contained_product_worker_profile(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    worker_request: ManagedWorkerLaunchRequestV1,
    plan: _WindowsLpacProductWorkerProfilePlan,
    platform_imports: tuple[str, ...],
    provisioning_state_store: _WindowsLpacProvisioningStateStore,
    _platform_probe: _PlatformProbe | None = None,
    _runtime_bindings: _WindowsLpacRuntimeBindings | None = None,
) -> ProductWorkerNativeProfilePort:
    _require_exact_binding(receipt=receipt, worker_request=worker_request)
    if type(plan) is not _WindowsLpacProductWorkerProfilePlan:
        raise TypeError("Worker Windows LPAC profile requires the exact plan")
    policy = receipt.policy
    if policy.native_profile_id != _WINDOWS_LPAC_PROFILE_ID:
        raise WorkerBindingError(
            "Worker native profile is unsupported",
            code="worker_native_profile_unsupported",
        )
    bindings = _runtime_bindings or _load_windows_lpac_bindings_after_platform(
        _platform_probe or _observe_platform
    )
    current_plan, spec = _build_windows_lpac_product_worker_profile_plan(
        worker_request=worker_request,
        native_profile_catalog_revision=policy.native_profile_catalog_revision,
        containment_launcher_sha256=plan.containment_launcher_sha256,
        platform_imports=platform_imports,
        _platform_probe=_platform_probe,
        _runtime_bindings=bindings,
    )
    if current_plan != plan:
        raise WorkerBindingError(
            "Worker native provisioned profile changed",
            code="worker_native_provisioning_fingerprint_mismatch",
        )
    if (
        plan.worker_request_fingerprint != worker_request.fingerprint
        or plan.native_profile_catalog_revision
        != policy.native_profile_catalog_revision
        or plan.expected_native_policy_closure_fingerprint
        != policy.expected_native_policy_closure_fingerprint
    ):
        raise WorkerBindingError(
            "Worker native policy closure changed",
            code="worker_native_policy_closure_mismatch",
        )
    journal = _WindowsLpacProvisioningJournal(
        store=provisioning_state_store,
        receipt=receipt,
        worker_request=worker_request,
        plan=plan,
    )
    return _WindowsLpacContainedProductWorkerProfile(
        receipt=receipt,
        worker_request=worker_request,
        plan=plan,
        provision_spec=spec,
        bindings=bindings,
        journal=journal,
    )


def _load_windows_lpac_bindings_after_platform(
    probe: _PlatformProbe,
) -> _WindowsLpacRuntimeBindings:
    _require_windows_amd64(probe)
    return _load_windows_lpac_bindings()


def _load_windows_lpac_bindings() -> _WindowsLpacRuntimeBindings:
    from loushang.hosting._windows_launch_preparation import (
        _build_windows_lpac_launch_capture_spec,
        _build_windows_lpac_provision_spec,
        _lpac_spec_fingerprint,
        _WindowsLpacLaunchCaptureBackend,
        _WindowsLpacProfileCollision,
        _WindowsLpacProvisioner,
        _WindowsLpacProvisionWitness,
    )

    return _WindowsLpacRuntimeBindings(
        build_provision_spec=_build_windows_lpac_provision_spec,
        provisioner_factory=_WindowsLpacProvisioner,
        build_capture_spec=_build_windows_lpac_launch_capture_spec,
        spec_fingerprint=_lpac_spec_fingerprint,
        witness_factory=_WindowsLpacProvisionWitness,
        profile_collision_type=_WindowsLpacProfileCollision,
        capture_backend_id=_WindowsLpacLaunchCaptureBackend.backend_id,
    )


def _native_profile_prepared_request(
    profile: ProductWorkerNativeProfilePort,
    original: ProcessLaunchRequest,
) -> ProcessLaunchRequest:
    if type(profile) is _WindowsLpacContainedProductWorkerProfile:
        return cast(
            _WindowsLpacContainedProductWorkerProfile, profile
        ).prepared_request()
    return original


def _windows_lpac_provision_request(
    worker_request: ManagedWorkerLaunchRequestV1,
) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(str(worker_request.runtime.executable),),
        cwd=str(worker_request.runtime.package_root),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )


def _validate_windows_journal(
    value: object,
    identity: Mapping[str, object],
) -> dict[str, object]:
    document = _strict_mapping(
        value,
        _WINDOWS_JOURNAL_FIELDS,
        name="native provisioning journal",
    )
    for name, expected in identity.items():
        if document.get(name) != expected:
            raise WorkerBindingError(
                "Worker native provisioning identity changed",
                code="worker_native_provisioning_identity_mismatch",
            )
    revision = document["stateRevision"]
    if type(revision) is not int or cast(int, revision) < 1:
        raise ValueError("Worker native provisioning revision is invalid")
    phase = document["phase"]
    if not isinstance(phase, str) or phase not in _WINDOWS_JOURNAL_PHASES:
        raise ValueError("Worker native provisioning phase is invalid")
    raw_witness = document["witness"]
    witness_state: str | None = None
    if raw_witness is not None:
        witness = _strict_mapping(
            raw_witness,
            _WINDOWS_WITNESS_FIELDS,
            name="native provisioning witness",
        )
        witness_state_value = witness["state"]
        if (
            not isinstance(witness_state_value, str)
            or witness_state_value not in _WINDOWS_WITNESS_STATES
        ):
            raise ValueError("Worker native provisioning witness state is invalid")
        witness_state = witness_state_value
        if (
            witness["attemptId"] != identity["attemptId"]
            or witness["operationNonce"] != identity["operationNonce"]
            or witness["specFingerprint"] != identity["specFingerprint"]
        ):
            raise WorkerBindingError(
                "Worker native provisioning witness changed",
                code="worker_native_provisioning_witness_mismatch",
            )
        for field in (
            "grantDigest",
            "operationNonce",
            "privateStateFingerprint",
            "profileFingerprint",
            "sidFingerprint",
            "specFingerprint",
        ):
            _require_sha256(witness[field], name="provisioning witness")
        platform_identity = witness["platformIdentity"]
        if (
            not isinstance(platform_identity, str)
            or not platform_identity.startswith("windows-amd64-")
            or len(platform_identity.encode("utf-8")) > _MAX_PLATFORM_FACT_BYTES
        ):
            raise ValueError("Worker native witness platform is invalid")
        document["witness"] = witness
    if witness_state not in _WINDOWS_PHASE_WITNESS_STATES[phase]:
        raise ValueError("Worker native provisioning phase/witness is inconsistent")
    return document


def _windows_witness_document(witness: object) -> dict[str, object]:
    document = {
        "attemptId": getattr(witness, "attempt_id", None),
        "grantDigest": getattr(witness, "grant_digest", None),
        "operationNonce": getattr(witness, "operation_nonce", None),
        "platformIdentity": getattr(witness, "platform_identity", None),
        "privateStateFingerprint": getattr(
            witness,
            "private_state_fingerprint",
            None,
        ),
        "profileFingerprint": getattr(witness, "profile_fingerprint", None),
        "sidFingerprint": getattr(witness, "sid_fingerprint", None),
        "specFingerprint": getattr(witness, "spec_fingerprint", None),
        "state": getattr(witness, "state", None),
    }
    return _strict_mapping(
        document,
        _WINDOWS_WITNESS_FIELDS,
        name="native provisioning witness",
    )


def _strict_mapping(
    value: object,
    fields: frozenset[str],
    *,
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"Worker {name} has invalid fields")
    copied = _json_copy(value)
    if not isinstance(copied, dict):  # pragma: no cover - JSON object invariant
        raise TypeError(f"Worker {name} is not an object")
    return cast(dict[str, object], copied)


def _bind_static_method(value: object, name: str) -> Callable[..., object]:
    descriptor = inspect.getattr_static(type(value), name, None)
    visible = inspect.getattr_static(value, name, None)
    instance_values = inspect.getattr_static(value, "__dict__", None)
    shadowed = isinstance(instance_values, dict) and name in instance_values
    if (
        descriptor is None
        or visible is not descriptor
        or shadowed
        or not inspect.isfunction(descriptor)
    ):
        raise TypeError(f"Worker native provisioning store requires static {name}")
    bound = descriptor.__get__(value, type(value))
    if not callable(bound):  # pragma: no cover - descriptor invariant
        raise TypeError(f"Worker native provisioning store {name} is not callable")
    return cast(Callable[..., object], bound)


def _json_copy(value: object) -> object:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Worker native provisioning state is not JSON") from error


def _document_fingerprint(domain: str, document: Mapping[str, object]) -> str:
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    return digest.hexdigest()


def _domain_values_fingerprint(domain: str, values: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _require_exact_binding(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    worker_request: ManagedWorkerLaunchRequestV1,
) -> None:
    if not isinstance(receipt, ProductWorkerActivationReceiptV1):
        raise TypeError("Worker native profile requires an activation receipt")
    if not isinstance(worker_request, ManagedWorkerLaunchRequestV1):
        raise TypeError("Worker native profile requires a managed Worker request")
    policy = receipt.policy
    identity = worker_request.identity
    expected = (
        policy.product_id,
        policy.product_scope_id,
        policy.plugin_id,
        policy.plugin_revision_digest,
        policy.contribution_id,
        policy.declaration_fingerprint,
        policy.worker_configuration_fingerprint,
    )
    actual = (
        identity.product_id,
        identity.scope_id,
        identity.plugin_id,
        identity.plugin_revision_digest,
        identity.contribution_id,
        identity.declaration_fingerprint,
        identity.worker_configuration_fingerprint,
    )
    if expected != actual:
        raise WorkerBindingError(
            "Worker native receipt targets a different request",
            code="worker_native_receipt_mismatch",
        )
    if (
        not policy.enabled
        or policy.requested_owner != "hosting"
        or not policy.no_fallback
    ):
        raise WorkerBindingError(
            "Worker native profile is disabled",
            code="worker_native_profile_disabled",
        )


def _require_process_request(
    request: ProcessLaunchRequest,
    *,
    worker_request: ManagedWorkerLaunchRequestV1,
) -> None:
    runtime = worker_request.runtime
    if (
        request.argv != (str(runtime.executable),)
        or request.cwd != str(runtime.package_root)
        or request.effective_environment
        or request.streams.stdin is not ProcessStdinMode.CLOSED
        or request.streams.stdout is not ProcessStdoutMode.DISCARD
        or request.streams.stderr is not ProcessStderrMode.PIPE
    ):
        raise WorkerBindingError(
            "Worker native execution closure changed",
            code="worker_native_execution_closure_mismatch",
        )


def _observe_platform() -> tuple[str, str, str, str]:
    return (
        platform.system(),
        platform.machine(),
        platform.release(),
        platform.version(),
    )


def _require_linux_x86_64(probe: _PlatformProbe) -> None:
    try:
        observation = probe()
    except BaseException as exc:
        raise WorkerBindingError(
            "Worker native platform could not be classified",
            code="worker_native_platform_unknown",
        ) from exc
    if (
        not isinstance(observation, tuple)
        or len(observation) != 4
        or any(
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > _MAX_PLATFORM_FACT_BYTES
            or "\0" in value
            for value in observation
        )
    ):
        raise WorkerBindingError(
            "Worker native platform could not be classified",
            code="worker_native_platform_unknown",
        )
    system, machine, release, version = observation
    if system.casefold() != "linux":
        raise WorkerBindingError(
            "Worker native platform is unsupported",
            code="worker_native_platform_unsupported",
        )
    if machine.casefold() not in _SUPPORTED_MACHINES:
        raise WorkerBindingError(
            "Worker native architecture is unsupported",
            code="worker_native_architecture_unsupported",
        )
    kernel = f"{release}\n{version}".casefold()
    if "microsoft" in kernel or "wsl" in kernel:
        raise WorkerBindingError(
            "Worker native platform is unsupported",
            code="worker_native_platform_wsl_unsupported",
        )


def _require_windows_amd64(probe: _PlatformProbe) -> None:
    observation = _validated_platform_observation(probe)
    system, machine, release, version = observation
    kernel = f"{release}\n{version}".casefold()
    if system.casefold() != "windows":
        if "microsoft" in kernel or "wsl" in kernel:
            raise WorkerBindingError(
                "Worker native platform is unsupported",
                code="worker_native_platform_wsl_unsupported",
            )
        raise WorkerBindingError(
            "Worker native platform is unsupported",
            code="worker_native_platform_unsupported",
        )
    if machine.casefold() not in _SUPPORTED_MACHINES:
        raise WorkerBindingError(
            "Worker native architecture is unsupported",
            code="worker_native_architecture_unsupported",
        )


def _validated_platform_observation(
    probe: _PlatformProbe,
) -> tuple[str, str, str, str]:
    try:
        observation = probe()
    except BaseException as exc:
        raise WorkerBindingError(
            "Worker native platform could not be classified",
            code="worker_native_platform_unknown",
        ) from exc
    if (
        not isinstance(observation, tuple)
        or len(observation) != 4
        or any(
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > _MAX_PLATFORM_FACT_BYTES
            or "\0" in value
            for value in observation
        )
    ):
        raise WorkerBindingError(
            "Worker native platform could not be classified",
            code="worker_native_platform_unknown",
        )
    return observation


def _closure_fingerprint(closure: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(_EXECUTION_CLOSURE_DOMAIN.encode("ascii"))
    for value in closure:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _require_sha256(value: object, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Worker native {name} digest is invalid")


def _require_opaque(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 128
        or any(character.isspace() for character in value)
        or "\0" in value
    ):
        raise ValueError(f"Worker native {name} is invalid")


__all__ = ["ProductWorkerNativeProfilePort"]
