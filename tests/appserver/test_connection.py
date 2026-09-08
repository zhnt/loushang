from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import create_autospec

import pytest

from loushang.appserver.client import AppClientV1, SessionDiscoveryClientV1
from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.framing import (
    AppConnectionClosedError,
    AppFramedStreamV1,
)
from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppOperationV1,
    AppRequestV1,
    AppResponseV1,
    AppServiceError,
    AttachmentEventV1,
    InteractionOutcomeV1,
    InteractionRespondV1,
    InvalidAppMessageError,
    MuxAttachmentV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxListResultV1,
    MuxListV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    MuxSpaceV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnInterruptV1,
    TurnTextV1,
    encode_request,
    encode_response,
)
from loushang.appserver.protocol.codec import MAX_MESSAGE_BYTES
from loushang.appserver.protocol.stdio_profile import STDIO_HELLO_V1
from loushang.appserver.remote_client import StdioAppClientV1


class _MemoryPipe:
    def __init__(self) -> None:
        self.reader = asyncio.StreamReader()
        self.peer: _MemoryPipe
        self.closed = False
        self.block_writes = False

    async def read(self, size: int) -> bytes:
        return await self.reader.read(min(size, 7))

    async def write(self, data: bytes) -> None:
        if self.block_writes:
            await asyncio.Event().wait()
        if self.closed:
            raise OSError("sentinel-private-io")
        self.peer.reader.feed_data(data)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.peer.reader.feed_eof()


def _pair() -> tuple[_MemoryPipe, _MemoryPipe]:
    left, right = _MemoryPipe(), _MemoryPipe()
    left.peer, right.peer = right, left
    return left, right


class _SemanticClient:
    def __init__(self) -> None:
        self.entered = asyncio.Queue[None]()
        self.release = asyncio.Event()
        self.cancelled = 0

    async def start_turn(self, _request: TurnTextV1) -> AckV1:
        self.entered.put_nowait(None)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return AckV1()

    async def interrupt_turn(self, _request: TurnInterruptV1) -> AckV1:
        self.release.set()
        return AckV1()

    async def list_muxes(self) -> MuxListResultV1:
        return MuxListResultV1(())


async def _connect(
    semantic: _SemanticClient,
) -> tuple[StdioAppClientV1, asyncio.Task[None], _MemoryPipe, _MemoryPipe]:
    left, right = _pair()
    server = AppServerConnectionV1(
        cast(AppClientV1, semantic),
        AppFramedStreamV1(right, io_timeout=0.2),
        phase_timeout=0.2,
    )
    serving = asyncio.create_task(server.serve())
    client = StdioAppClientV1(
        AppFramedStreamV1(left, io_timeout=0.2), phase_timeout=0.2
    )
    await client.start()
    return client, serving, left, right


def test_G14_CONTROL_saturated_prompts_do_not_block_interrupt_or_replies() -> None:
    async def scenario() -> None:
        semantic = _SemanticClient()
        client, serving, _, _ = await _connect(semantic)
        prompts = [
            asyncio.create_task(client.start_turn(TurnTextV1("a", 1, "m", "hello")))
            for _ in range(16)
        ]
        for _ in prompts:
            await semantic.entered.get()
        with pytest.raises(AppServiceError) as full:
            await client.list_muxes()
        assert full.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert await client.interrupt_turn(TurnInterruptV1("a", 1, "m")) == AckV1()
        assert await asyncio.gather(*prompts) == [AckV1()] * 16
        assert await client.list_muxes() == MuxListResultV1(())
        await client.close()
        await serving

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G14_WIRE_every_client_method_reaches_its_exact_semantic_target() -> None:
    async def scenario() -> None:
        identity = SessionIdentityV1("coding", "c", "s", SessionScopeV1.CWD, "a" * 64)
        selector = MuxSelectorV1(name="dev")
        mux = MuxSpaceV1("mux", "dev", 1, ())
        snapshot = SessionSnapshotV1(identity, "Coding", 0, 0, False)
        attachment = MuxAttachmentV1("a", mux, 1, ())
        event = AttachmentEventV1(
            "a", "m", SessionEventV1("s", 1, SessionEventKindV1.TURN_COMPLETED)
        )
        calls = (
            ("create_mux", MuxCreateV1("dev"), mux),
            ("list_muxes", None, MuxListResultV1((mux,))),
            ("read_mux", MuxReadV1(selector), mux),
            ("attach_mux", MuxAttachV1(selector), attachment),
            ("detach_mux", MuxDetachV1("a", 1), AckV1()),
            ("close_mux", MuxCloseV1(selector), AckV1()),
            (
                "open_member",
                MuxMemberOpenV1(
                    selector,
                    SessionOpenSpecV1(
                        "coding", "c", SessionScopeV1.CWD, "a" * 64, "Coding"
                    ),
                ),
                mux,
            ),
            ("close_member", MuxMemberCloseV1(selector, "m"), mux),
            ("snapshot_session", SessionSnapshotRequestV1("a", 1, "m"), snapshot),
            ("start_turn", TurnTextV1("a", 1, "m", "start"), AckV1()),
            ("steer_turn", TurnTextV1("a", 1, "m", "steer"), AckV1()),
            ("follow_up_turn", TurnTextV1("a", 1, "m", "follow up"), AckV1()),
            ("interrupt_turn", TurnInterruptV1("a", 1, "m"), AckV1()),
            (
                "respond_interaction",
                InteractionRespondV1("a", 1, "m", "i", InteractionOutcomeV1.DENY),
                AckV1(),
            ),
        )
        method_names = {name for name, _, _ in calls} | {"read_events"}
        assert method_names == {
            name for name in vars(AppClientV1) if not name.startswith("_")
        }
        # G17 adds an optional capability without growing the legacy protocol.
        optional_names = {
            name for name in vars(SessionDiscoveryClientV1) if not name.startswith("_")
        }
        assert optional_names == {"list_sessions"}
        assert not method_names.intersection(optional_names)
        assert len(method_names | optional_names) == len(AppOperationV1)
        semantic = create_autospec(AppClientV1, instance=True)
        for name, _, result in calls:
            getattr(semantic, name).return_value = result
        semantic.read_events.return_value = (event,)
        client, serving, _, _ = await _connect(semantic)
        try:
            for name, request, result in calls:
                args = () if request is None else (request,)
                assert await getattr(client, name)(*args) == result
                getattr(semantic, name).assert_awaited_once_with(*args)
            assert await client.read_events(
                attachment_id="a", controller_generation=1, limit=64
            ) == (event,)
            # The transport deliberately polls one bounded event per wire frame.
            semantic.read_events.assert_awaited_once_with(
                attachment_id="a", controller_generation=1, limit=1
            )
        finally:
            await client.close()
            await serving

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G14_CORRELATION_cancelled_caller_does_not_lose_remote_result() -> None:
    async def scenario() -> None:
        semantic = _SemanticClient()
        client, serving, _, _ = await _connect(semantic)
        prompt = asyncio.create_task(
            client.start_turn(TurnTextV1("a", 1, "m", "hello"))
        )
        await semantic.entered.get()
        prompt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await prompt
        assert semantic.cancelled == 0
        assert await client.list_muxes() == MuxListResultV1(())
        await client.interrupt_turn(TurnInterruptV1("a", 1, "m"))
        await client.list_muxes()
        await client.close()
        await serving
        assert semantic.cancelled == 0

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G14_OWNERSHIP_eof_mid_turn_settles_tasks_and_pending_callers() -> None:
    async def scenario() -> None:
        semantic = _SemanticClient()
        client, serving, _, _ = await _connect(semantic)
        prompt = asyncio.create_task(
            client.start_turn(TurnTextV1("a", 1, "m", "hello"))
        )
        await semantic.entered.get()
        await client.close()
        with pytest.raises(AppConnectionClosedError):
            await prompt
        await serving
        assert semantic.cancelled == 1

    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize("request_id", ["1", "0", "01", "x", "9223372036854775808"])
def test_G14_CORRELATION_repeated_or_invalid_ids_fail_closed(request_id: str) -> None:
    async def scenario() -> None:
        left, right = _pair()
        stream = AppFramedStreamV1(left)
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right)
        )
        serving = asyncio.create_task(server.serve())
        assert await stream.receive() == STDIO_HELLO_V1
        await stream.send(STDIO_HELLO_V1)
        first = encode_request(AppRequestV1("1", AppOperationV1.MUX_LIST, MuxListV1()))
        await stream.send(first)
        await stream.receive()
        await stream.send(
            encode_request(
                AppRequestV1(request_id, AppOperationV1.MUX_LIST, MuxListV1())
            )
        )
        with pytest.raises(InvalidAppMessageError):
            await serving
        await stream.close()

    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize(
    "data",
    [
        b"\0\0\0\0",
        (MAX_MESSAGE_BYTES + 1).to_bytes(4, "big"),
        b"\0\0",
        b"\0\0\0\x04{}",
    ],
    ids=["zero", "oversized", "short-header", "short-body"],
)
def test_G14_WIRE_rejects_invalid_frame_without_reading_unbounded_body(
    data: bytes,
) -> None:
    async def scenario() -> None:
        left, right = _pair()
        right.reader.feed_data(data)
        right.reader.feed_eof()
        with pytest.raises(InvalidAppMessageError):
            await AppFramedStreamV1(right).receive()
        await left.close()

    asyncio.run(scenario())


def test_G14_BACKPRESSURE_nonreading_peer_closes_in_bounded_time() -> None:
    async def scenario() -> None:
        left, right = _pair()
        left.block_writes = True
        with pytest.raises(AppConnectionClosedError, match="^service_closed$"):
            await AppFramedStreamV1(left, io_timeout=0.01).send(b"{}")
        await right.close()

    asyncio.run(asyncio.wait_for(scenario(), 1))


def test_G14_CORRELATION_wrong_result_type_closes_all_pending_waiters() -> None:
    async def scenario() -> None:
        left, right = _pair()
        server = AppFramedStreamV1(right)
        client = StdioAppClientV1(AppFramedStreamV1(left))
        await server.send(STDIO_HELLO_V1)
        await client.start()
        assert await server.receive() == STDIO_HELLO_V1
        calls = [asyncio.create_task(client.list_muxes()) for _ in range(2)]
        await server.receive()
        await server.receive()
        await server.send(encode_response(AppResponseV1("1", AckV1())))
        results = await asyncio.gather(*calls, return_exceptions=True)
        assert all(type(result) is AppConnectionClosedError for result in results)
        await client.close()

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G14_BACKPRESSURE_semantic_exceptions_are_redacted_without_dropping_peer() -> (
    None
):
    class _FailingClient(_SemanticClient):
        async def list_muxes(self) -> MuxListResultV1:
            raise RuntimeError("sentinel-private-path-and-credential")

    async def scenario() -> None:
        client, serving, _, _ = await _connect(_FailingClient())
        for _ in range(2):
            with pytest.raises(AppServiceError, match="^operation_unavailable$"):
                await client.list_muxes()
        await client.close()
        await serving

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G14_OWNERSHIP_client_close_bounds_and_retains_uncooperative_cleanup() -> None:
    async def scenario() -> None:
        left, right = _pair()
        entered, release = asyncio.Event(), asyncio.Event()
        close_calls = 0
        close_cancellations = 0
        original_close = left.close

        async def blocked_close() -> None:
            nonlocal close_calls, close_cancellations
            close_calls += 1
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    close_cancellations += 1
            await original_close()

        left.close = blocked_close
        server = AppFramedStreamV1(right)
        client = StdioAppClientV1(AppFramedStreamV1(left), phase_timeout=0.02)
        await server.send(STDIO_HELLO_V1)
        await client.start()
        await server.receive()
        pending = asyncio.create_task(client.list_muxes())
        await server.receive()
        closing = asyncio.create_task(client.close())
        try:
            await entered.wait()
            with pytest.raises(AppServiceError) as first:
                await asyncio.wait_for(asyncio.shield(closing), 0.3)
            assert first.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            with pytest.raises(AppConnectionClosedError):
                await pending
            with pytest.raises(AppServiceError) as second:
                await asyncio.wait_for(client.close(), 0.3)
            assert second.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert close_calls == 1 and close_cancellations == 0
        finally:
            release.set()
            await asyncio.gather(closing, pending, return_exceptions=True)
            await client.close()
        assert close_calls == 1 and close_cancellations == 0

    asyncio.run(asyncio.wait_for(scenario(), 3))
