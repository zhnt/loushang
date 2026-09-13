"""Optional Linux service identity and retained process-exit observations.

No root-facade activation. These observations are not process-tree ownership,
application settlement, or permission to terminate a process. In particular,
closing an observer never signals the observed service.

Kernel contracts: https://man7.org/linux/man-pages/man2/pidfd_open.2.html and
https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html .
"""

from __future__ import annotations

import math
import os
import re
import select
import sys
from dataclasses import dataclass, field
from threading import Event, RLock
from time import monotonic

from .errors import HostingError, HostingFailureCategory

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_PROC_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class LinuxServiceIdentityV1:
    """Native lookup facts; values alone do not establish current liveness."""

    pid: int = field(repr=False)
    start_ticks: int
    boot_id: str
    user_id: int
    pid_namespace_device: int
    pid_namespace_inode: int

    def __post_init__(self) -> None:
        if (
            type(self.pid) is not int or not 1 <= self.pid < 2**31
            or type(self.boot_id) is not str or _UUID.fullmatch(self.boot_id) is None
            or any(type(value) is not int or not 0 <= value < 2**64 for value in (
                self.start_ticks, self.user_id, self.pid_namespace_device, self.pid_namespace_inode,
            ))
            or self.pid_namespace_inode == 0
        ):
            raise _error(HostingFailureCategory.INVALID_REQUEST)


class LinuxServiceObserverV1:
    """One private pidfd. Cross-thread wait/close is bounded and serialized."""

    _fd: int | None
    _identity: LinuxServiceIdentityV1
    _mutex: RLock
    _closing: Event

    def __init__(self) -> None:
        raise TypeError("use capture or reopen")

    @classmethod
    def capture(cls, pid: int) -> LinuxServiceObserverV1:
        """Capture an explicitly supplied PID; no process enumeration or spawn."""
        return cls._open(pid, None)

    @classmethod
    def reopen(cls, expected: LinuxServiceIdentityV1) -> LinuxServiceObserverV1:
        """Re-admit a stored identity; missing/mismatched facts remain unknown."""
        if type(expected) is not LinuxServiceIdentityV1:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        return cls._open(expected.pid, expected)

    @classmethod
    def _open(cls, pid: int, expected: LinuxServiceIdentityV1 | None) -> LinuxServiceObserverV1:
        if sys.platform != "linux":
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        if type(pid) is not int or not 1 <= pid < 2**31:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        descriptor = None
        try:
            before = _observe(pid)
            if expected is not None and before != expected:
                raise _error(HostingFailureCategory.PREPARATION_STALE)
            descriptor = _open_pidfd(pid)
            os.set_inheritable(descriptor, False)
            after = _observe(pid)
            if after != before or _pidfd_pid(descriptor) != pid:
                raise _error(HostingFailureCategory.PREPARATION_STALE)
            owner = object.__new__(cls)
            owner._fd = descriptor
            owner._identity = after
            owner._mutex = RLock()
            owner._closing = Event()
            descriptor = None
            return owner
        except (OSError, UnicodeError):
            raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
        finally:
            if descriptor is not None:
                _close_fd(descriptor)

    @property
    def identity(self) -> LinuxServiceIdentityV1:
        return self._identity

    def exited(self, *, timeout: float = 0.0) -> bool:
        """Wait at most 30 seconds for leader/thread-group exit, not scope exit.

        False means only no exit event was observed during this call. Missing
        proc files, timeout, and socket loss are never converted into True.
        """
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        deadline = monotonic() + timeout
        if self._closing.is_set():
            raise _error(HostingFailureCategory.HOST_CLOSED)
        if not self._mutex.acquire(timeout=timeout):
            raise _error(HostingFailureCategory.CAPACITY_EXHAUSTED)
        try:
            if self._closing.is_set() or self._fd is None:
                raise _error(HostingFailureCategory.HOST_CLOSED)
            try:
                poller = select.poll()
                poller.register(self._fd, select.POLLIN)
                events = poller.poll(math.floor(max(0.0, deadline - monotonic()) * 1000))
            except OSError:
                raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
            for _, event in events:
                if event & (select.POLLERR | select.POLLNVAL):
                    raise _error(HostingFailureCategory.PREPARATION_FAILED)
                if event & (select.POLLIN | select.POLLHUP):
                    return True
            return False
        finally:
            self._mutex.release()

    def close(self) -> None:
        self._closing.set()
        if not self._mutex.acquire(timeout=30):
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        try:
            descriptor, self._fd = self._fd, None
            if descriptor is not None:
                _close_fd(descriptor)
        finally:
            self._mutex.release()


def _observe(pid: int) -> LinuxServiceIdentityV1:
    # Detect a procfs mounted from a different PID namespace before using its
    # numeric process directories with pidfd_open in the caller's namespace.
    self_stat = _read_file("/proc/self/stat")
    _parse_start_ticks(self_stat, os.getpid())
    boot = _read_file("/proc/sys/kernel/random/boot_id", limit=64).strip().decode("ascii")
    namespace = os.stat("/proc/self/ns/pid")
    directory = os.open(f"/proc/{pid}", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(directory).st_uid != os.geteuid():
            raise _error(HostingFailureCategory.PREPARATION_REJECTED)
        uid = _parse_uid(_read_file("status", parent=directory, limit=16 * 1024))
        if uid != os.geteuid():
            raise _error(HostingFailureCategory.PREPARATION_REJECTED)
        ticks = _parse_start_ticks(_read_file("stat", parent=directory), pid)
        return LinuxServiceIdentityV1(pid, ticks, boot, uid, namespace.st_dev, namespace.st_ino)
    finally:
        _close_fd(directory)


def _parse_start_ticks(content: bytes, expected_pid: int) -> int:
    # comm (field 2) can contain spaces and right parentheses. The final ')'
    # ends comm; starttime (field 22) is offset 19 in the remaining fields.
    try:
        prefix, fields = content.rsplit(b")", 1)
        pid, _comm = prefix.split(b" (", 1)
        tokens = fields.split()
        if int(pid) != expected_pid or len(tokens) < 20 or len(tokens[0]) != 1:
            raise ValueError
        ticks = int(tokens[19])
        if not 0 <= ticks < 2**64:
            raise ValueError
        return ticks
    except (ValueError, IndexError):
        raise _error(HostingFailureCategory.PREPARATION_REJECTED) from None


def _parse_uid(content: bytes) -> int:
    # Non-dumpable proc directories may be root-owned. Use the actual four
    # credentials, and reject set-ID/FSUID transitions for this same-user profile.
    # https://man7.org/linux/man-pages/man5/proc_pid.5.html
    try:
        entries = [line.split(b":", 1)[1].split() for line in content.splitlines()
                   if line.startswith(b"Uid:")]
        if len(entries) != 1 or len(entries[0]) != 4:
            raise ValueError
        values = [int(value) for value in entries[0]]
        if len(set(values)) != 1 or not 0 <= values[0] < 2**32:
            raise ValueError
        return values[1]
    except ValueError:
        raise _error(HostingFailureCategory.PREPARATION_REJECTED) from None


def _pidfd_pid(descriptor: int) -> int:
    try:
        lines = _read_file(f"/proc/self/fdinfo/{descriptor}").splitlines()
        values = [line.split(b":", 1)[1].strip() for line in lines if line.startswith(b"Pid:")]
        if len(values) != 1:
            raise ValueError
        return int(values[0])
    except ValueError:
        raise _error(HostingFailureCategory.PREPARATION_REJECTED) from None


def _open_pidfd(pid: int) -> int:
    native = getattr(os, "pidfd_open", None)
    if callable(native):
        return native(pid, 0)
    # Some standalone CPython builds omit the wrapper even on a capable
    # kernel/libc. Use that exact native API, never guessed syscall numbers or
    # weaker /proc polling. All symbol admission remains Linux-only and lazy.
    from ctypes import CDLL, c_int, c_uint, get_errno

    library = CDLL(None, use_errno=True)
    function = getattr(library, "pidfd_open", None)
    if function is None:
        raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
    function.argtypes = [c_int, c_uint]
    function.restype = c_int
    descriptor = function(pid, 0)
    if descriptor < 0:
        raise OSError(get_errno(), "pidfd_open_failed")
    return descriptor


def _read_file(path: str, *, parent: int | None = None, limit: int = _PROC_LIMIT) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        content = bytearray()
        while len(content) <= limit:
            chunk = os.read(descriptor, limit + 1 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > limit:
            raise _error(HostingFailureCategory.READ_BOUND_EXCEEDED)
        return bytes(content)
    finally:
        _close_fd(descriptor)


def _close_fd(descriptor: int) -> None:
    primary = sys.exception()
    try:
        os.close(descriptor)
    except OSError:
        if primary is not None:
            primary.add_note("service_observer_cleanup_incomplete")
        else:
            raise _error(HostingFailureCategory.CLEANUP_FAILED) from None


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "linux_service_" + category.value)
