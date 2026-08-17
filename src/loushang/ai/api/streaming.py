from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.auth.credentials import AuthCredential
from loushang.ai.auth.resolver import resolve_auth
from loushang.ai.bootstrap import register_builtin_api_adapters
from loushang.ai.context import NormalizedContext, normalize_context_result
from loushang.ai.diagnostics import NormalizationDiagnostic
from loushang.ai.errors import UnsupportedCapabilityError
from loushang.ai.model import (
    AnthropicMessagesConfig,
    Model,
    OpenAIResponsesConfig,
    default_adapter_config,
)
from loushang.ai.options import CallOptions, PairingMode
from loushang.ai.provider import (
    ProviderInvocationMode,
    normalize_provider_request_for_api,
    resolve_request_for_model,
)
from loushang.ai.provider.invocation import (
    call_api_adapter_stream,
    validate_provider_request,
)
from loushang.ai.provider_registry import get_default_provider_registry
from loushang.ai.structured import (
    StructuredOutputOptions,
    StructuredOutputResult,
    get_structured_output_options,
    parse_structured_output,
    with_structured_output_options,
)
from loushang.ai.utils.capabilities import context_has_image_input


def _has_tools(normalized_context: NormalizedContext) -> bool:
    return bool(normalized_context.tools)


def _requests_structured_output(options) -> bool:
    return get_structured_output_options(options) is not None


def _requests_tool_choice(options) -> bool:
    if options is None:
        return False
    tool_choice = getattr(options, "tool_choice", None)
    return tool_choice is not None and tool_choice != "none"


def _supports(capabilities, field: str) -> bool:
    return bool(getattr(capabilities, field, False))


def _adapter_supports_long_cache_retention(adapter_config: object) -> bool:
    if isinstance(adapter_config, OpenAIResponsesConfig | AnthropicMessagesConfig):
        return adapter_config.long_cache_retention
    return False


def _adapter_consumes_cache_key(adapter_config: object) -> bool:
    if isinstance(adapter_config, OpenAIResponsesConfig):
        return adapter_config.prompt_cache_key
    return False


def _normalize_cache_key_for_adapter(
    options: CallOptions | None,
    adapter_config: object,
) -> CallOptions | None:
    """Return call options safe for the resolved adapter."""
    if options is None:
        return None

    cache_key = getattr(options, "cache_key", None)
    if not isinstance(cache_key, str) or not cache_key:
        return options

    if getattr(options, "cache_retention", None) == "none":
        return replace(options, cache_key=None)

    if _adapter_consumes_cache_key(adapter_config):
        return options

    return replace(options, cache_key=None)


def _resolved_adapter_config(model) -> object:
    return model.adapter or default_adapter_config(model.api or "")


def _validate_explicit_adapter_config(model, options) -> None:
    if options is None:
        return
    adapter_config = _resolved_adapter_config(model)
    cache_retention = getattr(options, "cache_retention", None)
    if cache_retention == "long" and not _adapter_supports_long_cache_retention(
        adapter_config
    ):
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support long cache retention",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=getattr(model, "id", None),
            details={"capability": "cache_long_retention"},
        )


def _validate_capability(
    model,
    capabilities,
    normalized_context: NormalizedContext,
    options,
    resolved_request,
    *,
    require_stream: bool,
) -> None:
    if require_stream and not _supports(capabilities, "stream"):
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support streaming",
            model=getattr(model, "id", None),
            details={"capability": "stream"},
        )

    if (
        _has_tools(normalized_context) or _requests_tool_choice(options)
    ) and not _supports(capabilities, "tool_use"):
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support tool use",
            model=getattr(model, "id", None),
            details={"capability": "tool_use"},
        )

    if getattr(resolved_request, "reasoning_enabled", None) is True and not _supports(
        capabilities, "reasoning"
    ):
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support reasoning",
            model=getattr(model, "id", None),
            details={"capability": "reasoning"},
        )

    if _requests_structured_output(options) and not _supports(
        capabilities, "structured_output"
    ):
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support structured output",
            model=getattr(model, "id", None),
            details={"capability": "structured_output"},
        )

    if getattr(resolved_request, "temperature", None) is not None and not _supports(
        capabilities, "temperature"
    ):
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support temperature",
            model=getattr(model, "id", None),
            details={"capability": "temperature"},
        )

    supports_image_input = bool(getattr(capabilities, "supports_image_input", False))
    if context_has_image_input(normalized_context.messages) and not supports_image_input:
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support image input",
            model=getattr(model, "id", None),
            details={"capability": "image_input"},
        )


def _resolve_provider_registry():
    default_registry = get_default_api_registry()
    if not default_registry.list_api_adapters():
        register_builtin_api_adapters(default_registry)
    return get_default_provider_registry()


def _validate_call_options(options: object | None) -> CallOptions | None:
    if options is None or isinstance(options, CallOptions):
        return options
    raise TypeError("options must be CallOptions")


def _supports_structured_output_mapping(adapter: object) -> bool:
    return bool(getattr(adapter, "supports_structured_output", False))


def _resolve_pairing_mode(options) -> PairingMode:
    if options is None:
        return "repair"
    pairing_mode = getattr(options, "pairing_mode", "repair")
    if pairing_mode == "repair":
        return "repair"
    return "strict"


def _emit_normalization_diagnostics(
    options: CallOptions | None,
    diagnostics: tuple[NormalizationDiagnostic, ...],
) -> None:
    if not diagnostics:
        return
    from loushang.ai.trace import emit_trace
    from loushang.foundation.observability import get_log

    log = get_log(__name__).bind(component="AINormalization")
    for diagnostic in diagnostics:
        payload = {
            "type": "normalization:diagnostic",
            "code": diagnostic.code,
            "field": diagnostic.path,
            "level": diagnostic.level,
        }
        emit_trace(options, payload)
        if diagnostic.level == "warning":
            log.warning(
                diagnostic.message,
                code=diagnostic.code,
                path=diagnostic.path,
                level=diagnostic.level,
            )
        else:
            log.debug(
                diagnostic.message,
                code=diagnostic.code,
                path=diagnostic.path,
                level=diagnostic.level,
            )


async def _start_stream(
    model: Model,
    context,
    options: CallOptions | None = None,
    *,
    mode: ProviderInvocationMode,
    require_stream: bool,
):
    options = _validate_call_options(options)
    request_auth = await resolve_auth(model, options=options)
    if options is None:
        prepared_options = CallOptions(auth=request_auth) if request_auth else None
    else:
        prepared_options = replace(
            options,
            auth=request_auth,
            credential=None,
            credential_file=None,
        )
    resolved = resolve_request_for_model(model, options=prepared_options)
    resolved_model = resolved.model
    options = _normalize_cache_key_for_adapter(
        prepared_options,
        _resolved_adapter_config(resolved_model),
    )
    normalization_result = normalize_context_result(
        context,
        model=resolved_model,
        pairing_mode=_resolve_pairing_mode(options),
    )
    normalized = normalization_result.context
    _emit_normalization_diagnostics(options, normalization_result.diagnostics)
    resolved = replace(
        resolved,
        context=normalized,
        options=options,
        mode=mode,
        invocation_id=uuid4().hex,
        attempt=1,
    )
    _validate_capability(
        resolved_model,
        resolved_model.capabilities,
        normalized,
        options,
        resolved,
        require_stream=require_stream,
    )
    _validate_explicit_adapter_config(resolved_model, options)
    adapter = _resolve_provider_registry().resolve_api_adapter(
        resolved_model.provider_id,
        resolved_model.api or "",
    )
    resolved = normalize_provider_request_for_api(adapter.api, resolved)
    validate_provider_request(adapter, resolved)
    if get_structured_output_options(
        options
    ) is not None and not _supports_structured_output_mapping(adapter):
        raise UnsupportedCapabilityError(
            f"Provider API {resolved_model.api!r} does not support structured output mapping",
            provider=resolved_model.provider_id,
            endpoint=resolved_model.endpoint_id,
            model=resolved_model.id,
            details={
                "capability": "structured_output_mapping",
                "api": resolved_model.api,
            },
        )
    return await call_api_adapter_stream(adapter, resolved)


async def stream(
    model: Model,
    context,
    options: CallOptions | None = None,
    *,
    auth: AuthCredential | None = None,
):
    return await _start_stream(
        model,
        context,
        _with_explicit_auth(options, auth),
        mode="stream",
        require_stream=True,
    )


async def complete(
    model: Model,
    context,
    options: CallOptions | None = None,
    *,
    auth: AuthCredential | None = None,
):
    event_stream = await _start_stream(
        model,
        context,
        _with_explicit_auth(options, auth),
        mode="complete",
        require_stream=False,
    )
    return await event_stream.result()


async def complete_structured(
    model: Model,
    context,
    output: StructuredOutputOptions | None = None,
    *,
    options: CallOptions | None = None,
    auth: AuthCredential | None = None,
) -> StructuredOutputResult:
    structured_output = output or get_structured_output_options(options)
    if structured_output is None:
        raise ValueError("complete_structured requires StructuredOutputOptions")
    call_options = with_structured_output_options(options, structured_output)
    message = await complete(model, context, call_options, auth=auth)
    return parse_structured_output(message, structured_output)


def _with_explicit_auth(
    options: CallOptions | None,
    auth: AuthCredential | None,
) -> CallOptions | None:
    if auth is None:
        return options
    if options is None:
        return CallOptions(auth=auth)
    if options.auth is not None:
        raise ValueError(
            "Pass request auth through either auth= or CallOptions.auth, not both"
        )
    return replace(options, auth=auth)
