"""Process-local runtime scopes with crash-safe ownership leases.

Path resolution stays pure in :mod:`loushang.foundation.platform_paths`.
This module is the effectful boundary that creates one private run directory,
keeps its lease live, and reclaims inactive residue without following links.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .platform_paths import PlatformPaths, resolve_platform_paths

_LEASE_NAME = ".lease"
_GC_PREFIX = ".gc-"
# Keep the Windows byte-range lock well outside the bounded lease record.  A
# lock at byte zero makes the otherwise-readable record inaccessible through
# every second handle, including one opened by the owning process.
_WINDOWS_LEASE_LOCK_OFFSET = 1 << 30


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    """Immutable, injectable paths for one application run."""

    paths: PlatformPaths
    run_id: str

    def __post_init__(self) -> None:
        if not _is_runtime_run_id(self.run_id):
            raise ValueError(
                "runtime run id must be 32 lowercase hexadecimal characters"
            )

    @property
    def runs_root(self) -> Path:
        return self.paths.runtime / "runs"

    @property
    def run_dir(self) -> Path:
        return self.runs_root / self.run_id

    @property
    def drafts(self) -> Path:
        return self.run_dir / "drafts"

    @property
    def artifacts(self) -> Path:
        return self.run_dir / "artifacts"


def resolve_runtime_scope(
    *,
    paths: PlatformPaths | None = None,
    run_id: str | None = None,
) -> RuntimeScope:
    """Resolve one scope without touching the filesystem."""

    normalized_run_id = (run_id or uuid4().hex).lower()
    return RuntimeScope(
        paths=paths or resolve_platform_paths(),
        run_id=normalized_run_id,
    )


@dataclass(frozen=True, slots=True)
class RuntimeSweepPolicy:
    """Bounds for reclaiming inactive run directories."""

    stale_after_seconds: float = 24 * 60 * 60
    max_inactive_runs: int = 32
    max_inactive_bytes: int = 512 * 1024 * 1024
    max_scan_entries: int = 10_000

    def __post_init__(self) -> None:
        if self.stale_after_seconds < 0:
            raise ValueError("stale_after_seconds must not be negative")
        if self.max_inactive_runs < 0:
            raise ValueError("max_inactive_runs must not be negative")
        if self.max_inactive_bytes < 0:
            raise ValueError("max_inactive_bytes must not be negative")
        if self.max_scan_entries < 1:
            raise ValueError("max_scan_entries must be positive")


DEFAULT_RUNTIME_SWEEP_POLICY = RuntimeSweepPolicy()


@dataclass(frozen=True, slots=True)
class RuntimeSweepReport:
    """Observable result of one best-effort startup sweep."""

    inspected: int = 0
    active: int = 0
    removed: int = 0
    removed_bytes: int = 0
    skipped: int = 0
    failed: int = 0
    truncated: bool = False


@dataclass(slots=True)
class _InactiveRun:
    path: Path
    expected_run_id: str
    quarantined: bool
    size: int
    modified_at: float
    descriptor: int | None
    lease_identity: tuple[int, int] | None


class RunLease:
    """Exclusive live ownership of a private ``runtime/runs/<run_id>`` tree."""

    __slots__ = ("scope", "sweep_report", "_descriptor", "_lease_identity")

    def __init__(
        self,
        *,
        scope: RuntimeScope,
        descriptor: int,
        lease_identity: tuple[int, int],
        sweep_report: RuntimeSweepReport,
    ) -> None:
        self.scope = scope
        self.sweep_report = sweep_report
        self._descriptor: int | None = descriptor
        self._lease_identity = lease_identity

    @property
    def active(self) -> bool:
        return self._descriptor is not None

    @classmethod
    def acquire(
        cls,
        scope: RuntimeScope,
        *,
        sweep_policy: RuntimeSweepPolicy = DEFAULT_RUNTIME_SWEEP_POLICY,
        now: Callable[[], float] = time.time,
    ) -> RunLease:
        """Create the run tree, sweep inactive residue, and hold its lock."""

        _prepare_private_directory(scope.runs_root)
        report = sweep_runtime_runs(scope, policy=sweep_policy, now=now)
        scope.run_dir.mkdir(mode=0o700, exist_ok=False)
        _validate_owned_directory(scope.run_dir)
        lease_path = scope.run_dir / _LEASE_NAME
        descriptor = -1
        try:
            descriptor = _open_new_private_file(lease_path)
            _lock_descriptor(descriptor, blocking=True)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            payload = json.dumps(
                {
                    "schema_version": 1,
                    "run_id": scope.run_id,
                    "pid": os.getpid(),
                    "created_at": now(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            return cls(
                scope=scope,
                descriptor=descriptor,
                lease_identity=(metadata.st_dev, metadata.st_ino),
                sweep_report=report,
            )
        except BaseException:
            if descriptor >= 0:
                _unlock_and_close(descriptor)
            with suppress(OSError, RecursionError, ValueError):
                _remove_owned_run_tree(
                    scope.run_dir,
                    expected_run_id=scope.run_id,
                    lease_identity=None,
                )
            raise

    def close(self) -> None:
        """Release the lease and best-effort remove this run's private tree."""

        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        quarantined: Path | None = None
        try:
            quarantined = _quarantine_run_tree(
                self.scope.run_dir,
                runs_root=self.scope.runs_root,
                expected_run_id=self.scope.run_id,
                lease_identity=self._lease_identity,
            )
        except (OSError, ValueError):
            pass
        finally:
            _unlock_and_close(descriptor)
        if quarantined is not None:
            # Normal shutdown must not be replaced by best-effort cleanup. A
            # quarantined residue remains eligible for the next sweep.
            with suppress(OSError, RecursionError, ValueError):
                _remove_owned_run_tree(
                    quarantined,
                    expected_run_id=self.scope.run_id,
                    lease_identity=self._lease_identity,
                )

    def __enter__(self) -> RunLease:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(BaseException):
            self.close()


def sweep_runtime_runs(
    scope: RuntimeScope,
    *,
    policy: RuntimeSweepPolicy = DEFAULT_RUNTIME_SWEEP_POLICY,
    now: Callable[[], float] = time.time,
) -> RuntimeSweepReport:
    """Remove expired or over-budget inactive runs, never following symlinks.

    A valid lease that cannot be locked is live and is always preserved.
    Lease-less or invalid directories are preserved because their inactive
    state cannot be proven safely.
    """

    try:
        _validate_owned_directory(scope.runs_root)
    except FileNotFoundError:
        return RuntimeSweepReport()
    inspected = active = skipped = failed = 0
    inactive: list[_InactiveRun] = []
    current_time = now()
    try:
        try:
            with os.scandir(scope.runs_root) as entries:
                for index, entry in enumerate(entries):
                    if index >= policy.max_scan_entries:
                        return RuntimeSweepReport(
                            inspected=inspected,
                            active=active,
                            skipped=skipped,
                            failed=failed + 1,
                            truncated=True,
                        )
                    entry_identity = _runtime_entry_identity(entry.name)
                    if entry_identity is None:
                        skipped += 1
                        continue
                    expected_run_id, quarantined = entry_identity
                    if not quarantined and expected_run_id == scope.run_id:
                        continue
                    inspected += 1
                    try:
                        candidate = _inspect_inactive_run(
                            Path(entry.path),
                            expected_run_id=expected_run_id,
                            quarantined=quarantined,
                        )
                    except (OSError, RecursionError):
                        failed += 1
                        continue
                    if candidate is None:
                        active += 1
                        continue
                    # Register ownership immediately so BaseException cannot strand
                    # its raw descriptor between inspection and classification.
                    inactive.append(candidate)
                    if candidate.size < 0:
                        skipped += 1
                        _release_candidate(candidate)
        except OSError:
            return RuntimeSweepReport(failed=failed + 1)

        selected: set[Path] = {
            candidate.path
            for candidate in inactive
            if candidate.size >= 0
            and (
                candidate.quarantined
                or current_time - candidate.modified_at >= policy.stale_after_seconds
            )
        }
        quota_candidates = sorted(
            (
                candidate
                for candidate in inactive
                if candidate.size >= 0 and candidate.path not in selected
            ),
            key=lambda candidate: (candidate.modified_at, candidate.path.name),
        )
        retained_count = len(quota_candidates)
        retained_bytes = sum(candidate.size for candidate in quota_candidates)
        for candidate in quota_candidates:
            if (
                retained_count <= policy.max_inactive_runs
                and retained_bytes <= policy.max_inactive_bytes
            ):
                break
            selected.add(candidate.path)
            retained_count -= 1
            retained_bytes -= candidate.size

        removed = removed_bytes = 0
        for candidate in inactive:
            if candidate.size < 0 or candidate.path not in selected:
                continue
            try:
                if not candidate.quarantined:
                    candidate.path = _quarantine_run_tree(
                        candidate.path,
                        runs_root=scope.runs_root,
                        expected_run_id=candidate.expected_run_id,
                        lease_identity=candidate.lease_identity,
                    )
                    candidate.quarantined = True
                _release_candidate(candidate)
                _remove_owned_run_tree(
                    candidate.path,
                    expected_run_id=candidate.expected_run_id,
                    lease_identity=candidate.lease_identity,
                )
            except (OSError, RecursionError):
                failed += 1
            else:
                removed += 1
                removed_bytes += candidate.size
        return RuntimeSweepReport(
            inspected=inspected,
            active=active,
            removed=removed,
            removed_bytes=removed_bytes,
            skipped=skipped,
            failed=failed,
        )
    finally:
        for candidate in inactive:
            _release_candidate(candidate)


def _inspect_inactive_run(
    path: Path,
    *,
    expected_run_id: str,
    quarantined: bool,
) -> _InactiveRun | None:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not _owned_by_current_user(metadata)
    ):
        return _InactiveRun(
            path,
            expected_run_id,
            quarantined,
            -1,
            metadata.st_mtime,
            None,
            None,
        )
    lease_path = path / _LEASE_NAME
    try:
        descriptor = _open_existing_private_file(lease_path)
    except FileNotFoundError:
        return _InactiveRun(
            path,
            expected_run_id,
            quarantined,
            -1,
            metadata.st_mtime,
            None,
            None,
        )
    try:
        lease_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(lease_metadata.st_mode) or not _owned_by_current_user(
            lease_metadata
        ):
            return _InactiveRun(
                path,
                expected_run_id,
                quarantined,
                -1,
                metadata.st_mtime,
                None,
                None,
            )
        locked = _lock_descriptor(descriptor, blocking=False)
        if not locked:
            return None
        lease_identity = (lease_metadata.st_dev, lease_metadata.st_ino)
        if not _valid_lease_record(descriptor, expected_run_id=expected_run_id):
            candidate = _InactiveRun(
                path=path,
                expected_run_id=expected_run_id,
                quarantined=quarantined,
                size=-1,
                modified_at=max(metadata.st_mtime, lease_metadata.st_mtime),
                descriptor=descriptor,
                lease_identity=None,
            )
            descriptor = -1
            return candidate
        size, modified_at = _tree_usage(path)
        candidate = _InactiveRun(
            path=path,
            expected_run_id=expected_run_id,
            quarantined=quarantined,
            size=size,
            modified_at=max(modified_at, lease_metadata.st_mtime),
            descriptor=descriptor,
            lease_identity=lease_identity,
        )
        descriptor = -1
        return candidate
    finally:
        if descriptor >= 0:
            _unlock_and_close(descriptor)


def _valid_lease_record(descriptor: int, *, expected_run_id: str) -> bool:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, 4097)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if len(raw) > 4096:
            return False
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and value.get("run_id") == expected_run_id
        and isinstance(value.get("pid"), int)
        and isinstance(value.get("created_at"), int | float)
    )


def _tree_usage(path: Path) -> tuple[int, float]:
    if os.name == "posix" and hasattr(os, "O_DIRECTORY"):
        flags = os.O_RDONLY | os.O_DIRECTORY
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        try:
            path_metadata = path.lstat()
            descriptor_metadata = os.fstat(descriptor)
            if not os.path.samestat(path_metadata, descriptor_metadata):
                raise OSError(errno.EAGAIN, "runtime directory identity changed")
            return _tree_usage_descriptor(descriptor)
        finally:
            os.close(descriptor)
    return _tree_usage_path(path)


def _tree_usage_descriptor(descriptor: int) -> tuple[int, float]:
    metadata = os.fstat(descriptor)
    total = metadata.st_size
    modified_at = metadata.st_mtime
    flags = os.O_RDONLY | os.O_DIRECTORY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    with os.scandir(descriptor) as entries:
        for entry in entries:
            entry_metadata = entry.stat(follow_symlinks=False)
            modified_at = max(modified_at, entry_metadata.st_mtime)
            if stat.S_ISDIR(entry_metadata.st_mode):
                child_descriptor = os.open(
                    entry.name,
                    flags,
                    dir_fd=descriptor,
                )
                try:
                    child_metadata = os.fstat(child_descriptor)
                    if not os.path.samestat(entry_metadata, child_metadata):
                        raise OSError(
                            errno.EAGAIN,
                            "runtime child directory identity changed",
                        )
                    child_size, child_modified_at = _tree_usage_descriptor(
                        child_descriptor
                    )
                finally:
                    os.close(child_descriptor)
                total += child_size
                modified_at = max(modified_at, child_modified_at)
            else:
                total += entry_metadata.st_size
    return total, modified_at


def _tree_usage_path(path: Path) -> tuple[int, float]:
    metadata = path.lstat()
    total = metadata.st_size
    modified_at = metadata.st_mtime
    with os.scandir(path) as entries:
        for entry in entries:
            entry_path = Path(entry.path)
            entry_metadata = entry.stat(follow_symlinks=False)
            modified_at = max(modified_at, entry_metadata.st_mtime)
            if stat.S_ISDIR(entry_metadata.st_mode) and not _is_reparse_point(
                entry_metadata
            ):
                child_path_metadata = entry_path.lstat()
                if not os.path.samestat(entry_metadata, child_path_metadata):
                    raise OSError(
                        errno.EAGAIN,
                        "runtime child directory identity changed",
                    )
                child_size, child_modified_at = _tree_usage_path(entry_path)
                total += child_size
                modified_at = max(modified_at, child_modified_at)
            else:
                total += entry_metadata.st_size
    return total, modified_at


def _quarantine_run_tree(
    path: Path,
    *,
    runs_root: Path,
    expected_run_id: str,
    lease_identity: tuple[int, int] | None,
) -> Path:
    if path.parent != runs_root:
        raise ValueError(f"runtime run is outside its runs root: {path}")
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not _owned_by_current_user(metadata)
    ):
        raise PermissionError(f"runtime run directory is not safely owned: {path}")
    if lease_identity is not None:
        _validate_lease_identity(path / _LEASE_NAME, lease_identity)
    target = runs_root / f"{_GC_PREFIX}{expected_run_id}-{uuid4().hex}"
    path.rename(target)
    target_metadata = target.lstat()
    if (
        not stat.S_ISDIR(target_metadata.st_mode)
        or _is_reparse_point(target_metadata)
        or (target_metadata.st_dev, target_metadata.st_ino)
        != (metadata.st_dev, metadata.st_ino)
    ):
        raise PermissionError(f"runtime quarantine identity changed: {target}")
    if lease_identity is not None:
        _validate_lease_identity(target / _LEASE_NAME, lease_identity)
    return target


def _remove_owned_run_tree(
    path: Path,
    *,
    expected_run_id: str,
    lease_identity: tuple[int, int] | None,
) -> None:
    entry_identity = _runtime_entry_identity(path.name)
    if entry_identity is None or entry_identity[0] != expected_run_id:
        raise ValueError(f"refusing to remove non-run directory: {path}")
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not _owned_by_current_user(metadata)
    ):
        raise PermissionError(f"runtime run directory is not safely owned: {path}")
    if lease_identity is not None:
        _validate_lease_identity(path / _LEASE_NAME, lease_identity)
    if os.name == "posix" and not shutil.rmtree.avoids_symlink_attacks:
        raise OSError(
            errno.ENOTSUP,
            "safe runtime tree removal is unavailable on this platform",
        )
    shutil.rmtree(path)


def _validate_lease_identity(
    lease_path: Path,
    expected: tuple[int, int],
) -> None:
    path_metadata = lease_path.lstat()
    if not stat.S_ISREG(path_metadata.st_mode) or _is_reparse_point(path_metadata):
        raise PermissionError(f"runtime lease identity changed: {lease_path}")
    if os.name == "nt":
        descriptor = _open_existing_private_file(lease_path)
        try:
            metadata = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    else:
        metadata = path_metadata
    if (metadata.st_dev, metadata.st_ino) != expected:
        raise PermissionError(f"runtime lease identity changed: {lease_path}")


def _prepare_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_owned_directory(path)
    if os.name == "posix":
        path.chmod(0o700)


def _validate_owned_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_point(metadata):
        raise NotADirectoryError(str(path))
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"runtime directory is not owned by this user: {path}")


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return os.name != "posix" or not callable(getuid) or metadata.st_uid == getuid()


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_reparse_tag", 0))


def _open_new_private_file(path: Path) -> int:
    if os.name == "nt":
        return _open_windows_shared_delete_file(path, create_new=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, 0o600)


def _open_existing_private_file(path: Path) -> int:
    if os.name == "nt":
        return _open_windows_shared_delete_file(path, create_new=False)
    flags = os.O_RDWR
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags)


def _open_windows_shared_delete_file(path: Path, *, create_new: bool) -> int:
    """Open a lock file that does not block atomic parent-directory rename."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    generic_read_write = 0x80000000 | 0x40000000
    share_read_write_delete = 0x00000001 | 0x00000002 | 0x00000004
    create_new_disposition = 1
    open_existing_disposition = 3
    file_attribute_normal = 0x00000080
    handle = create_file(
        str(path),
        generic_read_write,
        share_read_write_delete,
        None,
        create_new_disposition if create_new else open_existing_disposition,
        file_attribute_normal,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        get_last_error = getattr(ctypes, "get_last_error")
        win_error = getattr(ctypes, "WinError")
        raise win_error(get_last_error())
    try:
        open_osfhandle = getattr(msvcrt, "open_osfhandle")
        return open_osfhandle(
            handle,
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
    except BaseException:
        close_handle(handle)
        raise


def _write_all(descriptor: int, content: bytes) -> None:
    """Write a complete lease record even when the OS reports short writes."""

    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError(errno.EIO, "runtime lease write made no progress")
        offset += written


def _lock_descriptor(descriptor: int, *, blocking: bool) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, _WINDOWS_LEASE_LOCK_OFFSET, os.SEEK_SET)
        mode = (
            getattr(msvcrt, "LK_LOCK")
            if blocking
            else getattr(
                msvcrt,
                "LK_NBLCK",
            )
        )
        locking = getattr(msvcrt, "locking")
        try:
            locking(descriptor, mode, 1)
        except OSError as error:
            if not blocking and error.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise
        return True
    import fcntl

    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    try:
        fcntl.flock(descriptor, flags)
    except BlockingIOError:
        return False
    return True


def _unlock_and_close(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, _WINDOWS_LEASE_LOCK_OFFSET, os.SEEK_SET)
            locking = getattr(msvcrt, "locking")
            locking(descriptor, getattr(msvcrt, "LK_UNLCK"), 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _release_candidate(candidate: _InactiveRun) -> None:
    descriptor = candidate.descriptor
    if descriptor is not None:
        candidate.descriptor = None
        _unlock_and_close(descriptor)


def _is_runtime_run_id(value: str) -> bool:
    return len(value) == 32 and all(
        character in "0123456789abcdef" for character in value
    )


def _runtime_entry_identity(value: str) -> tuple[str, bool] | None:
    if _is_runtime_run_id(value):
        return value, False
    if not value.startswith(_GC_PREFIX):
        return None
    payload = value.removeprefix(_GC_PREFIX)
    run_id, separator, token = payload.partition("-")
    if separator and _is_runtime_run_id(run_id) and _is_runtime_run_id(token):
        return run_id, True
    return None


__all__ = [
    "DEFAULT_RUNTIME_SWEEP_POLICY",
    "RunLease",
    "RuntimeScope",
    "RuntimeSweepPolicy",
    "RuntimeSweepReport",
    "resolve_runtime_scope",
    "sweep_runtime_runs",
]
