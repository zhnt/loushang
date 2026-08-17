from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .event_stream import AssistantMessageEventStream
from .types import Context, Model, SimpleStreamOptions, StreamOptions

StreamFunction = Callable[[Model, Context, StreamOptions | None], AssistantMessageEventStream]
StreamSimpleFunction = Callable[[Model, Context, SimpleStreamOptions | None], AssistantMessageEventStream]


@dataclass(slots=True)
class ApiProvider:
    api: str
    stream: StreamFunction
    stream_simple: StreamSimpleFunction


_REGISTRY: dict[str, ApiProvider] = {}


def register_api_provider(provider: ApiProvider) -> None:
    _REGISTRY[provider.api] = provider


def get_api_provider(api: str) -> ApiProvider:
    try:
        return _REGISTRY[api]
    except KeyError as exc:
        raise KeyError(f"No API provider registered for api={api!r}") from exc


def clear_api_providers() -> None:
    _REGISTRY.clear()
