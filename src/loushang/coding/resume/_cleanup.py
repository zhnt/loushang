"""Retain Resume cleanup responsibility in the original Coding owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loushang.coding.harness.session import resume_cleanup

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
        await resume_cleanup.retry_owner(self.original_owner)


def retain_resume_cleanup_failure(
    *, original_owner: AgentSession | SessionManager,
    original_error: BaseException, cleanup_error: BaseException,
) -> CodingResumeContinuationCleanupFailure:
    """Fence the admitting factory and retain that same owner for retry."""

    resume_cleanup.fence_owner(original_owner, original_error)
    return CodingResumeContinuationCleanupFailure(
        original_owner=original_owner, original_error=original_error,
        cleanup_error=cleanup_error,
    )
