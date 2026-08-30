from __future__ import annotations

import inspect
import os
import stat
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from shutil import copyfileobj
from typing import Generic, Protocol, TypeVar, Union, cast
from uuid import uuid4

from loushang.harness.runtime.transition import SessionTransitionHost

S = TypeVar("S")
P = TypeVar("P")

LifecycleCallback = Callable[[], Awaitable[None] | None]
FileCopy = Callable[[Path, Path], None]


class VerifiedFileCopy(Protocol):
    """Optional copy capability that binds a discovered source identity."""

    def __call__(
        self,
        source: Path,
        destination: Path,
        *,
        expected_source_fingerprint: str,
    ) -> None: ...


class SessionOperationPhase(str, Enum):
    PREPARE = "prepare"
    REPLACE = "replace"
    AFTER_COMMIT = "after_commit"


@dataclass(frozen=True)
class SessionOperationCandidate(Generic[S, P]):
    session: S
    payload: P
    rollback: LifecycleCallback | None = None


@dataclass(frozen=True)
class CancelledSessionOperation(Generic[P]):
    payload: P
    cleanup: LifecycleCallback | None = None


SessionOperationPreparation = Union[
    SessionOperationCandidate[S, P],
    CancelledSessionOperation[P],
]


@dataclass(frozen=True)
class SessionOperationResult(Generic[S, P]):
    previous: S | None
    current: S | None
    payload: P
    cancelled: bool

    @property
    def changed(self) -> bool:
        return self.previous is not self.current


@dataclass(frozen=True)
class SessionOperationFailure(Generic[S]):
    phase: SessionOperationPhase
    error: Exception
    previous: S | None
    current: S | None


@dataclass(frozen=True)
class StagedFileImport:
    source: Path
    destination: Path
    copied: bool

    def cleanup(self) -> None:
        if not self.copied:
            return
        with suppress(FileNotFoundError):
            self.destination.unlink()


@dataclass(frozen=True)
class ReplacementCallbackFailure:
    name: str
    error: Exception


PrepareOperation = Callable[
    [S | None],
    Awaitable[SessionOperationPreparation[S, P]] | SessionOperationPreparation[S, P],
]
CandidateCallback = Callable[
    [SessionOperationCandidate[S, P], S | None], Awaitable[None] | None
]
ReleaseCallback = Callable[[S, SessionOperationCandidate[S, P]], Awaitable[None] | None]
CommitCallback = Callable[[SessionOperationResult[S, P]], Awaitable[None] | None]
FailureCallback = Callable[[SessionOperationFailure[S]], Awaitable[None] | None]
ReplacementFailureCallback = Callable[
    [ReplacementCallbackFailure], Awaitable[None] | None
]


class SessionOperationCoordinator(Generic[S]):
    """Run a product-owned session operation as one serialized transaction."""

    def __init__(self, host: SessionTransitionHost[S]) -> None:
        self._host = host

    @property
    def current(self) -> S | None:
        return self._host.current

    async def run(
        self,
        prepare: PrepareOperation[S, P],
        *,
        prepare_session: CandidateCallback[S, P] | None = None,
        before_release: ReleaseCallback[S, P] | None = None,
        activate: CandidateCallback[S, P] | None = None,
        after_commit: CommitCallback[S, P] | None = None,
        on_failure: FailureCallback[S] | None = None,
    ) -> SessionOperationResult[S, P]:
        async with self._host.transition():
            previous = self._host.current
            try:
                preparation = await _maybe_await(prepare(previous))
            except Exception as exc:
                await self._report_failure(
                    on_failure,
                    phase=SessionOperationPhase.PREPARE,
                    error=exc,
                    previous=previous,
                )
                raise

            if isinstance(preparation, CancelledSessionOperation):
                if preparation.cleanup is not None:
                    await _maybe_await(preparation.cleanup())
                return SessionOperationResult(
                    previous=previous,
                    current=self._host.current,
                    payload=preparation.payload,
                    cancelled=True,
                )

            candidate = cast(SessionOperationCandidate[S, P], preparation)
            try:
                await self._host.replace(
                    candidate.session,
                    prepare=(
                        None
                        if prepare_session is None
                        else lambda _session: prepare_session(candidate, previous)
                    ),
                    before_release=(
                        None
                        if before_release is None
                        else lambda session: before_release(session, candidate)
                    ),
                    activate=(
                        None
                        if activate is None
                        else lambda _session: activate(candidate, previous)
                    ),
                )
            except BaseException as exc:
                candidate_is_current = self._host.current is candidate.session
                if not candidate_is_current and candidate.rollback is not None:
                    await _maybe_await(candidate.rollback())
                if isinstance(exc, Exception):
                    await self._report_failure(
                        on_failure,
                        phase=(
                            SessionOperationPhase.AFTER_COMMIT
                            if candidate_is_current
                            else SessionOperationPhase.REPLACE
                        ),
                        error=exc,
                        previous=previous,
                    )
                raise

            result = SessionOperationResult(
                previous=previous,
                current=self._host.current,
                payload=candidate.payload,
                cancelled=False,
            )
            if after_commit is None:
                return result
            try:
                await _maybe_await(after_commit(result))
            except BaseException as exc:
                if isinstance(exc, Exception):
                    await self._report_failure(
                        on_failure,
                        phase=SessionOperationPhase.AFTER_COMMIT,
                        error=exc,
                        previous=previous,
                    )
                raise
            return result

    async def _report_failure(
        self,
        callback: FailureCallback[S] | None,
        *,
        phase: SessionOperationPhase,
        error: Exception,
        previous: S | None,
    ) -> None:
        if callback is None:
            return
        await _maybe_await(
            callback(
                SessionOperationFailure(
                    phase=phase,
                    error=error,
                    previous=previous,
                    current=self._host.current,
                )
            )
        )


def copy_file_exclusive(
    source: Path,
    destination: Path,
    *,
    expected_source_fingerprint: str | None = None,
) -> None:
    """Durably publish a complete private copy without replacing a peer."""

    temporary = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    source_descriptor = -1
    parent_descriptor = -1
    published = False
    try:
        source_metadata = source.lstat()
        if not _is_regular_file_no_follow(source_metadata):
            raise OSError("session import source must be a regular file")
        if (
            expected_source_fingerprint is not None
            and file_status_fingerprint(source_metadata)
            != expected_source_fingerprint
        ):
            raise OSError("session import source no longer matches discovery")
        source_descriptor, parent_descriptor = _open_source_no_follow(source)
        opened = os.fstat(source_descriptor)
        if not _same_file_status(source_metadata, opened):
            raise OSError("session import source identity changed")
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output_handle:
            descriptor = -1
            bounded_source = _FixedLengthReader(source_descriptor, opened.st_size)
            copyfileobj(bounded_source, output_handle)
            if bounded_source.remaining:
                raise OSError("session import source was truncated")
            output_handle.flush()
            os.fsync(output_handle.fileno())
        after = os.fstat(source_descriptor)
        current = source.lstat()
        if not _same_file_status(opened, after) or not _same_file_status(
            source_metadata,
            current,
        ):
            raise OSError("session import source changed while copying")
        _publish_file_exclusive(temporary, destination)
        published = True
        _sync_directory(destination.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()
        if published:
            _sync_directory(destination.parent)


def _publish_file_exclusive(temporary: Path, destination: Path) -> None:
    if os.name == "nt":
        # Windows rename does not replace an existing destination.
        temporary.rename(destination)
        return
    # Same-directory hard-link publication is atomic and fails when the final
    # path already exists. Both names briefly reference the complete inode.
    os.link(temporary, destination)


def _sync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        os.close(descriptor)


def stage_file_import(
    source: Path,
    destination_dir: Path,
    *,
    copy_file: FileCopy = copy_file_exclusive,
    verified_copy_file: VerifiedFileCopy | None = None,
    expected_source_fingerprint: str | None = None,
) -> StagedFileImport:
    """Copy a file to an import-safe destination without overwriting a peer."""
    source = _absolute_path_preserving_leaf(source)
    if expected_source_fingerprint is not None:
        current = source.lstat()
        if (
            not _is_regular_file_no_follow(current)
            or file_status_fingerprint(current) != expected_source_fingerprint
        ):
            raise OSError("session import source no longer matches discovery")
    destination_dir = destination_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    for index in range(10_000):
        suffix = "" if index == 0 else f"-import-{index}"
        destination = destination_dir / f"{source.stem}{suffix}{source.suffix}"
        if destination == source:
            return StagedFileImport(source, destination, copied=False)
        if destination.exists():
            continue
        try:
            if copy_file is copy_file_exclusive:
                copy_file_exclusive(
                    source,
                    destination,
                    expected_source_fingerprint=expected_source_fingerprint,
                )
            elif (
                expected_source_fingerprint is not None
                and verified_copy_file is not None
            ):
                verified_copy_file(
                    source,
                    destination,
                    expected_source_fingerprint=expected_source_fingerprint,
                )
            else:
                copy_file(source, destination)
                if expected_source_fingerprint is not None:
                    current = source.lstat()
                    if (
                        not _is_regular_file_no_follow(current)
                        or file_status_fingerprint(current)
                        != expected_source_fingerprint
                    ):
                        raise OSError(
                            "session import source no longer matches discovery"
                        )
        except FileExistsError:
            continue
        except Exception:
            with suppress(FileNotFoundError):
                destination.unlink()
            raise
        return StagedFileImport(source, destination, copied=True)
    raise FileExistsError(f"No available import destination for {source}")


def _absolute_path_preserving_leaf(path: str | Path) -> Path:
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    return absolute.parent.resolve(strict=False) / absolute.name


@dataclass
class _FixedLengthReader:
    descriptor: int
    remaining: int

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        requested = self.remaining if size < 0 else min(size, self.remaining)
        chunk = os.read(self.descriptor, requested)
        self.remaining -= len(chunk)
        return chunk


def _open_source_no_follow(source: Path) -> tuple[int, int]:
    file_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    file_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if os.name != "nt" and directory_flag:
        parent_flags = os.O_RDONLY | directory_flag
        parent_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        parent_descriptor = os.open(source.parent, parent_flags)
        try:
            return os.open(source.name, file_flags, dir_fd=parent_descriptor), (
                parent_descriptor
            )
        except BaseException:
            os.close(parent_descriptor)
            raise
    return os.open(source, file_flags), -1


def _is_regular_file_no_follow(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and not (
        stat.S_ISLNK(metadata.st_mode)
        or bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    )


def file_status_fingerprint(metadata: os.stat_result) -> str:
    """Encode the stable local identity carried by discovery projections."""

    return (
        f"stat-v1:{metadata.st_dev}:{metadata.st_ino}:{metadata.st_size}:"
        f"{metadata.st_mtime_ns}:{metadata.st_ctime_ns}"
    )


def _same_file_status(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


async def run_replacement_callbacks(
    *,
    setup: object | None = None,
    setup_argument: object | None = None,
    after_setup: LifecycleCallback | None = None,
    with_session: object | None = None,
    session_argument: object | None = None,
    on_failure: ReplacementFailureCallback | None = None,
) -> None:
    callbacks = (
        ("setup", setup, setup_argument, after_setup),
        ("withSession", with_session, session_argument, None),
    )
    for name, callback, argument, after_success in callbacks:
        if not callable(callback):
            continue
        try:
            await _invoke_async_callback(callback, argument, name=name)
            if after_success is not None:
                await _maybe_await(after_success())
        except Exception as exc:
            if on_failure is not None:
                await _maybe_await(
                    on_failure(ReplacementCallbackFailure(name=name, error=exc))
                )
            raise


async def _invoke_async_callback(
    callback: object, argument: object, *, name: str
) -> None:
    call = getattr(callback, "__call__", None)
    if not inspect.iscoroutinefunction(callback) and not inspect.iscoroutinefunction(
        call
    ):
        raise TypeError(f"{name} callback must be an async callable.")
    async_callback = cast(Callable[[object], Awaitable[object]], callback)
    await async_callback(argument)


async def _maybe_await(value: Awaitable[P] | P) -> P:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "CancelledSessionOperation",
    "SessionOperationCandidate",
    "SessionOperationCoordinator",
    "SessionOperationFailure",
    "SessionOperationPhase",
    "SessionOperationPreparation",
    "SessionOperationResult",
    "StagedFileImport",
    "ReplacementCallbackFailure",
    "copy_file_exclusive",
    "file_status_fingerprint",
    "run_replacement_callbacks",
    "stage_file_import",
]
