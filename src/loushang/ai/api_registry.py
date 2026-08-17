from __future__ import annotations

from typing import Any, cast

from loushang.ai.provider.invocation import (
    validate_api_adapter_invoke_raw_contract,
    validate_api_adapter_request_validator_contract,
)
from loushang.ai.provider.protocol import APIAdapter

__all__ = [
    "APIRegistry",
    "DetachedAPIAdapters",
    "get_default_api_registry",
]


def _validate_api_adapter(adapter: APIAdapter) -> str:
    adapter_any = cast(Any, adapter)
    required = ("api", "invoke_raw")
    for name in required:
        if not hasattr(adapter_any, name):
            raise TypeError(f"API adapter missing required attribute: {name}")
    if not callable(adapter_any.invoke_raw):
        raise TypeError("API adapter attribute must be callable: invoke_raw")
    api = adapter_any.api
    if not isinstance(api, str) or not api:
        raise TypeError("API adapter api must be a non-empty string")
    validate_api_adapter_invoke_raw_contract(adapter_any)
    validate_api_adapter_request_validator_contract(adapter_any)
    return api


class APIRegistry:
    def __init__(self) -> None:
        # api -> (protocol adapter, source_id)
        self._adapters: dict[str, tuple[APIAdapter, str | None]] = {}

    def register_api_adapter(
        self, adapter: APIAdapter, *, source_id: str | None = None
    ) -> None:
        api = _validate_api_adapter(adapter)
        if api in self._adapters:
            raise ValueError(f"API adapter already registered: {api}")
        self._adapters[api] = (adapter, source_id)

    def get_api_adapter(self, api: str) -> APIAdapter:
        return self._adapters[api][0]

    def list_api_adapters(self) -> list[APIAdapter]:
        return [entry[0] for entry in self._adapters.values()]

    def unregister_api_adapters(self, source_id: str) -> None:
        """Unregister adapters registered with the given source identifier."""

        self.detach_api_adapters(source_id)

    def detach_api_adapters(self, source_id: str) -> DetachedAPIAdapters:
        """Detach one source's exact adapters for reversible lifecycle masking."""

        detached = tuple(
            (index, api, adapter, sid)
            for index, (api, (adapter, sid)) in enumerate(self._adapters.items())
            if sid == source_id
        )
        for _index, api, _adapter, _sid in detached:
            del self._adapters[api]
        return DetachedAPIAdapters(self, detached)

    def clear_api_adapters(self) -> None:
        self._adapters.clear()


class DetachedAPIAdapters:
    """Opaque, one-shot restoration token for exact API adapter entries."""

    def __init__(
        self,
        registry: APIRegistry,
        entries: tuple[tuple[int, str, APIAdapter, str | None], ...],
    ) -> None:
        self._registry = registry
        self._entries = entries
        self._restored = False

    @property
    def count(self) -> int:
        return len(self._entries)

    def restore(self) -> None:
        if self._restored:
            return
        collisions = [
            api for _index, api, _adapter, _sid in self._entries
            if api in self._registry._adapters
        ]
        if collisions:
            raise RuntimeError("detached API adapter slot is already occupied")
        restored = list(self._registry._adapters.items())
        for index, api, adapter, source_id in self._entries:
            restored.insert(min(index, len(restored)), (api, (adapter, source_id)))
        self._registry._adapters = dict(restored)
        self._restored = True

    def __repr__(self) -> str:
        return f"DetachedAPIAdapters(count={self.count}, restored={self._restored})"


_default_api_registry: APIRegistry | None = None


def get_default_api_registry() -> APIRegistry:
    global _default_api_registry
    if _default_api_registry is None:
        _default_api_registry = APIRegistry()
    return _default_api_registry
