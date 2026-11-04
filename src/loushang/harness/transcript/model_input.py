"""Commit and reconstruct one provider request from transcript facts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import InitVar, dataclass, field, replace
from types import MappingProxyType
from typing import Protocol, cast
from uuid import uuid4

from loushang.ai.prepared_request import (
    FrozenJSONValue,
    PreparedModelCallOutcome,
    PreparedModelCallOutcomeRecorder,
    PreparedModelRequest,
    PreparedRequestCommitter,
    PreparedRequestMetrics,
)
from loushang.foundation.json import JSONValue, validate_json_value
from loushang.foundation.observability import get_log
from loushang.harness.capabilities import (
    MountGraphSnapshot,
    RegistrationInventorySnapshot,
)
from loushang.harness.transcript.kinds import (
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_blobs import (
    MODEL_INPUT_BINARY_PROJECTION_VERSION,
    ModelInputBinaryProjectionError,
    SessionModelInputBlobCodec,
)
from loushang.harness.transcript.model_input_timing import (
    PhaseTimer,
    PhaseTimingSnapshot,
)
from loushang.harness.transcript.model_input_types import (
    MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
    ModelInputComponent,
    ModelInputComponentReference,
    ModelInputIntegrityError,
    ModelInputSnapshot,
    canonical_model_input_json,
    freeze_model_input_json,
    hash_model_input_json,
    thaw_model_input_json,
)
from loushang.harness.transcript.model_input_v2 import (
    ModelInputV2MaterializationStats,
    ModelInputV2Resolver,
    ModelInputV2Writer,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    ModelInputSnapshotV2,
)
from loushang.harness.transcript.model_usage_types import ModelCallAttemptUsage
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork

ModelInputLogicalProjection = dict[str, object]
_MODEL_INPUT_PERFORMANCE_LOG = get_log(__name__).bind(component="ModelInputCommit")
_LOGICAL_BINARY_MARKERS = (
    '"$loushang.sessionBlob"',
    '"$loushang.literal"',
    '"type":"image"',
)


class _DigestState(Protocol):
    def copy(self) -> _DigestState: ...

    def update(self, data: bytes) -> None: ...

    def hexdigest(self) -> str: ...


@dataclass(frozen=True)
class ModelInputCommitContext:
    """Provider-neutral logical materialization captured for one main turn."""

    purpose: str
    source_leaf_id: str
    source_revision: int
    logical_input: Mapping[str, object] = field(repr=False)
    reuse_from: InitVar[ModelInputCommitContext | None] = None
    _message_canonical_prefix: tuple[str, ...] = field(
        default=(), init=False, repr=False, compare=False
    )
    _message_canonical_parts: tuple[str, ...] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _reused_message_prefix_count: int = field(
        default=0, init=False, repr=False, compare=False
    )
    _owned_reuse_from: ModelInputCommitContext | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_canonical: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_digest: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_message_offset: int | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_prefix_digest: _DigestState | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_prefix_hash: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_other_fields: Mapping[str, str] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _owned_tail: str | None = field(default=None, init=False, repr=False, compare=False)
    _owned_prefix_tail: str = field(default="", init=False, repr=False, compare=False)
    _owned_binary_markers: frozenset[str] = field(
        default=frozenset(), init=False, repr=False, compare=False
    )

    def __post_init__(self, reuse_from: ModelInputCommitContext | None) -> None:
        _require_text(self.purpose, name="Model Input purpose")
        _require_text(self.source_leaf_id, name="Model Input source leaf id")
        _require_non_negative_int(
            self.source_revision,
            name="Model Input source revision",
        )
        frozen = _freeze_logical_input_with_prefix(self.logical_input, reuse_from)
        if not isinstance(frozen, Mapping):
            raise TypeError("Model Input logical projection must be a mapping")
        required = {"system_prompt", "messages", "tools", "request_options"}
        missing = sorted(required.difference(frozen))
        if missing:
            raise ValueError(
                "Model Input logical projection is missing: " + ", ".join(missing)
            )
        if not isinstance(frozen["messages"], tuple):
            raise TypeError("Model Input messages must be an array")
        if not isinstance(frozen["tools"], tuple):
            raise TypeError("Model Input tools must be an array")
        if not isinstance(frozen["request_options"], Mapping):
            raise TypeError("Model Input request options must be an object")
        object.__setattr__(self, "logical_input", frozen)
        if reuse_from is not None:
            previous_messages = reuse_from.logical_input.get("messages")
            if isinstance(previous_messages, tuple):
                reused = 0
                for current, prior in zip(
                    frozen["messages"], previous_messages, strict=False
                ):
                    if current is not prior:
                        break
                    reused += 1
                object.__setattr__(self, "_reused_message_prefix_count", reused)
                if reused == len(previous_messages):
                    object.__setattr__(self, "_owned_reuse_from", reuse_from)
                if reuse_from._message_canonical_parts is not None:
                    object.__setattr__(
                        self,
                        "_message_canonical_prefix",
                        reuse_from._message_canonical_parts[:reused],
                    )

    def _canonical_logical_input_json(self, value: dict[str, JSONValue]) -> str:
        """Encode an owned thaw, reusing only the freeze-proven message prefix."""

        name = "logical Model Input"
        prefix = self._message_canonical_prefix
        frozen_messages = self.logical_input["messages"]
        if (
            not prefix
            or not isinstance(frozen_messages, tuple)
            or len(prefix) > len(frozen_messages)
            or any(type(key) is not str for key in self.logical_input)
        ):
            canonical = canonical_model_input_json(value, name=name)
            messages = value["messages"]
            if isinstance(messages, list):
                parts = tuple(
                    canonical_model_input_json(
                        message,
                        name=f"{name}.messages[{index}]",
                    )
                    for index, message in enumerate(messages)
                )
                object.__setattr__(self, "_message_canonical_parts", parts)
            return canonical

        parts = prefix + tuple(
            canonical_model_input_json(message, name=f"{name}.messages[{index}]")
            for index, message in enumerate(frozen_messages[len(prefix) :], len(prefix))
        )
        fields = []
        for key in sorted(self.logical_input):
            encoded = (
                "[" + ",".join(parts) + "]"
                if key == "messages"
                else canonical_model_input_json(
                    self.logical_input[key], name=f"{name}.{key}"
                )
            )
            fields.append(json.dumps(key, ensure_ascii=False) + ":" + encoded)
        canonical = "{" + ",".join(fields) + "}"
        object.__setattr__(self, "_message_canonical_parts", parts)
        return canonical

    def _canonical_owned_logical_input(
        self, value: dict[str, JSONValue]
    ) -> tuple[str | None, str]:
        """Hash an exact sealed append without materializing historical text."""

        previous = self._owned_reuse_from
        messages = self.logical_input["messages"]
        assert isinstance(messages, tuple)
        other_fields = {
            name: canonical_model_input_json(item, name=f"logical Model Input.{name}")
            for name, item in self.logical_input.items()
            if name != "messages"
        }
        if (
            previous is not None
            and previous._owned_tail is not None
            and previous._owned_other_fields == other_fields
            and previous._owned_message_offset is not None
            and previous._owned_prefix_digest is not None
            and previous._owned_prefix_digest.copy().hexdigest()
            == previous._owned_prefix_hash
            and previous._message_canonical_parts is not None
            and len(previous._message_canonical_parts)
            == self._reused_message_prefix_count
            and previous._owned_tail.startswith("]")
        ):
            suffix = tuple(
                canonical_model_input_json(
                    message,
                    name=f"logical Model Input.messages[{index}]",
                )
                for index, message in enumerate(
                    messages[self._reused_message_prefix_count :],
                    self._reused_message_prefix_count,
                )
            )
            added = (
                "," if self._reused_message_prefix_count and suffix else ""
            ) + ",".join(suffix)
            prefix_digest = previous._owned_prefix_digest.copy()
            prefix_digest.update(added.encode("utf-8"))
            full_digest = prefix_digest.copy()
            full_digest.update(previous._owned_tail.encode("utf-8"))
            digest = "sha256:" + full_digest.hexdigest()
            object.__setattr__(
                self,
                "_message_canonical_parts",
                previous._message_canonical_parts + suffix,
            )
            self._retain_owned_canonical(
                None,
                digest,
                previous._owned_message_offset + len(added),
                prefix_digest,
                other_fields,
                tail=previous._owned_tail,
                prefix_tail=(previous._owned_prefix_tail + added)[-32:],
                binary_markers=previous._owned_binary_markers.union(
                    marker
                    for marker in _LOGICAL_BINARY_MARKERS
                    if marker in added
                    or marker in previous._owned_prefix_tail + added[:32]
                    or marker in added[-32:] + previous._owned_tail[:32]
                ),
            )
            object.__setattr__(self, "_owned_reuse_from", None)
            return None, digest

        canonical = self._canonical_logical_input_json(value)
        digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        parts = self._message_canonical_parts
        fallback_offset: int | None = None
        if parts is not None:
            position = 1
            for index, name in enumerate(sorted(self.logical_input)):
                if index:
                    position += 1
                position += len(json.dumps(name, ensure_ascii=False)) + 1
                if name == "messages":
                    fallback_offset = (
                        position + 1 + sum(map(len, parts)) + max(0, len(parts) - 1)
                    )
                    break
                position += len(other_fields[name])
        fallback_prefix_digest = (
            hashlib.sha256(canonical[:fallback_offset].encode("utf-8"))
            if fallback_offset is not None
            and canonical[fallback_offset : fallback_offset + 1] == "]"
            else None
        )
        self._retain_owned_canonical(
            canonical,
            digest,
            fallback_offset if fallback_prefix_digest is not None else None,
            fallback_prefix_digest,
            other_fields,
            tail=canonical[fallback_offset:]
            if fallback_prefix_digest is not None
            else None,
            prefix_tail=canonical[max(0, fallback_offset - 32) : fallback_offset]
            if fallback_prefix_digest is not None and fallback_offset is not None
            else "",
            binary_markers=frozenset(
                marker for marker in _LOGICAL_BINARY_MARKERS if marker in canonical
            ),
        )
        object.__setattr__(self, "_owned_reuse_from", None)
        return canonical, digest

    def _retain_owned_canonical(
        self,
        canonical: str | None,
        digest: str,
        offset: int | None,
        prefix_digest: _DigestState | None,
        other_fields: Mapping[str, str],
        *,
        tail: str | None,
        prefix_tail: str,
        binary_markers: frozenset[str],
    ) -> None:
        object.__setattr__(self, "_owned_canonical", canonical)
        object.__setattr__(self, "_owned_digest", digest)
        object.__setattr__(self, "_owned_message_offset", offset)
        object.__setattr__(self, "_owned_prefix_digest", prefix_digest)
        object.__setattr__(
            self,
            "_owned_prefix_hash",
            prefix_digest.hexdigest() if prefix_digest is not None else None,
        )
        object.__setattr__(
            self, "_owned_other_fields", MappingProxyType(dict(other_fields))
        )
        object.__setattr__(self, "_owned_tail", tail)
        object.__setattr__(self, "_owned_prefix_tail", prefix_tail)
        object.__setattr__(self, "_owned_binary_markers", frozenset(binary_markers))


def _freeze_logical_input_with_prefix(
    value: Mapping[str, object],
    previous: ModelInputCommitContext | None,
) -> object:
    name = "Model Input logical projection"
    if previous is None or not isinstance(value, Mapping):
        return freeze_model_input_json(value, name=name)
    raw_messages = value.get("messages")
    old_messages = previous.logical_input.get("messages")
    if (
        not isinstance(raw_messages, Sequence)
        or isinstance(raw_messages, str | bytes | bytearray)
        or not isinstance(old_messages, tuple)
    ):
        return freeze_model_input_json(value, name=name)
    reused = 0
    for raw, frozen in zip(raw_messages, old_messages, strict=False):
        if not _raw_matches_frozen_json(raw, frozen, seen=set()):
            break
        reused += 1
    fields: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{name} keys must be strings")
        if key == "messages":
            fields[key] = old_messages[:reused] + tuple(
                freeze_model_input_json(
                    raw,
                    name=f"{name}.messages[{index}]",
                )
                for index, raw in enumerate(raw_messages[reused:], reused)
            )
        else:
            fields[key] = freeze_model_input_json(item, name=f"{name}.{key}")
    return MappingProxyType(fields)


def _logical_input_for_materialization(
    frozen: Mapping[str, object],
) -> dict[str, JSONValue]:
    """Reuse sealed message values until the writer needs a changed item.

    The v2 writer checks the immutable message source against its verified
    sequence prefix and canonicalizes any unmatched values itself. Only the
    top-level array must be mutable for sequence planning.
    """

    projected: dict[str, JSONValue] = {}
    for name, value in frozen.items():
        if name == "messages" and isinstance(value, tuple):
            projected[name] = cast(JSONValue, list(value))
        else:
            projected[name] = thaw_model_input_json(value)
    return projected


def _prepared_payload_for_materialization(
    frozen: Mapping[str, FrozenJSONValue],
) -> dict[str, JSONValue]:
    # PreparedModelRequest owns recursively frozen JSON and its canonical
    # digest. The writer accepts sealed values; only its top-level sequence
    # planner needs native lists.
    return {
        name: cast(JSONValue, list(value) if isinstance(value, tuple) else value)
        for name, value in frozen.items()
    }


def _raw_matches_frozen_json(
    raw: object,
    frozen: object,
    *,
    seen: set[int],
) -> bool:
    if raw is frozen:
        # Only the previous owned, recursively frozen context can supply this
        # object. Identity proves the complete value without walking it again.
        return True
    if isinstance(frozen, Mapping):
        if not isinstance(raw, Mapping) or len(raw) != len(frozen):
            return False
        identity = id(raw)
        if identity in seen:
            return False
        seen.add(identity)
        try:
            return all(
                type(key) is str
                and key in frozen
                and _raw_matches_frozen_json(item, frozen[key], seen=seen)
                for key, item in raw.items()
            )
        finally:
            seen.remove(identity)
    if isinstance(frozen, tuple):
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, str | bytes | bytearray)
            or len(raw) != len(frozen)
        ):
            return False
        identity = id(raw)
        if identity in seen:
            return False
        seen.add(identity)
        try:
            return all(
                _raw_matches_frozen_json(item, old, seen=seen)
                for item, old in zip(raw, frozen, strict=True)
            )
        finally:
            seen.remove(identity)
    if type(raw) is not type(frozen):
        return False
    if type(raw) is float and raw == frozen == 0.0:
        return math.copysign(1.0, raw) == math.copysign(1.0, frozen)
    return raw == frozen


@dataclass(frozen=True)
class ModelInputRuntimeReferences:
    product_id: str
    runtime_id: str
    mount_generation: int
    profile_fingerprint: str
    registration_revision: str

    @classmethod
    def from_snapshots(
        cls,
        graph: MountGraphSnapshot,
        registrations: RegistrationInventorySnapshot,
        *,
        profile_fingerprint: str | None = None,
    ) -> ModelInputRuntimeReferences:
        if not isinstance(graph, MountGraphSnapshot):
            raise TypeError("Model Input requires a committed MountGraphSnapshot")
        if not isinstance(registrations, RegistrationInventorySnapshot):
            raise TypeError(
                "Model Input requires a committed RegistrationInventorySnapshot"
            )
        if graph.schema_version != 1 or registrations.schema_version != 1:
            raise ValueError(
                "Model Input does not support this runtime snapshot version"
            )
        if (
            registrations.graph_id != graph.graph_id
            or registrations.runtime_id != graph.runtime_id
            or registrations.mount_generation != graph.generation
        ):
            raise ValueError("Mount graph and registration inventory clocks diverge")
        return cls(
            product_id=graph.product_id,
            runtime_id=graph.runtime_id,
            mount_generation=graph.generation,
            profile_fingerprint=(
                graph.profile_fingerprint
                if profile_fingerprint is None
                else profile_fingerprint
            ),
            registration_revision=registrations.revision,
        )

    def __post_init__(self) -> None:
        _require_text(self.product_id, name="Model Input Product id")
        _require_text(self.runtime_id, name="Model Input runtime id")
        _require_non_negative_int(
            self.mount_generation,
            name="Model Input Mount generation",
        )
        _require_fingerprint(
            self.profile_fingerprint,
            name="Model Input Profile fingerprint",
        )
        _require_fingerprint(
            self.registration_revision,
            name="Model Input registration revision",
        )


@dataclass(frozen=True)
class ModelInputCommitResult:
    snapshot_id: str
    record_id: str
    source_revision: int
    commit_revision: int


@dataclass(frozen=True)
class RebuiltModelInput:
    snapshot: ModelInputSnapshot | ModelInputSnapshotV2
    commit_revision: int
    logical_input: dict[str, JSONValue]
    prepared_payload: dict[str, JSONValue]
    model_visible_headers: dict[str, str]
    canonical_prepared_payload: str
    logical_input_hash: str
    prepared_payload_hash: str


@dataclass(frozen=True)
class ModelInputReconstructionVerification:
    snapshot_id: str
    logical_input_matches: bool
    prepared_payload_matches: bool

    @property
    def verified(self) -> bool:
        return self.logical_input_matches and self.prepared_payload_matches


class ModelInputTranscriptCommitter(
    PreparedRequestCommitter,
    PreparedModelCallOutcomeRecorder,
):
    """AI commit-port implementation over one authoritative transcript."""

    def __init__(
        self,
        *,
        transcript: AgentTranscriptUnitOfWork,
        context: ModelInputCommitContext,
        runtime_references: ModelInputRuntimeReferences,
        max_encoded_record_bytes: int = MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
        binary_codec: SessionModelInputBlobCodec | None = None,
        binary_codec_factory: Callable[[], SessionModelInputBlobCodec] | None = None,
    ) -> None:
        if not isinstance(transcript, AgentTranscriptUnitOfWork):
            raise TypeError("Model Input committer requires AgentTranscriptUnitOfWork")
        if not isinstance(context, ModelInputCommitContext):
            raise TypeError("Model Input committer requires ModelInputCommitContext")
        if not isinstance(runtime_references, ModelInputRuntimeReferences):
            raise TypeError(
                "Model Input committer requires ModelInputRuntimeReferences"
            )
        _require_positive_int(
            max_encoded_record_bytes,
            name="maximum encoded Model Input record bytes",
        )
        if max_encoded_record_bytes > MODEL_INPUT_MAX_ENCODED_RECORD_BYTES:
            raise ValueError(
                "maximum encoded Model Input record bytes must not exceed "
                f"{MODEL_INPUT_MAX_ENCODED_RECORD_BYTES}"
            )
        if transcript.revision != context.source_revision:
            raise ModelInputIntegrityError(
                "Model Input source revision does not match the transcript"
            )
        if transcript.leaf_id != context.source_leaf_id:
            raise ModelInputIntegrityError(
                "Model Input source leaf does not match the transcript"
            )
        self._transcript = transcript
        self._context = context
        self._runtime = runtime_references
        if binary_codec is not None and not isinstance(
            binary_codec, SessionModelInputBlobCodec
        ):
            raise TypeError(
                "Model Input binary codec must be SessionModelInputBlobCodec"
            )
        if binary_codec is not None and binary_codec_factory is not None:
            raise ValueError("Model Input binary codec and factory are exclusive")
        self._binary_codec = binary_codec
        self._binary_codec_factory = binary_codec_factory
        self._max_encoded_record_bytes = max_encoded_record_bytes
        self._expected_revision = transcript.revision
        self._expected_leaf_id = transcript.leaf_id
        self._commits: list[ModelInputCommitResult] = []
        self._invocation_id: str | None = None
        self._latest_metrics: PreparedRequestMetrics | None = None
        self._outcome_recorded = False
        self._attempt_usage_observations: set[ModelCallAttemptUsage] = set()
        self._terminal_attempt_usage_keys: set[tuple[str, int, str]] = set()
        self._lock = asyncio.Lock()
        self._logical_prewarm_task: asyncio.Task[tuple[str | None, str]] | None = None
        self._prewarmed_logical_canonical: tuple[str | None, str] | None = None

    @property
    def commits(self) -> tuple[ModelInputCommitResult, ...]:
        return tuple(self._commits)

    @property
    def sealed_logical_messages(self) -> tuple[object, ...]:
        """Expose owned, immutable message values for same-Session reuse."""

        messages = self._context.logical_input["messages"]
        if not isinstance(messages, tuple):
            raise ModelInputIntegrityError("sealed Model Input messages are invalid")
        return messages

    @property
    def sealed_logical_input(self) -> Mapping[str, object]:
        """Expose the same owned values used by the durable commit."""

        return self._context.logical_input

    def _prepare_logical_canonical(self) -> tuple[str | None, str]:
        frozen = self._context.logical_input
        logical = cast(
            dict[str, JSONValue],
            (
                _logical_input_for_materialization(frozen)
                if self._context._reused_message_prefix_count
                else thaw_model_input_json(frozen)
            ),
        )
        return self._context._canonical_owned_logical_input(logical)

    async def prewarm_logical_input(self) -> None:
        """Prepare the sealed logical hash while provider payloads are built."""

        self._require_current_transcript()
        if self._prewarmed_logical_canonical is not None:
            return
        task = self._logical_prewarm_task
        if task is None:
            task = asyncio.create_task(
                asyncio.to_thread(self._prepare_logical_canonical)
            )
            self._logical_prewarm_task = task
            task.add_done_callback(self._finish_logical_prewarm)
        prepared = await asyncio.shield(task)
        self._require_current_transcript()
        self._prewarmed_logical_canonical = prepared

    def _finish_logical_prewarm(
        self, task: asyncio.Task[tuple[str | None, str]]
    ) -> None:
        if not task.cancelled():
            task.exception()

    async def commit_prepared_request(
        self,
        request: PreparedModelRequest,
    ) -> None:
        timer = PhaseTimer()
        outcome = "failed"
        node_index_cache_status: str | None = None
        materialization_timing: PhaseTimingSnapshot | None = None
        materialization_stats: ModelInputV2MaterializationStats | None = None
        try:
            async with self._lock:
                with timer.phase("preconditions"):
                    if self._outcome_recorded:
                        raise ModelInputIntegrityError(
                            "Model Input attempt cannot follow its terminal outcome"
                        )
                    self._require_current_transcript()
                    invocation_id = _prepared_text(request, "invocation_id")
                    if self._invocation_id is None:
                        self._invocation_id = invocation_id
                    elif self._invocation_id != invocation_id:
                        raise ModelInputIntegrityError(
                            "Model Input attempts changed logical invocation identity"
                        )
                if self._logical_prewarm_task is not None:
                    with timer.phase("join_logical_prewarm"):
                        self._prewarmed_logical_canonical = await asyncio.shield(
                            self._logical_prewarm_task
                        )
                    self._require_current_transcript()
                with timer.phase("validate_prepared_request"):
                    if (
                        type(request) is PreparedModelRequest
                        and request._owned_envelope_is_current()
                    ):
                        # The exact built-in envelope is recursively frozen.
                        # Copy it off-loop so a long request cannot stall input.
                        (
                            prepared_payload,
                            model_visible_headers,
                            canonical,
                        ) = await asyncio.to_thread(_validate_prepared_request, request)
                    else:
                        prepared_payload, model_visible_headers, canonical = (
                            _validate_prepared_request(request)
                        )
                # Validation can consume an entire input frame on a long
                # request. Service cancellation before allocating or writing
                # its durable graph, and reject a Session changed meanwhile.
                with timer.phase("post_validation_yield"):
                    await _yield_preparation()
                self._require_current_transcript()
                self._latest_metrics = request.metrics
                logical_shared_prefix = bool(self._context._reused_message_prefix_count)
                prepared_shared_prefix = (
                    type(request) is PreparedModelRequest
                    and request._reused_message_prefix_count > 0
                    and request._owned_envelope_is_current()
                )
                with timer.phase("logical_input_thaw"):
                    logical_input = cast(
                        dict[str, JSONValue],
                        await asyncio.to_thread(
                            (
                                _logical_input_for_materialization
                                if logical_shared_prefix
                                else thaw_model_input_json
                            ),
                            self._context.logical_input,
                        ),
                    )
                stored_logical_input = logical_input
                stored_prepared_payload = prepared_payload
                binary_projection_version = 0
                logical_input_hash: str | None = None
                needs_binary_projection = self._binary_codec is not None
                if (
                    type(self._binary_codec) is SessionModelInputBlobCodec
                    or self._binary_codec_factory is not None
                ):
                    # The built-in codec only changes declared prepared images,
                    # logical image objects, and reserved literal marker keys.
                    # A plain request needs its canonical logical encoding for
                    # the snapshot hash anyway; use that immutable text to avoid
                    # two more full-tree copies and an avoidable GC pause.
                    with timer.phase("logical_canonical"):
                        if self._prewarmed_logical_canonical is not None:
                            logical_canonical, logical_input_hash = (
                                self._prewarmed_logical_canonical
                            )
                        else:
                            logical_canonical = await asyncio.to_thread(
                                self._context._canonical_logical_input_json,
                                logical_input,
                            )
                            logical_input_hash = (
                                "sha256:"
                                + hashlib.sha256(
                                    logical_canonical.encode("utf-8")
                                ).hexdigest()
                            )
                    needs_binary_projection = (
                        bool(request.binary_fields)
                        or any(
                            marker in canonical
                            or (
                                marker in logical_canonical
                                if logical_canonical is not None
                                else marker in self._context._owned_binary_markers
                            )
                            for marker in (
                                '"$loushang.sessionBlob"',
                                '"$loushang.literal"',
                            )
                        )
                        or (
                            '"type":"image"' in logical_canonical
                            if logical_canonical is not None
                            else '"type":"image"' in self._context._owned_binary_markers
                        )
                    )
                    if (
                        needs_binary_projection
                        and self._binary_codec_factory is not None
                    ):
                        codec = self._binary_codec_factory()
                        if type(codec) is not SessionModelInputBlobCodec:
                            raise TypeError(
                                "deferred Model Input codec must be the built-in codec"
                            )
                        self._binary_codec = codec
                        self._binary_codec_factory = None
                if needs_binary_projection and self._binary_codec is not None:
                    # Blob rewriting may inspect and replace any nested JSON
                    # node, so give that path a fully detached native tree.
                    if logical_shared_prefix:
                        logical_input = cast(
                            dict[str, JSONValue],
                            await asyncio.to_thread(
                                thaw_model_input_json,
                                self._context.logical_input,
                            ),
                        )
                        stored_logical_input = logical_input
                    if prepared_shared_prefix:
                        prepared_payload = cast(
                            dict[str, JSONValue],
                            await asyncio.to_thread(
                                thaw_model_input_json,
                                prepared_payload,
                            ),
                        )
                        stored_prepared_payload = prepared_payload
                    with timer.phase("binary_externalize"):
                        projected_logical = self._binary_codec.externalize_mapping(
                            logical_input
                        )
                        projected_prepared = self._binary_codec.externalize_mapping(
                            prepared_payload,
                            binary_fields=request.binary_fields,
                        )
                    if (
                        projected_logical.replacement_count
                        + projected_prepared.replacement_count
                    ):
                        stored_logical_input = projected_logical.value
                        stored_prepared_payload = projected_prepared.value
                        binary_projection_version = (
                            MODEL_INPUT_BINARY_PROJECTION_VERSION
                        )
                    # Zero-replacement projections are unused full tree copies.
                    # Release them before indexing; changed trees remain owned
                    # by stored_logical_input/stored_prepared_payload above.
                    del projected_logical, projected_prepared
                if logical_input_hash is None:
                    if (
                        self._prewarmed_logical_canonical is not None
                        and self._binary_codec is None
                        and self._binary_codec_factory is None
                    ):
                        logical_input_hash = self._prewarmed_logical_canonical[1]
                    else:
                        logical_input_hash = await asyncio.to_thread(
                            hash_model_input_json,
                            logical_input,
                            name="logical Model Input",
                        )
                with timer.phase("pre_writer_yield"):
                    await _yield_preparation()
                self._require_current_transcript()
                writer = await ModelInputV2Writer.prepare(
                    transcript=self._transcript,
                    expected_revision=self._expected_revision,
                    expected_leaf_id=self._expected_leaf_id,
                    max_encoded_record_bytes=self._max_encoded_record_bytes,
                    phase_timer=timer,
                )
                node_index_cache_status = writer.index_cache_status
                with timer.phase("materialize"):
                    materialization = await writer.materialize(
                        logical_input=stored_logical_input,
                        prepared_payload=stored_prepared_payload,
                        model_visible_headers=model_visible_headers,
                        logical_source=(
                            self._context.logical_input
                            if stored_logical_input is logical_input
                            else None
                        ),
                        prepared_source=(
                            request.payload
                            if type(request) is PreparedModelRequest
                            and stored_prepared_payload is prepared_payload
                            and request._owned_envelope_is_current()
                            else None
                        ),
                    )
                materialization_timing = writer.materialization_timing
                materialization_stats = writer.materialization_stats
                with timer.phase("snapshot_build"):
                    snapshot = ModelInputSnapshotV2(
                        snapshot_id=str(uuid4()),
                        invocation_id=invocation_id,
                        attempt=_prepared_positive_int(request, "attempt"),
                        purpose=self._context.purpose,
                        product_id=self._runtime.product_id,
                        runtime_id=self._runtime.runtime_id,
                        mount_generation=self._runtime.mount_generation,
                        profile_fingerprint=self._runtime.profile_fingerprint,
                        registration_revision=self._runtime.registration_revision,
                        conversation_id=self._transcript.header.conversation_id,
                        source_leaf_id=self._context.source_leaf_id,
                        source_revision=self._context.source_revision,
                        commit_revision=materialization.expected_revision + 1,
                        provider_id=_prepared_text(request, "provider_id"),
                        model_id=_prepared_text(request, "model_id"),
                        api_id=_prepared_text(request, "api"),
                        endpoint_id=_prepared_text(request, "endpoint_id"),
                        logical_root=materialization.logical_root,
                        prepared_payload_root=materialization.prepared_payload_root,
                        model_visible_headers_root=(
                            materialization.model_visible_headers_root
                        ),
                        logical_input_hash=logical_input_hash,
                        prepared_payload_hash=_prepared_text(request, "payload_hash"),
                        binary_projection_version=binary_projection_version,
                    )
                    # A canonical mismatch is checked before any writes. Keeping this
                    # assertion here documents that the committed references still
                    # represent exactly the AI-owned frozen envelope.
                    if canonical != _prepared_text(request, "canonical_payload"):
                        raise ModelInputIntegrityError(
                            "prepared request canonical materialization changed "
                            "during commit"
                        )
                with timer.phase("append_snapshot"):
                    batch = await self._transcript.append_staged_model_input_snapshot(
                        writer.staged_records,
                        snapshot,
                        max_encoded_record_bytes=self._max_encoded_record_bytes,
                        expected_revision=self._expected_revision,
                        expected_leaf_id=self._expected_leaf_id,
                    )
                    commit = batch[-1]
                receipt = commit.receipt
                if receipt is None:
                    raise ModelInputIntegrityError(
                        "Model Input snapshot did not reach the authoritative Store"
                    )
                if receipt.revision != snapshot.commit_revision:
                    raise ModelInputIntegrityError(
                        "Model Input snapshot commit revision changed"
                    )
                try:
                    with timer.phase("incremental_verify"):
                        writer.verify_snapshot_commit(
                            commit.record,
                            snapshot,
                            materialization,
                            logical_input_hash=logical_input_hash,
                            prepared_payload_hash=_prepared_text(
                                request,
                                "payload_hash",
                            ),
                        )
                except ModelInputIntegrityError:
                    with timer.phase("rebuild_verify_fallback"):
                        if self._binary_codec is None:
                            rebuilt = rebuild_model_input(
                                self._transcript,
                                snapshot.snapshot_id,
                            )
                        else:
                            rebuilt = rebuild_model_input(
                                self._transcript,
                                snapshot.snapshot_id,
                                binary_codec=self._binary_codec,
                            )
                        if rebuilt.canonical_prepared_payload != canonical:
                            raise ModelInputIntegrityError(
                                "committed Model Input v2 prepared payload changed"
                            )
                with timer.phase("publish_commit"):
                    writer.publish_committed_graph()
                    self._advance(commit.record.record_id, receipt.revision)
                    self._commits.append(
                        ModelInputCommitResult(
                            snapshot_id=snapshot.snapshot_id,
                            record_id=commit.record.record_id,
                            source_revision=self._context.source_revision,
                            commit_revision=receipt.revision,
                        )
                    )
            outcome = "completed"
        finally:
            _emit_model_input_commit_timing(
                timer,
                request=request,
                outcome=outcome,
                source_revision=self._context.source_revision,
                committed_revision=self._expected_revision,
                node_index_cache_status=node_index_cache_status,
                materialization_timing=materialization_timing,
                materialization_stats=materialization_stats,
            )

    async def record_model_call_outcome(
        self,
        outcome: PreparedModelCallOutcome,
    ) -> None:
        async with self._lock:
            if self._outcome_recorded:
                raise ModelInputIntegrityError(
                    "model call invocation already has a terminal outcome"
                )
            self._require_current_transcript()
            if self._invocation_id is None:
                self._invocation_id = outcome.invocation_id
            elif self._invocation_id != outcome.invocation_id:
                raise ModelInputIntegrityError(
                    "model call outcome changed logical invocation identity"
                )
            fact = ModelCallOutcome.from_prepared_outcome(
                _outcome_with_request_metrics(outcome, self._latest_metrics),
                model_input_snapshot_ids=tuple(
                    commit.snapshot_id for commit in self._commits
                ),
            )
            commit = await self._transcript.append_model_call_outcome(
                fact,
                expected_revision=self._expected_revision,
                expected_leaf_id=self._expected_leaf_id,
            )
            receipt = commit.receipt
            if receipt is None:
                raise ModelInputIntegrityError(
                    "model call outcome did not reach the authoritative Store"
                )
            self._advance(commit.record.record_id, receipt.revision)
            self._outcome_recorded = True

    async def record_model_call_attempt_usage(
        self,
        usage: ModelCallAttemptUsage,
    ) -> bool:
        """Commit one normalized attempt snapshot; return false for a duplicate."""

        if not isinstance(usage, ModelCallAttemptUsage):
            raise TypeError("attempt usage must be ModelCallAttemptUsage")
        async with self._lock:
            if self._outcome_recorded:
                raise ModelInputIntegrityError(
                    "model call attempt usage cannot follow its terminal outcome"
                )
            self._require_current_transcript()
            key = self._require_attempt_usage_identity(usage)
            if usage in self._attempt_usage_observations:
                return False
            if key in self._terminal_attempt_usage_keys:
                raise ModelInputIntegrityError(
                    "model call attempt usage cannot follow its terminal observation"
                )
            commit = await self._transcript.append_model_call_attempt_usage(
                usage,
                max_encoded_record_bytes=self._max_encoded_record_bytes,
                expected_revision=self._expected_revision,
                expected_leaf_id=self._expected_leaf_id,
            )
            receipt = commit.receipt
            if receipt is None:
                raise ModelInputIntegrityError(
                    "model call attempt usage did not reach the authoritative Store"
                )
            self._advance(commit.record.record_id, receipt.revision)
            self._attempt_usage_observations.add(usage)
            if usage.terminal:
                self._terminal_attempt_usage_keys.add(key)
            return True

    async def record_terminal_model_call(
        self,
        outcome: PreparedModelCallOutcome,
        *,
        usage: ModelCallAttemptUsage | None,
    ) -> None:
        """Commit terminal usage and outcome together once both are known."""

        if usage is None:
            await self.record_model_call_outcome(outcome)
            return
        if not isinstance(usage, ModelCallAttemptUsage) or not usage.terminal:
            raise TypeError("terminal model call requires terminal attempt usage")
        async with self._lock:
            if self._outcome_recorded:
                raise ModelInputIntegrityError(
                    "model call invocation already has a terminal outcome"
                )
            self._require_current_transcript()
            if self._invocation_id != outcome.invocation_id:
                raise ModelInputIntegrityError(
                    "model call outcome changed logical invocation identity"
                )
            key = self._require_attempt_usage_identity(usage)
            if (
                usage in self._attempt_usage_observations
                or key in self._terminal_attempt_usage_keys
            ):
                # A provider may already have reported the same terminal usage.
                # A conflicting terminal observation cannot replace it, but
                # the independently known outcome must still be recorded.
                fact = ModelCallOutcome.from_prepared_outcome(
                    _outcome_with_request_metrics(outcome, self._latest_metrics),
                    model_input_snapshot_ids=tuple(
                        commit.snapshot_id for commit in self._commits
                    ),
                )
                commit = await self._transcript.append_model_call_outcome(
                    fact,
                    expected_revision=self._expected_revision,
                    expected_leaf_id=self._expected_leaf_id,
                )
                receipt = commit.receipt
                if receipt is None:
                    raise ModelInputIntegrityError(
                        "model call outcome did not reach the authoritative Store"
                    )
                self._advance(commit.record.record_id, receipt.revision)
                self._outcome_recorded = True
                return
            fact = ModelCallOutcome.from_prepared_outcome(
                _outcome_with_request_metrics(outcome, self._latest_metrics),
                model_input_snapshot_ids=tuple(
                    commit.snapshot_id for commit in self._commits
                ),
            )
            (
                usage_commit,
                outcome_commit,
            ) = await self._transcript._append_model_call_terminal_batch(
                usage,
                fact,
                max_encoded_record_bytes=self._max_encoded_record_bytes,
                expected_revision=self._expected_revision,
                expected_leaf_id=self._expected_leaf_id,
            )
            if usage_commit.receipt is None or outcome_commit.receipt is None:
                raise ModelInputIntegrityError(
                    "terminal model call did not reach the authoritative Store"
                )
            self._advance(
                outcome_commit.record.record_id,
                outcome_commit.receipt.revision,
            )
            self._attempt_usage_observations.add(usage)
            self._terminal_attempt_usage_keys.add(key)
            self._outcome_recorded = True

    def _require_attempt_usage_identity(
        self,
        usage: ModelCallAttemptUsage,
    ) -> tuple[str, int, str]:
        if self._invocation_id != usage.invocation_id:
            raise ModelInputIntegrityError(
                "model call attempt usage changed logical invocation identity"
            )
        # A receipt for the current append chain proves ancestry without
        # rescanning the full historical path for every usage observation.
        snapshot_commit = next(
            (
                commit
                for commit in self._commits
                if commit.snapshot_id == usage.model_input_snapshot_id
            ),
            None,
        )
        snapshot_record = (
            self._transcript.get(snapshot_commit.record_id)
            if snapshot_commit is not None
            else None
        )
        snapshot = snapshot_record.payload if snapshot_record is not None else None
        if (
            not isinstance(snapshot, ModelInputSnapshot | ModelInputSnapshotV2)
            or snapshot.snapshot_id != usage.model_input_snapshot_id
            or snapshot.invocation_id != usage.invocation_id
            or snapshot.attempt != usage.attempt
        ):
            raise ModelInputIntegrityError(
                "model call attempt usage does not match a committed attempt"
            )
        return (
            usage.invocation_id,
            usage.attempt,
            usage.model_input_snapshot_id,
        )

    def _require_current_transcript(self) -> None:
        if (
            self._transcript.revision != self._expected_revision
            or self._transcript.leaf_id != self._expected_leaf_id
        ):
            raise ModelInputIntegrityError(
                "transcript changed outside the Model Input commit sequence"
            )

    def _advance(self, record_id: str, revision: int) -> None:
        self._expected_leaf_id = record_id
        self._expected_revision = revision


async def _yield_preparation() -> None:
    # Service the queued reader/consumer chain before another full projection.
    for _ in range(3):
        await asyncio.sleep(0)


def _emit_model_input_commit_timing(
    timer: PhaseTimer,
    *,
    request: PreparedModelRequest,
    outcome: str,
    source_revision: int,
    committed_revision: int,
    node_index_cache_status: str | None,
    materialization_timing: PhaseTimingSnapshot | None,
    materialization_stats: ModelInputV2MaterializationStats | None,
) -> None:
    """Publish one best-effort aggregate without exposing request content."""

    try:
        snapshot = timer.snapshot()
        measured_ns = sum(item.total_ns for item in snapshot.phases.values())
        _MODEL_INPUT_PERFORMANCE_LOG.debug_event(
            "model_input.performance",
            "commit",
            outcome=outcome,
            total_ms=_timing_milliseconds(snapshot.total_ns),
            unattributed_ms=_timing_milliseconds(
                max(0, snapshot.total_ns - measured_ns)
            ),
            phases=_timing_phase_data(snapshot),
            materialize_phases=(
                _timing_phase_data(materialization_timing)
                if materialization_timing is not None
                else {}
            ),
            materialize_counts=(
                {
                    "sequence_count": materialization_stats.sequence_count,
                    "sequence_item_count": (materialization_stats.sequence_item_count),
                    "reused_prefix_item_count": (
                        materialization_stats.reused_prefix_item_count
                    ),
                    "planned_item_count": materialization_stats.planned_item_count,
                }
                if materialization_stats is not None
                else {}
            ),
            provider_id=request.provider_id,
            model_id=request.model_id,
            attempt=request.attempt,
            source_revision=source_revision,
            committed_revision=committed_revision,
            node_index_cache_status=node_index_cache_status,
            canonical_bytes=request.metrics.canonical_bytes,
            message_count=request.metrics.message_count,
            estimated_input_tokens=request.metrics.estimated_input_tokens,
        )
    except Exception:
        # Diagnostics must never change a durable Model Input outcome.
        return


def _timing_phase_data(snapshot: PhaseTimingSnapshot) -> dict[str, JSONValue]:
    return {
        name: {
            "total_ms": _timing_milliseconds(measurement.total_ns),
            "count": measurement.count,
        }
        for name, measurement in snapshot.phases.items()
    }


def _timing_milliseconds(duration_ns: int) -> float:
    return round(duration_ns / 1_000_000, 3)


def _outcome_with_request_metrics(
    outcome: PreparedModelCallOutcome,
    metrics: PreparedRequestMetrics | None,
) -> PreparedModelCallOutcome:
    if outcome.disposition != "failed" or outcome.error_info is None or metrics is None:
        return outcome
    error_info = dict(outcome.error_info)
    raw_details = error_info.get("details")
    details = dict(raw_details) if isinstance(raw_details, Mapping) else {}
    details.setdefault("canonicalBytes", metrics.canonical_bytes)
    if metrics.estimated_wire_bytes is not None:
        details.setdefault("estimatedWireBytes", metrics.estimated_wire_bytes)
    if metrics.message_bytes is not None:
        details.setdefault("messageBytes", metrics.message_bytes)
    details.setdefault("messageCount", metrics.message_count)
    details.setdefault("imageBytes", metrics.image_bytes)
    details.setdefault("toolSchemaBytes", metrics.tool_schema_bytes)
    if metrics.estimated_input_tokens is not None:
        details.setdefault("estimatedInputTokens", metrics.estimated_input_tokens)
    error_info["details"] = details
    return replace(
        outcome,
        error_info=cast(Mapping[str, FrozenJSONValue], error_info),
    )


def rebuild_model_input(
    transcript: AgentTranscriptUnitOfWork,
    snapshot_id: str,
    *,
    binary_codec: SessionModelInputBlobCodec | None = None,
) -> RebuiltModelInput:
    rebuilt = _rebuild_model_input(
        transcript,
        snapshot_id,
        binary_codec=binary_codec,
    )
    verification = _verification(rebuilt)
    if not verification.verified:
        raise ModelInputIntegrityError(
            f"Model Input snapshot {snapshot_id!r} failed hash verification"
        )
    return rebuilt


def verify_model_input(
    transcript: AgentTranscriptUnitOfWork,
    snapshot_id: str,
    *,
    binary_codec: SessionModelInputBlobCodec | None = None,
) -> ModelInputReconstructionVerification:
    return _verification(
        _rebuild_model_input(
            transcript,
            snapshot_id,
            binary_codec=binary_codec,
        )
    )


def _rebuild_model_input(
    transcript: AgentTranscriptUnitOfWork,
    snapshot_id: str,
    *,
    binary_codec: SessionModelInputBlobCodec | None = None,
) -> RebuiltModelInput:
    _require_text(snapshot_id, name="Model Input snapshot id")
    matches = [
        record
        for record in transcript.records
        if record.kind == MODEL_INPUT_PREPARED_KIND
        and isinstance(record.payload, ModelInputSnapshot | ModelInputSnapshotV2)
        and record.payload.snapshot_id == snapshot_id
    ]
    if len(matches) != 1:
        raise ModelInputIntegrityError(
            f"Model Input snapshot {snapshot_id!r} is not uniquely available"
        )
    snapshot_record = matches[0]
    snapshot = cast(ModelInputSnapshot | ModelInputSnapshotV2, snapshot_record.payload)
    expected_payload_version = (
        MODEL_INPUT_V2_PAYLOAD_VERSION
        if isinstance(snapshot, ModelInputSnapshotV2)
        else 1
    )
    if snapshot_record.payload_version != expected_payload_version:
        raise ModelInputIntegrityError(
            "Model Input snapshot uses the wrong payload version"
        )
    # Forks preserve historical records byte-for-byte.  The conversation id on
    # the fact is therefore provenance for the conversation that created it,
    # while reachability in this transcript is proved by the parent-linked
    # record graph below.
    ancestry = transcript.records_to(snapshot_record.record_id)
    ancestors = {
        record.record_id: record
        for record in ancestry
        if record.record_id != snapshot_record.record_id
    }
    if snapshot.source_leaf_id not in ancestors:
        raise ModelInputIntegrityError(
            "Model Input source leaf is outside snapshot ancestry"
        )
    if snapshot.conversation_id == transcript.header.conversation_id:
        local_commit_revision = transcript.records.index(snapshot_record) + 1
        source_record_revision = next(
            index
            for index, record in enumerate(transcript.records, start=1)
            if record.record_id == snapshot.source_leaf_id
        )
        if (
            local_commit_revision != snapshot.commit_revision
            or source_record_revision > snapshot.source_revision
        ):
            raise ModelInputIntegrityError("Model Input origin revision is invalid")
    if isinstance(snapshot, ModelInputSnapshotV2):
        rebuilt_v2 = ModelInputV2Resolver(ancestry).rebuild_snapshot(
            snapshot_record,
            snapshot,
        )
        logical_input = rebuilt_v2.logical_input
        prepared_payload = rebuilt_v2.prepared_payload
        model_visible_headers = rebuilt_v2.model_visible_headers
    else:
        logical_input = _rebuild_mapping(snapshot.logical_components, ancestors)
        prepared_payload = _rebuild_mapping(
            snapshot.prepared_payload_components,
            ancestors,
        )
        raw_headers = _component_content(
            snapshot.model_visible_headers_component,
            ancestors,
        )
        if not isinstance(raw_headers, dict) or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in raw_headers.items()
        ):
            raise ModelInputIntegrityError("model-visible headers are not string pairs")
        model_visible_headers = cast(dict[str, str], raw_headers)
    if (
        isinstance(snapshot, ModelInputSnapshotV2)
        and snapshot.binary_projection_version
    ):
        if (
            snapshot.binary_projection_version != MODEL_INPUT_BINARY_PROJECTION_VERSION
            or binary_codec is None
        ):
            raise ModelInputIntegrityError(
                "Model Input binary projection requires its Session blob authority"
            )
        try:
            logical_input = binary_codec.hydrate_mapping(logical_input)
            prepared_payload = binary_codec.hydrate_mapping(prepared_payload)
        except ModelInputBinaryProjectionError as error:
            raise ModelInputIntegrityError(
                "Model Input binary projection failed reconstruction"
            ) from error
    _validate_rebuilt_logical_input(logical_input)
    canonical_prepared = canonical_model_input_json(
        {
            "model_visible_headers": model_visible_headers,
            "payload": prepared_payload,
        },
        name="rebuilt prepared model request",
    )
    return RebuiltModelInput(
        snapshot=snapshot,
        commit_revision=snapshot.commit_revision,
        logical_input=logical_input,
        prepared_payload=prepared_payload,
        model_visible_headers=model_visible_headers,
        canonical_prepared_payload=canonical_prepared,
        logical_input_hash=hash_model_input_json(
            logical_input,
            name="rebuilt logical Model Input",
        ),
        prepared_payload_hash="sha256:"
        + hashlib.sha256(canonical_prepared.encode("utf-8")).hexdigest(),
    )


def _verification(
    rebuilt: RebuiltModelInput,
) -> ModelInputReconstructionVerification:
    return ModelInputReconstructionVerification(
        snapshot_id=rebuilt.snapshot.snapshot_id,
        logical_input_matches=(
            rebuilt.logical_input_hash == rebuilt.snapshot.logical_input_hash
        ),
        prepared_payload_matches=(
            rebuilt.prepared_payload_hash == rebuilt.snapshot.prepared_payload_hash
        ),
    )


def _rebuild_mapping(
    references: tuple[ModelInputComponentReference, ...],
    ancestors: Mapping[str, object],
) -> dict[str, JSONValue]:
    return {
        reference.name: _component_content(reference, ancestors)
        for reference in references
    }


def _component_content(
    reference: ModelInputComponentReference,
    ancestors: Mapping[str, object],
) -> JSONValue:
    record = ancestors.get(reference.record_id)
    if record is None:
        raise ModelInputIntegrityError(
            "Model Input component is outside snapshot ancestry"
        )
    if getattr(record, "kind", None) != MODEL_INPUT_COMPONENT_KIND or not isinstance(
        getattr(record, "payload", None), ModelInputComponent
    ):
        raise ModelInputIntegrityError(
            "Model Input component reference does not target a component fact"
        )
    component = cast(ModelInputComponent, getattr(record, "payload"))
    if component.content_hash != reference.content_hash:
        raise ModelInputIntegrityError("Model Input component reference hash changed")
    return thaw_model_input_json(component.content)


def _validate_rebuilt_logical_input(value: Mapping[str, JSONValue]) -> None:
    if not isinstance(value.get("messages"), list):
        raise ModelInputIntegrityError("Model Input messages must be an array")
    if not isinstance(value.get("tools"), list):
        raise ModelInputIntegrityError("Model Input tools must be an array")
    if not isinstance(value.get("request_options"), dict):
        raise ModelInputIntegrityError("Model Input request options must be an object")


def _validate_prepared_request(
    request: PreparedModelRequest,
) -> tuple[dict[str, JSONValue], dict[str, str], str]:
    if type(request) is PreparedModelRequest and request._owned_envelope_is_current():
        if request._reused_message_prefix_count:
            return (
                _prepared_payload_for_materialization(request.payload),
                dict(request.model_visible_headers),
                request.canonical_payload,
            )
        owned = request.owned_commit_projection()
        if owned is not None:
            return owned
    payload = _prepared_json_mapping(request, "payload")
    raw_headers = getattr(request, "model_visible_headers", None)
    if not isinstance(raw_headers, Mapping) or any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in raw_headers.items()
    ):
        raise ModelInputIntegrityError(
            "prepared request model-visible headers are invalid"
        )
    headers = dict(cast(Mapping[str, str], raw_headers))
    canonical = canonical_model_input_json(
        {"model_visible_headers": headers, "payload": payload},
        name="prepared model request",
    )
    if canonical != _prepared_text(request, "canonical_payload"):
        raise ModelInputIntegrityError(
            "prepared request canonical payload is not reproducible"
        )
    payload_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if payload_hash != _prepared_text(request, "payload_hash"):
        raise ModelInputIntegrityError("prepared request payload hash is invalid")
    return payload, headers, canonical


def _prepared_json_mapping(
    request: PreparedModelRequest,
    attribute: str,
) -> dict[str, JSONValue]:
    value = getattr(request, attribute, None)
    if not isinstance(value, Mapping):
        raise ModelInputIntegrityError(f"prepared request {attribute} is not a mapping")
    try:
        thawed = thaw_model_input_json(value)
    except RecursionError:
        # Retain the original cycle/depth rejection contract on malformed
        # inputs, without building a frozen intermediate for valid requests.
        try:
            freeze_model_input_json(value, name=f"prepared request {attribute}")
        except (TypeError, ValueError, RecursionError) as error:
            raise error from None
        raise
    if not isinstance(thawed, dict):
        raise ModelInputIntegrityError(f"prepared request {attribute} is not an object")
    validate_json_value(thawed, name=f"prepared request {attribute}")
    return thawed


def _prepared_text(request: object, attribute: str) -> str:
    value = getattr(request, attribute, None)
    if not isinstance(value, str) or not value:
        raise ModelInputIntegrityError(
            f"prepared request {attribute} must be non-empty text"
        )
    return value


def _prepared_positive_int(request: object, attribute: str) -> int:
    value = getattr(request, attribute, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ModelInputIntegrityError(
            f"prepared request {attribute} must be a positive integer"
        )
    return value


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _require_non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_fingerprint(value: object, *, name: str) -> str:
    text = _require_text(value, name=name)
    digest = text.removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint")
    return text


__all__ = [
    "ModelInputCommitContext",
    "ModelInputCommitResult",
    "ModelInputIntegrityError",
    "ModelInputReconstructionVerification",
    "ModelInputRuntimeReferences",
    "ModelInputTranscriptCommitter",
    "RebuiltModelInput",
    "rebuild_model_input",
    "verify_model_input",
]
