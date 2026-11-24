"""Fresh, process-local hosted Method application using installed Coding wiring."""

from __future__ import annotations

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.application import HostedApplicationRuntimeV1
from loushang.coding.hosted.bootstrap import (
    CodingHostedLaunchV1,
    _create_coding_scoped_work_application,
)
from loushang.coding.hosted.method import (
    CodingHostedMethodV1,
    create_coding_method_service_binding,
)
from loushang.harness.tools.core import ToolDefinition


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
    return await _create_coding_scoped_work_application(
        launch, method=method, execution=create_coding_method_service_binding,
        model=model, stream_fn=stream_fn, tools=tools,
    )
