"""Opt-in Goal control. Importing ordinary Work never enables this module."""

from .contracts import (
    GoalAcceptancePolicy,
    GoalAssessment,
    GoalBasis,
    GoalFacts,
    GoalRecordStore,
    NextWorkPolicy,
    PolicyStop,
    WorkCandidate,
)
from .controller import GoalController
from .records import (
    CommandReceipt,
    GoalBatch,
    GoalError,
    GoalHeader,
    GoalHistory,
    GoalRecord,
    GoalState,
    Requirement,
    UnsupportedGoalVersion,
)

__all__ = [
    "GoalController",
    "GoalHeader",
    "GoalRecord",
    "GoalHistory",
    "GoalState",
    "GoalBatch",
    "Requirement",
    "CommandReceipt",
    "GoalError",
    "UnsupportedGoalVersion",
    "GoalBasis",
    "GoalFacts",
    "WorkCandidate",
    "PolicyStop",
    "GoalAssessment",
    "NextWorkPolicy",
    "GoalAcceptancePolicy",
    "GoalRecordStore",
]
