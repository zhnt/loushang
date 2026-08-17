import asyncio

import pytest

from loushang.agent.types import ProxyStreamOptions
from loushang.ai.errors import AIStreamError
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, Context, Usage, UserMessage


def _model() -> Model:
    return Model(
        id="proxy-model",
        name="Proxy Model",
        provider="proxy",
        endpoint="openai-completions",
        api="openai-completions",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _usage() -> Usage:
    return Usage(
        input=1,
        output=2,
        cache_read=0,
        cache_write=0,
        total_tokens=3,
        cost=None,
    )


def test_process_proxy_event_reconstructs_partial_message() -> None:
    from loushang.agent.proxy import (
        _create_initial_partial_message,
        _process_proxy_event,
    )

    partial = _create_initial_partial_message(_model())

    start_event = _process_proxy_event({"type": "start"}, partial)
    text_start = _process_proxy_event(
        {"type": "text_start", "content_index": 0}, partial
    )
    text_delta = _process_proxy_event(
        {"type": "text_delta", "content_index": 0, "delta": "Hello"}, partial
    )
    text_end = _process_proxy_event(
        {"type": "text_end", "content_index": 0, "content_signature": "sig-1"},
        partial,
    )
    tool_start = _process_proxy_event(
        {
            "type": "toolcall_start",
            "content_index": 1,
            "id": "tc_1",
            "tool_name": "calc",
        },
        partial,
    )
    tool_delta = _process_proxy_event(
        {"type": "toolcall_delta", "content_index": 1, "delta": '{"x": 1}'},
        partial,
    )
    tool_end = _process_proxy_event(
        {"type": "toolcall_end", "content_index": 1}, partial
    )
    done = _process_proxy_event(
        {"type": "done", "reason": "toolUse", "usage": _usage()}, partial
    )

    assert start_event["type"] == "start"
    assert start_event["partial"].usage.cost is None
    assert text_start["type"] == "text_start"
    assert text_delta["type"] == "text_delta"
    assert text_end["type"] == "text_end"
    assert tool_start["type"] == "toolcall_start"
    assert tool_delta["type"] == "toolcall_delta"
    assert tool_end["type"] == "toolcall_end"
    assert done["type"] == "done"

    final_message: AssistantMessage = done["message"]
    assert final_message.content[0].text == "Hello"
    assert final_message.content[0].text_signature == "sig-1"
    assert final_message.content[1].id == "tc_1"
    assert final_message.content[1].name == "calc"
    assert final_message.content[1].arguments == {"x": 1}
    assert final_message.stop_reason == "toolUse"
    assert final_message.usage == _usage()


def test_process_proxy_event_accumulates_partial_toolcall_json_until_valid() -> None:
    from loushang.agent.proxy import (
        _create_initial_partial_message,
        _process_proxy_event,
    )

    partial = _create_initial_partial_message(_model())
    _process_proxy_event(
        {
            "type": "toolcall_start",
            "content_index": 0,
            "id": "tc_1",
            "tool_name": "calc",
        },
        partial,
    )

    first_delta = _process_proxy_event(
        {"type": "toolcall_delta", "content_index": 0, "delta": '{"x": '}, partial
    )
    second_delta = _process_proxy_event(
        {"type": "toolcall_delta", "content_index": 0, "delta": '1, "y": 2}'}, partial
    )
    tool_end = _process_proxy_event(
        {"type": "toolcall_end", "content_index": 0}, partial
    )

    assert first_delta["partial"].content[0].arguments == {}
    assert second_delta["partial"].content[0].arguments == {"x": 1, "y": 2}
    assert tool_end["tool_call"].arguments == {"x": 1, "y": 2}


def test_stream_proxy_emits_error_event_for_non_ok_response() -> None:
    from loushang.agent.proxy import stream_proxy

    context = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0.0)],
    )
    options = ProxyStreamOptions(
        auth_token="secret",
        proxy_url="https://proxy.example.com",
    )
    client = _FakeAsyncClient(
        response=_FakeResponse(
            [],
            status_code=401,
            status_text="Unauthorized",
            json_body={"error": "bad token"},
        )
    )

    async def scenario() -> None:
        stream = stream_proxy(_model(), context, options, client=client)
        events = [event async for event in stream]

        assert [event["type"] for event in events] == ["error"]
        error_event = events[0]
        assert error_event["reason"] == "error"
        assert error_event["error"].error_message == "Proxy error: bad token"
        assert error_event["error"].stop_reason == "error"
        assert error_event["error"].usage.cost is None
        assert client.last_path == "/api/stream"
        assert client.last_headers == {
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        }
        assert client.last_json["model"].id == "proxy-model"

    asyncio.run(scenario())


def test_stream_proxy_reconstructs_sse_success_path() -> None:
    from loushang.agent.proxy import stream_proxy

    context = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0.0)],
    )
    options = ProxyStreamOptions(
        auth_token="secret",
        proxy_url="https://proxy.example.com",
    )
    client = _FakeAsyncClient(
        response=_FakeResponse(
            [
                ": keepalive",
                'data: {"type":"start"}',
                'data: {"type":"text_start","content_index":0}',
                'data: {"type":"text_delta","content_index":0,"delta":"Hello"}',
                'data: {"type":"text_end","content_index":0,"content_signature":"sig-1"}',
                'data: {"type":"thinking_start","content_index":1}',
                'data: {"type":"thinking_delta","content_index":1,"delta":"Plan"}',
                'data: {"type":"thinking_end","content_index":1,"content_signature":"think-1"}',
                'data: {"type":"done","reason":"stop","usage":{"input":1,"output":2,"cache_read":0,"cache_write":0,"total_tokens":3,"cost":{}}}',
            ]
        )
    )

    async def scenario() -> None:
        stream = stream_proxy(_model(), context, options, client=client)
        events = [event async for event in stream]
        result = await stream.result()

        assert [event["type"] for event in events] == [
            "start",
            "text_start",
            "text_delta",
            "text_end",
            "thinking_start",
            "thinking_delta",
            "thinking_end",
            "done",
        ]
        assert result.stop_reason == "stop"
        assert result.content[0].text == "Hello"
        assert result.content[0].text_signature == "sig-1"
        assert result.content[1].thinking == "Plan"
        assert result.content[1].thinking_signature == "think-1"
        assert result.usage.cost is None

    asyncio.run(scenario())


def test_stream_proxy_maps_signal_abort_to_aborted_error() -> None:
    from loushang.agent.proxy import stream_proxy

    class _Signal:
        def __init__(self) -> None:
            self.aborted = False

    context = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0.0)],
    )
    signal = _Signal()
    options = ProxyStreamOptions(
        auth_token="secret",
        proxy_url="https://proxy.example.com",
        signal=signal,
    )
    client = _FakeAsyncClient(
        response=_FakeResponse(
            [
                'data: {"type":"start"}',
            ]
        )
    )

    async def scenario() -> None:
        stream = stream_proxy(_model(), context, options, client=client)
        signal.aborted = True
        events = [event async for event in stream]

        assert [event["type"] for event in events] == ["error"]
        error_event = events[0]
        assert error_event["reason"] == "aborted"
        assert error_event["error"].stop_reason == "aborted"

    asyncio.run(scenario())


def test_stream_proxy_stops_on_proxy_error_event() -> None:
    from loushang.agent.proxy import stream_proxy

    context = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0.0)],
    )
    options = ProxyStreamOptions(
        auth_token="secret",
        proxy_url="https://proxy.example.com",
    )
    client = _FakeAsyncClient(
        response=_FakeResponse(
            [
                'data: {"type":"start"}',
                'data: {"type":"error","reason":"error","error_message":"proxy failed","usage":{"input":1,"output":0,"cache_read":0,"cache_write":0,"total_tokens":1,"cost":{}}}',
                'data: {"type":"text_start","content_index":0}',
            ]
        )
    )

    async def scenario() -> None:
        stream = stream_proxy(_model(), context, options, client=client)
        events = [event async for event in stream]
        with pytest.raises(AIStreamError) as exc_info:
            await stream.result()
        result = await stream.final_message()

        assert [event["type"] for event in events] == ["start", "error"]
        assert str(exc_info.value) == "proxy failed"
        assert events[-1]["error"].error_message == "proxy failed"
        assert events[-1]["error"].usage.cost is None
        assert result.stop_reason == "error"
        assert result.error_message == "proxy failed"
        assert result.usage.cost is None

    asyncio.run(scenario())


def test_stream_proxy_consumer_close_cancels_proxy_task() -> None:
    from loushang.agent.proxy import stream_proxy

    context = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0.0)],
    )
    options = ProxyStreamOptions(
        auth_token="secret",
        proxy_url="https://proxy.example.com",
    )
    response = _BlockingResponse()
    client = _FakeAsyncClient(response=response)

    async def scenario() -> None:
        stream = stream_proxy(_model(), context, options, client=client)
        iterator = stream.__aiter__()
        assert (await iterator.__anext__())["type"] == "start"
        await stream.aclose()
        assert response.closed.is_set()
        task = stream._producer_task
        assert task is not None and task.cancelled()

    asyncio.run(scenario())


def test_stream_proxy_signal_abort_cancels_blocked_sse_read() -> None:
    from loushang.agent.proxy import stream_proxy

    class _Signal:
        def __init__(self) -> None:
            self.aborted = False
            self._listeners = []

        def add_event_listener(self, event: str, listener) -> None:
            assert event == "abort"
            self._listeners.append(listener)

        def remove_event_listener(self, event: str, listener) -> None:
            assert event == "abort"
            self._listeners.remove(listener)

        def abort(self) -> None:
            self.aborted = True
            for listener in list(self._listeners):
                listener()

    context = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0.0)],
    )
    signal = _Signal()
    options = ProxyStreamOptions(
        auth_token="secret",
        proxy_url="https://proxy.example.com",
        signal=signal,
    )
    response = _BlockingResponse()
    client = _FakeAsyncClient(response=response)

    async def scenario() -> None:
        stream = stream_proxy(_model(), context, options, client=client)
        iterator = stream.__aiter__()
        assert (await iterator.__anext__())["type"] == "start"

        signal.abort()
        events = [event async for event in iterator]

        assert [event["type"] for event in events] == ["error"]
        assert events[0]["reason"] == "aborted"
        assert events[0]["error"].stop_reason == "aborted"
        assert response.closed.is_set()
        assert signal._listeners == []

    asyncio.run(scenario())


class _FakeResponse:
    def __init__(
        self,
        lines: list[str],
        *,
        status_code: int = 200,
        status_text: str = "OK",
        json_body: dict | None = None,
    ) -> None:
        self._lines = lines
        self.status_code = status_code
        self.reason_phrase = status_text
        self._json_body = json_body or {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def json(self) -> dict:
        return self._json_body


class _BlockingResponse(_FakeResponse):
    def __init__(self) -> None:
        super().__init__([])
        self.closed = asyncio.Event()

    async def aiter_lines(self):
        try:
            yield 'data: {"type":"start"}'
            await asyncio.Event().wait()
        finally:
            self.closed.set()


class _FakeAsyncClient:
    def __init__(self, *, response: _FakeResponse) -> None:
        self._response = response
        self.last_json: dict | None = None
        self.last_headers: dict | None = None
        self.last_path: str | None = None

    def stream(
        self, method: str, path: str, json: dict, headers: dict
    ) -> _FakeResponse:
        assert method == "POST"
        self.last_path = path
        self.last_json = json
        self.last_headers = headers
        return self._response
