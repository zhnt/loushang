from __future__ import annotations

import asyncio
import inspect
import math
import random
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast
from uuid import uuid4

from loushang.ai.errors import AIProviderProtocolError, AITimeoutError
from loushang.ai.event_stream import AssistantMessageEventStream, RawAssembler
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.options import (
    RetryOptions,
    get_idle_timeout_seconds,
    get_timeout_seconds,
)
from loushang.ai.provider.cancellation import is_signal_cancelled, wait_signal_cancelled
from loushang.ai.provider.errors import (
    normalize_provider_error,
    provider_error_info_from_raw,
    provider_error_part,
)
from loushang.ai.provider.protocol import ProviderRequest
from loushang.ai.trace import emit_trace

RawPartSource = Callable[[], AsyncIterator[RawPart] | Any]
Sleep = Callable[[float], Awaitable[object]]
Jitter = Callable[[], float]

_DEFAULT_MAX_RETRY_DELAY_SECONDS = 30.0
_INITIAL_RETRY_DELAY_SECONDS = 0.25
_PENDING_RETRY_BUFFER_MAX_PARTS = 256
_PENDING_RETRY_BUFFER_MAX_BYTES = 262_144
_VISIBLE_RAW_PART_TYPES = frozenset(
    {
        "text_delta",
        "thinking_delta",
        "thinking_signature_delta",
        "redacted_thinking",
        "tool_call_start",
        "tool_call_args_delta",
        "tool_call_done",
        "tool_call_thought_signature",
        "image_part",
    }
)
_TERMINAL_RAW_PART_TYPES = frozenset({"response_done", "response_error", "aborted"})


class _RuntimeCancelled(Exception):
    pass


class _AttemptDeadline:
    def __init__(self, timeout_seconds: float | int | None) -> None:
        self.expired = False
        self._task = asyncio.current_task()
        self._handle: asyncio.TimerHandle | None = None
        if timeout_seconds is not None:
            self._handle = asyncio.get_running_loop().call_later(
                float(timeout_seconds),
                self._expire,
            )

    def _expire(self) -> None:
        self.expired = True
        if self._task is not None:
            self._task.cancel()

    def cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()


def start_provider_runtime(
    raw_parts: RawPartSource,
    *,
    options,
    request: ProviderRequest,
    _sleep: Sleep = asyncio.sleep,
    _jitter: Jitter = random.random,
) -> AssistantMessageEventStream:
    model = request.model
    stream = AssistantMessageEventStream()
    call_id = uuid4().hex
    assembler = RawAssembler(
        stream=stream,
        api=model.api or "",
        provider=model.provider_id,
        endpoint=model.endpoint_id,
        model=model.id,
        pricing=model.pricing,
    )

    async def _run() -> None:
        signals = _cancellation_signals(options)
        cancellation_task = _create_cancellation_task(signals)
        if _signals_cancelled(signals):
            _emit_runtime_cancel_trace(
                options, request=request, model=model, call_id=call_id
            )
            await assembler.emit({"type": "aborted"})
            return
        try:
            max_attempts = _retry_max_attempts(options)
            attempt = 1
            while attempt <= max_attempts:
                deadline = _AttemptDeadline(get_timeout_seconds(options))
                pending: deque[RawPart] = deque()
                pending_bytes = 0
                visible_output_started = False
                raw_part_received = False
                retry_next_attempt = False
                source = None
                try:
                    _emit_runtime_request_trace(
                        options,
                        request=request,
                        model=model,
                        call_id=call_id,
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                    source = raw_parts()
                    if inspect.isawaitable(source):
                        source = await _await_or_cancel(source, cancellation_task)
                    while True:
                        try:
                            part = await _next_raw_part(
                                source,
                                cancellation_task,
                                idle_timeout_seconds=(
                                    get_idle_timeout_seconds(options)
                                    if raw_part_received
                                    else None
                                ),
                            )
                        except StopAsyncIteration:
                            break
                        raw_part_received = True

                        if _signals_cancelled(signals):
                            raise _RuntimeCancelled

                        if (
                            part["type"] == "response_error"
                            and not visible_output_started
                            and attempt < max_attempts
                            and _retryable_response_error_part(
                                part,
                                request=request,
                                model=model,
                            )
                        ):
                            deadline.cancel()
                            await _close_source(source)
                            source = None
                            await _sleep_before_retry(
                                options=options,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                retry_after_seconds=_retry_after_seconds_from_part(
                                    part
                                ),
                                reason=_retry_reason_from_part(part, request, model),
                                request=request,
                                model=model,
                                call_id=call_id,
                                sleep=_sleep,
                                jitter=_jitter,
                                cancellation_task=cancellation_task,
                            )
                            retry_next_attempt = True
                            break

                        if part["type"] in _VISIBLE_RAW_PART_TYPES:
                            await _flush_pending(assembler, pending)
                            pending_bytes = 0
                            visible_output_started = True
                            await assembler.emit(part)
                            continue

                        if (
                            visible_output_started
                            or part["type"] in _TERMINAL_RAW_PART_TYPES
                        ):
                            await _flush_pending(assembler, pending)
                            pending_bytes = 0
                            if part["type"] == "response_error":
                                _emit_runtime_error_trace(
                                    options,
                                    part=part,
                                    request=request,
                                    model=model,
                                    call_id=call_id,
                                )
                            await assembler.emit(part)
                            if part["type"] in _TERMINAL_RAW_PART_TYPES:
                                return
                            continue

                        pending_bytes = _append_pending_part(
                            pending,
                            pending_bytes,
                            part,
                            request=request,
                            model=model,
                        )

                    if retry_next_attempt:
                        attempt += 1
                        continue
                    await _flush_pending(assembler, pending)
                    error_part = _provider_error_part_for_request(
                        AIProviderProtocolError(
                            "provider stream ended before a terminal response event",
                            source=model.api or "",
                            provider=model.provider_id,
                            endpoint=model.endpoint_id,
                            model=_runtime_model_id(request=request, model=model),
                        ),
                        request=request,
                        model=model,
                    )
                    _emit_runtime_error_trace(
                        options,
                        part=error_part,
                        request=request,
                        model=model,
                        call_id=call_id,
                    )
                    await assembler.emit(error_part)
                    return
                except _RuntimeCancelled:
                    await _flush_pending(assembler, pending)
                    _emit_runtime_cancel_trace(
                        options, request=request, model=model, call_id=call_id
                    )
                    await assembler.emit({"type": "aborted"})
                    return
                except (Exception, asyncio.CancelledError) as caught:
                    if isinstance(caught, asyncio.CancelledError):
                        if not deadline.expired:
                            raise
                        error: Exception = AITimeoutError(
                            "Provider request timed out.",
                            source=model.api or "",
                            provider=model.provider_id,
                            endpoint=model.endpoint_id,
                            model=_runtime_model_id(request=request, model=model),
                        )
                    else:
                        error = caught
                    if _signals_cancelled(signals):
                        await _flush_pending(assembler, pending)
                        _emit_runtime_cancel_trace(
                            options,
                            request=request,
                            model=model,
                            call_id=call_id,
                        )
                        await assembler.emit({"type": "aborted"})
                        return
                    if (
                        not visible_output_started
                        and attempt < max_attempts
                        and _retryable_exception(error, source=model.api or "")
                    ):
                        deadline.cancel()
                        await _close_source(source)
                        source = None
                        await _sleep_before_retry(
                            options=options,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            retry_after_seconds=_retry_after_seconds_from_exception(
                                error
                            ),
                            reason=_retry_reason_from_exception(error, model.api or ""),
                            request=request,
                            model=model,
                            call_id=call_id,
                            sleep=_sleep,
                            jitter=_jitter,
                            cancellation_task=cancellation_task,
                        )
                        attempt += 1
                        continue
                    await _flush_pending(assembler, pending)
                    error_part = _provider_error_part_for_request(
                        error,
                        request=request,
                        model=model,
                    )
                    _emit_runtime_error_trace(
                        options,
                        part=error_part,
                        request=request,
                        model=model,
                        call_id=call_id,
                    )
                    await assembler.emit(error_part)
                    return
                finally:
                    deadline.cancel()
                    await _close_source(source)
        finally:
            await _cancel_task(cancellation_task)

    stream.attach_task(asyncio.create_task(_run()))
    return stream


async def _flush_pending(assembler: RawAssembler, pending: deque[RawPart]) -> None:
    while pending:
        await assembler.emit(pending.popleft())


def _append_pending_part(
    pending: deque[RawPart],
    pending_bytes: int,
    part: RawPart,
    *,
    request: ProviderRequest,
    model,
) -> int:
    part_bytes = _estimated_raw_part_bytes(part)
    next_bytes = pending_bytes + part_bytes
    if (
        len(pending) >= _PENDING_RETRY_BUFFER_MAX_PARTS
        or next_bytes > _PENDING_RETRY_BUFFER_MAX_BYTES
    ):
        raise AIProviderProtocolError(
            "Pre-visible provider buffer exceeded retry bounds.",
            source=model.api or "",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=_runtime_model_id(request=request, model=model),
            details={
                "maxParts": _PENDING_RETRY_BUFFER_MAX_PARTS,
                "maxBytes": _PENDING_RETRY_BUFFER_MAX_BYTES,
                "partCount": len(pending) + 1,
                "estimatedBytes": next_bytes,
            },
        )
    pending.append(part)
    return next_bytes


def _estimated_raw_part_bytes(part: RawPart) -> int:
    return _estimated_value_bytes(cast(Mapping[str, object], part))


def _estimated_value_bytes(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="replace"))
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, bool | int | float):
        return len(str(value))
    if isinstance(value, Mapping):
        return sum(
            _estimated_value_bytes(str(key)) + _estimated_value_bytes(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return sum(_estimated_value_bytes(item) for item in value)
    return len(str(value))


def _runtime_model_id(*, request: ProviderRequest, model) -> str | None:
    value = getattr(model, "id", None)
    if isinstance(value, str) and value:
        return value
    value = getattr(request.model, "id", None)
    if isinstance(value, str) and value:
        return value
    return None


def _runtime_trace_base(
    *,
    request: ProviderRequest,
    model,
    call_id: str,
) -> dict[str, object]:
    return {
        "callId": call_id,
        "api": request.model.api,
        "provider": request.model.provider_id,
        "endpoint": request.model.endpoint_id,
        "model": _runtime_model_id(request=request, model=model),
    }


def _provider_error_part_for_request(
    error: Exception,
    *,
    request: ProviderRequest,
    model,
) -> RawPart:
    part = dict(provider_error_part(error, source=request.model.api or ""))
    raw_info = part.get("error_info")
    if isinstance(raw_info, Mapping):
        info = dict(raw_info)
        if info.get("provider") is None:
            info["provider"] = request.model.provider_id
        if info.get("endpoint") is None:
            info["endpoint"] = request.model.endpoint_id
        if info.get("model") is None:
            info["model"] = _runtime_model_id(request=request, model=model)
        part["error_info"] = info
    return cast(RawPart, part)


def _emit_runtime_request_trace(
    options: object | None,
    *,
    request: ProviderRequest,
    model,
    call_id: str,
    attempt: int,
    max_attempts: int,
) -> None:
    event: dict[str, object] = {
        "type": "runtime:request",
        **_runtime_trace_base(request=request, model=model, call_id=call_id),
        "attempt": attempt,
        "maxAttempts": max_attempts,
    }
    event["upstreamModel"] = request.model.upstream_id or request.model.id
    emit_trace(options, event)


def _emit_runtime_error_trace(
    options: object | None,
    *,
    part: RawPart,
    request: ProviderRequest,
    model,
    call_id: str,
) -> None:
    try:
        error_info = provider_error_info_from_raw(
            cast(Mapping[str, object], part),
            source=request.model.api or "",
            provider=request.model.provider_id,
            endpoint=request.model.endpoint_id,
            model=getattr(model, "id", None),
        )
    except Exception:
        emit_trace(
            options,
            {
                "type": "runtime:error",
                **_runtime_trace_base(request=request, model=model, call_id=call_id),
                "reason": "provider",
            },
        )
        return
    event: dict[str, object] = {
        "type": "runtime:error",
        **_runtime_trace_base(request=request, model=model, call_id=call_id),
        "reason": error_info.code.value
        if hasattr(error_info.code, "value")
        else str(error_info.code),
        "retryable": error_info.retryable,
    }
    if error_info.status_code is not None:
        event["statusCode"] = error_info.status_code
    if error_info.request_id is not None:
        event["requestId"] = error_info.request_id
    details = error_info.details
    exception_type = details.get("exceptionType")
    if isinstance(exception_type, str) and exception_type:
        event["exceptionType"] = exception_type
    response_summary = cast(Mapping[str, object], part).get(
        "provider_response_summary"
    )
    if isinstance(response_summary, str) and response_summary:
        event["providerResponseSummary"] = response_summary
    emit_trace(options, event)


def _emit_runtime_cancel_trace(
    options: object | None,
    *,
    request: ProviderRequest,
    model,
    call_id: str,
) -> None:
    emit_trace(
        options,
        {
            "type": "runtime:cancel",
            **_runtime_trace_base(request=request, model=model, call_id=call_id),
            "reason": "cancelled",
        },
    )


def _cancellation_signals(options: object | None) -> tuple[object, ...]:
    if options is None:
        return ()
    signal = getattr(options, "cancellation", None)
    return (signal,) if signal is not None else ()


def _signals_cancelled(signals: tuple[object, ...]) -> bool:
    return any(is_signal_cancelled(signal) for signal in signals)


def _create_cancellation_task(
    signals: tuple[object, ...],
) -> asyncio.Task[None] | None:
    if not signals:
        return None
    return asyncio.create_task(_wait_any_signal_cancelled(signals))


async def _wait_any_signal_cancelled(signals: tuple[object, ...]) -> None:
    if _signals_cancelled(signals):
        return
    tasks = [asyncio.create_task(wait_signal_cancelled(signal)) for signal in signals]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            await task
        for task in pending:
            with suppress(asyncio.CancelledError):
                await task
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()


async def _await_or_cancel(awaitable, cancellation_task: asyncio.Task[None] | None):
    if cancellation_task is None:
        return await awaitable
    if cancellation_task.done():
        raise _RuntimeCancelled
    task = asyncio.ensure_future(awaitable)
    try:
        done, pending = await asyncio.wait(
            {task, cancellation_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    except BaseException:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise
    if cancellation_task in done:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise _RuntimeCancelled
    for pending_task in pending:
        if pending_task is not cancellation_task:
            pending_task.cancel()
    return await task


async def _next_raw_part(
    source,
    cancellation_task: asyncio.Task[None] | None,
    *,
    idle_timeout_seconds: float | int | None,
):
    iterator = source.__aiter__() if hasattr(source, "__aiter__") else source
    next_part = _await_or_cancel(iterator.__anext__(), cancellation_task)
    if idle_timeout_seconds is None:
        return await next_part
    return await asyncio.wait_for(next_part, timeout=float(idle_timeout_seconds))


async def _close_source(source) -> None:
    if source is None:
        return
    for name in ("aclose", "close"):
        close = getattr(source, name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return


async def _cancel_task(task: asyncio.Task[object] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _retry_max_attempts(options: object | None) -> int:
    if options is None:
        return 1
    retry = getattr(options, "retry", None)
    if isinstance(retry, RetryOptions):
        return retry.max_attempts
    return 1


def _retry_max_delay_seconds(options: object | None) -> float:
    if options is None:
        return _DEFAULT_MAX_RETRY_DELAY_SECONDS
    retry = getattr(options, "retry", None)
    if isinstance(retry, RetryOptions):
        return float(retry.max_delay_seconds)
    return _DEFAULT_MAX_RETRY_DELAY_SECONDS


def _retryable_exception(error: Exception, *, source: str) -> bool:
    return normalize_provider_error(error, source=source).info.retryable


def _retryable_response_error_part(
    part: RawPart,
    *,
    request: ProviderRequest,
    model,
) -> bool:
    try:
        error_info = provider_error_info_from_raw(
            cast(Mapping[str, object], part),
            source=request.model.api or "",
            provider=request.model.provider_id,
            endpoint=request.model.endpoint_id,
            model=getattr(model, "id", None),
        )
    except Exception:
        return False
    return error_info.retryable


async def _sleep_before_retry(
    *,
    options,
    attempt: int,
    max_attempts: int,
    retry_after_seconds: float | None,
    reason: dict[str, object],
    request: ProviderRequest,
    model,
    call_id: str,
    sleep: Sleep,
    jitter: Jitter,
    cancellation_task: asyncio.Task[None] | None,
) -> None:
    delay_seconds = _retry_delay_seconds(
        attempt=attempt,
        options=options,
        retry_after_seconds=retry_after_seconds,
        jitter=jitter,
    )
    emit_trace(
        options,
        {
            "type": "runtime:retry",
            **_runtime_trace_base(request=request, model=model, call_id=call_id),
            "attempt": attempt + 1,
            "maxAttempts": max_attempts,
            "delayMs": int(delay_seconds * 1000),
            **reason,
        },
    )
    if delay_seconds > 0:
        await _await_or_cancel(sleep(delay_seconds), cancellation_task)


def _retry_delay_seconds(
    *,
    attempt: int,
    options,
    retry_after_seconds: float | None,
    jitter: Jitter,
) -> float:
    max_delay = _retry_max_delay_seconds(options)
    if max_delay <= 0:
        return 0.0
    if retry_after_seconds is not None:
        return min(max_delay, retry_after_seconds)
    backoff = min(max_delay, _INITIAL_RETRY_DELAY_SECONDS * (2 ** max(0, attempt - 1)))
    jitter_ratio = min(1.0, max(0.0, float(jitter())))
    return min(max_delay, backoff + (backoff * 0.25 * jitter_ratio))


def _retry_after_seconds_from_exception(error: Exception) -> float | None:
    headers = getattr(error, "headers", None)
    if headers is None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
    return _retry_after_seconds_from_headers(headers)


def _retry_after_seconds_from_part(part: RawPart) -> float | None:
    for key in ("retryAfter", "retry_after"):
        value = cast(Mapping[str, object], part).get(key)
        if value is not None:
            return _parse_retry_after(value)
    return None


def _retry_after_seconds_from_headers(headers: object) -> float | None:
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "retry-after":
            return _parse_retry_after(value)
    return None


def _parse_retry_after(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _finite_retry_after_seconds(float(value))
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return _finite_retry_after_seconds(float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return _finite_retry_after_seconds((retry_at - datetime.now(UTC)).total_seconds())


def _finite_retry_after_seconds(value: float) -> float | None:
    if not math.isfinite(value):
        return None
    return max(0.0, value)


def _retry_reason_from_exception(error: Exception, source: str) -> dict[str, object]:
    info = normalize_provider_error(error, source=source).info
    reason: dict[str, object] = {
        "reason": info.code.value if hasattr(info.code, "value") else str(info.code),
    }
    if info.status_code is not None:
        reason["statusCode"] = info.status_code
    if info.request_id is not None:
        reason["requestId"] = info.request_id
    return reason


def _retry_reason_from_part(
    part: RawPart,
    request: ProviderRequest,
    model,
) -> dict[str, object]:
    try:
        info = provider_error_info_from_raw(
            cast(Mapping[str, object], part),
            source=request.model.api or "",
            provider=request.model.provider_id,
            endpoint=request.model.endpoint_id,
            model=getattr(model, "id", None),
        )
    except Exception:
        return {"reason": "provider"}
    reason: dict[str, object] = {
        "reason": info.code.value if hasattr(info.code, "value") else str(info.code),
    }
    if info.status_code is not None:
        reason["statusCode"] = info.status_code
    if info.request_id is not None:
        reason["requestId"] = info.request_id
    return reason


__all__ = ["RawPartSource", "start_provider_runtime"]
