"""Read-only original Linux service-group observations, never signal authority.

The borrowed pidfd must be retained through every call. Escaped processes are
excluded: the application must settle its separately owned child resources.
Kernel semantics: https://man7.org/linux/man-pages/man2/kill.2.html and
https://man7.org/linux/man-pages/man2/setsid.2.html .
"""

from __future__ import annotations

import os
import re
import sys
from typing import Literal

from .errors import HostingError, HostingFailureCategory
from .service import (
    LinuxServiceIdentityV1,
    LinuxServiceObserverV1,
    _parse_start_ticks,
    _read_file,
)

_BOOT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
LinuxServiceGroupRecoveryStatus = Literal[
    "absent", "present", "prior_boot_absent", "context_stale"
]


def linux_current_boot_id() -> str:
    """Read the verified current Linux boot for pre-launch Worker custody."""

    if sys.platform != "linux":
        raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
    try:
        _parse_start_ticks(_read_file("/proc/self/stat"), os.getpid())
        boot_id = _read_file("/proc/sys/kernel/random/boot_id", limit=64).strip().decode(
            "ascii"
        )
        if _BOOT_ID.fullmatch(boot_id) is None:
            raise _error(HostingFailureCategory.PREPARATION_FAILED)
        return boot_id
    except (OSError, UnicodeError):
        raise _error(HostingFailureCategory.PREPARATION_FAILED) from None


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
        if getattr(os, "geteuid")() != identity.user_id or (
            namespace.st_dev,
            namespace.st_ino,
        ) != (identity.pid_namespace_device, identity.pid_namespace_inode):
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


def linux_service_group_absent_after_restart(identity: LinuxServiceIdentityV1) -> bool:
    """Observe absence of a trusted original group in the same Linux context.

    This does not authenticate the stored identity or prove that children were
    contained in the group. The Product must bind both facts separately before
    using this observation as cleanup evidence.
    """

    if type(identity) is not LinuxServiceIdentityV1:
        raise _error(HostingFailureCategory.INVALID_REQUEST)
    if sys.platform != "linux" or not callable(getattr(os, "killpg", None)):
        raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
    try:
        boot_id = _read_file("/proc/sys/kernel/random/boot_id", limit=64)
        namespace = os.stat("/proc/self/ns/pid")
        if (
            boot_id.strip().decode("ascii") != identity.boot_id
            or getattr(os, "geteuid")() != identity.user_id
            or (namespace.st_dev, namespace.st_ino)
            != (identity.pid_namespace_device, identity.pid_namespace_inode)
        ):
            raise _error(HostingFailureCategory.PREPARATION_STALE)
        try:
            getattr(os, "killpg")(identity.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False
    except (OSError, UnicodeError):
        raise _error(HostingFailureCategory.PREPARATION_FAILED) from None


def linux_service_group_recovery_status(
    identity: LinuxServiceIdentityV1,
) -> LinuxServiceGroupRecoveryStatus:
    """Classify a trusted original group, including a changed Linux boot.

    A prior-boot identity cannot have a live local process after a kernel
    restart. Product must separately authenticate this identity and its
    containment before using the result to settle an attempt.
    """

    if type(identity) is not LinuxServiceIdentityV1:
        raise _error(HostingFailureCategory.INVALID_REQUEST)
    if sys.platform != "linux" or not callable(getattr(os, "killpg", None)):
        raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
    try:
        boot_id = linux_current_boot_id()
        if boot_id != identity.boot_id:
            return "prior_boot_absent"
        namespace = os.stat("/proc/self/ns/pid")
        if getattr(os, "geteuid")() != identity.user_id or (
            namespace.st_dev,
            namespace.st_ino,
        ) != (identity.pid_namespace_device, identity.pid_namespace_inode):
            return "context_stale"
        try:
            getattr(os, "killpg")(identity.pid, 0)
        except ProcessLookupError:
            return "absent"
        except PermissionError:
            return "present"
        return "present"
    except (OSError, UnicodeError):
        raise _error(HostingFailureCategory.PREPARATION_FAILED) from None


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "service_group_" + category.value)


__all__ = [
    "LinuxServiceGroupObservationV1",
    "LinuxServiceGroupRecoveryStatus",
    "linux_current_boot_id",
    "linux_service_group_absent_after_restart",
    "linux_service_group_recovery_status",
]
