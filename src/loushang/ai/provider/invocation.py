from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any
from uuid import uuid4

from loushang.ai.context import NormalizedContext
from loushang.ai.prepared_request import (
    PreparedRequestAdapter,
    invoke_prepared_request,
)
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
    if request.attempt != 1:
        raise ValueError("ProviderRequest initial attempt must be 1")
    committer = (
        request.options.prepared_request_committer
        if request.options is not None
        else None
    )
    request_limits = (
        request.options.request_limits if request.options is not None else None
    )
    uses_prepared_barrier = isinstance(adapter, PreparedRequestAdapter)
    requires_prepared_barrier = committer is not None or request_limits is not None
    if requires_prepared_barrier and not uses_prepared_barrier:
        raise TypeError(
            f"API adapter {adapter.api!r} does not implement the prepared-request barrier"
        )

    invocation_id = request.invocation_id or uuid4().hex
    attempt = request.attempt - 1

    def _raw_parts():
        nonlocal attempt
        attempt += 1
        attempt_request = (
            request
            if request.invocation_id == invocation_id and request.attempt == attempt
            else replace(
                request,
                invocation_id=invocation_id,
                attempt=attempt,
            )
        )
        if requires_prepared_barrier:
            return invoke_prepared_request(adapter, attempt_request)
        return _call_adapter_raw_parts(adapter, attempt_request)

    return start_provider_runtime(
        _raw_parts,
        options=request.options,
        request=request,
        invocation_id=invocation_id,
    )
