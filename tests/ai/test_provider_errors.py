from __future__ import annotations

import pytest

from loushang.ai import AIErrorCode
from loushang.ai.errors import (
    AIAuthenticationError,
    AIProviderProtocolError,
    AIRateLimitError,
    AIRequestTooLargeError,
)
from loushang.ai.provider.errors import (
    normalize_provider_error,
    provider_error_info_from_raw,
    provider_error_part,
    provider_error_part_from_raw,
    provider_response_summary,
)


class _HttpError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _HttpErrorWithHeaders(_HttpError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message, status_code)
        self.headers = {"x-request-id": "req_headers"}


class _HttpErrorWithBody(_HttpError):
    def __init__(self, body: object) -> None:
        super().__init__("unsafe exception text", 400)
        self.body = body


HttpxReadTimeout = type("ReadTimeout", (Exception,), {"__module__": "httpx"})
OpenAIAPITimeoutError = type(
    "APITimeoutError",
    (Exception,),
    {"__module__": "openai"},
)
AnthropicAPITimeoutError = type(
    "APITimeoutError",
    (Exception,),
    {"__module__": "anthropic"},
)


@pytest.mark.parametrize(
    ("status_code", "code", "retryable", "message"),
    [
        (401, AIErrorCode.AUTHENTICATION, False, "Provider authentication failed."),
        (403, AIErrorCode.AUTHENTICATION, False, "Provider authentication failed."),
        (408, AIErrorCode.TIMEOUT, True, "Provider request timed out."),
        (413, AIErrorCode.REQUEST_TOO_LARGE, False, "Provider request is too large."),
        (429, AIErrorCode.RATE_LIMIT, True, "Provider rate limit exceeded."),
        (500, AIErrorCode.SERVICE_UNAVAILABLE, True, "Provider service unavailable."),
        (503, AIErrorCode.SERVICE_UNAVAILABLE, True, "Provider service unavailable."),
    ],
)
def test_provider_error_part_maps_http_status_codes_to_error_info(
    status_code: int,
    code: AIErrorCode,
    retryable: bool,
    message: str,
) -> None:
    part = provider_error_part(
        _HttpError("provider failed", status_code), source="openai"
    )

    assert part["type"] == "response_error"
    assert part["message"] == message
    assert part["code"] == status_code
    assert part["error_info"]["code"] == code.value
    assert part["error_info"]["source"] == "openai"
    assert part["error_info"]["retryable"] is retryable
    assert part["error_info"]["statusCode"] == status_code


def test_provider_error_part_maps_timeout_without_http_status() -> None:
    part = provider_error_part(TimeoutError("connection timed out"), source="openai")

    assert part["type"] == "response_error"
    assert part["message"] == "Provider request timed out."
    assert "code" not in part
    assert part["error_info"]["code"] == "timeout"
    assert part["error_info"]["retryable"] is True


@pytest.mark.parametrize(
    "error",
    [
        HttpxReadTimeout("read timed out"),
        OpenAIAPITimeoutError("request timed out"),
        AnthropicAPITimeoutError("request timed out"),
    ],
)
def test_provider_error_part_maps_sdk_timeout_exceptions(error: Exception) -> None:
    part = provider_error_part(error, source="provider")

    assert part["type"] == "response_error"
    assert part["error_info"]["code"] == "timeout"
    assert part["error_info"]["retryable"] is True


def test_provider_error_part_omits_non_http_status_code() -> None:
    part = provider_error_part(_HttpError("grpc unavailable", 14), source="openai")

    assert part["type"] == "response_error"
    assert part["message"] == "Provider request failed."
    assert "code" not in part
    assert part["error_info"]["code"] == "provider"
    assert part["error_info"]["retryable"] is False


@pytest.mark.parametrize(
    ("raw_code", "code", "retryable"),
    [
        ("rate-limited", "rate_limit", True),
        ("request_timeout", "timeout", True),
        ("overloaded", "service_unavailable", True),
        ("invalid_api_key", "authentication", False),
        ("request_too_large", "request_too_large", False),
        ("context_length_exceeded", "context_overflow", False),
        ("unknown_error", "provider", False),
        (object(), "provider", False),
    ],
)
def test_provider_error_part_from_raw_maps_known_string_codes(
    raw_code: object,
    code: str,
    retryable: bool,
) -> None:
    part = provider_error_part_from_raw(
        "provider failed",
        code=raw_code,
        source="provider",
    )

    assert part["type"] == "response_error"
    assert "code" not in part
    assert part["error_info"]["code"] == code
    assert part["error_info"]["retryable"] is retryable


def test_normalize_provider_error_does_not_retain_raw_exception_text() -> None:
    original = _HttpError("Authorization: Bearer secret-token", 429)
    normalized = normalize_provider_error(original, source="openai")

    assert normalized.info.code is AIErrorCode.RATE_LIMIT
    assert normalized.info.retryable is True
    assert normalized.info.message == "Provider rate limit exceeded."
    assert normalized.__cause__ is None
    assert "secret-token" not in repr(normalized)


def test_normalize_provider_error_preserves_local_typed_validation_error() -> None:
    from loushang.ai.errors import AIRequestValidationError

    original = AIRequestValidationError(
        "Prepared Model Input exceeds the durable record limit.",
        source="loushang.harness.transcript",
        details={"limitBytes": 1_048_576},
    )

    normalized = normalize_provider_error(original, source="openai-responses")

    assert isinstance(normalized, AIRequestValidationError)
    assert normalized.info == original.info


def test_normalize_provider_error_preserves_request_id_from_headers() -> None:
    normalized = normalize_provider_error(
        _HttpErrorWithHeaders("rate limited", 429),
        source="openai",
    )

    assert normalized.info.request_id == "req_headers"


def test_provider_response_summary_keeps_only_diagnostic_fields_and_redacts() -> None:
    error = _HttpErrorWithBody(
        {
            "error": {
                "type": "invalid_request_error",
                "message": "max_tokens is too large; Bearer secret-token",
                "api_key": "sk-secret",
            },
            "request": {"prompt": "private user prompt"},
        }
    )

    summary = provider_response_summary(error)

    assert summary == (
        '{"error":{"type":"invalid_request_error","message":'
        '"max_tokens is too large; Bearer [REDACTED]"}}'
    )
    assert "sk-secret" not in summary
    assert "private user prompt" not in summary


def test_normalized_provider_error_keeps_only_structured_body_identity() -> None:
    normalized = normalize_provider_error(
        _HttpErrorWithBody(
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "request_too_large",
                    "message": "private prompt and Bearer secret-token",
                },
                "request": {"prompt": "private user prompt"},
            }
        ),
        source="openai",
    )

    assert normalized.info.details == {
        "exceptionType": "_HttpErrorWithBody",
        "providerErrorType": "invalid_request_error",
        "providerErrorCode": "request_too_large",
    }
    assert isinstance(normalized, AIRequestTooLargeError)
    assert normalized.info.code is AIErrorCode.REQUEST_TOO_LARGE
    assert normalized.info.message == "Provider request is too large."
    assert "private prompt" not in repr(normalized.info.details)
    assert "secret-token" not in repr(normalized.info.details)


def test_raw_generic_http_failure_uses_safe_provider_capacity_identity() -> None:
    info = provider_error_info_from_raw(
        {
            "type": "response_error",
            "code": 400,
            "error_info": {
                "code": "provider",
                "message": "unsafe",
                "source": "custom-provider",
                "retryable": False,
                "statusCode": 400,
                "details": {
                    "providerErrorType": "invalid_request_error",
                    "providerErrorCode": "request_too_large",
                    "estimatedWireBytes": 900_000,
                },
            },
        },
        source="custom-provider",
    )

    assert info.code is AIErrorCode.REQUEST_TOO_LARGE
    assert info.retryable is False
    assert info.message == "Provider request is too large."
    assert info.details == {
        "providerErrorType": "invalid_request_error",
        "providerErrorCode": "request_too_large",
        "estimatedWireBytes": 900_000,
    }


def test_provider_response_summary_is_bounded_for_plain_text() -> None:
    error = _HttpErrorWithBody("token=secret " + ("x" * 800))

    summary = provider_response_summary(error)

    assert summary is not None
    assert len(summary) == 512
    assert summary.endswith("…")
    assert "secret" not in summary


def test_existing_authentication_error_is_forced_non_retryable() -> None:
    normalized = normalize_provider_error(
        AIAuthenticationError(
            "unsafe",
            retryable=True,
            status_code=401,
        )
    )

    assert normalized.info.code is AIErrorCode.AUTHENTICATION
    assert normalized.info.retryable is False
    assert normalized.info.message == "Provider authentication failed."


def test_existing_non_authentication_retry_policy_is_preserved() -> None:
    normalized = normalize_provider_error(
        AIRateLimitError(
            "unsafe",
            retryable=False,
            status_code=429,
        )
    )

    assert normalized.info.code is AIErrorCode.RATE_LIMIT
    assert normalized.info.retryable is False
    assert normalized.info.message == "Provider rate limit exceeded."


@pytest.mark.parametrize("status_code", [401, 403])
def test_raw_auth_error_info_cannot_override_authentication_invariants(
    status_code: int,
) -> None:
    info = provider_error_info_from_raw(
        {
            "type": "response_error",
            "code": status_code,
            "message": "Authorization: Bearer secret-token",
            "error_info": {
                "code": "service_unavailable",
                "message": "Authorization: Bearer secret-token",
                "source": "custom-provider",
                "retryable": True,
                "statusCode": status_code,
                "details": {"headers": {"X-Custom": "secret-token"}},
            },
        },
        source="custom-provider",
    )

    assert info.code is AIErrorCode.AUTHENTICATION
    assert info.retryable is False
    assert info.message == "Provider authentication failed."
    assert info.details == {}


def test_raw_non_authentication_retry_policy_is_preserved() -> None:
    info = provider_error_info_from_raw(
        {
            "type": "response_error",
            "code": 429,
            "message": "unsafe",
            "error_info": {
                "code": "rate_limit",
                "message": "unsafe",
                "source": "custom-provider",
                "retryable": False,
                "statusCode": 429,
            },
        },
        source="custom-provider",
    )

    assert info.code is AIErrorCode.RATE_LIMIT
    assert info.retryable is False


def test_raw_error_call_context_overrides_conflicting_route_identity() -> None:
    info = provider_error_info_from_raw(
        {
            "type": "response_error",
            "error_info": {
                "code": "provider",
                "message": "unsafe",
                "source": "wrong-api",
                "retryable": False,
                "provider": "wrong-provider",
                "endpoint": "wrong-endpoint",
                "model": "wrong-model",
            },
        },
        source="openai-responses",
        provider="openai",
        endpoint="actual-endpoint",
        model="gpt-test",
    )

    assert info.source == "openai-responses"
    assert info.provider == "openai"
    assert info.endpoint == "actual-endpoint"
    assert info.model == "gpt-test"


def test_outer_http_status_is_the_authoritative_error_classification() -> None:
    info = provider_error_info_from_raw(
        {
            "type": "response_error",
            "code": 429,
            "error_info": {
                "code": "authentication",
                "message": "unsafe",
                "source": "custom-provider",
                "retryable": False,
                "statusCode": 429,
            },
        },
        source="custom-provider",
    )

    assert info.code is AIErrorCode.RATE_LIMIT
    assert info.retryable is False


def test_provider_protocol_error_only_keeps_safe_numeric_details() -> None:
    normalized = normalize_provider_error(
        AIProviderProtocolError(
            "unsafe",
            details={
                "maxParts": 2,
                "partCount": 3,
                "upstreamPayload": "secret-payload",
            },
        )
    )

    assert isinstance(normalized, AIProviderProtocolError)
    assert normalized.info.details == {"maxParts": 2, "partCount": 3}
    assert "secret-payload" not in repr(normalized.to_dict())
