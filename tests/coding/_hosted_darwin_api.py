"""Public Darwin observation APIs; neither kqueue nor waitid grants signal authority.

The owning witness must retain its direct child without Popen.poll/wait until
the observer explicitly allows reaping. Descendant watches are admitted only
while their retained parents are frozen and ancestry has been confirmed.
"""

from __future__ import annotations

import ctypes
import select
import sys

_EV_RECEIPT = 0x0040  # Public Darwin event.h; CPython 3.11 does not export it.


class DarwinWatchEventError(RuntimeError):
    """Fixed native masks for diagnosis; no process names or runtime payloads."""

    def __init__(self, *, registered, flags, notes):
        super().__init__("native process topology became unknown")
        self.registered, self.flags, self.notes = registered, flags, notes


class _SigValue(ctypes.Union):
    _fields_ = [("integer", ctypes.c_int), ("pointer", ctypes.c_void_p)]


class _SigInfo(ctypes.Structure):
    # Public 64-bit Darwin sys/signal.h layout, not a private libproc SPI.
    _fields_ = [
        ("si_signo", ctypes.c_int), ("si_errno", ctypes.c_int),
        ("si_code", ctypes.c_int), ("si_pid", ctypes.c_int),
        ("si_uid", ctypes.c_uint), ("si_status", ctypes.c_int),
        ("si_addr", ctypes.c_void_p), ("si_value", _SigValue),
        ("si_band", ctypes.c_int64), ("padding", ctypes.c_uint64 * 7),
    ]


def _pid(pid):
    if type(pid) is not int or not 1 < pid < 2**31:
        raise ValueError("invalid observed process identity")


class DarwinObservationApi:
    def __init__(self, *, libc=None):
        if (sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8
                or ctypes.sizeof(_SigInfo) != 104):
            raise RuntimeError("native Darwin 64-bit observation required")
        library = ctypes.CDLL(None, use_errno=True) if libc is None else libc
        self._waitid = library.waitid
        self._waitid.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.POINTER(_SigInfo), ctypes.c_int]
        self._waitid.restype = ctypes.c_int

    def exited_unreaped(self, pid):
        """Return the direct child's exit code without releasing its PID."""
        _pid(pid)
        information = _SigInfo()
        if self._waitid(1, pid, ctypes.byref(information), 0x25) != 0:
            raise OSError(ctypes.get_errno(), "native waitid observation failed")
        if information.si_pid == 0:
            if any((information.si_signo, information.si_code, information.si_status)):
                raise RuntimeError("inconsistent native waitid result")
            return None
        if information.si_pid != pid or information.si_signo != 20:
            raise RuntimeError("native waitid identity changed")
        if information.si_code == 1 and 0 <= information.si_status <= 255:
            return information.si_status
        if information.si_code in {2, 3} and 0 < information.si_status < 32:
            return -information.si_status
        # XNU's kernel WSTOPPED mask also overlaps WEXITED/WNOWAIT. A valid
        # CLD_STOPPED result is still non-terminal; never authorize its reap.
        if information.si_code == 5 and information.si_status in {17, 18, 21, 22}:
            return None
        raise RuntimeError(
            f"unexpected native waitid state: code={information.si_code}, status={information.si_status}"
        )


class DarwinExitWatch:
    """Bounded registered exits; an unexpected topology change stays unknown."""

    def __init__(self, pids, *, native=None, group_members=()):
        if not 1 <= len(pids) <= 8 or len(set(pids)) != len(pids):
            raise ValueError("ambiguous native observation process set")
        for pid in pids:
            _pid(pid)
        if (len(set(group_members)) != len(group_members)
                or not set(group_members).issubset(pids)):
            raise ValueError("owned-group members must be registered identities")
        if native is None and sys.platform != "darwin":
            raise RuntimeError("native Darwin kqueue required")
        self._native = select if native is None else native
        self._pids, self._ended = set(pids), set()
        self._group_members, self._forked = set(group_members), set()
        self._unknown, self._closed = False, False
        self._queue = self._native.kqueue()
        try:
            for pid in pids:
                event = self._native.kevent(
                    pid, filter=self._native.KQ_FILTER_PROC,
                    flags=self._native.KQ_EV_ADD | self._native.KQ_EV_CLEAR | _EV_RECEIPT,
                    fflags=self._native.KQ_NOTE_EXIT | self._native.KQ_NOTE_FORK | self._native.KQ_NOTE_EXEC,
                )
                receipts = self._queue.control([event], 1, 0)
                if (len(receipts) != 1 or receipts[0].ident != pid
                        or not receipts[0].flags & self._native.KQ_EV_ERROR):
                    raise RuntimeError("native watch registration unconfirmed")
                if receipts[0].data:
                    raise OSError(receipts[0].data, "native watch registration failed")
        except BaseException:
            self._unknown = True
            self.close()
            raise

    def exited(self):
        if self._unknown or self._closed:
            raise RuntimeError("native process observation unavailable")
        try:
            for event in self._queue.control([], 8, 0):
                allowed = self._native.KQ_NOTE_EXIT
                if event.ident in self._group_members:
                    allowed |= self._native.KQ_NOTE_FORK
                if (event.ident not in self._pids
                        or event.flags & self._native.KQ_EV_ERROR
                        or not event.fflags or event.fflags & ~allowed):
                    raise DarwinWatchEventError(
                        registered=event.ident in self._pids, flags=event.flags, notes=event.fflags,
                    )
                if event.fflags & self._native.KQ_NOTE_FORK:
                    self._forked.add(event.ident)
                if event.fflags & self._native.KQ_NOTE_EXIT:
                    self._ended.add(event.ident)
        except BaseException:
            self._unknown = True
            raise
        return set(self._ended)

    @property
    def forked(self):
        """Observed group activity, not an exact fork count or child inventory."""
        return set(self._forked)

    def close(self):
        if not self._closed:
            self._queue.close()
            self._closed = True
