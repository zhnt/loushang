"""Current-Session adapter for Agent sampling and AI's transport barrier."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import pickle
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Protocol, TypeVar, cast

from loushang.agent import ModelCallPreparation
from loushang.ai.context import (
    NormalizationResult,
    NormalizedContext,
    normalize_context_result,
)
from loushang.ai.json_codec import deserialize_message, serialize_message
from loushang.ai.model import Model
from loushang.ai.options import CallOptions, PairingMode
from loushang.ai.prepared_request import (
    PreparedModelCallAttemptUsage,
    PreparedModelCallAttemptUsageRecorder,
    PreparedModelCallOutcome,
    PreparedModelCallOutcomeRecorder,
    PreparedModelCallTerminalRecorder,
    PreparedModelRequest,
    PreparedRequestCommitter,
)
from loushang.ai.structured import StructuredOutputOptions
from loushang.ai.types import (
    AssistantMessage,
    Context,
    ImagePart,
    Message,
    ProviderCompactionWindow,
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.foundation.json import JSONValue, require_json_mapping, require_json_value
from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityContractRange,
    CapabilityDependencyBinding,
    CapabilityFacetBinding,
    CapabilityProviderContext,
    EffectiveRuntimeDiff,
    EffectiveRuntimeView,
    ModelSurfaceReference,
    RegistrationExplanation,
    RegistrationInventoryEntry,
    RegistrationInventorySnapshot,
    RuntimeCapabilityGraphProjector,
    RuntimeProfileSlotExplanation,
    ScopedSourcePublicationReference,
)
from loushang.harness.capabilities.effective_runtime import (
    compose_registration_inventory,
)
from loushang.harness.capabilities.graph_projection import CapabilityGraphExplanation
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.model_input_contracts import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    MODEL_INPUT_PREPARATION_FACET,
    MODEL_INPUT_PREPARATION_REQUIREMENT,
)
from loushang.harness.capabilities.session_contracts import (
    SESSION_CAPABILITY_DEFINITION,
    SESSION_TRANSCRIPT_REQUIREMENT,
    TRANSCRIPT_PROFILE_FACET,
)
from loushang.harness.runtime import RuntimeProfileSnapshot
from loushang.harness.session.request_evidence import (
    RESOURCE_EVIDENCE_COMPONENT,
)
from loushang.harness.session.turn_performance import TurnStartPerformanceRuntime
from loushang.harness.transcript import (
    ModelCallAttemptUsage,
    ModelInputRuntimeReferences,
)
from loushang.harness.transcript.model_input import (
    ModelInputTranscriptCommitter,
    RebuiltModelInput,
)
from loushang.harness.transcript.model_input_types import (
    freeze_model_input_json,
    thaw_model_input_json,
)

CurrentSessionPredicate = Callable[[], bool]
_OwnedResult = TypeVar("_OwnedResult")
RegistrationEntriesProvider = Callable[[], tuple[RegistrationInventoryEntry, ...]]
CurrentProfileFingerprintProvider = Callable[[], str]
SourcePublicationProvider = Callable[[], ScopedSourcePublicationReference | None]
RequestEvidenceProvider = Callable[[ModelCallPreparation], Mapping[str, object] | None]
CommittedModelInputObserver = Callable[[str], None]


def _call_on_owner_loop(
    owner_loop: asyncio.AbstractEventLoop | None,
    callback: Callable[[], _OwnedResult],
) -> _OwnedResult:
    if owner_loop is None:
        return callback()

    async def invoke() -> _OwnedResult:
        return callback()

    return asyncio.run_coroutine_threadsafe(invoke(), owner_loop).result()


@dataclass(frozen=True, slots=True)
class _SealedMessageReuse:
    message: Message
    shape: tuple[object, ...] | None
    sealed: object


@dataclass(frozen=True, slots=True)
class _StrictMessageSnapshot:
    sealed: object
    message: Message
    encoded: bytes


@dataclass(frozen=True, slots=True)
class _StrictSnapshotBatch:
    snapshots: tuple[_StrictMessageSnapshot | None, ...]
    messages: tuple[Message, ...] | None
    encoded: bytes | None


@dataclass(frozen=True, slots=True)
class _NormalizedPrefixCache:
    source: tuple[object, ...]
    key: str
    result: NormalizationResult
    encoded: bytes
    prior_tool_ids: frozenset[str]


def _normalization_key(model: Model, pairing_mode: PairingMode) -> str | None:
    try:
        return json.dumps(
            {
                "model": model.to_raw(),
                "model_id": model.id,
                "provider_id": model.provider_id,
                "endpoint_id": model.endpoint_id,
                "api": model.api,
                "pairing_mode": pairing_mode,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None


def _tool_ids(messages: Sequence[Message]) -> frozenset[str]:
    ids: set[str] = set()
    for message in messages:
        if type(message) is AssistantMessage:
            ids.update(part.id for part in message.content if type(part) is ToolCall)
        elif type(message) is ToolResultMessage:
            ids.add(message.tool_call_id)
    return frozenset(ids)


def _build_normalized_prefix_cache(
    source: tuple[object, ...],
    owned_context: Callable[[Context], Context],
    model: Model,
    pairing_mode: PairingMode,
) -> _NormalizedPrefixCache | None:
    key = _normalization_key(model, pairing_mode)
    if key is None:
        return None
    context = owned_context(Context())
    if len(context.messages) != len(source):
        return None
    result = normalize_context_result(context, model=model, pairing_mode=pairing_mode)
    if (
        not result.context.messages
        or type(result.context.messages[-1]) is not UserMessage
    ):
        return None
    ids = _tool_ids(context.messages) | _tool_ids(result.context.messages)
    try:
        encoded = pickle.dumps(result.context.messages, protocol=5)
    except Exception:
        return None
    return _NormalizedPrefixCache(source, key, result, encoded, ids)


def _strict_message_equal(current: object, snapshot: object) -> bool:
    if type(current) is not type(snapshot) or current != snapshot:
        return False
    try:
        return pickle.dumps(current, protocol=5) == pickle.dumps(snapshot, protocol=5)
    except Exception:
        return False


def _strict_snapshot_matches(
    current: Message, snapshot: _StrictMessageSnapshot
) -> bool:
    if type(current) is not type(snapshot.message) or current != snapshot.message:
        return False
    try:
        return pickle.dumps(current, protocol=5) == snapshot.encoded
    except Exception:
        return False


def _build_strict_message_snapshots(
    source: tuple[_SealedMessageReuse, ...],
    previous: tuple[_StrictMessageSnapshot | None, ...],
) -> _StrictSnapshotBatch:
    snapshots: list[_StrictMessageSnapshot | None] = []
    for index, entry in enumerate(source):
        prior = previous[index] if index < len(previous) else None
        if prior is not None and prior.sealed is entry.sealed:
            snapshots.append(prior)
            continue
        try:
            copied = deepcopy(entry.message)
            if (
                freeze_model_input_json(
                    serialize_message(copied), name="strict Model Input message"
                )
                != entry.sealed
            ):
                snapshots.append(None)
                continue
            encoded = pickle.dumps(copied, protocol=5)
        except (TypeError, ValueError, RecursionError, pickle.PicklingError):
            snapshots.append(None)
            continue
        snapshots.append(_StrictMessageSnapshot(entry.sealed, copied, encoded))
    if all(snapshot is not None for snapshot in snapshots):
        messages = tuple(
            snapshot.message for snapshot in snapshots if snapshot is not None
        )
        prefix_encoded: bytes | None
        try:
            prefix_encoded = pickle.dumps(messages, protocol=5)
        except Exception:
            prefix_encoded = None
        return _StrictSnapshotBatch(tuple(snapshots), messages, prefix_encoded)
    return _StrictSnapshotBatch(tuple(snapshots), None, None)


_UNSAFE_SHAPE = object()
_MESSAGE_JSON_SHAPE_LIMIT = 64


def _scalar_shape(value: object) -> tuple[object, ...] | object:
    if value is None:
        return (None,)
    if type(value) is float:
        return (float, repr(value)) if math.isfinite(value) else _UNSAFE_SHAPE
    if type(value) in (str, int, bool):
        return (type(value), value)
    return _UNSAFE_SHAPE


def _scalar_shapes(*values: object) -> tuple[tuple[object, ...], ...] | None:
    shapes = tuple(_scalar_shape(value) for value in values)
    if any(shape is _UNSAFE_SHAPE for shape in shapes):
        return None
    return cast(tuple[tuple[object, ...], ...], shapes)


def _bounded_json_shape(
    value: object, *, budget: list[int], seen: set[int]
) -> tuple[object, ...] | None:
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    primitive = _scalar_shape(value)
    if primitive is not _UNSAFE_SHAPE:
        return cast(tuple[object, ...], primitive)
    if type(value) is not list and type(value) is not dict:
        return None
    identity = id(value)
    if identity in seen:
        return None
    seen.add(identity)
    try:
        if isinstance(value, list):
            list_items = tuple(
                _bounded_json_shape(item, budget=budget, seen=seen) for item in value
            )
            return (
                None if any(item is None for item in list_items) else (list, list_items)
            )
        dict_items: list[tuple[str, tuple[object, ...]]] = []
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str:
                return None
            shape = _bounded_json_shape(item, budget=budget, seen=seen)
            if shape is None:
                return None
            dict_items.append((key, shape))
        return (dict, tuple(dict_items))
    finally:
        seen.remove(identity)


def _content_shape(value: object, *, budget: list[int]) -> tuple[object, ...] | None:
    if type(value) is not list:
        return None
    parts: list[object] = []
    for part in value:
        if type(part) is TextPart:
            fields = _scalar_shapes(part.type, part.text)
            signature = _bounded_json_shape(
                part.text_signature, budget=budget, seen=set()
            )
            if fields is None or signature is None:
                return None
            parts.append((TextPart, fields, signature))
        elif type(part) is ImagePart:
            fields = _scalar_shapes(part.type, part.data, part.mime_type)
            if fields is None:
                return None
            parts.append((ImagePart, fields))
        elif type(part) is ThinkingPart:
            fields = _scalar_shapes(
                part.type, part.thinking, part.thinking_signature, part.redacted
            )
            if fields is None:
                return None
            parts.append((ThinkingPart, fields))
        elif type(part) is ToolCall:
            fields = _scalar_shapes(
                part.type, part.id, part.name, part.thought_signature
            )
            arguments = _bounded_json_shape(part.arguments, budget=budget, seen=set())
            if fields is None or arguments is None:
                return None
            parts.append((ToolCall, fields, arguments))
        else:
            return None
    return tuple(parts)


def _sealed_message_shape(message: Message) -> tuple[object, ...] | None:
    """Certify only message forms whose complete wire value is cheap to check."""

    budget = [_MESSAGE_JSON_SHAPE_LIMIT]
    if type(message) is UserMessage:
        content = message.content
        content_shape = (
            (str, _scalar_shape(content))
            if type(content) is str
            else _content_shape(content, budget=budget)
        )
        fields = _scalar_shapes(message.role, message.timestamp)
        if content_shape is None or fields is None:
            return None
        return (UserMessage, fields, content_shape)
    if type(message) is ToolResultMessage:
        content_shape = _content_shape(message.content, budget=budget)
        details_shape = _bounded_json_shape(message.details, budget=budget, seen=set())
        fields = _scalar_shapes(
            message.role,
            message.tool_call_id,
            message.tool_name,
            message.is_error,
            message.timestamp,
            message.terminate,
        )
        if content_shape is None or details_shape is None or fields is None:
            return None
        return (ToolResultMessage, fields, content_shape, details_shape)
    if type(message) is AssistantMessage:
        content_shape = _content_shape(message.content, budget=budget)
        usage = message.usage
        cost_shape = (
            _bounded_json_shape(usage.cost, budget=budget, seen=set())
            if type(usage) is Usage
            else None
        )
        error_shape = _bounded_json_shape(message.error_info, budget=budget, seen=set())
        if (
            content_shape is None
            or type(usage) is not Usage
            or cost_shape is None
            or error_shape is None
        ):
            return None
        fields = _scalar_shapes(
            message.role,
            message.api,
            message.provider,
            message.endpoint,
            message.model,
            message.response_id,
            usage.input,
            usage.output,
            usage.cache_read,
            usage.cache_write,
            usage.total_tokens,
            message.stop_reason,
            message.error_message,
            message.timestamp,
            message.response_model,
        )
        if fields is None:
            return None
        return (AssistantMessage, fields, content_shape, cost_shape, error_shape)
    return None


class ModelInputTranscriptPort(Protocol):
    def create_model_input_committer(
        self,
        *,
        purpose: str,
        logical_input: dict[str, object],
        runtime_references: ModelInputRuntimeReferences,
    ) -> ModelInputTranscriptCommitter: ...

    def rebuild_model_input(self, snapshot_id: str) -> RebuiltModelInput: ...


@dataclass(frozen=True)
class _DependencyModelInputTranscriptPort:
    """Expose only Model Input operations from the declared Session dependency."""

    dependency: CapabilityDependencyBinding

    def create_model_input_committer(
        self,
        *,
        purpose: str,
        logical_input: dict[str, object],
        runtime_references: ModelInputRuntimeReferences,
    ) -> ModelInputTranscriptCommitter:
        return self._facet().create_model_input_committer(
            purpose=purpose,
            logical_input=logical_input,
            runtime_references=runtime_references,
        )

    def rebuild_model_input(self, snapshot_id: str) -> RebuiltModelInput:
        return self._facet().rebuild_model_input(snapshot_id)

    def _facet(self) -> ModelInputTranscriptPort:
        value = self.dependency.require(TRANSCRIPT_PROFILE_FACET)
        _require_transcript_port(value, name="model-input Session dependency")
        return cast(ModelInputTranscriptPort, value)


class SessionModelCallPreparer:
    """Bind one fresh transcript committer to a final Agent-level model input."""

    def __init__(
        self,
        *,
        transcript: ModelInputTranscriptPort,
        projector: RuntimeCapabilityGraphProjector,
        is_current: CurrentSessionPredicate,
        registration_entries_provider: RegistrationEntriesProvider,
        profile_fingerprint_provider: CurrentProfileFingerprintProvider,
        turn_performance: TurnStartPerformanceRuntime | None = None,
        request_evidence_provider: RequestEvidenceProvider | None = None,
        on_committed_evidence_free_input: CommittedModelInputObserver | None = None,
    ) -> None:
        _require_transcript_port(transcript, name="model-call preparation")
        if not isinstance(projector, RuntimeCapabilityGraphProjector):
            raise TypeError("model-call preparation requires graph projection")
        if not callable(is_current):
            raise TypeError("model-call preparation requires a current-Session check")
        if not callable(registration_entries_provider):
            raise TypeError("model-call preparation requires registration inventory")
        if not callable(profile_fingerprint_provider):
            raise TypeError("model-call preparation requires current Profile facts")
        if request_evidence_provider is not None and not callable(
            request_evidence_provider
        ):
            raise TypeError("model-call preparation request evidence must be callable")
        self._transcript = transcript
        self._projector = projector
        self._is_current = is_current
        self._registration_entries_provider = registration_entries_provider
        self._profile_fingerprint_provider = profile_fingerprint_provider
        self._turn_performance = turn_performance
        self._request_evidence_provider = request_evidence_provider
        self._on_committed_evidence_free_input = on_committed_evidence_free_input
        self._last_prepared_request: PreparedModelRequest | None = None
        self._last_prepared_source: tuple[object, ...] = ()
        self._last_prepared_message_cache: tuple[_SealedMessageReuse, ...] = ()
        self._sealed_message_cache: tuple[_SealedMessageReuse, ...] = ()
        self._strict_message_snapshots: tuple[_StrictMessageSnapshot | None, ...] = ()
        self._strict_prefix_messages: tuple[Message, ...] | None = None
        self._strict_prefix_encoded: bytes | None = None
        self._strict_snapshot_task: asyncio.Task[_StrictSnapshotBatch] | None = None
        self._normalized_cache: _NormalizedPrefixCache | None = None
        self._normalized_cache_task: (
            asyncio.Task[_NormalizedPrefixCache | None] | None
        ) = None

    def _retain_prepared_request(
        self,
        request: PreparedModelRequest,
        source: tuple[object, ...],
        message_cache: tuple[_SealedMessageReuse, ...],
    ) -> None:
        self._last_prepared_request = request
        self._last_prepared_source = source
        self._last_prepared_message_cache = message_cache

    def _finish_strict_snapshot(
        self,
        task: asyncio.Task[_StrictSnapshotBatch],
        source: tuple[object, ...],
    ) -> None:
        if task.cancelled():
            return
        try:
            batch = task.result()
        except BaseException:
            return
        if self._last_prepared_source is source:
            self._strict_message_snapshots = batch.snapshots
            self._strict_prefix_messages = batch.messages
            self._strict_prefix_encoded = batch.encoded

    def _schedule_normalized_cache(
        self,
        source: tuple[object, ...],
        owned_context: Callable[[Context], Context],
        model: Model,
        pairing_mode: PairingMode,
    ) -> None:
        if self._last_prepared_source is not source:
            return
        strict_task = asyncio.create_task(
            asyncio.to_thread(
                _build_strict_message_snapshots,
                self._last_prepared_message_cache,
                self._strict_message_snapshots,
            )
        )
        self._strict_snapshot_task = strict_task
        strict_task.add_done_callback(
            lambda completed: self._finish_strict_snapshot(completed, source)
        )
        if model.api != "openai-completions":
            return

        async def build_normalized_cache() -> _NormalizedPrefixCache | None:
            with suppress(Exception):
                await strict_task
            return await asyncio.to_thread(
                _build_normalized_prefix_cache,
                source,
                owned_context,
                model,
                pairing_mode,
            )

        task = asyncio.create_task(build_normalized_cache())
        self._normalized_cache_task = task
        task.add_done_callback(
            lambda completed: self._finish_normalized_cache(completed, source)
        )

    def _finish_normalized_cache(
        self,
        task: asyncio.Task[_NormalizedPrefixCache | None],
        source: tuple[object, ...],
    ) -> None:
        if task.cancelled():
            return
        try:
            cache = task.result()
        except BaseException:
            return
        if self._last_prepared_source is source:
            self._normalized_cache = cache

    def _project_logical_messages(
        self, messages: Sequence[Message]
    ) -> tuple[list[object], tuple[tuple[object, ...] | None, ...], int]:
        projected: list[object] = []
        shapes: list[tuple[object, ...] | None] = []
        prefix_matches = True
        reused_prefix_count = 0
        for index, message in enumerate(messages):
            prior = (
                self._sealed_message_cache[index]
                if index < len(self._sealed_message_cache)
                else None
            )
            if (
                prefix_matches
                and prior is not None
                and prior.message is message
                and prior.shape is not None
            ):
                projected.append(prior.sealed)
                shapes.append(prior.shape)
                reused_prefix_count += 1
            else:
                prefix_matches = False
                projected.append(serialize_message(message))
                shapes.append(_sealed_message_shape(message))
        return projected, tuple(shapes), reused_prefix_count

    @staticmethod
    def _recheck_logical_messages(
        messages: Sequence[Message],
        projected: list[object],
        shapes: tuple[tuple[object, ...] | None, ...],
        reused_prefix_count: int,
        strict_snapshots: list[_StrictMessageSnapshot | None] | None = None,
        strict_prefix_messages: tuple[Message, ...] | None = None,
        strict_prefix_encoded: bytes | None = None,
    ) -> tuple[tuple[tuple[object, ...] | None, ...], int]:
        if len(messages) != len(projected):
            projected[:] = [serialize_message(message) for message in messages]
            return tuple(_sealed_message_shape(message) for message in messages), 0
        if (
            reused_prefix_count > 0
            and strict_prefix_messages is not None
            and strict_prefix_encoded is not None
            and len(strict_prefix_messages) == reused_prefix_count
            and strict_snapshots is not None
            and len(strict_snapshots) >= reused_prefix_count
            and all(
                snapshot is not None and type(message) is type(snapshot.message)
                for message, snapshot in zip(
                    messages[:reused_prefix_count],
                    strict_snapshots[:reused_prefix_count],
                    strict=False,
                )
            )
        ):
            try:
                current_prefix = tuple(messages[:reused_prefix_count])
                if (
                    current_prefix == strict_prefix_messages
                    and pickle.dumps(current_prefix, protocol=5)
                    == strict_prefix_encoded
                ):
                    return shapes, reused_prefix_count
            except Exception:
                pass
        for index in range(reused_prefix_count):
            snapshot = (
                strict_snapshots[index]
                if strict_snapshots is not None and index < len(strict_snapshots)
                else None
            )
            if snapshot is not None and _strict_snapshot_matches(
                messages[index], snapshot
            ):
                continue
            if strict_snapshots is not None and index < len(strict_snapshots):
                strict_snapshots[index] = None
            if _sealed_message_shape(messages[index]) != shapes[index]:
                projected[index:] = [
                    serialize_message(message) for message in messages[index:]
                ]
                return (
                    shapes[:index]
                    + tuple(
                        _sealed_message_shape(message) for message in messages[index:]
                    ),
                    index,
                )
        return shapes, reused_prefix_count

    def __call__(
        self,
        preparation: ModelCallPreparation,
        *,
        owner_loop: asyncio.AbstractEventLoop | None = None,
    ) -> CallOptions:
        if not isinstance(preparation, ModelCallPreparation):
            raise TypeError("model-call preparation requires ModelCallPreparation")
        if _call_on_owner_loop(owner_loop, self._is_current) is not True:
            raise RuntimeError("Session is not current; model transport is forbidden")
        if preparation.options.prepared_request_committer is not None:
            raise RuntimeError(
                "durable Session cannot replace an existing prepared-request committer"
            )

        if self._turn_performance is not None:
            self._turn_performance.model_call_prepare_started(preparation)
        try:
            graph = self._projector.snapshot()
            registrations = compose_registration_inventory(
                self._projector.registration_inventory(),
                self._registration_entries_provider(),
            )
            (
                logical_messages,
                message_shapes,
                reused_prefix_count,
            ) = self._project_logical_messages(preparation.context.messages)
            logical_input = _logical_input(
                preparation, serialized_messages=logical_messages
            )
            if self._request_evidence_provider is not None:
                evidence_provider = self._request_evidence_provider
                evidence = _call_on_owner_loop(
                    owner_loop, lambda: evidence_provider(preparation)
                )
                if evidence is not None:
                    logical_input[RESOURCE_EVIDENCE_COMPONENT] = require_json_mapping(
                        evidence,
                        name="Model Input Resource evidence",
                    )
            runtime_references = ModelInputRuntimeReferences.from_snapshots(
                graph,
                registrations,
                profile_fingerprint=self._profile_fingerprint_provider(),
            )
            prior_strict_snapshots = [
                (
                    snapshot
                    if index < len(self._sealed_message_cache)
                    and snapshot is not None
                    and snapshot.sealed is self._sealed_message_cache[index].sealed
                    else None
                )
                for index, snapshot in enumerate(self._strict_message_snapshots)
            ]
            message_shapes, reused_prefix_count = self._recheck_logical_messages(
                preparation.context.messages,
                logical_messages,
                message_shapes,
                reused_prefix_count,
                prior_strict_snapshots,
                self._strict_prefix_messages,
                self._strict_prefix_encoded,
            )
            committer = _call_on_owner_loop(
                owner_loop,
                lambda: self._transcript.create_model_input_committer(
                    purpose=preparation.purpose,
                    logical_input=logical_input,
                    runtime_references=runtime_references,
                ),
            )
            sealed_messages = committer.sealed_logical_messages
            sealed_input = committer.sealed_logical_input
            prior_source = self._last_prepared_source
            certified_provider_prefix_count = 0
            if (
                self._last_prepared_request is not None
                and prior_source
                and len(sealed_messages) == len(preparation.context.messages)
                and len(sealed_messages) >= len(prior_source)
                and isinstance(prior_source[-1], Mapping)
                and prior_source[-1].get("role") == "user"
                and all(
                    current is previous
                    for current, previous in zip(
                        sealed_messages, prior_source, strict=False
                    )
                )
            ):
                # The Model Input committer only shares these recursively
                # frozen nodes after proving the raw logical prefix exactly.
                certified_provider_prefix_count = len(prior_source)
            if len(sealed_messages) == len(preparation.context.messages):
                self._sealed_message_cache = tuple(
                    _SealedMessageReuse(
                        message,
                        (
                            shape
                            if index < reused_prefix_count
                            or shape == _sealed_message_shape(message)
                            else None
                        ),
                        sealed,
                    )
                    for index, (message, shape, sealed) in enumerate(
                        zip(
                            preparation.context.messages,
                            message_shapes,
                            sealed_messages,
                            strict=True,
                        )
                    )
                )
            else:
                self._sealed_message_cache = ()
            message_cache = self._sealed_message_cache
            matched_snapshots: list[_StrictMessageSnapshot | None] = []
            for index, sealed in enumerate(sealed_messages):
                snapshot = (
                    prior_strict_snapshots[index]
                    if index < len(prior_strict_snapshots)
                    else None
                )
                matched_snapshots.append(
                    snapshot
                    if snapshot is not None and snapshot.sealed is sealed
                    else None
                )
            strict_snapshots = tuple(matched_snapshots)
            options = replace(
                preparation.options,
                prepared_request_committer=_CurrentSessionCommitter(
                    committer=committer,
                    is_current=self._is_current,
                    turn_performance=self._turn_performance,
                    on_committed_prepared_request=(
                        lambda request: self._retain_prepared_request(
                            request, sealed_messages, message_cache
                        )
                    ),
                    on_committed_model_input=(
                        self._on_committed_evidence_free_input
                        if RESOURCE_EVIDENCE_COMPONENT not in logical_input
                        else None
                    ),
                    prepared_request_reuse=self._last_prepared_request,
                    certified_provider_prefix_count=(certified_provider_prefix_count),
                    current_provider_source_count=(
                        len(sealed_messages)
                        if len(sealed_messages) == len(preparation.context.messages)
                        else -1
                    ),
                    sealed_messages=sealed_messages,
                    sealed_message_shapes=tuple(
                        item.shape for item in self._sealed_message_cache
                    ),
                    strict_message_snapshots=strict_snapshots,
                    normalized_prefix_cache=self._normalized_cache,
                    on_committed_normalization=self._schedule_normalized_cache,
                    sealed_system_prompt=sealed_input["system_prompt"],
                    sealed_tools=sealed_input["tools"],
                    sealed_provider_window=sealed_input.get("provider_window"),
                ),
            )
        except BaseException:
            if self._turn_performance is not None:
                self._turn_performance.model_call_prepare_failed()
            raise
        if self._turn_performance is not None:
            self._turn_performance.model_call_prepared()
        return options


class _CurrentSessionCommitter(
    PreparedRequestCommitter,
    PreparedModelCallAttemptUsageRecorder,
    PreparedModelCallOutcomeRecorder,
    PreparedModelCallTerminalRecorder,
):
    """Carry current-Session ownership through AI's final commit barrier."""

    normalize_context_in_worker = True

    def __init__(
        self,
        *,
        committer: PreparedRequestCommitter,
        is_current: CurrentSessionPredicate,
        turn_performance: TurnStartPerformanceRuntime | None = None,
        on_committed_prepared_request: (
            Callable[[PreparedModelRequest], None] | None
        ) = None,
        on_committed_model_input: CommittedModelInputObserver | None = None,
        prepared_request_reuse: PreparedModelRequest | None = None,
        certified_provider_prefix_count: int = 0,
        current_provider_source_count: int = 0,
        sealed_messages: tuple[object, ...] = (),
        sealed_message_shapes: tuple[tuple[object, ...] | None, ...] = (),
        strict_message_snapshots: tuple[_StrictMessageSnapshot | None, ...] = (),
        normalized_prefix_cache: _NormalizedPrefixCache | None = None,
        on_committed_normalization: (
            Callable[
                [
                    tuple[object, ...],
                    Callable[[Context], Context],
                    Model,
                    PairingMode,
                ],
                None,
            ]
            | None
        ) = None,
        sealed_system_prompt: object = None,
        sealed_tools: object = (),
        sealed_provider_window: object = None,
    ) -> None:
        self._committer = committer
        self._is_current = is_current
        self._turn_performance = turn_performance
        self._on_committed_prepared_request = on_committed_prepared_request
        self._on_committed_model_input = on_committed_model_input
        self.prepared_request_reuse = prepared_request_reuse
        self.certified_provider_prefix_count = certified_provider_prefix_count
        self.current_provider_source_count = current_provider_source_count
        self._sealed_messages = sealed_messages
        self._sealed_message_shapes = sealed_message_shapes
        self._strict_message_snapshots = strict_message_snapshots
        self._normalized_prefix_cache = normalized_prefix_cache
        self._on_committed_normalization = on_committed_normalization
        self._normalization_model: Model | None = None
        self._normalization_pairing_mode: PairingMode | None = None
        self._sealed_system_prompt = sealed_system_prompt
        self._sealed_tools = sealed_tools
        self._sealed_provider_window = sealed_provider_window
        self._sealed_verification_task: asyncio.Task[None] | None = None
        self._latest_attempt_by_invocation: dict[str, tuple[int, str]] = {}

    def owned_sealed_context(self, context: Context) -> Context:
        """Build provider input from the same owned facts as Model Input."""

        if type(context) is not Context:
            raise TypeError("sealed Model Input requires a Context")
        messages: list[Message] = []
        for index, sealed in enumerate(self._sealed_messages):
            snapshot = (
                self._strict_message_snapshots[index]
                if index < len(self._strict_message_snapshots)
                else None
            )
            if snapshot is not None and snapshot.sealed is sealed:
                try:
                    if pickle.dumps(snapshot.message, protocol=5) == snapshot.encoded:
                        messages.append(snapshot.message)
                        continue
                except Exception:
                    pass
            raw = thaw_model_input_json(sealed)
            if not isinstance(raw, dict):
                raise RuntimeError("sealed Model Input message is invalid")
            messages.append(deserialize_message(raw))
        raw_tools = thaw_model_input_json(self._sealed_tools)
        if not isinstance(raw_tools, list):
            raise RuntimeError("sealed Model Input tools are invalid")
        tools = [
            Tool(
                name=cast(str, tool["name"]),
                description=cast(str, tool["description"]),
                parameters=cast(dict[str, Any], tool["parameters"]),
            )
            for tool in raw_tools
            if isinstance(tool, dict)
        ]
        if len(tools) != len(raw_tools):
            raise RuntimeError("sealed Model Input tools are invalid")
        return Context(
            system_prompt=cast(str | None, self._sealed_system_prompt),
            messages=messages,
            tools=tools,
            provider_window=(
                ProviderCompactionWindow.from_raw(
                    cast(
                        dict[str, object],
                        thaw_model_input_json(self._sealed_provider_window),
                    )
                )
                if self._sealed_provider_window is not None
                else None
            ),
        )

    def normalize_owned_context(
        self,
        context: Context,
        *,
        model: Model,
        pairing_mode: PairingMode,
    ) -> NormalizationResult:
        self._normalization_model = model
        self._normalization_pairing_mode = pairing_mode
        cache = self._normalized_prefix_cache
        prior_count = self.certified_provider_prefix_count
        key = _normalization_key(model, pairing_mode)
        if (
            model.api == "openai-completions"
            and context.provider_window is None
            and cache is not None
            and key is not None
            and cache.key == key
            and prior_count > 0
            and prior_count == len(cache.source)
            and len(context.messages) > prior_count
            and type(cache.result.context.messages[-1]) is UserMessage
            and all(
                sealed is previous
                for sealed, previous in zip(
                    self._sealed_messages, cache.source, strict=False
                )
            )
        ):
            suffix = context.messages[prior_count:]
            if type(suffix[0]) is AssistantMessage and not (
                _tool_ids(suffix) & cache.prior_tool_ids
            ):
                try:
                    if (
                        pickle.dumps(cache.result.context.messages, protocol=5)
                        == cache.encoded
                    ):
                        suffix_result = normalize_context_result(
                            Context(
                                system_prompt=context.system_prompt,
                                messages=suffix,
                                tools=context.tools,
                            ),
                            model=model,
                            pairing_mode=pairing_mode,
                        )
                        if not suffix_result.diagnostics:
                            return NormalizationResult(
                                context=NormalizedContext(
                                    system_prompt=context.system_prompt,
                                    messages=(
                                        cache.result.context.messages
                                        + suffix_result.context.messages
                                    ),
                                    tools=suffix_result.context.tools,
                                ),
                                diagnostics=cache.result.diagnostics,
                            )
                except Exception:
                    pass
        return normalize_context_result(context, model=model, pairing_mode=pairing_mode)

    def _prewarm_normalized_prefix_for_tool(
        self, outcome: PreparedModelCallOutcome
    ) -> None:
        if (
            outcome.stop_reason == "toolUse"
            and self._on_committed_normalization is not None
            and self._normalization_model is not None
            and self._normalization_pairing_mode is not None
        ):
            self._on_committed_normalization(
                self._sealed_messages,
                self.owned_sealed_context,
                self._normalization_model,
                self._normalization_pairing_mode,
            )

    def verify_sealed_context(self, context: Context) -> None:
        """Reject a context changed after its durable logical projection."""

        if (
            type(context) is not Context
            or context.system_prompt != self._sealed_system_prompt
            or freeze_model_input_json(
                context.provider_window.to_raw()
                if context.provider_window is not None
                else None,
                name="current provider compaction window",
            )
            != self._sealed_provider_window
            or len(context.messages) != len(self._sealed_messages)
            or len(self._sealed_message_shapes) != len(self._sealed_messages)
            or freeze_model_input_json(
                project_model_tools(context.tools or ()),
                name="current Model Input tools",
            )
            != self._sealed_tools
        ):
            raise RuntimeError("sealed Model Input context changed")
        for index, (message, shape, sealed) in enumerate(
            zip(
                context.messages,
                self._sealed_message_shapes,
                self._sealed_messages,
                strict=True,
            )
        ):
            snapshot = (
                self._strict_message_snapshots[index]
                if index < len(self._strict_message_snapshots)
                else None
            )
            if (
                snapshot is not None
                and snapshot.sealed is sealed
                and _strict_snapshot_matches(message, snapshot)
            ):
                continue
            if shape is not None:
                if _sealed_message_shape(message) != shape:
                    raise RuntimeError("sealed Model Input context changed")
            elif (
                freeze_model_input_json(
                    serialize_message(message), name="current Model Input message"
                )
                != sealed
            ):
                raise RuntimeError("sealed Model Input context changed")

    def start_sealed_context_verification(self, context: Context) -> None:
        if self._sealed_verification_task is not None:
            raise RuntimeError("sealed Model Input verification already started")
        task = asyncio.create_task(
            asyncio.to_thread(self.verify_sealed_context, context)
        )
        self._sealed_verification_task = task
        task.add_done_callback(self._finish_sealed_verification)

    @staticmethod
    def _finish_sealed_verification(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def commit_prepared_request(self, request: PreparedModelRequest) -> None:
        if self._sealed_verification_task is not None:
            await self._sealed_verification_task
        self._require_current()
        if self._turn_performance is not None:
            self._turn_performance.model_input_commit_started(request)
        try:
            await self._committer.commit_prepared_request(request)
        except BaseException:
            if self._turn_performance is not None:
                self._turn_performance.model_input_commit_failed(request)
            raise
        self._require_current()
        commits = getattr(self._committer, "commits", ())
        if not commits:
            raise RuntimeError("durable Model Input commit produced no snapshot")
        snapshot_id = getattr(commits[-1], "snapshot_id", None)
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise RuntimeError("durable Model Input commit produced no snapshot id")
        self._latest_attempt_by_invocation[request.invocation_id] = (
            request.attempt,
            snapshot_id,
        )
        self.prepared_request_reuse = request
        if self._on_committed_prepared_request is not None:
            self._on_committed_prepared_request(request)
        if self._on_committed_model_input is not None:
            self._on_committed_model_input(snapshot_id)
        if self._turn_performance is not None:
            self._turn_performance.transport_ready(request)

    async def prewarm_logical_input(self) -> None:
        """Overlap immutable logical encoding with provider request sealing."""

        self._require_current()
        prewarm = getattr(self._committer, "prewarm_logical_input", None)
        if callable(prewarm):
            await prewarm()
        self._require_current()

    async def record_prepared_model_call_attempt_usage(
        self,
        observation: PreparedModelCallAttemptUsage,
    ) -> bool:
        self._require_current()
        if not isinstance(self._committer, ModelInputTranscriptCommitter):
            raise TypeError(
                "durable Session Model Input committer cannot record attempt usage"
            )
        attempt_identity = self._latest_attempt_by_invocation.get(
            observation.invocation_id
        )
        if attempt_identity is None:
            raise RuntimeError(
                "attempt usage has no committed Model Input snapshot identity"
            )
        attempt, snapshot_id = attempt_identity
        usage = observation.usage
        recorded = await self._committer.record_model_call_attempt_usage(
            ModelCallAttemptUsage(
                invocation_id=observation.invocation_id,
                attempt=attempt,
                model_input_snapshot_id=snapshot_id,
                input=usage.input,
                output=usage.output,
                cache_read=usage.cache_read,
                cache_write=usage.cache_write,
                total_tokens=usage.total_tokens,
                terminal=observation.terminal,
            )
        )
        self._require_current()
        return recorded

    async def record_model_call_outcome(
        self,
        outcome: PreparedModelCallOutcome,
    ) -> None:
        self._require_current()
        if not isinstance(self._committer, PreparedModelCallOutcomeRecorder):
            raise TypeError(
                "durable Session Model Input committer cannot record outcomes"
            )
        await self._committer.record_model_call_outcome(outcome)
        self._require_current()
        self._prewarm_normalized_prefix_for_tool(outcome)

    async def record_terminal_model_call(
        self,
        outcome: PreparedModelCallOutcome,
        *,
        usage_observed: bool,
    ) -> None:
        self._require_current()
        if not isinstance(self._committer, ModelInputTranscriptCommitter):
            raise TypeError(
                "durable Session Model Input committer cannot record terminal facts"
            )
        usage = None
        if usage_observed:
            attempt_identity = self._latest_attempt_by_invocation.get(
                outcome.invocation_id
            )
            if attempt_identity is None:
                raise RuntimeError(
                    "terminal usage has no committed Model Input snapshot identity"
                )
            attempt, snapshot_id = attempt_identity
            observed = outcome.usage
            usage = ModelCallAttemptUsage(
                invocation_id=outcome.invocation_id,
                attempt=attempt,
                model_input_snapshot_id=snapshot_id,
                input=observed.input,
                output=observed.output,
                cache_read=observed.cache_read,
                cache_write=observed.cache_write,
                total_tokens=observed.total_tokens,
                terminal=True,
            )
        await self._committer.record_terminal_model_call(outcome, usage=usage)
        self._require_current()
        self._prewarm_normalized_prefix_for_tool(outcome)

    @property
    def model_input_snapshot_ids(self) -> tuple[str, ...]:
        commits = getattr(self._committer, "commits", ())
        return tuple(
            commit.snapshot_id
            for commit in commits
            if isinstance(getattr(commit, "snapshot_id", None), str)
        )

    def _require_current(self) -> None:
        if self._is_current() is not True:
            raise RuntimeError("Session is not current; model transport is forbidden")


@dataclass(frozen=True)
class SessionModelCallCapabilityConsumer:
    """Adapt the declared preparation facet without receiving the graph runtime."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != MODEL_INPUT_PREPARATION_REQUIREMENT:
            raise ValueError("model-call Consumer received the wrong facet view")

    def prepare(
        self,
        preparation: ModelCallPreparation,
        *,
        owner_loop: asyncio.AbstractEventLoop | None = None,
    ) -> CallOptions:
        preparer = cast(
            SessionModelCallPreparer,
            self.facets.require(MODEL_INPUT_PREPARATION_FACET),
        )
        return preparer(preparation, owner_loop=owner_loop)


@dataclass(frozen=True)
class SessionModelCallCapabilityBinding:
    """Immutable built-in Provider input for the Session composition root."""

    provider_binding: CapabilityBundleProviderBinding


def build_session_model_call_capability_binding(
    *,
    transcript: ModelInputTranscriptPort,
    projector: RuntimeCapabilityGraphProjector,
    product_id: str,
    runtime_id: str,
    is_current: CurrentSessionPredicate,
    registration_entries_provider: RegistrationEntriesProvider,
    profile_fingerprint_provider: CurrentProfileFingerprintProvider,
    conversation_id: str | None = None,
    session_provider: CapabilityBundleProvider | None = None,
    resources_provider: CapabilityBundleProvider | None = None,
    workspace_provider: CapabilityBundleProvider | None = None,
    turn_performance: TurnStartPerformanceRuntime | None = None,
    request_evidence_provider: RequestEvidenceProvider | None = None,
    on_committed_evidence_free_input: CommittedModelInputObserver | None = None,
) -> SessionModelCallCapabilityBinding:
    """Build data-only graph inputs without acquiring graph lifecycle authority."""

    if resources_provider is not None and session_provider is None:
        raise ValueError(
            "model-call binding cannot use a Resources Provider without a Session Provider"
        )
    if workspace_provider is not None and session_provider is None:
        raise ValueError(
            "model-call binding cannot use a Workspace Provider without a Session Provider"
        )
    if session_provider is not None and resources_provider is None:
        raise ValueError(
            "model-call binding requires the Session Provider's Resources dependency"
        )
    _require_transcript_port(transcript, name="model-call binding")
    if not isinstance(projector, RuntimeCapabilityGraphProjector):
        raise TypeError("model-call binding requires graph projection")
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("model-call binding Product id must be non-empty")
    if not isinstance(runtime_id, str) or not runtime_id.strip():
        raise ValueError("model-call binding runtime id must be non-empty")
    for callback, name in (
        (is_current, "current-Session check"),
        (registration_entries_provider, "registration inventory"),
        (profile_fingerprint_provider, "current Profile facts"),
    ):
        if not callable(callback):
            raise TypeError(f"model-call binding requires {name}")
    if request_evidence_provider is not None and not callable(
        request_evidence_provider
    ):
        raise TypeError("model-call binding request evidence must be callable")

    resolved_conversation_id = conversation_id or getattr(
        getattr(transcript, "header", None),
        "conversation_id",
        None,
    )
    if not isinstance(resolved_conversation_id, str) or not resolved_conversation_id:
        raise ValueError("model-call binding requires a conversation id")

    provider = CapabilityBundleProvider(
        capability_id=MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
        provider_id="harness.model_input.standard",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=MODEL_INPUT_CAPABILITY_DEFINITION.facets,
        requirements=(
            (SESSION_TRANSCRIPT_REQUIREMENT,) if session_provider is not None else ()
        ),
        required_authorities=frozenset({"transcript"}),
        source_id="builtin",
        selection_rule="Product durable Model Input selection",
    )

    def build_value(
        transcript_port: ModelInputTranscriptPort,
    ) -> CapabilityBundleValue:
        return CapabilityBundleValue(
            (
                CapabilityFacetBinding(
                    MODEL_INPUT_PREPARATION_FACET,
                    SessionModelCallPreparer(
                        transcript=transcript_port,
                        projector=projector,
                        is_current=is_current,
                        registration_entries_provider=registration_entries_provider,
                        profile_fingerprint_provider=profile_fingerprint_provider,
                        turn_performance=turn_performance,
                        request_evidence_provider=request_evidence_provider,
                        on_committed_evidence_free_input=(
                            on_committed_evidence_free_input
                        ),
                    ),
                ),
            )
        )

    if session_provider is None:

        def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
            del context
            return build_value(transcript)

    else:

        def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
            return build_value(
                _DependencyModelInputTranscriptPort(
                    context.dependency(SESSION_CAPABILITY_DEFINITION.capability_id)
                )
            )

    return SessionModelCallCapabilityBinding(
        provider_binding=CapabilityBundleProviderBinding(
            provider=provider,
            scope_instance_id=runtime_id,
            binding_input_fingerprint=_fingerprint(
                {
                    "conversation_id": resolved_conversation_id,
                    "runtime_id": runtime_id,
                }
            ),
            create=create,
        ),
    )


class SessionModelCallRuntime:
    """Consume the Session-owned model-input facet and read-only projection."""

    def __init__(
        self,
        *,
        transcript: ModelInputTranscriptPort,
        ensure_consumer: Callable[[], Awaitable[SessionModelCallCapabilityConsumer]],
        projector: RuntimeCapabilityGraphProjector,
        registration_entries_provider: RegistrationEntriesProvider | None = None,
        source_publication_provider: SourcePublicationProvider | None = None,
    ) -> None:
        _require_transcript_port(transcript, name="model-call runtime")
        if not callable(ensure_consumer):
            raise TypeError("model-call runtime requires a typed Consumer port")
        if not isinstance(projector, RuntimeCapabilityGraphProjector):
            raise TypeError("model-call runtime requires graph projection")
        if registration_entries_provider is not None and not callable(
            registration_entries_provider
        ):
            raise TypeError(
                "model-call runtime registration inventory must be callable"
            )
        if source_publication_provider is not None and not callable(
            source_publication_provider
        ):
            raise TypeError("model-call runtime source publication must be callable")

        self._transcript = transcript
        self._ensure_consumer = ensure_consumer
        self._projector = projector
        self._registration_entries_provider = registration_entries_provider or (
            lambda: ()
        )
        self._source_publication_provider = source_publication_provider or (
            lambda: None
        )
        self._prepare_lock = asyncio.Lock()

    def effective_view(
        self,
        profile: RuntimeProfileSnapshot,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> EffectiveRuntimeView:
        return self._projector.effective_view(
            profile,
            model_surface=self._model_surface(model_input_snapshot_id),
            registrations=self._registration_inventory(),
            source_publication=self._source_publication_provider(),
        )

    def explain_capability(
        self,
        profile: RuntimeProfileSnapshot,
        capability_id: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> CapabilityGraphExplanation:
        model_surface = self._model_surface(model_input_snapshot_id)
        return self._projector.explain(
            capability_id,
            profile=profile,
            model_surface=model_surface,
            registrations=self._registration_inventory(),
            source_publication=self._source_publication_provider(),
        )

    def explain_profile_slot(
        self,
        profile: RuntimeProfileSnapshot,
        slot: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> RuntimeProfileSlotExplanation:
        return self._projector.explain_profile_slot(
            profile,
            slot,
            model_surface=self._model_surface(model_input_snapshot_id),
            registrations=self._registration_inventory(),
        )

    def explain_registration(
        self,
        profile: RuntimeProfileSnapshot,
        registration_id: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> RegistrationExplanation:
        return self._projector.explain_registration(
            registration_id,
            profile=profile,
            model_surface=self._model_surface(model_input_snapshot_id),
            registrations=self._registration_inventory(),
        )

    def diff(
        self,
        before: EffectiveRuntimeView,
        after: EffectiveRuntimeView,
    ) -> EffectiveRuntimeDiff:
        return self._projector.diff(before, after)

    def to_json(
        self,
        value: EffectiveRuntimeView
        | EffectiveRuntimeDiff
        | CapabilityGraphExplanation
        | RuntimeProfileSlotExplanation
        | RegistrationExplanation,
    ) -> dict[str, JSONValue]:
        return self._projector.to_json(value)

    async def prepare(self, preparation: ModelCallPreparation) -> CallOptions:
        consumer = await self._ensure_consumer()
        # Preparation serializes and seals the full logical request. Keep the
        # event loop available for input and cancellation while preserving the
        # old single-consumer ordering if a cancelled worker is still running.
        await self._prepare_lock.acquire()
        try:
            worker = asyncio.create_task(
                asyncio.to_thread(
                    consumer.prepare,
                    preparation,
                    owner_loop=asyncio.get_running_loop(),
                )
            )
        except BaseException:
            self._prepare_lock.release()
            raise
        worker.add_done_callback(self._finish_prepare_worker)
        return await asyncio.shield(worker)

    def _finish_prepare_worker(self, worker: asyncio.Task[CallOptions]) -> None:
        self._prepare_lock.release()
        if not worker.cancelled():
            worker.exception()

    def _registration_inventory(self) -> RegistrationInventorySnapshot:
        return compose_registration_inventory(
            self._projector.registration_inventory(),
            self._registration_entries_provider(),
        )

    def _model_surface(
        self,
        snapshot_id: str | None,
    ) -> ModelSurfaceReference | None:
        if snapshot_id is None:
            return None
        snapshot = self._transcript.rebuild_model_input(snapshot_id).snapshot
        return ModelSurfaceReference(
            schema_version=1,
            snapshot_id=snapshot.snapshot_id,
            product_id=snapshot.product_id,
            runtime_id=snapshot.runtime_id,
            profile_fingerprint=snapshot.profile_fingerprint,
            mount_generation=snapshot.mount_generation,
            registration_revision=snapshot.registration_revision,
        )


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_transcript_port(
    value: object,
    *,
    name: str,
) -> None:
    if not callable(getattr(value, "create_model_input_committer", None)):
        raise TypeError(f"{name} requires a Model Input transcript port")
    if not callable(getattr(value, "rebuild_model_input", None)):
        raise TypeError(f"{name} requires a Model Input transcript port")


def _logical_input(
    preparation: ModelCallPreparation,
    *,
    serialized_messages: list[object] | None = None,
) -> dict[str, object]:
    context = preparation.context
    logical_input: dict[str, object] = {
        "system_prompt": context.system_prompt,
        "messages": (
            serialized_messages
            if serialized_messages is not None
            else [serialize_message(message) for message in context.messages]
        ),
        "tools": project_model_tools(context.tools or ()),
        "request_options": project_model_request_options(preparation.options),
    }
    if context.provider_window is not None:
        logical_input["provider_window"] = context.provider_window.to_raw()
    return logical_input


def project_model_tools(tools: Iterable[Any]) -> list[dict[str, JSONValue]]:
    """Project Agent tools exactly as the durable logical Model Input does."""

    return [
        {
            "name": str(tool.name),
            "description": str(tool.description),
            "parameters": require_json_mapping(
                tool.parameters,
                name=f"Model Input Tool schema {tool.name!r}",
            ),
        }
        for tool in tools
    ]


def project_model_request_options(options: CallOptions) -> dict[str, JSONValue]:
    """Project token-relevant request options into durable logical JSON."""

    projected: dict[str, JSONValue] = {}
    for name in (
        "cache_retention",
        "cache_key",
        "max_output_tokens",
        "temperature",
    ):
        value = getattr(options, name)
        if value is not None:
            projected[name] = require_json_value(
                value,
                name=f"Model Input request option {name!r}",
            )

    if options.reasoning is not None:
        projected["reasoning"] = require_json_mapping(
            {
                "enabled": options.reasoning.enabled,
                "effort": options.reasoning.effort,
                "budget_tokens": options.reasoning.budget_tokens,
                "expose_summary": options.reasoning.expose_summary,
            },
            name="Model Input reasoning options",
        )
    if options.tool_choice is not None:
        projected["tool_choice"] = require_json_value(
            options.tool_choice,
            name="Model Input Tool choice",
        )
    if options.output is not None:
        projected["output"] = _structured_output(options.output)
    if options.request_limits is not None:
        projected["request_limits"] = require_json_mapping(
            {
                name: value
                for name in (
                    "max_canonical_bytes",
                    "max_estimated_wire_bytes",
                    "max_message_count",
                    "max_image_bytes",
                    "max_tool_schema_bytes",
                    "max_estimated_input_tokens",
                )
                if (value := getattr(options.request_limits, name)) is not None
            },
            name="Model Input request capacity limits",
        )
    return projected


def _structured_output(output: StructuredOutputOptions) -> dict[str, JSONValue]:
    projected: dict[str, object] = {
        "mode": output.mode,
        "strict": output.strict,
    }
    if output.schema is not None:
        projected["schema"] = _structured_output_schema(output.schema)
    return require_json_mapping(projected, name="Model Input structured output")


def _structured_output_schema(
    schema: Mapping[str, JSONValue] | type,
) -> dict[str, JSONValue]:
    if isinstance(schema, Mapping):
        return require_json_mapping(schema, name="Model Input structured output schema")
    for method_name in ("model_json_schema", "schema"):
        method = getattr(schema, method_name, None)
        if callable(method):
            value = method()
            if isinstance(value, Mapping):
                return require_json_mapping(
                    value,
                    name="Model Input structured output schema",
                )
    raise TypeError("structured output type must expose a JSON schema")


__all__ = [
    "CurrentSessionPredicate",
    "project_model_request_options",
    "project_model_tools",
    "SessionModelCallCapabilityConsumer",
    "SessionModelCallPreparer",
    "SessionModelCallRuntime",
]
