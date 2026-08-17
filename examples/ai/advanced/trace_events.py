"""Advanced offline trace schema and redaction example."""

from __future__ import annotations

import asyncio
import json

from loushang.ai import CallOptions, Model, RetryOptions, stream
from loushang.ai.advanced.registry import clear_api_adapters, register_api_adapter
from loushang.ai.model import Auth, Capabilities, Endpoint, Provider
from loushang.ai.model.registry import ModelRegistry
from loushang.ai.provider import ProviderRequest
from loushang.ai.trace import emit_trace


class _RetryableProviderError(Exception):
    status_code = 503

    def __init__(self) -> None:
        super().__init__("Provider temporarily unavailable.")
        self.headers = {"Retry-After": "0", "x-request-id": "req_trace_retry"}


class _TraceProvider:
    api = "anthropic-messages"

    def __init__(self) -> None:
        self.attempts = 0

    async def invoke_raw(self, request: ProviderRequest):
        self.attempts += 1
        emit_trace(
            request.options,
            {
                "type": "sdk:client",
                "headers": {
                    "Authorization": "Bearer secret-token",
                    "x-api-key": "secret-key",
                    "anthropic-version": "2023-06-01",
                },
                "apiKey": "secret-key",
                "credential": {"private_value": "secret-value"},
            },
        )
        if self.attempts == 1:
            raise _RetryableProviderError()
        yield {"type": "response_start", "response_id": "trace-demo"}
        yield {"type": "text_delta", "text": "trace recovered"}
        yield {"type": "response_done"}


async def inspect_trace_events() -> dict[str, object]:
    provider = _TraceProvider()
    trace_events: list[dict[str, object]] = []
    model_registry = _build_model_registry()
    model = model_registry.get_model("trace-demo", "anthropic-messages", "trace-demo")
    clear_api_adapters()
    register_api_adapter(provider)
    event_stream = await stream(
        model,
        {"messages": []},
        CallOptions(
            retry=RetryOptions(max_attempts=2, max_delay_seconds=0),
            trace=trace_events.append,
        ),
    )
    message = await event_stream.result()
    sdk_client = next(event for event in trace_events if event["type"] == "sdk:client")
    retry = next(event for event in trace_events if event["type"] == "runtime:retry")
    runtime_events = [
        event for event in trace_events if str(event["type"]).startswith("runtime:")
    ]
    runtime_call_ids = [event["data"].get("callId") for event in runtime_events]
    retry_data = dict(retry["data"])
    if isinstance(retry_data.get("callId"), str) and retry_data["callId"]:
        retry_data["callId"] = "<callId>"
    return {
        "schemas": sorted({str(event["schema"]) for event in trace_events}),
        "eventTypes": [event["type"] for event in trace_events],
        "callIdStable": (
            len(runtime_call_ids) == 3
            and all(
                isinstance(call_id, str) and call_id for call_id in runtime_call_ids
            )
            and len(set(runtime_call_ids)) == 1
        ),
        "text": "".join(
            part.text
            for part in message.content
            if getattr(part, "type", None) == "text"
        ),
        "privacy": {
            "dataKeys": sorted(sdk_client["data"]),
            "sensitiveValuesAbsent": "secret-token"
            not in json.dumps(sdk_client, sort_keys=True),
        },
        "retry": retry_data,
    }


def main() -> None:
    print(json.dumps(asyncio.run(inspect_trace_events()), indent=2, sort_keys=True))


def _build_model() -> Model:
    return Model(
        id="trace-demo",
        provider="trace-demo",
        endpoint="anthropic-messages",
        base_url="https://example.invalid/v1",
        capabilities=Capabilities(stream=True),
        auth=Auth(kind="none"),
    )


def _build_model_registry() -> ModelRegistry:
    endpoint = Endpoint(
        id="anthropic-messages",
        provider="trace-demo",
        api="anthropic-messages",
        base_url="https://example.invalid/v1",
        models={"trace-demo": _build_model()},
    )
    return ModelRegistry.from_providers(
        {
            "trace-demo": Provider(
                id="trace-demo",
                endpoints={endpoint.id: endpoint},
            )
        }
    )


if __name__ == "__main__":
    main()
