from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Self

from loushang.ai.utils.redaction import is_header_container_key, is_sensitive_key
from loushang.foundation.json import JSONValue
from loushang.foundation.observability.projection import (
    project_diagnostic_mapping,
    project_diagnostic_value,
)

_REDACTED = "[redacted]"


class AIErrorCode(str, Enum):
    CONFIGURATION = "configuration"
    MODEL_NOT_FOUND = "model_not_found"
    AMBIGUOUS_MODEL = "ambiguous_model"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    AUTHENTICATION = "authentication"
    REQUEST_VALIDATION = "request_validation"
    REQUEST_TOO_LARGE = "request_too_large"
    TOOL_VALIDATION = "tool_validation"
    PROVIDER = "provider"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    CONTEXT_OVERFLOW = "context_overflow"
    PROVIDER_PROTOCOL = "provider_protocol"
    STREAM = "stream"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AIErrorInfo:
    code: AIErrorCode
    message: str
    source: str
    retryable: bool
    provider: str | None = None
    endpoint: str | None = None
    model: str | None = None
    status_code: int | None = None
    request_id: str | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, AIErrorCode):
            raise TypeError("AIErrorInfo.code must be AIErrorCode")
        details = project_diagnostic_mapping(self.details)
        object.__setattr__(self, "details", details)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "code": self.code.value,
            "message": self.message,
            "source": self.source,
            "retryable": self.retryable,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "statusCode": self.status_code,
            "requestId": self.request_id,
            "details": _redact_json_mapping(self.details),
        }


class AIError(Exception):
    default_code = AIErrorCode.PROVIDER
    default_source = "loushang.ai"
    default_retryable = False

    def __init__(
        self,
        message: str | AIErrorInfo,
        *,
        info: AIErrorInfo | None = None,
        code: AIErrorCode | None = None,
        source: str | None = None,
        retryable: bool | None = None,
        provider: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        status_code: int | None = None,
        request_id: str | None = None,
        details: Mapping[str, JSONValue] | None = None,
    ) -> None:
        if isinstance(message, AIErrorInfo):
            if info is not None:
                raise TypeError(
                    "AIError accepts either message info or info=, not both"
                )
            info = message
            message_text = info.message
        else:
            message_text = message
        if info is None:
            info = AIErrorInfo(
                code=code or self.default_code,
                message=message_text,
                source=source or self.default_source,
                retryable=self.default_retryable if retryable is None else retryable,
                provider=provider,
                endpoint=endpoint,
                model=model,
                status_code=status_code,
                request_id=request_id,
                details=details or {},
            )
        super().__init__(info.message)
        self.info = info

    def to_dict(self) -> dict[str, JSONValue]:
        return self.info.to_dict()

    @classmethod
    def from_info(cls, info: AIErrorInfo) -> Self:
        return cls(info)


class AIConfigurationError(AIError):
    default_code = AIErrorCode.CONFIGURATION


class ModelNotFoundError(AIConfigurationError):
    default_code = AIErrorCode.MODEL_NOT_FOUND


class AmbiguousModelError(AIConfigurationError):
    default_code = AIErrorCode.AMBIGUOUS_MODEL


class UnsupportedCapabilityError(AIConfigurationError):
    default_code = AIErrorCode.UNSUPPORTED_CAPABILITY


class AIAuthenticationError(AIError):
    default_code = AIErrorCode.AUTHENTICATION


class AIRequestValidationError(AIError):
    default_code = AIErrorCode.REQUEST_VALIDATION


class AIRequestTooLargeError(AIRequestValidationError):
    default_code = AIErrorCode.REQUEST_TOO_LARGE


class ToolValidationError(AIRequestValidationError):
    default_code = AIErrorCode.TOOL_VALIDATION


class AIProviderError(AIError):
    default_code = AIErrorCode.PROVIDER
    default_source = "provider"


class AIRateLimitError(AIProviderError):
    default_code = AIErrorCode.RATE_LIMIT
    default_retryable = True


class AITimeoutError(AIProviderError):
    default_code = AIErrorCode.TIMEOUT
    default_retryable = True


class AIServiceUnavailableError(AIProviderError):
    default_code = AIErrorCode.SERVICE_UNAVAILABLE
    default_retryable = True


class AIContextOverflowError(AIProviderError):
    default_code = AIErrorCode.CONTEXT_OVERFLOW


class AIProviderProtocolError(AIProviderError):
    default_code = AIErrorCode.PROVIDER_PROTOCOL


class AIStreamError(AIError):
    default_code = AIErrorCode.STREAM


class AICancelledError(AIError):
    default_code = AIErrorCode.CANCELLED


_ERROR_CLASS_BY_CODE: dict[AIErrorCode, type[AIError]] = {
    AIErrorCode.CONFIGURATION: AIConfigurationError,
    AIErrorCode.MODEL_NOT_FOUND: ModelNotFoundError,
    AIErrorCode.AMBIGUOUS_MODEL: AmbiguousModelError,
    AIErrorCode.UNSUPPORTED_CAPABILITY: UnsupportedCapabilityError,
    AIErrorCode.AUTHENTICATION: AIAuthenticationError,
    AIErrorCode.REQUEST_VALIDATION: AIRequestValidationError,
    AIErrorCode.REQUEST_TOO_LARGE: AIRequestTooLargeError,
    AIErrorCode.TOOL_VALIDATION: ToolValidationError,
    AIErrorCode.PROVIDER: AIProviderError,
    AIErrorCode.RATE_LIMIT: AIRateLimitError,
    AIErrorCode.TIMEOUT: AITimeoutError,
    AIErrorCode.SERVICE_UNAVAILABLE: AIServiceUnavailableError,
    AIErrorCode.CONTEXT_OVERFLOW: AIContextOverflowError,
    AIErrorCode.PROVIDER_PROTOCOL: AIProviderProtocolError,
    AIErrorCode.STREAM: AIStreamError,
    AIErrorCode.CANCELLED: AICancelledError,
}


def ai_error_from_info(info: AIErrorInfo) -> AIError:
    return _ERROR_CLASS_BY_CODE.get(info.code, AIError).from_info(info)


def ai_error_info_from_mapping(raw: Mapping[str, object]) -> AIErrorInfo:
    details = raw.get("details")
    return AIErrorInfo(
        code=AIErrorCode(_required_str(raw, "code")),
        message=_required_str(raw, "message"),
        source=_required_str(raw, "source"),
        retryable=bool(raw.get("retryable")),
        provider=_optional_str(raw.get("provider")),
        endpoint=_optional_str(raw.get("endpoint")),
        model=_optional_str(raw.get("model")),
        status_code=_http_status_code(raw.get("statusCode")),
        request_id=_optional_str(raw.get("requestId")),
        details=details if isinstance(details, Mapping) else {},
    )


def _redact_json_value(value: JSONValue, *, key: str | None = None) -> JSONValue:
    if key is not None and is_header_container_key(key) and isinstance(value, dict):
        return {item_key: _REDACTED for item_key in value}
    if key is not None and is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, dict):
        return {
            item_key: _redact_json_value(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    return project_diagnostic_value(value)


def _redact_json_mapping(value: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    return {key: _redact_json_value(item, key=key) for key, item in value.items()}


def _http_status_code(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        code = value
    elif isinstance(value, str) and value.isdecimal():
        code = int(value)
    else:
        return None
    if 100 <= code <= 599:
        return code
    return None


def _required_str(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"error_info.{key} must be a non-empty string")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "AIError",
    "AIErrorCode",
    "AIErrorInfo",
    "AIConfigurationError",
    "ModelNotFoundError",
    "AmbiguousModelError",
    "UnsupportedCapabilityError",
    "AIAuthenticationError",
    "AIRequestValidationError",
    "AIRequestTooLargeError",
    "ToolValidationError",
    "AIProviderError",
    "AIRateLimitError",
    "AITimeoutError",
    "AIServiceUnavailableError",
    "AIContextOverflowError",
    "AIProviderProtocolError",
    "AIStreamError",
    "AICancelledError",
    "ai_error_from_info",
    "ai_error_info_from_mapping",
]
