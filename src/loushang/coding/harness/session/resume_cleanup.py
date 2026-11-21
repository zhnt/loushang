"""Release a failed continuation through its original Session owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loushang.coding.resume import _cleanup as _binding

if TYPE_CHECKING:
    from loushang.coding.session.agent_session import AgentSession
    from loushang.coding.session.manager import SessionManager


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
        raise _binding.retain_resume_cleanup_failure(
            original_owner=owner,
            original_error=original_error,
            cleanup_error=cleanup_error,
        ) from original_error


def fence_owner(
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
        original_error.add_note(f"{_binding._FENCE_FAILURE_NOTE}{fence_error!r}")


async def retry_owner(owner: AgentSession | SessionManager) -> None:
    """Retry the original disposal route under the existing lifecycle owner."""
    from loushang.coding.session.agent_session import AgentSession

    if isinstance(owner, AgentSession):
        await _release_candidate(owner, None)
    else:
        await _release_candidate(None, owner)
