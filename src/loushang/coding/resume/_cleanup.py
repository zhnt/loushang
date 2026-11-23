"""Retain Resume cleanup responsibility in the original Coding owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loushang.coding.session.agent_session import AgentSession
    from loushang.coding.session.manager import SessionManager

_FENCE_FAILURE_NOTE = "Original Coding Resume factory fencing also failed: "


class CodingResumeContinuationCleanupFailure(RuntimeError):
    """Retain the original undelivered owner until its cleanup can be retried.

    The original Transcript factory is fenced; successful cleanup does not
    reopen it. The Product root must retain this debt and close/restart its
    affected owner before accepting another activation.
    """

    def __init__(
        self, *, original_owner: AgentSession | SessionManager,
        original_error: BaseException, cleanup_error: BaseException,
    ) -> None:
        super().__init__("Coding Resume continuation cleanup remains pending")
        self.original_owner = original_owner
        self.original_error = original_error
        self.cleanup_error = cleanup_error

    async def retry_cleanup(self) -> None:
        await _retry_owner(self.original_owner)


def retain_resume_cleanup_failure(
    *, original_owner: AgentSession | SessionManager,
    original_error: BaseException, cleanup_error: BaseException,
) -> CodingResumeContinuationCleanupFailure:
    """Fence the admitting factory and retain that same owner for retry."""

    _fence_owner(original_owner, original_error)
    return CodingResumeContinuationCleanupFailure(
        original_owner=original_owner, original_error=original_error,
        cleanup_error=cleanup_error,
    )


async def _release_candidate(
    session: AgentSession | None, manager: SessionManager | None
) -> None:
    if session is not None:
        await session.dispose()
    elif manager is not None:
        await manager.dispose_runtime_profile()


async def discard_candidate(
    session: AgentSession | None,
    original_error: BaseException,
    *,
    manager: SessionManager | None = None,
    cleanup_note: str | None = None,
) -> None:
    """Dispose the original candidate and retain it when cleanup fails."""
    try:
        await _release_candidate(session, manager)
    except BaseException as cleanup_error:
        if cleanup_note is not None:
            original_error.add_note(f"{cleanup_note}{cleanup_error!r}")
        owner = session if session is not None else manager
        assert owner is not None
        raise retain_resume_cleanup_failure(
            original_owner=owner,
            original_error=original_error,
            cleanup_error=cleanup_error,
        ) from original_error


def _fence_owner(
    owner: AgentSession | SessionManager, original_error: BaseException
) -> None:
    """Fence the admitting native Transcript factory before retaining its owner."""
    from loushang.coding.session.agent_session import AgentSession

    manager = (
        owner._coding_session_manager if isinstance(owner, AgentSession) else owner
    )
    try:
        type(manager)._factory_for_persistence(True).fence()
    except BaseException as fence_error:
        original_error.add_note(f"{_FENCE_FAILURE_NOTE}{fence_error!r}")


async def _retry_owner(owner: AgentSession | SessionManager) -> None:
    """Retry the original disposal route under the existing lifecycle owner."""
    from loushang.coding.session.agent_session import AgentSession

    if isinstance(owner, AgentSession):
        await _release_candidate(owner, None)
    else:
        await _release_candidate(None, owner)
