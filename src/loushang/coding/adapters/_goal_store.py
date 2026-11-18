"""Coding's path and owner-identity binding over the optional shared Goal store."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from loushang.harnesswork.goal import GoalHeader
from loushang.harnesswork.integrations.goal_store import JsonlGoalRecordStore

_GOAL_JOURNAL_NAME = re.compile(r"[0-9a-f]{64}\.goal(?:\.work)?\.jsonl")


def is_goal_journal_filename(name: str) -> bool:
    return _GOAL_JOURNAL_NAME.fullmatch(name) is not None


def goal_journal_path(session_dir: Path, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    return session_dir / f"{digest}.goal.jsonl"


class GoalJournal(JsonlGoalRecordStore):
    """Retain this owner before open; close even an unsuccessful admission."""

    def __init__(
        self, session_dir: Path, header: GoalHeader, *, read_only: bool = False
    ):
        super().__init__(
            goal_journal_path(session_dir, header.session_id),
            header,
            owner_id="coding-goal",
            read_only=read_only,
        )
