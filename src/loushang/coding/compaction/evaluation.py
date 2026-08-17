"""Coding bindings for the generic summary evaluation runtime."""

from __future__ import annotations

from pathlib import Path

from loushang.coding.compaction.profiles import (
    CODING_BRANCH_SUMMARY_PROFILE,
    CODING_COMPACTION_SUMMARY_PROFILE,
)
from loushang.harness.context import (
    SummaryEvaluationSuiteResult,
    evaluate_summary_fixture,
)

_CODING_SUMMARY_PROFILES = {
    CODING_COMPACTION_SUMMARY_PROFILE.profile_id: CODING_COMPACTION_SUMMARY_PROFILE,
    CODING_BRANCH_SUMMARY_PROFILE.profile_id: CODING_BRANCH_SUMMARY_PROFILE,
}


def evaluate_coding_summary_fixture(path: str | Path) -> SummaryEvaluationSuiteResult:
    """Evaluate a Coding fixture against Coding's summary profiles."""

    return evaluate_summary_fixture(path, profiles=_CODING_SUMMARY_PROFILES)


__all__ = ["evaluate_coding_summary_fixture"]
