"""Commit and reconstruct one provider request from transcript facts."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import cast
from uuid import uuid4

from loushang.ai.prepared_request import (
    FrozenJSONValue,
    PreparedModelCallOutcome,
    PreparedModelCallOutcomeRecorder,
    PreparedModelRequest,
    PreparedRequestCommitter,
    PreparedRequestMetrics,
)
from loushang.foundation.json import JSONValue
from loushang.harness.capabilities import (
    MountGraphSnapshot,
    RegistrationInventorySnapshot,
)
from loushang.harness.transcript.kinds import (
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
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
    ModelInputV2Resolver,
    ModelInputV2Writer,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    ModelInputSnapshotV2,
)
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork


@dataclass(frozen=True)
class ModelInputCommitContext:
    """Provider-neutral logical materialization captured for one main turn."""

    purpose: str
    source_leaf_id: str
    source_revision: int
    logical_input: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.purpose, name="Model Input purpose")
        _require_text(self.source_leaf_id, name="Model Input source leaf id")
        _require_non_negative_int(
            self.source_revision,
            name="Model Input source revision",
        )
        frozen = freeze_model_input_json(
            self.logical_input,
            name="Model Input logical projection",
        )
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
        self._max_encoded_record_bytes = max_encoded_record_bytes
        self._expected_revision = transcript.revision
        self._expected_leaf_id = transcript.leaf_id
        self._commits: list[ModelInputCommitResult] = []
        self._invocation_id: str | None = None
        self._latest_metrics: PreparedRequestMetrics | None = None
        self._outcome_recorded = False
        self._lock = asyncio.Lock()

    @property
    def commits(self) -> tuple[ModelInputCommitResult, ...]:
        return tuple(self._commits)

    async def commit_prepared_request(
        self,
        request: PreparedModelRequest,
    ) -> None:
        async with self._lock:
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
            prepared_payload, model_visible_headers, canonical = (
                _validate_prepared_request(request)
            )
            self._latest_metrics = request.metrics
            logical_input = cast(
                dict[str, JSONValue],
                thaw_model_input_json(self._context.logical_input),
            )
            materialization = await ModelInputV2Writer(
                transcript=self._transcript,
                expected_revision=self._expected_revision,
                expected_leaf_id=self._expected_leaf_id,
                max_encoded_record_bytes=self._max_encoded_record_bytes,
            ).materialize(
                logical_input=logical_input,
                prepared_payload=prepared_payload,
                model_visible_headers=model_visible_headers,
            )
            self._expected_revision = materialization.expected_revision
            self._expected_leaf_id = materialization.expected_leaf_id
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
                commit_revision=self._expected_revision + 1,
                provider_id=_prepared_text(request, "provider_id"),
                model_id=_prepared_text(request, "model_id"),
                api_id=_prepared_text(request, "api"),
                endpoint_id=_prepared_text(request, "endpoint_id"),
                logical_root=materialization.logical_root,
                prepared_payload_root=materialization.prepared_payload_root,
                model_visible_headers_root=(materialization.model_visible_headers_root),
                logical_input_hash=hash_model_input_json(
                    logical_input,
                    name="Model Input logical projection",
                ),
                prepared_payload_hash=_prepared_text(request, "payload_hash"),
            )
            # A canonical mismatch is checked before any writes. Keeping this
            # assertion here documents that the committed references still
            # represent exactly the AI-owned frozen envelope.
            if canonical != _prepared_text(request, "canonical_payload"):
                raise ModelInputIntegrityError(
                    "prepared request canonical materialization changed during commit"
                )
            commit = await self._transcript.append_model_input_snapshot(
                snapshot,
                max_encoded_record_bytes=self._max_encoded_record_bytes,
                expected_revision=self._expected_revision,
                expected_leaf_id=self._expected_leaf_id,
            )
            receipt = commit.receipt
            if receipt is None:
                raise ModelInputIntegrityError(
                    "Model Input snapshot did not reach the authoritative Store"
                )
            if receipt.revision != snapshot.commit_revision:
                raise ModelInputIntegrityError(
                    "Model Input snapshot commit revision changed"
                )
            self._advance(commit.record.record_id, receipt.revision)
            rebuilt = rebuild_model_input(self._transcript, snapshot.snapshot_id)
            if rebuilt.canonical_prepared_payload != canonical:
                raise ModelInputIntegrityError(
                    "committed Model Input v2 prepared payload changed"
                )
            self._commits.append(
                ModelInputCommitResult(
                    snapshot_id=snapshot.snapshot_id,
                    record_id=commit.record.record_id,
                    source_revision=self._context.source_revision,
                    commit_revision=receipt.revision,
                )
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
) -> RebuiltModelInput:
    rebuilt = _rebuild_model_input(transcript, snapshot_id)
    verification = _verification(rebuilt)
    if not verification.verified:
        raise ModelInputIntegrityError(
            f"Model Input snapshot {snapshot_id!r} failed hash verification"
        )
    return rebuilt


def verify_model_input(
    transcript: AgentTranscriptUnitOfWork,
    snapshot_id: str,
) -> ModelInputReconstructionVerification:
    return _verification(_rebuild_model_input(transcript, snapshot_id))


def _rebuild_model_input(
    transcript: AgentTranscriptUnitOfWork,
    snapshot_id: str,
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
    thawed = thaw_model_input_json(
        freeze_model_input_json(value, name=f"prepared request {attribute}")
    )
    if not isinstance(thawed, dict):
        raise ModelInputIntegrityError(f"prepared request {attribute} is not an object")
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
