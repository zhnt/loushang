"""Read-only original Linux service-group observations, never signal authority.

The borrowed pidfd must be retained through every call. Escaped processes are
excluded: the application must settle its separately owned child resources.
Kernel semantics: https://man7.org/linux/man-pages/man2/kill.2.html and
https://man7.org/linux/man-pages/man2/setsid.2.html .
"""

from __future__ import annotations

import os

from .errors import HostingError, HostingFailureCategory
from .service import LinuxServiceObserverV1


class LinuxServiceGroupObservationV1:
    """Borrow one observer and its mutex; allocate no descriptor or close duty."""

    def __init__(self, observer: LinuxServiceObserverV1) -> None:
        if type(observer) is not LinuxServiceObserverV1 or observer.identity.pid <= 1:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        self._observer = observer
        self._admitted = False

    def _context(self) -> None:
        identity = self._observer.identity
        namespace = os.stat("/proc/self/ns/pid")
        if (getattr(os, "geteuid")() != identity.user_id
                or (namespace.st_dev, namespace.st_ino) != (
                    identity.pid_namespace_device, identity.pid_namespace_inode)):
            raise _error(HostingFailureCategory.PREPARATION_STALE)

    def admit(self) -> None:
        observer = self._observer
        if not observer._mutex.acquire(blocking=False):
            raise _error(HostingFailureCategory.CAPACITY_EXHAUSTED)
        try:
            if self._admitted:
                raise _error(HostingFailureCategory.INVALID_REQUEST)
            self._context()
            pid = observer.identity.pid
            if (
                observer.exited()
                or getattr(os, "getpgid")(pid) != pid
                or getattr(os, "getsid")(pid) != pid
                or observer.exited()
            ):
                raise _error(HostingFailureCategory.PREPARATION_STALE)
            self._admitted = True
        except OSError:
            raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
        finally:
            observer._mutex.release()

    def exited(self) -> bool:
        observer = self._observer
        if not observer._mutex.acquire(blocking=False):
            raise _error(HostingFailureCategory.CAPACITY_EXHAUSTED)
        try:
            if not self._admitted:
                raise _error(HostingFailureCategory.INVALID_REQUEST)
            self._context()
            if not observer.exited():
                return False
            try:
                getattr(os, "killpg")(observer.identity.pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            return False
        except OSError:
            raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
        finally:
            observer._mutex.release()


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "service_group_" + category.value)


__all__ = ["LinuxServiceGroupObservationV1"]
