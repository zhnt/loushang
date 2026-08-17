"""Reusable contract probe for the prepared-request commit barrier."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from loushang.ai.context import NormalizedContext
from loushang.ai.errors import AIError
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.options import CallOptions
from loushang.ai.prepared_request import (
    PreparedModelRequest,
    PreparedRequestCommitter,
)
from loushang.ai.provider.invocation import call_api_adapter_stream
from loushang.ai.provider.protocol import ProviderRequest


@dataclass(frozen=True, slots=True)
class PreparedRequestBarrierConformanceReport:
    """Observable ordering and outcome from one contract probe invocation."""

    events: tuple[str, ...]
    prepared_requests: tuple[PreparedModelRequest, ...]
    transport_calls: int
    error: AIError | None = field(default=None, repr=False)

    @property
    def commit_completed(self) -> bool:
        return "commit:completed" in self.events


class _ObservedCommitter:
    def __init__(
        self,
        delegate: PreparedRequestCommitter,
        events: list[str],
        prepared_requests: list[PreparedModelRequest],
    ) -> None:
        self._delegate = delegate
        self._events = events
        self._prepared_requests = prepared_requests

    async def commit_prepared_request(self, request: PreparedModelRequest) -> None:
        self._events.append("commit:started")
        self._prepared_requests.append(request)
        await self._delegate.commit_prepared_request(request)
        self._events.append("commit:completed")


class _ConformanceAdapter:
    api = "prepared-request-conformance"

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.transport_calls = 0

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "model": request.model.id,
                "messages": [{"role": "user", "content": "conformance"}],
            },
        )

    async def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[dict[str, object]]:
        del request
        self.transport_calls += 1
        self._events.append("transport")
        prepared.payload_for_transport()
        yield {"type": "response_done"}

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        del request
        raise AssertionError("a configured committer must use the prepared barrier")
        yield {"type": "response_done"}  # pragma: no cover


async def run_prepared_request_barrier_conformance(
    committer: PreparedRequestCommitter,
) -> PreparedRequestBarrierConformanceReport:
    """Exercise one committer through the real provider runtime boundary.

    The returned report lets another package assert its own durable side
    effects while this probe enforces the cross-package ordering invariant:
    transport is impossible unless the delegated commit completed.
    """

    events: list[str] = []
    prepared_requests: list[PreparedModelRequest] = []
    observed = _ObservedCommitter(committer, events, prepared_requests)
    adapter = _ConformanceAdapter(events)
    model = Model(
        id="conformance-model",
        provider="conformance-provider",
        endpoint="conformance-endpoint",
        api=adapter.api,
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), output=("text",), stream=True),
    )
    request = ProviderRequest(
        model=model,
        context=NormalizedContext(system_prompt=None),
        options=CallOptions(prepared_request_committer=observed),
        base_url="https://provider.test/v1",
        invocation_id="prepared-request-conformance",
    )
    stream = await call_api_adapter_stream(adapter, request)
    error: AIError | None = None
    try:
        await stream.result()
    except AIError as exc:
        error = exc

    report = PreparedRequestBarrierConformanceReport(
        events=tuple(events),
        prepared_requests=tuple(prepared_requests),
        transport_calls=adapter.transport_calls,
        error=error,
    )
    if not report.commit_completed and report.transport_calls:
        raise AssertionError("prepared-request transport preceded durable commit")
    return report


__all__ = [
    "PreparedRequestBarrierConformanceReport",
    "run_prepared_request_barrier_conformance",
]
