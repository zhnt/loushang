"""Read-only operational inspection for an optional Agent transcript session.

Products bind their active Agent and selected runtime state through callbacks.
This module derives common state, context usage, and transcript statistics;
Product wire formats and display projections remain outside Harness.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

from loushang.agent.types import AgentMessage
from loushang.ai.json_codec import deserialize_message
from loushang.ai.model import ModelSelection
from loushang.ai.types import AssistantMessage
from loushang.harness.runtime.types import RunState
from loushang.harness.session.model_call import (
    project_model_request_options,
    project_model_tools,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_PREPARED_KIND,
    AgentTranscriptInspector,
    AgentTranscriptRecord,
    AgentTranscriptSession,
    ModelCallOutcome,
    ProviderContextAnchor,
    build_context_usage_snapshot,
    calculate_context_tokens,
    estimate_context_tokens,
    measure_replay_context_surface,
    measure_structural_envelope_fingerprint,
    project_context_from_provider_anchor,
    project_model_call_usage,
)

TokenUsageTotalsSource = Literal[
    "attempt_usage_facts",
    "logical_outcome_derived",
    "legacy_derived",
    "mixed_derived",
]
_PROVIDER_CONTEXT_ANCHOR_PURPOSES = frozenset(
    {"main", "main_turn", "continuation", "retry"}
)


class AgentStateInspectionPort(Protocol):
    """Read-only Agent state values needed for common session inspection."""

    @property
    def is_streaming(self) -> bool: ...

    @property
    def messages(self) -> list[AgentMessage]: ...


class AgentInspectionPort(Protocol):
    """Public Agent values required by the optional session profile."""

    @property
    def model(self) -> object: ...

    @property
    def thinking_level(self) -> str: ...

    @property
    def state(self) -> AgentStateInspectionPort: ...


@dataclass(frozen=True)
class AgentSessionState:
    """Common active-Agent state without a Product display projection."""

    run: RunState
    steering: list[str] = field(default_factory=list)
    follow_up: list[str] = field(default_factory=list)
    active_tool_names: list[str] = field(default_factory=list)
    is_compacting: bool = False
    is_retrying: bool = False
    thinking_level: str = "off"
    model_selection: ModelSelection | None = None


@dataclass(frozen=True)
class ContextUsage:
    """Context-budget and transcript-count observation for one active branch."""

    message_count: int
    assistant_message_count: int
    user_message_count: int
    tool_call_count: int
    tool_result_count: int
    custom_message_count: int
    estimated_context_tokens: int | None
    has_compaction: bool
    branch_depth: int
    leaf_entry_id: str | None
    tokens: int | None = None
    context_window: int | None = None
    percent: float | None = None
    reserve_tokens: int = 0
    compact_percent: float = 100.0
    keep_recent_tokens: int | None = None
    percent_threshold_tokens: int | None = None
    reserve_threshold_tokens: int | None = None
    threshold_tokens: int | None = None
    threshold_reason: Literal["compact_percent", "reserve_tokens"] | None = None
    source: Literal[
        "assistant_usage",
        "provider_anchor",
        "estimated_from_last_usage",
        "estimated",
        "unknown",
    ] = "unknown"
    last_usage_index: int | None = None
    stale_after_compaction: bool = False
    compactable: bool = False
    reason: str | None = None
    authority: Literal["provider_usage", "local_estimator", "unknown"] = "unknown"
    accuracy: Literal["projected", "estimated", "unknown"] = "unknown"
    transcript_revision: int | None = None
    leaf_id: str | None = None
    estimator_id: str | None = None
    surface_fingerprint: str | None = None
    provider_anchor: ProviderContextAnchor | None = None
    structural_envelope_fingerprint: str | None = None
    structural_envelope_status: Literal[
        "matched", "mismatched", "unavailable"
    ] = "unavailable"


@dataclass(frozen=True)
class TokenUsageTotals:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total: int = 0
    source: TokenUsageTotalsSource = "legacy_derived"
    incomplete_attempts: bool = True


@dataclass(frozen=True)
class SessionStats:
    session_id: str
    session_name: str | None
    entry_count: int
    message_count: int
    custom_message_count: int
    active_tool_count: int
    is_retrying: bool
    is_compacting: bool
    has_diagnostics: bool
    branch_count: int
    last_model_selection: ModelSelection | None
    context_usage: ContextUsage | None
    tokens: TokenUsageTotals = field(default_factory=TokenUsageTotals)


@dataclass
class AgentSessionInspector:
    """Build common state and transcript observations for one live Agent."""

    agent: AgentInspectionPort
    session: AgentTranscriptSession
    get_session_id: Callable[[], str]
    get_session_name: Callable[[], str | None]
    get_active_tool_names: Callable[[], list[str]]
    is_retrying: Callable[[], bool]
    is_compacting: Callable[[], bool]
    get_last_diagnostics: Callable[[int], Sequence[object]]
    get_model_selection: Callable[[], ModelSelection | None]
    is_host_running: Callable[[], bool] | None = None
    get_compaction_reserve_tokens: Callable[[], int] = lambda: 0
    get_compaction_compact_percent: Callable[[], float] = lambda: 100.0
    get_compaction_keep_recent_tokens: Callable[[], int | None] = lambda: None
    _transcript: AgentTranscriptInspector = field(init=False, repr=False)
    _provider_anchor_cache_key: tuple[int, str | None] | None = field(
        init=False,
        default=None,
        repr=False,
    )
    _provider_anchor_cache: ProviderContextAnchor | None = field(
        init=False,
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._transcript = AgentTranscriptInspector(self.session)

    def get_state(
        self, *, steering: list[str], follow_up: list[str]
    ) -> AgentSessionState:
        is_running = (
            self.is_host_running()
            if self.is_host_running is not None
            else self.agent.state.is_streaming
        )
        return AgentSessionState(
            run=RunState(status="running" if is_running else "idle"),
            steering=steering,
            follow_up=follow_up,
            active_tool_names=self.get_active_tool_names(),
            is_compacting=self.is_compacting(),
            is_retrying=self.is_retrying(),
            thinking_level=self.agent.thinking_level,
            model_selection=self.get_model_selection(),
        )

    def get_context_usage(self) -> ContextUsage:
        context = self.session.build_context()
        messages = list(context.messages)
        branch_records = self.session.get_branch()
        branch_entries: list[object] = list(branch_records)
        transcript_revision = len(self.session.get_entries())
        leaf_id = self.session.get_leaf_id()
        counts = self._transcript.message_counts()
        snapshot = build_context_usage_snapshot(
            messages,
            branch_entries,
            self.agent.model,
            reserve_tokens=self.get_compaction_reserve_tokens(),
            compact_percent=self.get_compaction_compact_percent(),
            keep_recent_tokens=self.get_compaction_keep_recent_tokens(),
            transcript_revision=transcript_revision,
            leaf_id=leaf_id,
        )
        provider_anchor = self._get_provider_context_anchor(
            branch_records,
            transcript_revision=transcript_revision,
            leaf_id=leaf_id,
        )
        if provider_anchor is not None and self._anchor_matches_active_model(
            provider_anchor
        ):
            snapshot = project_context_from_provider_anchor(
                snapshot,
                provider_anchor,
                measure_replay_context_surface(messages),
                structural_envelope_fingerprint=(
                    self._current_structural_envelope_fingerprint()
                ),
            )
        else:
            snapshot = replace(snapshot, provider_anchor=provider_anchor)
        estimated_context_tokens = (
            estimate_context_tokens(messages).tokens if messages else 0
        )
        return ContextUsage(
            message_count=counts.message_count,
            assistant_message_count=counts.assistant_message_count,
            user_message_count=counts.user_message_count,
            tool_call_count=counts.tool_call_count,
            tool_result_count=counts.tool_result_count,
            custom_message_count=counts.application_message_count,
            estimated_context_tokens=estimated_context_tokens,
            has_compaction=self._transcript.has_compaction_checkpoint(),
            branch_depth=len(branch_entries),
            leaf_entry_id=self.session.get_leaf_id(),
            tokens=snapshot.tokens,
            context_window=snapshot.context_window,
            percent=snapshot.percent,
            reserve_tokens=snapshot.reserve_tokens,
            compact_percent=snapshot.compact_percent,
            keep_recent_tokens=snapshot.keep_recent_tokens,
            percent_threshold_tokens=snapshot.percent_threshold_tokens,
            reserve_threshold_tokens=snapshot.reserve_threshold_tokens,
            threshold_tokens=snapshot.threshold_tokens,
            threshold_reason=snapshot.threshold_reason,
            source=snapshot.source,
            last_usage_index=snapshot.last_usage_index,
            stale_after_compaction=snapshot.stale_after_compaction,
            compactable=snapshot.compactable,
            reason=snapshot.reason,
            authority=snapshot.authority,
            accuracy=snapshot.accuracy,
            transcript_revision=snapshot.transcript_revision,
            leaf_id=snapshot.leaf_id,
            estimator_id=snapshot.estimator_id,
            surface_fingerprint=snapshot.surface_fingerprint,
            provider_anchor=snapshot.provider_anchor,
            structural_envelope_fingerprint=(
                snapshot.structural_envelope_fingerprint
            ),
            structural_envelope_status=snapshot.structural_envelope_status,
        )

    def _get_provider_context_anchor(
        self,
        branch_entries: Sequence[AgentTranscriptRecord],
        *,
        transcript_revision: int,
        leaf_id: str | None,
    ) -> ProviderContextAnchor | None:
        cache_key = (transcript_revision, leaf_id)
        if self._provider_anchor_cache_key == cache_key:
            return self._provider_anchor_cache
        anchor = self._derive_provider_context_anchor(branch_entries)
        self._provider_anchor_cache_key = cache_key
        self._provider_anchor_cache = anchor
        return anchor

    def _anchor_matches_active_model(self, anchor: ProviderContextAnchor) -> bool:
        model = self.agent.model
        return (
            anchor.provider_id == getattr(model, "provider_id", None)
            and anchor.endpoint_id == getattr(model, "endpoint_id", None)
            and anchor.api_id == getattr(model, "api", None)
            and anchor.model_id == getattr(model, "id", None)
        )

    def _current_structural_envelope_fingerprint(self) -> str | None:
        system_prompt = getattr(self.agent, "system_prompt", None)
        tools = getattr(self.agent, "tools", None)
        get_effective_call_options = getattr(
            self.agent, "get_effective_call_options", None
        )
        model = self.agent.model
        if (
            not isinstance(system_prompt, str)
            or tools is None
            or not callable(get_effective_call_options)
        ):
            return None
        call_options = get_effective_call_options()
        return measure_structural_envelope_fingerprint(
            system_prompt=system_prompt,
            tools=project_model_tools(tools),
            request_options=project_model_request_options(call_options),
            provider_id=str(getattr(model, "provider_id", "")),
            endpoint_id=str(getattr(model, "endpoint_id", "")),
            api_id=str(getattr(model, "api", "")),
            model_id=str(getattr(model, "id", "")),
        )

    def _derive_provider_context_anchor(
        self,
        branch_entries: Sequence[AgentTranscriptRecord],
    ) -> ProviderContextAnchor | None:
        ledger = project_model_call_usage(tuple(branch_entries))
        for attempt in reversed(ledger.attempts):
            if not attempt.terminal:
                continue
            provider_prompt_tokens = (
                attempt.usage.input
                + attempt.usage.cache_read
                + attempt.usage.cache_write
            )
            if provider_prompt_tokens <= 0:
                continue
            rebuilt = self.session.rebuild_model_input(
                attempt.model_input_snapshot_id
            )
            snapshot = rebuilt.snapshot
            if snapshot.purpose not in _PROVIDER_CONTEXT_ANCHOR_PURPOSES:
                continue
            raw_messages = rebuilt.logical_input.get("messages")
            if not isinstance(raw_messages, list):
                continue
            messages = [
                deserialize_message(dict(message))
                for message in raw_messages
                if isinstance(message, Mapping)
            ]
            if len(messages) != len(raw_messages):
                continue
            sampled_surface = measure_replay_context_surface(messages)
            sampled_envelope = measure_structural_envelope_fingerprint(
                system_prompt=rebuilt.logical_input["system_prompt"],
                tools=rebuilt.logical_input["tools"],
                request_options=rebuilt.logical_input["request_options"],
                provider_id=snapshot.provider_id,
                endpoint_id=snapshot.endpoint_id,
                api_id=snapshot.api_id,
                model_id=snapshot.model_id,
            )
            return ProviderContextAnchor(
                invocation_id=attempt.invocation_id,
                attempt=attempt.attempt,
                model_input_snapshot_id=attempt.model_input_snapshot_id,
                provider_prompt_tokens=provider_prompt_tokens,
                sampled_prepared_payload_hash=rebuilt.prepared_payload_hash,
                sampled_surface_tokens=sampled_surface.tokens,
                sampled_surface_fingerprint=sampled_surface.surface_fingerprint,
                source_revision=snapshot.source_revision,
                commit_revision=snapshot.commit_revision,
                provider_id=snapshot.provider_id,
                endpoint_id=snapshot.endpoint_id,
                api_id=snapshot.api_id,
                model_id=snapshot.model_id,
                sampled_structural_envelope_fingerprint=sampled_envelope,
            )
        return None

    def build_session_stats(self) -> SessionStats:
        context_usage = self.get_context_usage()
        counts = self._transcript.message_counts()
        branch_entries = list(self.session.get_branch())
        return SessionStats(
            session_id=self.get_session_id(),
            session_name=self.get_session_name(),
            entry_count=len(self.session.get_entries()),
            message_count=context_usage.message_count,
            custom_message_count=counts.application_message_count,
            active_tool_count=len(self.get_active_tool_names()),
            is_retrying=self.is_retrying(),
            is_compacting=self.is_compacting(),
            has_diagnostics=bool(self.get_last_diagnostics(1)),
            branch_count=self._transcript.branch_leaf_count(),
            last_model_selection=self.get_model_selection(),
            context_usage=context_usage,
            tokens=_build_token_usage_totals(branch_entries),
        )

    def get_user_messages_for_forking(self) -> list[dict[str, str]]:
        return [
            {"entry_id": candidate.record_id, "text": candidate.text}
            for candidate in self._transcript.fork_candidates()
        ]

    def get_entry_text(self, entry_id: str) -> str | None:
        return self._transcript.entry_text(entry_id)

    def get_last_assistant_text(self) -> str | None:
        texts = self.get_recent_assistant_texts()
        return texts[0] if texts else None

    def get_recent_assistant_texts(self) -> tuple[str, ...]:
        return self._transcript.recent_assistant_texts(self.agent.state.messages)


def _build_token_usage_totals(
    branch_entries: Sequence[AgentTranscriptRecord],
) -> TokenUsageTotals:
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    total_tokens = 0
    ledger = project_model_call_usage(tuple(branch_entries))
    fact_invocations = {attempt.invocation_id for attempt in ledger.attempts}
    terminal_fact_snapshots: dict[str, set[str]] = {}
    for attempt in ledger.attempts:
        if attempt.terminal:
            terminal_fact_snapshots.setdefault(attempt.invocation_id, set()).add(
                attempt.model_input_snapshot_id
            )
    fact_usage = ledger.usage
    input_tokens += fact_usage.input
    output_tokens += fact_usage.output
    cache_read_tokens += fact_usage.cache_read
    cache_write_tokens += fact_usage.cache_write
    total_tokens += calculate_context_tokens(fact_usage)
    fact_outcome_invocations: set[str] = set()
    fallback_outcome_count = 0
    covered_assistant_indexes = _outcome_covered_assistant_indexes(branch_entries)
    legacy_count = 0

    for index, entry in enumerate(branch_entries):
        payload = getattr(entry, "payload", None)
        if (
            getattr(entry, "kind", None) == MODEL_CALL_OUTCOME_KIND
            and isinstance(payload, ModelCallOutcome)
        ):
            if payload.invocation_id in fact_invocations:
                fact_outcome_invocations.add(payload.invocation_id)
                continue
            fallback_outcome_count += 1
            usage = payload.usage
        elif (
            index not in covered_assistant_indexes
            and getattr(entry, "kind", None) == AGENT_MESSAGE_KIND
            and isinstance(payload, AssistantMessage)
            and payload.stop_reason not in {"aborted", "error"}
        ):
            legacy_count += 1
            usage = payload.usage
        else:
            continue
        input_tokens += int(getattr(usage, "input", 0) or 0)
        output_tokens += int(getattr(usage, "output", 0) or 0)
        cache_read_tokens += int(getattr(usage, "cache_read", 0) or 0)
        cache_write_tokens += int(getattr(usage, "cache_write", 0) or 0)
        total_tokens += calculate_context_tokens(usage)

    facts_complete = ledger.complete
    if facts_complete:
        facts_complete = fact_invocations == fact_outcome_invocations and all(
            set(outcome.model_input_snapshot_ids)
            == terminal_fact_snapshots.get(outcome.invocation_id, set())
            for entry in branch_entries
            if getattr(entry, "kind", None) == MODEL_CALL_OUTCOME_KIND
            and isinstance((outcome := getattr(entry, "payload", None)), ModelCallOutcome)
            and outcome.invocation_id in fact_invocations
        )
    has_facts = bool(ledger.attempts)
    has_fallback = bool(fallback_outcome_count or legacy_count)
    return TokenUsageTotals(
        input=input_tokens,
        output=output_tokens,
        cache_read=cache_read_tokens,
        cache_write=cache_write_tokens,
        total=total_tokens,
        source=(
            "mixed_derived"
            if has_facts and has_fallback
            else "attempt_usage_facts"
            if has_facts
            else "mixed_derived"
            if fallback_outcome_count and legacy_count
            else "logical_outcome_derived"
            if fallback_outcome_count
            else "legacy_derived"
        ),
        incomplete_attempts=(not facts_complete or has_fallback),
    )


def _outcome_covered_assistant_indexes(
    entries: Sequence[AgentTranscriptRecord],
) -> set[int]:
    """Find legacy assistant projections already represented by durable outcomes."""

    snapshot_indexes = {
        snapshot_id: index
        for index, entry in enumerate(entries)
        if getattr(entry, "kind", None) == MODEL_INPUT_PREPARED_KIND
        and isinstance((snapshot_id := getattr(entry.payload, "snapshot_id", None)), str)
    }
    assistant_indexes = [
        index
        for index, entry in enumerate(entries)
        if getattr(entry, "kind", None) == AGENT_MESSAGE_KIND
        and isinstance(getattr(entry, "payload", None), AssistantMessage)
    ]
    covered: set[int] = set()
    for outcome_index, entry in enumerate(entries):
        outcome = getattr(entry, "payload", None)
        if (
            getattr(entry, "kind", None) != MODEL_CALL_OUTCOME_KIND
            or not isinstance(outcome, ModelCallOutcome)
            or outcome.disposition != "completed"
        ):
            continue
        attempt_indexes = [
            snapshot_indexes[snapshot_id]
            for snapshot_id in outcome.model_input_snapshot_ids
            if snapshot_id in snapshot_indexes
        ]
        if not attempt_indexes:
            continue
        first_attempt_index = min(attempt_indexes)
        position = bisect_left(assistant_indexes, outcome_index)
        if position and assistant_indexes[position - 1] > first_attempt_index:
            covered.add(assistant_indexes[position - 1])
    return covered


__all__ = [
    "AgentInspectionPort",
    "AgentStateInspectionPort",
    "AgentSessionInspector",
    "AgentSessionState",
    "ContextUsage",
    "SessionStats",
    "TokenUsageTotals",
]
