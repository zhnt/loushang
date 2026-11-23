"""In-process model transport for disposable offline checks."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.ai.types import ToolCall


class OfflineModelAdapter:
    """Prepare standard model input and optionally issue one scripted tool call."""

    def __init__(
        self, api: str, *, response_id: str, text: str, tool_call: ToolCall | None = None,
    ) -> None:
        self.api = api
        self._response_id = response_id
        self._text = text
        self._tool_call = tool_call

    @contextmanager
    def registered(self) -> Iterator[None]:
        registry = get_default_api_registry()
        registry.register_api_adapter(self, source_id=self.api)
        try:
            yield
        finally:
            registry.unregister_api_adapters(self.api)

    def model(self, *, model_id: str, name: str, endpoint: str) -> Model:
        return Model(
            id=model_id,
            name=name,
            provider="test",
            endpoint=endpoint,
            api=self.api,
            base_url="https://provider.invalid/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                input=("text",),
                output=("text",),
                context_window=128000,
                stream=True,
                tool_use=True,
            ),
        )

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [
                    serialize_message(item) for item in request.context.messages
                ],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(
        self, request: ProviderRequest, prepared: PreparedModelRequest
    ) -> AsyncIterator[RawPart]:
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": self._response_id}
        tool_call = self._tool_call
        if tool_call is None or any(
            getattr(item, "role", None) == "toolResult" for item in request.context.messages
        ):
            yield {"type": "text_delta", "text": self._text}
            yield {"type": "stop_reason", "stop_reason": "stop"}
        else:
            yield {"type": "tool_call_start", "id": tool_call.id, "name": tool_call.name}
            yield {
                "type": "tool_call_args_delta",
                "tool_call_id": tool_call.id,
                "delta": json.dumps(tool_call.arguments),
            }
            yield {"type": "tool_call_done", "tool_call_id": tool_call.id}
            yield {"type": "stop_reason", "stop_reason": "toolUse"}
        yield {"type": "response_done"}

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part
