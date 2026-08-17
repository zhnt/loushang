from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

import pytest

from loushang.agent import Agent, ModelCallPreparation
from loushang.ai import Context, stream
from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.prepared_request import PreparedModelRequest, PreparedRequestLimits
from loushang.ai.provider.protocol import ProviderRequest
from loushang.ai.types import AssistantMessage, UserMessage
from loushang.coding.compaction.profiles import (
    CODING_BRANCH_SUMMARY_PROFILE,
    CODING_COMPACTION_SUMMARY_PROFILE,
    CODING_TURN_PREFIX_SUMMARY_PROFILE,
)
from loushang.harness.capabilities import (
    MODEL_INPUT_PREPARATION_REQUIREMENT,
    RegistrationInventoryEntry,
    RuntimeCapabilityGraphBinder,
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
from loushang.harness.session.model_call import (
    SessionModelCallCapabilityConsumer,
    SessionModelCallRuntime,
    build_session_model_call_capability_binding,
)
from loushang.harness.transcript import (
    CONTEXT_BRANCH_SUMMARY_KIND,
    MODEL_CALL_OUTCOME_KIND,
    AgentTranscriptRecordFactory,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    BranchContextSummary,
    CompactionPreparation,
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


async def _transcript_session() -> AgentTranscriptSession:
    transcript = await AgentTranscriptUnitOfWork.create(
        MemoryConversationStore(record_id=lambda record: record.record_id),
        ConversationKey("test", "session-model-call"),
        ConversationHeader(
            conversation_id="session-model-call",
            version=1,
            created_at="2026-08-15T00:00:00Z",
        ),
    )
    session = AgentTranscriptSession(transcript=transcript)
    await session.append_message(
        UserMessage(role="user", content="hello", timestamp=1.0)
    )
    return session


class _ModelCallTestRoot:
    def __init__(
        self,
        session: AgentTranscriptSession,
        *,
        is_current: Callable[[], bool],
        registrations: tuple[RegistrationInventoryEntry, ...],
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
                    self._binding.plan,
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
) -> _ModelCallTestRoot:
    return _ModelCallTestRoot(
        session,
        is_current=is_current,
        registrations=registrations,
    )


class _PreparedAdapter:
    api = "session-model-call-test"

    def __init__(
        self,
        *,
        retry_first: bool = False,
        terminal_error: bool = False,
    ) -> None:
        self.transport_calls = 0
        self.retry_first = retry_first
        self.terminal_error = terminal_error

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


def test_current_session_prepares_and_rebuilds_main_model_call() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
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
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        ).snapshot()
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


def test_provider_retry_commits_each_attempt_with_one_invocation_identity() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter(retry_first=True)
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
        projected = session.get_model_call_invocations()
        assert len(projected) == 1
        assert projected[0].state == "completed"
        assert projected[0].outcome == outcome
        for snapshot in snapshots:
            assert session.rebuild_model_input(snapshot.snapshot_id).snapshot == snapshot
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


def test_capacity_preflight_records_failed_outcome_without_snapshot_or_transport() -> None:
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
        assert session.rebuild_model_input(snapshots[0].snapshot_id).snapshot == (
            snapshots[0]
        )
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


def test_split_turn_compaction_retains_both_ordered_model_inputs() -> None:
    async def scenario() -> None:
        session = await _transcript_session()
        source_id = session.get_entries()[0].record_id
        runtime = _model_call_runtime(session, is_current=lambda: True)
        adapter = _PreparedAdapter()
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

        assert adapter.transport_calls == 2
        assert len(result.model_input_snapshot_ids) == 2
        assert [
            session.rebuild_model_input(snapshot_id).snapshot.purpose
            for snapshot_id in result.model_input_snapshot_ids
        ] == ["compaction_history", "compaction_turn_prefix"]
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
