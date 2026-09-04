"""Product-neutral bounded lifecycle supervisor for one local Worker attempt."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from secrets import token_hex
from typing import Literal, cast

from .contracts import ManagedWorkerLaunchRequestV1, WorkerLaunchIdentityV1
from .journal import (
    WorkerAttemptPhase,
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
)
from .launch import ManagedWorkerLaunchPort, ManagedWorkerProcess
from .protocol import (
    WorkerFramedTransport,
    WorkerProtocolError,
    WorkerProtocolMessage,
)

WORKER_SUPERVISOR_LIMITS_VERSION = 1
WORKER_SUPERVISOR_STATUS_VERSION = 1
WORKER_SUPERVISOR_MAX_IN_FLIGHT = 1024
WORKER_SUPERVISOR_MAX_TOMBSTONES = 4096
WORKER_SUPERVISOR_MAX_ATTEMPTS = 32
WORKER_SUPERVISOR_MAX_MESSAGES_PER_SESSION = 65_536
WORKER_SUPERVISOR_MAX_TIMEOUT_SECONDS = 3600.0

WorkerSupervisorState = Literal[
    "created",
    "launching",
    "handshaking",
    "healthy",
    "draining",
    "stopped",
    "failed",
    "fenced",
]


class WorkerSupervisorError(RuntimeError):
    """Stable, redacted local Worker lifecycle failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        attempt_id: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.attempt_id = attempt_id


class WorkerRemoteFailure(WorkerSupervisorError):
    def __init__(
        self,
        *,
        code: str,
        attempt_id: str,
        retryable: bool,
    ) -> None:
        super().__init__(
            "Local Worker refused the bounded request",
            code=code,
            attempt_id=attempt_id,
        )
        self.retryable = retryable


def _require_timeout(value: object, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
        or value > WORKER_SUPERVISOR_MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(f"{name} is outside its supported bound")
    return float(value)


@dataclass(frozen=True, slots=True)
class WorkerSupervisorLimitsV1:
    max_in_flight: int = 32
    max_tombstones: int = 128
    max_attempts: int = 3
    max_messages_per_session: int = 4096
    handshake_timeout_seconds: float = 5.0
    query_timeout_seconds: float = 30.0
    heartbeat_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    limits_version: int = WORKER_SUPERVISOR_LIMITS_VERSION

    def __post_init__(self) -> None:
        for name, integer_value, maximum in (
            (
                "max in-flight requests",
                self.max_in_flight,
                WORKER_SUPERVISOR_MAX_IN_FLIGHT,
            ),
            (
                "max cancellation tombstones",
                self.max_tombstones,
                WORKER_SUPERVISOR_MAX_TOMBSTONES,
            ),
            (
                "max Worker attempts",
                self.max_attempts,
                WORKER_SUPERVISOR_MAX_ATTEMPTS,
            ),
            (
                "max messages per Worker session",
                self.max_messages_per_session,
                WORKER_SUPERVISOR_MAX_MESSAGES_PER_SESSION,
            ),
        ):
            if (
                isinstance(integer_value, bool)
                or not isinstance(integer_value, int)
                or integer_value < 1
                or integer_value > maximum
            ):
                raise ValueError(f"{name} is outside its supported bound")
        for name, timeout_value in (
            ("handshake timeout", self.handshake_timeout_seconds),
            ("query timeout", self.query_timeout_seconds),
            ("heartbeat timeout", self.heartbeat_timeout_seconds),
            ("shutdown timeout", self.shutdown_timeout_seconds),
        ):
            _require_timeout(timeout_value, name=name)
        if (
            type(self.limits_version) is not int
            or self.limits_version != WORKER_SUPERVISOR_LIMITS_VERSION
        ):
            raise ValueError("Unsupported Worker supervisor limits version")


@dataclass(frozen=True, slots=True)
class WorkerSupervisorStatusV1:
    attempt_id: str
    supervisor_epoch: int
    state: WorkerSupervisorState
    journal_revision: int
    pending_requests: int
    cancellation_tombstones: int
    failure_code: str | None = None
    status_version: int = WORKER_SUPERVISOR_STATUS_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempt_id, str)
            or len(self.attempt_id) != 32
            or any(char not in "0123456789abcdef" for char in self.attempt_id)
        ):
            raise ValueError("Worker supervisor status attempt id is invalid")
        for name, value, minimum in (
            ("supervisor epoch", self.supervisor_epoch, 1),
            ("journal revision", self.journal_revision, 0),
            ("pending request count", self.pending_requests, 0),
            ("cancellation tombstone count", self.cancellation_tombstones, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"Worker supervisor status {name} is invalid")
        if self.state not in {
            "created",
            "launching",
            "handshaking",
            "healthy",
            "draining",
            "stopped",
            "failed",
            "fenced",
        }:
            raise ValueError("Worker supervisor status state is invalid")
        if self.failure_code is not None:
            _require_failure_code(self.failure_code)
        if (
            type(self.status_version) is not int
            or self.status_version != WORKER_SUPERVISOR_STATUS_VERSION
        ):
            raise ValueError("Unsupported Worker supervisor status version")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "cancellationTombstones": self.cancellation_tombstones,
            "failureCode": self.failure_code,
            "journalRevision": self.journal_revision,
            "pendingRequests": self.pending_requests,
            "state": self.state,
            "statusVersion": self.status_version,
            "supervisorEpoch": self.supervisor_epoch,
        }


class WorkerSupervisor:
    """Own protocol mechanics for one identity; it cannot publish domain state."""

    def __init__(
        self,
        *,
        identity: WorkerLaunchIdentityV1,
        journal: WorkerSupervisorJournal,
        protocol: str,
        protocol_version: int,
        limits: WorkerSupervisorLimitsV1 = WorkerSupervisorLimitsV1(),
        correlation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(identity, WorkerLaunchIdentityV1):
            raise TypeError("Worker supervisor requires a launch identity")
        if not isinstance(journal, WorkerSupervisorJournal):
            raise TypeError("Worker supervisor requires its durable journal")
        _require_protocol_identifier(protocol, name="Worker supervisor protocol")
        if (
            isinstance(protocol_version, bool)
            or not isinstance(protocol_version, int)
            or protocol_version < 1
        ):
            raise ValueError("Worker supervisor protocol version must be positive")
        if not isinstance(limits, WorkerSupervisorLimitsV1):
            raise TypeError("Worker supervisor requires typed limits")
        if correlation_id_factory is not None and not callable(correlation_id_factory):
            raise TypeError("Worker correlation id factory must be callable")
        self._identity = identity
        self._journal = journal
        self._protocol = protocol
        self._protocol_version = protocol_version
        self._limits = limits
        self._correlation_id_factory = correlation_id_factory or (lambda: token_hex(16))
        self._state: WorkerSupervisorState = "created"
        self._failure_code: str | None = None
        self._record: WorkerAttemptRecordV1 | None = None
        self._process: ManagedWorkerProcess | None = None
        self._transport: WorkerFramedTransport | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._exit_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[Mapping[str, object]]] = {}
        self._tombstones: deque[str] = deque(maxlen=limits.max_tombstones)
        self._cancel_ack_pending: set[str] = set()
        self._issued_ids: set[str] = set()
        self._heartbeat_waiter: tuple[str, asyncio.Future[None]] | None = None
        self._shutdown_waiter: asyncio.Future[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def identity(self) -> WorkerLaunchIdentityV1:
        return self._identity

    @property
    def status(self) -> WorkerSupervisorStatusV1:
        record = self._record
        return WorkerSupervisorStatusV1(
            attempt_id=self._identity.attempt_id,
            supervisor_epoch=self._identity.supervisor_epoch,
            state=self._state,
            journal_revision=0 if record is None else record.record_revision,
            pending_requests=len(self._pending),
            cancellation_tombstones=len(self._tombstones),
            failure_code=self._failure_code,
        )

    async def start(
        self,
        *,
        launch_port: ManagedWorkerLaunchPort,
        launch_request: ManagedWorkerLaunchRequestV1,
        transport: WorkerFramedTransport,
        correlation_id: str,
        signal: object | None = None,
    ) -> None:
        if not isinstance(launch_request, ManagedWorkerLaunchRequestV1):
            raise TypeError("Worker supervisor requires a typed launch request")
        if not callable(getattr(launch_port, "start", None)):
            raise TypeError("Worker supervisor requires a launch port")
        if launch_request.identity != self._identity:
            raise ValueError("Worker launch request identity changed at supervisor")
        if (
            launch_request.runtime.protocol != self._protocol
            or launch_request.runtime.protocol_version != self._protocol_version
        ):
            raise ValueError(
                "Worker supervisor protocol does not match the runtime binding"
            )
        if not isinstance(transport, WorkerFramedTransport):
            raise TypeError("Worker supervisor requires a framed transport")
        _require_protocol_identifier(
            correlation_id,
            name="Worker launch correlation id",
        )
        async with self._lock:
            if self._state != "created":
                raise self._error(
                    "Worker supervisor is single-use",
                    code="worker_supervisor_already_started",
                )
            self._record = self._journal.claim(
                self._identity,
                max_attempts=self._limits.max_attempts,
            )
            self._transition_locked("launching")
            self._transport = transport
        try:
            process = await launch_port.start(
                launch_request,
                correlation_id=correlation_id,
                signal=signal,
            )
        except asyncio.CancelledError:
            await self._terminal_failure("worker_launch_cancelled", fenced=False)
            raise
        except BaseException as exc:
            await self._terminal_failure("worker_launch_failed", fenced=False)
            raise self._error(
                "Managed Worker launch failed",
                code="worker_launch_failed",
            ) from exc
        self._process = process
        try:
            async with self._lock:
                self._transition_locked("handshaking")
        except Exception as exc:
            await self._terminal_failure(
                "worker_supervisor_journal_failed",
                fenced=True,
            )
            raise self._error(
                "Managed Worker launch evidence could not be committed",
                code="worker_supervisor_journal_failed",
            ) from exc
        try:
            await transport.send(
                WorkerProtocolMessage.create(
                    "start",
                    identity=self._identity.to_dict(),
                    protocol=self._protocol,
                    protocolVersion=self._protocol_version,
                ),
                direction="host_to_worker",
            )
            ready = await asyncio.wait_for(
                transport.receive(direction="worker_to_host"),
                timeout=self._limits.handshake_timeout_seconds,
            )
            self._validate_ready(ready)
        except asyncio.CancelledError:
            await self._terminal_failure("worker_handshake_cancelled", fenced=True)
            raise
        except asyncio.TimeoutError as exc:
            await self._terminal_failure("worker_handshake_timeout", fenced=True)
            raise self._error(
                "Managed Worker handshake timed out",
                code="worker_handshake_timeout",
            ) from exc
        except WorkerProtocolError as exc:
            await self._terminal_failure(exc.code, fenced=True)
            raise self._error(
                "Managed Worker handshake violated its protocol",
                code=exc.code,
            ) from exc
        except BaseException as exc:
            await self._terminal_failure("worker_handshake_failed", fenced=True)
            raise self._error(
                "Managed Worker handshake failed",
                code="worker_handshake_failed",
            ) from exc
        try:
            async with self._lock:
                self._transition_locked("healthy")
                self._reader_task = asyncio.create_task(
                    self._read_loop(),
                    name=f"worker-protocol-reader-{self._identity.attempt_id}",
                )
                self._exit_task = asyncio.create_task(
                    self._watch_process_exit(),
                    name=f"worker-process-watch-{self._identity.attempt_id}",
                )
        except Exception as exc:
            await self._terminal_failure(
                "worker_supervisor_journal_failed",
                fenced=True,
            )
            raise self._error(
                "Managed Worker healthy evidence could not be committed",
                code="worker_supervisor_journal_failed",
            ) from exc

    async def query(
        self,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, object]:
        if not isinstance(payload, Mapping):
            raise TypeError("Worker query payload must be a mapping")
        timeout = (
            self._limits.query_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        _require_timeout(timeout, name="Worker query timeout")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Mapping[str, object]] = loop.create_future()
        async with self._lock:
            self._require_healthy_locked()
            if len(self._pending) >= self._limits.max_in_flight:
                raise self._error(
                    "Worker request queue is full",
                    code="worker_request_queue_full",
                )
            correlation_id = self._new_correlation_id()
            self._pending[correlation_id] = future
            transport = self._require_transport_locked()
        try:
            await transport.send(
                WorkerProtocolMessage.create(
                    "query",
                    correlationId=correlation_id,
                    payload=dict(payload),
                ),
                direction="host_to_worker",
            )
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self._cancel_pending(correlation_id, code="worker_query_timeout")
            raise self._error(
                "Worker query timed out",
                code="worker_query_timeout",
            ) from exc
        except asyncio.CancelledError:
            await self._cancel_pending(correlation_id, code="worker_query_cancelled")
            raise
        except WorkerProtocolError as exc:
            await self._terminal_failure(exc.code, fenced=True)
            raise self._error(
                "Worker query transport failed",
                code=exc.code,
            ) from exc
        except BaseException:
            async with self._lock:
                self._pending.pop(correlation_id, None)
            raise

    async def heartbeat(self) -> None:
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        async with self._lock:
            self._require_healthy_locked()
            if self._heartbeat_waiter is not None:
                raise self._error(
                    "Worker heartbeat is already pending",
                    code="worker_heartbeat_already_pending",
                )
            heartbeat_id = self._new_correlation_id()
            self._heartbeat_waiter = (heartbeat_id, waiter)
            transport = self._require_transport_locked()
        try:
            await transport.send(
                WorkerProtocolMessage.create("ping", heartbeatId=heartbeat_id),
                direction="host_to_worker",
            )
            await asyncio.wait_for(
                asyncio.shield(waiter),
                timeout=self._limits.heartbeat_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            await self._terminal_failure("worker_heartbeat_timeout", fenced=True)
            raise self._error(
                "Worker heartbeat timed out",
                code="worker_heartbeat_timeout",
            ) from exc
        except asyncio.CancelledError:
            await self._terminal_failure("worker_heartbeat_cancelled", fenced=True)
            raise
        except WorkerProtocolError as exc:
            await self._terminal_failure(exc.code, fenced=True)
            raise self._error(
                "Worker heartbeat transport failed",
                code=exc.code,
            ) from exc
        finally:
            async with self._lock:
                if (
                    self._heartbeat_waiter is not None
                    and self._heartbeat_waiter[0] == heartbeat_id
                ):
                    self._heartbeat_waiter = None

    async def shutdown(self, *, reason: str = "host_shutdown") -> None:
        _require_protocol_identifier(reason, name="Worker shutdown reason")
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        async with self._lock:
            if self._state == "stopped":
                return
            self._require_healthy_locked()
            if self._pending or self._heartbeat_waiter is not None:
                raise self._error(
                    "Worker shutdown requires all requests to be settled",
                    code="worker_shutdown_work_pending",
                )
            self._transition_locked("draining")
            self._shutdown_waiter = waiter
            transport = self._require_transport_locked()
            process = self._require_process_locked()
        try:
            await transport.send(
                WorkerProtocolMessage.create("shutdown", reason=reason),
                direction="host_to_worker",
            )
            try:
                await asyncio.wait_for(
                    asyncio.shield(waiter),
                    timeout=self._limits.shutdown_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise self._error(
                    "Worker shutdown acknowledgement timed out",
                    code="worker_shutdown_timeout",
                ) from exc
            try:
                exit_status = await asyncio.wait_for(
                    process.wait(),
                    timeout=self._limits.shutdown_timeout_seconds,
                )
                if exit_status.return_code != 0:
                    raise self._error(
                        "Worker exited unsuccessfully during shutdown",
                        code="worker_shutdown_exit_failed",
                    )
            except asyncio.TimeoutError as exc:
                raise self._error(
                    "Worker process did not exit after shutdown",
                    code="worker_shutdown_exit_timeout",
                ) from exc
            await transport.close()
            async with self._lock:
                if self._state == "draining":
                    self._transition_locked("stopped")
        except asyncio.CancelledError:
            await self._terminal_failure("worker_shutdown_cancelled", fenced=True)
            raise
        except WorkerSupervisorError as exc:
            await self._terminal_failure(exc.code, fenced=True)
            raise
        except BaseException as exc:
            await self._terminal_failure("worker_shutdown_failed", fenced=True)
            raise self._error(
                "Worker shutdown failed",
                code="worker_shutdown_failed",
            ) from exc
        finally:
            await self._cancel_background_tasks()

    async def fence(self, *, code: str = "worker_fenced") -> None:
        _require_failure_code(code)
        await self._terminal_failure(code, fenced=True)

    async def _read_loop(self) -> None:
        try:
            while True:
                transport = self._transport
                if transport is None:
                    return
                message = await transport.receive(direction="worker_to_host")
                await self._dispatch(message)
                if message.kind == "shutdown_ack":
                    return
        except asyncio.CancelledError:
            raise
        except WorkerProtocolError as exc:
            transport = self._transport
            code = (
                transport.failure_code
                if transport is not None and transport.failure_code is not None
                else exc.code
            )
            await self._terminal_failure(code, fenced=True)
        except BaseException:
            await self._terminal_failure("worker_protocol_failure", fenced=True)

    async def _watch_process_exit(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            exit_status = await process.wait()
        except asyncio.CancelledError:
            raise
        except BaseException:
            await self._terminal_failure("worker_process_wait_failed", fenced=True)
            return
        async with self._lock:
            state = self._state
        if state in {"stopped", "failed", "fenced"}:
            return
        if state == "draining":
            if exit_status.return_code == 0:
                return
            await self._terminal_failure("worker_shutdown_exit_failed", fenced=True)
            return
        await self._terminal_failure("worker_process_exited", fenced=True)

    async def _dispatch(self, message: WorkerProtocolMessage) -> None:
        if message.kind in {"result", "failure", "cancelled"}:
            correlation_id = cast(str, message.fields["correlationId"])
            async with self._lock:
                if message.kind == "cancelled":
                    if (
                        correlation_id in self._tombstones
                        and correlation_id in self._cancel_ack_pending
                    ):
                        self._cancel_ack_pending.remove(correlation_id)
                        return
                    future = None
                else:
                    future = self._pending.pop(correlation_id, None)
                invalid_correlation = (
                    future is None or correlation_id in self._tombstones
                )
            if invalid_correlation or future is None:
                raise WorkerProtocolError(
                    "Worker reply correlation is unknown, duplicate, or late",
                    code="worker_protocol_reply_correlation_invalid",
                )
            if message.kind == "result":
                payload = message.to_dict()["payload"]
                future.set_result(cast(Mapping[str, object], payload))
            elif message.kind == "failure":
                future.set_exception(
                    WorkerRemoteFailure(
                        code=cast(str, message.fields["code"]),
                        retryable=cast(bool, message.fields["retryable"]),
                        attempt_id=self._identity.attempt_id,
                    )
                )
            return
        if message.kind == "pong":
            heartbeat_id = cast(str, message.fields["heartbeatId"])
            async with self._lock:
                current = self._heartbeat_waiter
                if current is None or current[0] != heartbeat_id:
                    raise WorkerProtocolError(
                        "Worker heartbeat correlation is invalid",
                        code="worker_protocol_heartbeat_correlation_invalid",
                    )
                self._heartbeat_waiter = None
            current[1].set_result(None)
            return
        if message.kind == "shutdown_ack":
            async with self._lock:
                waiter = self._shutdown_waiter
                if self._state != "draining" or waiter is None:
                    raise WorkerProtocolError(
                        "Worker shutdown acknowledgement is out of order",
                        code="worker_protocol_shutdown_state_invalid",
                    )
                self._shutdown_waiter = None
            waiter.set_result(None)
            return
        raise WorkerProtocolError(
            "Worker message is illegal after handshake",
            code="worker_protocol_state_invalid",
        )

    async def _cancel_pending(self, correlation_id: str, *, code: str) -> None:
        async with self._lock:
            future = self._pending.pop(correlation_id, None)
            if correlation_id not in self._tombstones:
                if len(self._tombstones) == self._tombstones.maxlen:
                    self._cancel_ack_pending.discard(self._tombstones[0])
                self._tombstones.append(correlation_id)
            self._cancel_ack_pending.add(correlation_id)
            transport = self._transport
        if future is not None and not future.done():
            future.set_exception(self._error("Worker request cancelled", code=code))
            future.exception()
        if transport is not None:
            try:
                await transport.send(
                    WorkerProtocolMessage.create(
                        "cancel",
                        correlationId=correlation_id,
                    ),
                    direction="host_to_worker",
                )
            except BaseException:
                failure_code = (
                    transport.failure_code
                    if transport.failure_code is not None
                    else "worker_cancel_delivery_failed"
                )
                await self._terminal_failure(
                    failure_code,
                    fenced=True,
                )

    async def _terminal_failure(self, code: str, *, fenced: bool) -> None:
        _require_failure_code(code)
        process: ManagedWorkerProcess | None
        transport: WorkerFramedTransport | None
        async with self._lock:
            if self._state in {"stopped", "failed", "fenced"}:
                return
            target: WorkerSupervisorState = "fenced" if fenced else "failed"
            effective_code = code
            try:
                self._transition_locked(target, failure_code=code)
            except Exception:
                effective_code = "worker_supervisor_journal_failed"
                self._state = "fenced"
            self._failure_code = effective_code
            error = self._error(
                "Worker attempt is no longer usable",
                code=effective_code,
            )
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
                    future.exception()
            self._pending.clear()
            self._cancel_ack_pending.clear()
            if self._heartbeat_waiter is not None:
                heartbeat = self._heartbeat_waiter[1]
                if not heartbeat.done():
                    heartbeat.set_exception(error)
                    heartbeat.exception()
                self._heartbeat_waiter = None
            if self._shutdown_waiter is not None and not self._shutdown_waiter.done():
                self._shutdown_waiter.set_exception(error)
                self._shutdown_waiter.exception()
            self._shutdown_waiter = None
            process = self._process
            transport = self._transport
        if transport is not None:
            with suppress(BaseException):
                await transport.close()
        if process is not None:
            try:
                await process.terminate()
            except BaseException:
                with suppress(BaseException):
                    await process.close()

    def _validate_ready(self, message: WorkerProtocolMessage) -> None:
        expected = {
            "attemptId": self._identity.attempt_id,
            "identityFingerprint": self._identity.fingerprint,
            "protocol": self._protocol,
            "protocolVersion": self._protocol_version,
            "sessionNonce": self._identity.session_nonce,
            "supervisorEpoch": self._identity.supervisor_epoch,
        }
        if message.kind != "ready" or dict(message.fields) != expected:
            raise WorkerProtocolError(
                "Worker handshake identity or protocol does not match",
                code="worker_protocol_handshake_mismatch",
            )

    def _transition_locked(
        self,
        state: WorkerSupervisorState,
        *,
        failure_code: str | None = None,
    ) -> None:
        record = self._record
        if record is None:
            raise RuntimeError("Worker journal record is not claimed")
        phase = cast(WorkerAttemptPhase, state)
        self._record = self._journal.transition(
            self._identity.attempt_id,
            expected_phase=record.phase,
            next_phase=phase,
            expected_record_revision=record.record_revision,
            expected_supervisor_epoch=self._identity.supervisor_epoch,
            failure_code=failure_code,
        )
        self._state = state

    def _new_correlation_id(self) -> str:
        value = self._correlation_id_factory()
        if (
            not isinstance(value, str)
            or len(value) != 32
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise self._error(
                "Worker correlation id factory returned an invalid id",
                code="worker_correlation_id_invalid",
            )
        if value in self._pending or value in self._tombstones:
            raise self._error(
                "Worker correlation id was reused",
                code="worker_correlation_id_reused",
            )
        if value in self._issued_ids:
            raise self._error(
                "Worker correlation id was reused",
                code="worker_correlation_id_reused",
            )
        if len(self._issued_ids) >= self._limits.max_messages_per_session:
            raise self._error(
                "Worker session message budget is exhausted",
                code="worker_message_budget_exhausted",
            )
        self._issued_ids.add(value)
        return value

    def _require_healthy_locked(self) -> None:
        if self._state != "healthy":
            raise self._error(
                "Worker supervisor is not healthy",
                code="worker_supervisor_not_healthy",
            )

    def _require_transport_locked(self) -> WorkerFramedTransport:
        if self._transport is None:
            raise RuntimeError("Worker transport is not bound")
        return self._transport

    def _require_process_locked(self) -> ManagedWorkerProcess:
        if self._process is None:
            raise RuntimeError("Worker process is not bound")
        return self._process

    def _error(self, message: str, *, code: str) -> WorkerSupervisorError:
        return WorkerSupervisorError(
            message,
            code=code,
            attempt_id=self._identity.attempt_id,
        )

    async def _cancel_background_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = tuple(
            task
            for task in (self._reader_task, self._exit_task)
            if task is not None and task is not current and not task.done()
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _require_failure_code(code: object) -> str:
    if (
        not isinstance(code, str)
        or not code
        or len(code) > 128
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in code)
        or code[0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
        or code[-1] not in "abcdefghijklmnopqrstuvwxyz0123456789"
    ):
        raise ValueError("Worker failure code must be a bounded identifier")
    return code


def _require_protocol_identifier(value: object, *, name: str) -> str:
    try:
        return _require_failure_code(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a bounded identifier") from exc


__all__ = [
    "WORKER_SUPERVISOR_LIMITS_VERSION",
    "WORKER_SUPERVISOR_MAX_ATTEMPTS",
    "WORKER_SUPERVISOR_MAX_IN_FLIGHT",
    "WORKER_SUPERVISOR_MAX_MESSAGES_PER_SESSION",
    "WORKER_SUPERVISOR_MAX_TIMEOUT_SECONDS",
    "WORKER_SUPERVISOR_MAX_TOMBSTONES",
    "WORKER_SUPERVISOR_STATUS_VERSION",
    "WorkerRemoteFailure",
    "WorkerSupervisor",
    "WorkerSupervisorError",
    "WorkerSupervisorLimitsV1",
    "WorkerSupervisorState",
    "WorkerSupervisorStatusV1",
]
