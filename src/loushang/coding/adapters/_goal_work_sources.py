"""Product composition of original Goal/Work associations and source readers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.transcript.source_reader import TranscriptSourceReader
from loushang.harnesswork.cancellation_projection import project_work_cancellations
from loushang.harnesswork.event_log import EventLogEntry, JsonlEventLogBackend
from loushang.harnesswork.goal import GoalError, GoalHeader
from loushang.harnesswork.goal.records import GoalHistory, replay
from loushang.harnesswork.integrations.transcript import (
    WorkTranscriptResolution,
    WorkTranscriptSource,
    project_work_transcript,
    resolve_work_transcript,
)
from loushang.harnesswork.recording import WorkRecording, project_work_recording
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.types import WorkRun

from ._goal_calculator import POLICY_ID
from ._goal_store import GoalJournal, goal_journal_path


def _goal_work_facts(
    history: GoalHistory,
    entries: Sequence[EventLogEntry],
    session_id: str,
) -> tuple[tuple[WorkRun, ...], bool]:
    """Use the same historical association checks for business and source reads."""
    runs = tuple(project_work_runs(entries, mark_incomplete_orphaned=True))
    by_operation = {run.operation_id: run for run in runs}
    cancellations = {r.run_id: r for r in project_work_cancellations(entries)}
    unresolved = False
    for batch in history.batches:
        found = by_operation.get(batch.operation_id)
        if batch.not_submitted:
            if found is not None:
                raise GoalError("not_submitted contradicts original Work")
            continue
        if found is None:
            unresolved = True
            continue
        if found.session_id != session_id or (
            batch.run_receipt and batch.run_receipt != found.run_id
        ):
            raise GoalError("Goal/Work association mismatch")
        observation = cancellations.get(found.run_id)
        if (
            found.status == "orphaned"
            or observation is None
            or observation.status
            not in {
                "not_requested",
                "settled",
            }
        ):
            unresolved = True
    return runs, unresolved


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
    """
    if reader.conversation_id != session_id:
        raise GoalError("Goal source reader conversation mismatch")
    root = data_root.resolve() / "sessions"
    store = GoalJournal(
        root, GoalHeader(session_id, session_id, POLICY_ID), read_only=True
    )
    try:
        store.open()
        header, records = store.load()
        from ._goal_proposal import POLICY_ID as PLANNING_POLICY_ID

        if header not in (
            GoalHeader(session_id, session_id, POLICY_ID),
            GoalHeader(session_id, session_id, PLANNING_POLICY_ID),
        ):
            raise GoalError("unsupported Goal source policy")
        history = replay(header, records)
        history.goal(goal_id)
        log = JsonlEventLogBackend(
            goal_journal_path(root, session_id).with_suffix(".work.jsonl")
        )
        entries = log.query()
        runs, _ = _goal_work_facts(history, entries, session_id)
        by_operation = {run.operation_id: run for run in runs}
        views = []
        for batch in history.batches:
            if batch.goal_id != goal_id:
                continue
            identity = (batch.id, batch.operation_id)
            if batch.not_submitted:
                views.append(GoalWorkSourceView(*identity, "not_submitted"))
                continue
            run = by_operation.get(batch.operation_id)
            if run is None:
                views.append(GoalWorkSourceView(*identity, "unresolved"))
                continue
            recording = project_work_recording(entries, run.run_id)
            if recording is None:
                raise GoalError("Goal Work recording disappeared")
            handoffs = project_work_transcript(recording, entries)
            if handoffs is None:
                views.append(GoalWorkSourceView(*identity, "not_declared", recording))
                continue
            if handoffs.binding_id != f"coding-goal:{session_id}":
                raise GoalError("Goal source binding mismatch")
            source = await WorkTranscriptSource.bind(
                reader,
                binding_id=handoffs.binding_id,
                retained_until=handoffs.retained_until,
            )
            resolved = await resolve_work_transcript(recording, entries, source=source)
            views.append(
                GoalWorkSourceView(
                    *identity,
                    "complete" if resolved.handoffs.complete else "incomplete",
                    recording,
                    resolved,
                )
            )
        return tuple(views)
    finally:
        store.close()
