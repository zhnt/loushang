"""Retain Resume cleanup responsibility in the original Coding owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session.agent_session import AgentSession
    from .session_manager import SessionManager


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
        from .session.agent_session import AgentSession

        if isinstance(self.original_owner, AgentSession):
            await self.original_owner.dispose()
        else:
            await self.original_owner.dispose_runtime_profile()


def retain_resume_cleanup_failure(
    *, original_owner: AgentSession | SessionManager,
    original_error: BaseException, cleanup_error: BaseException,
) -> CodingResumeContinuationCleanupFailure:
    """Fence the admitting factory and retain that same owner for retry."""

    from .session.agent_session import AgentSession

    manager = original_owner._coding_session_manager if isinstance(original_owner, AgentSession) else original_owner
    try:
        type(manager)._factory_for_persistence(True).fence()
    except BaseException as fence_error:
        original_error.add_note(f"Original Coding Resume factory fencing also failed: {fence_error!r}")
    return CodingResumeContinuationCleanupFailure(
        original_owner=original_owner, original_error=original_error,
        cleanup_error=cleanup_error,
    )
