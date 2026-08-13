from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.capabilities import (
    CapabilityCompositionRuntime,
    bind_capability_composition_runtime,
    standard_capability_composition_plan,
)
from loushang.harness.config.agent import (
    CompactionSettings,
    ControlConfig,
    RetrySettings,
    SettingsManager,
)
from loushang.harness.conversation import ConversationKey, MemoryConversationStore
from loushang.harness.runtime import CancellationSignal, RuntimeProfileResolver
from loushang.harness.session import AgentProductSession
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptProfile,
    AgentTranscriptRuntimeBinding,
    AgentTranscriptSessionFactory,
    BranchSummaryOutput,
    CompactionHookDecision,
    CompactionHookRequest,
    CompactionPreparation,
    CompactionResult,
    ContextCompactionCheckpoint,
    ProductTranscriptSession,
)


class _ContractTranscriptSession(ProductTranscriptSession[str, str]):
    _factory: ClassVar[AgentTranscriptSessionFactory[str, str]]

    @classmethod
    def _session_factory(cls) -> AgentTranscriptSessionFactory[str, str]:
        return cls._factory

    def _fork_binding_input(self) -> str:
        return self._lifecycle_session.product_binding


@dataclass
class _Footer:
    available_provider_count: int | None = None
    disposed: bool = False

    def set_extension_status(self, name: str, status: str | None) -> None:
        del name, status

    def set_available_provider_count(self, count: int) -> None:
        self.available_provider_count = count

    def dispose(self) -> None:
        self.disposed = True


class _ContractProductSession(AgentProductSession):
    def __init__(
        self,
        *,
        product_id: str,
        transcript: _ContractTranscriptSession,
        capability_runtime: CapabilityCompositionRuntime,
        reserve_tokens: int,
        compact_percent: float,
    ) -> None:
        self.product_id = product_id
        self.executor_calls: list[tuple[str, str | None]] = []
        self.hook_calls: list[tuple[str, str, object]] = []
        self.footer = _Footer()

        async def execute_compaction(
            *,
            preparation: CompactionPreparation,
            model: object,
            headers: Mapping[str, str] | None,
            signal: object | None,
            custom_instructions: str | None = None,
        ) -> CompactionResult:
            assert getattr(model, "id", None) == f"{product_id}-model"
            assert headers is None
            assert signal is self.agent.signal
            self.executor_calls.append((product_id, custom_instructions))
            return CompactionResult(
                summary=f"{product_id} summary",
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
                details={"product": product_id},
            )

        async def execute_branch_summary(
            entries: object,
            signal: CancellationSignal,
            **options: object,
        ) -> BranchSummaryOutput:
            del entries, signal, options
            raise AssertionError("branch summary is outside this contract")

        async def retry_sleep(delay_ms: int, signal: CancellationSignal) -> None:
            del delay_ms, signal

        super().__init__(
            agent=Agent(
                initial_state={
                    "system_prompt": f"{product_id} prompt",
                    "model": _model(product_id),
                    "thinking_level": "off",
                }
            ),
            session_manager=transcript,
            capability_runtime=capability_runtime,
            execute_compaction=execute_compaction,
            execute_branch_summary=execute_branch_summary,
            get_changelog=lambda cwd, args: (cwd, args),
            copy_to_clipboard=lambda text: text,
            retry_sleep=retry_sleep,
            footer_data_provider=self.footer,
            settings_manager=SettingsManager(
                ControlConfig(
                    compaction=CompactionSettings(
                        enabled=True,
                        reserve_tokens=reserve_tokens,
                        compact_percent=compact_percent,
                        keep_recent_tokens=1,
                    ),
                    retry=RetrySettings(
                        enabled=False,
                        max_retries=0,
                        base_delay_ms=0,
                    ),
                )
            ),
        )

    async def _before_product_compaction(
        self,
        request: CompactionHookRequest,
    ) -> CompactionHookDecision | None:
        self.hook_calls.append(("before", request.reason, request.custom_instructions))
        return None

    async def _after_product_compaction(
        self,
        result: CompactionResult,
        record_id: str,
        from_hook: bool,
    ) -> None:
        self.hook_calls.append(("after", result.summary, (record_id, from_hook)))


def test_agent_product_sessions_keep_compaction_strategy_and_state_isolated(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        research_transcript = await _new_transcript(
            tmp_path,
            product_id="research",
        )
        design_transcript = await _new_transcript(
            tmp_path,
            product_id="design",
        )
        research_capabilities = _capability_runtime("research")
        design_capabilities = _capability_runtime("design")
        research = _ContractProductSession(
            product_id="research",
            transcript=research_transcript,
            capability_runtime=research_capabilities,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        design = _ContractProductSession(
            product_id="design",
            transcript=design_transcript,
            capability_runtime=design_capabilities,
            reserve_tokens=2_222,
            compact_percent=72.0,
        )
        research_events: list[dict[str, object]] = []
        design_events: list[dict[str, object]] = []
        research.subscribe(research_events.append)
        design.subscribe(design_events.append)

        assert research.session_control is research
        assert design.session_control is design
        assert research.session_id == "research-session"
        assert design.session_id == "design-session"
        assert research.get_active_tool_names() == []
        assert design.get_active_tool_names() == []
        _assert_no_composed_runtime_mirrors(research)
        _assert_no_composed_runtime_mirrors(design)

        research_result = await research.compact("research-only")

        assert isinstance(research_result, CompactionResult)
        assert research_result.summary == "research summary"
        assert research.executor_calls == [("research", "research-only")]
        assert research.hook_calls[0] == (
            "before",
            "manual",
            "research-only",
        )
        assert research.hook_calls[1][0:2] == (
            "after",
            "research summary",
        )
        assert _checkpoint_summaries(research_transcript) == ["research summary"]
        assert _checkpoint_summaries(design_transcript) == []
        assert design.executor_calls == []
        assert design.hook_calls == []
        assert design_events == []
        _assert_compaction_events(
            research_events,
            product_id="research",
            session_id="research-session",
            reserve_tokens=1_111,
            compact_percent=61.0,
        )

        await research.dispose()

        assert research.footer.disposed is True
        assert research_capabilities.binding.is_closed is True
        assert design_capabilities.binding.is_closed is False
        assert disposed_transcripts == ["research-session"]

        design_result = await design.compact("design-only")

        assert isinstance(design_result, CompactionResult)
        assert design_result.summary == "design summary"
        assert design.executor_calls == [("design", "design-only")]
        assert design.hook_calls[0] == ("before", "manual", "design-only")
        assert design.hook_calls[1][0:2] == ("after", "design summary")
        assert _checkpoint_summaries(design_transcript) == ["design summary"]
        assert _checkpoint_summaries(research_transcript) == ["research summary"]
        _assert_compaction_events(
            design_events,
            product_id="design",
            session_id="design-session",
            reserve_tokens=2_222,
            compact_percent=72.0,
        )

        await design.dispose()

        assert design.footer.disposed is True
        assert design_capabilities.binding.is_closed is True
        assert disposed_transcripts == ["research-session", "design-session"]

    asyncio.run(scenario())


def _bind_transcript_factory(disposed: list[str]) -> None:
    async def bind_runtime(context, binding: str):
        assert context.persist is False
        conversation_id = context.header.conversation_id

        async def dispose() -> None:
            disposed.append(conversation_id)

        return AgentTranscriptRuntimeBinding(
            store=MemoryConversationStore(record_id=lambda record: record.record_id),
            key=ConversationKey("memory", conversation_id),
            profile=AgentTranscriptProfile.default(),
            product_binding=binding,
            dispose=dispose,
        )

    lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
    _ContractTranscriptSession._factory = AgentTranscriptSessionFactory(
        lifecycle=lifecycle,
        resolve_binding_input=lambda persist: "memory" if not persist else "file",
        header_metadata=lambda binding: {"productBinding": binding},
    )


async def _new_transcript(
    tmp_path: Path,
    *,
    product_id: str,
) -> _ContractTranscriptSession:
    transcript = await _ContractTranscriptSession.in_memory(
        cwd=tmp_path / product_id,
        session_id=f"{product_id}-session",
    )
    await transcript.append_message(
        UserMessage(
            role="user",
            content=f"{product_id} context that should be summarized",
            timestamp=1.0,
        )
    )
    await transcript.append_message(
        AssistantMessage(
            endpoint="test-endpoint",
            role="assistant",
            content=[TextPart(type="text", text=f"{product_id} recent reply")],
            api="test",
            provider="test",
            model=f"{product_id}-model",
            response_id=None,
            usage=Usage(
                input=20,
                output=10,
                cache_read=0,
                cache_write=0,
                total_tokens=30,
                cost=None,
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=2.0,
        )
    )
    return transcript


def _capability_runtime(product_id: str) -> CapabilityCompositionRuntime:
    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id=product_id)
    )
    return bind_capability_composition_runtime(profile)


def _model(product_id: str) -> Model:
    return Model(
        id=f"{product_id}-model",
        name=f"{product_id.title()} Model",
        provider="test",
        endpoint="test",
        capabilities=Capabilities(
            input=("text",),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


def _checkpoint_summaries(
    transcript: _ContractTranscriptSession,
) -> list[str]:
    return [
        entry.payload.summary
        for entry in transcript.get_entries()
        if isinstance(entry.payload, ContextCompactionCheckpoint)
    ]


def _assert_compaction_events(
    events: list[dict[str, object]],
    *,
    product_id: str,
    session_id: str,
    reserve_tokens: int,
    compact_percent: float,
) -> None:
    compaction_events = [
        event
        for event in events
        if event["type"] in {"compaction_start", "compaction_end"}
    ]
    assert [event["type"] for event in compaction_events] == [
        "compaction_start",
        "compaction_end",
    ]
    assert all(event["product_id"] == product_id for event in compaction_events)
    assert all(event["session_id"] == session_id for event in compaction_events)
    usage = compaction_events[0]["usage"]
    assert isinstance(usage, dict)
    assert usage["reserve_tokens"] == reserve_tokens
    assert usage["compact_percent"] == compact_percent


def _assert_no_composed_runtime_mirrors(session: AgentProductSession) -> None:
    mirrored_runtime_names = {
        "_bash_runtime",
        "_command_controller",
        "_compaction_capability",
        "_compaction_runtime",
        "_diagnostics_bridge",
        "_extension_binding",
        "_extension_event_sink",
        "_extension_input_runtime",
        "_extension_message_controller",
        "_identity_binding",
        "_maintenance_binding",
        "_model_binding",
        "_navigation_runtime",
        "_resource_refresh_runtime",
        "_resource_watch_controller",
        "_retry_runtime",
        "_selection_runtime",
        "_session_inspector",
        "_session_runtime",
        "_tool_controller",
    }
    assert mirrored_runtime_names.isdisjoint(vars(session))
