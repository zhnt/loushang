from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast, runtime_checkable
from uuid import uuid4

from loushang.ai.errors import AIRequestTooLargeError
from loushang.ai.json_codec import deserialize_usage, serialize_usage
from loushang.ai.types import AssistantMessage, StopReason, Usage
from loushang.foundation.json import JSONValue, require_json_mapping

if TYPE_CHECKING:
    from loushang.ai.event_stream.raw_parts import RawPart
    from loushang.ai.provider.protocol import ProviderRequest

FrozenJSONPrimitive: TypeAlias = str | int | float | bool | None
FrozenJSONValue: TypeAlias = (
    FrozenJSONPrimitive
    | tuple["FrozenJSONValue", ...]
    | Mapping[str, "FrozenJSONValue"]
)

PREPARED_MODEL_REQUEST_SCHEMA_VERSION = 1
PREPARED_MODEL_CALL_OUTCOME_SCHEMA_VERSION = 1
PreparedModelCallDisposition: TypeAlias = Literal[
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class PreparedRequestMetrics:
    """Safe capacity measurements derived from one frozen Provider request."""

    canonical_bytes: int
    estimated_wire_bytes: int | None
    message_bytes: int | None
    message_count: int
    image_bytes: int
    tool_schema_bytes: int
    estimated_input_tokens: int | None

    def __post_init__(self) -> None:
        for name in (
            "canonical_bytes",
            "message_count",
            "image_bytes",
            "tool_schema_bytes",
        ):
            _require_non_negative_int(getattr(self, name), name=name)
        for name in (
            "estimated_wire_bytes",
            "message_bytes",
            "estimated_input_tokens",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_non_negative_int(value, name=name)


@dataclass(frozen=True, slots=True)
class PreparedRequestLimits:
    """Optional explicit limits; unknown limits never reject a request."""

    max_canonical_bytes: int | None = None
    max_estimated_wire_bytes: int | None = None
    max_message_count: int | None = None
    max_image_bytes: int | None = None
    max_tool_schema_bytes: int | None = None
    max_estimated_input_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_canonical_bytes",
            "max_estimated_wire_bytes",
            "max_message_count",
            "max_image_bytes",
            "max_tool_schema_bytes",
            "max_estimated_input_tokens",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_positive_int(value, name=name)


@dataclass(frozen=True, slots=True)
class PreparedModelCallOutcome:
    """Content-free terminal result for one logical Provider invocation."""

    invocation_id: str
    disposition: PreparedModelCallDisposition
    stop_reason: StopReason
    usage: Usage
    error_info: Mapping[str, FrozenJSONValue] | None = field(
        default=None,
        repr=False,
    )
    schema_version: int = PREPARED_MODEL_CALL_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError(
                "PreparedModelCallOutcome.invocation_id must be non-empty"
            )
        if self.schema_version != PREPARED_MODEL_CALL_OUTCOME_SCHEMA_VERSION:
            raise ValueError(
                "unsupported PreparedModelCallOutcome schema version: "
                f"{self.schema_version}"
            )
        expected_disposition: PreparedModelCallDisposition
        if self.stop_reason == "error":
            expected_disposition = "failed"
        elif self.stop_reason == "aborted":
            expected_disposition = "cancelled"
        elif self.stop_reason in {"stop", "length", "toolUse"}:
            expected_disposition = "completed"
        else:
            raise ValueError(
                f"unsupported PreparedModelCallOutcome stop reason: {self.stop_reason}"
            )
        if self.disposition != expected_disposition:
            raise ValueError(
                "PreparedModelCallOutcome disposition does not match stop reason"
            )
        if not isinstance(self.usage, Usage):
            raise TypeError("PreparedModelCallOutcome.usage must be Usage")
        for name in ("input", "output", "cache_read", "cache_write", "total_tokens"):
            value = getattr(self.usage, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"PreparedModelCallOutcome.usage.{name} must be non-negative"
                )
        canonical_usage = deserialize_usage(serialize_usage(self.usage))
        if canonical_usage != self.usage:
            raise ValueError(
                "PreparedModelCallOutcome.usage cost must be finite and non-negative"
            )
        object.__setattr__(self, "usage", canonical_usage)
        if self.error_info is None:
            if self.disposition == "failed":
                raise ValueError("failed PreparedModelCallOutcome requires error info")
            return
        if self.disposition != "failed":
            raise ValueError(
                "non-failed PreparedModelCallOutcome cannot contain error info"
            )
        projected = require_json_mapping(
            self.error_info,
            name="prepared model call outcome error info",
        )
        object.__setattr__(self, "error_info", _freeze_json(projected))

    @classmethod
    def from_assistant_message(
        cls,
        invocation_id: str,
        message: AssistantMessage,
    ) -> PreparedModelCallOutcome:
        if not isinstance(message, AssistantMessage):
            raise TypeError("PreparedModelCallOutcome requires AssistantMessage")
        disposition: PreparedModelCallDisposition
        if message.stop_reason == "error":
            disposition = "failed"
        elif message.stop_reason == "aborted":
            disposition = "cancelled"
        else:
            disposition = "completed"
        return cls(
            invocation_id=invocation_id,
            disposition=disposition,
            stop_reason=message.stop_reason,
            usage=message.usage,
            error_info=cast(
                Mapping[str, FrozenJSONValue] | None,
                message.error_info,
            ),
        )


@dataclass(frozen=True, slots=True)
class PreparedModelRequest:
    """Immutable, provider-facing model payload committed before transport."""

    invocation_id: str
    attempt: int
    provider_id: str
    endpoint_id: str
    api: str
    model_id: str
    mode: str
    payload: Mapping[str, FrozenJSONValue] = field(repr=False)
    model_visible_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    estimated_wire_bytes: int | None = field(default=None, repr=False)
    estimated_input_tokens: int | None = field(default=None, repr=False)
    schema_version: int = PREPARED_MODEL_REQUEST_SCHEMA_VERSION
    canonical_payload: str = field(init=False, repr=False)
    payload_hash: str = field(init=False)
    metrics: PreparedRequestMetrics = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "invocation_id",
            "provider_id",
            "endpoint_id",
            "api",
            "model_id",
            "mode",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"PreparedModelRequest.{name} must be non-empty")
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise ValueError("PreparedModelRequest.attempt must be a positive integer")
        if self.schema_version != PREPARED_MODEL_REQUEST_SCHEMA_VERSION:
            raise ValueError(
                "unsupported PreparedModelRequest schema version: "
                f"{self.schema_version}"
            )

        projected = _project_payload(self.payload)
        model_visible_headers = _project_model_visible_headers(
            self.model_visible_headers
        )
        canonical_payload = json.dumps(
            {
                "model_visible_headers": model_visible_headers,
                "payload": projected,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        object.__setattr__(self, "payload", _freeze_json(projected))
        object.__setattr__(
            self,
            "model_visible_headers",
            MappingProxyType(model_visible_headers),
        )
        object.__setattr__(self, "canonical_payload", canonical_payload)
        object.__setattr__(
            self,
            "metrics",
            _measure_prepared_request(
                canonical_payload=canonical_payload,
                payload=projected,
                estimated_wire_bytes=self.estimated_wire_bytes,
                estimated_input_tokens=self.estimated_input_tokens,
            ),
        )
        object.__setattr__(
            self,
            "payload_hash",
            "sha256:"
            + hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
        )

    @classmethod
    def from_provider_request(
        cls,
        request: ProviderRequest,
        *,
        payload: Mapping[str, object],
        model_visible_headers: Mapping[str, str] | None = None,
        estimated_wire_bytes: int | None = None,
        estimated_input_tokens: int | None = None,
    ) -> PreparedModelRequest:
        model = request.model
        return cls(
            invocation_id=request.invocation_id or uuid4().hex,
            attempt=request.attempt,
            provider_id=model.provider_id,
            endpoint_id=model.endpoint_id,
            api=model.api or "",
            model_id=model.id,
            mode=request.mode,
            payload=cast(Mapping[str, FrozenJSONValue], payload),
            model_visible_headers=model_visible_headers or {},
            estimated_wire_bytes=estimated_wire_bytes,
            estimated_input_tokens=estimated_input_tokens,
        )

    def payload_for_transport(self) -> dict[str, JSONValue]:
        """Return a fresh transport object without reordering adapter mappings."""

        digest = "sha256:" + hashlib.sha256(
            self.canonical_payload.encode("utf-8")
        ).hexdigest()
        if digest != self.payload_hash:
            raise RuntimeError("prepared model request payload hash mismatch")
        return _project_payload(self.payload)

    def model_visible_headers_for_transport(self) -> dict[str, str]:
        return dict(self.model_visible_headers)


@runtime_checkable
class PreparedRequestCommitter(Protocol):
    async def commit_prepared_request(self, request: PreparedModelRequest) -> None: ...


@runtime_checkable
class PreparedModelCallOutcomeRecorder(Protocol):
    async def record_model_call_outcome(
        self,
        outcome: PreparedModelCallOutcome,
    ) -> None: ...


@runtime_checkable
class PreparedRequestAdapter(Protocol):
    api: str

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest: ...

    def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[RawPart]: ...

    def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]: ...


async def commit_prepared_request(
    request: PreparedModelRequest,
    committer: PreparedRequestCommitter | None,
) -> None:
    if committer is not None:
        await committer.commit_prepared_request(request)


async def invoke_prepared_request(
    adapter: PreparedRequestAdapter,
    request: ProviderRequest,
) -> AsyncIterator[RawPart]:
    prepared = adapter.prepare_request(request)
    committer = (
        request.options.prepared_request_committer
        if request.options is not None
        else None
    )
    limits = request.options.request_limits if request.options is not None else None
    validate_prepared_request_capacity(prepared, limits)
    await commit_prepared_request(prepared, committer)
    _raise_if_transport_cancelled()
    async for part in adapter.invoke_prepared_raw(request, prepared):
        yield part


def validate_prepared_request_capacity(
    request: PreparedModelRequest,
    limits: PreparedRequestLimits | None,
) -> None:
    """Reject a frozen request before commit when an explicit limit is exceeded."""

    if limits is None:
        return
    metrics = request.metrics
    exceeded = _first_exceeded_limit(metrics, limits)
    if exceeded is None:
        return
    metric_name, metric_value, limit_name, limit_value = exceeded
    details: dict[str, JSONValue] = {
        "canonicalBytes": metrics.canonical_bytes,
        "messageBytes": metrics.message_bytes,
        "messageCount": metrics.message_count,
        "imageBytes": metrics.image_bytes,
        "toolSchemaBytes": metrics.tool_schema_bytes,
        "capacityMetric": metric_name,
        "capacityLimit": limit_name,
        "capacityValue": metric_value,
        "capacityMaximum": limit_value,
    }
    if metrics.estimated_wire_bytes is not None:
        details["estimatedWireBytes"] = metrics.estimated_wire_bytes
    if metrics.estimated_input_tokens is not None:
        details["estimatedInputTokens"] = metrics.estimated_input_tokens
    raise AIRequestTooLargeError(
        "Prepared Provider request exceeds its configured capacity limit.",
        source="loushang.ai.preflight",
        provider=request.provider_id,
        endpoint=request.endpoint_id,
        model=request.model_id,
        details=details,
    )


def _raise_if_transport_cancelled() -> None:
    """Keep a committer from consuming caller cancellation before transport."""

    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


def _measure_prepared_request(
    *,
    canonical_payload: str,
    payload: Mapping[str, JSONValue],
    estimated_wire_bytes: int | None,
    estimated_input_tokens: int | None,
) -> PreparedRequestMetrics:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = payload.get("input")
    message_sequence = messages if isinstance(messages, list) else None
    tools = payload.get("tools")
    return PreparedRequestMetrics(
        canonical_bytes=len(canonical_payload.encode("utf-8")),
        estimated_wire_bytes=estimated_wire_bytes,
        message_bytes=(
            _canonical_json_size(message_sequence)
            if message_sequence is not None
            else None
        ),
        message_count=len(message_sequence) if message_sequence is not None else 0,
        image_bytes=_estimate_image_bytes(payload),
        tool_schema_bytes=_canonical_json_size(tools) if tools is not None else 0,
        estimated_input_tokens=estimated_input_tokens,
    )


def _canonical_json_size(value: JSONValue) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _estimate_image_bytes(value: object) -> int:
    if isinstance(value, str):
        marker = ";base64,"
        if value.startswith("data:image/") and marker in value:
            return _base64_decoded_size(value.split(marker, 1)[1])
        return 0
    if isinstance(value, list):
        return sum(_estimate_image_bytes(item) for item in value)
    if not isinstance(value, Mapping):
        return 0
    if (
        value.get("type") == "base64"
        and isinstance(value.get("media_type"), str)
        and cast(str, value["media_type"]).startswith("image/")
        and isinstance(value.get("data"), str)
    ):
        return _base64_decoded_size(cast(str, value["data"]))
    return sum(_estimate_image_bytes(item) for item in value.values())


def _base64_decoded_size(value: str) -> int:
    encoded = value.strip()
    if not encoded:
        return 0
    padding = len(encoded) - len(encoded.rstrip("="))
    return max(0, (len(encoded) * 3) // 4 - min(padding, 2))


def _first_exceeded_limit(
    metrics: PreparedRequestMetrics,
    limits: PreparedRequestLimits,
) -> tuple[str, int, str, int] | None:
    candidates = (
        (
            "estimatedWireBytes",
            metrics.estimated_wire_bytes,
            "maxEstimatedWireBytes",
            limits.max_estimated_wire_bytes,
        ),
        (
            "canonicalBytes",
            metrics.canonical_bytes,
            "maxCanonicalBytes",
            limits.max_canonical_bytes,
        ),
        (
            "messageCount",
            metrics.message_count,
            "maxMessageCount",
            limits.max_message_count,
        ),
        (
            "imageBytes",
            metrics.image_bytes,
            "maxImageBytes",
            limits.max_image_bytes,
        ),
        (
            "toolSchemaBytes",
            metrics.tool_schema_bytes,
            "maxToolSchemaBytes",
            limits.max_tool_schema_bytes,
        ),
        (
            "estimatedInputTokens",
            metrics.estimated_input_tokens,
            "maxEstimatedInputTokens",
            limits.max_estimated_input_tokens,
        ),
    )
    for metric_name, metric_value, limit_name, limit_value in candidates:
        if (
            metric_value is not None
            and limit_value is not None
            and metric_value > limit_value
        ):
            return metric_name, metric_value, limit_name, limit_value
    return None


def _require_non_negative_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_positive_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _project_payload(payload: Mapping[str, FrozenJSONValue]) -> dict[str, JSONValue]:
    projected = _thaw_json(payload)
    return require_json_mapping(projected, name="prepared model request payload")


def _project_model_visible_headers(headers: Mapping[str, str]) -> dict[str, str]:
    projected: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not name:
            raise ValueError("model-visible header names must be non-empty strings")
        if not isinstance(value, str) or not value:
            raise ValueError("model-visible header values must be non-empty strings")
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise ValueError("model-visible headers must not contain CR or LF")
        projected[name] = value
    return projected


def _freeze_json(value: JSONValue) -> FrozenJSONValue:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> JSONValue:
    if isinstance(value, Mapping):
        projected: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("prepared model request payload keys must be strings")
            projected[key] = _thaw_json(item)
        return projected
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_thaw_json(item) for item in value]
    return cast(JSONValue, value)


__all__ = [
    "PREPARED_MODEL_REQUEST_SCHEMA_VERSION",
    "PREPARED_MODEL_CALL_OUTCOME_SCHEMA_VERSION",
    "PreparedModelCallDisposition",
    "PreparedModelCallOutcome",
    "PreparedModelCallOutcomeRecorder",
    "PreparedModelRequest",
    "PreparedRequestLimits",
    "PreparedRequestMetrics",
    "PreparedRequestAdapter",
    "PreparedRequestCommitter",
    "commit_prepared_request",
    "invoke_prepared_request",
    "validate_prepared_request_capacity",
]
