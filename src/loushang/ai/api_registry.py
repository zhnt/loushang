from __future__ import annotations

from typing import Any, cast

from loushang.ai.provider.invocation import (
    validate_api_adapter_invoke_raw_contract,
    validate_api_adapter_request_validator_contract,
)
from loushang.ai.provider.protocol import APIAdapter

__all__ = [
    "APIRegistry",
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

        to_delete: list[str] = []
        for api, (_adapter, sid) in self._adapters.items():
            if sid == source_id:
                to_delete.append(api)
        for api in to_delete:
            del self._adapters[api]

    def clear_api_adapters(self) -> None:
        self._adapters.clear()


_default_api_registry: APIRegistry | None = None


def get_default_api_registry() -> APIRegistry:
    global _default_api_registry
    if _default_api_registry is None:
        _default_api_registry = APIRegistry()
    return _default_api_registry
