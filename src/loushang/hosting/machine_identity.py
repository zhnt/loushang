"""Read an application-scoped Linux machine lookup key, never process authority.

The raw machine ID is confidential: do not return, log or persist it. Read only
the OS-provisioned identity; no hostname, boot-ID, random or DBus-path fallback.
The system administrator remains responsible for unique IDs on cloned hosts.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from hashlib import blake2b, sha256

from .errors import HostingError, HostingFailureCategory

_ETC = "/etc"
_ROOT_UID = 0
_ID = re.compile(rb"[0-9a-f]{32}\n?\Z")
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9./_-]{0,127}\Z")


def linux_machine_key(*, domain: str) -> str:
    """Return a stable 128-bit domain-separated key without creating files."""
    if type(domain) is not str or _DOMAIN.fullmatch(domain) is None:
        raise _error(HostingFailureCategory.INVALID_REQUEST)
    if sys.platform != "linux":
        raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    parent = descriptor = None
    primary: BaseException | None = None
    try:
        parent = os.open(_ETC, flags | os.O_DIRECTORY)
        _trusted(os.fstat(parent), directory=True)
        descriptor = os.open("machine-id", flags, dir_fd=parent)
        before = os.fstat(descriptor)
        _trusted(before, directory=False)
        content = bytearray()
        while len(content) < 34:
            chunk = os.read(descriptor, 34 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        ):
            raise _error(HostingFailureCategory.PREPARATION_STALE)
        raw = bytes(content)
        if _ID.fullmatch(raw) is None or raw.rstrip(b"\n") == b"0" * 32:
            raise _error(HostingFailureCategory.PREPARATION_REJECTED)
        # Fixed domain-derived key, raw 128-bit machine identity input.
        return blake2b(bytes.fromhex(raw.decode("ascii")),
                       key=sha256(domain.encode("ascii")).digest(), digest_size=16).hexdigest()
    except OSError:
        primary = _error(HostingFailureCategory.PREPARATION_FAILED)
        raise primary from None
    except BaseException as error:
        primary = error
        raise
    finally:
        _close_owned((descriptor, parent), primary=primary)


def _trusted(value: os.stat_result, *, directory: bool) -> None:
    if (value.st_uid != _ROOT_UID or value.st_mode & 0o022
            or not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))):
        raise _error(HostingFailureCategory.PREPARATION_REJECTED)


def _close_owned(descriptors: tuple[int | None, ...], *, primary: BaseException | None) -> None:
    cleanup: BaseException | None = None
    for descriptor in descriptors:
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except BaseException as error:
            # Attempt each owned fd once even after a lost close receipt. Never
            # infer this call's primary exception from the caller's except block.
            if primary is not None:
                primary.add_note("machine_identity_cleanup_failed")
            elif cleanup is None:
                cleanup = _error(HostingFailureCategory.CLEANUP_FAILED) if isinstance(error, OSError) else error
    if cleanup is not None:
        raise cleanup from None


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "machine_identity_" + category.value)


__all__ = ["linux_machine_key"]
