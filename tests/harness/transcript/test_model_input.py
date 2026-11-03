from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.agent import Agent
from loushang.ai import prepared_request as prepared_request_module
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
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.capabilities import (
    MountGraphSnapshot,
    RegistrationInventorySnapshot,
)
from loushang.harness.conversation import (
    ConversationCommitResult,
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
    StoreCommitOutcomeUnknown,
)
from loushang.harness.transcript import (
    MODEL_CALL_ATTEMPT_USAGE_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
    MODEL_INPUT_PREPARED_KIND,
    AgentTranscriptFileLayout,
    AgentTranscriptRecordFactory,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    BranchContextSummary,
    ModelCallAttemptUsage,
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
    project_model_call_usage,
    rebuild_model_input,
    verify_model_input,
)
from loushang.harness.transcript import model_input as model_input_module
from loushang.harness.transcript import model_input_v2 as model_input_v2_module
from loushang.harness.transcript.model_input_blobs import SessionModelInputBlobCodec
from loushang.harness.transcript.model_input_types import (
    canonical_model_input_json,
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
    create_model_input_json_value,
    hash_model_input_node,
    model_input_node_hash_basis,
    model_input_node_to_json,
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
    reuse_from: PreparedModelRequest | None = None,
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
        reuse_from=reuse_from,
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


@pytest.mark.parametrize("has_image", [False, True])
def test_model_input_releases_unused_binary_projection_before_indexing(
    tmp_path, monkeypatch, has_image
):
    import weakref

    class WeakMapping(dict):
        pass

    class TrackingCodec(SessionModelInputBlobCodec):
        roots = []

        def externalize_mapping(self, value, **kwargs):
            projected = super().externalize_mapping(value, **kwargs)
            root = WeakMapping(projected.value)
            self.roots.append(weakref.ref(root))
            return replace(projected, value=root)

    async def scenario():
        transcript = await _memory_transcript()
        store = SessionBlobStore(tmp_path / "data", "model-input-conversation")
        codec = TrackingCodec(store)
        logical = dict(thaw_model_input_json(_context(transcript).logical_input))
        if has_image:
            image = b"projection-lifetime-image"
            store.put_bytes(
                image,
                logical_name="images/input.png",
                kind="image",
                media_type="image/png",
                source="test",
            )
            logical["messages"] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "mimeType": "image/png",
                            "data": base64.b64encode(image).decode("ascii"),
                        }
                    ],
                }
            ]
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=logical),
            runtime_references=_runtime_references(),
            binary_codec=codec,
        )
        original = model_input_v2_module.ModelInputV2Writer.prepare

        async def prepare(cls, **kwargs):
            assert len(codec.roots) == 2
            assert all(
                (reference() is not None) == has_image for reference in codec.roots
            ), "unused full request copies survived into cold index construction"
            return await original(**kwargs)

        monkeypatch.setattr(
            model_input_v2_module.ModelInputV2Writer, "prepare", classmethod(prepare)
        )
        request = _prepared()
        await committer.commit_prepared_request(request)
        rebuilt = rebuild_model_input(
            transcript, committer.commits[0].snapshot_id, binary_codec=codec
        )
        assert rebuilt.logical_input == logical
        assert rebuilt.prepared_payload_hash == request.payload_hash

    asyncio.run(scenario())


def test_plain_model_input_materializes_frozen_messages_without_full_thaw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        logical = {
            "system_prompt": "system prompt",
            "messages": [
                {"role": "user", "content": f"message {index}"}
                for index in range(200)
            ],
            "tools": [],
            "request_options": {},
        }
        context = _context(transcript, logical_input=logical)
        first_committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=context,
            runtime_references=_runtime_references(),
        )
        await first_committer.commit_prepared_request(_prepared())
        await transcript.append_agent_message(
            UserMessage(role="user", content="latest", timestamp=2.0)
        )
        assert transcript.leaf_id is not None
        logical = {**logical, "messages": [*logical["messages"], {"role": "user", "content": "latest"}]}
        next_context = ModelInputCommitContext(
            purpose="main_turn",
            source_leaf_id=transcript.leaf_id,
            source_revision=transcript.revision,
            logical_input=logical,
            reuse_from=context,
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=next_context,
            runtime_references=_runtime_references(),
        )
        original_thaw = model_input_module.thaw_model_input_json
        full_thaws = 0

        def thaw(value):
            nonlocal full_thaws
            if value is next_context.logical_input:
                full_thaws += 1
            return original_thaw(value)

        monkeypatch.setattr(model_input_module, "thaw_model_input_json", thaw)
        await committer.commit_prepared_request(_prepared(invocation_id="invocation-2"))

        assert full_thaws == 0
        assert (
            rebuild_model_input(transcript, committer.commits[-1].snapshot_id)
            .logical_input
            == logical
        )

    asyncio.run(scenario())


def test_owned_prepared_request_commits_without_copying_sealed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        first_request = _prepared()
        await committer.commit_prepared_request(first_request)
        await transcript.append_agent_message(
            UserMessage(role="user", content="latest", timestamp=2.0)
        )
        next_committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        next_payload = first_request.payload_for_transport()
        next_payload["messages"].append({"role": "user", "content": "latest"})
        request = _prepared(
            invocation_id="invocation-2",
            payload=next_payload,
            reuse_from=first_request,
        )
        copies = 0
        original_copy = PreparedModelRequest._owned_payload_copy

        def copy(request: PreparedModelRequest):
            nonlocal copies
            copies += 1
            return original_copy(request)

        monkeypatch.setattr(PreparedModelRequest, "_owned_payload_copy", copy)
        await next_committer.commit_prepared_request(request)

        assert copies == 0
        assert (
            rebuild_model_input(transcript, next_committer.commits[-1].snapshot_id)
            .prepared_payload
            == thaw_model_input_json(request.payload)
        )

    asyncio.run(scenario())


def test_prewarmed_logical_canonical_is_committed_without_reencoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        logical = {
            "system_prompt": "system",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [],
            "request_options": {},
        }
        context = _context(transcript, logical_input=logical)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=context,
            runtime_references=_runtime_references(),
            binary_codec=SessionModelInputBlobCodec(
                SessionBlobStore(tmp_path / "data", "model-input-conversation")
            ),
        )
        await committer.prewarm_logical_input()
        prewarmed = committer._prewarmed_logical_canonical
        assert prewarmed is not None
        canonical, digest = prewarmed

        def unexpected_reencode(_context: object, _value: object) -> str:
            pytest.fail("prewarmed logical input was encoded again during commit")

        monkeypatch.setattr(
            ModelInputCommitContext,
            "_canonical_logical_input_json",
            unexpected_reencode,
        )
        await committer.commit_prepared_request(_prepared())
        rebuilt = rebuild_model_input(
            transcript,
            committer.commits[-1].snapshot_id,
            binary_codec=SessionModelInputBlobCodec(
                SessionBlobStore(tmp_path / "data", "model-input-conversation")
            ),
        )
        assert rebuilt.logical_input == logical
        assert rebuilt.snapshot.logical_input_hash == digest
        assert canonical == model_input_module.canonical_model_input_json(
            logical, name="logical Model Input"
        )

    asyncio.run(scenario())


def test_cancelled_prewarm_worker_settles_before_direct_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    async def scenario() -> None:
        transcript = await _memory_transcript()
        context = _context(transcript)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=context,
            runtime_references=_runtime_references(),
            binary_codec=SessionModelInputBlobCodec(
                SessionBlobStore(tmp_path / "data", "model-input-conversation")
            ),
        )
        started = threading.Event()
        release = threading.Event()
        original_prepare = committer._prepare_logical_canonical
        original_canonical = ModelInputCommitContext._canonical_logical_input_json

        def held_prepare() -> tuple[str, str]:
            started.set()
            assert release.wait(1.0)
            return original_prepare()

        def guarded_canonical(self, value):
            assert release.is_set(), "commit encoded while cancelled prewarm was active"
            return original_canonical(self, value)

        monkeypatch.setattr(committer, "_prepare_logical_canonical", held_prepare)
        monkeypatch.setattr(
            ModelInputCommitContext,
            "_canonical_logical_input_json",
            guarded_canonical,
        )
        prewarm = asyncio.create_task(committer.prewarm_logical_input())
        assert await asyncio.to_thread(started.wait, 1.0)
        prewarm.cancel()
        with pytest.raises(asyncio.CancelledError):
            await prewarm
        try:
            commit = asyncio.create_task(committer.commit_prepared_request(_prepared()))
            await asyncio.sleep(0.05)
            assert not commit.done(), "commit did not wait for the existing worker"
        finally:
            release.set()
        await commit
        assert len(committer.commits) == 1

    asyncio.run(scenario())


def test_model_input_omits_plain_builtin_binary_projection(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        codec = SessionModelInputBlobCodec(
            SessionBlobStore(tmp_path / "data", "model-input-conversation")
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
            binary_codec=codec,
        )

        def unnecessary_projection(*args, **kwargs):
            raise AssertionError("plain request copied through blob projection")

        monkeypatch.setattr(
            SessionModelInputBlobCodec,
            "externalize_mapping",
            unnecessary_projection,
        )
        request = _prepared()
        await committer.commit_prepared_request(request)
        rebuilt = rebuild_model_input(transcript, committer.commits[-1].snapshot_id)
        assert rebuilt.prepared_payload == request.payload_for_transport()
        assert rebuilt.snapshot.binary_projection_version == 0

    asyncio.run(scenario())


def test_plain_model_input_does_not_open_deferred_blob_authority(tmp_path) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        codec = SessionModelInputBlobCodec(
            SessionBlobStore(tmp_path / "data", "model-input-conversation")
        )
        openings = 0

        def open_codec() -> SessionModelInputBlobCodec:
            nonlocal openings
            openings += 1
            return codec

        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
            binary_codec_factory=open_codec,
        )
        await committer.commit_prepared_request(_prepared())
        assert openings == 0
        rebuilt = rebuild_model_input(transcript, committer.commits[-1].snapshot_id)
        assert rebuilt.snapshot.binary_projection_version == 0

    asyncio.run(scenario())


def test_prepared_payload_projection_does_not_hold_two_complete_container_trees():
    import tracemalloc

    request = _prepared(
        payload={
            "rows": [
                {"index": i, "text": "message", "flags": [True, None]}
                for i in range(2500)
            ]
        }
    )
    tracemalloc.start()
    try:
        projected = model_input_module._prepared_json_mapping(request, "payload")
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(projected["rows"]) == 2500
    assert peak < retained * 1.5, (
        "projection retained an extra frozen tree while copying"
    )


def test_owned_prepared_request_commits_without_recanonicalizing_payload(
    monkeypatch,
):
    async def scenario():
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        request = _prepared()

        def unexpected_recanonicalization(*_args, **_kwargs):
            raise AssertionError("sealed prepared payload was recanonicalized")

        monkeypatch.setattr(
            model_input_module,
            "canonical_model_input_json",
            unexpected_recanonicalization,
        )
        monkeypatch.setattr(
            prepared_request_module,
            "validate_json_value",
            unexpected_recanonicalization,
        )
        await committer.commit_prepared_request(request)
        assert len(committer.commits) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["cycle", "nan", "surrogate", "non_string_key"])
def test_invalid_prepared_payload_is_rejected_before_any_model_input_write(invalid):
    async def scenario():
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        request = _prepared()
        if invalid == "cycle":
            payload = {}
            payload["self"] = payload
        elif invalid == "nan":
            payload = {"nested": [float("nan")]}
        elif invalid == "surrogate":
            payload = {"nested": ["\ud800"]}
        else:
            payload = {1: "invalid key"}
        object.__setattr__(request, "payload", payload)
        before = transcript.records
        with pytest.raises(TypeError):
            await committer.commit_prepared_request(request)
        assert transcript.records == before
        assert not committer.commits

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "attribute,replacement",
    [
        ("payload", {"messages": []}),
        ("model_visible_headers", {"anthropic-beta": "changed"}),
        ("canonical_payload", "{}"),
        ("payload_hash", "sha256:" + "0" * 64),
    ],
)
def test_changed_prepared_envelope_is_rejected_before_model_input_write(
    attribute, replacement
):
    async def scenario():
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        request = _prepared()
        object.__setattr__(request, attribute, replacement)
        before = transcript.records
        with pytest.raises(ModelInputIntegrityError):
            await committer.commit_prepared_request(request)
        assert transcript.records == before
        assert not committer.commits

    asyncio.run(scenario())


def test_model_input_externalizes_session_images_without_losing_exact_rebuild(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        store = SessionBlobStore(tmp_path / "data", "model-input-conversation")
        image = b"model-input-image-bytes"
        encoded = base64.b64encode(image).decode("ascii")
        store.put_bytes(
            image,
            logical_name="images/user.png",
            kind="image",
            media_type="image/png",
            source="transcript-image:user",
        )
        logical_input = {
            "system_prompt": "system prompt",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "data": encoded,
                            "mimeType": "image/png",
                        }
                    ],
                }
            ],
            "tools": [],
            "request_options": {},
        }
        prepared_payload = {
            "model": "model-input-model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        }
                    ],
                }
            ],
        }
        codec = SessionModelInputBlobCodec(store)
        openings = 0

        def open_codec() -> SessionModelInputBlobCodec:
            nonlocal openings
            openings += 1
            return codec

        context = _context(transcript, logical_input=logical_input)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=context,
            runtime_references=_runtime_references(),
            binary_codec_factory=open_codec,
        )

        original_thaw = model_input_module.thaw_model_input_json
        full_logical_thaws = 0

        def thaw(value):
            nonlocal full_logical_thaws
            if value is context.logical_input:
                full_logical_thaws += 1
            return original_thaw(value)

        monkeypatch.setattr(model_input_module, "thaw_model_input_json", thaw)
        await committer.commit_prepared_request(_prepared(payload=prepared_payload))
        assert openings == 1
        assert full_logical_thaws == 1

        snapshot_id = committer.commits[0].snapshot_id
        snapshot_record = next(
            record
            for record in transcript.records
            if record.kind == MODEL_INPUT_PREPARED_KIND
        )
        assert isinstance(snapshot_record.payload, ModelInputSnapshotV2)
        assert snapshot_record.payload.binary_projection_version == 1
        model_input_wire_repr = json.dumps(
            [
                model_input_node_to_json(node)
                for record in transcript.records
                if record.kind == MODEL_INPUT_COMPONENT_KIND
                and isinstance(record.payload, ModelInputNodeBundle)
                for node in record.payload.nodes
            ],
            sort_keys=True,
        )
        assert encoded not in model_input_wire_repr
        assert "$loushang.sessionBlob" in model_input_wire_repr

        rebuilt = rebuild_model_input(
            transcript,
            snapshot_id,
            binary_codec=codec,
        )
        assert rebuilt.logical_input == logical_input
        assert rebuilt.prepared_payload == prepared_payload
        assert verify_model_input(
            transcript,
            snapshot_id,
            binary_codec=codec,
        ).verified
        with pytest.raises(ModelInputIntegrityError, match="blob authority"):
            rebuild_model_input(transcript, snapshot_id)

    asyncio.run(scenario())


def test_model_input_reserved_literal_alone_sets_projection_version(tmp_path) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        logical_input = {
            "system_prompt": "system prompt",
            "messages": [],
            "tools": [],
            "request_options": {"$loushang.sessionBlob": {"application": "literal"}},
        }
        prepared_payload = {
            "model": "model-input-model",
            "metadata": {"$loushang.literal": {"application": "literal"}},
        }
        codec = SessionModelInputBlobCodec(
            SessionBlobStore(tmp_path / "data", "model-input-conversation")
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=logical_input),
            runtime_references=_runtime_references(),
            binary_codec=codec,
        )

        await committer.commit_prepared_request(_prepared(payload=prepared_payload))

        snapshot_id = committer.commits[0].snapshot_id
        snapshot = next(
            record.payload
            for record in transcript.records
            if record.kind == MODEL_INPUT_PREPARED_KIND
        )
        assert isinstance(snapshot, ModelInputSnapshotV2)
        assert snapshot.binary_projection_version == 1
        rebuilt = rebuild_model_input(
            transcript,
            snapshot_id,
            binary_codec=codec,
        )
        assert rebuilt.logical_input == logical_input
        assert rebuilt.prepared_payload == prepared_payload

    asyncio.run(scenario())


def test_incremental_logical_hash_preserves_literal_projection(tmp_path) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        logical = {
            "system_prompt": "system prompt",
            "messages": [],
            "tools": [],
            "request_options": {},
        }
        first = ModelInputCommitContext(
            purpose="main_turn",
            source_leaf_id=transcript.leaf_id,
            source_revision=transcript.revision,
            logical_input=logical,
        )
        first._canonical_owned_logical_input(
            model_input_module._logical_input_for_materialization(first.logical_input)
        )
        logical["messages"] = [
            {"role": "user", "content": {"$loushang.literal": "unchanged"}}
        ]
        context = ModelInputCommitContext(
            purpose="main_turn",
            source_leaf_id=transcript.leaf_id,
            source_revision=transcript.revision,
            logical_input=logical,
            reuse_from=first,
        )
        codec = SessionModelInputBlobCodec(
            SessionBlobStore(tmp_path / "data", "model-input-conversation")
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=context,
            runtime_references=_runtime_references(),
            binary_codec=codec,
        )
        await committer.prewarm_logical_input()
        assert committer._prewarmed_logical_canonical is not None
        assert committer._prewarmed_logical_canonical[0] is None
        await committer.commit_prepared_request(_prepared())
        rebuilt = rebuild_model_input(
            transcript, committer.commits[-1].snapshot_id, binary_codec=codec
        )
        assert rebuilt.snapshot.binary_projection_version == 1
        assert rebuilt.logical_input == logical

    asyncio.run(scenario())


def test_model_input_commit_emits_one_aggregate_performance_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    class _TimingLog:
        def debug_event(self, scope: str, name: str, **data: object) -> None:
            events.append((scope, name, data))

    monkeypatch.setattr(
        model_input_module,
        "_MODEL_INPUT_PERFORMANCE_LOG",
        _TimingLog(),
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        prepared = _prepared()

        await committer.commit_prepared_request(prepared)

        assert len(events) == 1
        scope, name, data = events[0]
        assert (scope, name) == ("model_input.performance", "commit")
        assert data["outcome"] == "completed"
        assert data["provider_id"] == prepared.provider_id
        assert data["model_id"] == prepared.model_id
        assert data["message_count"] == prepared.metrics.message_count
        assert data["canonical_bytes"] == prepared.metrics.canonical_bytes
        assert data["node_index_cache_status"] == "rebuilt"
        assert "payload" not in data
        assert "canonical_payload" not in data
        phases = data["phases"]
        assert isinstance(phases, dict)
        assert set(phases) == {
            "preconditions",
            "validate_prepared_request",
            "post_validation_yield",
            "logical_input_thaw",
            "pre_writer_yield",
            "active_path",
            "node_index_build",
            "resolver_build",
            "materialize",
            "snapshot_build",
            "append_snapshot",
            "incremental_verify",
            "publish_commit",
        }
        assert all(
            isinstance(value, dict)
            and value["count"] == 1
            and isinstance(value["total_ms"], float)
            and value["total_ms"] >= 0
            for value in phases.values()
        )
        materialize_phases = data["materialize_phases"]
        assert isinstance(materialize_phases, dict)
        assert set(materialize_phases) == {
            "plan",
            "values",
            "sequences",
            "roots",
        }
        assert all(
            isinstance(value, dict)
            and value["count"] == 1
            and isinstance(value["total_ms"], float)
            and value["total_ms"] >= 0
            for value in materialize_phases.values()
        )
        assert "payload" not in materialize_phases
        assert "canonical_payload" not in materialize_phases
        assert data["materialize_counts"] == {
            "sequence_count": 4,
            "sequence_item_count": 4,
            "reused_prefix_item_count": 0,
            "planned_item_count": 4,
        }

        events.clear()
        with pytest.raises(
            ModelInputIntegrityError,
            match="changed logical invocation identity",
        ):
            await committer.commit_prepared_request(
                _prepared(invocation_id="different-invocation", attempt=2)
            )

        assert len(events) == 1
        _, _, failed_data = events[0]
        assert failed_data["outcome"] == "failed"
        assert set(failed_data["phases"]) == {"preconditions"}
        assert failed_data["materialize_phases"] == {}
        assert failed_data["materialize_counts"] == {}

    asyncio.run(scenario())


def test_model_input_commit_does_not_rebuild_the_committed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_full_rebuild(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("normal Model Input commit performed a full rebuild")

    monkeypatch.setattr(
        model_input_module,
        "rebuild_model_input",
        fail_full_rebuild,
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )

        await committer.commit_prepared_request(_prepared())

        assert len(committer.commits) == 1

    asyncio.run(scenario())


def test_model_input_commit_falls_back_to_full_rebuild_when_incremental_proof_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rebuilt_snapshot_ids: list[str] = []
    full_rebuild = model_input_module.rebuild_model_input

    def fail_incremental_proof(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ModelInputIntegrityError("incremental proof unavailable")

    def track_full_rebuild(
        transcript: AgentTranscriptUnitOfWork,
        snapshot_id: str,
    ) -> object:
        rebuilt_snapshot_ids.append(snapshot_id)
        return full_rebuild(transcript, snapshot_id)

    monkeypatch.setattr(
        model_input_v2_module.ModelInputV2Writer,
        "verify_snapshot_commit",
        fail_incremental_proof,
    )
    monkeypatch.setattr(
        model_input_module,
        "rebuild_model_input",
        track_full_rebuild,
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )

        await committer.commit_prepared_request(_prepared())

        assert rebuilt_snapshot_ids == [committer.commits[0].snapshot_id]

    asyncio.run(scenario())


def test_model_input_v2_node_index_cache_extends_selected_ancestry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0
    resolver_builds = 0
    original_init = model_input_v2_module.ModelInputV2NodeIndex.__init__
    original_resolver_init = model_input_v2_module.ModelInputV2Resolver.__init__

    def counting_init(self, records) -> None:
        nonlocal builds
        builds += 1
        original_init(self, records)

    def counting_resolver_init(self, records) -> None:
        nonlocal resolver_builds
        resolver_builds += 1
        original_resolver_init(self, records)

    monkeypatch.setattr(
        model_input_v2_module.ModelInputV2NodeIndex,
        "__init__",
        counting_init,
    )
    monkeypatch.setattr(
        model_input_v2_module.ModelInputV2Resolver,
        "__init__",
        counting_resolver_init,
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        first = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await first.commit_prepared_request(_prepared(invocation_id="first"))
        await transcript.append_agent_message(
            UserMessage(role="user", content="next", timestamp=2.0)
        )
        second = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await second.commit_prepared_request(_prepared(invocation_id="second"))

        assert builds == 1
        assert resolver_builds == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["none", "cancel", "branch", "commit"])
def test_model_input_validation_yields_before_writing(monkeypatch, change):
    async def scenario():
        transcript = await _memory_transcript()
        root = transcript.leaf_id
        await transcript.append_agent_message(
            UserMessage(role="user", content="next", timestamp=2.0)
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        before = transcript.records
        validated = asyncio.Event()
        original = model_input_module._validate_prepared_request

        def validate(request):
            result = original(request)
            validated.set()
            return result

        monkeypatch.setattr(model_input_module, "_validate_prepared_request", validate)
        job = asyncio.create_task(committer.commit_prepared_request(_prepared()))
        await validated.wait()
        assert not job.done(), "request validation blocked input until durable writes"
        assert transcript.records == before
        if change == "cancel":
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
            assert transcript.records == before
        elif change == "branch":
            transcript.branch(root)
            with pytest.raises(ModelInputIntegrityError, match="changed"):
                await job
            transcript.branch(before[-1].record_id)
            assert transcript.records == before
        elif change == "commit":
            await transcript.append_agent_message(
                UserMessage(role="user", content="other", timestamp=2.0)
            )
            with pytest.raises(ModelInputIntegrityError, match="changed"):
                await job
            assert len(transcript.records) == len(before) + 1
        else:
            await job
            rebuilt = rebuild_model_input(transcript, committer.commits[0].snapshot_id)
            assert rebuilt.prepared_payload_hash == _prepared().payload_hash
        if change != "none":
            assert not committer.commits

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["none", "cancel", "branch", "commit"])
@pytest.mark.parametrize("warm", [False, True])
def test_model_input_planning_services_input_before_finishing(
    monkeypatch, change, warm
):
    import threading

    async def scenario():
        transcript = await _memory_transcript()
        root = transcript.leaf_id
        if warm:
            first = ModelInputTranscriptCommitter(
                transcript=transcript,
                context=_context(transcript),
                runtime_references=_runtime_references(),
            )
            await first.commit_prepared_request(_prepared())
        await transcript.append_agent_message(
            UserMessage(role="user", content="continue", timestamp=3.0)
        )
        messages = [{"role": "user", "content": str(i)} for i in range(30)]
        logical = dict(thaw_model_input_json(_context(transcript).logical_input))
        logical["messages"] = messages
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=logical),
            runtime_references=_runtime_references(),
        )
        request = _prepared(payload={"messages": messages})
        before = transcript.records
        prior_cache = model_input_v2_module._MODEL_INPUT_V2_INDEX_CACHES.get(transcript)
        prior_plans = {} if prior_cache is None else dict(prior_cache.sequence_plans)
        planning = asyncio.Event()
        release_planning = threading.Event()
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        planning_thread = None
        collected = []
        original = model_input_v2_module.ModelInputV2Writer._collect_value

        def collect(writer, value):
            nonlocal planning_thread
            result = original(writer, value)
            collected.append(value)
            if len(collected) == 3:
                planning_thread = threading.get_ident()
                if planning_thread == loop_thread:
                    planning.set()
                else:
                    loop.call_soon_threadsafe(planning.set)
                    release_planning.wait(timeout=10)
            return result

        monkeypatch.setattr(
            model_input_v2_module.ModelInputV2Writer, "_collect_value", collect
        )
        job = asyncio.create_task(committer.commit_prepared_request(request))
        await planning.wait()
        assert planning_thread != loop_thread, "planning occupied the input event loop"
        assert not job.done()
        assert len(collected) < 30, "planning a long request blocked pending input"
        assert transcript.records == before
        if change == "cancel":
            job.cancel()
            release_planning.set()
            with pytest.raises(asyncio.CancelledError):
                await job
            assert transcript.records == before
        elif change == "branch":
            transcript.branch(root)
            release_planning.set()
            with pytest.raises(ModelInputIntegrityError, match="changed"):
                await job
            assert transcript.records == before
        elif change == "commit":
            await transcript.append_agent_message(
                UserMessage(role="user", content="other", timestamp=4.0)
            )
            release_planning.set()
            with pytest.raises(ModelInputIntegrityError, match="changed"):
                await job
            assert len(transcript.records) == len(before) + 1
        else:
            release_planning.set()
            await job
            rebuilt = rebuild_model_input(transcript, committer.commits[0].snapshot_id)
            assert rebuilt.prepared_payload_hash == request.payload_hash
            assert rebuilt.logical_input == logical
        if change != "none":
            assert not committer.commits
            cache = model_input_v2_module._MODEL_INPUT_V2_INDEX_CACHES.get(transcript)
            assert cache is None or cache.sequence_plans == prior_plans

    asyncio.run(scenario())


def test_model_input_append_reuses_verified_prefix_value_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        messages = [{"role": "user", "content": str(index)} for index in range(50)]
        logical = dict(thaw_model_input_json(_context(transcript).logical_input))
        logical["messages"] = messages
        first = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=logical),
            runtime_references=_runtime_references(),
        )
        await first.commit_prepared_request(_prepared(payload={"messages": messages}))

        await transcript.append_agent_message(
            UserMessage(role="user", content="continue", timestamp=3.0)
        )
        next_messages = [*messages, {"role": "user", "content": "new"}]
        next_logical = dict(thaw_model_input_json(_context(transcript).logical_input))
        next_logical["messages"] = next_messages
        second = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript, logical_input=next_logical),
            runtime_references=_runtime_references(),
        )
        value_lookups = 0
        yield_checks = 0
        original_find = model_input_v2_module.ModelInputV2NodeIndex.find_value
        original_yield = model_input_v2_module.ModelInputV2Writer._yield_if_needed

        def find_value(index, value_hash):
            nonlocal value_lookups
            value_lookups += 1
            return original_find(index, value_hash)

        monkeypatch.setattr(
            model_input_v2_module.ModelInputV2NodeIndex,
            "find_value",
            find_value,
        )
        async def count_yield(writer):
            nonlocal yield_checks
            yield_checks += 1
            await original_yield(writer)

        monkeypatch.setattr(
            model_input_v2_module.ModelInputV2Writer,
            "_yield_if_needed",
            count_yield,
        )
        request = _prepared(payload={"messages": next_messages})
        await second.commit_prepared_request(request)

        assert value_lookups < 10, "append rechecked every verified old value"
        assert yield_checks < 20, f"append checked {yield_checks} verified old values"
        rebuilt = rebuild_model_input(transcript, second.commits[-1].snapshot_id)
        assert rebuilt.logical_input == next_logical
        assert rebuilt.prepared_payload == request.payload_for_transport()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["none", "cancel", "branch", "commit", "invalid"])
@pytest.mark.parametrize("warm", [False, True])
def test_model_input_index_preparation_yields_without_publishing_partial_state(
    monkeypatch, change, warm
):
    from types import SimpleNamespace

    async def scenario():
        transcript = await _memory_transcript()
        root = transcript.leaf_id
        if warm:
            first = ModelInputTranscriptCommitter(
                transcript=transcript,
                context=_context(transcript),
                runtime_references=_runtime_references(),
            )
            await first.commit_prepared_request(_prepared())
            transcript.branch(root)
        previous_cache = model_input_v2_module._MODEL_INPUT_V2_INDEX_CACHES.get(
            transcript
        )
        nodes = tuple(create_model_input_json_value({"value": i}) for i in range(100))
        await transcript.append_model_input_node_bundles(
            (ModelInputNodeBundle(nodes),),
            max_encoded_record_bytes=MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
            expected_revision=transcript.revision,
            expected_leaf_id=transcript.leaf_id,
        )
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        before = transcript.records
        clock = [0.0]
        indexed = []
        original = model_input_v2_module.ModelInputV2NodeIndex._add_indexed_node

        def add(index, node, **kwargs):
            clock[0] += 0.005
            indexed.append(node)
            if change == "invalid" and len(indexed) == 100:
                raise ModelInputIntegrityError("invalid final indexed node")
            return original(index, node, **kwargs)

        monkeypatch.setattr(
            model_input_v2_module.ModelInputV2NodeIndex, "_add_indexed_node", add
        )
        monkeypatch.setattr(
            model_input_v2_module,
            "time",
            SimpleNamespace(monotonic=lambda: clock[0]),
            raising=False,
        )
        job = asyncio.create_task(committer.commit_prepared_request(_prepared()))
        while not indexed and not job.done():
            await asyncio.sleep(0)
        assert not job.done(), (
            "cold Model Input index blocked input until it was complete"
        )
        assert 0 < len(indexed) < 100
        assert (
            model_input_v2_module._MODEL_INPUT_V2_INDEX_CACHES.get(transcript)
            is previous_cache
        )
        assert transcript.records == before
        if change == "cancel":
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
        elif change == "branch":
            transcript.branch(root)
            with pytest.raises(ModelInputIntegrityError, match="changed"):
                await job
        elif change == "commit":
            await transcript.append_agent_message(
                UserMessage(role="user", content="other", timestamp=2.0)
            )
            with pytest.raises(ModelInputIntegrityError, match="changed"):
                await job
        elif change == "invalid":
            with pytest.raises(ModelInputIntegrityError, match="invalid final"):
                await job
        else:
            await job
            rebuilt = rebuild_model_input(transcript, committer.commits[0].snapshot_id)
            assert rebuilt.prepared_payload_hash == _prepared().payload_hash
            assert rebuilt.logical_input == thaw_model_input_json(
                _context(transcript).logical_input
            )
        if change != "none":
            assert not committer.commits
            assert (
                model_input_v2_module._MODEL_INPUT_V2_INDEX_CACHES.get(transcript)
                is previous_cache
            )
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]

    asyncio.run(scenario())


def test_model_input_v2_fast_node_hash_matches_general_canonical_hash() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())

        nodes = tuple(
            node
            for record in transcript.records
            if isinstance(record.payload, ModelInputNodeBundle)
            for node in record.payload.nodes
        )
        assert nodes
        for node in nodes:
            assert hash_model_input_node(node) == hash_model_input_json(
                model_input_node_hash_basis(node),
                name="Model Input v2 typed node",
            )

    asyncio.run(scenario())


def test_model_input_v2_fast_sequence_and_mapping_hashes_remain_canonical() -> None:
    previous = "sha256:" + ("a" * 64)
    item = "sha256:" + ("b" * 64)
    assert model_input_v2_module.extend_model_input_sequence_hash(
        previous,
        item,
    ) == hash_model_input_json(
        {
            "domain": "harness.model-input.sequence-link.v2",
            "previous": previous,
            "item": item,
        },
        name="Model Input sequence link",
    )

    mapping = {
        "messages": [{"role": "user", "content": "你好"}],
        "model": "model-input-model",
    }
    canonical_fields = {
        name: canonical_model_input_json(value, name=f"field {name}")
        for name, value in mapping.items()
    }
    assert model_input_v2_module._hash_canonical_mapping_fields(
        canonical_fields
    ) == hash_model_input_json(mapping, name="Model Input mapping")


def test_model_input_v2_node_index_cache_rebuilds_after_branch_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0
    events: list[dict[str, object]] = []
    original_init = model_input_v2_module.ModelInputV2NodeIndex.__init__

    class _TimingLog:
        def debug_event(self, scope: str, name: str, **data: object) -> None:
            events.append(data)

    def counting_init(self, records) -> None:
        nonlocal builds
        builds += 1
        original_init(self, records)

    monkeypatch.setattr(
        model_input_v2_module.ModelInputV2NodeIndex,
        "__init__",
        counting_init,
    )
    monkeypatch.setattr(
        model_input_module,
        "_MODEL_INPUT_PERFORMANCE_LOG",
        _TimingLog(),
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        branch_root = transcript.leaf_id
        assert branch_root is not None
        first = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await first.commit_prepared_request(_prepared(invocation_id="left"))

        transcript.branch(branch_root)
        await transcript.append_agent_message(
            UserMessage(role="user", content="right", timestamp=2.0)
        )
        second = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await second.commit_prepared_request(_prepared(invocation_id="right"))

        assert builds == 2
        assert len(events) == 2
        assert events[-1]["materialize_counts"] == {
            "sequence_count": 4,
            "sequence_item_count": 4,
            "reused_prefix_item_count": 0,
            "planned_item_count": 4,
        }

    asyncio.run(scenario())


def test_model_input_v2_node_index_cache_rebuilds_after_compatibility_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0
    original_init = model_input_v2_module.ModelInputV2NodeIndex.__init__

    def counting_init(self, records) -> None:
        nonlocal builds
        builds += 1
        original_init(self, records)

    monkeypatch.setattr(
        model_input_v2_module.ModelInputV2NodeIndex,
        "__init__",
        counting_init,
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        first = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await first.commit_prepared_request(_prepared(invocation_id="before-change"))

        monkeypatch.setattr(
            model_input_v2_module,
            "MODEL_INPUT_V2_INDEX_COMPATIBILITY_TOKEN",
            "test-incompatible-node-index",
        )
        second = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await second.commit_prepared_request(_prepared(invocation_id="after-change"))

        assert builds == 2

    asyncio.run(scenario())


def test_model_input_performance_reporting_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenTimingLog:
        def debug_event(self, scope: str, name: str, **data: object) -> None:
            raise OSError("diagnostic sink failed")

    monkeypatch.setattr(
        model_input_module,
        "_MODEL_INPUT_PERFORMANCE_LOG",
        _BrokenTimingLog(),
    )

    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )

        await committer.commit_prepared_request(_prepared())

        assert len(committer.commits) == 1

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


def test_attempt_usage_committer_is_atomic_idempotent_and_terminal() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        snapshot_id = committer.commits[0].snapshot_id
        partial = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=snapshot_id,
            input=10,
            cache_read=0,
            cache_write=0,
        )

        assert await committer.record_model_call_attempt_usage(partial) is True
        revision = transcript.revision
        assert await committer.record_model_call_attempt_usage(partial) is False
        assert transcript.revision == revision
        terminal = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=snapshot_id,
            output=2,
            terminal=True,
        )
        assert await committer.record_model_call_attempt_usage(terminal) is True
        assert project_model_call_usage(transcript.active_path()).complete is True
        assert (
            project_model_call_usage(transcript.active_path()).usage.total_tokens == 12
        )
        assert [
            record.payload
            for record in transcript.records
            if record.kind == MODEL_CALL_ATTEMPT_USAGE_KIND
        ] == [partial, terminal]

        with pytest.raises(ModelInputIntegrityError, match="terminal observation"):
            await committer.record_model_call_attempt_usage(
                replace(terminal, output=3, terminal=False)
            )

        await committer.record_model_call_outcome(
            PreparedModelCallOutcome(
                invocation_id="invocation-1",
                disposition="completed",
                stop_reason="stop",
                usage=Usage(10, 2, 0, 0, 12, None),
            )
        )
        with pytest.raises(ModelInputIntegrityError, match="terminal outcome"):
            await committer.record_model_call_attempt_usage(partial)

    asyncio.run(scenario())


def test_attempt_usage_committer_rejects_identity_and_revision_drift() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        fact = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=committer.commits[0].snapshot_id,
            input=1,
        )

        with pytest.raises(ModelInputIntegrityError, match="invocation identity"):
            await committer.record_model_call_attempt_usage(
                replace(fact, invocation_id="other-invocation")
            )
        with pytest.raises(ModelInputIntegrityError, match="committed attempt"):
            await committer.record_model_call_attempt_usage(replace(fact, attempt=2))
        with pytest.raises(ModelInputIntegrityError, match="committed attempt"):
            await committer.record_model_call_attempt_usage(
                replace(fact, model_input_snapshot_id="other-snapshot")
            )

        await transcript.append_agent_message(
            UserMessage(role="user", content=[], timestamp=1.0)
        )
        with pytest.raises(ModelInputIntegrityError, match="changed outside"):
            await committer.record_model_call_attempt_usage(fact)

    asyncio.run(scenario())


def test_terminal_usage_and_outcome_commit_as_one_ordered_batch() -> None:
    async def scenario() -> None:
        backend = _CountingModelInputStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        before_batches = len(backend.batch_sizes)
        before_appends = backend.append_calls
        usage = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=committer.commits[-1].snapshot_id,
            input=10,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=12,
            terminal=True,
        )
        await committer.record_terminal_model_call(
            PreparedModelCallOutcome(
                invocation_id="invocation-1",
                disposition="completed",
                stop_reason="stop",
                usage=Usage(10, 2, 0, 0, 12, None),
            ),
            usage=usage,
        )
        assert backend.batch_sizes[before_batches:] == [2]
        assert backend.append_calls == before_appends
        assert [record.kind for record in transcript.records[-2:]] == [
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            MODEL_CALL_OUTCOME_KIND,
        ]
        assert project_model_call_usage(transcript.active_path()).complete

    asyncio.run(scenario())


def test_terminal_observation_batch_recovers_unknown_receipt_once() -> None:
    class UnknownOnceStore(_CountingModelInputStore):
        def __init__(self) -> None:
            super().__init__()
            self.fail_next_batch = False

        async def append_batch(self, key, records, *, expected_revision, operation_ids):
            result = await super().append_batch(
                key,
                records,
                expected_revision=expected_revision,
                operation_ids=operation_ids,
            )
            if self.fail_next_batch:
                self.fail_next_batch = False
                raise StoreCommitOutcomeUnknown("lost terminal batch receipt")
            return result

    async def scenario() -> None:
        backend = UnknownOnceStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        usage = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=committer.commits[-1].snapshot_id,
            input=10,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=12,
            terminal=True,
        )
        before_batches = len(backend.batch_sizes)
        backend.fail_next_batch = True
        await committer.record_terminal_model_call(
            PreparedModelCallOutcome(
                invocation_id="invocation-1",
                disposition="completed",
                stop_reason="stop",
                usage=Usage(10, 2, 0, 0, 12, None),
            ),
            usage=usage,
        )
        assert backend.batch_sizes[before_batches:] == [2, 2]
        assert [record.kind for record in transcript.records[-2:]] == [
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            MODEL_CALL_OUTCOME_KIND,
        ]
        assert sum(
            record.kind == MODEL_CALL_ATTEMPT_USAGE_KIND
            for record in transcript.records
        ) == 1
        assert sum(
            record.kind == MODEL_CALL_OUTCOME_KIND for record in transcript.records
        ) == 1
        assert project_model_call_usage(transcript.active_path()).complete

    asyncio.run(scenario())


def test_terminal_observation_batch_settles_before_cancellation() -> None:
    async def scenario() -> None:
        backend = _BlockingModelInputStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        usage = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=committer.commits[-1].snapshot_id,
            input=10,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=12,
            terminal=True,
        )
        backend.block_appends = True
        task = asyncio.create_task(
            committer.record_terminal_model_call(
                PreparedModelCallOutcome(
                    invocation_id="invocation-1",
                    disposition="completed",
                    stop_reason="stop",
                    usage=Usage(10, 2, 0, 0, 12, None),
                ),
                usage=usage,
            )
        )
        await backend.committed.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        backend.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert [record.kind for record in transcript.records[-2:]] == [
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            MODEL_CALL_OUTCOME_KIND,
        ]
        assert project_model_call_usage(transcript.active_path()).complete

    asyncio.run(scenario())


def test_terminal_observation_batch_uses_committed_lineage_without_path_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        usage = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=committer.commits[-1].snapshot_id,
            input=10,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=12,
            terminal=True,
        )

        def unexpected_path_scan():
            raise AssertionError("terminal commit rescanned the active path")

        with monkeypatch.context() as patch:
            patch.setattr(transcript, "active_path", unexpected_path_scan)
            await committer.record_terminal_model_call(
                PreparedModelCallOutcome(
                    invocation_id="invocation-1",
                    disposition="completed",
                    stop_reason="stop",
                    usage=Usage(10, 2, 0, 0, 12, None),
                ),
                usage=usage,
            )
        assert project_model_call_usage(transcript.active_path()).complete

    asyncio.run(scenario())


def test_terminal_observation_batch_rejects_prior_outcome_on_other_branch() -> None:
    async def scenario() -> None:
        backend = _CountingModelInputStore()
        transcript = await _memory_transcript(backend)
        source_leaf_id = transcript.leaf_id
        assert source_leaf_id is not None
        first = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await first.commit_prepared_request(_prepared())
        outcome = PreparedModelCallOutcome(
            invocation_id="invocation-1",
            disposition="completed",
            stop_reason="stop",
            usage=Usage(10, 2, 0, 0, 12, None),
        )
        await first.record_model_call_outcome(outcome)

        reopened = await AgentTranscriptUnitOfWork.load(
            backend,
            ConversationKey("test", "model-input-conversation"),
            leaf_id=source_leaf_id,
        )
        second = ModelInputTranscriptCommitter(
            transcript=reopened,
            context=_context(reopened),
            runtime_references=_runtime_references(),
        )
        await second.commit_prepared_request(_prepared())
        usage = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=second.commits[-1].snapshot_id,
            input=10,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=12,
            terminal=True,
        )
        with pytest.raises(ModelInputIntegrityError, match="already has"):
            await second.record_terminal_model_call(outcome, usage=usage)
        assert not any(
            record.kind == MODEL_CALL_ATTEMPT_USAGE_KIND
            and record.payload.model_input_snapshot_id == usage.model_input_snapshot_id
            for record in reopened.records
        )

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
                    reversed([commit.snapshot_id for commit in committer.commits])
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
        await committer.commit_prepared_request(_prepared(invocation_id="file-v2"))
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


def test_model_input_materializes_v2_graph_and_snapshot_in_one_store_batch() -> None:
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
        assert backend.batch_sizes == [component_count + 1]
        assert backend.append_calls == append_calls_before
        first_batch_sizes = list(backend.batch_sizes)

        await committer.commit_prepared_request(
            _prepared(invocation_id="invocation-1", attempt=2)
        )

        assert backend.batch_sizes == [*first_batch_sizes, 1]
        assert backend.append_calls == append_calls_before
        assert verify_model_input(transcript, committer.commits[-1].snapshot_id).verified

    asyncio.run(scenario())


def test_failed_v2_staging_leaves_no_graph_facts_or_cached_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        backend = _CountingModelInputStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        before = transcript.records
        original = transcript.stage_model_input_node_bundles
        stages = 0

        def fail_after_values(*args, **kwargs):
            nonlocal stages
            stages += 1
            if stages == 2:
                raise ModelInputIntegrityError("staging failed")
            return original(*args, **kwargs)

        monkeypatch.setattr(
            transcript, "stage_model_input_node_bundles", fail_after_values
        )
        with pytest.raises(ModelInputIntegrityError, match="staging failed"):
            await committer.commit_prepared_request(_prepared())
        assert stages == 2
        assert transcript.records == before
        assert backend.batch_sizes == []
        cached = model_input_v2_module._MODEL_INPUT_V2_INDEX_CACHES[transcript]
        assert cached.records == transcript.active_path()
        assert cached.index.find_value(
            model_input_v2_module.ModelInputV2Writer._value_plan(
                {"role": "user", "content": "hello"}
            ).value_hash
        ) is None

        monkeypatch.setattr(transcript, "stage_model_input_node_bundles", original)
        await committer.commit_prepared_request(_prepared())
        assert verify_model_input(transcript, committer.commits[-1].snapshot_id).verified

    asyncio.run(scenario())


def test_v2_batch_recovers_unknown_store_receipt_without_duplicate_facts() -> None:
    class UnknownOnceStore(_CountingModelInputStore):
        def __init__(self) -> None:
            super().__init__()
            self.unknown_once = True

        async def append_batch(self, key, records, *, expected_revision, operation_ids):
            result = await super().append_batch(
                key,
                records,
                expected_revision=expected_revision,
                operation_ids=operation_ids,
            )
            if self.unknown_once:
                self.unknown_once = False
                raise StoreCommitOutcomeUnknown("lost batch receipt")
            return result

    async def scenario() -> None:
        backend = UnknownOnceStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        assert len(backend.batch_sizes) == 2
        assert backend.batch_sizes[0] == backend.batch_sizes[1]
        assert sum(
            record.kind == MODEL_INPUT_PREPARED_KIND
            for record in transcript.records
        ) == 1
        assert verify_model_input(transcript, committer.commits[-1].snapshot_id).verified

    asyncio.run(scenario())


def test_branch_during_v2_staging_rejects_the_entire_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        backend = _CountingModelInputStore()
        transcript = await _memory_transcript(backend)
        root = transcript.leaf_id
        await transcript.append_agent_message(
            UserMessage(role="user", content="second", timestamp=2.0)
        )
        selected = transcript.leaf_id
        before = transcript.records
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        original = transcript.stage_model_input_node_bundles
        changed = False

        def branch_after_first_stage(*args, **kwargs):
            nonlocal changed
            records = original(*args, **kwargs)
            if not changed:
                changed = True
                transcript.branch(root)
            return records

        monkeypatch.setattr(
            transcript, "stage_model_input_node_bundles", branch_after_first_stage
        )
        with pytest.raises(ModelInputIntegrityError, match="changed"):
            await committer.commit_prepared_request(_prepared())
        assert changed
        assert transcript.records == before
        assert backend.batch_sizes == []
        transcript.branch(selected)

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


def test_model_input_v2_reuses_the_previous_message_prefix_and_appends_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []

    class _TimingLog:
        def debug_event(self, scope: str, name: str, **data: object) -> None:
            events.append(data)

    monkeypatch.setattr(
        model_input_module,
        "_MODEL_INPUT_PERFORMANCE_LOG",
        _TimingLog(),
    )

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
        assert len(events) == 2
        assert events[-1]["materialize_counts"] == {
            "sequence_count": 4,
            "sequence_item_count": 4,
            "reused_prefix_item_count": 3,
            "planned_item_count": 1,
        }
        assert (
            rebuild_model_input(
                transcript,
                second_committer.commits[-1].snapshot_id,
            ).logical_input
            == second_logical
        )

    asyncio.run(scenario())


def test_v2_writer_reuses_sealed_prepared_message_prefix_without_reencoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        messages = [{"role": "user", "content": str(index)} for index in range(50)]
        payload = {"messages": messages, "tools": [], "model": "model-input-model"}
        first = _prepared(payload=payload)
        await committer.commit_prepared_request(first)

        model = _model(api="model-input-test")
        request = ProviderRequest(
            model=model,
            context=NormalizedContext(system_prompt=None),
            options=None,
            base_url=model.base_url,
            invocation_id=first.invocation_id,
            attempt=2,
        )
        second = PreparedModelRequest.from_provider_request(
            request,
            payload={**payload, "messages": [*messages, {"role": "user", "content": "tail"}]},
            model_visible_headers={"anthropic-beta": "feature-1"},
            reuse_from=first,
        )
        assert second.payload["messages"][0] is first.payload["messages"][0]
        count = 0
        original = model_input_v2_module.canonical_model_input_json

        def canonical(value, *, name):
            nonlocal count
            if name == "Model Input v2 cached sequence item":
                count += 1
            return original(value, name=name)

        monkeypatch.setattr(model_input_v2_module, "canonical_model_input_json", canonical)
        await committer.commit_prepared_request(second)
        assert count < 10
        assert verify_model_input(transcript, committer.commits[-1].snapshot_id).verified
        changed = [{"role": "user", "content": "changed"}, *messages[1:]]
        await committer.commit_prepared_request(
            _prepared(
                attempt=3,
                payload={**payload, "messages": changed},
            )
        )
        rebuilt = rebuild_model_input(transcript, committer.commits[-1].snapshot_id)
        assert rebuilt.prepared_payload["messages"][0] == changed[0]

    asyncio.run(scenario())


def test_logical_context_freeze_reuses_only_an_exact_immutable_prefix() -> None:
    messages = [
        {"role": "user", "content": ["same", {"value": index}]}
        for index in range(50)
    ]
    logical = {
        "system_prompt": None,
        "messages": messages,
        "tools": [],
        "request_options": {},
    }
    first = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="first",
        source_revision=1,
        logical_input=logical,
    )
    next_messages = [*messages, {"role": "user", "content": "tail"}]
    second = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="second",
        source_revision=2,
        logical_input={**logical, "messages": next_messages},
        reuse_from=first,
    )
    assert second.logical_input["messages"][0] is first.logical_input["messages"][0]
    messages[0]["content"][1]["value"] = "changed"
    third = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="third",
        source_revision=3,
        logical_input={**logical, "messages": next_messages},
        reuse_from=second,
    )
    assert third.logical_input["messages"][0] is not second.logical_input["messages"][0]
    assert third.logical_input["messages"][1] == second.logical_input["messages"][1]
    assert third.logical_input["messages"][0]["content"][1]["value"] == "changed"
    zero = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="zero",
        source_revision=4,
        logical_input={**logical, "messages": [{"content": 0.0}]},
    )
    negative_zero = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="negative-zero",
        source_revision=5,
        logical_input={**logical, "messages": [{"content": -0.0}]},
        reuse_from=zero,
    )
    assert negative_zero.logical_input["messages"][0] is not zero.logical_input[
        "messages"
    ][0]
    assert canonical_model_input_json(
        negative_zero.logical_input["messages"][0], name="negative zero"
    ) != canonical_model_input_json(zero.logical_input["messages"][0], name="zero")


def test_logical_canonical_reuses_only_verified_message_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {"role": "user", "content": ["same", {"value": index}]}
        for index in range(80)
    ]
    logical = {
        "system_prompt": "system",
        "messages": messages,
        "tools": [{"name": "tool"}],
        "request_options": {},
        "resource_evidence": {"enabled": True},
    }
    first = ModelInputCommitContext(
        purpose="main_turn", source_leaf_id="first", source_revision=1,
        logical_input=logical,
    )
    first._canonical_logical_input_json(thaw_model_input_json(first.logical_input))
    second = ModelInputCommitContext(
        purpose="main_turn", source_leaf_id="second", source_revision=2,
        logical_input={**logical, "messages": [*messages, {"role": "tool", "content": "done"}]},
        reuse_from=first,
    )
    exact = thaw_model_input_json(second.logical_input)
    expected = canonical_model_input_json(exact, name="logical Model Input")
    original = model_input_module.canonical_model_input_json
    historical_calls = 0

    def counted(value: object, *, name: str) -> str:
        nonlocal historical_calls
        if name.startswith("logical Model Input.messages["):
            historical_calls += 1
        return original(value, name=name)

    monkeypatch.setattr(model_input_module, "canonical_model_input_json", counted)
    assert second._canonical_logical_input_json(exact) == expected
    assert historical_calls <= 2

    messages[10]["content"][1]["value"] = -0.0
    changed = ModelInputCommitContext(
        purpose="main_turn", source_leaf_id="changed", source_revision=3,
        logical_input={**logical, "messages": [*messages, {"role": "tool", "content": "done"}]},
        reuse_from=second,
    )
    changed_value = thaw_model_input_json(changed.logical_input)
    assert changed._canonical_logical_input_json(changed_value) == original(
        changed_value, name="logical Model Input"
    )
    assert changed.logical_input["messages"][10] is not second.logical_input[
        "messages"
    ][10]


def test_owned_logical_canonical_hash_reuses_exact_append_only_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    messages = [{"role": "user", "content": '历史\\"文' * 4000}]
    logical = {
        "alpha_component": {"messages": [{"text": "嵌套"}]},
        "system_prompt": "系统",
        "messages": messages,
        "tools": [{"name": "工具"}],
        "request_options": {},
    }
    previous = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="one",
        source_revision=1,
        logical_input=logical,
    )
    previous._canonical_owned_logical_input(
        model_input_module._logical_input_for_materialization(previous.logical_input)
    )
    original = model_input_module.canonical_model_input_json
    for index, suffix in enumerate(
        (
            {"role": "assistant", "content": '回答\\"一'},
            {"role": "toolResult", "content": "输出二"},
            {"role": "user", "content": {"type": "image", "data": "图"}},
        ),
        start=2,
    ):
        messages = [*messages, suffix]
        current = ModelInputCommitContext(
            purpose="main_turn",
            source_leaf_id=str(index),
            source_revision=index,
            logical_input={**logical, "messages": messages},
            reuse_from=previous,
        )
        historical_calls = 0

        def counted(value: object, *, name: str) -> str:
            nonlocal historical_calls
            if name.startswith("logical Model Input.messages["):
                historical_calls += 1
            return original(value, name=name)

        with monkeypatch.context() as patcher:
            patcher.setattr(model_input_module, "canonical_model_input_json", counted)
            canonical, digest = current._canonical_owned_logical_input(
                model_input_module._logical_input_for_materialization(
                    current.logical_input
                )
            )
        expected = original(
            thaw_model_input_json(current.logical_input), name="logical Model Input"
        )
        assert canonical is None
        assert (
            digest == "sha256:" + hashlib.sha256(expected.encode("utf-8")).hexdigest()
        )
        assert historical_calls <= 1
        for marker in model_input_module._LOGICAL_BINARY_MARKERS:
            assert (marker in expected) == (marker in current._owned_binary_markers)
        previous = current

    changed = ModelInputCommitContext(
        purpose="main_turn",
        source_leaf_id="changed",
        source_revision=5,
        logical_input={**logical, "messages": messages, "system_prompt": "新系统"},
        reuse_from=previous,
    )
    canonical, digest = changed._canonical_owned_logical_input(
        model_input_module._logical_input_for_materialization(changed.logical_input)
    )
    expected = original(
        thaw_model_input_json(changed.logical_input), name="logical Model Input"
    )
    assert canonical == expected
    assert digest == "sha256:" + hashlib.sha256(expected.encode("utf-8")).hexdigest()

    prefix_digest = previous._owned_prefix_digest
    assert prefix_digest is not None
    prefix_digest.update(b"corrupt")
    appended = [*messages, {"role": "user", "content": "after cache change"}]
    fallback = ModelInputCommitContext(
        purpose="main_turn", source_leaf_id="fallback", source_revision=6,
        logical_input={**logical, "messages": appended}, reuse_from=previous,
    )
    fallback_canonical, fallback_digest = fallback._canonical_owned_logical_input(
        model_input_module._logical_input_for_materialization(fallback.logical_input)
    )
    fallback_expected = original(
        thaw_model_input_json(fallback.logical_input), name="logical Model Input"
    )
    assert fallback_canonical == fallback_expected
    assert fallback_digest == "sha256:" + hashlib.sha256(
        fallback_expected.encode("utf-8")
    ).hexdigest()


def test_session_append_reuses_verified_logical_prefix_at_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        session = AgentTranscriptSession(transcript=transcript)
        messages = [{"role": "user", "content": str(index)} for index in range(50)]
        logical = {
            "system_prompt": None,
            "messages": messages,
            "tools": [],
            "request_options": {},
        }
        first = session.create_model_input_committer(
            purpose="main_turn",
            logical_input=logical,
            runtime_references=_runtime_references(),
        )
        await first.commit_prepared_request(_prepared())
        await transcript.append_agent_message(
            UserMessage(role="user", content="tail", timestamp=2.0)
        )
        second = session.create_model_input_committer(
            purpose="main_turn",
            logical_input={
                **logical,
                "messages": [*messages, {"role": "user", "content": "tail"}],
            },
            runtime_references=_runtime_references(),
        )
        assert (
            second._context.logical_input["messages"][0]
            is first._context.logical_input["messages"][0]
        )
        count = 0
        original = model_input_v2_module.canonical_model_input_json

        def canonical(value, *, name):
            nonlocal count
            if name == "Model Input v2 cached sequence item":
                count += 1
            return original(value, name=name)

        monkeypatch.setattr(model_input_v2_module, "canonical_model_input_json", canonical)
        await second.commit_prepared_request(_prepared(invocation_id="next"))
        assert count < 10
        assert verify_model_input(transcript, second.commits[-1].snapshot_id).verified

    asyncio.run(scenario())


def test_model_input_v2_sequence_prefix_comparison_preserves_json_types() -> None:
    assert not model_input_v2_module._same_model_input_json(
        {"content": 1},
        {"content": True},
    )
    assert not model_input_v2_module._same_model_input_json(
        {"content": 1},
        {"content": 1.0},
    )
    assert not model_input_v2_module._same_model_input_json(
        {"content": -0.0},
        {"content": 0.0},
    )
    assert model_input_v2_module._same_model_input_json(
        {"content": ["same", {"nested": None}]},
        {"content": ["same", {"nested": None}]},
    )


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


def test_fork_derivation_keeps_attempt_usage_for_referenced_snapshot() -> None:
    async def scenario() -> None:
        transcript = await _memory_transcript()
        branch_root = transcript.leaf_id
        assert branch_root is not None
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=replace(_context(transcript), purpose="branch_summary"),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        snapshot_id = committer.commits[0].snapshot_id
        fact = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=snapshot_id,
            input=10,
            output=0,
            cache_read=0,
            cache_write=0,
            terminal=True,
        )
        await committer.record_model_call_attempt_usage(fact)

        transcript.branch(branch_root)
        await transcript.append_agent_message(
            UserMessage(role="user", content="sibling", timestamp=2.0)
        )
        summary = await transcript.append_branch_summary(
            BranchContextSummary(
                from_record_id=branch_root,
                summary="derived summary",
                model_input_snapshot_ids=(snapshot_id,),
            )
        )

        fork_records = transcript.records_for_fork(summary.record.record_id)

        assert any(record.payload == fact for record in fork_records)
        assert project_model_call_usage(fork_records).usage.total_tokens == 10
        assert project_model_call_usage(fork_records).complete is True

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

        snapshots = [
            record.payload
            for record in transcript.records
            if record.kind == MODEL_INPUT_PREPARED_KIND
        ]
        assert len(snapshots) == 1
        assert any(
            record.kind == MODEL_INPUT_COMPONENT_KIND for record in transcript.records
        )
        assert verify_model_input(transcript, snapshots[0].snapshot_id).verified

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


def test_attempt_usage_commit_propagates_cancellation_after_safe_append() -> None:
    async def scenario() -> None:
        backend = _BlockingModelInputStore()
        transcript = await _memory_transcript(backend)
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        await committer.commit_prepared_request(_prepared())
        fact = ModelCallAttemptUsage(
            invocation_id="invocation-1",
            attempt=1,
            model_input_snapshot_id=committer.commits[0].snapshot_id,
            input=10,
            terminal=True,
        )
        backend.block_appends = True

        task = asyncio.create_task(committer.record_model_call_attempt_usage(fact))
        await backend.committed.wait()
        task.cancel()
        await asyncio.sleep(0)

        assert task.done() is False
        backend.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert [
            record.payload
            for record in transcript.records
            if record.kind == MODEL_CALL_ATTEMPT_USAGE_KIND
        ] == [fact]

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


def test_forwarded_cancel_runs_before_the_next_logical_projection(monkeypatch):
    async def scenario():
        transcript = await _memory_transcript()
        before = transcript.records
        committer = ModelInputTranscriptCommitter(
            transcript=transcript,
            context=_context(transcript),
            runtime_references=_runtime_references(),
        )
        original_validate = model_input_module._validate_prepared_request
        original_thaw = model_input_module.thaw_model_input_json
        validated = False
        logical_projections = []

        def validate(request):
            nonlocal validated
            value = original_validate(request)
            validated = True
            loop.call_soon(lambda: loop.call_soon(job.cancel))
            return value

        def thaw(value):
            if validated:
                logical_projections.append(value is not None)
            return original_thaw(value)

        monkeypatch.setattr(model_input_module, "_validate_prepared_request", validate)
        monkeypatch.setattr(model_input_module, "thaw_model_input_json", thaw)
        loop = asyncio.get_running_loop()
        job = asyncio.create_task(committer.commit_prepared_request(_prepared()))
        with pytest.raises(asyncio.CancelledError):
            await job
        assert not logical_projections, (
            "queued cancel forwarding lost priority to another full request clone"
        )
        assert transcript.records == before
        assert not committer.commits

    asyncio.run(scenario())
