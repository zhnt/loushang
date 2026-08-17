from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.ai import CallOptions, complete
from loushang.ai.advanced.registry import get_default_api_registry
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.model import (
    load_builtin_model_registry,
    load_model_registry_from_file,
)
from loushang.ai.model.loader import _load_layered_model_registry
from loushang.ai.provider import ProviderRequest


class RecordingProvider:
    api = "anthropic-messages"

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def invoke_raw(self, request: ProviderRequest):
        self.requests.append(request)
        yield {"type": "response_start", "response_id": "recorded-response"}
        yield {"type": "text_delta", "text": "recorded hello"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def _custom_model_raw() -> dict[str, object]:
    return {
        "providers": {
            "company": {
                "displayName": "Company AI",
                "auth": {"apiKeyEnv": "COMPANY_AI_API_KEY"},
                "endpoints": {
                    "anthropic-messages": {
                        "api": "anthropic-messages",
                        "baseUrl": "https://models.company.example",
                        "adapter": {
                            "fineGrainedTools": True,
                            "longCacheRetention": False,
                        },
                        "models": {
                            "company-chat": {
                                "displayName": "Company Chat",
                                "upstreamId": "vendor/company-chat-2026-06",
                                "capabilities": {
                                    "input": ["text"],
                                    "output": ["text"],
                                    "stream": True,
                                    "toolUse": True,
                                },
                            }
                        },
                    }
                },
            }
        }
    }


def _write_model_file(directory: Path, raw: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "company.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_json_only_custom_model_loads_merges_queries_and_completes(
    tmp_path: Path,
) -> None:
    user_model_dir = tmp_path / "models"
    path = _write_model_file(user_model_dir, _custom_model_raw())

    custom_registry = load_model_registry_from_file(path)
    custom_model = custom_registry.get_model(
        "company",
        "anthropic-messages",
        "company-chat",
    )
    assert custom_model.upstream_id == "vendor/company-chat-2026-06"
    assert custom_model.supports_stream is True
    assert custom_model.supports_tool_use is True

    layered = _load_layered_model_registry(user_dir=user_model_dir)
    builtin_model = load_builtin_model_registry().list_models()[0]
    assert (
        layered.get_model(
            builtin_model.provider_id,
            builtin_model.endpoint_id,
            builtin_model.id,
        ).id
        == builtin_model.id
    )
    model = layered.get_model("company", "anthropic-messages", "company-chat")
    assert model.base_url == "https://models.company.example"
    assert model.upstream_id == "vendor/company-chat-2026-06"

    provider = RecordingProvider()
    provider_registry = get_default_api_registry()
    provider_registry.clear_api_adapters()
    provider_registry.register_api_adapter(provider)

    async def run_complete():
        return await complete(
            model,
            {"messages": [{"role": "user", "content": "hello"}]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )

    message = asyncio.run(run_complete())

    assert message.provider == "company"
    assert message.api == "anthropic-messages"
    assert message.model == "company-chat"
    assert message.response_id == "recorded-response"
    assert message.content[0].text == "recorded hello"

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.mode == "complete"
    assert request.model.provider_id == "company"
    assert request.model.endpoint_id == "anthropic-messages"
    assert request.model.api == "anthropic-messages"
    assert request.base_url == "https://models.company.example"
    assert request.model == model
    assert request.model.capabilities == model.capabilities
    assert request.model.defaults == model.defaults
    assert request.model.upstream_id == "vendor/company-chat-2026-06"
    assert getattr(request.model.adapter, "fine_grained_tools") is True
    assert getattr(request.model.adapter, "long_cache_retention") is False


def test_custom_model_file_rejects_invalid_adapter_field(tmp_path: Path) -> None:
    raw = _custom_model_raw()
    providers = raw["providers"]
    assert isinstance(providers, dict)
    company = providers["company"]
    assert isinstance(company, dict)
    endpoints = company["endpoints"]
    assert isinstance(endpoints, dict)
    endpoint = endpoints["anthropic-messages"]
    assert isinstance(endpoint, dict)
    endpoint["adapter"] = {"maxOutputTokensField": "max_tokens"}

    path = _write_model_file(tmp_path, raw)

    with pytest.raises(ValueError, match="unknown keys") as exc_info:
        load_model_registry_from_file(path)

    assert str(path) in str(exc_info.value)


def test_layered_registry_rejects_duplicate_builtin_full_model_id(
    tmp_path: Path,
) -> None:
    raw = _custom_model_raw()
    builtin_model = load_builtin_model_registry().list_models()[0]
    api = builtin_model.api
    assert api is not None
    assert builtin_model.base_url is not None
    providers = raw["providers"]
    assert isinstance(providers, dict)
    providers.clear()
    providers[builtin_model.provider_id] = {
        "endpoints": {
            builtin_model.endpoint_id: {
                "api": api,
                "baseUrl": builtin_model.base_url,
                "models": {
                    builtin_model.id: {
                        "capabilities": {
                            "input": ["text"],
                            "output": ["text"],
                        }
                    }
                },
            }
        }
    }
    path = _write_model_file(tmp_path, raw)

    with pytest.raises(ValueError, match="duplicate model id") as exc_info:
        _load_layered_model_registry(user_dir=tmp_path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "<builtin>" in message
