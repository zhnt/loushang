"""Optional Linux background launch owner, without implicit termination.

The consumer adopts this owner before spawn and fences its durable attempt
before crossing the native effect. This local managed profile accepts complete
pathname launch material, not sealed plugin preparation; it is not a fallback
for H6 containment. No async transport destructor can terminate this service.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from threading import Event, RLock
from time import monotonic

from ._posix_process import _PosixProcess
from .contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory
from .service import LinuxServiceIdentityV1, LinuxServiceObserverV1


class _ServiceChild:
    """Popen reaps only our direct child; no pidfd-to-returncode substitution."""

    stdin = stdout = stderr = None

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.poll()


class LinuxServiceProcessV1:
    """Adopt the child endpoint at construction, then allow exactly one spawn.

    The caller owns the parent endpoint and durable handoff. close() releases
    only parent-local descriptors and fences spawn; it never signals or waits
    for the service. scope_exited() is separate from local handles_closed and
    from application cleanup. Live committed services are expected after close.

    The child must adopt its control FD before preparing Product resources.
    Synchronous native creation/IO cannot be preempted by a Python timeout; the
    consumer retains this owner and the durable fence across uncertain returns.
    """

    def __init__(self, request: ProcessLaunchRequest, child_endpoint: socket.socket) -> None:
        if sys.platform != "linux":
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        if (type(request) is not ProcessLaunchRequest or not os.path.isabs(request.argv[0])
                or request.streams.stdin is not ProcessStdinMode.CLOSED
                or request.streams.stdout is not ProcessStdoutMode.DISCARD
                or request.streams.stderr is not ProcessStderrMode.DISCARD
                or type(child_endpoint) is not socket.socket):
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        try:
            if (child_endpoint.family != socket.AF_UNIX or child_endpoint.fileno() < 3
                    or child_endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
                raise _error(HostingFailureCategory.INVALID_REQUEST)
            child_endpoint.getpeername()
            child_endpoint.set_inheritable(False)
        except OSError:
            # Admission failure leaves ownership with the caller.
            raise _error(HostingFailureCategory.INVALID_REQUEST) from None
        self._request: ProcessLaunchRequest | None = request
        self._endpoint = child_endpoint
        self._process: subprocess.Popen[bytes] | None = None
        self._scope: _PosixProcess | None = None
        self._observer: LinuxServiceObserverV1 | None = None
        self._identity: LinuxServiceIdentityV1 | None = None
        self._attempted = False
        self._handles_closed = False
        self._observer_close_unknown = False
        self._observer_adoption_unknown = False
        self._endpoint_close_unknown = False
        self._endpoint_closed = False
        self._closing = Event()
        self._mutex = RLock()

    @property
    def identity(self) -> LinuxServiceIdentityV1 | None:
        """Captured lookup facts, never readiness or signal authority."""
        return self._identity

    @property
    def handles_closed(self) -> bool:
        return self._handles_closed

    @property
    def creation_uncertain(self) -> bool:
        """An attempted spawn without attached process must remain fenced."""
        return self._attempted and self._process is None

    def _enter(self, *, timeout: float = 0.0, allow_closed: bool = False) -> float:
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        deadline = monotonic() + timeout
        if self._closing.is_set() and not allow_closed:
            raise _error(HostingFailureCategory.HOST_CLOSED)
        if not self._mutex.acquire(timeout=timeout):
            raise _error(HostingFailureCategory.CAPACITY_EXHAUSTED)
        if self._closing.is_set() and not allow_closed:
            self._mutex.release()
            raise _error(HostingFailureCategory.HOST_CLOSED)
        return deadline

    def spawn(self) -> LinuxServiceIdentityV1:
        """One effect, no retry and no settled-without-process error receipt."""
        self._enter()
        try:
            if self._attempted or self._request is None:
                raise _error(HostingFailureCategory.SPAWN_FAILED)
            request = self._request
            self._request = None
            self._attempted = True
            try:
                self._process = subprocess.Popen(
                    request.argv, executable=request.argv[0], cwd=request.cwd,
                    env=dict(request.effective_environment), shell=False,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                    pass_fds=(self._endpoint.fileno(),),
                )
                self._scope = _PosixProcess(_ServiceChild(self._process))
                self._observer_adoption_unknown = True
                self._observer = LinuxServiceObserverV1.capture(self._process.pid)
                self._observer_adoption_unknown = False
                self._identity = self._observer.identity
                self._close_endpoint()  # No parent copy of the child's socket.
                return self._identity
            except (OSError, subprocess.SubprocessError):
                raise _error(HostingFailureCategory.SPAWN_FAILED) from None
            # Other exceptions also retain this attempted owner. In particular,
            # observer failure does not discard the attached Popen/scope.
        finally:
            self._mutex.release()

    def leader_exited(self) -> bool:
        """Direct-child reaping fact, not scope/application settlement."""
        self._enter(allow_closed=True)
        try:
            return self._process is not None and self._process.poll() is not None
        finally:
            self._mutex.release()

    def scope_exited(self) -> bool:
        """Original process group and leader are gone; escaped resources excluded.

        The admitted profile must keep descendants within owned groups or under
        separate child-resource owners. This query does not scan the machine or
        claim settlement of descendants that escaped that ownership model.
        """
        self._enter(allow_closed=True)
        try:
            if not self._attempted:
                return self._closing.is_set()
            if self._process is None or self._process.poll() is None:
                return False
            # Retain attachment even if failure happened before scope creation.
            if self._scope is None:
                self._scope = _PosixProcess(_ServiceChild(self._process))
            try:
                return not self._scope.group_exists()
            except OSError:
                raise _error(HostingFailureCategory.CLEANUP_FAILED) from None
        finally:
            self._mutex.release()

    def wait_scope(self, *, timeout: float) -> bool:
        """Cooperatively wait on owned facts; no timeout triggers a signal."""
        deadline = self._enter(timeout=timeout, allow_closed=True)
        try:
            while True:
                if self.scope_exited():
                    return True
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                # A local wait primitive, not a service control channel.
                Event().wait(min(0.01, remaining))
        finally:
            self._mutex.release()

    def close(self) -> None:
        """Fence new creation and release only local handles, never terminate."""
        self._closing.set()
        self._enter(timeout=30, allow_closed=True)
        try:
            self._request = None
            if self._handles_closed:
                return
            primary: BaseException | None = None
            if self._observer_close_unknown or self._observer_adoption_unknown:
                primary = _error(HostingFailureCategory.CLEANUP_FAILED)
            elif self._observer is not None:
                self._observer_close_unknown = True
                try:
                    self._observer.close()
                except BaseException as error:
                    primary = error
                else:
                    self._observer = None
                    self._observer_close_unknown = False
            try:
                self._close_endpoint()
            except BaseException as error:
                if primary is None:
                    primary = error
            if primary is not None:
                if isinstance(primary, Exception):
                    raise _error(HostingFailureCategory.CLEANUP_FAILED) from None
                primary.add_note("service_process_cleanup_incomplete")
                raise primary
            self._handles_closed = True
        finally:
            self._mutex.release()

    def _close_endpoint(self) -> None:
        if self._endpoint_close_unknown:
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        if not self._endpoint_closed:
            self._endpoint_close_unknown = True
            self._endpoint.close()
            self._endpoint_closed = True
            self._endpoint_close_unknown = False


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "service_process_" + category.value)
