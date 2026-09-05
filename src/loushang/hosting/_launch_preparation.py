"""Private H6.1 request-bound opaque launch-preparation ownership.

This module deliberately has no public composition entrypoint.  It freezes the
cross-platform ownership state machine against deterministic fakes before the
H6.2 and H6.3 native adapters exist.
"""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar, cast, runtime_checkable

from ._process_backend import (
    _ManagedProcessPreparation,
    _ProcessBackend,
    _ProcessInheritance,
    _ProcessTransport,
)
from .contracts import LaunchPreparationLease, ProcessLaunchRequest
from .errors import HostingError, HostingFailureCategory

_T = TypeVar("_T")
_MAX_PROFILE_ID_LENGTH = 128
_MAX_ATTEMPT_ID_LENGTH = 128
_MAX_CLOSURE_IDENTITIES = 64
_MAX_IDENTITY_LENGTH = 512
_MAX_BACKEND_ID_LENGTH = 128
_MAX_INHERITED_SLOTS = 64


@dataclass(frozen=True, slots=True)
class _LaunchCaptureSpec:
    """Neutral capture intent; platform details remain inside the backend."""

    request: ProcessLaunchRequest
    profile_id: str
    execution_closure: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProcessLaunchRequest):
            raise TypeError("launch capture requires a ProcessLaunchRequest")
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or len(self.profile_id) > _MAX_PROFILE_ID_LENGTH
            or self.profile_id != self.profile_id.strip()
            or "\0" in self.profile_id
        ):
            raise ValueError("launch capture profile_id is invalid")
        closure = tuple(self.execution_closure)
        if not closure or len(closure) > _MAX_CLOSURE_IDENTITIES:
            raise ValueError("launch capture execution closure is invalid")
        if any(
            not isinstance(identity, str)
            or not identity
            or len(identity) > _MAX_IDENTITY_LENGTH
            or identity != identity.strip()
            or "\0" in identity
            for identity in closure
        ):
            raise ValueError("launch capture execution identity is invalid")
        if len(set(closure)) != len(closure):
            raise ValueError("launch capture execution identities must be unique")
        object.__setattr__(self, "execution_closure", closure)


class _OpaqueLaunchBinding:
    """Non-owning token proving which reservation produced captured material."""

    __slots__ = ("_authority", "_nonce")

    def __init__(self, authority: object, nonce: object) -> None:
        self._authority = authority
        self._nonce = nonce


@dataclass(frozen=True, slots=True)
class _ManagedLaunchPreparationResult:
    """Caller semantic lease joined to one opaque Hosting binding."""

    lease: LaunchPreparationLease
    binding: _OpaqueLaunchBinding

    def __post_init__(self) -> None:
        if not isinstance(self.lease, LaunchPreparationLease):
            raise TypeError("managed preparation returned an invalid caller lease")
        if not isinstance(self.binding, _OpaqueLaunchBinding):
            raise TypeError("managed preparation returned an invalid opaque binding")


@runtime_checkable
class _LaunchCapturePort(Protocol):
    """Leaf capability minted for one already-reserved start transaction."""

    async def capture(self, spec: _LaunchCaptureSpec) -> _OpaqueLaunchBinding: ...


class _ManagedLaunchPreparationPort(ABC):
    """Private two-sided caller port; the public H0--H5 port stays unchanged."""

    @abstractmethod
    async def prepare_managed(
        self,
        request: ProcessLaunchRequest,
        capture: _LaunchCapturePort,
    ) -> _ManagedLaunchPreparationResult:
        raise NotImplementedError


@runtime_checkable
class _CapturedLaunchMaterial(Protocol):
    """Backend-owned native material; raw values never cross the caller seam."""

    @property
    def backend_id(self) -> str: ...

    @property
    def attempt_id(self) -> str: ...

    @property
    def attempt_token(self) -> object: ...

    @property
    def profile_id(self) -> str: ...

    @property
    def execution_closure(self) -> tuple[str, ...]: ...

    @property
    def request(self) -> ProcessLaunchRequest: ...

    @property
    def inherited_slot_count(self) -> int: ...

    async def verify_current(self, request: ProcessLaunchRequest) -> None: ...

    async def spawn(
        self,
        backend: _ProcessBackend,
        request: ProcessLaunchRequest,
        *,
        effect: "_ManagedSpawnEffect",
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _ProcessTransport:
        """Perform matched-backend preparation plus the unique spawn effect."""

    async def close(self) -> None: ...


class _LaunchCaptureBackend(Protocol):
    """Selected-platform acquisition seam used only by trusted composition."""

    @property
    def backend_id(self) -> str: ...

    async def capture(
        self,
        spec: _LaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
    ) -> _CapturedLaunchMaterial:
        """Acquire and attach before the first post-acquisition cancellation point."""


class _ReservationLaunchCapture(_LaunchCapturePort):
    """One reservation-bound acquisition authority and state coordinator."""

    def __init__(
        self,
        backend: _LaunchCaptureBackend,
        *,
        attempt_id: str,
        max_inherited_slots: int,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
        on_orphan: Callable[[_CapturedLaunchMaterial], None],
    ) -> None:
        if (
            type(max_inherited_slots) is not int
            or max_inherited_slots < 1
            or max_inherited_slots > _MAX_INHERITED_SLOTS
        ):
            raise ValueError("managed launch inherited-slot bound is invalid")
        backend_id = backend.backend_id
        if (
            not isinstance(backend_id, str)
            or not backend_id
            or len(backend_id) > _MAX_BACKEND_ID_LENGTH
            or backend_id != backend_id.strip()
            or "\0" in backend_id
        ):
            raise ValueError("managed launch backend_id is invalid")
        if (
            not isinstance(attempt_id, str)
            or not attempt_id
            or len(attempt_id) > _MAX_ATTEMPT_ID_LENGTH
            or attempt_id != attempt_id.strip()
            or "\0" in attempt_id
        ):
            raise ValueError("managed launch attempt_id is invalid")
        self._backend = backend
        self._attempt_id = attempt_id
        self._max_inherited_slots = max_inherited_slots
        self._on_capture = on_capture
        self._on_orphan = on_orphan
        self._attempt_token = object()
        self._state = "minted"
        self._material: _CapturedLaunchMaterial | None = None
        self._spec: _LaunchCaptureSpec | None = None
        self._binding_nonce = object()
        self._state_lock = threading.Lock()
        self._operation_lock = asyncio.Lock()

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def material(self) -> _CapturedLaunchMaterial | None:
        with self._state_lock:
            return self._material

    async def capture(self, spec: _LaunchCaptureSpec) -> _OpaqueLaunchBinding:
        if not isinstance(spec, _LaunchCaptureSpec):
            raise TypeError("managed launch capture requires _LaunchCaptureSpec")
        async with self._operation_lock:
            with self._state_lock:
                if self._state != "minted":
                    raise HostingError(
                        HostingFailureCategory.PREPARATION_FAILED,
                        "managed launch capture is single-use",
                    )
                self._state = "capturing"
                self._spec = spec
            task = asyncio.create_task(
                self._backend.capture(
                    spec,
                    attempt_id=self._attempt_id,
                    attempt_token=self._attempt_token,
                    on_capture=self._attach,
                ),
                name=f"hosting-{self._attempt_id}-native-capture",
            )
            try:
                returned = await _await_owned(task)
            except BaseException as primary:
                with self._state_lock:
                    attached = self._material
                    self._state = "closed" if attached is None else "faulted"
                if task.done() and not task.cancelled():
                    try:
                        orphan = task.result()
                    except BaseException:
                        pass
                    else:
                        if orphan is not attached:
                            self._attach_orphan(orphan, primary=primary)
                raise
            with self._state_lock:
                attached = self._material
                if returned is attached:
                    self._state = "captured"
                    return _OpaqueLaunchBinding(self, self._binding_nonce)
                self._state = "faulted"
            if attached is None:
                contract_error = RuntimeError(
                    "launch capture backend returned before owner attachment"
                )
                try:
                    self._validate_material(returned)
                    self._on_capture(returned)
                except BaseException as attach_error:
                    self._attach_orphan(returned, primary=attach_error)
                    raise contract_error from attach_error
                with self._state_lock:
                    self._material = returned
                    self._state = "captured"
                raise contract_error
            contract_error = RuntimeError(
                "launch capture backend returned a different material owner"
            )
            self._attach_orphan(returned, primary=contract_error)
            raise contract_error

    def bind_result(
        self,
        result: _ManagedLaunchPreparationResult,
    ) -> "_ManagedPreparationLease":
        if not isinstance(result, _ManagedLaunchPreparationResult):
            raise TypeError("managed launch preparation returned an invalid result")
        prepared_request = result.lease.request
        if not isinstance(prepared_request, ProcessLaunchRequest):
            raise TypeError("managed caller lease returned an invalid request")
        with self._state_lock:
            binding = result.binding
            if (
                binding._authority is not self
                or binding._nonce is not self._binding_nonce
            ):
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch binding targets a different reservation",
                )
            if self._state != "captured" or self._material is None:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch binding is unavailable",
                )
            if self._spec is None or self._spec.request != prepared_request:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch capture does not match the prepared request",
                )
            material = self._material
            self._binding_nonce = object()
            return _ManagedPreparationLease(result.lease, material, self)

    def _attach(self, material: _CapturedLaunchMaterial) -> None:
        with self._state_lock:
            if self._state != "capturing" or self._material is not None:
                raise RuntimeError("launch capture material attached more than once")
            self._validate_material(material)
            self._on_capture(material)
            self._material = material

    def _validate_material(self, material: object) -> None:
        if not isinstance(material, _CapturedLaunchMaterial):
            raise TypeError("launch capture backend returned invalid material")
        assert self._spec is not None
        if (
            material.backend_id != self._backend.backend_id
            or material.attempt_id != self._attempt_id
            or material.attempt_token is not self._attempt_token
            or material.request != self._spec.request
            or material.profile_id != self._spec.profile_id
            or material.execution_closure != self._spec.execution_closure
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "captured launch material has incompatible identity",
            )
        count = material.inherited_slot_count
        if type(count) is not int or count < 0 or count > self._max_inherited_slots:
            raise HostingError(
                HostingFailureCategory.CAPACITY_EXHAUSTED,
                "captured launch material exceeds its inherited-slot bound",
            )

    def _attach_orphan(self, material: object, *, primary: BaseException) -> None:
        if not isinstance(material, _CapturedLaunchMaterial):
            return
        try:
            self._on_orphan(material)
        except BaseException as attach_error:
            primary.add_note(
                f"orphan launch material attachment also failed: {attach_error}"
            )

    def begin_verify(self, material: _CapturedLaunchMaterial) -> None:
        with self._state_lock:
            if self._material is not material or self._state != "captured":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch material cannot be verified in its current state",
                )
            try:
                self._validate_material(material)
            except BaseException:
                self._state = "faulted"
                raise
            self._state = "verifying"

    def finish_verify(self, material: _CapturedLaunchMaterial, *, success: bool) -> None:
        with self._state_lock:
            if self._material is not material or self._state != "verifying":
                raise RuntimeError("managed launch verification state is inconsistent")
            self._state = "verified" if success else "captured"

    def begin_spawn(
        self,
        material: _CapturedLaunchMaterial,
        *,
        backend_id: str,
    ) -> None:
        with self._state_lock:
            if self._material is not material or self._state != "verified":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch material is not verified for spawn",
                )
            try:
                self._validate_material(material)
            except BaseException:
                self._state = "faulted"
                raise
            if backend_id != self._backend.backend_id:
                self._state = "faulted"
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "managed launch material targets a different process backend",
                )
            self._state = "claimed"

    def reject_spawn(self, material: _CapturedLaunchMaterial) -> None:
        with self._state_lock:
            if self._material is material and self._state == "verified":
                self._state = "faulted"

    def finish_spawn(
        self,
        material: _CapturedLaunchMaterial,
        *,
        outcome: str,
    ) -> None:
        with self._state_lock:
            if self._material is not material or self._state != "claimed":
                raise RuntimeError("managed launch spawn state is inconsistent")
            if outcome not in {"attached", "not-created", "fenced"}:
                raise ValueError("managed launch spawn outcome is invalid")
            self._state = {
                "attached": "attached",
                "not-created": "faulted",
                "fenced": "fenced",
            }[outcome]

    def mark_closed(self, material: _CapturedLaunchMaterial, *, success: bool) -> None:
        with self._state_lock:
            if self._material is material:
                self._state = "closed" if success else "faulted"

    def begin_close(self, material: _CapturedLaunchMaterial) -> None:
        with self._state_lock:
            if self._material is not material:
                raise RuntimeError("managed launch close owner is inconsistent")
            if self._state == "closed":
                return
            if self._state == "closing":
                raise RuntimeError("managed launch close is already active")
            if self._state == "fenced":
                raise HostingError(
                    HostingFailureCategory.CLEANUP_FAILED,
                    "managed launch outcome is fenced and cannot be reclaimed",
                )
            self._state = "closing"


class _ManagedSpawnNotCreated(Exception):
    """Authority-minted receipt that the unique OS creation effect did not run."""

    def __init__(self, cause: BaseException, receipt: object) -> None:
        super().__init__("managed launch did not create a process")
        self.cause = cause
        self._receipt = receipt


class _ManagedSpawnSettledWithoutProcess(Exception):
    """Authority receipt for an attempted effect known to own no process."""

    def __init__(self, cause: BaseException, receipt: object) -> None:
        super().__init__("managed launch attempt settled without a process")
        self.cause = cause
        self._receipt = receipt


class _ManagedSpawnEffect:
    """One authority-owned witness around the native process-creation effect."""

    def __init__(self) -> None:
        self._receipt = object()
        self._state = "ready"
        self._attached: _ProcessTransport | None = None
        self._lock = threading.Lock()

    def begin_effect(self) -> None:
        """Fence immediately before the backend may create an OS process."""

        with self._lock:
            if self._state != "ready":
                raise RuntimeError("managed process creation effect began more than once")
            self._state = "started"

    def observe_attachment(self, process: _ProcessTransport) -> None:
        with self._lock:
            if self._state == "ready":
                self._attached = process
                self._state = "invalid-attached"
                raise RuntimeError(
                    "managed process attached before its creation effect gate"
                )
            if self._attached is not None and self._attached is not process:
                raise RuntimeError("managed process attachment identity changed")
            if self._state not in {"started", "attached"}:
                raise RuntimeError("managed process attachment state is invalid")
            self._attached = process
            self._state = "attached"

    def not_created(self, cause: BaseException) -> _ManagedSpawnNotCreated:
        """Mint a receipt; it remains valid only while no effect has begun."""

        return _ManagedSpawnNotCreated(cause, self._receipt)

    def settled_without_process(
        self, cause: BaseException
    ) -> _ManagedSpawnSettledWithoutProcess:
        """Settle one begun native attempt that proved it owns no process."""

        with self._lock:
            if self._state != "started" or self._attached is not None:
                raise RuntimeError(
                    "managed process attempt cannot settle without a process"
                )
            self._state = "settled-without-process"
            return _ManagedSpawnSettledWithoutProcess(cause, self._receipt)

    def accepts(self, failure: _ManagedSpawnNotCreated) -> bool:
        with self._lock:
            return (
                failure._receipt is self._receipt
                and self._state == "ready"
                and self._attached is None
            )

    def accepts_settled(
        self, failure: _ManagedSpawnSettledWithoutProcess
    ) -> bool:
        with self._lock:
            return (
                failure._receipt is self._receipt
                and self._state == "settled-without-process"
                and self._attached is None
            )

    def observes(self, process: _ProcessTransport) -> bool:
        """Return whether the reservation gate has seen this exact owner."""

        with self._lock:
            return self._attached is process


class _ManagedPreparationLease(LaunchPreparationLease, _ManagedProcessPreparation):
    """Joins caller semantics and Hosting native ownership without blending them."""

    def __init__(
        self,
        caller: LaunchPreparationLease,
        material: _CapturedLaunchMaterial,
        authority: _ReservationLaunchCapture,
    ) -> None:
        self._caller = caller
        self._material = material
        self._authority = authority
        self._operation_lock = asyncio.Lock()
        self._verify_task: asyncio.Task[None] | None = None
        self._spawn_task: asyncio.Task[_ProcessTransport] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._caller_closed = False
        self._material_closed = False

    @property
    def request(self) -> ProcessLaunchRequest:
        return self._caller.request

    @property
    def backend_id(self) -> str:
        return self._material.backend_id

    async def verify_current(self) -> None:
        async with self._operation_lock:
            if self._close_task is not None:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch preparation is closing",
                )
            if self._verify_task is not None:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch preparation verification is single-use",
                )
            self._authority.begin_verify(self._material)
            task = asyncio.create_task(
                self._verify_owned(),
                name=f"hosting-{self._material.attempt_id}-preparation-verify",
            )
            self._verify_task = task
        await _await_owned(task)

    async def _verify_owned(self) -> None:
        success = False
        try:
            await self._caller.verify_current()
            await self._material.verify_current(self.request)
            success = True
        finally:
            self._authority.finish_verify(self._material, success=success)

    async def spawn_prepared(
        self,
        backend: _ProcessBackend,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        on_orphan_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _ProcessTransport:
        async with self._operation_lock:
            if self._close_task is not None:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch preparation is closing",
                )
            if self._spawn_task is not None:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch spawn is single-use",
                )
            if request != self.request:
                self._authority.reject_spawn(self._material)
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "managed launch spawn request was retargeted",
                )
            self._authority.begin_spawn(
                self._material,
                backend_id=backend.backend_id,
            )
            task = asyncio.create_task(
                self._spawn_owned(
                    backend,
                    request,
                    on_spawn=on_spawn,
                    on_orphan_spawn=on_orphan_spawn,
                    inheritance=inheritance,
                ),
                name=f"hosting-{self._material.attempt_id}-prepared-spawn",
            )
            self._spawn_task = task
        return await _await_owned(task)

    async def _spawn_owned(
        self,
        backend: _ProcessBackend,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        on_orphan_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _ProcessTransport:
        outcome = "fenced"
        attached: _ProcessTransport | None = None
        effect = _ManagedSpawnEffect()

        def attach(process: _ProcessTransport) -> None:
            nonlocal attached
            if attached is None:
                on_spawn(process)
                attached = process
                effect.observe_attachment(process)
                return
            if process is attached:
                on_spawn(process)
                return
            on_orphan_spawn(process)
            raise RuntimeError(
                "managed process backend attached more than one process"
            )

        try:
            process = await self._material.spawn(
                backend,
                request,
                effect=effect,
                on_spawn=attach,
                inheritance=inheritance,
            )
            if attached is None:
                on_spawn(process)
                attached = process
                effect.observe_attachment(process)
                outcome = "attached"
                raise RuntimeError(
                    "managed process backend returned before owner attachment"
                )
            if process is not attached:
                on_orphan_spawn(process)
                outcome = "attached"
                raise RuntimeError(
                    "managed process backend returned a different process owner"
                )
            outcome = "attached"
            return process
        except _ManagedSpawnNotCreated as failure:
            if effect.accepts(failure):
                outcome = "not-created"
            raise failure.cause from failure
        except _ManagedSpawnSettledWithoutProcess as failure:
            if effect.accepts_settled(failure):
                outcome = "not-created"
            raise failure.cause from failure
        finally:
            self._authority.finish_spawn(self._material, outcome=outcome)

    async def close(self) -> None:
        async with self._operation_lock:
            task = self._close_task
            if task is None:
                task = asyncio.create_task(
                    self._close_owned(),
                    name=f"hosting-{self._material.attempt_id}-preparation-close",
                )
                self._close_task = task
        try:
            await _await_owned(task)
        except BaseException:
            async with self._operation_lock:
                if self._close_task is task and _owner_task_failed(task):
                    self._close_task = None
            raise

    async def _close_owned(self) -> None:
        verify = self._verify_task
        if verify is not None and not verify.done():
            await asyncio.gather(asyncio.shield(verify), return_exceptions=True)
        spawn = self._spawn_task
        if spawn is not None and not spawn.done():
            await asyncio.gather(asyncio.shield(spawn), return_exceptions=True)
        self._authority.begin_close(self._material)
        failures: list[BaseException] = []
        if not self._material_closed:
            try:
                await self._material.close()
            except BaseException as error:
                failures.append(error)
            else:
                self._material_closed = True
        if not self._caller_closed:
            try:
                await self._caller.close()
            except BaseException as error:
                failures.append(error)
            else:
                self._caller_closed = True
        success = self._caller_closed and self._material_closed
        self._authority.mark_closed(self._material, success=success)
        if failures:
            raise BaseExceptionGroup(
                "managed launch preparation cleanup failed",
                failures,
            )


async def _await_owned(task: asyncio.Task[_T]) -> _T:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = exc
        except BaseException as exc:
            if cancellation is not None:
                raise cancellation from exc
            raise
    if cancellation is not None:
        raise cancellation
    return cast(_T, result)


def _owner_task_failed(task: asyncio.Task[object]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


__all__: list[str] = []
