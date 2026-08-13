from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from loushang.ai.errors import (
    AIAuthenticationError,
    AIError,
    AIErrorCode,
    AIErrorInfo,
    AIProviderError,
    AIRateLimitError,
    AIServiceUnavailableError,
    AITimeoutError,
    ai_error_from_info,
    ai_error_info_from_mapping,
)
from loushang.foundation.json import JSONValue

if TYPE_CHECKING:
    from loushang.ai.event_stream.raw_parts import RawPart, ResponseErrorPart


class ProviderErrorInfo(TypedDict):
    message: str
    code: NotRequired[int]
    error_info: NotRequired[dict[str, JSONValue]]


_ERROR_CLASS_BY_CODE: dict[
    AIErrorCode, type[AIProviderError | AIAuthenticationError]
] = {
    AIErrorCode.AUTHENTICATION: AIAuthenticationError,
    AIErrorCode.RATE_LIMIT: AIRateLimitError,
    AIErrorCode.TIMEOUT: AITimeoutError,
    AIErrorCode.SERVICE_UNAVAILABLE: AIServiceUnavailableError,
    AIErrorCode.PROVIDER: AIProviderError,
}

_PROVIDER_RESPONSE_SUMMARY_MAX_CHARS = 512
_PROVIDER_DIAGNOSTIC_KEYS = frozenset({"code", "detail", "error", "message", "type"})
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|token)\b"
    r"(\s*[:=]\s*)([^\s,;}]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;}]+")


def classify_provider_error(
    error: Exception,
    *,
    source: str = "provider",
) -> ProviderErrorInfo:
    normalized = normalize_provider_error(error, source=source)
    info: ProviderErrorInfo = {
        "message": normalized.info.message,
        "error_info": normalized.info.to_dict(),
    }
    status_code = _http_status_code(getattr(error, "status_code", None))
    if status_code is None:
        status_code = _http_status_code(getattr(error, "status", None))
    if status_code is not None:
        info["code"] = status_code
    return info


def provider_error_part(
    error: Exception,
    *,
    source: str = "provider",
) -> "RawPart":
    info = classify_provider_error(error, source=source)
    part: dict[str, object] = {"type": "response_error", **info}
    response_summary = provider_response_summary(error)
    if response_summary is not None:
        part["provider_response_summary"] = response_summary
    return cast("RawPart", part)


def provider_response_summary(error: Exception) -> str | None:
    """Return a bounded, redacted provider response summary for diagnostics only."""
    body = getattr(error, "body", None)
    if body is None:
        response = getattr(error, "response", None)
        body = getattr(response, "text", None)
    if body is None:
        return None
    summarized = _summarize_provider_body(body)
    if not summarized:
        return None
    return _truncate_diagnostic(summarized)


def provider_error_part_from_raw(
    message: object,
    *,
    code: object = None,
    source: str = "provider",
) -> "RawPart":
    del message
    status_code = _http_status_code(code)
    error_code = _provider_error_code_from_raw(code, status_code)
    info = AIErrorInfo(
        code=error_code,
        message=_public_provider_error_message(error_code),
        source=source,
        retryable=_is_retryable_provider_error(error_code),
        status_code=status_code,
        details=_raw_code_details(code, error_code, status_code),
    )
    info = _canonicalize_provider_error_info(info)
    part = cast(
        "ResponseErrorPart",
        {
            "type": "response_error",
            "message": info.message,
            "error_info": info.to_dict(),
        },
    )
    if status_code is not None:
        part["code"] = status_code
    return cast("RawPart", part)


def normalize_provider_error(
    error: Exception,
    *,
    source: str = "provider",
) -> AIError:
    if isinstance(error, AIError):
        info = _canonicalize_provider_error_info(error.info)
        return ai_error_from_info(info)
    status_code = _provider_status_code(error)
    code = _provider_error_code(error, status_code)
    error_type = _ERROR_CLASS_BY_CODE.get(code, AIProviderError)
    info = AIErrorInfo(
        code=code,
        message=_public_provider_error_message(code),
        source=source,
        retryable=_is_retryable_provider_error(code),
        status_code=status_code,
        request_id=_provider_request_id(error),
        details={
            "exceptionType": error.__class__.__name__,
            **_raw_code_details(getattr(error, "code", None), code, status_code),
        },
    )
    return error_type(_canonicalize_provider_error_info(info))


def provider_error_info_from_raw(
    part: Mapping[str, object],
    *,
    source: str,
    provider: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
) -> AIErrorInfo:
    outer_status_code = _http_status_code(part.get("code"))
    raw_info = part.get("error_info")
    if isinstance(raw_info, Mapping):
        parsed = ai_error_info_from_mapping(raw_info)
        canonical = _canonicalize_provider_error_info(
            parsed,
            status_code=outer_status_code,
        )
        return replace(
            canonical,
            source=source,
            provider=provider if provider is not None else canonical.provider,
            endpoint=endpoint if endpoint is not None else canonical.endpoint,
            model=model if model is not None else canonical.model,
            details=canonical.details,
        )
    code = _provider_error_code_from_raw(part.get("code"), outer_status_code)
    info = AIErrorInfo(
        code=code,
        message=_public_provider_error_message(code),
        source=source,
        retryable=_is_retryable_provider_error(code),
        provider=provider,
        endpoint=endpoint,
        model=model,
        status_code=outer_status_code,
        details=_raw_code_details(part.get("code"), code, outer_status_code),
    )
    return _canonicalize_provider_error_info(info)


def _canonicalize_provider_error_info(
    info: AIErrorInfo,
    *,
    status_code: int | None = None,
) -> AIErrorInfo:
    resolved_status_code = info.status_code if status_code is None else status_code
    code = cast(AIErrorCode, info.code)
    if resolved_status_code is not None:
        code = _provider_error_code_from_status(resolved_status_code)
    is_authentication_error = (
        resolved_status_code in {401, 403} or code is AIErrorCode.AUTHENTICATION
    )
    if is_authentication_error:
        code = AIErrorCode.AUTHENTICATION
    retryable = False if is_authentication_error else info.retryable
    return replace(
        info,
        code=code,
        message=_public_provider_error_message(code),
        retryable=retryable,
        status_code=resolved_status_code,
        details=_safe_provider_error_details(code, info.details),
    )


def _safe_provider_error_details(
    code: AIErrorCode,
    details: Mapping[str, JSONValue],
) -> dict[str, JSONValue]:
    safe: dict[str, JSONValue] = {}
    exception_type = details.get("exceptionType")
    if isinstance(exception_type, str) and exception_type:
        safe["exceptionType"] = exception_type
    raw_code = details.get("rawCode")
    if isinstance(raw_code, str) and raw_code:
        safe["rawCode"] = raw_code
    if code is not AIErrorCode.PROVIDER_PROTOCOL:
        return safe
    for key in ("maxParts", "maxBytes", "partCount", "estimatedBytes"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            safe[key] = value
    return safe


def _raw_code_details(
    raw_code: object,
    code: AIErrorCode,
    status_code: int | None,
) -> dict[str, JSONValue]:
    if status_code is not None or code is not AIErrorCode.PROVIDER:
        return {}
    if isinstance(raw_code, str) and raw_code.strip():
        return {"rawCode": raw_code}
    return {}


def _public_provider_error_message(code: AIErrorCode) -> str:
    if code is AIErrorCode.AUTHENTICATION:
        return "Provider authentication failed."
    if code is AIErrorCode.RATE_LIMIT:
        return "Provider rate limit exceeded."
    if code is AIErrorCode.TIMEOUT:
        return "Provider request timed out."
    if code is AIErrorCode.SERVICE_UNAVAILABLE:
        return "Provider service unavailable."
    if code is AIErrorCode.PROVIDER_PROTOCOL:
        return "provider stream ended before a terminal response event"
    return "Provider request failed."


def _http_status_code(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        code = value
    elif isinstance(value, str) and value.isdecimal():
        code = int(value)
    else:
        return None
    if is_http_status_code(code):
        return code
    return None


def is_http_status_code(value: object) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599
    )


def _provider_status_code(error: Exception) -> int | None:
    status_code = _http_status_code(getattr(error, "status_code", None))
    if status_code is None:
        status_code = _http_status_code(getattr(error, "status", None))
    return status_code


def _provider_request_id(error: Exception) -> str | None:
    for name in (
        "request_id",
        "requestId",
        "x_request_id",
        "x_requestid",
    ):
        value = getattr(error, name, None)
        if isinstance(value, str) and value:
            return value
    headers = getattr(error, "headers", None)
    request_id = _request_id_from_headers(headers)
    if request_id is not None:
        return request_id
    response = getattr(error, "response", None)
    return _request_id_from_headers(getattr(response, "headers", None))


def _request_id_from_headers(headers: object) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            continue
        if key.lower() in {
            "x-request-id",
            "request-id",
            "x-ms-request-id",
            "x-amzn-requestid",
        }:
            return value
    return None


def _summarize_provider_body(body: object) -> str | None:
    if isinstance(body, str):
        text = body.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return _redact_diagnostic_text(text)
        return _summarize_provider_body(parsed)
    if isinstance(body, Mapping):
        safe = _safe_provider_diagnostic_mapping(body)
        if not safe:
            return None
        return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    if isinstance(body, list):
        safe_items = [
            item
            for value in body[:10]
            if (item := _safe_provider_diagnostic_value(value)) is not None
        ]
        if not safe_items:
            return None
        return json.dumps(safe_items, ensure_ascii=False, separators=(",", ":"))
    return None


def _safe_provider_diagnostic_mapping(
    value: Mapping[object, object],
) -> dict[str, JSONValue]:
    safe: dict[str, JSONValue] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip()
        if key.lower() not in _PROVIDER_DIAGNOSTIC_KEYS:
            continue
        item = _safe_provider_diagnostic_value(raw_value)
        if item is not None:
            safe[key] = item
    return safe


def _safe_provider_diagnostic_value(value: object) -> JSONValue | None:
    if isinstance(value, str):
        return _truncate_diagnostic(_redact_diagnostic_text(value))
    if value is None or isinstance(value, bool | int | float):
        return cast(JSONValue, value)
    if isinstance(value, Mapping):
        safe = _safe_provider_diagnostic_mapping(value)
        return safe or None
    if isinstance(value, list):
        safe_items: list[JSONValue] = []
        for nested in value[:10]:
            item = _safe_provider_diagnostic_value(nested)
            if item is not None:
                safe_items.append(item)
        return safe_items or None
    return None


def _redact_diagnostic_text(value: str) -> str:
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    return _SENSITIVE_KEY_PATTERN.sub(r"\1\2[REDACTED]", redacted)


def _truncate_diagnostic(value: str) -> str:
    if len(value) <= _PROVIDER_RESPONSE_SUMMARY_MAX_CHARS:
        return value
    return value[: _PROVIDER_RESPONSE_SUMMARY_MAX_CHARS - 1] + "…"


def _provider_error_code(error: Exception, status_code: int | None) -> AIErrorCode:
    if _is_timeout_exception(error):
        return AIErrorCode.TIMEOUT
    return _provider_error_code_from_status(status_code)


def _is_timeout_exception(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True
    for cls in type(error).__mro__:
        module = getattr(cls, "__module__", "")
        name = getattr(cls, "__name__", "")
        if name in {
            "APITimeoutError",
            "ConnectTimeout",
            "PoolTimeout",
            "ReadTimeout",
            "TimeoutException",
            "WriteTimeout",
        } and module.startswith(("anthropic", "httpcore", "httpx", "openai")):
            return True
    return False


def _provider_error_code_from_status(status_code: int | None) -> AIErrorCode:
    if status_code in {401, 403}:
        return AIErrorCode.AUTHENTICATION
    if status_code == 408:
        return AIErrorCode.TIMEOUT
    if status_code == 429:
        return AIErrorCode.RATE_LIMIT
    if status_code is not None and 500 <= status_code <= 599:
        return AIErrorCode.SERVICE_UNAVAILABLE
    return AIErrorCode.PROVIDER


def _provider_error_code_from_raw(
    raw_code: object,
    status_code: int | None,
) -> AIErrorCode:
    if status_code is not None:
        return _provider_error_code_from_status(status_code)
    if not isinstance(raw_code, str):
        return AIErrorCode.PROVIDER
    normalized = raw_code.strip().lower().replace("-", "_")
    if normalized in {"rate_limit", "rate_limited", "too_many_requests"}:
        return AIErrorCode.RATE_LIMIT
    if normalized in {"timeout", "timed_out", "request_timeout"}:
        return AIErrorCode.TIMEOUT
    if normalized in {
        "server_error",
        "service_unavailable",
        "temporarily_unavailable",
        "overloaded",
        "unavailable",
    }:
        return AIErrorCode.SERVICE_UNAVAILABLE
    if normalized in {"authentication", "authentication_error", "invalid_api_key"}:
        return AIErrorCode.AUTHENTICATION
    return AIErrorCode.PROVIDER


def _is_retryable_provider_error(code: AIErrorCode) -> bool:
    return code in {
        AIErrorCode.RATE_LIMIT,
        AIErrorCode.TIMEOUT,
        AIErrorCode.SERVICE_UNAVAILABLE,
    }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
