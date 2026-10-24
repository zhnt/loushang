from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from loushang.agent import Agent, ModelCallPreparation
from loushang.ai import Context, stream
from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.context import normalize_context, normalize_context_result
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model, OpenAICompletionsConfig
from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.prepared_request import (
    PreparedModelCallOutcome,
    PreparedModelRequest,
    PreparedRequestLimits,
)
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.provider.protocol import ProviderRequest
from loushang.ai.types import (
    AssistantMessage,
    Message,
    TextPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.coding.compaction.profiles import (
    CODING_BRANCH_SUMMARY_PROFILE,
    CODING_COMPACTION_SUMMARY_PROFILE,
    CODING_TURN_PREFIX_SUMMARY_PROFILE,
)
from loushang.foundation.json import JSONValue
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    MODEL_INPUT_PREPARATION_REQUIREMENT,
    CapabilityBundleProvider,
    CapabilityGraphPlanRequest,
    RegistrationInventoryEntry,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphProjector,
    RuntimeCapabilityGraphRuntime,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.effective_runtime import (
    runtime_profile_fingerprint,
)
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.runtime import RuntimeProfileResolver
from loushang.harness.session import AgentSessionInspector
from loushang.harness.session import model_call as model_call_module
from loushang.harness.session.model_call import (
    ModelInputTranscriptPort,
    SessionModelCallCapabilityConsumer,
    SessionModelCallRuntime,
    build_session_model_call_capability_binding,
)
from loushang.harness.session.request_evidence import (
    RESOURCE_EVIDENCE_COMPONENT,
    RESOURCE_EVIDENCE_METADATA_KEY,
    RESOURCE_EVIDENCE_SCHEMA_ID,
    PreparedResourceEvidence,
    RequestEvidenceIntegrityError,
    SessionRequestEvidenceRuntime,
)
from loushang.harness.session.turn_performance import TurnStartPerformanceRuntime
from loushang.harness.transcript import (
    CONTEXT_BRANCH_SUMMARY_KIND,
    MODEL_CALL_ATTEMPT_USAGE_KIND,
    MODEL_CALL_OUTCOME_KIND,
    AgentTranscriptRecordFactory,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    BranchContextSummary,
    CompactionPreparation,
    ModelCallAttemptUsage,
    ModelCallOutcome,
    ModelInputIntegrityError,
    execute_branch_summary,
    execute_transcript_compaction,
)
from loushang.harness.transcript.summarization import SummaryCapacityPlanError


def _model(*, api: str, context_window: int = 8_192) -> Model:
    return Model(
        id="model-call-test",
        name="Model Call Test",
        provider="test-provider",
        api=api,
        endpoint="test-endpoint",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(
            input=("text",),
            output=("text",),
            context_window=context_window,
            stream=True,
        ),
    )


def _skill_evidence_payload() -> dict[str, JSONValue]:
    digest = "a" * 64
    return {
        "activationPolicyFingerprint": "b" * 64,
        "candidateFingerprint": "c" * 64,
        "catalogGeneration": 3,
        "catalogSnapshotFingerprint": "d" * 64,
        "expectedContentDigest": digest,
        "expectedContentLength": 12,
        "mediaType": "text/markdown",
        "observedContentDigest": digest,
        "observedContentLength": 12,
        "resourceIdentity": {
            "publicId": "review",
            "resourceKind": "skill",
            "schemaId": "loushang.skill",
            "schemaVersion": 1,
        },
        "schemaId": "loushang.skill",
        "schemaVersion": 1,
        "sourceGeneration": {
            "generation": "generation-3",
            "producer": {
                "bindingFingerprint": "f" * 64,
                "componentAdmissionFingerprint": "1" * 64,
                "componentCandidateFingerprint": "2" * 64,
                "componentContributionId": "project-skill-component",
                "packageContentDigest": "3" * 64,
                "pluginInstanceRevisionRef": "project-revision-3",
                "type": "resource_component",
            },
            "productId": "coding",
            "sourceId": "project-skills",
            "sourcePolicyFingerprint": "e" * 64,
        },
    }


async def _transcript_session(
    *,
    message_metadata: Mapping[str, JSONValue] | None = None,
    backend: MemoryConversationStore | None = None,
) -> AgentTranscriptSession:
    transcript = await AgentTranscriptUnitOfWork.create(
        backend or MemoryConversationStore(record_id=lambda record: record.record_id),
        ConversationKey("test", "session-model-call"),
        ConversationHeader(
            conversation_id="session-model-call",
            version=1,
            created_at="2026-08-15T00:00:00Z",
        ),
    )
    session = AgentTranscriptSession(transcript=transcript)
    await session.append_message(
        UserMessage(role="user", content="hello", timestamp=1.0),
        metadata=message_metadata,
    )
    return session


class _ModelCallTestRoot:
    def __init__(
        self,
        session: AgentTranscriptSession,
        *,
        is_current: Callable[[], bool],
        registrations: tuple[RegistrationInventoryEntry, ...],
        turn_performance: TurnStartPerformanceRuntime | None = None,
        request_evidence_provider: (
            Callable[[ModelCallPreparation], Mapping[str, object] | None] | None
        ) = None,
        on_committed_evidence_free_input: Callable[[str], None] | None = None,
    ) -> None:
        self._profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        profile_snapshot = self._profile.snapshot()
        self.graph_runtime = RuntimeCapabilityGraphRuntime(
            product_id=profile_snapshot.product_id,
            runtime_id="session:model-call-test",
            profile_fingerprint=runtime_profile_fingerprint(profile_snapshot),
        )
        self.current_profile_fingerprint = self.graph_runtime.profile_fingerprint
        self._binder = RuntimeCapabilityGraphBinder()
        self._projector = RuntimeCapabilityGraphProjector(self.graph_runtime)
        self._lock = asyncio.Lock()
        self._consumer: SessionModelCallCapabilityConsumer | None = None
        self._binding = build_session_model_call_capability_binding(
            transcript=session,
            projector=self._projector,
            product_id=profile_snapshot.product_id,
            runtime_id="session:model-call-test",
            is_current=is_current,
            registration_entries_provider=lambda: registrations,
            profile_fingerprint_provider=lambda: self.current_profile_fingerprint,
            turn_performance=turn_performance,
            request_evidence_provider=request_evidence_provider,
            on_committed_evidence_free_input=on_committed_evidence_free_input,
        )
        self._plan = RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id=profile_snapshot.product_id,
                roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
                definitions=(MODEL_INPUT_CAPABILITY_DEFINITION,),
                providers=(self._binding.provider_binding.provider,),
            )
        )
        self._runtime = SessionModelCallRuntime(
            transcript=session,
            ensure_consumer=self._ensure_consumer,
            projector=self._projector,
            registration_entries_provider=lambda: registrations,
        )

    async def _ensure_consumer(self) -> SessionModelCallCapabilityConsumer:
        if self._consumer is not None:
            return self._consumer
        async with self._lock:
            if self._consumer is None:
                await self._binder.bind(
                    self.graph_runtime,
                    self._plan,
                    (self._binding.provider_binding,),
                )
                self._consumer = SessionModelCallCapabilityConsumer(
                    self.graph_runtime.capture(MODEL_INPUT_PREPARATION_REQUIREMENT)
                )
            return self._consumer

    async def prepare(self, preparation: ModelCallPreparation) -> CallOptions:
        return await self._runtime.prepare(preparation)

    def effective_view(self, *args: object, **kwargs: object):
        return self._runtime.effective_view(*args, **kwargs)

    def explain_capability(self, *args: object, **kwargs: object):
        return self._runtime.explain_capability(*args, **kwargs)

    def to_json(self, value: object):
        return self._runtime.to_json(value)  # type: ignore[arg-type]

    async def dispose(self) -> None:
        async with self._lock:
            self._consumer = None
            await self._binder.dispose(self.graph_runtime)


def _model_call_runtime(
    session: AgentTranscriptSession,
    *,
    is_current: Callable[[], bool],
    registrations: tuple[RegistrationInventoryEntry, ...] = (),
    turn_performance: TurnStartPerformanceRuntime | None = None,
    request_evidence_provider: (
        Callable[[ModelCallPreparation], Mapping[str, object] | None] | None
    ) = None,
    on_committed_evidence_free_input: Callable[[str], None] | None = None,
) -> _ModelCallTestRoot:
    return _ModelCallTestRoot(
        session,
        is_current=is_current,
        registrations=registrations,
        turn_performance=turn_performance,
        request_evidence_provider=request_evidence_provider,
        on_committed_evidence_free_input=on_committed_evidence_free_input,
    )


class _PerformanceLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, JSONValue]]] = []

    def debug_event(self, scope: str, name: str, **data: JSONValue) -> None:
        self.events.append((scope, name, data))


def test_model_call_binding_rejects_resources_without_session_provider() -> None:
    with pytest.raises(ValueError, match="without a Session Provider"):
        build_session_model_call_capability_binding(
            transcript=cast(ModelInputTranscriptPort, object()),
            projector=cast(RuntimeCapabilityGraphProjector, object()),
            product_id="research",
            runtime_id="session:model-call-test",
            is_current=lambda: True,
            registration_entries_provider=lambda: (),
            profile_fingerprint_provider=lambda: "profile",
            conversation_id="session-model-call",
            resources_provider=cast(CapabilityBundleProvider, object()),
        )


def test_model_call_binding_rejects_workspace_without_session_provider() -> None:
    with pytest.raises(ValueError, match="without a Session Provider"):
        build_session_model_call_capability_binding(
            transcript=cast(ModelInputTranscriptPort, object()),
            projector=cast(RuntimeCapabilityGraphProjector, object()),
            product_id="research",
            runtime_id="session:model-call-test",
            is_current=lambda: True,
            registration_entries_provider=lambda: (),
            profile_fingerprint_provider=lambda: "profile",
            conversation_id="session-model-call",
            workspace_provider=cast(CapabilityBundleProvider, object()),
        )


class _PreparedAdapter:
    api = "session-model-call-test"

    def __init__(
        self,
        *,
        retry_first: bool = False,
        terminal_error: bool = False,
        report_usage: bool = False,
        response_text: str = "done",
    ) -> None:
        self.transport_calls = 0
        self.retry_first = retry_first
        self.terminal_error = terminal_error
        self.report_usage = report_usage
        self.response_text = response_text

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [
                    serialize_message(message) for message in request.context.messages
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
        if self.retry_first and prepared.attempt == 1:
            if self.report_usage:
                yield {
                    "type": "usage_delta",
                    "input": 10,
                    "output": 0,
                    "cache_read": 3,
                    "total_tokens": 13,
                }
            yield {
                "type": "response_error",
                "message": "retry",
                "code": 429,
                "error_info": {
                    "code": "rate_limit",
                    "message": "retry",
                    "source": self.api,
                    "retryable": True,
                    "details": {},
                },
            }
            return
        if self.terminal_error:
            yield {
                "type": "response_error",
                "message": "Authorization: Bearer secret-token",
                "code": 400,
                "error_info": {
                    "code": "provider",
                    "message": "Provider request failed.",
                    "source": self.api,
                    "retryable": False,
                    "statusCode": 400,
                    "requestId": "request-terminal-400",
                    "details": {
                        "exceptionType": "ProviderHTTPError",
                        "estimatedWireBytes": 900_000,
                        "providerErrorType": "invalid_request_error",
                        "providerErrorCode": "request_too_large",
                        "providerResponseSummary": "private prompt",
                    },
                },
            }
            return
        yield {"type": "response_start", "response_id": "response-1"}
        yield {"type": "text_delta", "text": self.response_text}
        if self.report_usage:
            yield {
                "type": "usage_delta",
                "input": 10,
                "output": 2,
                "cache_read": 3,
                "total_tokens": 15,
            }
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part


def test_current_session_prepares_and_rebuilds_main_model_call() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        certified: list[str] = []

        def certify(snapshot_id: str) -> None:
            assert (
                session.rebuild_model_input(snapshot_id).snapshot.snapshot_id
                == snapshot_id
            )
            certified.append(snapshot_id)

        supplemental_registration = RegistrationInventoryEntry(
            registration_id="extension-tool-registration",
            surface="tool",
            public_key="extension_echo",
            owner_kind="extension",
            owner_id="echo",
            runtime_id="session:model-call-test",
            owner_generation=1,
            attachment="effective",
            state="active",
        )
        runtime = _model_call_runtime(
            session,
            is_current=lambda: True,
            registrations=(supplemental_registration,),
            on_committed_evidence_free_input=certify,
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        assert adapter.transport_calls == 1, agent.state.messages[-1]
        snapshot_ids = [
            entry.payload.snapshot_id
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshot_ids) == 1
        assert certified == snapshot_ids
        rebuilt = session.rebuild_model_input(snapshot_ids[0])
        assert rebuilt.snapshot.purpose == "main"
        assert rebuilt.logical_input["system_prompt"] == "durable system prompt"
        assert rebuilt.logical_input["messages"][0]["content"][0]["text"] == "hello"
        assert rebuilt.prepared_payload["model"] == "model-call-test"
        graph_snapshot = runtime.graph_runtime.snapshot
        assert graph_snapshot is not None
        assert [node.capability_id for node in graph_snapshot.nodes] == [
            "harness.model_input"
        ]
        profile = (
            RuntimeProfileResolver()
            .resolve(standard_capability_composition_plan(product_id="coding"))
            .snapshot()
        )
        view = runtime.effective_view(
            profile,
            model_input_snapshot_id=snapshot_ids[0],
        )
        explanation = runtime.explain_capability(
            profile,
            "harness.model_input",
            model_input_snapshot_id=snapshot_ids[0],
        )
        projected = runtime.to_json(view)

        assert view.clocks.model_surface is not None
        assert view.clocks.model_surface.snapshot_id == snapshot_ids[0]
        assert view.skew == ()
        assert supplemental_registration in view.registrations
        assert rebuilt.snapshot.registration_revision == (
            view.clocks.registration.revision
        )
        assert explanation.clocks == view.clocks
        assert projected["assembly_fingerprint"] == view.assembly_fingerprint
        assert "durable system prompt" not in repr(projected)
        await runtime.dispose()
        assert runtime.graph_runtime.is_closed

    asyncio.run(scenario())


def test_session_reuses_sealed_text_prefix_and_rechecks_mutated_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        user = UserMessage(role="user", content="stable", timestamp=1.0)
        tool = ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="read",
            content=[TextPart(type="text", text="before")],
            is_error=False,
            timestamp=2.0,
        )
        context = Context(system_prompt="prompt", messages=[user, tool])
        calls: list[object] = []
        original = model_call_module.serialize_message

        def count_serialization(message):
            calls.append(message)
            return original(message)

        monkeypatch.setattr(model_call_module, "serialize_message", count_serialization)
        for sequence in (1, 2):
            await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=sequence,
                    model=_model(api="session-model-call-test"),
                    context=context,
                    options=CallOptions(),
                )
            )
        assert calls == [user, tool]

        tool.content[0] = TextPart(type="text", text="after")
        await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=3,
                model=_model(api="session-model-call-test"),
                context=context,
                options=CallOptions(),
            )
        )
        assert calls == [user, tool, tool]
        sealed = session._last_model_input_context
        assert sealed is not None
        assert sealed.logical_input["messages"][1]["content"][0]["text"] == "after"
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_rechecks_nested_tool_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        details = {"nested": ["before"]}
        tool = ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="read",
            content=[TextPart(type="text", text="done")],
            is_error=False,
            timestamp=2.0,
            details=details,
        )
        context = Context(messages=[tool])
        calls = 0
        original = model_call_module.serialize_message

        def count_serialization(message):
            nonlocal calls
            calls += 1
            return original(message)

        monkeypatch.setattr(model_call_module, "serialize_message", count_serialization)
        for sequence in (1, 2):
            await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=sequence,
                    model=_model(api="session-model-call-test"),
                    context=context,
                    options=CallOptions(),
                )
            )
        assert calls == 1
        details["nested"][0] = "after"
        await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=3,
                model=_model(api="session-model-call-test"),
                context=context,
                options=CallOptions(),
            )
        )
        assert calls == 2
        sealed = session._last_model_input_context
        assert sealed is not None
        assert sealed.logical_input["messages"][0]["details"]["nested"][0] == "after"
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_rechecks_assistant_tool_arguments_and_usage_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        arguments = {"path": ["before"]}
        cost = {
            "input": 0.0,
            "output": 0.0,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": 0.0,
        }
        assistant = AssistantMessage(
            role="assistant",
            content=[
                ToolCall(type="toolCall", id="call-1", name="read", arguments=arguments)
            ],
            api="test-api",
            provider="test-provider",
            endpoint="test-endpoint",
            model="test-model",
            response_id=None,
            usage=Usage(0, 0, 0, 0, 0, cost),
            stop_reason="toolUse",
            error_message=None,
            timestamp=1.0,
        )
        context = Context(messages=[assistant])
        calls = 0
        original = model_call_module.serialize_message

        def count_serialization(message):
            nonlocal calls
            calls += 1
            return original(message)

        monkeypatch.setattr(model_call_module, "serialize_message", count_serialization)
        for sequence in (1, 2):
            await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=sequence,
                    model=_model(api="session-model-call-test"),
                    context=context,
                    options=CallOptions(),
                )
            )
        assert calls == 1
        arguments["path"][0] = "after"
        cost["total"] = 1.0
        await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=3,
                model=_model(api="session-model-call-test"),
                context=context,
                options=CallOptions(),
            )
        )
        assert calls == 2
        sealed = session._last_model_input_context
        assert sealed is not None
        wire = sealed.logical_input["messages"][0]
        assert wire["content"][0]["arguments"]["path"][0] == "after"
        assert wire["usage"]["cost"]["total"] == 1.0
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_does_not_reuse_oversized_mutable_tool_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        tool = ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="read",
            content=[TextPart(type="text", text="done")],
            is_error=False,
            timestamp=2.0,
            details={"values": list(range(128))},
        )
        calls = 0
        original = model_call_module.serialize_message

        def count_serialization(message):
            nonlocal calls
            calls += 1
            return original(message)

        monkeypatch.setattr(model_call_module, "serialize_message", count_serialization)
        for sequence in (1, 2):
            await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=sequence,
                    model=_model(api="session-model-call-test"),
                    context=Context(messages=[tool]),
                    options=CallOptions(),
                )
            )
        assert calls == 2
        await runtime.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["content", "details", "append"])
def test_sealed_prefix_is_rechecked_before_model_input_capture(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        tool = ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="read",
            content=[TextPart(type="text", text="before")],
            is_error=False,
            timestamp=2.0,
            details={"nested": ["before"]},
        )
        context = Context(messages=[tool])
        preparation = ModelCallPreparation(
            purpose="main",
            sequence=1,
            model=_model(api="session-model-call-test"),
            context=context,
            options=CallOptions(),
        )
        await runtime.prepare(preparation)
        original = model_call_module.SessionModelCallPreparer._project_logical_messages

        def change_after_projection(self, messages):
            result = original(self, messages)
            if change == "content":
                tool.content[0] = TextPart(type="text", text="after")
            elif change == "details":
                tool.details["nested"][0] = "after"
            else:
                context.messages.append(
                    UserMessage(role="user", content="after", timestamp=3.0)
                )
            return result

        monkeypatch.setattr(
            model_call_module.SessionModelCallPreparer,
            "_project_logical_messages",
            change_after_projection,
        )
        await runtime.prepare(replace(preparation, sequence=2))
        sealed = session._last_model_input_context
        assert sealed is not None
        messages = sealed.logical_input["messages"]
        if change == "content":
            assert messages[0]["content"][0]["text"] == "after"
        elif change == "details":
            assert messages[0]["details"]["nested"][0] == "after"
        else:
            assert len(messages) == 2
            assert messages[1]["content"] == "after"
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_reuses_only_a_committed_prepared_request_prefix() -> None:
    class ReusingAdapter(_PreparedAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.prepared: list[PreparedModelRequest] = []
            self.candidates: list[PreparedModelRequest | None] = []
            self.certified_prefixes: list[int] = []
            self.source_counts: list[int] = []

        def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
            candidate = getattr(
                request.options.prepared_request_committer
                if request.options is not None
                else None,
                "prepared_request_reuse",
                None,
            )
            self.candidates.append(candidate)
            committer = request.options.prepared_request_committer
            self.certified_prefixes.append(
                getattr(committer, "certified_provider_prefix_count", -1)
            )
            self.source_counts.append(
                getattr(committer, "current_provider_source_count", -1)
            )
            prepared = PreparedModelRequest.from_provider_request(
                request,
                payload={
                    "model": request.model.id,
                    "messages": [
                        serialize_message(message)
                        for message in request.context.messages
                    ],
                },
            )
            self.prepared.append(prepared)
            return prepared

    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = ReusingAdapter()
        registry = get_default_api_registry()
        source_id = "session-prefix-reuse-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("first")
            await agent.prompt("second")
            first_user = agent.state.messages[0]
            assert isinstance(first_user, UserMessage)
            agent.state.messages[0] = replace(first_user, content="changed")
            await agent.prompt("third")
        finally:
            registry.unregister_api_adapters(source_id)
        assert adapter.transport_calls == 3
        assert adapter.candidates == [None, adapter.prepared[0], adapter.prepared[1]]
        assert adapter.certified_prefixes == [0, 1, 0]
        assert adapter.source_counts == [1, 3, 5]
        first_messages = adapter.prepared[0].payload["messages"]
        second_messages = adapter.prepared[1].payload["messages"]
        assert second_messages[0] is first_messages[0]
        snapshot_ids = [
            entry.payload.snapshot_id
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshot_ids) == 3
        for snapshot_id, prepared in zip(snapshot_ids, adapter.prepared, strict=True):
            rebuilt = session.rebuild_model_input(snapshot_id)
            assert rebuilt.prepared_payload == prepared.payload_for_transport()
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_certificate_reuses_exact_builtin_chat_payload() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        model = replace(
            _model(api="openai-completions"),
            capabilities=Capabilities(stream=True, tool_use=True, max_tokens=128),
            adapter=OpenAICompletionsConfig(),
        )
        adapter = OpenAIChatCompletionsAdapter()
        tool = Tool(name="read", description="Read", parameters={"type": "object"})
        user = UserMessage(role="user", content="hello", timestamp=1.0)
        first_context = Context(messages=[user], tools=[tool])

        async def prepare(
            context: Context, sequence: int
        ) -> tuple[CallOptions, ProviderRequest]:
            options = await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=sequence,
                    model=model,
                    context=context,
                    options=CallOptions(),
                )
            )
            return options, ProviderRequest(
                model=model,
                context=normalize_context(
                    context, model=model, pairing_mode=options.pairing_mode
                ),
                options=options,
                base_url="https://provider.test/v1",
                max_output_tokens=16,
            )

        first_options, first_request = await prepare(first_context, 1)
        first_prepared = adapter.prepare_request(first_request)
        assert first_options.prepared_request_committer is not None
        await first_options.prepared_request_committer.commit_prepared_request(
            first_prepared
        )

        assistant = AssistantMessage(
            role="assistant",
            content=[ToolCall(type="toolCall", id="call-1", name="read", arguments={})],
            api="openai-completions",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            response_id=None,
            usage=Usage(0, 0, 0, 0, 0, None),
            stop_reason="toolUse",
            error_message=None,
            timestamp=2.0,
        )
        result = ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="read",
            content=[TextPart(type="text", text="done")],
            is_error=False,
            timestamp=3.0,
        )
        second_context = Context(messages=[user, assistant, result], tools=[tool])
        second_options, second_request = await prepare(second_context, 2)
        assert second_options.prepared_request_committer is not None
        assert (
            second_options.prepared_request_committer.certified_provider_prefix_count
            == 1
        )
        expected = adapter.prepare_request(
            replace(second_request, options=CallOptions())
        )
        second_prepared = adapter.prepare_request(second_request)
        assert second_prepared._reused_message_prefix_count > 0
        assert (
            second_prepared.payload["messages"][0]
            is first_prepared.payload["messages"][0]
        )
        assert second_prepared.canonical_payload == expected.canonical_payload
        assert second_prepared.payload_hash == expected.payload_hash
        assert second_prepared.metrics == expected.metrics
        assert (
            second_prepared.payload_for_transport() == expected.payload_for_transport()
        )
        await second_options.prepared_request_committer.commit_prepared_request(
            second_prepared
        )

        snapshot_ids = [
            entry.payload.snapshot_id
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshot_ids) == 2
        for snapshot_id, prepared in zip(
            snapshot_ids, (first_prepared, second_prepared), strict=True
        ):
            rebuilt = session.rebuild_model_input(snapshot_id)
            assert rebuilt.prepared_payload == prepared.payload_for_transport()
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_sealed_context_rejects_mutation_before_provider_normalization() -> (
    None
):
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        user = UserMessage(
            role="user",
            content=[TextPart(type="text", text="sealed")],
            timestamp=1.0,
        )
        tool = Tool(
            name="read",
            description="Read",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        context = Context(messages=[user], tools=[tool])
        options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=1,
                model=_model(api="openai-completions"),
                context=context,
                options=CallOptions(),
            )
        )
        committer = options.prepared_request_committer
        assert committer is not None
        committer.verify_sealed_context(context)
        user.content[0] = TextPart(type="text", text="changed")
        with pytest.raises(RuntimeError, match="sealed Model Input context changed"):
            committer.verify_sealed_context(context)
        user.content[0] = TextPart(type="text", text="sealed")
        context.messages.append(
            UserMessage(role="user", content="extra", timestamp=2.0)
        )
        with pytest.raises(RuntimeError, match="sealed Model Input context changed"):
            committer.verify_sealed_context(context)
        context.messages.pop()
        with pytest.raises(RuntimeError, match="sealed Model Input context changed"):
            committer.verify_sealed_context(replace(context, system_prompt="changed"))
        tool.parameters["properties"]["path"]["type"] = "integer"
        with pytest.raises(RuntimeError, match="sealed Model Input context changed"):
            committer.verify_sealed_context(context)
        committer.start_sealed_context_verification(context)
        prepared = PreparedModelRequest.from_provider_request(
            ProviderRequest(
                model=_model(api="openai-completions"),
                context=normalize_context(context),
                options=options,
                base_url="https://provider.test/v1",
                max_output_tokens=16,
            ),
            payload={"messages": []},
        )
        with pytest.raises(RuntimeError, match="sealed Model Input context changed"):
            await committer.commit_prepared_request(prepared)
        assert not any(
            entry.kind == "model.input.prepared" for entry in session.get_entries()
        )
        user.content[0] = TextPart(type="text", text="changed again")
        owned = committer.owned_sealed_context(context)
        assert owned.messages[0].content[0].text == "sealed"
        assert owned.tools[0].parameters["properties"]["path"]["type"] == "string"
        await runtime.dispose()

    asyncio.run(scenario())


def test_strict_message_snapshot_detects_nested_json_and_number_type_changes() -> None:
    original = UserMessage(
        role="user",
        content=[
            TextPart(
                type="text",
                text="sealed",
                text_signature={"nested": [0.0, 1]},
            )
        ],
        timestamp=1.0,
    )
    snapshot = deepcopy(original)
    assert model_call_module._strict_message_equal(original, snapshot)
    original.content[0].text_signature["nested"][0] = -0.0
    assert not model_call_module._strict_message_equal(original, snapshot)
    original.content[0].text_signature["nested"][0] = 0.0
    original.content[0].text_signature["nested"][1] = 1.0
    assert not model_call_module._strict_message_equal(original, snapshot)
    original.content[0].text_signature["nested"][1] = 1

    class EqualString(str):
        pass

    original.content[0] = replace(original.content[0], text=EqualString("sealed"))
    assert not model_call_module._strict_message_equal(original, snapshot)


def test_committed_strict_snapshot_skips_historical_shape_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        model = _model(api="openai-completions")
        user = UserMessage(
            role="user", content=[TextPart(type="text", text="sealed")], timestamp=1.0
        )
        first_context = Context(messages=[user])
        first_options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=1,
                model=model,
                context=first_context,
                options=CallOptions(),
            )
        )
        first_committer = first_options.prepared_request_committer
        assert first_committer is not None
        first_committer.normalize_owned_context(
            first_committer.owned_sealed_context(first_context),
            model=model,
            pairing_mode="repair",
        )
        first_prepared = PreparedModelRequest.from_provider_request(
            ProviderRequest(
                model=model,
                context=normalize_context(first_context),
                options=first_options,
                base_url="https://provider.test/v1",
                max_output_tokens=16,
            ),
            payload={"messages": []},
        )
        await first_committer.commit_prepared_request(first_prepared)
        assert runtime._consumer is not None
        preparer = runtime._consumer.facets.require(
            model_call_module.MODEL_INPUT_PREPARATION_FACET
        )
        assert preparer._strict_snapshot_task is None
        await first_committer.record_terminal_model_call(
            PreparedModelCallOutcome(
                invocation_id=first_prepared.invocation_id,
                disposition="completed",
                stop_reason="toolUse",
                usage=Usage(0, 0, 0, 0, 0, None),
            ),
            usage_observed=False,
        )
        assert preparer._strict_snapshot_task is not None
        await preparer._strict_snapshot_task
        assert preparer._strict_message_snapshots[0] is not None
        assert preparer._strict_prefix_encoded is not None

        observed: list[Message] = []
        original = model_call_module._sealed_message_shape
        matches: list[Message] = []
        original_match = model_call_module._strict_snapshot_matches

        def count_match(message, snapshot):
            matches.append(message)
            return original_match(message, snapshot)

        monkeypatch.setattr(model_call_module, "_strict_snapshot_matches", count_match)

        def count_shape(message):
            observed.append(message)
            return original(message)

        monkeypatch.setattr(model_call_module, "_sealed_message_shape", count_shape)
        second_context = Context(
            messages=[
                user,
                UserMessage(role="user", content="next", timestamp=2.0),
            ]
        )
        second_options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=2,
                model=model,
                context=second_context,
                options=CallOptions(),
            )
        )
        assert second_options.prepared_request_committer is not None
        assert matches == []
        second_options.prepared_request_committer.verify_sealed_context(second_context)
        owned = second_options.prepared_request_committer.owned_sealed_context(
            second_context
        )
        assert owned.messages[0] is preparer._strict_message_snapshots[0].message
        assert user not in observed
        user.content[0] = TextPart(type="text", text="changed")
        third_options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=3,
                model=model,
                context=second_context,
                options=CallOptions(),
            )
        )
        assert matches and all(message is user for message in matches)
        assert third_options.prepared_request_committer is not None
        assert (
            third_options.prepared_request_committer.certified_provider_prefix_count
            == 0
        )
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_incremental_normalization_matches_full_after_user_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        model = replace(
            _model(api="openai-completions"),
            capabilities=Capabilities(stream=True, tool_use=True, max_tokens=128),
            adapter=OpenAICompletionsConfig(),
        )
        user = UserMessage(role="user", content="first", timestamp=1.0)
        tool = Tool(name="read", description="Read", parameters={"type": "object"})
        first_context = Context(messages=[user], tools=[tool])
        first_options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=1,
                model=model,
                context=first_context,
                options=CallOptions(),
            )
        )
        first_committer = first_options.prepared_request_committer
        assert first_committer is not None
        first_owned = first_committer.owned_sealed_context(first_context)
        first_result = first_committer.normalize_owned_context(
            first_owned, model=model, pairing_mode="repair"
        )
        first_request = ProviderRequest(
            model=model,
            context=first_result.context,
            options=first_options,
            base_url="https://provider.test/v1",
            max_output_tokens=16,
        )
        first_prepared = OpenAIChatCompletionsAdapter().prepare_request(first_request)
        await first_committer.commit_prepared_request(first_prepared)
        assert runtime._consumer is not None
        preparer = runtime._consumer.facets.require(
            model_call_module.MODEL_INPUT_PREPARATION_FACET
        )
        assert preparer._normalized_cache_task is None
        assert preparer._strict_snapshot_task is None
        await first_committer.record_terminal_model_call(
            PreparedModelCallOutcome(
                invocation_id=first_prepared.invocation_id,
                disposition="completed",
                stop_reason="toolUse",
                usage=Usage(0, 0, 0, 0, 0, None),
            ),
            usage_observed=False,
        )
        assert preparer._normalized_cache_task is not None
        await preparer._normalized_cache_task
        assert preparer._normalized_cache is not None

        assistant = AssistantMessage(
            role="assistant",
            content=[ToolCall(type="toolCall", id="fresh", name="read", arguments={})],
            api="openai-completions",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            response_id=None,
            usage=Usage(0, 0, 0, 0, 0, None),
            stop_reason="toolUse",
            error_message=None,
            timestamp=2.0,
        )
        result = ToolResultMessage(
            role="toolResult",
            tool_call_id="fresh",
            tool_name="read",
            content=[TextPart(type="text", text="done")],
            is_error=False,
            timestamp=3.0,
        )
        second_context = Context(messages=[user, assistant, result], tools=[tool])
        second_options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=2,
                model=model,
                context=second_context,
                options=CallOptions(),
            )
        )
        second_committer = second_options.prepared_request_committer
        assert second_committer is not None
        second_owned = second_committer.owned_sealed_context(second_context)
        expected = normalize_context_result(
            second_owned, model=model, pairing_mode="repair"
        )
        lengths: list[int] = []
        original = model_call_module.normalize_context_result

        def count_normalization(context, **kwargs):
            lengths.append(len(context.messages))
            return original(context, **kwargs)

        monkeypatch.setattr(
            model_call_module, "normalize_context_result", count_normalization
        )
        actual = second_committer.normalize_owned_context(
            second_owned, model=model, pairing_mode="repair"
        )
        assert actual == expected
        assert lengths == [2]

        lengths.clear()
        changed_model = replace(model, id="different-model")
        second_committer.normalize_owned_context(
            second_owned, model=changed_model, pairing_mode="repair"
        )
        assert lengths == [3]

        lengths.clear()
        second_committer.normalize_owned_context(
            second_owned, model=model, pairing_mode="strict"
        )
        assert lengths == [3]

        lengths.clear()
        cached_user = preparer._normalized_cache.result.context.messages[0]
        assert isinstance(cached_user, UserMessage)
        cached_user.content[0] = TextPart(type="text", text="tampered")
        assert (
            second_committer.normalize_owned_context(
                second_owned, model=model, pairing_mode="repair"
            )
            == expected
        )
        assert lengths == [3]
        await runtime.dispose()

    asyncio.run(scenario())


def test_terminal_model_call_skips_unneeded_normalization_prewarm() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        model = replace(
            _model(api="openai-completions"),
            capabilities=Capabilities(stream=True, tool_use=True, max_tokens=128),
            adapter=OpenAICompletionsConfig(),
        )
        context = Context(
            messages=[UserMessage(role="user", content="done", timestamp=1.0)]
        )
        options = await runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=1,
                model=model,
                context=context,
                options=CallOptions(),
            )
        )
        committer = options.prepared_request_committer
        assert committer is not None
        result = committer.normalize_owned_context(
            committer.owned_sealed_context(context), model=model, pairing_mode="repair"
        )
        prepared = OpenAIChatCompletionsAdapter().prepare_request(
            ProviderRequest(
                model=model,
                context=result.context,
                options=options,
                base_url="https://provider.test/v1",
                max_output_tokens=16,
            )
        )
        await committer.commit_prepared_request(prepared)
        await committer.record_terminal_model_call(
            PreparedModelCallOutcome(
                invocation_id=prepared.invocation_id,
                disposition="completed",
                stop_reason="stop",
                usage=Usage(0, 0, 0, 0, 0, None),
            ),
            usage_observed=False,
        )
        assert runtime._consumer is not None
        preparer = runtime._consumer.facets.require(
            model_call_module.MODEL_INPUT_PREPARATION_FACET
        )
        assert preparer._normalized_cache_task is None
        assert preparer._strict_snapshot_task is None
        await runtime.dispose()

    asyncio.run(scenario())


def test_resource_evidence_is_request_bound_durable_and_resumable() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        certified: list[str] = []
        message_record_id, transcript_message = session.get_context_message_bindings()[
            0
        ]
        evidence = PreparedResourceEvidence(
            model_visible_text="hello",
            skills=(_skill_evidence_payload(),),
        )
        evidence_runtime = SessionRequestEvidenceRuntime(
            get_context_message_bindings=session.get_context_message_bindings,
            get_active_records=session.get_active_entries,
            rebuild_model_input=session.rebuild_model_input,
        )
        owner = object()
        evidence_runtime.bind(transcript_message, evidence, owner=owner)
        assert (
            evidence_runtime.commit_message(transcript_message, message_record_id)
            is True
        )

        runtime = _model_call_runtime(
            session,
            is_current=lambda: True,
            request_evidence_provider=evidence_runtime.project_model_input,
            on_committed_evidence_free_input=certified.append,
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-resource-evidence"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)
        assert certified == []

        snapshot_id = next(
            entry.payload.snapshot_id
            for entry in session.get_active_entries()
            if entry.kind == "model.input.prepared"
        )
        rebuilt = session.rebuild_model_input(snapshot_id)
        component = rebuilt.logical_input[RESOURCE_EVIDENCE_COMPONENT]
        assert component["schemaId"] == RESOURCE_EVIDENCE_SCHEMA_ID
        assert component["schemaVersion"] == 1
        assert component["contextComplete"] is True
        assert component["messages"] == [
            {
                "messageIndex": 0,
                "messageRecordId": message_record_id,
                "messageTextDigest": evidence.message_text_digest,
                "modelVisibleText": "hello",
                "skills": [_skill_evidence_payload()],
            }
        ]

        resumed = SessionRequestEvidenceRuntime(
            get_context_message_bindings=session.get_context_message_bindings,
            get_active_records=session.get_active_entries,
            rebuild_model_input=session.rebuild_model_input,
        )
        recovered = resumed.project_model_input(
            ModelCallPreparation(
                purpose="continuation",
                sequence=2,
                model=_model(api=adapter.api),
                context=Context(
                    system_prompt="durable system prompt",
                    messages=[UserMessage(role="user", content="hello", timestamp=1.0)],
                ),
                options=CallOptions(),
            )
        )
        assert recovered == component
        assert (
            resumed.project_model_input(
                ModelCallPreparation(
                    purpose="tool-loop",
                    sequence=3,
                    model=_model(api=adapter.api),
                    context=Context(
                        system_prompt="durable system prompt",
                        messages=[
                            UserMessage(role="user", content="hello", timestamp=1.0)
                        ],
                    ),
                    options=CallOptions(),
                )
            )
            == component
        )

        compacted = SessionRequestEvidenceRuntime(
            get_context_message_bindings=lambda records=None: (
                () if records is None else session.get_context_message_bindings(records)
            ),
            get_active_records=session.get_active_entries,
            rebuild_model_input=session.rebuild_model_input,
        )
        assert (
            compacted.project_model_input(
                ModelCallPreparation(
                    purpose="post-compaction",
                    sequence=4,
                    model=_model(api=adapter.api),
                    context=Context(
                        system_prompt="durable system prompt",
                        messages=[],
                    ),
                    options=CallOptions(),
                )
            )
            is None
        )

        compacted.close()
        resumed.close()
        evidence_runtime.close()
        await runtime.dispose()

    asyncio.run(scenario())


def test_anchored_resource_evidence_resume_skips_snapshot_rebuild() -> None:
    async def scenario() -> None:
        evidence = PreparedResourceEvidence(
            model_visible_text="hello",
            skills=(_skill_evidence_payload(),),
        )
        session = await _transcript_session(
            message_metadata={
                RESOURCE_EVIDENCE_METADATA_KEY: evidence.to_message_metadata()
            }
        )
        runtime_evidence = SessionRequestEvidenceRuntime(
            get_context_message_bindings=session.get_context_message_bindings,
            get_active_records=session.get_active_entries,
            rebuild_model_input=lambda _snapshot_id: pytest.fail(
                "anchored evidence should not rebuild historical snapshots"
            ),
        )
        runtime = _model_call_runtime(
            session,
            is_current=lambda: True,
            request_evidence_provider=runtime_evidence.project_model_input,
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-anchored-resource-evidence"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        resumed = SessionRequestEvidenceRuntime(
            get_context_message_bindings=session.get_context_message_bindings,
            get_active_records=session.get_active_entries,
            rebuild_model_input=lambda _snapshot_id: pytest.fail(
                "anchored evidence should not rebuild historical snapshots"
            ),
        )
        component = resumed.project_model_input(
            ModelCallPreparation(
                purpose="continuation",
                sequence=2,
                model=_model(api=adapter.api),
                context=Context(
                    system_prompt="durable system prompt",
                    messages=[session.get_context_message_bindings()[0][1]],
                ),
                options=CallOptions(),
            )
        )
        assert component is not None
        assert component["messages"][0]["modelVisibleText"] == "hello"
        assert any(
            entry.kind == "model.input.prepared"
            for entry in session.get_active_entries()
        )
        resumed.close()
        runtime_evidence.close()
        await runtime.dispose()

    asyncio.run(scenario())


def test_resource_evidence_recovery_is_strict_and_transactional() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        message_record_id, transcript_message = session.get_context_message_bindings()[
            0
        ]
        evidence = PreparedResourceEvidence(
            model_visible_text="hello",
            skills=(_skill_evidence_payload(),),
        )
        first_message = evidence.to_message_payload(
            message_record_id=message_record_id,
            message_index=0,
        )
        duplicate_message = deepcopy(first_message)
        component: dict[str, object] = {
            "contextComplete": True,
            "schemaId": RESOURCE_EVIDENCE_SCHEMA_ID,
            "schemaVersion": 1,
            "messages": [first_message, duplicate_message],
        }
        runtime = _model_call_runtime(
            session,
            is_current=lambda: True,
            request_evidence_provider=lambda _preparation: component,
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-invalid-resource-evidence"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        resumed = SessionRequestEvidenceRuntime(
            get_context_message_bindings=session.get_context_message_bindings,
            get_active_records=session.get_active_entries,
            rebuild_model_input=session.rebuild_model_input,
        )
        preparation = ModelCallPreparation(
            purpose="continuation",
            sequence=2,
            model=_model(api=adapter.api),
            context=Context(
                system_prompt="durable system prompt",
                messages=[transcript_message],
            ),
            options=CallOptions(),
        )
        snapshot_id = next(
            entry.payload.snapshot_id
            for entry in session.get_active_entries()
            if entry.kind == "model.input.prepared"
        )
        assert (
            session.rebuild_model_input(snapshot_id).logical_input[
                RESOURCE_EVIDENCE_COMPONENT
            ]
            == component
        )
        with pytest.raises(
            RequestEvidenceIntegrityError, match="repeats a message index"
        ):
            resumed.audit_snapshot_resource_evidence(snapshot_id)
        with pytest.raises(
            RequestEvidenceIntegrityError, match="repeats a message index"
        ):
            resumed.project_model_input(preparation)

        session.branch(message_record_id)
        assert resumed.project_model_input(preparation) is None
        resumed.close()
        await runtime.dispose()

    asyncio.run(scenario())


def test_current_session_persists_observed_attempt_usage_before_outcome() -> None:
    async def scenario() -> None:
        class CountingBatchStore(MemoryConversationStore):
            def __init__(self) -> None:
                super().__init__(record_id=lambda record: record.record_id)
                self.batch_sizes: list[int] = []

            async def append_batch(
                self, key, records, *, expected_revision, operation_ids
            ):
                self.batch_sizes.append(len(records))
                return await super().append_batch(
                    key,
                    records,
                    expected_revision=expected_revision,
                    operation_ids=operation_ids,
                )

        backend = CountingBatchStore()
        session = await _transcript_session(backend=backend)
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter(report_usage=True)
        registry = get_default_api_registry()
        source_id = "session-model-call-attempt-usage-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        entries = session.get_entries()
        usage_entries = [
            entry for entry in entries if entry.kind == MODEL_CALL_ATTEMPT_USAGE_KIND
        ]
        outcome_index = next(
            index
            for index, entry in enumerate(entries)
            if entry.kind == MODEL_CALL_OUTCOME_KIND
        )

        assert len(usage_entries) == 1
        usage = usage_entries[0].payload
        assert isinstance(usage, ModelCallAttemptUsage)
        assert usage.model_input_snapshot_id == next(
            entry.payload.snapshot_id
            for entry in entries
            if entry.kind == "model.input.prepared"
        )
        assert usage.input == 10
        assert usage.output == 2
        assert usage.cache_read == 3
        assert usage.total_tokens == 15
        assert usage.terminal is True
        assert entries.index(usage_entries[0]) < outcome_index
        assert backend.batch_sizes[-1] == 2
        inspector = AgentSessionInspector(
            agent=agent,
            session=session,
            get_session_id=lambda: "session-model-call",
            get_session_name=lambda: None,
            get_active_tool_names=lambda: [],
            is_retrying=lambda: False,
            is_compacting=lambda: False,
            get_last_diagnostics=lambda limit: [],
            get_model_selection=lambda: None,
        )
        context_usage = inspector.get_context_usage()
        anchor = context_usage.provider_anchor
        assert anchor is not None
        assert anchor.model_input_snapshot_id == usage.model_input_snapshot_id
        assert anchor.provider_prompt_tokens == 13
        assert anchor.sampled_surface_tokens > 0
        assert anchor.sampled_surface_fingerprint.startswith("sha256:")
        assert anchor.sampled_prepared_payload_hash.startswith("sha256:")
        assert anchor.sampled_structural_envelope_fingerprint is not None
        assert anchor.sampled_structural_envelope_fingerprint.startswith("sha256:")
        assert anchor.provider_id == "test-provider"
        assert anchor.api_id == adapter.api
        assert context_usage.source == "provider_anchor"
        assert context_usage.structural_envelope_status == "logical_match"
        assert context_usage.compactable is False
        agent.system_prompt = "changed system prompt"
        changed_usage = inspector.get_context_usage()
        assert changed_usage.source != "provider_anchor"
        assert changed_usage.structural_envelope_status == "logical_mismatch"
        await runtime.dispose()

    asyncio.run(scenario())


def test_model_call_binding_reports_prepare_and_durable_transport_boundary() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        log = _PerformanceLog()
        turn_performance = TurnStartPerformanceRuntime(
            session_id="session-model-call",
            turn_id_factory=lambda: "turn-model-call",
            log=log,
        )
        timing = turn_performance.begin(source="tui")
        timing.activate()
        runtime = _model_call_runtime(
            session,
            is_current=lambda: True,
            turn_performance=turn_performance,
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-performance-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("private prompt")
        finally:
            registry.unregister_api_adapters(source_id)
            timing.finish("completed")

        assert len(log.events) == 1
        scope, name, data = log.events[0]
        assert (scope, name) == ("turn.start.performance", "turn")
        assert data["invocation_id"] is not None
        assert data["provider_id"] == "test-provider"
        assert data["endpoint_id"] == "test-endpoint"
        assert data["api_id"] == adapter.api
        assert data["model_id"] == "model-call-test"
        assert data["local_ready_ms"] is not None
        assert data["startup_ms"] is None
        milestones = cast(dict[str, JSONValue], data["milestones"])
        assert set(milestones) >= {
            "model_call_prepare_started",
            "model_call_prepared",
            "model_input_commit_started",
            "transport_ready",
        }
        assert "private prompt" not in repr(data)
        await runtime.dispose()

    asyncio.run(scenario())


def test_provider_retry_commits_each_attempt_with_one_invocation_identity() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter(retry_first=True, report_usage=True)
        registry = get_default_api_registry()
        source_id = "session-model-call-provider-retry-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            call_options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0)
            ),
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        snapshots = [
            entry.payload
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert adapter.transport_calls == 2
        assert [snapshot.attempt for snapshot in snapshots] == [1, 2]
        assert len({snapshot.invocation_id for snapshot in snapshots}) == 1
        assert [snapshot.purpose for snapshot in snapshots] == ["main", "main"]
        outcomes = [
            entry.payload
            for entry in session.get_entries()
            if entry.kind == MODEL_CALL_OUTCOME_KIND
        ]
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert isinstance(outcome, ModelCallOutcome)
        assert outcome.invocation_id == snapshots[0].invocation_id
        assert outcome.model_input_snapshot_ids == tuple(
            snapshot.snapshot_id for snapshot in snapshots
        )
        assert outcome.disposition == "completed"
        assert outcome.stop_reason == "stop"
        attempt_usage = [
            entry.payload
            for entry in session.get_entries()
            if entry.kind == MODEL_CALL_ATTEMPT_USAGE_KIND
        ]
        assert len(attempt_usage) == 2
        assert all(isinstance(item, ModelCallAttemptUsage) for item in attempt_usage)
        assert [item.attempt for item in attempt_usage] == [1, 2]
        assert [item.model_input_snapshot_id for item in attempt_usage] == [
            snapshot.snapshot_id for snapshot in snapshots
        ]
        inspector = AgentSessionInspector(
            agent=agent,
            session=session,
            get_session_id=lambda: "session-model-call",
            get_session_name=lambda: None,
            get_active_tool_names=lambda: [],
            is_retrying=lambda: False,
            is_compacting=lambda: False,
            get_last_diagnostics=lambda limit: [],
            get_model_selection=lambda: None,
        )
        anchor = inspector.get_context_usage().provider_anchor
        assert anchor is not None
        assert anchor.attempt == 2
        assert anchor.model_input_snapshot_id == snapshots[1].snapshot_id
        totals = inspector.build_session_stats().tokens
        assert totals.input == 20
        assert totals.output == 2
        assert totals.cache_read == 6
        assert totals.total == 28
        assert totals.source == "attempt_usage_facts"
        assert totals.incomplete_attempts is False
        projected = session.get_model_call_invocations()
        assert len(projected) == 1
        assert projected[0].state == "completed"
        assert projected[0].outcome == outcome
        for snapshot in snapshots:
            assert (
                session.rebuild_model_input(snapshot.snapshot_id).snapshot == snapshot
            )
        await runtime.dispose()

    asyncio.run(scenario())


def test_terminal_provider_failure_records_one_safe_model_call_outcome() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter(terminal_error=True)
        registry = get_default_api_registry()
        source_id = "session-model-call-terminal-failure-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        snapshots = [
            entry.payload
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        outcomes = [
            entry.payload
            for entry in session.get_entries()
            if isinstance(entry.payload, ModelCallOutcome)
        ]
        assert adapter.transport_calls == 1
        assert len(snapshots) == 1
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.model_input_snapshot_ids == (snapshots[0].snapshot_id,)
        assert outcome.disposition == "failed"
        assert outcome.failure is not None
        assert outcome.failure.code == "request_too_large"
        assert outcome.failure.status_code == 400
        assert outcome.failure.request_id == "request-terminal-400"
        failure_details = dict(outcome.failure.details)
        assert {
            "exceptionType": failure_details["exceptionType"],
            "providerErrorType": failure_details["providerErrorType"],
            "providerErrorCode": failure_details["providerErrorCode"],
        } == {
            "exceptionType": "ProviderHTTPError",
            "providerErrorType": "invalid_request_error",
            "providerErrorCode": "request_too_large",
        }
        assert failure_details["canonicalBytes"] > 0
        assert failure_details["messageBytes"] > 0
        assert failure_details["messageCount"] >= 1
        assert failure_details["imageBytes"] == 0
        assert failure_details["toolSchemaBytes"] == 2
        assert "secret-token" not in repr(outcome)
        assert "private prompt" not in repr(outcome)
        await runtime.dispose()

    asyncio.run(scenario())


def test_capacity_preflight_records_failed_outcome_without_snapshot_or_transport() -> (
    None
):
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-capacity-preflight-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            call_options=CallOptions(
                request_limits=PreparedRequestLimits(max_canonical_bytes=1)
            ),
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        snapshots = [
            entry
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        outcomes = [
            entry.payload
            for entry in session.get_entries()
            if isinstance(entry.payload, ModelCallOutcome)
        ]
        assert adapter.transport_calls == 0
        assert snapshots == []
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.model_input_snapshot_ids == ()
        assert outcome.disposition == "failed"
        assert outcome.failure is not None
        assert outcome.failure.code == "request_too_large"
        assert dict(outcome.failure.details)["capacityMetric"] == "canonicalBytes"
        assert dict(outcome.failure.details)["capacityMaximum"] == 1
        assert session.get_model_call_invocations()[0].state == "failed"
        await runtime.dispose()

    asyncio.run(scenario())


def test_model_input_uses_current_profile_fact_instead_of_mount_profile() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        runtime.current_profile_fingerprint = "d" * 64
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-current-profile-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        snapshot = next(
            entry.payload
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        )
        assert snapshot.profile_fingerprint == "d" * 64
        assert snapshot.profile_fingerprint != runtime.graph_runtime.profile_fingerprint
        assert session.rebuild_model_input(snapshot.snapshot_id).snapshot == snapshot
        await runtime.dispose()

    asyncio.run(scenario())


def test_mount_registration_mismatch_writes_nothing_and_sends_nothing() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        await runtime._ensure_consumer()
        inventory = runtime._projector.registration_inventory()
        runtime._projector.registration_inventory = lambda: replace(  # type: ignore[method-assign]
            inventory,
            mount_generation=inventory.mount_generation + 1,
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-clock-mismatch-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "durable system prompt",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        assert adapter.transport_calls == 0
        assert all(
            entry.kind != "model.input.prepared" for entry in session.get_entries()
        )
        assert isinstance(agent.state.messages[-1], AssistantMessage)
        assert agent.state.messages[-1].error_message == "Agent run failed."
        assert agent.state.messages[-1].error_info is not None
        assert agent.state.messages[-1].error_info["details"] == {
            "exceptionType": "ValueError"
        }
        await runtime.dispose()

    asyncio.run(scenario())


def test_concurrent_session_model_inputs_allow_only_one_transport() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-conflict-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        model = _model(api=adapter.api)
        context = Context(
            system_prompt="system",
            messages=[UserMessage(role="user", content="hello", timestamp=1.0)],
        )
        try:
            first_options = await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=1,
                    model=model,
                    context=context,
                    options=CallOptions(),
                )
            )
            second_options = await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=2,
                    model=model,
                    context=context,
                    options=CallOptions(),
                )
            )
            first_stream, second_stream = await asyncio.gather(
                stream(model, context, first_options),
                stream(model, context, second_options),
            )
            results = await asyncio.gather(
                first_stream.result(),
                second_stream.result(),
                return_exceptions=True,
            )
        finally:
            registry.unregister_api_adapters(source_id)

        assert adapter.transport_calls == 1
        assert sum(isinstance(result, Exception) for result in results) == 1
        snapshots = [
            entry.payload
            for entry in session.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshots) == 1
        assert (
            session.rebuild_model_input(snapshots[0].snapshot_id).snapshot
            == (snapshots[0])
        )
        await runtime.dispose()

    asyncio.run(scenario())


def test_worker_preparation_uses_the_transcript_owner_loop_for_owned_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        owner_loop = asyncio.get_running_loop()
        current_checked = []
        projected = []
        created = []
        create_committer = session.create_model_input_committer

        def observe_create_committer(**kwargs: object):
            assert asyncio.get_running_loop() is owner_loop
            created.append(True)
            return create_committer(**kwargs)

        monkeypatch.setattr(session, "create_model_input_committer", observe_create_committer)

        def is_current() -> bool:
            assert asyncio.get_running_loop() is owner_loop
            current_checked.append(True)
            return True

        def project_evidence(preparation: ModelCallPreparation) -> None:
            assert preparation.purpose == "main"
            assert asyncio.get_running_loop() is owner_loop
            projected.append(True)
            return None

        runtime = _model_call_runtime(
            session,
            is_current=is_current,
            request_evidence_provider=project_evidence,
        )
        try:
            options = await runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=1,
                    model=_model(api="test-api"),
                    context=Context(
                        messages=[UserMessage(role="user", content="hello", timestamp=1.0)]
                    ),
                    options=CallOptions(),
                )
            )
            assert options.prepared_request_committer is not None
            assert current_checked == [True]
            assert projected == [True]
            assert created == [True]
        finally:
            await runtime.dispose()

    asyncio.run(scenario())


def test_cancelled_model_preparation_keeps_input_responsive_and_serializes_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    original = SessionModelCallCapabilityConsumer.prepare

    def slow_prepare(
        consumer: SessionModelCallCapabilityConsumer,
        preparation: ModelCallPreparation,
        *,
        owner_loop: asyncio.AbstractEventLoop | None = None,
    ) -> CallOptions:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(1)
        return original(consumer, preparation, owner_loop=owner_loop)

    monkeypatch.setattr(SessionModelCallCapabilityConsumer, "prepare", slow_prepare)

    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        preparation = ModelCallPreparation(
            purpose="main",
            sequence=1,
            model=_model(api="test-api"),
            context=Context(
                system_prompt="system",
                messages=[UserMessage(role="user", content="hello", timestamp=1.0)],
            ),
            options=CallOptions(),
        )
        try:
            first = asyncio.create_task(runtime.prepare(preparation))
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait), 0.5)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(first, 0.1)
            second = asyncio.create_task(runtime.prepare(preparation))
            await asyncio.sleep(0)
            assert calls == 1
            release.set()
            options = await asyncio.wait_for(second, 2)
            assert options.prepared_request_committer is not None
            assert calls == 2
        finally:
            release.set()
            await runtime.dispose()

    asyncio.run(scenario())


def test_non_current_session_fails_before_model_transport() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: False)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-not-current-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "system",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        assert adapter.transport_calls == 0
        assert isinstance(agent.state.messages[-1], AssistantMessage)
        assert agent.state.messages[-1].error_message == "Agent run failed."
        assert agent.state.messages[-1].error_info is not None
        assert agent.state.messages[-1].error_info["details"] == {
            "exceptionType": "RuntimeError"
        }
        assert all(
            entry.kind != "model.input.prepared" for entry in session.get_entries()
        )
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_retired_after_preparation_fails_at_commit_barrier() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        current_checks = iter((True, False))
        runtime = _model_call_runtime(
            session,
            is_current=lambda: next(current_checks, False),
        )
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        source_id = "session-model-call-retired-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        agent = Agent(
            initial_state={
                "system_prompt": "system",
                "model": _model(api=adapter.api),
                "thinking_level": "off",
            },
            prepare_model_call=runtime.prepare,
        )
        try:
            await agent.prompt("hello")
        finally:
            registry.unregister_api_adapters(source_id)

        assert adapter.transport_calls == 0
        assert isinstance(agent.state.messages[-1], AssistantMessage)
        assert agent.state.messages[-1].stop_reason == "error"
        assert all(
            entry.kind != "model.input.prepared" for entry in session.get_entries()
        )
        await runtime.dispose()

    asyncio.run(scenario())


def test_compaction_v2_records_and_rebuilds_summary_model_input() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        source_id = session.get_entries()[0].record_id
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        adapter_source = "session-model-call-compaction-test"
        registry.register_api_adapter(adapter, source_id=adapter_source)
        try:
            result = await execute_transcript_compaction(
                preparation=CompactionPreparation(
                    first_kept_entry_id=source_id,
                    messages_to_summarize=[
                        UserMessage(role="user", content="hello", timestamp=1.0)
                    ],
                    turn_prefix_messages=[],
                    is_split_turn=False,
                    tokens_before=10,
                ),
                model=_model(api=adapter.api),
                compaction_profile=CODING_COMPACTION_SUMMARY_PROFILE,
                turn_prefix_profile=CODING_TURN_PREFIX_SUMMARY_PROFILE,
                prepare_model_call=runtime.prepare,
            )
        finally:
            registry.unregister_api_adapters(adapter_source)

        assert adapter.transport_calls == 1
        assert len(result.model_input_snapshot_ids) == 1
        rebuilt = session.rebuild_model_input(result.model_input_snapshot_ids[0])
        assert rebuilt.snapshot.purpose == "compaction_history"
        await session.append_compaction(
            result.summary,
            result.first_kept_entry_id,
            result.tokens_before,
            model_input_snapshot_ids=result.model_input_snapshot_ids,
        )
        checkpoint = session.get_entries()[-1].payload
        assert checkpoint.derivation_verifiable is True
        assert checkpoint.model_input_snapshot_ids == result.model_input_snapshot_ids
        await runtime.dispose()

    asyncio.run(scenario())


def test_oversized_compaction_request_fails_before_snapshot_and_transport() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        source_id = session.get_entries()[0].record_id
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        adapter_source = "session-model-call-oversized-compaction-test"
        registry.register_api_adapter(adapter, source_id=adapter_source)
        try:
            with pytest.raises(
                SummaryCapacityPlanError,
                match="one conversation turn has no legal cut",
            ):
                await execute_transcript_compaction(
                    preparation=CompactionPreparation(
                        first_kept_entry_id=source_id,
                        messages_to_summarize=[
                            UserMessage(
                                role="user",
                                content="x" * 600_000,
                                timestamp=1.0,
                            )
                        ],
                        turn_prefix_messages=[],
                        is_split_turn=False,
                        tokens_before=150_000,
                    ),
                    model=_model(api=adapter.api),
                    compaction_profile=CODING_COMPACTION_SUMMARY_PROFILE,
                    turn_prefix_profile=CODING_TURN_PREFIX_SUMMARY_PROFILE,
                    prepare_model_call=runtime.prepare,
                )
        finally:
            registry.unregister_api_adapters(adapter_source)

        assert adapter.transport_calls == 0
        assert all(
            entry.kind != "model.input.prepared" for entry in session.get_entries()
        )
        outcomes = [
            entry.payload
            for entry in session.get_entries()
            if isinstance(entry.payload, ModelCallOutcome)
        ]
        assert outcomes == []
        await runtime.dispose()

    asyncio.run(scenario())


def test_batched_compaction_records_ordered_history_and_merge_lineage() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        source_id = session.get_entries()[0].record_id
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        adapter_source = "session-model-call-batched-compaction-test"
        registry.register_api_adapter(adapter, source_id=adapter_source)
        try:
            result = await execute_transcript_compaction(
                preparation=CompactionPreparation(
                    first_kept_entry_id=source_id,
                    messages_to_summarize=[
                        UserMessage(
                            role="user",
                            content=f"turn-{index}:" + character * 200_000,
                            timestamp=float(index),
                        )
                        for index, character in enumerate(
                            ("a", "b", "c"),
                            start=1,
                        )
                    ],
                    turn_prefix_messages=[],
                    is_split_turn=False,
                    tokens_before=150_000,
                ),
                model=_model(api=adapter.api, context_window=1_048_576),
                compaction_profile=CODING_COMPACTION_SUMMARY_PROFILE,
                turn_prefix_profile=CODING_TURN_PREFIX_SUMMARY_PROFILE,
                prepare_model_call=runtime.prepare,
            )
        finally:
            registry.unregister_api_adapters(adapter_source)

        assert adapter.transport_calls == 4
        assert len(result.model_input_snapshot_ids) == 4
        purposes = [
            session.rebuild_model_input(snapshot_id).snapshot.purpose
            for snapshot_id in result.model_input_snapshot_ids
        ]
        assert purposes == [
            "compaction_history",
            "compaction_history",
            "compaction_history",
            "compaction_merge",
        ]
        await session.append_compaction(
            result.summary,
            result.first_kept_entry_id,
            result.tokens_before,
            model_input_snapshot_ids=result.model_input_snapshot_ids,
        )
        checkpoint = session.get_entries()[-1].payload
        assert checkpoint.derivation_verifiable is True
        assert checkpoint.model_input_snapshot_ids == result.model_input_snapshot_ids
        outcomes = [
            entry.payload
            for entry in session.get_entries()
            if isinstance(entry.payload, ModelCallOutcome)
        ]
        assert len(outcomes) == 4
        await runtime.dispose()

    asyncio.run(scenario())


def test_split_turn_compaction_retains_single_ordered_model_input() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        source_id = session.get_entries()[0].record_id
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter(
            response_text=(
                "## Goal\nContinue the task\n## Constraints & Preferences\n- c\n"
                "## Progress\n### Done\n- [x] d\n### In Progress\n- [ ] i\n"
                "### Blocked\n- none\n## Key Decisions\n- k\n"
                "## Next Steps\n1. n\n## Critical Context\n- x\n\n---\n\n"
                "**Turn Context (split turn):**\n\n"
                "## Original Request\ncurrent turn\n## Early Progress\n- e\n"
                "## Context for Suffix\n- s"
            )
        )
        registry = get_default_api_registry()
        adapter_source = "session-model-call-split-compaction-test"
        registry.register_api_adapter(adapter, source_id=adapter_source)
        try:
            result = await execute_transcript_compaction(
                preparation=CompactionPreparation(
                    first_kept_entry_id=source_id,
                    messages_to_summarize=[
                        UserMessage(role="user", content="history", timestamp=1.0)
                    ],
                    turn_prefix_messages=[
                        UserMessage(role="user", content="prefix", timestamp=2.0)
                    ],
                    is_split_turn=True,
                    tokens_before=20,
                ),
                model=_model(api=adapter.api),
                compaction_profile=CODING_COMPACTION_SUMMARY_PROFILE,
                turn_prefix_profile=CODING_TURN_PREFIX_SUMMARY_PROFILE,
                prepare_model_call=runtime.prepare,
            )
        finally:
            registry.unregister_api_adapters(adapter_source)

        assert adapter.transport_calls == 1
        assert len(result.model_input_snapshot_ids) == 1
        assert [
            session.rebuild_model_input(snapshot_id).snapshot.purpose
            for snapshot_id in result.model_input_snapshot_ids
        ] == ["compaction_history"]
        await runtime.dispose()

    asyncio.run(scenario())


def test_branch_summary_v2_lineage_survives_selected_path_fork_and_reload() -> None:
    async def scenario() -> None:
        store = MemoryConversationStore(record_id=lambda record: record.record_id)
        source_key = ConversationKey("test", "branch-lineage-source")
        source_uow = await AgentTranscriptUnitOfWork.create(
            store,
            source_key,
            ConversationHeader(
                conversation_id=source_key.conversation_id,
                version=1,
                created_at="2026-08-15T00:00:00Z",
            ),
        )
        source = AgentTranscriptSession(transcript=source_uow)
        root_id = await source.append_message(
            UserMessage(role="user", content="root", timestamp=1.0)
        )
        runtime = _model_call_runtime(source, is_current=lambda: True)
        adapter = _PreparedAdapter()
        registry = get_default_api_registry()
        adapter_source = "session-model-call-branch-test"
        registry.register_api_adapter(adapter, source_id=adapter_source)
        try:
            output = await execute_branch_summary(
                [UserMessage(role="user", content="abandoned", timestamp=2.0)],
                model=_model(api=adapter.api),
                profile=CODING_BRANCH_SUMMARY_PROFILE,
                prepare_model_call=runtime.prepare,
            )
        finally:
            registry.unregister_api_adapters(adapter_source)

        assert output.error is None
        assert output.summary is not None
        assert len(output.model_input_snapshot_ids) == 1
        source_outcome = next(
            entry.payload
            for entry in source.get_entries()
            if isinstance(entry.payload, ModelCallOutcome)
            and output.model_input_snapshot_ids[0]
            in entry.payload.model_input_snapshot_ids
        )
        with pytest.raises(ModelInputIntegrityError, match="has purpose"):
            await source.append_compaction(
                "wrong lineage",
                root_id,
                1,
                model_input_snapshot_ids=output.model_input_snapshot_ids,
            )
        with pytest.raises(ModelInputIntegrityError, match="not uniquely available"):
            await source.branch_with_summary(
                root_id,
                "missing lineage",
                model_input_snapshot_ids=("missing",),
            )
        with pytest.raises(ModelInputIntegrityError, match="not uniquely available"):
            await source_uow.append(
                CONTEXT_BRANCH_SUMMARY_KIND,
                BranchContextSummary(
                    from_record_id=root_id,
                    summary="generic missing lineage",
                    model_input_snapshot_ids=("missing",),
                ),
            )
        invalid_record = AgentTranscriptRecordFactory().create(
            CONTEXT_BRANCH_SUMMARY_KIND,
            BranchContextSummary(
                from_record_id=root_id,
                summary="prebuilt missing lineage",
                model_input_snapshot_ids=("missing",),
            ),
            parent_id=source_uow.leaf_id,
        )
        with pytest.raises(ModelInputIntegrityError, match="not uniquely available"):
            await source_uow.commit(invalid_record)
        summary_id = await source.branch_with_summary(
            root_id,
            output.summary,
            model_input_snapshot_ids=output.model_input_snapshot_ids,
        )

        target_key = ConversationKey("test", "branch-lineage-fork")
        await source_uow.fork(
            target_key,
            ConversationHeader(
                conversation_id=target_key.conversation_id,
                version=1,
                created_at="2026-08-15T00:00:01Z",
            ),
            leaf_id=summary_id,
        )
        reloaded = await AgentTranscriptUnitOfWork.load(
            store,
            target_key,
            leaf_id=summary_id,
        )
        forked = AgentTranscriptSession(transcript=reloaded)
        rebuilt = forked.rebuild_model_input(output.model_input_snapshot_ids[0])
        assert rebuilt.snapshot.purpose == "branch_summary"
        branch_summary = forked.get_entry(summary_id)
        assert branch_summary is not None
        assert branch_summary.payload.derivation_verifiable is True
        assert branch_summary.payload.model_input_snapshot_ids == (
            output.model_input_snapshot_ids
        )
        forked_outcome = next(
            entry.payload
            for entry in forked.get_entries()
            if isinstance(entry.payload, ModelCallOutcome)
            and output.model_input_snapshot_ids[0]
            in entry.payload.model_input_snapshot_ids
        )
        assert forked_outcome == source_outcome
        await runtime.dispose()

    asyncio.run(scenario())
