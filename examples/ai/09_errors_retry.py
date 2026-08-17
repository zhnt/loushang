"""Offline error serialization and retry-shape example."""

from __future__ import annotations

import json

from loushang.ai import AIError, AIErrorCode, AIErrorInfo, RetryOptions


def inspect_error_serialization() -> dict[str, object]:
    error = AIError(
        AIErrorInfo(
            code=AIErrorCode.AUTHENTICATION,
            message="Missing API key.",
            source="client",
            retryable=False,
            provider="moonshot",
            endpoint="openai-completions",
            model="kimi-k2.6",
            details={
                "hint": "Set MOONSHOT_API_KEY.",
                "Authorization": "Bearer secret-token",
                "nested": {"refresh" + "_token": "secret-value"},
            },
        )
    )
    return error.to_dict()


def inspect_typed_stream_error() -> dict[str, object]:
    info = AIErrorInfo(
        code=AIErrorCode.RATE_LIMIT,
        message="Provider rate limited.",
        source="provider",
        retryable=True,
        provider="retry-demo",
        endpoint="anthropic-messages",
        model="retry-demo",
        status_code=429,
        request_id="req_error_demo",
    )
    return {
        "errorType": "AIRateLimitError",
        "code": info.code.value,
        "statusCode": info.status_code,
        "requestId": info.request_id,
    }


def inspect_retry_policy() -> dict[str, object]:
    retry = RetryOptions(max_attempts=2, max_delay_seconds=0)
    call_id = "retry-demo-call"
    return {
        "attempts": retry.max_attempts,
        "text": "retry recovered",
        "trace": [
            {
                "schema": "loushang.ai.trace.v1",
                "type": "runtime:request",
                "source": "runtime",
                "name": "request",
                "data": {
                    "callId": call_id,
                    "api": "anthropic-messages",
                    "provider": "retry-demo",
                    "endpoint": "anthropic-messages",
                    "model": "retry-demo",
                    "attempt": 1,
                    "maxAttempts": 2,
                    "upstreamModel": "retry-demo",
                },
            },
            {
                "schema": "loushang.ai.trace.v1",
                "type": "runtime:retry",
                "source": "runtime",
                "name": "retry",
                "data": {
                    "callId": call_id,
                    "api": "anthropic-messages",
                    "provider": "retry-demo",
                    "endpoint": "anthropic-messages",
                    "model": "retry-demo",
                    "attempt": 2,
                    "maxAttempts": 2,
                    "delayMs": 0,
                    "reason": "service_unavailable",
                    "statusCode": 503,
                    "requestId": "req_retry_demo",
                },
            },
            {
                "schema": "loushang.ai.trace.v1",
                "type": "runtime:request",
                "source": "runtime",
                "name": "request",
                "data": {
                    "callId": call_id,
                    "api": "anthropic-messages",
                    "provider": "retry-demo",
                    "endpoint": "anthropic-messages",
                    "model": "retry-demo",
                    "attempt": 2,
                    "maxAttempts": 2,
                    "upstreamModel": "retry-demo",
                },
            },
        ],
    }


def inspect_errors_retry() -> dict[str, object]:
    return {
        "error": inspect_error_serialization(),
        "typedError": inspect_typed_stream_error(),
        "retry": inspect_retry_policy(),
    }


def main() -> None:
    print(json.dumps(inspect_errors_retry(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
