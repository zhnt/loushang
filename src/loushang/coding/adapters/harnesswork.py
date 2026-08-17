"""Coding vocabulary bound to the shared Agent session Work adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TextIO, cast

from loushang.channel.adapters.harnesswork import (
    SessionWorkChannelProfile,
    SessionWorkChannelSession,
    run_session_work_channel_host,
)
from loushang.channel.adapters.runtime_events import AgentRuntimeChannelProjection
from loushang.harness.session import JsonEventView, require_active_session_control
from loushang.harnesswork import InMemoryEventLogBackend
from loushang.harnesswork.event_log import EventLogBackend
from loushang.harnesswork.integrations.agent_session import (
    create_agent_session_work_runtime,
    project_agent_runtime_event_to_work_facts,
)
from loushang.harnesswork.integrations.session import (
    SessionPromptPort,
    SessionWorkProfile,
    SessionWorkRuntime,
)

CODING_WORK_PROFILE = SessionWorkProfile(
    domain="coding",
    operation_kind="SubmitCodingTurn",
)
CODING_WORK_CHANNEL_PROFILE = SessionWorkChannelProfile(
    product_name="Coding",
    domain=CODING_WORK_PROFILE.domain,
    operation_kind=CODING_WORK_PROFILE.operation_kind,
)

project_coding_runtime_event = project_agent_runtime_event_to_work_facts


def create_coding_work_runtime(
    *,
    session: SessionPromptPort,
    event_log: EventLogBackend,
    session_id: Callable[[], str] = lambda: "",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    cancellation_timeout: float | None = 30.0,
) -> SessionWorkRuntime:
    return create_agent_session_work_runtime(
        session=session,
        event_log=event_log,
        profile=CODING_WORK_PROFILE,
        session_id=session_id,
        clock=clock,
        cancellation_timeout=cancellation_timeout,
    )


async def run_coding_work_channel(
    *,
    runtime: object,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO | None = None,
    event_view: JsonEventView = "full",
    event_select: Sequence[str] | str | None = None,
    work_event_log: EventLogBackend | None = None,
    work_runtime: SessionWorkRuntime | None = None,
) -> int:
    """Bind Coding's Work vocabulary to the shared Agent Channel host."""

    session = require_active_session_control(runtime)
    event_log = work_event_log or InMemoryEventLogBackend()
    resolved_work_runtime = work_runtime or create_coding_work_runtime(
        session=cast(SessionPromptPort, session),
        event_log=event_log,
        session_id=lambda: session.session_id,
    )
    return await run_session_work_channel_host(
        session=cast(SessionWorkChannelSession, session),
        runtime=resolved_work_runtime,
        profile=CODING_WORK_CHANNEL_PROFILE,
        project_runtime_envelopes=AgentRuntimeChannelProjection(
            event_view=event_view,
            event_select=event_select,
        ),
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


__all__ = [
    "CODING_WORK_CHANNEL_PROFILE",
    "CODING_WORK_PROFILE",
    "create_coding_work_runtime",
    "project_coding_runtime_event",
    "run_coding_work_channel",
]
