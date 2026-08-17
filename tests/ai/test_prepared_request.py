from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from loushang.ai.context import NormalizedContext
from loushang.ai.errors import (
    AICancelledError,
    AIProviderError,
    AIRequestTooLargeError,
)
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.prepared_request import (
    PreparedModelCallOutcome,
    PreparedModelRequest,
    PreparedRequestAdapter,
    PreparedRequestLimits,
)
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider import ProviderRequest
from loushang.ai.provider.invocation import call_api_adapter_stream


class _RecordingCommitter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[PreparedModelRequest] = []
        self.events: list[str] = []

    async def commit_prepared_request(self, request: PreparedModelRequest) -> None:
        self.requests.append(request)
        self.events.append(f"commit:{request.attempt}")
        if self.fail:
            raise RuntimeError("prepared request commit failed")


class _PreparedAdapter:
    api = "faux"

    def __init__(
        self,
        events: list[str],
        *,
        terminal_error: bool = False,
        terminal_aborted: bool = False,
    ) -> None:
        self.events = events
        self.transport_calls = 0
        self.terminal_error = terminal_error
        self.terminal_aborted = terminal_aborted

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "model": request.model.upstream_id or request.model.id,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    async def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[dict[str, object]]:
        self.transport_calls += 1
        self.events.append(f"transport:{prepared.attempt}")
        assert prepared.payload_for_transport()["model"] == request.model.id
        if prepared.attempt == 1 and request.options is not None:
            retry = request.options.retry
            if retry is not None and retry.max_attempts > 1:
                yield {
                    "type": "response_error",
                    "message": "rate limited",
                    "code": 429,
                    "error_info": {
                        "code": "rate_limit",
                        "message": "rate limited",
                        "source": self.api,
                        "retryable": True,
                        "details": {},
                    },
                }
                return
        if self.terminal_error:
            yield {
                "type": "response_error",
                "message": "Authorization: Bearer secret-token",
                "code": 400,
                "error_info": {
                    "code": "provider",
                    "message": "Provider request failed.",
                    "source": self.api,
                    "retryable": False,
                    "statusCode": 400,
                    "requestId": "request-terminal-400",
                    "details": {"exceptionType": "ProviderHTTPError"},
                },
            }
            return
        if self.terminal_aborted:
            yield {"type": "aborted"}
            return
        yield {"type": "response_start", "response_id": "response-1"}
        yield {"type": "response_done"}

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        raise AssertionError("prepared adapters must use invoke_prepared_raw")
        yield {"type": "response_done"}  # pragma: no cover


class _OutcomeRecordingCommitter(_RecordingCommitter):
    def __init__(self) -> None:
        super().__init__()
        self.outcomes: list[PreparedModelCallOutcome] = []

    async def record_model_call_outcome(
        self,
        outcome: PreparedModelCallOutcome,
    ) -> None:
        self.outcomes.append(outcome)
        self.events.append(f"outcome:{outcome.disposition}")


class _LegacyAdapter:
    api = "faux"

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        yield {"type": "response_done"}


class _InheritedPreparedAdapter(_PreparedAdapter):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.legacy_invoke_calls = 0

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        self.legacy_invoke_calls += 1
        self.events.append("legacy-invoke")
        yield {"type": "response_done"}


def test_prepared_model_request_is_canonical_and_deeply_immutable() -> None:
    prepared = PreparedModelRequest.from_provider_request(
        _request(invocation_id="invocation-1", attempt=2),
        payload={
            "messages": [{"content": "hello", "role": "user"}],
            "model": "faux-model",
        },
    )

    assert prepared.schema_version == 1
    assert prepared.invocation_id == "invocation-1"
    assert prepared.attempt == 2
    assert prepared.canonical_payload == (
        '{"model_visible_headers":{},"payload":{"messages":'
        '[{"content":"hello","role":"user"}],"model":"faux-model"}}'
    )
    assert prepared.payload_hash.startswith("sha256:")
    assert prepared.payload_for_transport() == {
        "messages": [{"content": "hello", "role": "user"}],
        "model": "faux-model",
    }
    with pytest.raises(TypeError):
        prepared.payload["model"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        prepared.payload["messages"][0]["content"] = "changed"  # type: ignore[index]


def test_prepared_model_request_measures_messages_tools_and_images() -> None:
    prepared = PreparedModelRequest.from_provider_request(
        _request(invocation_id="invocation-metrics"),
        payload={
            "messages": [
                {"role": "user", "content": "hello"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "aW1hZ2UtYnl0ZXM=",
                            },
                        }
                    ],
                },
            ],
            "tools": [{"name": "lookup", "input_schema": {"type": "object"}}],
            "model": "faux-model",
        },
        estimated_wire_bytes=2_000,
        estimated_input_tokens=100,
    )

    metrics = prepared.metrics
    assert metrics.canonical_bytes == len(prepared.canonical_payload.encode("utf-8"))
    assert metrics.estimated_wire_bytes == 2_000
    assert metrics.message_bytes is not None
    assert metrics.message_bytes > metrics.image_bytes
    assert metrics.message_count == 2
    assert metrics.image_bytes == len(b"image-bytes")
    assert metrics.tool_schema_bytes > 0
    assert metrics.estimated_input_tokens == 100


def test_prepared_model_request_measures_openai_data_url_image() -> None:
    prepared = PreparedModelRequest.from_provider_request(
        _request(invocation_id="invocation-data-url"),
        payload={
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM=",
                        }
                    ],
                }
            ],
            "model": "faux-model",
        },
    )

    assert prepared.metrics.message_count == 1
    assert prepared.metrics.image_bytes == len(b"image-bytes")


def test_transport_preserves_adapter_payload_key_order() -> None:
    prepared = PreparedModelRequest.from_provider_request(
        _request(invocation_id="invocation-order"),
        payload={
            "tools": [
                {
                    "name": "lookup",
                    "input_schema": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
            "messages": [{"role": "user", "content": "hello"}],
            "model": "faux-model",
        },
    )

    transport = prepared.payload_for_transport()

    assert list(transport) == ["tools", "messages", "model"]
    tools = transport["tools"]
    assert isinstance(tools, list)
    tool = tools[0]
    assert isinstance(tool, dict)
    schema = tool["input_schema"]
    assert isinstance(schema, dict)
    assert list(schema) == ["type", "required", "properties"]


def test_prepared_model_request_rejects_non_json_payload() -> None:
    with pytest.raises(TypeError, match="payload keys must be strings"):
        PreparedModelRequest.from_provider_request(
            _request(invocation_id="invocation-invalid"),
            payload={1: "invalid"},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize(
    ("api", "adapter_type", "payload_field"),
    (
        ("anthropic-messages", AnthropicMessagesAdapter, "messages"),
        ("openai-completions", OpenAIChatCompletionsAdapter, "messages"),
        ("openai-responses", OpenAIResponsesAdapter, "input"),
    ),
)
def test_core_adapter_preparation_freezes_complete_model_visible_payload(
    api: str,
    adapter_type: type[object],
    payload_field: str,
) -> None:
    request = _request(
        api=api,
        headers={"Authorization": "secret-transport-credential"},
        invocation_id="invocation-core",
    )
    adapter = adapter_type()

    assert isinstance(adapter, PreparedRequestAdapter)
    prepared = adapter.prepare_request(request)
    payload = prepared.payload_for_transport()

    assert prepared.invocation_id == "invocation-core"
    assert payload["model"] == "faux-model"
    assert payload_field in payload
    assert "extra_headers" not in payload
    assert "secret-transport-credential" not in prepared.canonical_payload


def test_anthropic_protocol_behavior_headers_are_frozen_before_commit() -> None:
    request = _request(
        api="anthropic-messages",
        invocation_id="invocation-anthropic",
        reasoning_enabled=True,
    )

    prepared = AnthropicMessagesAdapter().prepare_request(request)

    beta_header = prepared.model_visible_headers["anthropic-beta"]
    assert "interleaved-thinking-2025-05-14" in beta_header
    assert beta_header in prepared.canonical_payload


def test_anthropic_transport_header_cannot_enter_frozen_behavior_headers() -> None:
    request = _request(
        api="anthropic-messages",
        headers={"anthropic-beta": "secret-credential-value"},
        invocation_id="invocation-anthropic-secret",
        reasoning_enabled=True,
    )

    prepared = AnthropicMessagesAdapter().prepare_request(request)

    assert "secret-credential-value" not in prepared.canonical_payload
    assert "secret-credential-value" not in prepared.model_visible_headers.values()


def test_prepared_barrier_commits_before_each_retry_transport() -> None:
    async def _run() -> tuple[_PreparedAdapter, _RecordingCommitter]:
        events: list[str] = []
        committer = _RecordingCommitter()
        committer.events = events
        adapter = _PreparedAdapter(events)
        request = _request(
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0),
                prepared_request_committer=committer,
            )
        )

        stream = await call_api_adapter_stream(adapter, request)
        await stream.result()
        return adapter, committer

    adapter, committer = asyncio.run(_run())

    assert isinstance(adapter, PreparedRequestAdapter)
    assert adapter.transport_calls == 2
    assert committer.events == ["commit:1", "transport:1", "commit:2", "transport:2"]
    assert [request.attempt for request in committer.requests] == [1, 2]
    assert len({request.invocation_id for request in committer.requests}) == 1
    assert len({request.payload_hash for request in committer.requests}) == 1


def test_capacity_preflight_rejects_before_commit_and_transport() -> None:
    async def _run() -> tuple[
        _PreparedAdapter,
        _OutcomeRecordingCommitter,
        AIRequestTooLargeError,
    ]:
        committer = _OutcomeRecordingCommitter()
        adapter = _PreparedAdapter(committer.events)
        stream = await call_api_adapter_stream(
            adapter,
            _request(
                options=CallOptions(
                    request_limits=PreparedRequestLimits(max_canonical_bytes=1),
                    prepared_request_committer=committer,
                )
            ),
        )
        with pytest.raises(AIRequestTooLargeError) as exc_info:
            await stream.result()
        return adapter, committer, exc_info.value

    adapter, committer, error = asyncio.run(_run())

    assert adapter.transport_calls == 0
    assert committer.requests == []
    assert committer.events == ["outcome:failed"]
    assert error.info.code.value == "request_too_large"
    assert error.info.retryable is False
    assert error.info.details["capacityMetric"] == "canonicalBytes"
    assert error.info.details["capacityMaximum"] == 1
    assert len(committer.outcomes) == 1
    outcome = committer.outcomes[0]
    assert outcome.disposition == "failed"
    assert outcome.error_info is not None
    assert outcome.error_info["code"] == "request_too_large"


def test_outcome_recorder_runs_once_after_all_internal_provider_retries() -> None:
    async def _run() -> tuple[_PreparedAdapter, _OutcomeRecordingCommitter]:
        events: list[str] = []
        committer = _OutcomeRecordingCommitter()
        committer.events = events
        adapter = _PreparedAdapter(events)
        stream = await call_api_adapter_stream(
            adapter,
            _request(
                options=CallOptions(
                    retry=RetryOptions(max_attempts=2, max_delay_seconds=0),
                    prepared_request_committer=committer,
                )
            ),
        )
        await stream.result()
        return adapter, committer

    adapter, committer = asyncio.run(_run())

    assert adapter.transport_calls == 2
    assert committer.events == [
        "commit:1",
        "transport:1",
        "commit:2",
        "transport:2",
        "outcome:completed",
    ]
    assert len(committer.outcomes) == 1
    outcome = committer.outcomes[0]
    assert outcome.invocation_id == committer.requests[0].invocation_id
    assert outcome.stop_reason == "stop"
    assert outcome.error_info is None


def test_outcome_recorder_receives_typed_terminal_provider_failure() -> None:
    async def _run() -> _OutcomeRecordingCommitter:
        committer = _OutcomeRecordingCommitter()
        adapter = _PreparedAdapter(committer.events, terminal_error=True)
        stream = await call_api_adapter_stream(
            adapter,
            _request(
                options=CallOptions(prepared_request_committer=committer),
            ),
        )
        with pytest.raises(AIProviderError):
            await stream.result()
        return committer

    committer = asyncio.run(_run())

    assert committer.events == ["commit:1", "transport:1", "outcome:failed"]
    assert len(committer.outcomes) == 1
    outcome = committer.outcomes[0]
    assert outcome.disposition == "failed"
    assert outcome.stop_reason == "error"
    assert outcome.error_info is not None
    assert outcome.error_info["code"] == "provider"
    assert outcome.error_info["statusCode"] == 400
    assert outcome.error_info["requestId"] == "request-terminal-400"
    assert "secret-token" not in repr(outcome)


def test_outcome_recorder_receives_terminal_cancellation() -> None:
    async def _run() -> _OutcomeRecordingCommitter:
        committer = _OutcomeRecordingCommitter()
        adapter = _PreparedAdapter(committer.events, terminal_aborted=True)
        stream = await call_api_adapter_stream(
            adapter,
            _request(options=CallOptions(prepared_request_committer=committer)),
        )
        with pytest.raises(AICancelledError):
            await stream.result()
        return committer

    committer = asyncio.run(_run())

    assert committer.events == ["commit:1", "transport:1", "outcome:cancelled"]
    assert len(committer.outcomes) == 1
    outcome = committer.outcomes[0]
    assert outcome.disposition == "cancelled"
    assert outcome.stop_reason == "aborted"
    assert outcome.error_info is None


def test_pre_transport_cancellation_records_outcome_without_an_attempt() -> None:
    async def _run() -> tuple[_PreparedAdapter, _OutcomeRecordingCommitter]:
        cancellation = asyncio.Event()
        cancellation.set()
        committer = _OutcomeRecordingCommitter()
        adapter = _PreparedAdapter(committer.events)
        stream = await call_api_adapter_stream(
            adapter,
            _request(
                options=CallOptions(
                    cancellation=cancellation,
                    prepared_request_committer=committer,
                )
            ),
        )
        with pytest.raises(AICancelledError):
            await stream.result()
        return adapter, committer

    adapter, committer = asyncio.run(_run())

    assert adapter.transport_calls == 0
    assert committer.requests == []
    assert committer.events == ["outcome:cancelled"]
    assert len(committer.outcomes) == 1


def test_committer_failure_makes_zero_transport_calls() -> None:
    async def _run() -> tuple[_PreparedAdapter, _RecordingCommitter, Exception]:
        committer = _RecordingCommitter(fail=True)
        adapter = _PreparedAdapter(committer.events)
        request = _request(
            options=CallOptions(prepared_request_committer=committer),
        )
        stream = await call_api_adapter_stream(adapter, request)
        with pytest.raises(AIProviderError) as exc_info:
            await stream.result()
        return adapter, committer, exc_info.value

    adapter, committer, _error = asyncio.run(_run())

    assert committer.events == ["commit:1"]
    assert adapter.transport_calls == 0


def test_swallowed_commit_cancellation_still_makes_zero_transport_calls() -> None:
    class _CancellationSwallowingCommitter:
        async def commit_prepared_request(
            self,
            request: PreparedModelRequest,
        ) -> None:
            del request
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

    async def _run() -> _PreparedAdapter:
        events: list[str] = []
        adapter = _PreparedAdapter(events)
        request = _request(
            options=CallOptions(
                timeout_seconds=0.01,
                prepared_request_committer=_CancellationSwallowingCommitter(),
            )
        )
        stream = await call_api_adapter_stream(adapter, request)
        with pytest.raises(AIProviderError):
            await stream.result()
        return adapter

    adapter = asyncio.run(_run())

    assert adapter.transport_calls == 0


def test_committer_rejects_adapter_without_prepared_barrier() -> None:
    committer = _RecordingCommitter()

    with pytest.raises(TypeError, match="prepared-request barrier"):
        asyncio.run(
            call_api_adapter_stream(
                _LegacyAdapter(),
                _request(options=CallOptions(prepared_request_committer=committer)),
            )
        )


def test_legacy_adapter_remains_standalone_without_committer() -> None:
    async def _run() -> None:
        stream = await call_api_adapter_stream(_LegacyAdapter(), _request())
        await stream.result()

    asyncio.run(_run())


def test_no_committer_preserves_inherited_invoke_raw_override() -> None:
    async def _run() -> _InheritedPreparedAdapter:
        adapter = _InheritedPreparedAdapter([])
        stream = await call_api_adapter_stream(adapter, _request())
        await stream.result()
        return adapter

    adapter = asyncio.run(_run())

    assert isinstance(adapter, PreparedRequestAdapter)
    assert adapter.legacy_invoke_calls == 1
    assert adapter.transport_calls == 0


def test_request_limits_without_committer_still_use_prepared_barrier() -> None:
    async def _run() -> _InheritedPreparedAdapter:
        adapter = _InheritedPreparedAdapter([])
        stream = await call_api_adapter_stream(
            adapter,
            _request(
                options=CallOptions(
                    request_limits=PreparedRequestLimits(max_canonical_bytes=1)
                )
            ),
        )
        with pytest.raises(AIRequestTooLargeError):
            await stream.result()
        return adapter

    adapter = asyncio.run(_run())

    assert adapter.legacy_invoke_calls == 0
    assert adapter.transport_calls == 0


def test_request_limits_reject_adapter_without_prepared_barrier() -> None:
    with pytest.raises(TypeError, match="prepared-request barrier"):
        asyncio.run(
            call_api_adapter_stream(
                _LegacyAdapter(),
                _request(
                    options=CallOptions(
                        request_limits=PreparedRequestLimits(max_canonical_bytes=1)
                    )
                ),
            )
        )


def test_provider_runtime_requires_initial_attempt_one() -> None:
    with pytest.raises(ValueError, match="initial attempt must be 1"):
        asyncio.run(call_api_adapter_stream(_LegacyAdapter(), _request(attempt=2)))


def _request(
    *,
    options: CallOptions | None = None,
    invocation_id: str | None = None,
    attempt: int = 1,
    api: str = "faux",
    headers: dict[str, str] | None = None,
    reasoning_enabled: bool | None = None,
) -> ProviderRequest:
    model = Model(
        id="faux-model",
        provider="faux",
        endpoint="faux",
        api=api,
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), stream=True),
    )
    return ProviderRequest(
        model=model,
        context=NormalizedContext(system_prompt=None),
        options=options,
        base_url="https://provider.test/v1",
        headers=headers or {},
        reasoning_enabled=reasoning_enabled,
        invocation_id=invocation_id,
        attempt=attempt,
    )
