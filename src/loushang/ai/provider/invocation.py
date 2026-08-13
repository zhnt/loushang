from __future__ import annotations

import inspect
from typing import Any

from loushang.ai.context import NormalizedContext
from loushang.ai.provider.protocol import ProviderRequest, ProviderRequestValidator
from loushang.ai.provider.runtime import start_provider_runtime


def validate_api_adapter_invoke_raw_contract(adapter: Any) -> None:
    method = getattr(adapter, "invoke_raw", None)
    if not callable(method):
        raise TypeError("API adapter missing required invoke_raw method")
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        raise TypeError("API adapter invoke_raw signature is not inspectable") from None

    parameters = list(signature.parameters.values())
    if len(parameters) != 1:
        raise TypeError(
            "API adapter invoke_raw must accept exactly one ProviderRequest"
        )
    parameter = parameters[0]
    if parameter.kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise TypeError("API adapter invoke_raw request must be a positional parameter")


def validate_api_adapter_request_validator_contract(adapter: Any) -> None:
    method = getattr(adapter, "validate_request", None)
    if method is None:
        return
    if not callable(method):
        raise TypeError("API adapter validate_request must be callable")
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        raise TypeError(
            "API adapter validate_request signature is not inspectable"
        ) from None

    parameters = list(signature.parameters.values())
    if len(parameters) != 1:
        raise TypeError(
            "API adapter validate_request must accept exactly one ProviderRequest"
        )
    parameter = parameters[0]
    if parameter.kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise TypeError("API adapter validate_request request must be positional")


def validate_provider_request(adapter: Any, request: ProviderRequest) -> None:
    if isinstance(adapter, ProviderRequestValidator):
        adapter.validate_request(request)


def _call_adapter_raw_parts(
    adapter: Any,
    request: ProviderRequest,
):
    if not isinstance(request.context, NormalizedContext):
        raise TypeError("ProviderRequest.context must be NormalizedContext")
    return adapter.invoke_raw(request)


async def call_api_adapter_stream(
    adapter: Any,
    request: ProviderRequest,
):
    invoke_raw_method = getattr(adapter, "invoke_raw", None)
    if request.model.api != adapter.api:
        raise ValueError(
            f"Mismatched api: adapter={adapter.api!r} "
            f"request.model.api={request.model.api!r}"
        )
    if not callable(invoke_raw_method):
        raise TypeError("API adapter missing required invoke_raw method")
    if not isinstance(request.context, NormalizedContext):
        raise TypeError("ProviderRequest.context must be NormalizedContext")
    return start_provider_runtime(
        lambda: _call_adapter_raw_parts(
            adapter,
            request,
        ),
        options=request.options,
        request=request,
    )
