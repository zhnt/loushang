from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.agent import Agent
from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.context import NormalizedContext
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.options import CallOptions
from loushang.ai.prepared_request import (
    PreparedModelCallOutcome,
    PreparedModelRequest,
)
from loushang.ai.provider.prepared_request_conformance import (
    run_prepared_request_barrier_conformance,
)
from loushang.ai.provider.protocol import ProviderRequest
from loushang.ai.types import Usage, UserMessage
from loushang.harness.capabilities import (
    MountGraphSnapshot,
    RegistrationInventorySnapshot,
)
from loushang.harness.conversation import (
    ConversationCommitResult,
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.transcript import (
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
    MODEL_INPUT_PREPARED_KIND,
    AgentTranscriptFileLayout,
    AgentTranscriptRecordFactory,
    AgentTranscriptUnitOfWork,
    ModelCallOutcome,
    ModelInputCommitContext,
    ModelInputComponent,
    ModelInputComponentReference,
    ModelInputIntegrityError,
    ModelInputRecordSizeError,
    ModelInputRuntimeReferences,
    ModelInputSnapshot,
    ModelInputTranscriptCommitter,
    create_agent_transcript_file_store,
    project_model_call_invocations,
    rebuild_model_input,
    verify_model_input,
)
from loushang.harness.transcript.model_input_types import (
    hash_model_input_json,
    thaw_model_input_json,
)
from loushang.harness.transcript.model_input_v2_types import (
    ModelInputJsonChunkNode,
    ModelInputMappingRootNode,
    ModelInputNodeBundle,
    ModelInputNodeReference,
    ModelInputSequenceTailNode,
    ModelInputSnapshotV2,
)


class _BlockingModelInputStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.block_appends = False
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def append(
        self,
        key: ConversationKey,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        result = await super().append(
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )
        if self.block_appends:
            self.committed.set()
            await self.release.wait()
        return result

    async def append_batch(
        self,
        key: ConversationKey,
        records,
        *,
        expected_revision: int,
        operation_ids,
    ):
        result = await super().append_batch(
            key,
            records,
            expected_revision=expected_revision,
            operation_ids=operation_ids,
        )
        if self.block_appends:
            self.committed.set()
            await self.release.wait()
        return result


class _CountingModelInputStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.append_calls = 0
        self.batch_sizes: list[int] = []

    async def append(
        self,
        key: ConversationKey,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        self.append_calls += 1
        return await super().append(
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    async def append_batch(
        self,
        key: ConversationKey,
        records,
        *,
        expected_revision: int,
        operation_ids,
    ):
        self.batch_sizes.append(len(records))
        return await super().append_batch(
            key,
            records,
            expected_revision=expected_revision,
            operation_ids=operation_ids,
        )


class _InlineFileStore:
    """Exercise the real File Store without a test-only thread executor."""

    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def create(self, key, header, records=(), *, operation_id: str):
        return self.delegate._create_sync(
            key,
            header,
            records,
            operation_id=operation_id,
        )

    async def load(self, key):
        return self.delegate._load_sync(key)

    async def append(
        self,
        key,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ):
        return self.delegate._append_sync(
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    async def append_batch(
        self,
        key,
        records,
        *,
        expected_revision: int,
        operation_ids,
    ):
        return self.delegate._append_batch_sync(
            key,
            records,
            expected_revision=expected_revision,
            operation_ids=operation_ids,
        )


def _header(conversation_id: str = "model-input-conversation") -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-08-14T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )


def _runtime_references(
    *,
    profile_fingerprint: str | None = None,
) -> ModelInputRuntimeReferences:
    graph = MountGraphSnapshot(
        schema_version=1,
        graph_id="coding:runtime-1",
        product_id="coding",
        runtime_id="runtime-1",
        profile_fingerprint="a" * 64,
        generation=3,
        roots=(),
        assembly_fingerprint="b" * 64,
        nodes=(),
    )
    inventory = RegistrationInventorySnapshot(
        schema_version=1,
        graph_id=graph.graph_id,
        runtime_id=graph.runtime_id,
        mount_generation=graph.generation,
        revision="c" * 64,
        entries=(),
    )
    if profile_fingerprint is None:
        return ModelInputRuntimeReferences.from_snapshots(graph, inventory)
    return ModelInputRuntimeReferences.from_snapshots(
        graph,
        inventory,
        profile_fingerprint=profile_fingerprint,
    )


def test_runtime_references_keep_current_profile_separate_from_mount() -> None:
    references = _runtime_references(profile_fingerprint="d" * 64)

    assert references.profile_fingerprint == "d" * 64
    assert references.mount_generation == 3


def test_runtime_references_keep_legacy_mount_profile_default() -> None:
    references = _runtime_references()

    assert references.profile_fingerprint == "a" * 64


async def _memory_transcript(
    store: MemoryConversationStore | None = None,
) -> AgentTranscriptUnitOfWork:
    resolved_store = store or MemoryConversationStore(
        record_id=lambda record: record.record_id
    )
    transcript = await AgentTranscriptUnitOfWork.create(
        resolved_store,
        ConversationKey("test", "model-input-conversation"),
        _header(),
    )
    await transcript.append_agent_message(
        UserMessage(role="user", content="hello", timestamp=1.0)
    )
    return transcript


def _context(
    transcript: AgentTranscriptUnitOfWork,
    *,
    logical_input: dict[str, object] | None = None,
) -> ModelInputCommitContext:
    assert transcript.leaf_id is not None
    return ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id=transcript.leaf_id,
        source_revision=transcript.revision,
        logical_input=logical_input
        or {
            "system_prompt": "system prompt",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up a value",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            "request_options": {"reasoning": "medium"},
        },
    )


def _prepared(
    *,
    invocation_id: str = "invocation-1",
    attempt: int = 1,
    tools: list[dict[str, object]] | None = None,
    payload: dict[str, object] | None = None,
) -> PreparedModelRequest:
    model = _model(api="model-input-test")
    request = ProviderRequest(
        model=model,
        context=NormalizedContext(system_prompt=None),
        options=None,
        base_url=model.base_url,
        invocation_id=invocation_id,
        attempt=attempt,
    )
    return PreparedModelRequest.from_provider_request(
        request,
        payload=payload
        or {
            "tools": tools
            or [
                {
                    "name": "lookup",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "messages": [{"role": "user", "content": "hello"}],
            "model": model.id,
        },
        model_visible_headers={"anthropic-beta": "feature-1"},
    )


def _model(*, api: str) -> Model:
    return Model(
        id="model-input-model",
        provider="model-input-provider",
        endpoint="model-input-endpoint",
        api=api,
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), output=("text",), stream=True),
    )


def test_model_input_records_are_hidden_deduplicated_and_hash_verified() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )

        await committer.commit_prepared_request(_prepared())
        first_component_ids = {
            record.record_id
            for record in transcript.records
            if record.kind == MODEL_INPUT_COMPONENT_KIND
        }
        first_record_count = len(transcript.records)
        await committer.commit_prepared_request(
            _prepared(invocation_id="invocation-1", attempt=2)
        )

        component_ids = {
            record.record_id
            for record in transcript.records
            if record.kind == MODEL_INPUT_COMPONENT_KIND
        }
        prepared_records = [
            record
            for record in transcript.records
            if record.kind == MODEL_INPUT_PREPARED_KIND
        ]
        assert component_ids == first_component_ids
        assert len(transcript.records) == first_record_count + 1
        assert len(prepared_records) == 2
        assert transcript.replay_context().messages == (
            UserMessage(role="user", content="hello", timestamp=1.0),
        )

        commit = committer.commits[-1]
        rebuilt = rebuild_model_input(transcript, commit.snapshot_id)
        verification = verify_model_input(transcript, commit.snapshot_id)
        assert rebuilt.logical_input["system_prompt"] == "system prompt"
        assert list(rebuilt.prepared_payload) == ["tools", "messages", "model"]
        assert rebuilt.model_visible_headers == {"anthropic-beta": "feature-1"}
        assert verification.logical_input_matches
        assert verification.prepared_payload_matches
        assert commit.source_revision == 1
        assert commit.commit_revision == transcript.revision
        assert rebuilt.commit_revision == commit.commit_revision
        assert rebuilt.snapshot.commit_revision == commit.commit_revision

    asyncio.run(scenario())


def test_model_call_outcome_closes_all_ordered_attempt_snapshots_once() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        await committer.commit_prepared_request(_prepared(attempt=2))

        await committer.record_model_call_outcome(
            PreparedModelCallOutcome(
                invocation_id="invocation-1",
                disposition="completed",
                stop_reason="stop",
                usage=Usage(
                    input=20,
                    output=5,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=25,
                    cost=None,
                ),
            )
        )

        outcomes = [
            record.payload
            for record in transcript.records
            if record.kind == MODEL_CALL_OUTCOME_KIND
        ]
        assert outcomes == [
            ModelCallOutcome(
                invocation_id="invocation-1",
                model_input_snapshot_ids=tuple(
                    commit.snapshot_id for commit in committer.commits
                ),
                disposition="completed",
                stop_reason="stop",
                usage=Usage(
                    input=20,
                    output=5,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=25,
                    cost=None,
                ),
            )
        ]
        projected = project_model_call_invocations(transcript.active_path())
        assert len(projected) == 1
        assert projected[0].invocation_id == "invocation-1"
        assert projected[0].model_input_snapshot_ids == tuple(
            commit.snapshot_id for commit in committer.commits
        )
        assert projected[0].state == "completed"
        assert projected[0].terminal is True
        with pytest.raises(ModelInputIntegrityError, match="already has"):
            await committer.record_model_call_outcome(
                PreparedModelCallOutcome(
                    invocation_id="invocation-1",
                    disposition="completed",
                    stop_reason="stop",
                    usage=Usage(0, 0, 0, 0, 0, None),
                )
            )
        with pytest.raises(ModelInputIntegrityError, match="cannot follow"):
            await committer.commit_prepared_request(_prepared(attempt=3))

    asyncio.run(scenario())


def test_model_call_failure_outcome_persists_only_allowlisted_diagnostics() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())

        await committer.record_model_call_outcome(
            PreparedModelCallOutcome(
                invocation_id="invocation-1",
                disposition="failed",
                stop_reason="error",
                usage=Usage(10, 0, 0, 0, 10, None),
                error_info={
                    "code": "provider",
                    "message": "Authorization: Bearer secret-token",
                    "source": "provider-test",
                    "retryable": False,
                    "statusCode": 400,
                    "requestId": "request-safe-id",
                    "details": {
                        "exceptionType": "ProviderHTTPError",
                        "estimatedWireBytes": 900_000,
                        "providerErrorType": "invalid_request_error",
                        "providerErrorCode": "request_too_large",
                        "providerResponseSummary": "private prompt",
                        "authorization": "Bearer secret-token",
                    },
                },
            )
        )

        outcome = next(
            record.payload
            for record in transcript.records
            if isinstance(record.payload, ModelCallOutcome)
        )
        assert outcome.failure is not None
        assert outcome.failure.code == "provider"
        assert outcome.failure.status_code == 400
        assert outcome.failure.request_id == "request-safe-id"
        assert dict(outcome.failure.details) == {
            "exceptionType": "ProviderHTTPError",
            "canonicalBytes": 220,
            "estimatedWireBytes": 900_000,
            "messageBytes": 35,
            "messageCount": 1,
            "imageBytes": 0,
            "toolSchemaBytes": 68,
            "providerErrorType": "invalid_request_error",
            "providerErrorCode": "request_too_large",
        }
        assert "secret-token" not in repr(outcome)
        assert "private prompt" not in repr(outcome)

    asyncio.run(scenario())


def test_model_call_outcome_rejects_an_incomplete_attempt_sequence() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        await committer.commit_prepared_request(_prepared(attempt=2))
        assert transcript.leaf_id is not None

        with pytest.raises(ModelInputIntegrityError, match="complete ordered"):
            await transcript.append_model_call_outcome(
                ModelCallOutcome(
                    invocation_id="invocation-1",
                    model_input_snapshot_ids=(committer.commits[0].snapshot_id,),
                    disposition="cancelled",
                    stop_reason="aborted",
                    usage=Usage(0, 0, 0, 0, 0, None),
                ),
                expected_revision=transcript.revision,
                expected_leaf_id=transcript.leaf_id,
            )

    asyncio.run(scenario())


def test_prepared_attempts_without_an_outcome_project_as_unknown() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        await committer.commit_prepared_request(_prepared(attempt=2))

        projected = project_model_call_invocations(transcript.active_path())

        assert len(projected) == 1
        invocation = projected[0]
        assert invocation.invocation_id == "invocation-1"
        assert invocation.model_input_snapshot_ids == tuple(
            commit.snapshot_id for commit in committer.commits
        )
        assert invocation.state == "unknown"
        assert invocation.terminal is False
        assert invocation.outcome is None
        tampered = AgentTranscriptRecordFactory().create(
            MODEL_CALL_OUTCOME_KIND,
            ModelCallOutcome(
                invocation_id="invocation-1",
                model_input_snapshot_ids=tuple(
                    reversed(
                        [commit.snapshot_id for commit in committer.commits]
                    )
                ),
                disposition="completed",
                stop_reason="stop",
                usage=Usage(0, 0, 0, 0, 0, None),
            ),
            parent_id=transcript.leaf_id,
        )
        with pytest.raises(ModelInputIntegrityError, match="selected-path"):
            project_model_call_invocations((*transcript.active_path(), tampered))

    asyncio.run(scenario())


def test_pre_transport_cancellation_outcome_allows_no_attempt_snapshot() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )

        await committer.record_model_call_outcome(
            PreparedModelCallOutcome(
                invocation_id="cancelled-before-preparation",
                disposition="cancelled",
                stop_reason="aborted",
                usage=Usage(0, 0, 0, 0, 0, None),
            )
        )

        outcome = next(
            record.payload
            for record in transcript.records
            if isinstance(record.payload, ModelCallOutcome)
        )
        assert outcome.invocation_id == "cancelled-before-preparation"
        assert outcome.model_input_snapshot_ids == ()
        assert outcome.disposition == "cancelled"
        projected = project_model_call_invocations(transcript.active_path())
        assert len(projected) == 1
        assert projected[0].state == "cancelled"
        assert projected[0].model_input_snapshot_ids == ()

    asyncio.run(scenario())


def test_preflight_failure_outcome_allows_no_attempt_snapshot() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )

        await committer.record_model_call_outcome(
            PreparedModelCallOutcome(
                invocation_id="failed-before-preparation",
                disposition="failed",
                stop_reason="error",
                usage=Usage(0, 0, 0, 0, 0, None),
                error_info={
                    "code": "request_too_large",
                    "message": "Prepared request exceeded configured capacity.",
                    "source": "loushang.ai.preflight",
                    "retryable": False,
                    "details": {
                        "canonicalBytes": 900_000,
                        "capacityMetric": "canonicalBytes",
                        "capacityLimit": "maxCanonicalBytes",
                        "capacityValue": 900_000,
                        "capacityMaximum": 800_000,
                    },
                },
            )
        )

        outcome = next(
            record.payload
            for record in transcript.records
            if isinstance(record.payload, ModelCallOutcome)
        )
        assert outcome.model_input_snapshot_ids == ()
        assert outcome.disposition == "failed"
        assert outcome.failure is not None
        assert outcome.failure.code == "request_too_large"
        projected = project_model_call_invocations(transcript.active_path())
        assert len(projected) == 1
        assert projected[0].state == "failed"
        assert projected[0].model_input_snapshot_ids == ()

    asyncio.run(scenario())


async def _append_v1_model_input_snapshot(
    transcript: AgentTranscriptUnitOfWork,
) -> ModelInputSnapshot:
    assert transcript.leaf_id is not None
    source_leaf_id = transcript.leaf_id
    source_revision = transcript.revision
    logical_input = thaw_model_input_json(_context(transcript).logical_input)
    assert isinstance(logical_input, dict)
    prepared_request = _prepared(invocation_id="invocation-v1")
    prepared_payload = thaw_model_input_json(prepared_request.payload)
    assert isinstance(prepared_payload, dict)
    model_visible_headers = dict(prepared_request.model_visible_headers)

    async def append_components(
        values: dict[str, object],
    ) -> tuple[ModelInputComponentReference, ...]:
        references = []
        for name, value in values.items():
            content_hash = hash_model_input_json(
                value,
                name=f"v1 Model Input {name}",
            )
            commit = await transcript.append(
                MODEL_INPUT_COMPONENT_KIND,
                ModelInputComponent(
                    content_hash=content_hash,
                    content=value,
                ),
            )
            references.append(
                ModelInputComponentReference(
                    name=name,
                    record_id=commit.record.record_id,
                    content_hash=content_hash,
                )
            )
        return tuple(references)

    logical_references = await append_components(logical_input)
    prepared_references = await append_components(prepared_payload)
    headers_reference = (
        await append_components({"model_visible_headers": model_visible_headers})
    )[0]
    snapshot = ModelInputSnapshot(
        snapshot_id="snapshot-v1",
        invocation_id="invocation-v1",
        attempt=1,
        purpose="main_turn",
        product_id="coding",
        runtime_id="runtime-1",
        mount_generation=3,
        profile_fingerprint="a" * 64,
        registration_revision="c" * 64,
        conversation_id=transcript.header.conversation_id,
        source_leaf_id=source_leaf_id,
        source_revision=source_revision,
        commit_revision=transcript.revision + 1,
        provider_id=prepared_request.provider_id,
        model_id=prepared_request.model_id,
        api_id=prepared_request.api,
        endpoint_id=prepared_request.endpoint_id,
        logical_components=logical_references,
        prepared_payload_components=prepared_references,
        model_visible_headers_component=headers_reference,
        logical_input_hash=hash_model_input_json(
            logical_input,
            name="v1 logical Model Input",
        ),
        prepared_payload_hash=prepared_request.payload_hash,
    )
    await transcript.append(MODEL_INPUT_PREPARED_KIND, snapshot)
    return snapshot


def test_model_input_v1_snapshot_rebuilds_before_and_after_mixed_v2_writes() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        v1_snapshot = await _append_v1_model_input_snapshot(transcript)
        v1_before = rebuild_model_input(transcript, v1_snapshot.snapshot_id)

        await transcript.append_agent_message(
            UserMessage(role="user", content="continue with v2", timestamp=2.0)
        )
        v2_committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await v2_committer.commit_prepared_request(
            _prepared(invocation_id="invocation-v2")
        )

        v1_after = rebuild_model_input(transcript, v1_snapshot.snapshot_id)
        v2_rebuilt = rebuild_model_input(
            transcript,
            v2_committer.commits[-1].snapshot_id,
        )
        prepared_versions = {
            record.payload_version
            for record in transcript.records
            if record.kind == MODEL_INPUT_PREPARED_KIND
        }
        assert v1_after == v1_before
        assert isinstance(v1_after.snapshot, ModelInputSnapshot)
        assert isinstance(v2_rebuilt.snapshot, ModelInputSnapshotV2)
        assert prepared_versions == {1, 2}
        assert verify_model_input(transcript, v1_snapshot.snapshot_id).verified
        assert verify_model_input(
            transcript,
            v2_committer.commits[-1].snapshot_id,
        ).verified
        fork = await transcript.fork(
            ConversationKey("test", "mixed-model-input-fork"),
            _header("mixed-model-input-fork"),
        )
        assert rebuild_model_input(fork, v1_snapshot.snapshot_id).logical_input == (
            v1_before.logical_input
        )
        assert (
            rebuild_model_input(
                fork,
                v2_committer.commits[-1].snapshot_id,
            ).prepared_payload
            == v2_rebuilt.prepared_payload
        )

    asyncio.run(scenario())


def test_loading_a_v1_file_is_byte_stable_before_appending_v2(tmp_path: Path) -> None:
    async def scenario() -> None:
        layout = AgentTranscriptFileLayout(tmp_path / "sessions")
        key = layout.key("v1-to-v2-file")
        delegate = create_agent_transcript_file_store(layout)
        transcript = await AgentTranscriptUnitOfWork.create(
            _InlineFileStore(delegate),
            key,
            _header("v1-to-v2-file"),
        )
        await transcript.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        v1_snapshot = await _append_v1_model_input_snapshot(transcript)
        path = layout.resolve_path(key)
        assert path is not None
        before_load = path.read_bytes()

        loaded = await AgentTranscriptUnitOfWork.load(
            _InlineFileStore(delegate),
            key,
        )

        assert path.read_bytes() == before_load
        assert rebuild_model_input(loaded, v1_snapshot.snapshot_id).snapshot == (
            v1_snapshot
        )
        await loaded.append_agent_message(
            UserMessage(role="user", content="continue", timestamp=2.0)
        )
        committer = ModelInputTranscriptCommitter(
            transcript=loaded,
            context=_context(loaded),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(
            _prepared(invocation_id="file-v2")
        )
        assert path.read_bytes().startswith(before_load)
        assert rebuild_model_input(loaded, v1_snapshot.snapshot_id).snapshot == (
            v1_snapshot
        )
        assert isinstance(
            rebuild_model_input(
                loaded,
                committer.commits[-1].snapshot_id,
            ).snapshot,
            ModelInputSnapshotV2,
        )

    asyncio.run(scenario())


def test_model_input_materializes_missing_v2_layers_in_bounded_store_batches() -> None:
    async def scenario() -> None:
        backend = _CountingModelInputStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        append_calls_before = backend.append_calls

        await committer.commit_prepared_request(_prepared())

        component_count = sum(
            record.kind == MODEL_INPUT_COMPONENT_KIND for record in transcript.records
        )
        assert sum(backend.batch_sizes) == component_count
        assert 1 <= len(backend.batch_sizes) <= 4
        assert backend.append_calls == append_calls_before + 1
        first_batch_sizes = list(backend.batch_sizes)

        await committer.commit_prepared_request(
            _prepared(invocation_id="invocation-1", attempt=2)
        )

        assert backend.batch_sizes == first_batch_sizes
        assert backend.append_calls == append_calls_before + 2

    asyncio.run(scenario())


def _v2_node(transcript, reference: ModelInputNodeReference):
    record = transcript.get(reference.record_id)
    assert record is not None
    assert isinstance(record.payload, ModelInputNodeBundle)
    return record.payload.nodes[reference.ordinal]


def test_model_input_v2_chunks_and_rebuilds_a_single_message_over_one_mib() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        image_data = "A" * (2 * MODEL_INPUT_MAX_ENCODED_RECORD_BYTES)
        logical_input = {
            "system_prompt": "system prompt",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "media_type": "image/png",
                            "data": image_data,
                        }
                    ],
                }
            ],
            "tools": [],
            "request_options": {},
        }
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=logical_input),
            runtime_references=_runtime_references(),
        )

        await committer.commit_prepared_request(_prepared())

        rebuilt = rebuild_model_input(
            transcript,
            committer.commits[-1].snapshot_id,
        )
        chunks = [
            node
            for record in transcript.records
            if isinstance(record.payload, ModelInputNodeBundle)
            for node in record.payload.nodes
            if isinstance(node, ModelInputJsonChunkNode)
        ]
        assert len(chunks) > 1
        assert rebuilt.logical_input == logical_input

    asyncio.run(scenario())


def test_model_input_v2_reuses_the_previous_message_prefix_and_appends_suffix() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        first_message = {"role": "user", "content": "first"}
        first_logical = {
            "system_prompt": "system prompt",
            "messages": [first_message],
            "tools": [],
            "request_options": {},
        }
        first_committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=first_logical),
            runtime_references=_runtime_references(),
        )
        await first_committer.commit_prepared_request(_prepared())

        await transcript.append_agent_message(
            UserMessage(role="user", content="second", timestamp=2.0)
        )
        second_message = {"role": "user", "content": "second"}
        second_logical = {
            **first_logical,
            "messages": [first_message, second_message],
        }
        second_committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=second_logical),
            runtime_references=_runtime_references(),
        )
        await second_committer.commit_prepared_request(
            _prepared(invocation_id="invocation-2")
        )

        snapshot_record = next(
            record
            for record in transcript.records
            if isinstance(record.payload, ModelInputSnapshotV2)
            and record.payload.snapshot_id == second_committer.commits[-1].snapshot_id
        )
        snapshot = snapshot_record.payload
        logical_root = _v2_node(transcript, snapshot.logical_root)
        assert isinstance(logical_root, ModelInputMappingRootNode)
        messages_ref = next(
            entry.value for entry in logical_root.entries if entry.name == "messages"
        )
        messages_tail = _v2_node(transcript, messages_ref)

        assert isinstance(messages_tail, ModelInputSequenceTailNode)
        assert messages_tail.total_item_count == 2
        assert messages_tail.previous_tail is not None
        assert len(messages_tail.appended_items) == 1
        assert (
            rebuild_model_input(
                transcript,
                second_committer.commits[-1].snapshot_id,
            ).logical_input
            == second_logical
        )

    asyncio.run(scenario())


def test_model_input_v2_segments_a_large_first_sequence_tail() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        message = {"role": "user", "content": "same"}
        messages = [message] * 2_500
        logical_input = {
            "system_prompt": "system prompt",
            "messages": messages,
            "tools": [],
            "request_options": {},
        }
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=logical_input),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(
            _prepared(
                payload={
                    "messages": messages[:1_024],
                    "model": "model-input-model",
                }
            )
        )

        tails = [
            node
            for record in transcript.records
            if isinstance(record.payload, ModelInputNodeBundle)
            for node in record.payload.nodes
            if isinstance(node, ModelInputSequenceTailNode)
            and node.total_item_count > 0
        ]
        rebuilt = rebuild_model_input(
            transcript,
            committer.commits[-1].snapshot_id,
        )
        assert [tail.total_item_count for tail in tails] == [1_024, 2_048, 2_500]
        assert rebuilt.logical_input["messages"] == messages
        assert rebuilt.prepared_payload["messages"] == messages[:1_024]

    asyncio.run(scenario())


def test_model_input_v2_real_jsonl_growth_tracks_unique_suffix_content(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        layout = AgentTranscriptFileLayout(tmp_path / "sessions")
        key = layout.key("growth-conversation")
        delegate = create_agent_transcript_file_store(layout)
        transcript = await AgentTranscriptUnitOfWork.create(
            _InlineFileStore(delegate),
            key,
            _header("growth-conversation"),
        )
        await transcript.append_agent_message(
            UserMessage(role="user", content="start", timestamp=1.0)
        )
        path = layout.resolve_path(key)
        assert path is not None
        initial_bytes = path.stat().st_size
        image_data = "".join(
            hashlib.sha256(str(index).encode()).hexdigest() for index in range(2_000)
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "media_type": "image/png",
                        "data": image_data,
                    }
                ],
            }
        ]
        sizes = []
        for turn in range(20):
            if turn:
                text = f"turn-{turn}:" + ("x" * 4_096)
                await transcript.append_agent_message(
                    UserMessage(role="user", content=text, timestamp=turn + 1.0)
                )
                messages.append({"role": "user", "content": text})
            logical_input = {
                "system_prompt": "system prompt",
                "messages": list(messages),
                "tools": [],
                "request_options": {},
            }
            committer = ModelInputTranscriptCommitter(
                transcript=transcript,
                context=_context(transcript, logical_input=logical_input),
                runtime_references=_runtime_references(),
            )
            prepared_messages = []
            for message in messages:
                content = message["content"]
                if isinstance(content, list):
                    prepared_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": image_data,
                                    },
                                }
                            ],
                        }
                    )
                else:
                    prepared_messages.append(message)
            await committer.commit_prepared_request(
                _prepared(
                    invocation_id=f"growth-{turn}",
                    payload={
                        "messages": prepared_messages,
                        "model": "model-input-model",
                    },
                )
            )
            sizes.append(path.stat().st_size)

        first_ten_growth = sizes[9] - initial_bytes
        second_ten_growth = sizes[19] - sizes[9]
        journal_text = path.read_text(encoding="utf-8")
        assert second_ten_growth < first_ten_growth
        assert sizes[19] < sizes[9] * 2
        assert journal_text.count(image_data[:64]) == 1
        for line in journal_text.splitlines()[1:]:
            envelope = json.loads(line)
            if envelope.get("kind", "").startswith("model.input."):
                assert len((line + "\n").encode()) <= (
                    MODEL_INPUT_MAX_ENCODED_RECORD_BYTES
                )

    asyncio.run(scenario())


def test_model_input_retains_extension_tool_schema_after_source_removal(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        from loushang.harness.extensions.agent import (
            ExtensionRunner,
            ExtensionRuntimeBindings,
        )
        from loushang.harness.resources.types import ExtensionDescriptor
        from loushang.harness.tools.core import ToolRegistry

        extension_source = tmp_path / "review_extension.py"
        extension_source.write_text(
            """
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolDefinition


async def _execute(tool_call_id, arguments, signal, on_update):
    return {"value": arguments.get("value")}


def register(api):
    api.register_tool(
        ToolDefinition(
            name="extension_lookup",
            label="Extension Lookup",
            description="Look up a value from the loaded Extension",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            execution=direct_execution(_execute),
        )
    )
""".strip()
            + "\n",
            encoding="utf-8",
        )
        runner = ExtensionRunner(
            [
                ExtensionDescriptor(
                    name="review_extension",
                    source_path=extension_source,
                    entry_path=extension_source,
                )
            ]
        )
        registry = ToolRegistry()

        async def ignore_async(*_args: object) -> None:
            return None

        bindings = ExtensionRuntimeBindings(
            cwd=str(tmp_path),
            get_active_tool_names=lambda: ["extension_lookup"],
            get_model_selection=lambda: None,
            set_active_tools=ignore_async,
            set_model=ignore_async,
            request_resource_refresh=lambda: None,
            shutdown=lambda: None,
            record_diagnostic=lambda _diagnostic: None,
            bind_tool=lambda definition, owner, source_info: registry.bind_tool(
                definition,
                owner=owner,
                source_info=source_info,
            ),
            stage_tool=lambda definition, owner, source_info: registry.stage_tool(
                definition,
                owner=owner,
                source_info=source_info,
            ),
        )
        await runner.activate_runtime_generation(bindings)
        definition = registry.get_definition("extension_lookup")
        assert definition is not None
        logical_tool = {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters,
        }
        prepared_tool = {
            "name": definition.name,
            "description": definition.description,
            "input_schema": definition.parameters,
        }
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(
                transcript,
                logical_input={
                    "system_prompt": "system prompt",
                    "messages": [{"role": "user", "content": "hello"}],
                    "tools": [logical_tool],
                    "request_options": {},
                },
            ),
            runtime_references=_runtime_references(),
        )

        await committer.commit_prepared_request(_prepared(tools=[prepared_tool]))
        snapshot_id = committer.commits[-1].snapshot_id
        candidate = runner.prepare_generation([])
        await candidate.activate(bindings)
        retirement = candidate.publish(lambda: None)
        await retirement.retire()
        assert registry.list_definitions() == []
        extension_source.unlink()
        rebuilt = rebuild_model_input(transcript, snapshot_id)

        assert extension_source.exists() is False
        assert rebuilt.logical_input["tools"] == [
            {
                "name": "extension_lookup",
                "description": "Look up a value from the loaded Extension",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ]
        assert rebuilt.prepared_payload["tools"] == [
            {
                "name": "extension_lookup",
                "description": "Look up a value from the loaded Extension",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ]
        assert verify_model_input(transcript, snapshot_id).verified
        await runner.dispose_runtime_generation()

    asyncio.run(scenario())


def test_model_input_components_remain_reachable_and_reusable_after_fork() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        selected_root_id = transcript.leaf_id
        assert selected_root_id is not None
        for index in range(20):
            await transcript.append_agent_message(
                UserMessage(
                    role="user",
                    content=f"discarded sibling {index}",
                    timestamp=2.0 + index,
                )
            )
        transcript.branch(selected_root_id)
        await transcript.append_agent_message(
            UserMessage(role="user", content="selected branch", timestamp=30.0)
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        original_snapshot_id = committer.commits[-1].snapshot_id
        original_commit_revision = committer.commits[-1].commit_revision
        original_component_ids = {
            record.record_id
            for record in transcript.records
            if record.kind == MODEL_INPUT_COMPONENT_KIND
        }

        fork = await transcript.fork(
            ConversationKey("test", "model-input-fork"),
            ConversationHeader(
                conversation_id="model-input-fork",
                version=1,
                created_at="2026-08-14T01:00:00Z",
                parent_conversation_id=transcript.header.conversation_id,
            ),
        )
        rebuilt = rebuild_model_input(fork, original_snapshot_id)
        assert rebuilt.snapshot.conversation_id == transcript.header.conversation_id
        assert rebuilt.logical_input["system_prompt"] == "system prompt"
        assert rebuilt.commit_revision == original_commit_revision

        fork_record_count = len(fork.records)
        fork_committer = ModelInputTranscriptCommitter(
            transcript=fork,
            context=_context(fork),
            runtime_references=_runtime_references(),
        )
        await fork_committer.commit_prepared_request(
            _prepared(invocation_id="invocation-fork")
        )

        assert len(fork.records) == fork_record_count + 1
        assert {
            record.record_id
            for record in fork.records
            if record.kind == MODEL_INPUT_COMPONENT_KIND
        } == original_component_ids
        fork_snapshot = rebuild_model_input(
            fork,
            fork_committer.commits[-1].snapshot_id,
        ).snapshot
        assert fork_snapshot.conversation_id == "model-input-fork"
        assert (
            fork_snapshot.commit_revision == fork_committer.commits[-1].commit_revision
        )

    asyncio.run(scenario())


def test_reconstruction_rejects_component_outside_snapshot_ancestry() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        snapshot_id = committer.commits[-1].snapshot_id
        transcript.branch(_context_source_leaf(transcript))
        await transcript.append_agent_message(
            UserMessage(role="user", content="sibling", timestamp=2.0)
        )

        # The original snapshot remains reconstructable from its own ancestry;
        # selecting a sibling cannot make later facts eligible for it.
        rebuilt = rebuild_model_input(transcript, snapshot_id)
        assert rebuilt.snapshot.source_revision == 1

        snapshot_record = next(
            record
            for record in transcript.records
            if getattr(record.payload, "snapshot_id", None) == snapshot_id
        )
        reference = snapshot_record.payload.logical_root
        object.__setattr__(reference, "record_id", transcript.leaf_id)
        with pytest.raises(ModelInputIntegrityError, match="ancestry"):
            rebuild_model_input(transcript, snapshot_id)

    asyncio.run(scenario())


def test_model_input_v2_branch_back_never_reuses_sibling_nodes() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        selected_root_id = transcript.leaf_id
        assert selected_root_id is not None
        await transcript.append_agent_message(
            UserMessage(role="user", content="left", timestamp=2.0)
        )
        left = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await left.commit_prepared_request(_prepared(invocation_id="left"))
        left_record_id = left.commits[-1].record_id
        left_components = {
            record.record_id
            for record in transcript.records_to(left_record_id)
            if record.kind == MODEL_INPUT_COMPONENT_KIND
        }

        transcript.branch(selected_root_id)
        await transcript.append_agent_message(
            UserMessage(role="user", content="right", timestamp=3.0)
        )
        right = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await right.commit_prepared_request(_prepared(invocation_id="right"))
        right_record_id = right.commits[-1].record_id
        right_components = {
            record.record_id
            for record in transcript.records_to(right_record_id)
            if record.kind == MODEL_INPUT_COMPONENT_KIND
        }

        assert left_components
        assert right_components
        assert left_components.isdisjoint(right_components)
        assert rebuild_model_input(transcript, left.commits[-1].snapshot_id)
        assert rebuild_model_input(transcript, right.commits[-1].snapshot_id)

    asyncio.run(scenario())


def test_model_input_v2_reconstruction_rejects_an_invalid_node_ordinal() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        snapshot_id = committer.commits[-1].snapshot_id
        snapshot_record = next(
            record
            for record in transcript.records
            if isinstance(record.payload, ModelInputSnapshotV2)
            and record.payload.snapshot_id == snapshot_id
        )
        object.__setattr__(snapshot_record.payload.logical_root, "ordinal", 10_000)

        with pytest.raises(ModelInputIntegrityError, match="ordinal"):
            rebuild_model_input(transcript, snapshot_id)

    asyncio.run(scenario())


def test_model_input_v2_reconstruction_rejects_a_wrong_kind_ancestor() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        snapshot_id = committer.commits[-1].snapshot_id
        snapshot_record = next(
            record
            for record in transcript.records
            if isinstance(record.payload, ModelInputSnapshotV2)
            and record.payload.snapshot_id == snapshot_id
        )
        object.__setattr__(
            snapshot_record.payload.logical_root,
            "record_id",
            snapshot_record.payload.source_leaf_id,
        )

        with pytest.raises(ModelInputIntegrityError, match="node bundle"):
            rebuild_model_input(transcript, snapshot_id)

    asyncio.run(scenario())


def test_model_input_v2_reconstruction_rejects_the_wrong_payload_version() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        snapshot_id = committer.commits[-1].snapshot_id
        snapshot_record = next(
            record
            for record in transcript.records
            if isinstance(record.payload, ModelInputSnapshotV2)
            and record.payload.snapshot_id == snapshot_id
        )
        object.__setattr__(snapshot_record, "payload_version", 1)

        with pytest.raises(ModelInputIntegrityError, match="payload version"):
            rebuild_model_input(transcript, snapshot_id)

    asyncio.run(scenario())


def _context_source_leaf(transcript: AgentTranscriptUnitOfWork) -> str:
    first = transcript.records[0]
    return first.record_id


def test_record_limit_and_revision_conflict_fail_before_transport() -> None:
    async def oversized() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(
                transcript,
                logical_input={
                    "system_prompt": "x" * 4_096,
                    "messages": [],
                    "tools": [],
                    "request_options": {},
                },
            ),
            runtime_references=_runtime_references(),
            max_encoded_record_bytes=512,
        )

        with pytest.raises(ModelInputRecordSizeError) as exc_info:
            await committer.commit_prepared_request(_prepared())

        assert exc_info.value.info.code.value == "request_validation"

        report = await run_prepared_request_barrier_conformance(committer)

        assert report.transport_calls == 0
        assert report.error is not None
        assert not any(
            record.kind in {MODEL_INPUT_COMPONENT_KIND, MODEL_INPUT_PREPARED_KIND}
            for record in transcript.records
        )

    async def conflicted() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await transcript.append_agent_message(
            UserMessage(role="user", content="concurrent", timestamp=2.0)
        )

        with pytest.raises(ModelInputIntegrityError):
            await committer.commit_prepared_request(_prepared())

        report = await run_prepared_request_barrier_conformance(committer)

        assert report.transport_calls == 0
        assert report.error is not None

    asyncio.run(oversized())
    asyncio.run(conflicted())


def test_model_input_hard_record_ceiling_cannot_be_bypassed() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        with pytest.raises(ValueError, match="must not exceed"):
            ModelInputTranscriptCommitter(
                transcript=transcript,
                context=_context(transcript),
                runtime_references=_runtime_references(),
                max_encoded_record_bytes=(MODEL_INPUT_MAX_ENCODED_RECORD_BYTES + 1),
            )

        content = "x" * MODEL_INPUT_MAX_ENCODED_RECORD_BYTES
        component = ModelInputComponent(
            content_hash=hash_model_input_json(
                content,
                name="oversized Model Input component",
            ),
            content=content,
        )
        with pytest.raises(ModelInputRecordSizeError):
            await transcript.append(MODEL_INPUT_COMPONENT_KIND, component)

        record = AgentTranscriptRecordFactory().create(
            MODEL_INPUT_COMPONENT_KIND,
            component,
            parent_id=transcript.leaf_id,
        )
        with pytest.raises(ModelInputRecordSizeError):
            await transcript.commit(record)

        initial_backend = MemoryConversationStore(record_id=lambda item: item.record_id)
        initial_record = AgentTranscriptRecordFactory().create(
            MODEL_INPUT_COMPONENT_KIND,
            component,
            parent_id=None,
        )
        with pytest.raises(ModelInputRecordSizeError):
            await AgentTranscriptUnitOfWork.create(
                initial_backend,
                ConversationKey("initial", "oversized-model-input"),
                _header("oversized-model-input"),
                records=(initial_record,),
            )
        assert await initial_backend.scan("initial") == ()

    asyncio.run(scenario())


def test_model_input_snapshot_requires_the_v1_logical_surface() -> None:
    reference = ModelInputComponentReference(
        name="messages",
        record_id="component-record",
        content_hash="a" * 64,
    )
    snapshot = ModelInputSnapshot(
        snapshot_id="snapshot-1",
        invocation_id="invocation-1",
        attempt=1,
        purpose="main_turn",
        product_id="coding",
        runtime_id="runtime-1",
        mount_generation=1,
        profile_fingerprint="b" * 64,
        registration_revision="c" * 64,
        conversation_id="conversation-1",
        source_leaf_id="source-record",
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        model_id="model-1",
        api_id="api-1",
        endpoint_id="endpoint-1",
        logical_components=tuple(
            replace(reference, name=name)
            for name in ("system_prompt", "messages", "tools", "request_options")
        ),
        prepared_payload_components=(),
        model_visible_headers_component=replace(
            reference,
            name="model_visible_headers",
        ),
        logical_input_hash="d" * 64,
        prepared_payload_hash="e" * 64,
    )

    with pytest.raises(ValueError, match="logical components are missing"):
        replace(snapshot, logical_components=())
    with pytest.raises(ValueError, match="model_visible_headers"):
        replace(snapshot, model_visible_headers_component=reference)


@pytest.mark.parametrize(
    ("invalid_name", "invalid_value", "error"),
    (
        ("messages", {}, "messages must be an array"),
        ("tools", {}, "tools must be an array"),
        ("request_options", [], "request options must be an object"),
    ),
)
def test_reconstruction_rejects_invalid_v1_logical_component_types(
    invalid_name: str,
    invalid_value: object,
    error: str,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        assert transcript.leaf_id is not None
        source_leaf_id = transcript.leaf_id
        source_revision = transcript.revision
        logical_input: dict[str, object] = {
            "system_prompt": "system prompt",
            "messages": [],
            "tools": [],
            "request_options": {},
        }
        logical_input[invalid_name] = invalid_value

        references: list[ModelInputComponentReference] = []
        for name, content in logical_input.items():
            component_hash = hash_model_input_json(
                content,
                name=f"invalid Model Input {name}",
            )
            commit = await transcript.append(
                MODEL_INPUT_COMPONENT_KIND,
                ModelInputComponent(
                    content_hash=component_hash,
                    content=content,
                ),
            )
            references.append(
                ModelInputComponentReference(
                    name=name,
                    record_id=commit.record.record_id,
                    content_hash=component_hash,
                )
            )

        headers_hash = hash_model_input_json(
            {},
            name="invalid Model Input headers",
        )
        headers_commit = await transcript.append(
            MODEL_INPUT_COMPONENT_KIND,
            ModelInputComponent(content_hash=headers_hash, content={}),
        )
        snapshot = ModelInputSnapshot(
            snapshot_id=f"invalid-{invalid_name}",
            invocation_id="invocation-1",
            attempt=1,
            purpose="main_turn",
            product_id="coding",
            runtime_id="runtime-1",
            mount_generation=1,
            profile_fingerprint="a" * 64,
            registration_revision="b" * 64,
            conversation_id=transcript.header.conversation_id,
            source_leaf_id=source_leaf_id,
            source_revision=source_revision,
            commit_revision=transcript.revision + 1,
            provider_id="provider-1",
            model_id="model-1",
            api_id="api-1",
            endpoint_id="endpoint-1",
            logical_components=tuple(references),
            prepared_payload_components=(),
            model_visible_headers_component=ModelInputComponentReference(
                name="model_visible_headers",
                record_id=headers_commit.record.record_id,
                content_hash=headers_hash,
            ),
            logical_input_hash=hash_model_input_json(
                logical_input,
                name="invalid logical Model Input",
            ),
            prepared_payload_hash=hash_model_input_json(
                {"model_visible_headers": {}, "payload": {}},
                name="empty prepared Model Input",
            ),
        )
        await transcript.append(MODEL_INPUT_PREPARED_KIND, snapshot)

        with pytest.raises(ModelInputIntegrityError, match=error):
            rebuild_model_input(transcript, snapshot.snapshot_id)

    asyncio.run(scenario())


def test_model_input_commit_propagates_cancellation_after_safe_append() -> None:
    async def scenario() -> None:
        backend = _BlockingModelInputStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        backend.block_appends = True

        task = asyncio.create_task(committer.commit_prepared_request(_prepared()))
        await backend.committed.wait()
        task.cancel()
        await asyncio.sleep(0)

        assert task.done() is False
        backend.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert any(
            record.kind == MODEL_INPUT_COMPONENT_KIND for record in transcript.records
        )
        assert not any(
            record.kind == MODEL_INPUT_PREPARED_KIND for record in transcript.records
        )

        backend.block_appends = False
        resumed = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await resumed.commit_prepared_request(
            _prepared(invocation_id="invocation-after-cancel")
        )
        assert rebuild_model_input(
            transcript,
            resumed.commits[-1].snapshot_id,
        ).logical_input["messages"] == [{"role": "user", "content": "hello"}]

    asyncio.run(scenario())


class _AgentPreparedAdapter:
    api = "model-input-agent-test"

    def __init__(self) -> None:
        self.transport_calls = 0

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        context = request.context
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": getattr(context, "system_prompt", None),
                "messages": [
                    serialize_message(message)
                    for message in getattr(context, "messages", ())
                ],
                "tools": [],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[dict[str, object]]:
        del request
        self.transport_calls += 1
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": "response-1"}
        yield {"type": "text_delta", "text": "done"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part


@pytest.mark.requires_host_runtime
def test_main_agent_turn_rebuilds_after_restart_and_source_deletion(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source = tmp_path / "SYSTEM.md"
        source.write_text("durable system prompt", encoding="utf-8")
        system_prompt = source.read_text(encoding="utf-8")
        layout = AgentTranscriptFileLayout(tmp_path / "sessions")
        key = layout.key("model-input-conversation")
        transcript = await AgentTranscriptUnitOfWork.create(
            create_agent_transcript_file_store(layout),
            key,
            _header(),
        )
        await transcript.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(
                transcript,
                logical_input={
                    "system_prompt": system_prompt,
                    "messages": [{"role": "user", "content": "hello"}],
                    "tools": [],
                    "request_options": {},
                },
            ),
            runtime_references=_runtime_references(),
        )
        adapter = _AgentPreparedAdapter()
        registry = get_default_api_registry()
        source_id = "test-model-input-agent-adapter"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": system_prompt,
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            call_options=CallOptions(prepared_request_committer=committer),
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)
        assert adapter.transport_calls == 1
        commit = committer.commits[-1]

        source.unlink()
        restarted_layout = AgentTranscriptFileLayout(tmp_path / "sessions")
        restarted = await AgentTranscriptUnitOfWork.load(
            create_agent_transcript_file_store(restarted_layout),
            restarted_layout.key("model-input-conversation"),
        )
        rebuilt = rebuild_model_input(restarted, commit.snapshot_id)

        assert source.exists() is False
        assert rebuilt.logical_input["system_prompt"] == "durable system prompt"
        assert rebuilt.prepared_payload["system"] == "durable system prompt"
        assert verify_model_input(restarted, commit.snapshot_id).verified
        assert restarted.replay_context().messages == (
            UserMessage(role="user", content="hello", timestamp=1.0),
        )
        path = restarted_layout.resolve_path(key)
        assert path is not None
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            envelope = json.loads(line)
            if envelope.get("kind", "").startswith("model.input."):
                assert len((line + "\n").encode("utf-8")) <= 1024 * 1024

    asyncio.run(scenario())
