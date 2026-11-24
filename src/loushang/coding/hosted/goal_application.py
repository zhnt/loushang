"""Opt-in application-local calculator Goal on the canonical AppHost Session."""
from __future__ import annotations

from loushang.ai.model import Model, ModelSelection
from loushang.apphost.application import HostedApplicationRuntimeV1
from loushang.coding.hosted._goal_config import CodingHostedGoalV1 as CodingHostedGoalV1
from loushang.coding.hosted._goal_config import HostedGoalSetup
from loushang.coding.hosted._repository_config import (
    CodingHostedRepositoryGoalV1 as CodingHostedRepositoryGoalV1,
)
from loushang.coding.hosted.application import _create_coding_scoped_work_application
from loushang.coding.hosted.bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted.goal import create_coding_goal_service_binding


async def create_coding_goal_application(
    launch: CodingHostedLaunchV1, goal: CodingHostedGoalV1, *, model: Model | ModelSelection | None = None,
) -> HostedApplicationRuntimeV1:
    if type(launch) is not CodingHostedLaunchV1 or type(goal) is not CodingHostedGoalV1:
        raise TypeError("explicit launch and calculator Goal required")
    goal.validate_roots(launch)
    setup = HostedGoalSetup(goal)
    return await _create_goal_application(launch, setup, model)


async def _create_goal_application(
    launch: CodingHostedLaunchV1, setup: HostedGoalSetup, model: Model | ModelSelection | None,
) -> HostedApplicationRuntimeV1:
    return await _create_coding_scoped_work_application(
        launch, goal=setup, execution=create_coding_goal_service_binding,
        model=model, stream_fn=setup.allowance.stream, tool_policy=setup.policy,
        active_tools=["read", "edit", "write"], allowed_tools=["read", "edit", "write", "bash"],
        system_prompt=setup.repository.system_prompt if setup.repository is not None else ("Pursue the finite calculator Goal. Planning turns return only the requested JSON; "
                               "Method steps may use file tools and change only calculator.py. "
                               "Do not change requirements, tests, Method or permissions. "
                               "Only independent verification establishes completion."),
    )


async def create_coding_repository_goal_application(
    launch: CodingHostedLaunchV1, goal: CodingHostedRepositoryGoalV1, *,
    model: Model | ModelSelection | None = None,
) -> HostedApplicationRuntimeV1:
    """Run one trusted frozen task on the original hosted Session; no implicit review."""
    if type(launch) is not CodingHostedLaunchV1 or type(goal) is not CodingHostedRepositoryGoalV1:
        raise TypeError("explicit launch and repository Goal required")
    setup = HostedGoalSetup(goal, repository=goal.prepare(launch))
    return await _create_goal_application(launch, setup, model)
