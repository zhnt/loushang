from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import InitVar, dataclass, field
from queue import Empty, SimpleQueue
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast, runtime_checkable
from uuid import uuid4

from loushang.ai.errors import AIRequestTooLargeError
from loushang.ai.json_codec import deserialize_usage, serialize_usage
from loushang.ai.types import AssistantMessage, StopReason, Usage
from loushang.ai.utils.async_iter import close_async_source
from loushang.foundation.json import (
    JSONValue,
    require_json_mapping,
    validate_json_value,
)

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
PreparedRequestBinaryEncoding: TypeAlias = Literal["base64", "data_url"]


class _DigestState(Protocol):
    def copy(self) -> _DigestState: ...

    def update(self, data: bytes) -> None: ...

    def hexdigest(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PreparedRequestBinaryField:
    """Provider-owned location of one encoded binary field in a frozen payload."""

    path: tuple[str | int, ...]
    media_type: str
    encoding: PreparedRequestBinaryEncoding

    def __post_init__(self) -> None:
        path = tuple(self.path)
        if not path or any(
            (isinstance(item, bool) or not isinstance(item, str | int))
            or (isinstance(item, str) and not item)
            or (isinstance(item, int) and item < 0)
            for item in path
        ):
            raise ValueError("prepared binary field path is invalid")
        if not isinstance(self.media_type, str) or not self.media_type.startswith(
            "image/"
        ):
            raise ValueError("prepared binary field media type must be an image type")
        if self.encoding not in {"base64", "data_url"}:
            raise ValueError("prepared binary field encoding is invalid")
        object.__setattr__(self, "path", path)


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
            raise ValueError("PreparedModelCallOutcome.invocation_id must be non-empty")
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
class PreparedModelCallAttemptUsage:
    """Content-free normalized usage observed for one prepared attempt."""

    invocation_id: str
    usage: Usage
    terminal: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError(
                "PreparedModelCallAttemptUsage.invocation_id must be non-empty"
            )
        if not isinstance(self.usage, Usage):
            raise TypeError("PreparedModelCallAttemptUsage.usage must be Usage")
        if not isinstance(self.terminal, bool):
            raise TypeError("PreparedModelCallAttemptUsage.terminal must be boolean")
        for name in ("input", "output", "cache_read", "cache_write", "total_tokens"):
            _require_non_negative_int(getattr(self.usage, name), name=f"usage.{name}")
        canonical_usage = deserialize_usage(serialize_usage(self.usage))
        if canonical_usage != self.usage:
            raise ValueError(
                "PreparedModelCallAttemptUsage.usage cost must be finite and "
                "non-negative"
            )
        object.__setattr__(self, "usage", canonical_usage)


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
    reuse_from: InitVar[PreparedModelRequest | None] = None
    canonical_payload: str = field(init=False, repr=False)
    payload_hash: str = field(init=False)
    metrics: PreparedRequestMetrics = field(init=False)
    binary_fields: tuple[PreparedRequestBinaryField, ...] = field(
        init=False,
        repr=False,
    )
    _owned_envelope: tuple[
        Mapping[str, FrozenJSONValue], Mapping[str, str], str, str
    ] = field(init=False, repr=False, compare=False)
    # Retain small non-message fields; the canonical envelope owns message text.
    _canonical_fields: Mapping[str, str] = field(init=False, repr=False, compare=False)
    _message_array_close_offset: int | None = field(
        init=False, repr=False, compare=False
    )
    _message_prefix_digest: _DigestState | None = field(
        init=False, repr=False, compare=False
    )
    _message_prefix_hash: str | None = field(init=False, repr=False, compare=False)
    _owned_reuse: tuple[
        PreparedRequestMetrics,
        tuple[PreparedRequestBinaryField, ...],
        Mapping[str, str],
        int | None,
    ] = field(init=False, repr=False, compare=False)
    _reused_message_prefix_count: int = field(init=False, repr=False, compare=False)
    _transport_copies: SimpleQueue[dict[str, JSONValue]] = field(
        default_factory=SimpleQueue, init=False, repr=False, compare=False
    )
    _adapter_projection_state: object | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self, reuse_from: PreparedModelRequest | None) -> None:
        object.__setattr__(self, "_reused_message_prefix_count", 0)
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

        model_visible_headers = _project_model_visible_headers(
            self.model_visible_headers
        )
        if reuse_from is not None and _reuse_prepared_prefix(
            self, reuse_from, model_visible_headers
        ):
            return

        projected = _project_payload(self.payload)
        canonical_payload, message_bytes, tool_schema_bytes, canonical_fields = (
            _canonical_prepared_envelope(
                projected,
                model_visible_headers=model_visible_headers,
            )
        )
        object.__setattr__(
            self,
            "binary_fields",
            _discover_prepared_binary_fields(projected),
        )
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
                message_bytes=message_bytes,
                tool_schema_bytes=tool_schema_bytes,
                estimated_wire_bytes=self.estimated_wire_bytes,
                estimated_input_tokens=self.estimated_input_tokens,
            ),
        )
        object.__setattr__(
            self,
            "payload_hash",
            "sha256:" + hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
        )
        # Projection already detached the entire tree from the caller. Inspect
        # its native containers first, then freeze those owned containers.
        frozen_payload = cast(
            Mapping[str, FrozenJSONValue], _freeze_owned_json(projected)
        )
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(
            self,
            "_owned_envelope",
            (
                frozen_payload,
                self.model_visible_headers,
                canonical_payload,
                self.payload_hash,
            ),
        )
        message_offset = _prepared_message_array_close_offset(
            canonical_payload,
            canonical_fields,
            model_visible_headers,
        )
        frozen_fields = MappingProxyType(
            {
                name: value
                for name, value in canonical_fields.items()
                if name not in {"messages", "input"}
            }
        )
        object.__setattr__(self, "_canonical_fields", frozen_fields)
        object.__setattr__(self, "_message_array_close_offset", message_offset)
        prefix_digest = (
            hashlib.sha256(canonical_payload[:message_offset].encode("utf-8"))
            if message_offset is not None
            else None
        )
        object.__setattr__(self, "_message_prefix_digest", prefix_digest)
        object.__setattr__(
            self,
            "_message_prefix_hash",
            prefix_digest.hexdigest() if prefix_digest is not None else None,
        )
        object.__setattr__(
            self,
            "_owned_reuse",
            (self.metrics, self.binary_fields, frozen_fields, message_offset),
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
        reuse_from: PreparedModelRequest | None = None,
    ) -> PreparedModelRequest:
        model = request.model
        if reuse_from is None and request.options is not None:
            candidate = getattr(
                request.options.prepared_request_committer,
                "prepared_request_reuse",
                None,
            )
            if isinstance(candidate, PreparedModelRequest):
                reuse_from = candidate
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
            reuse_from=reuse_from,
            estimated_wire_bytes=estimated_wire_bytes,
            estimated_input_tokens=estimated_input_tokens,
        )

    def payload_for_transport(self) -> dict[str, JSONValue]:
        """Return a fresh transport object without reordering adapter mappings."""

        if not self._owned_envelope_is_current():
            raise RuntimeError(
                "prepared model request envelope changed before transport"
            )
        # The sealed digest was calculated from this owned tree at creation.
        # Frozen containers and the envelope identity check keep it unchanged.
        try:
            return self._transport_copies.get_nowait()
        except Empty:
            pass
        return self._owned_payload_copy()

    def _adopt_transport_copy(self, payload: dict[str, JSONValue]) -> None:
        """Hand one privately prepared copy to the post-commit adapter call."""

        if not self._owned_envelope_is_current():
            raise RuntimeError(
                "prepared model request envelope changed before transport"
            )
        self._transport_copies.put(payload)

    def _retain_adapter_projection_state(self, state: object) -> None:
        """Retain an adapter-local hint outside the durable request envelope."""

        object.__setattr__(self, "_adapter_projection_state", state)

    def owned_commit_projection(
        self,
    ) -> tuple[dict[str, JSONValue], dict[str, str], str] | None:
        """Project the originally sealed payload without repeating its JSON scan.

        The owned mappings contain only recursively frozen JSON values. If a
        caller replaced any envelope field after construction, the committer
        must use its full validation path instead.
        """

        if not self._owned_envelope_is_current():
            return None
        _payload, headers, canonical, _digest = self._owned_envelope
        return self._owned_payload_copy(), dict(headers), canonical

    def model_visible_headers_for_transport(self) -> dict[str, str]:
        if not self._owned_envelope_is_current():
            raise RuntimeError(
                "prepared model request envelope changed before transport"
            )
        return dict(self.model_visible_headers)

    def _owned_envelope_is_current(self) -> bool:
        payload, headers, canonical, digest = self._owned_envelope
        return (
            self.payload is payload
            and self.model_visible_headers is headers
            and self.canonical_payload is canonical
            and self.payload_hash == digest
        )

    def _owned_payload_copy(self) -> dict[str, JSONValue]:
        projected = _thaw_json(self.payload)
        if not isinstance(projected, dict):
            raise RuntimeError("sealed prepared payload is not an object")
        return projected


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
class PreparedModelCallAttemptUsageRecorder(Protocol):
    async def record_prepared_model_call_attempt_usage(
        self,
        usage: PreparedModelCallAttemptUsage,
    ) -> bool: ...


@runtime_checkable
class PreparedModelCallTerminalRecorder(Protocol):
    async def record_terminal_model_call(
        self,
        outcome: PreparedModelCallOutcome,
        *,
        usage_observed: bool,
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


async def _yield_preparation() -> None:
    # Input passes through reader and consumer callbacks. Let queued forwarding
    # finish before entering another CPU-heavy preparation stage.
    for _ in range(3):
        await asyncio.sleep(0)


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
    committer = (
        request.options.prepared_request_committer
        if request.options is not None
        else None
    )
    # Let input/cancellation run between Agent preparation, provider payload
    # materialization and the durable commit barrier. These stages can each
    # traverse a long context even when no transport has started yet.
    if committer is not None:
        await _yield_preparation()
        _raise_if_transport_cancelled()
    # Built-in, stateless adapters opt in explicitly. A trace callback keeps
    # its existing event-loop thread affinity. Custom adapters stay on the
    # caller thread unless their concrete class declares worker safety.
    prepare_in_worker = (
        committer is not None
        and type(adapter).__dict__.get("prepare_request_in_worker") is True
        and (request.options is None or request.options.trace is None)
    )
    prewarm = getattr(committer, "prewarm_logical_input", None)
    warm_task: asyncio.Task[None] | None = None
    if prepare_in_worker and callable(prewarm):
        # Both jobs read sealed request inputs. The commit barrier below waits
        # for both, so cancellation cannot publish a partial preparation.
        warm_task = asyncio.create_task(prewarm())
        warm_task.add_done_callback(_consume_speculative_preparation)
    try:
        prepared = (
            await asyncio.to_thread(adapter.prepare_request, request)
            if prepare_in_worker
            else adapter.prepare_request(request)
        )
        if warm_task is not None:
            await warm_task
    except BaseException:
        if warm_task is not None:
            warm_task.cancel()
        raise
    limits = request.options.request_limits if request.options is not None else None
    validate_prepared_request_capacity(prepared, limits)
    if committer is not None:
        await _yield_preparation()
        _raise_if_transport_cancelled()
    transport_copy_task: asyncio.Task[dict[str, JSONValue]] | None = None
    if (
        prepare_in_worker
        and type(prepared) is PreparedModelRequest
        and prepared.metrics.canonical_bytes >= 64 * 1024
        and not prepared.binary_fields
    ):
        # The copy reads only the sealed envelope. It has no publication or
        # transport authority; the durable barrier below remains first.
        transport_copy_task = asyncio.create_task(
            asyncio.to_thread(prepared._owned_payload_copy)
        )
        transport_copy_task.add_done_callback(_consume_transport_preparation)
    try:
        await commit_prepared_request(prepared, committer)
        _raise_if_transport_cancelled()
        if transport_copy_task is not None:
            prepared._adopt_transport_copy(await transport_copy_task)
    except BaseException:
        if transport_copy_task is not None:
            transport_copy_task.cancel()
        raise
    _raise_if_transport_cancelled()
    source = adapter.invoke_prepared_raw(request, prepared)
    try:
        async for part in source:
            yield part
    finally:
        await close_async_source(source)


def _consume_speculative_preparation(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _consume_transport_preparation(
    task: asyncio.Task[dict[str, JSONValue]],
) -> None:
    if not task.cancelled():
        task.exception()


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


def _same_raw_json_as_frozen(raw: object, frozen: object) -> bool:
    """Prove an untrusted provider value equals one previously sealed value."""

    # The prior request owns a recursively frozen tree. An adapter can reuse
    # one of those exact nodes without walking its historical descendants.
    if raw is frozen:
        return True
    raw_type = type(raw)
    if raw_type is dict and type(frozen) is MappingProxyType:
        raw_mapping = cast(dict[object, object], raw)
        frozen_mapping = cast(Mapping[str, object], frozen)
        return tuple(raw_mapping) == tuple(frozen_mapping) and all(
            type(name) is str
            and name in frozen_mapping
            and _same_raw_json_as_frozen(value, frozen_mapping[name])
            for name, value in raw_mapping.items()
        )
    if raw_type is list and type(frozen) is tuple:
        raw_items = cast(list[object], raw)
        frozen_items = cast(tuple[object, ...], frozen)
        return len(raw_items) == len(frozen_items) and all(
            _same_raw_json_as_frozen(left, right)
            for left, right in zip(raw_items, frozen_items, strict=True)
        )
    if raw_type is float and type(frozen) is float:
        return raw == frozen and (
            raw != 0.0 or math.copysign(1.0, raw) == math.copysign(1.0, frozen)
        )
    return raw_type in {type(None), str, bool, int} and (
        type(frozen) is raw_type and raw == frozen
    )


def _reuse_prepared_prefix(
    request: PreparedModelRequest,
    previous: PreparedModelRequest,
    headers: dict[str, str],
) -> bool:
    """Reuse only a sealed exact prefix; any uncertain shape takes the full path."""

    if not isinstance(previous, PreparedModelRequest):
        return False
    (
        prior_metrics,
        prior_binary_fields,
        prior_canonical_fields,
        prior_offset,
    ) = previous._owned_reuse
    if not previous._owned_envelope_is_current() or (
        previous.metrics is not prior_metrics
        or previous.binary_fields is not prior_binary_fields
        or previous._canonical_fields is not prior_canonical_fields
        or previous._message_array_close_offset != prior_offset
    ):
        return False
    if type(request.payload) is not dict or headers != previous.model_visible_headers:
        return False
    raw = cast(dict[str, object], request.payload)
    old = previous.payload
    if tuple(raw) != tuple(old) or any(type(name) is not str for name in raw):
        return False
    message_key = "messages" if type(raw.get("messages")) is list else "input"
    messages = raw.get(message_key)
    prior_messages = old.get(message_key)
    if type(messages) is not list or type(prior_messages) is not tuple:
        return False
    messages = cast(list[object], messages)
    sealed_messages = cast(tuple[FrozenJSONValue, ...], prior_messages)
    prior_count = len(sealed_messages)
    if len(messages) < prior_count or any(
        not _same_raw_json_as_frozen(current, sealed)
        for current, sealed in zip(messages[:prior_count], sealed_messages, strict=True)
    ):
        return False
    if any(
        not _same_raw_json_as_frozen(value, old[name])
        for name, value in raw.items()
        if name != message_key
    ):
        return False
    if (
        type(prior_offset) is not int
        or not 0 <= prior_offset < len(previous.canonical_payload)
        or previous.canonical_payload[prior_offset] != "]"
        or type(prior_metrics.message_bytes) is not int
    ):
        return False
    prior_prefix_digest = previous._message_prefix_digest
    if (
        prior_prefix_digest is None
        or prior_prefix_digest.copy().hexdigest() != previous._message_prefix_hash
    ):
        return False

    suffix = cast(
        list[JSONValue], [_thaw_json(item) for item in messages[prior_count:]]
    )
    validate_json_value(suffix, name="prepared model request message suffix")

    def encode(value: JSONValue | dict[str, str] | str) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    suffix_canonical = encode(suffix)[1:-1] if suffix else ""
    added_messages = ("," if prior_count and suffix else "") + suffix_canonical
    canonical = "".join(
        (
            previous.canonical_payload[:prior_offset],
            added_messages,
            previous.canonical_payload[prior_offset:],
        )
    )
    added_bytes = added_messages.encode("utf-8")
    prefix_digest = prior_prefix_digest.copy()
    prefix_digest.update(added_bytes)
    full_digest = prefix_digest.copy()
    full_digest.update(previous.canonical_payload[prior_offset:].encode("utf-8"))
    digest = "sha256:" + full_digest.hexdigest()
    suffix_image_bytes = _estimate_image_bytes(suffix)
    suffix_binary_fields = tuple(
        field
        for index, item in enumerate(suffix, start=prior_count)
        for field in _discover_prepared_binary_fields(item, path=(message_key, index))
    )
    owned = dict(old)
    owned[message_key] = sealed_messages + tuple(
        _freeze_owned_json(item) for item in suffix
    )
    frozen_payload = MappingProxyType(owned)
    binary_fields = previous.binary_fields + suffix_binary_fields
    metrics = PreparedRequestMetrics(
        canonical_bytes=prior_metrics.canonical_bytes + len(added_bytes),
        estimated_wire_bytes=request.estimated_wire_bytes,
        message_bytes=prior_metrics.message_bytes + len(added_messages.encode("utf-8")),
        message_count=len(messages),
        image_bytes=previous.metrics.image_bytes + suffix_image_bytes,
        tool_schema_bytes=previous.metrics.tool_schema_bytes,
        estimated_input_tokens=request.estimated_input_tokens,
    )
    frozen_fields = previous._canonical_fields
    frozen_headers = MappingProxyType(headers)
    object.__setattr__(request, "payload", frozen_payload)
    object.__setattr__(request, "model_visible_headers", frozen_headers)
    object.__setattr__(request, "canonical_payload", canonical)
    object.__setattr__(request, "payload_hash", digest)
    object.__setattr__(request, "binary_fields", binary_fields)
    object.__setattr__(request, "metrics", metrics)
    object.__setattr__(
        request, "_owned_envelope", (frozen_payload, frozen_headers, canonical, digest)
    )
    object.__setattr__(request, "_canonical_fields", frozen_fields)
    message_offset = prior_offset + len(added_messages)
    object.__setattr__(request, "_message_array_close_offset", message_offset)
    object.__setattr__(request, "_message_prefix_digest", prefix_digest)
    object.__setattr__(request, "_message_prefix_hash", prefix_digest.hexdigest())
    object.__setattr__(
        request,
        "_owned_reuse",
        (metrics, binary_fields, frozen_fields, message_offset),
    )
    object.__setattr__(request, "_reused_message_prefix_count", prior_count)
    return True


def _measure_prepared_request(
    *,
    canonical_payload: str,
    payload: Mapping[str, JSONValue],
    message_bytes: int | None,
    tool_schema_bytes: int,
    estimated_wire_bytes: int | None,
    estimated_input_tokens: int | None,
) -> PreparedRequestMetrics:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = payload.get("input")
    message_sequence = messages if isinstance(messages, list) else None
    return PreparedRequestMetrics(
        canonical_bytes=len(canonical_payload.encode("utf-8")),
        estimated_wire_bytes=estimated_wire_bytes,
        message_bytes=message_bytes,
        message_count=len(message_sequence) if message_sequence is not None else 0,
        image_bytes=_estimate_image_bytes(payload),
        tool_schema_bytes=tool_schema_bytes,
        estimated_input_tokens=estimated_input_tokens,
    )


def _canonical_prepared_envelope(
    payload: Mapping[str, JSONValue],
    *,
    model_visible_headers: Mapping[str, str],
) -> tuple[str, int | None, int, dict[str, str]]:
    """Encode each top-level field once and retain its exact canonical size."""

    def encode(value: JSONValue) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    messages_key = "messages" if isinstance(payload.get("messages"), list) else "input"
    message_bytes: int | None = None
    tool_schema_bytes = 0
    fields: list[str] = []
    canonical_fields: dict[str, str] = {}
    for name in sorted(payload):
        value = payload[name]
        encoded = encode(value)
        canonical_fields[name] = encoded
        if name == messages_key and isinstance(value, list):
            message_bytes = len(encoded.encode("utf-8"))
        if name == "tools" and value is not None:
            tool_schema_bytes = len(encoded.encode("utf-8"))
        fields.append(encode(name) + ":" + encoded)
    canonical = (
        '{"model_visible_headers":'
        + encode(dict(model_visible_headers))
        + ',"payload":{'
        + ",".join(fields)
        + "}}"
    )
    return canonical, message_bytes, tool_schema_bytes, canonical_fields


def _prepared_message_array_close_offset(
    canonical: str,
    fields: Mapping[str, str],
    headers: Mapping[str, str],
) -> int | None:
    message_key = next(
        (
            name
            for name in ("messages", "input")
            if fields.get(name, "").startswith("[")
        ),
        None,
    )
    if message_key is None:
        return None

    def encode(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    position = len('{"model_visible_headers":') + len(encode(dict(headers)))
    position += len(',"payload":{')
    for index, name in enumerate(sorted(fields)):
        position += (1 if index else 0) + len(encode(name)) + 1
        value = fields[name]
        if name == message_key:
            position += len(value) - 1
            return position if canonical[position : position + 1] == "]" else None
        position += len(value)
    return None


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


def _discover_prepared_binary_fields(
    value: JSONValue,
    *,
    path: tuple[str | int, ...] = (),
) -> tuple[PreparedRequestBinaryField, ...]:
    """Project provider wire details once into a stable AI-layer contract."""

    if isinstance(value, str):
        marker = ";base64,"
        if value.startswith("data:image/") and marker in value:
            prefix, _encoded = value.split(marker, 1)
            return (
                PreparedRequestBinaryField(
                    path=path,
                    media_type=prefix.removeprefix("data:"),
                    encoding="data_url",
                ),
            )
        return ()
    if isinstance(value, list):
        return tuple(
            field
            for index, item in enumerate(value)
            for field in _discover_prepared_binary_fields(
                item,
                path=(*path, index),
            )
        )
    if not isinstance(value, dict):
        return ()
    data = value.get("data")
    media_type = value.get("media_type")
    selected: tuple[PreparedRequestBinaryField, ...]
    if (
        value.get("type") == "base64"
        and isinstance(data, str)
        and isinstance(media_type, str)
        and media_type.startswith("image/")
    ):
        selected = (
            PreparedRequestBinaryField(
                path=(*path, "data"),
                media_type=media_type,
                encoding="base64",
            ),
        )
    else:
        selected = ()
    return selected + tuple(
        field
        for name, item in value.items()
        if not (selected and name == "data")
        for field in _discover_prepared_binary_fields(
            item,
            path=(*path, name),
        )
    )


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
    if not isinstance(projected, dict):
        return require_json_mapping(projected, name="prepared model request payload")
    # Thaw already owns every native container. Retain strict validation while
    # avoiding a second complete copy of that detached tree.
    validate_json_value(projected, name="prepared model request payload")
    return projected


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


def _freeze_owned_json(value: JSONValue) -> FrozenJSONValue:
    """Freeze an exclusively owned, validated projection without copying dicts."""

    if isinstance(value, dict):
        owned = cast(dict[str, FrozenJSONValue], value)
        for key, item in value.items():
            owned[key] = _freeze_owned_json(item)
        return MappingProxyType(owned)
    if isinstance(value, list):
        return tuple(_freeze_owned_json(item) for item in value)
    return value


def _thaw_json(value: object) -> JSONValue:
    value_type = type(value)
    # Most nodes in a long request are scalars or native owned/frozen
    # containers. Avoid generic ABC dispatch for every node in those trees.
    if (
        value is None
        or value_type is str
        or value_type is bool
        or value_type is int
        or value_type is float
    ):
        return cast(JSONValue, value)
    if value_type is list or value_type is tuple:
        return [_thaw_json(item) for item in cast("Sequence[object]", value)]
    if (
        value_type is dict
        or value_type is MappingProxyType
        or isinstance(value, Mapping)
    ):
        mapping = cast("Mapping[object, object]", value)
        projected: dict[str, JSONValue] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise TypeError("prepared model request payload keys must be strings")
            projected[key] = _thaw_json(item)
        return projected
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_thaw_json(item) for item in cast("Sequence[object]", value)]
    return cast(JSONValue, value)


__all__ = [
    "PREPARED_MODEL_REQUEST_SCHEMA_VERSION",
    "PREPARED_MODEL_CALL_OUTCOME_SCHEMA_VERSION",
    "PreparedModelCallDisposition",
    "PreparedModelCallAttemptUsage",
    "PreparedModelCallAttemptUsageRecorder",
    "PreparedModelCallOutcome",
    "PreparedModelCallOutcomeRecorder",
    "PreparedModelCallTerminalRecorder",
    "PreparedModelRequest",
    "PreparedRequestLimits",
    "PreparedRequestMetrics",
    "PreparedRequestAdapter",
    "PreparedRequestBinaryEncoding",
    "PreparedRequestBinaryField",
    "PreparedRequestCommitter",
    "commit_prepared_request",
    "invoke_prepared_request",
    "validate_prepared_request_capacity",
]
