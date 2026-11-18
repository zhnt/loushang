"""Cold projection of an authorized Coding Session's Goal and Work journals."""

from __future__ import annotations

from collections import Counter
from os import stat_result
from pathlib import Path
from typing import cast, get_args

from loushang.appserver.execution.model import (
    ExecutionGoalStatusV1,
    GoalRecoveryHistoryReasonV1,
    GoalRecoveryUnavailableReasonV1,
    InteractiveGoalRecoveryV1,
)
from loushang.harness.transcript.jsonl_file import _read_stable_regular_file
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint,
)
from loushang.harnesswork.event_log import decode_detached_work_events
from loushang.harnesswork.goal import GoalHeader
from loushang.harnesswork.goal.records import GoalError, GoalHistory
from loushang.harnesswork.goal.tasks import TASK_POLICY
from loushang.harnesswork.integrations.goal_store import _goal_work_facts
from loushang.harnesswork.recording import _RecordingObserver

from .adapters._goal_store import GoalJournal, goal_journal_path

_MAX_JOURNAL_BYTES = 64 * 1024 * 1024


def unavailable_recovery(reason: GoalRecoveryUnavailableReasonV1) -> InteractiveGoalRecoveryV1:
    return InteractiveGoalRecoveryV1("unavailable", reason, execution_unresolved=True)


def _fingerprint(path: Path) -> str | None:
    try:
        return session_file_authority_fingerprint(path)
    except FileNotFoundError:
        return None


def _read(path: Path, fingerprint: str) -> str:
    return _read_stable_regular_file(
        path, max_bytes=_MAX_JOURNAL_BYTES, expected_source_fingerprint=fingerprint,
    ).decode()


def _project(
    history: GoalHistory, session_id: str, work_path: Path, work_stamp: str | None,
) -> InteractiveGoalRecoveryV1:
    entries = () if work_stamp is None else decode_detached_work_events(_read(work_path, work_stamp), work_path)
    if any(entry.session_id != session_id for entry in entries):
        raise GoalError("Work belongs to a different Session")
    runs, unresolved = _goal_work_facts(history, entries, session_id)
    attempted = {batch.operation_id for batch in history.batches if not batch.not_submitted}
    matched = tuple(run for run in runs if run.operation_id in attempted)
    recordings = _RecordingObserver(entries)
    for run in matched:
        if recordings.get(run.run_id) is None:
            raise GoalError("missing associated Work recording")
    counts = Counter(run.status for run in matched)
    goal, = history.goals.values()
    reason = cast(GoalRecoveryHistoryReasonV1, goal.reason) if goal.reason in get_args(GoalRecoveryHistoryReasonV1) else "other"
    return InteractiveGoalRecoveryV1(
        "present", reason, goal.id, cast(ExecutionGoalStatusV1, goal.status), goal.revision, goal.epoch,
        len(history.batches), counts["completed"], counts["failed"], counts["cancelled"], counts["orphaned"],
        unresolved or any(command.outcome == "pending" for command in history.commands.values()),
    )


def _inputs_unchanged(
    directory: Path, root: stat_result, *inputs: tuple[Path, str | None],
) -> bool:
    try:
        current = directory.lstat()
        return ((root.st_dev, root.st_ino) == (current.st_dev, current.st_ino)
                and all(_fingerprint(path) == stamp for path, stamp in inputs))
    except OSError:
        return False


def read_interactive_goal_recovery(directory: Path, session_id: str) -> InteractiveGoalRecoveryV1:
    """Read only the original journal paths supplied by the authorized catalog."""
    try:
        if not directory.is_absolute() or directory.resolve(strict=True) != directory or not directory.is_dir():
            return unavailable_recovery("source_changed")
        root = directory.stat()
    except (OSError, RuntimeError):
        return unavailable_recovery("source_changed")

    path = goal_journal_path(directory, session_id)
    try:
        stamp = _fingerprint(path)
        header = GoalHeader(session_id, session_id, TASK_POLICY)
        history = None
        if stamp is not None:
            journal = GoalJournal(directory, header, read_only=True)
            history = journal.decode_detached(_read(path, stamp))
    except (OSError, ValueError, RuntimeError):
        return unavailable_recovery("goal_journal_invalid")

    if not _inputs_unchanged(directory, root, (path, stamp)):
        return unavailable_recovery("source_changed")
    if history is not None and history.header != header:
        return unavailable_recovery("unsupported_goal")
    if history is None or not history.goals:
        return InteractiveGoalRecoveryV1("absent", "no_goal")
    if len(history.goals) != 1:
        return unavailable_recovery("ambiguous_goal")
    work_path = path.with_suffix(".work.jsonl")
    try:
        work_stamp = _fingerprint(work_path)
        result = _project(history, session_id, work_path, work_stamp)
    except (OSError, ValueError, RuntimeError):
        return unavailable_recovery("work_log_invalid")
    if not _inputs_unchanged(directory, root, (path, stamp), (work_path, work_stamp)):
        return unavailable_recovery("source_changed")
    return result
