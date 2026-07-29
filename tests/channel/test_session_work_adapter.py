from __future__ import annotations

import asyncio

from loushang.channel import ChannelOperationRequest
from loushang.channel.adapters.session_work import (
    SessionWorkChannelPort,
    SessionWorkChannelProfile,
)
from loushang.channel.types import ChannelEnvelope
from loushang.work import InMemoryEventLogBackend, WorkOperation
from loushang.work.session import SessionWorkProfile, SessionWorkRuntime


class _Session:
    session_id = "research-1"

    def __init__(self) -> None:
        self.listeners = []
        self.prompts: list[str] = []
        self.release = asyncio.Event()

    def subscribe_runtime_events(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    async def prompt(self, text: str, **kwargs: object) -> None:
        del kwargs
        self.prompts.append(text)
        await self.release.wait()

    def abort(self) -> None:
        self.release.set()

    async def wait_for_idle(self) -> None:
        await self.release.wait()


def test_session_work_channel_port_accepts_non_coding_profile() -> None:
    async def scenario() -> None:
        session = _Session()
        runtime = SessionWorkRuntime(
            session=session,
            event_log=InMemoryEventLogBackend(),
            profile=SessionWorkProfile(
                domain="research",
                operation_kind="SubmitResearchTurn",
            ),
            project_event_facts=lambda _event: (),
            session_id=lambda: session.session_id,
        )
        port = SessionWorkChannelPort(
            session=session,
            runtime=runtime,
            profile=SessionWorkChannelProfile(
                product_name="Research",
                domain="research",
                operation_kind="SubmitResearchTurn",
            ),
            project_runtime_envelopes=lambda _event, _operation_id: (),
        )
        request = ChannelOperationRequest(
            request_id="request-1",
            envelope=ChannelEnvelope(
                envelope_id="envelope-1",
                kind="operation",
                payload=WorkOperation(
                    operation_id="operation-1",
                    kind="SubmitResearchTurn",
                    session_id=session.session_id,
                    domain="research",
                    payload={"text": "review the sources"},
                ),
            ),
        )

        accepted = await port.accept_operation(request)
        await asyncio.sleep(0)

        assert accepted.operation_id == "operation-1"
        assert session.prompts == ["review the sources"]
        session.release.set()
        await asyncio.sleep(0)
        port.close()

    asyncio.run(scenario())
