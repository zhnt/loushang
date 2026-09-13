"""Inherited-channel handoff coordination, independent of application semantics.

The injected consumer port binds one exact attempt/instance and performs durable
CAS. Wire bytes are hints only. This module neither spawns nor signals processes;
the child application owner performs cleanup only after an ABORTING decision.
"""

from __future__ import annotations

import select
import socket
import sys
from collections.abc import Callable
from contextlib import suppress
from enum import Enum
from threading import Event, RLock
from time import monotonic
from typing import Protocol

from .errors import HostingError, HostingFailureCategory


class ServiceHandoffPhaseV1(str, Enum):
    PROVISIONAL = "provisional"
    COMMITTED = "committed"
    ABORTING = "aborting"
    UNKNOWN = "unknown"


class ServiceHandoffPortV1(Protocol):
    """Trusted, bounded synchronous CAS operations for one exact generation.

    observe never infers phase from process/socket absence. commit is proposed
    only by the child after application readiness; abort cannot cross a durable
    commit. Errors or inability to durably determine the outcome mean UNKNOWN.
    The port consumes the supplied absolute monotonic deadline, including locks,
    SQL and re-observation. It is borrowed and not closed by the channel owner.
    This is a cooperative IO budget, not preemption of an in-flight OS fsync;
    owners retain completion/cleanup responsibility even if native IO overruns.
    """

    def observe(self, deadline: float, /) -> ServiceHandoffPhaseV1: ...

    def commit(self, deadline: float, /) -> ServiceHandoffPhaseV1: ...

    def abort(self, deadline: float, /) -> ServiceHandoffPhaseV1: ...


class _HandoffChannel:
    """Own a supplied stream socket; no timeout can erase a durable decision."""

    def __init__(self, endpoint: socket.socket, port: ServiceHandoffPortV1) -> None:
        if sys.platform != "linux":
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        if not isinstance(endpoint, socket.socket) or any(
            not callable(getattr(port, name, None)) for name in ("observe", "commit", "abort")
        ):
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        # Admission precedes ownership transfer: failed construction leaves the
        # supplied socket with its caller, which must close it in a finally.
        if endpoint.family != socket.AF_UNIX or endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        endpoint.setblocking(False)
        endpoint.set_inheritable(False)
        self._endpoint, self._port = endpoint, port
        self._closing = Event()
        self._mutex = RLock()
        self._closed = False

    def _enter(self, timeout: float = 2.0, deadline: float | None = None) -> float:
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        if deadline is not None and (type(deadline) not in (int, float) or not 0 < deadline <= 1e12):
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        now = monotonic()
        deadline = min(now + timeout, deadline) if deadline is not None else now + timeout
        if self._closing.is_set():
            raise _error(HostingFailureCategory.HOST_CLOSED)
        if not self._mutex.acquire(timeout=max(0.0, deadline - now)):
            raise _error(HostingFailureCategory.CAPACITY_EXHAUSTED)
        if self._closing.is_set():
            self._mutex.release()
            raise _error(HostingFailureCategory.HOST_CLOSED)
        return deadline

    def close(self) -> None:
        self._closing.set()
        if not self._mutex.acquire(timeout=30):
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        try:
            if not self._closed:
                try:
                    self._endpoint.close()
                except OSError:
                    raise _error(HostingFailureCategory.CLEANUP_FAILED) from None
                self._closed = True
        finally:
            self._mutex.release()

    @staticmethod
    def _call(operation: Callable[[float], ServiceHandoffPhaseV1], deadline: float) -> ServiceHandoffPhaseV1:
        if monotonic() >= deadline:
            return ServiceHandoffPhaseV1.UNKNOWN
        try:
            phase = operation(deadline)
        except Exception:
            return ServiceHandoffPhaseV1.UNKNOWN
        return phase if type(phase) is ServiceHandoffPhaseV1 else ServiceHandoffPhaseV1.UNKNOWN


class ServiceChildHandoffV1(_HandoffChannel):
    """A child checks parent loss while preparing, then proposes durable commit."""

    def __init__(self, endpoint: socket.socket, port: ServiceHandoffPortV1) -> None:
        super().__init__(endpoint, port)
        self._ack_attempted = False

    def _parent_lost(self) -> bool:
        try:
            self._endpoint.recv(1, socket.MSG_PEEK)
        except BlockingIOError:
            return False
        except OSError:
            return True
        # The parent never sends data. Unexpected input is not a commit or stop
        # command; treat a broken startup channel like parent loss, then use CAS.
        return True

    def poll_parent(self, *, timeout: float = 2.0, deadline: float | None = None) -> ServiceHandoffPhaseV1:
        """Only ABORTING authorizes caller cleanup; UNKNOWN remains owned debt."""
        deadline = self._enter(timeout, deadline)
        try:
            phase = self._call(self._port.observe, deadline)
            if phase is ServiceHandoffPhaseV1.PROVISIONAL and self._parent_lost():
                return self._call(self._port.abort, deadline)
            return phase
        finally:
            self._mutex.release()

    def commit(self, *, timeout: float = 2.0, deadline: float | None = None) -> ServiceHandoffPhaseV1:
        """After readiness, durable CAS wins even if EOF races the liveness peek.

        Parent death is not an instantaneous durable abort. Either CAS may win;
        a later EOF/notification loss never undoes the committed decision.
        """
        deadline = self._enter(timeout, deadline)
        try:
            phase = self._call(self._port.observe, deadline)
            if phase is ServiceHandoffPhaseV1.PROVISIONAL:
                phase = self._call(self._port.abort if self._parent_lost() else self._port.commit, deadline)
            if phase is ServiceHandoffPhaseV1.COMMITTED and not self._ack_attempted:
                self._ack_attempted = True
                # Notification loss is not a lifecycle transition.
                with suppress(OSError):
                    self._endpoint.send(b"C")
            return phase
        finally:
            self._mutex.release()


class ServiceParentHandoffV1(_HandoffChannel):
    """Starter-side bounded observation; notifications alone grant no authority."""

    def wait(self, *, timeout: float) -> ServiceHandoffPhaseV1:
        deadline = self._enter(timeout)
        try:
            phase = self._call(self._port.observe, deadline)
            if phase in (ServiceHandoffPhaseV1.COMMITTED, ServiceHandoffPhaseV1.ABORTING):
                return phase
            try:
                poller = select.poll()
                poller.register(self._endpoint, select.POLLIN)
                events = poller.poll(int(max(0, deadline - monotonic()) * 1000))
                if events:
                    self._endpoint.recv(1)  # Consume a hint, never trust its value.
            except OSError:
                pass
            phase = self._call(self._port.observe, deadline)
            return phase if phase in (ServiceHandoffPhaseV1.COMMITTED, ServiceHandoffPhaseV1.ABORTING) else ServiceHandoffPhaseV1.UNKNOWN
        finally:
            self._mutex.release()

    def abort(self) -> ServiceHandoffPhaseV1:
        """Request durable abort; a committed/unknown result forbids rollback."""
        deadline = self._enter()
        try:
            return self._call(self._port.abort, deadline)
        finally:
            self._mutex.release()


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "service_handoff_" + category.value)
