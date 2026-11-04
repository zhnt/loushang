"""Fresh, process-local hosted Method application using installed Coding wiring."""

from __future__ import annotations

from dataclasses import replace
from secrets import token_hex

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.application import HostedApplicationRuntimeV1
from loushang.harness.tools.core import ToolDefinition

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
from .hosted_method import CodingHostedMethodV1, create_coding_method_service_binding


async def create_coding_method_application(
    launch: CodingHostedLaunchV1, method: CodingHostedMethodV1, *,
    model: Model | ModelSelection | None = None, stream_fn: StreamFn | None = None,
    tools: list[ToolDefinition] | None = None,
) -> HostedApplicationRuntimeV1:
    """One fresh Session, fixed Method, eight submissions; no continuity replay.

    The caller owns the returned application and must close it. Ordinary hosted
    launch/CLI/transport defaults do not select this capability.
    """
    if type(launch) is not CodingHostedLaunchV1 or type(method) is not CodingHostedMethodV1:
        raise TypeError("explicit launch and fixed Method are required")
    request = _coding_foreground_request(
        application_id=launch.application_id, catalog=CodingHostedSessionCatalogV1(launch.scopes),
        generation=token_hex(16), model=model, stream_fn=stream_fn, tools=tools,
        session_discovery=False, owned_transcripts=False, profile_id=CODING_HOSTED_APPLICATION_PROFILE_ID,
    )
    app = await create_coding_foreground_hosted_application(replace(
        request, method=method, execution=create_coding_method_service_binding(launch.application_id),
    ))
    try:
        prepare_coding_hosted_session_roots(launch)
        app.enable_client_scopes()
    except BaseException:
        await app.close()
        raise
    return app
