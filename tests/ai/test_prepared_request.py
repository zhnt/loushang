from __future__ import annotations

import asyncio
import json
import threading
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
    invoke_prepared_request,
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


def test_prepared_request_projects_provider_binary_locations() -> None:
    request = PreparedModelRequest(
        invocation_id="binary-contract",
        attempt=1,
        provider_id="provider",
        endpoint_id="endpoint",
        api="api",
        model_id="model",
        mode="stream",
        payload={
            "input": [
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,aGVsbG8=",
                },
                {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": "aGVsbG8=",
                },
            ]
        },
    )

    assert [field.path for field in request.binary_fields] == [
        ("input", 0, "image_url"),
        ("input", 1, "data"),
    ]
    assert [field.encoding for field in request.binary_fields] == [
        "data_url",
        "base64",
    ]


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


def test_prepared_request_reuses_only_an_exact_immutable_message_prefix() -> None:
    first_payload = {
        "messages": [{"role": "user", "content": [{"text": "old", "ok": True}]}],
        "model": "faux-model",
        "tools": [{"name": "read", "parameters": {"type": "object"}}],
    }
    previous = PreparedModelRequest.from_provider_request(
        _request(), payload=first_payload
    )
    next_payload = {
        **first_payload,
        "messages": [
            {"role": "user", "content": [{"text": "old", "ok": True}]},
            {
                "role": "user",
                "content": ["data:image/png;base64,aGVsbG8="],
            },
        ],
    }
    expected = PreparedModelRequest.from_provider_request(
        _request(), payload=next_payload
    )
    reused = PreparedModelRequest.from_provider_request(
        _request(), payload=next_payload, reuse_from=previous
    )
    assert reused.canonical_payload == expected.canonical_payload
    assert reused.payload_hash == expected.payload_hash
    assert reused.metrics == expected.metrics
    assert reused.binary_fields == expected.binary_fields
    assert reused.payload_for_transport() == expected.payload_for_transport()
    assert reused.payload["messages"][0] is previous.payload["messages"][0]

    changed = {
        **next_payload,
        "messages": [
            {"role": "user", "content": [{"text": "old", "ok": 1}]},
            *next_payload["messages"][1:],
        ],
    }
    fallback = PreparedModelRequest.from_provider_request(
        _request(), payload=changed, reuse_from=previous
    )
    assert fallback.payload_for_transport() == changed
    assert fallback.payload["messages"][0] is not previous.payload["messages"][0]

    signed_zero_prior = PreparedModelRequest.from_provider_request(
        _request(), payload={"messages": [{"number": 0.0}]}
    )
    signed_zero = PreparedModelRequest.from_provider_request(
        _request(),
        payload={"messages": [{"number": -0.0}, {"number": 1.0}]},
        reuse_from=signed_zero_prior,
    )
    assert '"number":-0.0' in signed_zero.canonical_payload
    assert (
        signed_zero.payload["messages"][0]
        is not signed_zero_prior.payload["messages"][0]
    )

    reordered = PreparedModelRequest.from_provider_request(
        _request(),
        payload={
            "model": "faux-model",
            "messages": next_payload["messages"],
            "tools": next_payload["tools"],
        },
        reuse_from=previous,
    )
    assert tuple(reordered.payload_for_transport()) == ("model", "messages", "tools")
    assert reordered.payload["messages"][0] is not previous.payload["messages"][0]


def test_prepared_request_accepts_its_own_sealed_message_prefix() -> None:
    previous = PreparedModelRequest.from_provider_request(
        _request(),
        payload={
            "messages": [{"role": "user", "content": [{"text": "old"}]}],
            "model": "faux-model",
        },
    )
    suffix = {"role": "user", "content": [{"text": "new"}]}
    payload = {
        "messages": [previous.payload["messages"][0], suffix],
        "model": "faux-model",
    }
    expected = PreparedModelRequest.from_provider_request(
        _request(),
        payload={
            "messages": [
                {"role": "user", "content": [{"text": "old"}]},
                suffix,
            ],
            "model": "faux-model",
        },
    )
    reused = PreparedModelRequest.from_provider_request(
        _request(), payload=payload, reuse_from=previous
    )

    assert reused.payload["messages"][0] is previous.payload["messages"][0]
    assert reused.canonical_payload == expected.canonical_payload
    assert reused.payload_hash == expected.payload_hash
    assert reused.metrics == expected.metrics
    assert reused.binary_fields == expected.binary_fields
    assert reused.payload_for_transport() == expected.payload_for_transport()


@pytest.mark.parametrize("message_key", ["messages", "input"])
def test_prepared_request_reuses_multiple_large_suffixes_exactly(
    message_key: str,
) -> None:
    messages = [{"role": "user", "content": "history" * 3000}]
    previous = PreparedModelRequest.from_provider_request(
        _request(), payload={"model": "faux-model", message_key: messages}
    )
    for suffix in (
        {"role": "assistant", "content": '文\\"\\\\' * 3000},
        {"role": "tool", "content": "output" * 3000},
        {"role": "user", "content": "final"},
    ):
        messages = [*messages, suffix]
        payload = {"model": "faux-model", message_key: messages}
        expected = PreparedModelRequest.from_provider_request(
            _request(), payload=payload
        )
        reused = PreparedModelRequest.from_provider_request(
            _request(), payload=payload, reuse_from=previous
        )
        assert reused._reused_message_prefix_count == len(messages) - 1
        assert reused.canonical_payload == expected.canonical_payload
        assert reused.payload_hash == expected.payload_hash
        assert reused.metrics == expected.metrics
        assert reused.binary_fields == expected.binary_fields
        assert reused.payload_for_transport() == expected.payload_for_transport()
        previous = reused

    object.__setattr__(previous, "_message_array_close_offset", 0)
    payload = {
        "model": "faux-model",
        message_key: [*messages, {"role": "user", "content": "next"}],
    }
    fallback = PreparedModelRequest.from_provider_request(
        _request(), payload=payload, reuse_from=previous
    )
    full = PreparedModelRequest.from_provider_request(_request(), payload=payload)
    assert fallback._reused_message_prefix_count == 0
    assert fallback.canonical_payload == full.canonical_payload


def test_prepared_request_rechecks_incremental_digest_state() -> None:
    previous = PreparedModelRequest.from_provider_request(
        _request(),
        payload={"model": "faux-model", "messages": [{"role": "user", "content": "旧"}]},
    )
    prefix_digest = previous._message_prefix_digest
    assert prefix_digest is not None
    prefix_digest.update(b"changed")
    payload = {
        "model": "faux-model",
        "messages": [{"role": "user", "content": "旧"}, {"role": "user", "content": "新"}],
    }
    fallback = PreparedModelRequest.from_provider_request(
        _request(), payload=payload, reuse_from=previous
    )
    full = PreparedModelRequest.from_provider_request(_request(), payload=payload)
    assert fallback._reused_message_prefix_count == 0
    assert fallback.payload_hash == full.payload_hash
    assert fallback.metrics == full.metrics


@pytest.mark.parametrize("boundary", ["before_preparation", "after_preparation"])
def test_prepared_invocation_services_cancellation_before_commit(boundary) -> None:
    async def scenario():
        committer = _RecordingCommitter()
        adapter = _PreparedAdapter(committer.events)
        prepared = asyncio.Event()
        original = adapter.prepare_request

        def prepare(request):
            value = original(request)
            prepared.set()
            return value

        adapter.prepare_request = prepare
        source = invoke_prepared_request(
            adapter, _request(options=CallOptions(prepared_request_committer=committer))
        )
        task = asyncio.create_task(anext(source))
        if boundary == "before_preparation":
            await asyncio.sleep(0)
            assert not prepared.is_set()
        else:
            await prepared.wait()
        assert not committer.requests
        assert adapter.transport_calls == 0
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await source.aclose()
        assert not committer.requests
        assert adapter.transport_calls == 0

    asyncio.run(scenario())


def test_opted_in_prepared_request_keeps_input_loop_responsive_and_commits_first() -> (
    None
):
    async def scenario() -> None:
        committer = _RecordingCommitter()
        started = threading.Event()
        release = threading.Event()
        worker_names: list[str] = []

        class WorkerAdapter(_PreparedAdapter):
            prepare_request_in_worker = True

            def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
                worker_names.append(threading.current_thread().name)
                started.set()
                assert release.wait(1.0)
                return super().prepare_request(request)

        adapter = WorkerAdapter(committer.events)
        source = invoke_prepared_request(
            adapter, _request(options=CallOptions(prepared_request_committer=committer))
        )
        timer = threading.Timer(0.5, release.set)
        timer.start()
        task = asyncio.create_task(anext(source))
        try:
            assert await asyncio.to_thread(started.wait, 1.0)
            assert not release.is_set(), "request preparation blocked the input loop"
            assert committer.events == []
        finally:
            release.set()
            timer.cancel()
        assert (await task)["type"] == "response_start"
        await source.aclose()
        assert worker_names and worker_names[0] != "MainThread"
        assert committer.events == ["commit:1", "transport:1"]

    asyncio.run(scenario())


def test_large_transport_copy_is_prepared_during_durable_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        commit_started = asyncio.Event()
        release_commit = asyncio.Event()
        copy_started = threading.Event()
        release_copy = threading.Event()
        copy_threads: list[str] = []
        original_copy = PreparedModelRequest._owned_payload_copy

        def copy(request: PreparedModelRequest):
            copy_threads.append(threading.current_thread().name)
            copy_started.set()
            assert release_copy.wait(2.0)
            return original_copy(request)

        monkeypatch.setattr(PreparedModelRequest, "_owned_payload_copy", copy)

        class HoldingCommitter(_RecordingCommitter):
            async def commit_prepared_request(
                self, request: PreparedModelRequest
            ) -> None:
                commit_started.set()
                await release_commit.wait()
                await super().commit_prepared_request(request)

        class WorkerAdapter(_PreparedAdapter):
            prepare_request_in_worker = True

            def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
                return PreparedModelRequest.from_provider_request(
                    request,
                    payload={
                        "model": request.model.id,
                        "messages": [{"role": "user", "content": "x" * 65536}],
                    },
                )

        committer = HoldingCommitter()
        adapter = WorkerAdapter(committer.events)
        source = invoke_prepared_request(
            adapter, _request(options=CallOptions(prepared_request_committer=committer))
        )
        task = asyncio.create_task(anext(source))
        try:
            await asyncio.wait_for(commit_started.wait(), 1.0)
            assert await asyncio.to_thread(copy_started.wait, 0.5)
            assert not committer.requests
            assert adapter.transport_calls == 0
        finally:
            release_copy.set()
            release_commit.set()
        assert (await task)["type"] == "response_start"
        await source.aclose()
        assert len(copy_threads) == 1
        assert copy_threads[0] != "MainThread"
        assert committer.events == ["commit:1", "transport:1"]

    asyncio.run(scenario())


def test_cancelled_worker_preparation_cannot_commit_or_start_transport() -> None:
    async def scenario() -> None:
        committer = _RecordingCommitter()
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class WorkerAdapter(_PreparedAdapter):
            prepare_request_in_worker = True

            def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
                started.set()
                try:
                    assert release.wait(1.0)
                    return super().prepare_request(request)
                finally:
                    finished.set()

        adapter = WorkerAdapter(committer.events)
        source = invoke_prepared_request(
            adapter, _request(options=CallOptions(prepared_request_committer=committer))
        )
        task = asyncio.create_task(anext(source))
        try:
            assert await asyncio.to_thread(started.wait, 1.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 1.0)
        await source.aclose()
        assert committer.events == []
        assert adapter.transport_calls == 0

    asyncio.run(scenario())


def test_trace_callback_keeps_preparation_on_the_caller_thread() -> None:
    async def scenario() -> None:
        committer = _RecordingCommitter()
        thread_names: list[str] = []

        class WorkerAdapter(_PreparedAdapter):
            prepare_request_in_worker = True

            def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
                thread_names.append(threading.current_thread().name)
                return super().prepare_request(request)

        source = invoke_prepared_request(
            WorkerAdapter(committer.events),
            _request(
                options=CallOptions(
                    prepared_request_committer=committer,
                    trace=lambda _event: None,
                )
            ),
        )
        assert (await anext(source))["type"] == "response_start"
        await source.aclose()
        assert thread_names == ["MainThread"]
        assert committer.events == ["commit:1", "transport:1"]

    asyncio.run(scenario())


def test_worker_adapter_overlaps_committer_prewarm_before_durable_commit() -> None:
    async def scenario() -> None:
        both_started = threading.Event()
        release = threading.Event()
        started: set[str] = set()
        events: list[str] = []

        def mark(name: str) -> None:
            started.add(name)
            if len(started) == 2:
                both_started.set()
            assert release.wait(1.0)

        class WarmCommitter(_RecordingCommitter):
            async def prewarm_logical_input(self) -> None:
                await asyncio.to_thread(mark, "logical")
                events.append("prewarm")

            async def commit_prepared_request(
                self, request: PreparedModelRequest
            ) -> None:
                assert "prewarm" in events
                await super().commit_prepared_request(request)

        class WorkerAdapter(_PreparedAdapter):
            prepare_request_in_worker = True

            def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
                mark("provider")
                return super().prepare_request(request)

        committer = WarmCommitter()
        adapter = WorkerAdapter(committer.events)
        source = invoke_prepared_request(
            adapter, _request(options=CallOptions(prepared_request_committer=committer))
        )
        timer = threading.Timer(0.5, release.set)
        timer.start()
        task = asyncio.create_task(anext(source))
        try:
            assert await asyncio.to_thread(both_started.wait, 1.0)
            assert not release.is_set(), "preparation stages did not overlap"
            assert committer.events == []
        finally:
            release.set()
            timer.cancel()
        assert (await task)["type"] == "response_start"
        await source.aclose()
        assert events == ["prewarm"]
        assert committer.events == ["commit:1", "transport:1"]

    asyncio.run(scenario())


def test_transport_payload_copies_remain_independent_of_source_and_each_other() -> None:
    original = {"messages": [{"content": ["hello"]}]}
    prepared = PreparedModelRequest.from_provider_request(_request(), payload=original)
    canonical, digest = prepared.canonical_payload, prepared.payload_hash
    original["messages"][0]["content"].append("source mutation")
    first = prepared.payload_for_transport()
    first["messages"][0]["content"].append("transport mutation")
    assert prepared.payload_for_transport() == {"messages": [{"content": ["hello"]}]}
    assert prepared.canonical_payload == canonical
    assert prepared.payload_hash == digest


def test_prewarmed_transport_copy_is_used_once_and_remains_detached() -> None:
    prepared = PreparedModelRequest.from_provider_request(
        _request(), payload={"messages": [{"content": ["hello"]}]}
    )
    prepared._adopt_transport_copy(prepared._owned_payload_copy())
    first = prepared.payload_for_transport()
    first["messages"][0]["content"].append("changed")
    assert prepared.payload_for_transport() == {"messages": [{"content": ["hello"]}]}


def test_transport_rejects_replaced_owned_envelope_fields() -> None:
    prepared = PreparedModelRequest.from_provider_request(
        _request(),
        payload={"messages": [{"content": "hello"}]},
        model_visible_headers={"anthropic-beta": "feature-1"},
    )
    object.__setattr__(prepared, "payload", {"messages": [{"content": "changed"}]})
    with pytest.raises(RuntimeError, match="envelope changed"):
        prepared.payload_for_transport()

    prepared = PreparedModelRequest.from_provider_request(
        _request(),
        payload={"messages": [{"content": "hello"}]},
        model_visible_headers={"anthropic-beta": "feature-1"},
    )
    object.__setattr__(prepared, "model_visible_headers", {"anthropic-beta": "changed"})
    with pytest.raises(RuntimeError, match="envelope changed"):
        prepared.model_visible_headers_for_transport()

    prepared = PreparedModelRequest.from_provider_request(
        _request(), payload={"messages": [{"content": "hello"}]}
    )
    object.__setattr__(prepared, "payload_hash", "sha256:" + "0" * 64)
    with pytest.raises(RuntimeError, match="envelope changed"):
        prepared.payload_for_transport()


def test_transport_uses_the_validated_owned_payload_without_another_scan(
    monkeypatch,
) -> None:
    from loushang.ai import prepared_request as module

    prepared = PreparedModelRequest.from_provider_request(
        _request(), payload={"messages": [{"content": "hello"}]}
    )

    def unexpected_validation(*_args, **_kwargs):
        raise AssertionError("sealed transport payload was revalidated")

    monkeypatch.setattr(module, "validate_json_value", unexpected_validation)
    monkeypatch.setattr(module.hashlib, "sha256", unexpected_validation)
    assert prepared.payload_for_transport() == {"messages": [{"content": "hello"}]}


def test_prepared_request_freezes_its_owned_projection_without_another_tree_copy(
    monkeypatch,
) -> None:
    import weakref

    from loushang.ai import prepared_request as module

    class WeakMapping(dict):
        pass

    projected = []
    project = module._project_payload

    def tracked(payload):
        value = WeakMapping(project(payload))
        projected.append(weakref.ref(value))
        return value

    monkeypatch.setattr(module, "_project_payload", tracked)
    original = {"messages": [{"role": "user", "content": ["hello"]}]}
    prepared = PreparedModelRequest.from_provider_request(_request(), payload=original)
    assert projected[0]() is not None, "freezing discarded an already owned JSON tree"
    assert isinstance(projected[0]()["messages"], tuple)
    original["messages"][0]["content"].append("source mutation")
    first = prepared.payload_for_transport()
    first["messages"][0]["content"].append("transport mutation")
    assert prepared.payload_for_transport() == {
        "messages": [{"role": "user", "content": ["hello"]}]
    }


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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "z": {"b": "你好\n世界", "a": [1, 2.5, None]},
            "messages": [{"role": "user", "content": 'λ \\"'}],
            "input": [{"role": "user", "content": "secondary"}],
            "tools": [{"z": 1, "a": {"type": "object"}}],
        },
        {
            "tools": None,
            "input": [{"type": "input_text", "text": "é"}],
            "model": "faux-model",
        },
        {"messages": "unstructured", "input": None, "tools": []},
    ],
)
def test_prepared_request_field_sizes_match_full_canonical_encoding(payload) -> None:
    headers = {"X-Z": "Ω", "X-A": "true"}
    prepared = PreparedModelRequest.from_provider_request(
        _request(invocation_id="field-sizes"),
        payload=payload,
        model_visible_headers=headers,
    )

    def encoded(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    assert prepared.canonical_payload == encoded(
        {"model_visible_headers": headers, "payload": payload}
    )
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = payload.get("input")
    assert prepared.metrics.message_bytes == (
        len(encoded(messages).encode("utf-8")) if isinstance(messages, list) else None
    )
    tools = payload.get("tools")
    assert prepared.metrics.tool_schema_bytes == (
        len(encoded(tools).encode("utf-8")) if tools is not None else 0
    )


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
    "payload",
    [
        {"nested": [float("nan")]},
        {"nested": [float("inf")]},
        {"nested": ["\ud800"]},
        {"nested": {"\ud800": "invalid key"}},
        {"nested": [b"not JSON"]},
    ],
)
def test_detached_payload_still_requires_strict_json(payload) -> None:
    with pytest.raises(TypeError):
        PreparedModelRequest.from_provider_request(_request(), payload=payload)


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


def test_anthropic_client_uses_one_credential_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anthropic

    class ClientObserved(Exception):
        pass

    def client_constructor(**kwargs: object) -> None:
        assert kwargs["api_key"] == ""
        assert "auth_token" not in kwargs
        raise ClientObserved

    monkeypatch.setattr(anthropic, "AsyncAnthropic", client_constructor)
    request = _request(api="anthropic-messages")
    adapter = AnthropicMessagesAdapter()
    prepared = adapter.prepare_request(request)

    async def run() -> None:
        with pytest.raises(ClientObserved):
            await anext(adapter.invoke_prepared_raw(request, prepared))

    asyncio.run(run())


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


def test_failed_large_request_prewarm_cannot_start_transport() -> None:
    class WorkerAdapter(_PreparedAdapter):
        prepare_request_in_worker = True

        def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
            return PreparedModelRequest.from_provider_request(
                request,
                payload={
                    "model": request.model.id,
                    "messages": [{"role": "user", "content": "x" * 65536}],
                },
            )

    async def scenario() -> tuple[WorkerAdapter, _RecordingCommitter]:
        committer = _RecordingCommitter(fail=True)
        adapter = WorkerAdapter(committer.events)
        request = _request(options=CallOptions(prepared_request_committer=committer))
        stream = await call_api_adapter_stream(adapter, request)
        with pytest.raises(AIProviderError):
            await stream.result()
        return adapter, committer

    adapter, committer = asyncio.run(scenario())
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


@pytest.mark.parametrize("boundary", ["before_preparation", "after_preparation"])
def test_forwarded_cancellation_precedes_the_next_prepared_stage(boundary):
    async def scenario():
        committer = _RecordingCommitter()
        adapter = _PreparedAdapter(committer.events)
        original = adapter.prepare_request
        prepared = []
        loop = asyncio.get_running_loop()

        def queue_read_completion():
            loop.call_soon(lambda: loop.call_soon(job.cancel))

        def prepare(request):
            value = original(request)
            prepared.append(True)
            if boundary == "after_preparation":
                queue_read_completion()
            return value

        adapter.prepare_request = prepare
        source = invoke_prepared_request(
            adapter, _request(options=CallOptions(prepared_request_committer=committer))
        )
        job = asyncio.create_task(anext(source))
        if boundary == "before_preparation":
            queue_read_completion()
        with pytest.raises(asyncio.CancelledError):
            await job
        await source.aclose()
        if boundary == "before_preparation":
            assert not prepared, (
                "provider preparation ran before queued cancellation forwarding"
            )
        assert not committer.requests, (
            "commit started before queued cancellation forwarding"
        )
        assert adapter.transport_calls == 0

    asyncio.run(scenario())
