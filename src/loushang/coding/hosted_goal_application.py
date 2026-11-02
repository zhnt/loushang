"""Opt-in application-local calculator Goal on the canonical AppHost Session."""
from __future__ import annotations

from dataclasses import replace
from secrets import token_hex

from loushang.ai.model import Model, ModelSelection
from loushang.apphost.application import HostedApplicationRuntimeV1

from ._hosted_goal_config import CodingHostedGoalV1 as CodingHostedGoalV1
from ._hosted_goal_config import HostedGoalSetup
from .hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    create_coding_foreground_hosted_application,
)
from .hosted_bootstrap import (
    CodingHostedLaunchV1,
    _coding_foreground_request,
    prepare_coding_hosted_session_roots,
)
from .hosted_catalog import CodingHostedSessionCatalogV1
from .hosted_goal import create_coding_goal_service_binding


async def create_coding_goal_application(
    launch: CodingHostedLaunchV1, goal: CodingHostedGoalV1, *, model: Model | ModelSelection | None = None,
) -> HostedApplicationRuntimeV1:
    if type(launch) is not CodingHostedLaunchV1 or type(goal) is not CodingHostedGoalV1:
        raise TypeError("explicit launch and calculator Goal required")
    goal.validate_roots(launch)
    setup = HostedGoalSetup(goal)
    request = _coding_foreground_request(
        application_id=launch.application_id, catalog=CodingHostedSessionCatalogV1(launch.scopes),
        generation=token_hex(16), model=model, stream_fn=setup.allowance.stream, tools=None,
        session_discovery=False, owned_transcripts=False, profile_id=CODING_HOSTED_APPLICATION_PROFILE_ID,
        session_tool_policy=setup.policy, session_active_tools=["read", "edit", "write"],
        session_allowed_tools=["read", "edit", "write", "bash"],
        session_system_prompt=("Pursue the finite calculator Goal. Planning turns return only the requested JSON; "
                               "Method steps may use file tools and change only calculator.py. "
                               "Do not change requirements, tests, Method or permissions. "
                               "Only independent verification establishes completion."),
    )
    app = await create_coding_foreground_hosted_application(replace(
        request, goal=setup, execution=create_coding_goal_service_binding(launch.application_id),
    ))
    try:
        prepare_coding_hosted_session_roots(launch)
        app.enable_client_scopes()
    except BaseException:
        await app.close()
        raise
    return app
