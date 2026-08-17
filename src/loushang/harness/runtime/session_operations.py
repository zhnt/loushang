from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from shutil import copyfileobj
from typing import Generic, TypeVar, Union, cast

from loushang.harness.runtime.transition import SessionTransitionHost

S = TypeVar("S")
P = TypeVar("P")

LifecycleCallback = Callable[[], Awaitable[None] | None]


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


def copy_file_exclusive(source: Path, destination: Path) -> None:
    created = False
    try:
        with source.open("rb") as input_handle:
            with destination.open("xb") as output_handle:
                created = True
                copyfileobj(input_handle, output_handle)
    except Exception:
        if created:
            with suppress(FileNotFoundError):
                destination.unlink()
        raise


def stage_file_import(
    source: Path,
    destination_dir: Path,
    *,
    copy_file: Callable[[Path, Path], None] = copy_file_exclusive,
) -> StagedFileImport:
    """Copy a file to an import-safe destination without overwriting a peer."""
    source = source.resolve()
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
            copy_file(source, destination)
        except FileExistsError:
            continue
        except Exception:
            with suppress(FileNotFoundError):
                destination.unlink()
            raise
        return StagedFileImport(source, destination, copied=True)
    raise FileExistsError(f"No available import destination for {source}")


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
    "run_replacement_callbacks",
    "stage_file_import",
]
