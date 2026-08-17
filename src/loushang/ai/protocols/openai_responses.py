from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from loushang.ai.errors import UnsupportedCapabilityError
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model.domain import OpenAIResponsesConfig
from loushang.ai.options import get_reasoning_summary
from loushang.ai.output_budget import resolve_output_token_budget
from loushang.ai.prepared_request import invoke_prepared_request
from loushang.ai.protocols._helpers import (
    canonicalize_sdk_headers,
    close_provider_stream,
)
from loushang.ai.protocols._openai_responses import (
    convert_responses_messages,
    convert_responses_tools,
    process_responses_response,
    process_responses_stream,
)
from loushang.ai.protocols._openai_sdk import OPENAI_SDK_API_KEY_PLACEHOLDER
from loushang.ai.provider import PreparedModelRequest, ProviderRequest
from loushang.ai.provider.errors import provider_error_part
from loushang.ai.structured import openai_responses_text_format
from loushang.ai.trace import emit_trace as _emit_trace


def _resolve_cache_retention(options: object | None) -> str | None:
    cache_retention = (
        getattr(options, "cache_retention", None) if options is not None else None
    )
    if isinstance(cache_retention, str):
        return cache_retention
    return None


def _apply_prompt_cache_params(
    params: dict[str, Any],
    *,
    adapter_config: OpenAIResponsesConfig,
    cache_retention: str | None,
    cache_key: str | None,
) -> None:
    if (cache_retention or "short") == "none":
        return
    if adapter_config.prompt_cache_key and isinstance(cache_key, str) and cache_key:
        params["prompt_cache_key"] = cache_key
    if cache_retention == "long" and adapter_config.long_cache_retention:
        params["prompt_cache_retention"] = "24h"


def _validate_cache_options(
    model: object,
    resolved: object,
    *,
    adapter_config: OpenAIResponsesConfig,
    cache_retention: str | None,
) -> None:
    if cache_retention == "long" and not adapter_config.long_cache_retention:
        raise UnsupportedCapabilityError(
            f"Model {getattr(model, 'id', '<unknown>')!r} does not support long cache retention",
            source=getattr(resolved, "api", None),
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={"capability": "cache_long_retention"},
        )


def _validate_max_output_tokens_option(
    model: object,
    resolved: object,
    *,
    adapter_config: OpenAIResponsesConfig,
    options: object | None,
) -> None:
    if adapter_config.max_output_tokens:
        return
    if getattr(options, "max_output_tokens", None) is None:
        return
    raise UnsupportedCapabilityError(
        f"Model {getattr(model, 'id', '<unknown>')!r} does not support max_output_tokens",
        source=getattr(resolved, "api", None),
        provider=getattr(model, "provider_id", None),
        endpoint=getattr(model, "endpoint_id", None),
        model=getattr(model, "id", None),
        details={"capability": "max_output_tokens"},
    )


class OpenAIResponsesAdapter:
    api = "openai-responses"
    supports_structured_output = True

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        async for part in invoke_prepared_request(self, request):
            yield part

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        model = request.model
        options = request.options
        resolved = request

        def _debug(event: str, data: dict | None = None) -> None:
            _emit_trace(options, {"type": f"sdk:{event}", **(data or {})})

        normalized = request.context
        adapter_config = _request_adapter_config(resolved)
        _validate_max_output_tokens_option(
            model,
            resolved,
            adapter_config=adapter_config,
            options=options,
        )

        # 构造 Responses API 输入。下一步会继续向 pi-ai 的 shared conversion 收敛。
        capabilities = model.capabilities
        input_items = convert_responses_messages(
            model,
            normalized,
            adapter_config,
            capabilities,
        )

        cache_retention = _resolve_cache_retention(options)
        cache_key = getattr(options, "cache_key", None) if options is not None else None
        _validate_cache_options(
            model,
            resolved,
            adapter_config=adapter_config,
            cache_retention=cache_retention,
        )
        upstream_model_id = model.upstream_id or model.id
        is_stream_request = getattr(resolved, "mode", "stream") == "stream"
        params: dict[str, Any] = {
            "model": upstream_model_id,
            "input": input_items,
            "store": False,
        }
        if is_stream_request:
            params["stream"] = True
        # tools（如果提供）映射到 Responses API，触发结构化 function_call 事件
        mapped_tools = convert_responses_tools(normalized.tools)
        if isinstance(mapped_tools, list) and mapped_tools:
            params["tools"] = mapped_tools
            # 缺省让服务端自动选择是否调用工具（仅当 tools 非空）
            explicit_tool_choice = (
                getattr(options, "tool_choice", None) if options is not None else None
            )
            if explicit_tool_choice in {"auto", "none", "required"}:
                params["tool_choice"] = explicit_tool_choice
            elif "tool_choice" not in params:
                params["tool_choice"] = "auto"
        _apply_prompt_cache_params(
            params,
            adapter_config=adapter_config,
            cache_retention=cache_retention,
            cache_key=cache_key,
        )
        if adapter_config.max_output_tokens:
            params["max_output_tokens"] = resolve_output_token_budget(
                model,
                resolved,
            ).value
        # 温度
        if resolved.temperature is not None:
            params["temperature"] = resolved.temperature
        if _supports_reasoning(capabilities):
            if resolved.reasoning_enabled is True:
                reasoning: dict[str, str] = {
                    "effort": resolved.reasoning_effort or "medium",
                }
                reasoning_summary = get_reasoning_summary(options)
                if reasoning_summary is not None:
                    reasoning["summary"] = reasoning_summary
                params["reasoning"] = reasoning
                params["include"] = ["reasoning.encrypted_content"]
            elif resolved.reasoning_enabled is False:
                params["reasoning"] = {"effort": "none"}
        text_format = openai_responses_text_format(options)
        if text_format is not None:
            params["text"] = text_format

        _debug(
            "payload",
            {
                "api": model.api,
                "provider": model.provider_id,
                "endpoint": model.endpoint_id,
                "model": model.id,
                "parameter_keys": sorted(params),
                "input_count": len(input_items),
                "tool_count": len(mapped_tools or []),
            },
        )
        return PreparedModelRequest.from_provider_request(request, payload=params)

    async def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[RawPart]:
        model = request.model
        options = request.options
        resolved = request

        def _debug(event: str, data: dict | None = None) -> None:
            _emit_trace(options, {"type": f"sdk:{event}", **(data or {})})

        try:
            from openai import AsyncOpenAI, Omit  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "openai SDK is not installed. Install via `pip install openai`"
            ) from e

        default_headers = canonicalize_sdk_headers(resolved.headers or {})
        client = self._client or AsyncOpenAI(  # type: ignore[call-arg]
            api_key=OPENAI_SDK_API_KEY_PLACEHOLDER,
            base_url=resolved.base_url,
        )
        _debug(
            "client",
            {
                "api": model.api,
                "provider": model.provider_id,
                "endpoint": model.endpoint_id,
                "model": model.id,
            },
        )

        params: dict[str, Any] = prepared.payload_for_transport()
        params["extra_headers"] = {
            "Authorization": Omit(),
            "X-Api-Key": Omit(),
            **default_headers,
        }

        # 发送请求
        is_stream_request = getattr(resolved, "mode", "stream") == "stream"
        try:
            response = await client.responses.create(**params)
        except Exception as e:
            _debug("stream_error", {"exceptionType": type(e).__name__})
            yield provider_error_part(e, source=self.api)
            return
        if not is_stream_request:
            for part in process_responses_response(
                response,
                reasoning_enabled=resolved.reasoning_enabled is True,
                source=self.api,
            ):
                yield part
            return

        try:
            async for part in process_responses_stream(
                response,
                reasoning_enabled=resolved.reasoning_enabled is True,
                source=self.api,
            ):
                yield part
        except Exception as e:
            _debug("stream_iter_error", {"exceptionType": type(e).__name__})
            yield provider_error_part(e, source=self.api)
        finally:
            await close_provider_stream(response)


def _supports_reasoning(capabilities: object | None) -> bool:
    if capabilities is None:
        return False
    supports_thinking = getattr(capabilities, "supports_thinking", None)
    if supports_thinking is not None:
        return bool(supports_thinking)
    return bool(getattr(capabilities, "reasoning", False))


def _request_adapter_config(request: ProviderRequest) -> OpenAIResponsesConfig:
    adapter_config = request.model.adapter
    if isinstance(adapter_config, OpenAIResponsesConfig):
        return adapter_config
    return OpenAIResponsesConfig()
