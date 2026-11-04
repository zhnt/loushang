"""Trusted, bounded calculator Goal configuration; never client-selected code."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .adapters._goal_planning_limits import PlanningCallAllowance
from .adapters._goal_planning_work import PlanningToolPolicy


@dataclass(frozen=True, slots=True)
class CodingHostedGoalV1:
    workspace: Path
    data_root: Path
    max_advances: int = 8
    max_model_calls: int = 8
    max_output_tokens: int = 1024
    deadline_seconds: float = 120.0

    def __post_init__(self) -> None:
        for path in (self.workspace, self.data_root):
            if not isinstance(path, Path) or not path.is_absolute() or path != path.resolve():
                raise ValueError("Goal paths must be canonical")
        for value, maximum in ((self.max_advances, 8), (self.max_model_calls, 8), (self.max_output_tokens, 1024)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid hosted Goal budget")
        self._validate_deadline()

    def _validate_deadline(self) -> None:
        if not _finite_positive(self.deadline_seconds) or self.deadline_seconds > 120:
            raise ValueError("invalid hosted Goal deadline")

    def validate_roots(self, launch) -> None:
        if launch.workspace != self.workspace:
            raise ValueError("Goal workspace must match hosted workspace")
        roots = (self.workspace, self.data_root, launch.application_root,
                 *(scope.session_dir for scope in launch.scopes))
        if any(a.is_relative_to(b) or b.is_relative_to(a)
               for i, a in enumerate(roots) for b in roots[i + 1:]):
            raise ValueError("Goal workspace and record roots must not overlap")


class HostedGoalSetup:
    def __init__(self, config: CodingHostedGoalV1, *, repository=None) -> None:
        self.config = config
        self.repository = repository
        self.goal_id = "repository" if repository is not None else "calculator"
        self.profile_id = "repository-closeout" if repository is not None else "calculator"
        self.allowance = PlanningCallAllowance(total_limit=config.max_model_calls, max_output_tokens=config.max_output_tokens)
        self.policy = repository.tool_policy(config.workspace) if repository is not None else PlanningToolPolicy(config.workspace)


def _finite_positive(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False
