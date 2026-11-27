"""Read-only native identity and exit observation for a detached Darwin service."""

from __future__ import annotations

import ctypes
import os
import select
import subprocess
import sys
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from .errors import HostingError, HostingFailureCategory

_PROC_PIDTBSDINFO = 3
_PROC_FLAG_SLEADER = 0x20


@dataclass(frozen=True, slots=True)
class DarwinServiceIdentityV1:
    pid: int = field(repr=False)
    start_microseconds: int
    boot_id: str
    user_id: int

    def __post_init__(self) -> None:
        if (
            type(self.pid) is not int
            or not 1 < self.pid < 2**31
            or type(self.start_microseconds) is not int
            or not 0 < self.start_microseconds < 2**64
            or type(self.user_id) is not int
            or not 0 <= self.user_id < 2**32
            or not _canonical_uuid(self.boot_id)
        ):
            raise _error(HostingFailureCategory.INVALID_REQUEST)


class _BSDInfo(ctypes.Structure):
    # XNU's public proc_bsdinfo layout. Counters and unused fields occupy
    # the documented fixed-width slots before pbi_start_tvsec.
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("exit_status", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("parent_pid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("unused_ids", ctypes.c_uint32 * 6),
        ("names", ctypes.c_char * 48),
        ("file_count", ctypes.c_uint32),
        ("group", ctypes.c_uint32),
        ("unused_counters", ctypes.c_uint32 * 4),
        ("start_seconds", ctypes.c_uint64),
        ("start_microseconds", ctypes.c_uint64),
    ]


def _require_darwin() -> None:
    if sys.platform != "darwin" or not all(
        callable(getattr(os, name, None)) for name in ("geteuid", "killpg")
    ):
        raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str or len(value) != 36:
        return False
    try:
        identity = UUID(value)
    except ValueError:
        return False
    return identity.int != 0 and str(identity) == value


@cache
def _boot_id() -> str:
    try:
        value = subprocess.check_output(
            ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
            stderr=subprocess.DEVNULL, text=True, encoding="ascii", timeout=2,
        ).strip().lower()
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
    if not _canonical_uuid(value):
        raise _error(HostingFailureCategory.PREPARATION_REJECTED)
    return value


@cache
def _libproc() -> ctypes.CDLL:
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pidinfo.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
    ]
    library.proc_pidinfo.restype = ctypes.c_int
    return library


def _identity(pid: int) -> DarwinServiceIdentityV1:
    _require_darwin()
    if type(pid) is not int or not 1 < pid < 2**31:
        raise _error(HostingFailureCategory.INVALID_REQUEST)
    info = _BSDInfo()
    try:
        size = _libproc().proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    except (AttributeError, OSError):
        raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
    if (size != ctypes.sizeof(info) or info.pid != pid or info.group != pid
            or not info.flags & _PROC_FLAG_SLEADER or info.uid != getattr(os, "geteuid")()
            or info.start_microseconds >= 1_000_000):
        raise _error(HostingFailureCategory.PREPARATION_STALE)
    return DarwinServiceIdentityV1(
        pid, info.start_seconds * 1_000_000 + info.start_microseconds, _boot_id(), info.uid,
    )


def darwin_service_group_absent(identity: DarwinServiceIdentityV1) -> bool:
    """Use only the original UID/boot/group, and never signal the group."""
    _require_darwin()
    if type(identity) is not DarwinServiceIdentityV1 or identity.user_id != getattr(os, "geteuid")():
        raise _error(HostingFailureCategory.PREPARATION_STALE)
    if identity.boot_id != _boot_id():
        return True
    try:
        getattr(os, "killpg")(identity.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
    return False


if TYPE_CHECKING and sys.platform == "darwin":
    _ExitQueue = select.kqueue
else:
    class _ExitQueue(Protocol):
        def close(self) -> None: ...


class DarwinServiceObserverV1:
    """An exit watch admitted between two observations of the same process."""

    _identity: DarwinServiceIdentityV1
    _queue: _ExitQueue
    _exited: bool
    _closed: bool

    def __init__(self, identity: DarwinServiceIdentityV1) -> None:
        if sys.platform != "darwin":
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        _require_darwin()
        if not callable(getattr(select, "kqueue", None)) or not callable(getattr(select, "kevent", None)):
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        self._identity = identity
        try:
            self._queue = select.kqueue()
        except OSError:
            raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
        self._exited = self._closed = False
        try:
            event = select.kevent(
                identity.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT,
            )
            self._queue.control([event], 0, 0)
            if _identity(identity.pid) != identity:
                raise _error(HostingFailureCategory.PREPARATION_STALE)
        except BaseException as error:
            try:
                self.close()
            except OSError:
                failure = _error(HostingFailureCategory.CLEANUP_FAILED)
                failure.cleanup_incomplete = True
                raise failure from error
            if isinstance(error, OSError):
                raise _error(HostingFailureCategory.PREPARATION_FAILED) from error
            raise

    @classmethod
    def capture(cls, pid: int) -> DarwinServiceObserverV1:
        return cls(_identity(pid))

    @classmethod
    def reopen(cls, identity: DarwinServiceIdentityV1) -> DarwinServiceObserverV1:
        if type(identity) is not DarwinServiceIdentityV1 or _identity(identity.pid) != identity:
            raise _error(HostingFailureCategory.PREPARATION_STALE)
        return cls(identity)

    @property
    def identity(self) -> DarwinServiceIdentityV1:
        return self._identity

    def exited(self, *, timeout: float = 0.0) -> bool:
        if sys.platform != "darwin":
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        if self._closed:
            raise _error(HostingFailureCategory.HOST_CLOSED)
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        if not self._exited:
            try:
                events = self._queue.control(None, 1, timeout)
            except OSError:
                raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
            if events:
                event = events[0]
                if (event.ident != self.identity.pid or event.flags & select.KQ_EV_ERROR
                        or not event.fflags & select.KQ_NOTE_EXIT):
                    raise _error(HostingFailureCategory.PREPARATION_FAILED)
                self._exited = True
        return self._exited

    def scope_exited(self) -> bool:
        return self.exited() and darwin_service_group_absent(self.identity)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.close()


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "darwin_service_" + category.value)
