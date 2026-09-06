"""Installed, explicit, default-dark Coding AppHost native canary."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from typing import Any, Literal, Protocol, cast

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostShutdownBudgetV1,
    ProfileDescriptorV1,
    ProfileRegistrationV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.coding._apphost_canary_control import (
    CodingAppHostCanaryControlError,
    CodingAppHostCanaryControlJournal,
    CodingAppHostCanaryControlSnapshotV1,
    default_coding_apphost_canary_control_path,
)
from loushang.coding._product_worker_canary import (
    CodingProductWorkerCanaryStatusV1,
)
from loushang.coding.apphost_composition import (
    CodingAppHostCompositionActivationV1,
    CodingAppHostCompositionRequestV1,
    CodingAppHostCompositionV1,
    CodingAppHostRollbackLatchV1,
    create_coding_apphost_composition,
)
from loushang.coding.apphost_product import (
    CodingAppHostProductBindingV1,
    CodingAppHostWorkerAttemptV1,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.worker import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)
from loushang.hosting import (
    HostingObservation,
    HostingObservationSink,
    ProcessHostingPort,
    ProcessLaunchRequest,
    ProcessLease,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
    create_process_host,
)

CODING_APPHOST_CANARY_REPORT_VERSION = 1
CODING_APPHOST_CANARY_TIMEOUT_SECONDS = 10.0
CODING_APPHOST_CANARY_MAX_PROTOCOL_BYTES = 128
CODING_APPHOST_CANARY_MAX_TRANSITIONS = 32

CodingAppHostCanaryOperation = Literal["status", "run", "rollback", "enable"]
CodingAppHostCanaryState = Literal[
    "unconfigured", "enabled", "disabled", "ready", "failed"
]

_STABLE_CODE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE = re.compile(r"\S{1,128}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROTOCOL_PREFIX = b"loushang-apphost-canary/v1 "
_PROFILE_ID = "apphost-canary"
_COMPATIBILITY_ID = "coding-apphost-canary-v1"
_DIGESTS = {
    name: sha256(f"loushang-apphost-canary:{name}".encode("ascii")).hexdigest()
    for name in (
        "plugin",
        "reservation",
        "declaration",
        "configuration",
        "locator",
        "native-policy",
    )
}


class CodingAppHostCanaryError(RuntimeError):
    """Stable Product failure hidden behind the bounded canary report."""

    def __init__(self, *, code: str) -> None:
        if _STABLE_CODE.fullmatch(code) is None:
            raise ValueError("Coding AppHost canary error code is invalid")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CodingAppHostCanaryRequestV1:
    """Explicit installed operation with Product-selected storage and cwd."""

    operation: CodingAppHostCanaryOperation
    cwd: Path
    control_path: Path | None = None
    timeout_seconds: float = CODING_APPHOST_CANARY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.operation not in {"status", "run", "rollback", "enable"}:
            raise ValueError("Coding AppHost canary operation is invalid")
        cwd = Path(self.cwd).expanduser().resolve(strict=False)
        if self.operation == "run" and not cwd.is_dir():
            raise ValueError("Coding AppHost canary cwd is not a directory")
        control_path = (
            default_coding_apphost_canary_control_path()
            if self.control_path is None
            else Path(self.control_path).expanduser().absolute()
        )
        if not control_path.is_absolute():
            raise ValueError("Coding AppHost canary control path must be absolute")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0.1 <= float(self.timeout_seconds) <= 60.0
        ):
            raise ValueError("Coding AppHost canary timeout is invalid")
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "control_path", control_path)
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))


@dataclass(frozen=True, slots=True)
class CodingAppHostCanaryReportV1:
    """Closed, path-free and payload-free operational result."""

    operation: CodingAppHostCanaryOperation
    state: CodingAppHostCanaryState
    code: str
    selection_generation: int
    receipt_fingerprint: str | None = None
    attempt_fingerprint: str | None = None
    hosting_backend_id: str | None = None
    hosting_transitions: tuple[str, ...] = ()
    report_version: int = CODING_APPHOST_CANARY_REPORT_VERSION

    def __post_init__(self) -> None:
        if self.operation not in {"status", "run", "rollback", "enable"}:
            raise ValueError("Coding AppHost canary report operation is invalid")
        if self.state not in {
            "unconfigured",
            "enabled",
            "disabled",
            "ready",
            "failed",
        }:
            raise ValueError("Coding AppHost canary report state is invalid")
        if _STABLE_CODE.fullmatch(self.code) is None:
            raise ValueError("Coding AppHost canary report code is invalid")
        if type(self.selection_generation) is not int or self.selection_generation < 0:
            raise ValueError("Coding AppHost canary report generation is invalid")
        for value in (self.receipt_fingerprint, self.attempt_fingerprint):
            if value is not None and _SHA256.fullmatch(value) is None:
                raise ValueError("Coding AppHost canary report fingerprint is invalid")
        if (
            self.hosting_backend_id is not None
            and _OPAQUE.fullmatch(self.hosting_backend_id) is None
        ):
            raise ValueError("Coding AppHost canary backend is invalid")
        if (
            not isinstance(self.hosting_transitions, tuple)
            or len(self.hosting_transitions) > CODING_APPHOST_CANARY_MAX_TRANSITIONS
            or any(
                _STABLE_CODE.fullmatch(item) is None
                for item in self.hosting_transitions
            )
        ):
            raise ValueError("Coding AppHost canary transitions are invalid")
        if (
            type(self.report_version) is not int
            or self.report_version != CODING_APPHOST_CANARY_REPORT_VERSION
        ):
            raise ValueError("Coding AppHost canary report is unsupported")

    @property
    def succeeded(self) -> bool:
        return self.state != "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptFingerprint": self.attempt_fingerprint,
            "code": self.code,
            "hostingBackendId": self.hosting_backend_id,
            "hostingTransitions": list(self.hosting_transitions),
            "operation": self.operation,
            "receiptFingerprint": self.receipt_fingerprint,
            "reportVersion": self.report_version,
            "selectionGeneration": self.selection_generation,
            "state": self.state,
        }


class _ProcessHostFactory(Protocol):
    def __call__(
        self,
        *,
        observation_sink: HostingObservationSink | None = None,
    ) -> ProcessHostingPort: ...


class _ObservationSink:
    __slots__ = ("backend_ids", "overflow", "transitions")

    def __init__(self) -> None:
        self.backend_ids: list[str] = []
        self.transitions: list[str] = []
        self.overflow = False

    def observe(self, observation: HostingObservation) -> None:
        if type(observation) is not HostingObservation:
            self.overflow = True
            return
        if len(self.transitions) >= CODING_APPHOST_CANARY_MAX_TRANSITIONS:
            self.overflow = True
            return
        self.transitions.append(observation.transition.value)
        if (
            observation.backend_id is not None
            and observation.backend_id not in self.backend_ids
        ):
            self.backend_ids.append(observation.backend_id)

    def backend_id(self) -> str | None:
        return self.backend_ids[0] if len(self.backend_ids) == 1 else None


class _PreparationLease:
    __slots__ = ("_request",)

    def __init__(self, request: ProcessLaunchRequest) -> None:
        self._request = request

    @property
    def request(self) -> ProcessLaunchRequest:
        return self._request

    async def verify_current(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _PreparationPort:
    async def prepare(self, request: ProcessLaunchRequest) -> _PreparationLease:
        return _PreparationLease(request)


class _NativeCanaryAttempt:
    __slots__ = (
        "_close_lock",
        "_closed",
        "_cwd",
        "_failure_code",
        "_host",
        "_host_factory",
        "_lease",
        "_nonce",
        "_receipt",
        "_sink",
        "_status",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        selection_generation: int,
        cwd: Path,
        timeout_seconds: float,
        host_factory: _ProcessHostFactory,
        sink: _ObservationSink,
    ) -> None:
        self._nonce = token_hex(16)
        policy = _worker_policy(
            binding_key=binding_key,
            selection_generation=selection_generation,
        )
        self._receipt = ProductWorkerActivationReceiptV1(
            policy=policy,
            issue_sequence=1,
            issue_nonce=token_hex(16),
        )
        self._status = CodingProductWorkerCanaryStatusV1(
            code="coding_apphost_canary_selected",
            readiness="selected",
            required=True,
            requested_owner="hosting",
            effective_owner="hosting",
            receipt_fingerprint=self._receipt.fingerprint,
            attempt_id=self._nonce,
            owner_generation=selection_generation,
        )
        self._cwd = cwd
        self._timeout_seconds = timeout_seconds
        self._host_factory = host_factory
        self._sink = sink
        self._host: ProcessHostingPort | None = None
        self._lease: ProcessLease | None = None
        self._failure_code: str | None = None
        self._close_lock = asyncio.Lock()
        self._closed = False

    @property
    def status(self) -> CodingProductWorkerCanaryStatusV1:
        return self._status

    @property
    def failure_code(self) -> str | None:
        return self._failure_code

    @property
    def attempt_fingerprint(self) -> str:
        return sha256(
            b"loushang-apphost-canary-attempt/v1" + self._nonce.encode("ascii")
        ).hexdigest()

    def receipt_for_entrypoint(
        self,
        entrypoint: str,
    ) -> ProductWorkerActivationReceiptV1 | None:
        return self._receipt if entrypoint == "product" else None

    async def recover(self) -> tuple[str, ...]:
        return ("no_prior_owner_adopted",)

    async def start(
        self,
        *,
        correlation_id: str,
    ) -> CodingProductWorkerCanaryStatusV1:
        if not correlation_id or self._closed:
            self._failure_code = "coding_apphost_canary_attempt_invalid"
            raise CodingAppHostCanaryError(code=self._failure_code)
        # Preserve a virtual-environment launcher path. Resolving its symlink to
        # the base interpreter would discard the installed distribution's
        # site-packages and make the private module unavailable.
        executable = Path(sys.executable).absolute()
        if not executable.is_absolute() or not executable.is_file():
            self._failure_code = "coding_apphost_canary_python_unavailable"
            raise CodingAppHostCanaryError(code=self._failure_code)
        request = ProcessLaunchRequest(
            argv=(
                str(executable),
                "-m",
                "loushang.coding._apphost_canary_child",
                self._nonce,
            ),
            cwd=str(self._cwd),
            effective_environment=_child_environment(),
            streams=ProcessStreamSpec(
                stdin=ProcessStdinMode.CLOSED,
                stdout=ProcessStdoutMode.PIPE,
                stderr=ProcessStderrMode.CAPTURE_TAIL,
            ),
        )
        try:
            self._host = self._host_factory(observation_sink=self._sink)
            async with asyncio.timeout(self._timeout_seconds):
                self._lease = await self._host.start(request, _PreparationPort())
                output = await _read_protocol_line(self._lease)
                exited = await self._lease.wait()
            expected = _PROTOCOL_PREFIX + self._nonce.encode("ascii")
            if output not in {expected + b"\n", expected + b"\r\n"}:
                raise CodingAppHostCanaryError(
                    code="coding_apphost_canary_protocol_rejected"
                )
            if exited.return_code != 0:
                raise CodingAppHostCanaryError(
                    code="coding_apphost_canary_child_failed"
                )
            if self._sink.overflow or self._sink.backend_id() is None:
                raise CodingAppHostCanaryError(
                    code="coding_apphost_canary_observation_invalid"
                )
        except TimeoutError as error:
            self._failure_code = "coding_apphost_canary_timeout"
            raise CodingAppHostCanaryError(code=self._failure_code) from error
        except CodingAppHostCanaryError as error:
            self._failure_code = error.code
            raise
        except asyncio.CancelledError:
            self._failure_code = "coding_apphost_canary_cancelled"
            raise
        except BaseException as error:
            self._failure_code = "coding_apphost_canary_hosting_unavailable"
            raise CodingAppHostCanaryError(code=self._failure_code) from error
        self._status = CodingProductWorkerCanaryStatusV1(
            code="coding_apphost_canary_ready",
            readiness="ready",
            required=True,
            requested_owner="hosting",
            effective_owner="hosting",
            receipt_fingerprint=self._receipt.fingerprint,
            attempt_id=self._nonce,
            owner_generation=self._receipt.policy.owner_selection_generation,
        )
        return self._status

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            failures: list[BaseException] = []
            if self._lease is not None:
                try:
                    await self._lease.close()
                except BaseException as error:
                    failures.append(error)
            if self._host is not None:
                try:
                    await self._host.close()
                except BaseException as error:
                    failures.append(error)
            if failures:
                self._failure_code = "coding_apphost_canary_cleanup_incomplete"
                raise CodingAppHostCanaryError(code=self._failure_code) from None
            self._closed = True
            self._lease = None
            self._host = None


class _AttemptFactory:
    __slots__ = (
        "_cwd",
        "_host_factory",
        "_selection_generation",
        "_sink",
        "_timeout_seconds",
        "attempt",
    )

    def __init__(
        self,
        *,
        selection_generation: int,
        cwd: Path,
        timeout_seconds: float,
        host_factory: _ProcessHostFactory,
        sink: _ObservationSink,
    ) -> None:
        self._selection_generation = selection_generation
        self._cwd = cwd
        self._timeout_seconds = timeout_seconds
        self._host_factory = host_factory
        self._sink = sink
        self.attempt: _NativeCanaryAttempt | None = None

    def create_attempt(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> CodingAppHostWorkerAttemptV1:
        if self.attempt is not None or not isinstance(
            opaque_session_binding, _OpenedCandidate
        ):
            raise CodingAppHostCanaryError(code="coding_apphost_canary_attempt_invalid")
        attempt = _NativeCanaryAttempt(
            binding_key=binding_key,
            selection_generation=self._selection_generation,
            cwd=self._cwd,
            timeout_seconds=self._timeout_seconds,
            host_factory=self._host_factory,
            sink=self._sink,
        )
        self.attempt = attempt
        return attempt


class _AdmissionPin:
    __slots__ = ("_closed", "_identity")

    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity
        self._closed = False

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        self._closed = True


class _AdmissionSource:
    __slots__ = ("_identity",)

    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity

    async def acquire_pin(self) -> _AdmissionPin:
        return _AdmissionPin(self._identity)


class _ClaimedCandidate:
    __slots__ = ("_reference",)

    def __init__(self, reference: SessionCandidateRefV1) -> None:
        self._reference = reference

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        return self

    async def close(self) -> None:
        return None


class _SessionCandidate:
    __slots__ = ("_projection",)

    def __init__(self, envelope: SessionIdentityEnvelopeV1) -> None:
        self._projection = SessionIdentityProjectionV1(
            reference=SessionCandidateRefV1(
                "g10-ephemeral",
                envelope.session_id,
                _DIGESTS["locator"],
            ),
            scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            mode=SessionCandidateMode.CANONICAL,
            envelope=envelope,
        )

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def verify_current(self) -> None:
        return None

    async def claim(self) -> _ClaimedCandidate:
        return _ClaimedCandidate(self._projection.reference)

    async def close(self) -> None:
        return None


class _EphemeralSessions:
    __slots__ = ("_candidate",)

    def __init__(self, candidate: _SessionCandidate) -> None:
        self._candidate = candidate

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        if SessionDiscoveryScope.USER_GLOBAL_CANONICAL not in scopes or limit < 1:
            return ()
        return (self._candidate.projection,)

    async def open_candidate(
        self,
        reference: SessionCandidateRefV1,
    ) -> _SessionCandidate:
        if reference != self._candidate.projection.reference:
            raise CodingAppHostCanaryError(code="coding_apphost_canary_candidate_stale")
        return self._candidate

    async def find_created_candidate(
        self,
        request: SessionCreateRequestV1,
    ) -> _SessionCandidate | None:
        del request
        return None

    async def create_candidate(
        self,
        intent: SessionCreateIntentV1,
    ) -> _SessionCandidate:
        del intent
        raise CodingAppHostCanaryError(code="coding_apphost_canary_create_forbidden")


class _OpenedCandidate:
    __slots__ = ("_key",)

    def __init__(self, key: SessionBindingKeyV1) -> None:
        self._key = key

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def opaque_binding(self) -> object:
        return self

    async def close(self) -> None:
        return None


class _CandidateValidator:
    async def open_product_candidate(
        self,
        candidate: object,
        envelope: SessionIdentityEnvelopeV1,
    ) -> _OpenedCandidate:
        claimed = getattr(candidate, "opaque_binding", None)
        if (
            not isinstance(claimed, _ClaimedCandidate)
            or envelope.product_id != CODING_PRODUCT_ID
            or envelope.product_compatibility_id != _COMPATIBILITY_ID
            or claimed.reference.candidate_id != envelope.session_id
        ):
            raise CodingAppHostCanaryError(
                code="coding_apphost_canary_candidate_rejected"
            )
        return _OpenedCandidate(
            SessionBindingKeyV1(
                envelope.product_id,
                envelope.continuity_id,
                envelope.session_id,
            )
        )


class _ProfileLease:
    __slots__ = ("_binding", "_closed")

    def __init__(self, binding: object) -> None:
        self._binding = binding
        self._closed = False

    @property
    def profile_id(self) -> str:
        return _PROFILE_ID

    @property
    def profile_binding(self) -> object:
        return self._binding

    async def close(self) -> None:
        self._closed = True


class _ProfileFactory:
    async def bind_profile(self, binding: object) -> _ProfileLease:
        return _ProfileLease(binding)


class _RollbackControl:
    __slots__ = ("_journal",)

    def __init__(self, journal: CodingAppHostCanaryControlJournal) -> None:
        self._journal = journal

    async def latch_future_attempts(self) -> CodingAppHostRollbackLatchV1:
        snapshot = self._journal.rollback(operation_id=token_hex(16))
        return CodingAppHostRollbackLatchV1(
            selection_generation=snapshot.selection_generation,
            active_attempt_fingerprints=(),
        )


async def run_coding_apphost_canary(
    request: CodingAppHostCanaryRequestV1,
    *,
    process_host_factory: _ProcessHostFactory = create_process_host,
) -> CodingAppHostCanaryReportV1:
    """Execute one explicit control operation or settled native canary run."""

    if type(request) is not CodingAppHostCanaryRequestV1:
        raise TypeError("Coding AppHost canary request is invalid")
    journal = CodingAppHostCanaryControlJournal(cast(Path, request.control_path))
    try:
        if request.operation == "status":
            return _control_report(
                "status",
                await journal.snapshot_async(timeout_seconds=request.timeout_seconds),
            )
        if request.operation == "enable":
            return _control_report(
                "enable",
                await journal.enable_async(
                    operation_id=token_hex(16),
                    timeout_seconds=request.timeout_seconds,
                ),
            )
        if request.operation == "rollback":
            return _control_report(
                "rollback",
                await journal.rollback_async(
                    operation_id=token_hex(16),
                    timeout_seconds=request.timeout_seconds,
                ),
            )
        async with journal.admitted_run_async(
            timeout_seconds=request.timeout_seconds
        ) as control:
            return await _run_native_canary(
                request,
                control=control,
                journal=journal,
                process_host_factory=process_host_factory,
            )
    except CodingAppHostCanaryControlError as error:
        return _control_failure_report(
            request.operation,
            code=error.code,
            selection_generation=error.selection_generation,
        )


async def _run_native_canary(
    request: CodingAppHostCanaryRequestV1,
    *,
    control: CodingAppHostCanaryControlSnapshotV1,
    journal: CodingAppHostCanaryControlJournal,
    process_host_factory: _ProcessHostFactory,
) -> CodingAppHostCanaryReportV1:
    sink = _ObservationSink()
    attempts = _AttemptFactory(
        selection_generation=control.selection_generation,
        cwd=request.cwd,
        timeout_seconds=request.timeout_seconds,
        host_factory=process_host_factory,
        sink=sink,
    )
    composition: CodingAppHostCompositionV1 | None = None
    lease: Any | None = None
    try:
        composition, reference = await _create_canary_composition(
            journal=journal,
            attempts=attempts,
        )
        lease = await composition.attach_resume(
            reference=reference,
            profile_id=_PROFILE_ID,
        )
        profile_binding = lease.profile_binding
        binding = getattr(profile_binding, "opaque_binding", None)
        if type(binding) is not CodingAppHostProductBindingV1:
            raise CodingAppHostCanaryError(code="coding_apphost_canary_binding_invalid")
        key = lease.binding_key
        await lease.close()
        lease = None
        await composition.close_session(key)
        await composition.close()
        composition = None
        attempt = attempts.attempt
        if attempt is None:
            raise CodingAppHostCanaryError(code="coding_apphost_canary_attempt_missing")
        if (
            sink.overflow
            or sink.backend_id() is None
            or not {"published", "exited", "closed"}.issubset(sink.transitions)
        ):
            raise CodingAppHostCanaryError(
                code="coding_apphost_canary_observation_invalid"
            )
        return CodingAppHostCanaryReportV1(
            operation="run",
            state="ready",
            code="coding_apphost_canary_ready",
            selection_generation=control.selection_generation,
            receipt_fingerprint=binding.receipt_fingerprint,
            attempt_fingerprint=attempt.attempt_fingerprint,
            hosting_backend_id=sink.backend_id(),
            hosting_transitions=tuple(sink.transitions),
        )
    except asyncio.CancelledError:
        await _join_canary_cleanup(lease, composition)
        raise
    except BaseException as error:
        cleanup_complete = await _settle_canary_cleanup(lease, composition)
        attempt = attempts.attempt
        code = (
            "coding_apphost_canary_cleanup_incomplete"
            if not cleanup_complete
            else attempt.failure_code
            if attempt is not None and attempt.failure_code is not None
            else error.code
            if isinstance(error, CodingAppHostCanaryError)
            else "coding_apphost_canary_runtime_unavailable"
        )
        return CodingAppHostCanaryReportV1(
            operation="run",
            state="failed",
            code=code,
            selection_generation=control.selection_generation,
            receipt_fingerprint=(
                None if attempt is None else attempt.status.receipt_fingerprint
            ),
            attempt_fingerprint=(
                None if attempt is None else attempt.attempt_fingerprint
            ),
            hosting_backend_id=sink.backend_id(),
            hosting_transitions=tuple(sink.transitions),
        )


async def _create_canary_composition(
    *,
    journal: CodingAppHostCanaryControlJournal,
    attempts: _AttemptFactory,
) -> tuple[CodingAppHostCompositionV1, SessionCandidateRefV1]:
    session_id = token_hex(16)
    generation_id = f"g10-{token_hex(16)}"
    envelope = SessionIdentityEnvelopeV1(
        product_id=CODING_PRODUCT_ID,
        product_compatibility_id=_COMPATIBILITY_ID,
        continuity_id=f"continuity-{session_id}",
        session_id=session_id,
        provider_id="g10-ephemeral",
        locator_token=token_hex(16),
    )
    candidate = _SessionCandidate(envelope)
    product_identity = AdmissionIdentityV1(
        generation_id,
        AppHostAdmissionSubjectKind.PRODUCT,
        CODING_PRODUCT_ID,
    )
    profile_identity = AdmissionIdentityV1(
        generation_id,
        AppHostAdmissionSubjectKind.PROFILE,
        _PROFILE_ID,
    )
    composition = await create_coding_apphost_composition(
        CodingAppHostCompositionRequestV1(
            activation=CodingAppHostCompositionActivationV1(),
            generation_id=generation_id,
            product_version="g10-canary-v1",
            compatibility_id=_COMPATIBILITY_ID,
            product_admission_source=_AdmissionSource(product_identity),
            candidate_validator=_CandidateValidator(),
            attempt_factory=attempts,
            profiles=(
                ProfileRegistrationV1(
                    descriptor=ProfileDescriptorV1(_PROFILE_ID, "1.0"),
                    factory=_ProfileFactory(),
                    admission_identity=profile_identity,
                    admission_source=_AdmissionSource(profile_identity),
                ),
            ),
            sessions=_EphemeralSessions(candidate),
            rollback_control=_RollbackControl(journal),
            shutdown_budget=AppHostShutdownBudgetV1(5.0, 2.0),
        )
    )
    return composition, candidate.projection.reference


def _worker_policy(
    *,
    binding_key: SessionBindingKeyV1,
    selection_generation: int,
) -> ProductWorkerActivationPolicyV1:
    return ProductWorkerActivationPolicyV1(
        product_id=CODING_PRODUCT_ID,
        product_runtime_id=f"g10-runtime-{binding_key.session_id}",
        product_scope_id=f"g10.session.{binding_key.session_id}",
        session_id=binding_key.session_id,
        session_route="selected",
        selected_locator_fingerprint=_DIGESTS["locator"],
        selected_locator_revision=_DIGESTS["locator"],
        plugin_id="apphost-canary",
        plugin_revision_digest=_DIGESTS["plugin"],
        contribution_id="native-probe",
        reservation_fingerprint=_DIGESTS["reservation"],
        declaration_fingerprint=_DIGESTS["declaration"],
        worker_configuration_fingerprint=_DIGESTS["configuration"],
        declared_required=True,
        effective_required=True,
        enabled=True,
        allowed_product_ids=(CODING_PRODUCT_ID,),
        allowed_contribution_ids=("native-probe",),
        requested_owner="hosting",
        owner_selection_generation=selection_generation,
        no_fallback=True,
        native_profile_id="native-canary-v1",
        native_profile_catalog_revision="g10-native-catalog-v1",
        allowed_native_profile_ids=("native-canary-v1",),
        expected_native_policy_closure_fingerprint=_DIGESTS["native-policy"],
        product_policy_revision=f"g10-control-{selection_generation}",
        kill_switch_generation=max(0, selection_generation - 1),
    )


def _child_environment() -> tuple[tuple[str, str], ...]:
    selected = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            selected[name] = value
    return tuple(sorted(selected.items()))


async def _read_protocol_line(lease: ProcessLease) -> bytes:
    output = bytearray()
    while b"\n" not in output:
        remaining = CODING_APPHOST_CANARY_MAX_PROTOCOL_BYTES + 1 - len(output)
        if remaining <= 0:
            raise CodingAppHostCanaryError(
                code="coding_apphost_canary_protocol_oversize"
            )
        chunk = await lease.read_stdout(remaining)
        if not chunk:
            break
        output.extend(chunk)
    if len(output) > CODING_APPHOST_CANARY_MAX_PROTOCOL_BYTES:
        raise CodingAppHostCanaryError(code="coding_apphost_canary_protocol_oversize")
    if b"\n" in output and await lease.read_stdout(1):
        raise CodingAppHostCanaryError(
            code="coding_apphost_canary_protocol_trailing_data"
        )
    return bytes(output)


async def _settle_canary_cleanup(
    lease: Any | None,
    composition: CodingAppHostCompositionV1 | None,
) -> bool:
    failures: list[BaseException] = []
    if lease is not None:
        try:
            await lease.close()
        except BaseException as error:
            failures.append(error)
    if composition is not None:
        try:
            await composition.close()
        except BaseException as error:
            failures.append(error)
    return not failures


async def _join_canary_cleanup(
    lease: Any | None,
    composition: CodingAppHostCompositionV1 | None,
) -> None:
    operation = asyncio.create_task(_settle_canary_cleanup(lease, composition))
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                break
            cancellation = error
    cleanup_complete = operation.result()
    if not cleanup_complete:
        raise CodingAppHostCanaryError(code="coding_apphost_canary_cleanup_incomplete")
    if cancellation is not None:
        raise cancellation


def _control_report(
    operation: CodingAppHostCanaryOperation,
    snapshot: CodingAppHostCanaryControlSnapshotV1,
) -> CodingAppHostCanaryReportV1:
    return CodingAppHostCanaryReportV1(
        operation=operation,
        state=snapshot.state,
        code=f"coding_apphost_canary_{snapshot.state}",
        selection_generation=snapshot.selection_generation,
    )


def _control_failure_report(
    operation: CodingAppHostCanaryOperation,
    *,
    code: str,
    selection_generation: int,
) -> CodingAppHostCanaryReportV1:
    return CodingAppHostCanaryReportV1(
        operation=operation,
        state="failed",
        code=code,
        selection_generation=selection_generation,
    )


__all__ = [
    "CODING_APPHOST_CANARY_MAX_PROTOCOL_BYTES",
    "CODING_APPHOST_CANARY_MAX_TRANSITIONS",
    "CODING_APPHOST_CANARY_REPORT_VERSION",
    "CODING_APPHOST_CANARY_TIMEOUT_SECONDS",
    "CodingAppHostCanaryError",
    "CodingAppHostCanaryReportV1",
    "CodingAppHostCanaryRequestV1",
    "run_coding_apphost_canary",
]
