"""Session construction helpers for failure-preserving cleanup chains."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from contextlib import suppress
from typing import Protocol

from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic

CleanupStep = tuple[str, Callable[[], None]]


def run_cleanup_steps(
    primary_error: BaseException | None,
    steps: Iterable[CleanupStep],
) -> BaseException | None:
    """Attempt every cleanup step without replacing an earlier failure."""

    settled_error = primary_error
    for label, cleanup in steps:
        try:
            cleanup()
        except BaseException as cleanup_error:
            if settled_error is None:
                settled_error = cleanup_error
            else:
                settled_error.add_note(f"{label} also failed: {cleanup_error}")
    return settled_error


class _ConstructedSession(Protocol):
    async def dispose(self) -> None: ...


class SessionConstructionCleanup:
    """Retain exact completed Sessions until their failed handoff is settled.

    One retained task joins the original owners with the existing cancellation
    primitive. This adds no registry or second resource-retirement authority.
    """

    def __init__(self, session: _ConstructedSession) -> None:
        self._session: _ConstructedSession | None = session
        self._task: asyncio.Task[None] | None = None

    def owns_session(self, session: object) -> bool:
        """Match this pending custody to an exact completed construction."""
        return self._session is not None and self._session is session

    async def retry_cleanup(self) -> None:
        if self._session is None:
            return
        task = self._task
        if task is None or task.done():
            operation = self._drain()
            try:
                task = asyncio.create_task(operation)
            except BaseException:
                operation.close()
                raise
            self._task = task
        try:
            await _await_cancellation_atomic(task)
        finally:
            if (
                task.done()
                and not task.cancelled()
                and task.exception() is None
                and self._task is task
            ):
                self._task = None

    async def _drain(self) -> None:
        from loushang.harness.session.multiagent import SessionMultiAgentRuntime

        session = self._session
        if session is None:
            return
        runtime = getattr(session, "multiagent_runtime", None)
        if isinstance(runtime, SessionMultiAgentRuntime):
            await runtime.dispose()
        await session.dispose()
        self._session = None


class SessionConstructionCleanupAttachmentError(RuntimeError):
    """An occupied error retains its old owner and this exact failed candidate."""

    def __init__(
        self, original_error: BaseException, cleanup: SessionConstructionCleanup
    ) -> None:
        super().__init__("Session construction cleanup attachment is occupied")
        self.original_error = original_error
        self.cleanup = cleanup


_CONSTRUCTION_CLEANUP_SLOT = "_loushang_session_construction_cleanup"
_EXCEPTION_DICT = BaseException.__dict__["__dict__"]


def get_session_construction_cleanup(
    error: BaseException,
) -> SessionConstructionCleanup | None:
    """Return only the actual Core custody; do not invoke exception attributes."""
    attributes = _EXCEPTION_DICT.__get__(error)
    value = (
        attributes.get("cleanup")
        if type(error) is SessionConstructionCleanupAttachmentError
        else attributes.get(_CONSTRUCTION_CLEANUP_SLOT)
    )
    return value if type(value) is SessionConstructionCleanup else None


def retain_session_construction_failure(
    error: BaseException, session: _ConstructedSession
) -> BaseException:
    """Keep the original error identity unless its reserved slot is occupied.

    Synchronous callers obtain this custody with get_session_construction_cleanup
    and await its retry_cleanup(). Existing asynchronous owners settle it before
    discarding their dependent Transcript. Nothing is scheduled here.
    """
    attributes = _EXCEPTION_DICT.__get__(error)
    existing = get_session_construction_cleanup(error)
    if existing is not None and existing._session is session:
        return error
    cleanup = SessionConstructionCleanup(session)
    if (
        type(error) is SessionConstructionCleanupAttachmentError
        or _CONSTRUCTION_CLEANUP_SLOT in attributes
    ):
        return SessionConstructionCleanupAttachmentError(error, cleanup)
    attributes[_CONSTRUCTION_CLEANUP_SLOT] = cleanup
    # A malformed/overridden note surface cannot discard cleanup custody.
    with suppress(BaseException):
        BaseException.add_note(
            error,
            "Session construction cleanup is pending; await "
            "get_session_construction_cleanup(error).retry_cleanup()",
        )
    return error


__all__ = [
    "CleanupStep",
    "SessionConstructionCleanup",
    "SessionConstructionCleanupAttachmentError",
    "get_session_construction_cleanup",
    "retain_session_construction_failure",
    "run_cleanup_steps",
]
