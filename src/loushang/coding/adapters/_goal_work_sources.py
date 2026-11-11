"""Product composition of original Goal/Work associations and source readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.transcript.source_reader import TranscriptSourceReader
from loushang.harnesswork.goal import GoalError, GoalHeader
from loushang.harnesswork.integrations.goal_store import (
    _goal_work_facts as _goal_work_facts,
)
from loushang.harnesswork.integrations.goal_store import (
    _read_cold_goal_work_sources,
)
from loushang.harnesswork.integrations.transcript import (
    WorkTranscriptResolution,
)
from loushang.harnesswork.recording import WorkRecording

from ._goal_calculator import POLICY_ID
from ._goal_store import GoalJournal, goal_journal_path


@dataclass(frozen=True)
class GoalWorkSourceView:
    """One historical batch's source observation, never Goal acceptance."""

    batch_id: str
    operation_id: str
    status: Literal[
        "not_submitted", "unresolved", "not_declared", "complete", "incomplete"
    ]
    recording: WorkRecording | None = None
    resolution: WorkTranscriptResolution | None = None


class GoalWorkSourceCleanupError(GoalError):
    """Retain the owned Goal journal when its close needs an explicit retry.

    Call owner.close() again on this same object. The injected Transcript reader
    is still caller-owned; read_error preserves a failure or cancellation which
    preceded cleanup_error, and is None if the read itself succeeded.
    """

    def __init__(
        self,
        owner: GoalJournal,
        read_error: BaseException | None,
        cleanup_error: BaseException,
    ):
        super().__init__("Goal source journal cleanup pending")
        self.owner = owner
        self.read_error = read_error
        self.cleanup_error = cleanup_error


async def read_goal_work_sources(
    *,
    data_root: Path,
    session_id: str,
    goal_id: str,
    reader: TranscriptSourceReader,
) -> tuple[GoalWorkSourceView, ...]:
    """Cold-read original sources after stopping all writers.

    The caller owns the authorized reader and must await its aclose(), retaining
    it and its dependencies for retry if cleanup fails. This function neither
    creates nor closes that reader, and never starts a Session or executor.
    GoalWorkSourceCleanupError retains this function's own journal if closing
    that separate owner fails; its owner.close() must be retried before reopening.
    """
    if reader.conversation_id != session_id:
        raise GoalError("Goal source reader conversation mismatch")
    root = data_root.resolve() / "sessions"
    store = GoalJournal(
        root, GoalHeader(session_id, session_id, POLICY_ID), read_only=True
    )
    return await _read_cold_goal_work_sources(
        store=store,
        session_id=session_id,
        goal_id=goal_id,
        reader=reader,
        supported_headers=lambda: _supported_source_headers(session_id),
        work_log_path=lambda: goal_journal_path(root, session_id).with_suffix(
            ".work.jsonl"
        ),
        selection_decoder=_source_selection_decoder,
        binding_namespace="coding-goal",
        view_factory=lambda *args: GoalWorkSourceView(*args),
        cleanup_error_factory=lambda owner, read_error, cleanup_error: (
            GoalWorkSourceCleanupError(owner, read_error, cleanup_error)
        ),
    )


def _supported_source_headers(session_id: str) -> tuple[GoalHeader, ...]:
    from ._goal_proposal import POLICY_ID as PLANNING_POLICY_ID
    from ._goal_repository_task import RepositoryTask

    return (
        GoalHeader(session_id, session_id, POLICY_ID),
        GoalHeader(session_id, session_id, PLANNING_POLICY_ID),
        GoalHeader(session_id, session_id, RepositoryTask.policy_id),
    )


def _source_selection_decoder():
    from ._goal_delegation_report import decode_selection

    return decode_selection
