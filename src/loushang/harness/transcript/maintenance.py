"""Compaction lifecycle for the optional Agent transcript profile.

The profile owns durable conversation facts. Adjacent ``context_usage`` owns
context-budget observations; this module owns compaction decisions and
lifecycle mechanics around those facts. Product code supplies policy and
presentation or diagnostic adapters.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Literal, Protocol

from loushang.agent.types import AgentMessage
from loushang.ai.types import AssistantMessage
from loushang.harness.context.compaction import CompactionCoordinator
from loushang.harness.conversation import ConversationRecord
from loushang.harness.events import (
    CompactionReason,
    ContextCompactionCompleted,
    ContextCompactionStarted,
    SessionRuntimeEventPayload,
)
from loushang.harness.transcript.context_usage import (
    ContextUsageSnapshot,
    build_context_usage_snapshot,
    calculate_context_tokens,
    current_context_usage,
    estimate_context_tokens,
    estimate_message_tokens,
    has_post_compaction_usage,
    latest_compaction_entry,
    model_context_window,
)
from loushang.harness.transcript.types import AgentTranscriptRecord


@dataclass(frozen=True)
class CompactionDecision:
    """The profile-neutral outcome of checking one context budget."""

    action: Literal["none", "threshold", "overflow"]
    usage: ContextUsageSnapshot
    will_retry: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class CompactionResult:
    """A strategy-produced summary ready to become a transcript checkpoint."""

    summary: str
    first_kept_entry_id: str
    tokens_before: int
    details: object | None = None


class CompactionAborted(RuntimeError):
    """A Product hook deliberately stopped compaction before commit."""


@dataclass(frozen=True)
class AutoCompactionOutcome:
    """Explicit control result for one automatic-compaction check."""

    result: CompactionResult | None = None
    should_continue: bool = False


@dataclass(frozen=True)
class CompactionStatus:
    is_compacting: bool
    is_branch_summarizing: bool = False
    last_reason: str | None = None
    last_result: CompactionResult | None = None
    last_error: str | None = None
    aborted: bool = False
    last_started_at: str | None = None
    last_completed_at: str | None = None
    last_stage: str | None = None
    last_tokens_before: int | None = None
    last_tokens_after: int | None = None
    last_summary_mode: Literal["stream", "complete", "hook"] | None = None
    last_succeeded: bool | None = None
    context_window: int | None = None
    reserve_tokens: int | None = None


@dataclass(frozen=True)
class CompactionPlan:
    previous_compaction_id: str | None
    previous_first_kept_entry_id: str | None
    first_kept_entry_id: str
    summarized_entry_ids: tuple[str, ...]
    turn_prefix_entry_ids: tuple[str, ...]
    kept_entry_ids: tuple[str, ...]
    is_split_turn: bool
    tokens_before: int
    keep_recent_tokens: int


@dataclass(frozen=True)
class CompactionPreparation:
    first_kept_entry_id: str
    messages_to_summarize: list[AgentMessage]
    turn_prefix_messages: list[AgentMessage]
    is_split_turn: bool
    tokens_before: int
    previous_summary: str | None = None
    details: object | None = None
    plan: CompactionPlan | None = None


@dataclass(frozen=True)
class TranscriptCompactionPolicy:
    """Product-selected automatic-compaction policy values."""

    enabled: bool
    reserve_tokens: int
    compact_percent: float = 100.0
    keep_recent_tokens: int | None = None


EventDispatcher = Callable[[SessionRuntimeEventPayload], Awaitable[None]]
RuntimeExceptionRecorder = Callable[..., None]
ContextOverflowPredicate = Callable[[AssistantMessage, int], bool]


class TranscriptCompactionStore(Protocol):
    """The narrow transcript mutation surface required by maintenance."""

    def get_branch(self) -> list[AgentTranscriptRecord]: ...

    async def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: str,
        tokens_before: int,
        details: object | None = None,
        from_hook: bool | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class CompactionHookRequest:
    reason: CompactionReason
    custom_instructions: str | None


@dataclass(frozen=True)
class CompactionHookDecision:
    """Product adapter result for one optional pre-compaction interception."""

    cancel: bool = False
    result: CompactionResult | None = None


CompactionPolicyProvider = Callable[[], TranscriptCompactionPolicy]
ModelProvider = Callable[[], object | None]
ContextMessagesProvider = Callable[[], list[AgentMessage]]
ContextRefresher = Callable[[], None]
PreparationProvider = Callable[
    [list[AgentTranscriptRecord], int], CompactionPreparation
]
CompactionExecutor = Callable[
    [CompactionPreparation, str | None], Awaitable[CompactionResult]
]
CompactionHook = Callable[
    [CompactionHookRequest], Awaitable[CompactionHookDecision | None]
]
CompactionCommitObserver = Callable[[CompactionResult, str, bool], Awaitable[None]]
HasQueuedMessages = Callable[[], bool]


def _noop_record_runtime_exception(*, code: str, exc: Exception | str) -> None:
    del code, exc


class AgentTranscriptCompactionRuntime:
    """Own compaction lifecycle around a transcript and product strategy ports."""

    def __init__(
        self,
        *,
        transcript: TranscriptCompactionStore,
        get_policy: CompactionPolicyProvider,
        get_model: ModelProvider,
        get_context_messages: ContextMessagesProvider,
        refresh_context: ContextRefresher,
        prepare_compaction: PreparationProvider,
        execute_compaction: CompactionExecutor,
        dispatch_event: EventDispatcher,
        has_queued_messages: HasQueuedMessages,
        before_compaction: CompactionHook | None = None,
        after_compaction: CompactionCommitObserver | None = None,
        record_runtime_exception: RuntimeExceptionRecorder = _noop_record_runtime_exception,
        product_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._transcript = transcript
        self._get_policy = get_policy
        self._get_model = get_model
        self._get_context_messages = get_context_messages
        self._refresh_context = refresh_context
        self._prepare_compaction = prepare_compaction
        self._execute_compaction = execute_compaction
        self._dispatch_event = dispatch_event
        self._has_queued_messages = has_queued_messages
        self._before_compaction = before_compaction
        self._after_compaction = after_compaction
        self._record_runtime_exception = record_runtime_exception
        self._product_id = product_id
        self._session_id = session_id
        self._lifecycle: CompactionCoordinator[CompactionResult] = (
            CompactionCoordinator()
        )
        self._overflow_recovery_attempted = False
        self._last_started_at: str | None = None
        self._last_completed_at: str | None = None
        self._last_stage: str | None = None
        self._last_tokens_before: int | None = None
        self._last_tokens_after: int | None = None
        self._last_summary_mode: Literal["stream", "complete", "hook"] | None = None
        self._last_succeeded: bool | None = None
        self._last_context_window: int | None = None
        self._last_reserve_tokens: int | None = None

    @property
    def is_compacting(self) -> bool:
        return self._lifecycle.is_compacting

    def get_status(self) -> CompactionStatus:
        status = self._lifecycle.get_status()
        return CompactionStatus(
            is_compacting=status.is_compacting,
            last_reason=status.last_reason,
            last_result=status.last_result,
            last_error=status.last_error,
            aborted=status.aborted,
            last_started_at=self._last_started_at,
            last_completed_at=self._last_completed_at,
            last_stage=self._last_stage,
            last_tokens_before=self._last_tokens_before,
            last_tokens_after=self._last_tokens_after,
            last_summary_mode=self._last_summary_mode,
            last_succeeded=self._last_succeeded,
            context_window=self._last_context_window,
            reserve_tokens=self._last_reserve_tokens,
        )

    def abort(self) -> None:
        self._lifecycle.abort()

    def clear_overflow_recovery_attempted(self) -> None:
        self._overflow_recovery_attempted = False

    async def maybe_compact_after_turn(
        self,
        assistant_message: AssistantMessage,
        *,
        is_context_overflow_fn: ContextOverflowPredicate | None = None,
    ) -> AutoCompactionOutcome:
        policy = self._get_policy()
        if not policy.enabled:
            return AutoCompactionOutcome()
        context_window = model_context_window(self._get_model()) or 0
        if context_window <= 0:
            return AutoCompactionOutcome()
        branch = self._transcript.get_branch()
        latest_compaction = latest_compaction_entry(branch)
        if latest_compaction is not None and _message_is_before_or_at_entry(
            assistant_message, latest_compaction
        ):
            return AutoCompactionOutcome()

        if is_context_overflow_fn is not None and is_context_overflow_fn(
            assistant_message, context_window
        ):
            if self._overflow_recovery_attempted:
                message = (
                    "Context overflow recovery failed after one compact-and-retry attempt. "
                    "Try reducing context or switching to a larger-context model."
                )
                usage = _snapshot_payload(self.build_usage_snapshot(policy))
                await self._dispatch_event(
                    ContextCompactionCompleted(
                        reason="overflow",
                        result=None,
                        aborted=False,
                        will_retry=True,
                        error_message=message,
                        usage_before=usage,
                        usage_after=usage,
                        stage="failed",
                        product_id=self._product_id,
                        session_id=self._session_id,
                        duration_ms=0.0,
                        tokens_before=_usage_tokens(usage),
                        tokens_after=_usage_tokens(usage),
                    )
                )
                return AutoCompactionOutcome()
            self._overflow_recovery_attempted = True
            result = await self.compact(
                reason="overflow", will_retry=True, raise_on_error=False
            )
            return AutoCompactionOutcome(
                result=result,
                should_continue=result is not None,
            )

        context_messages = self._get_context_messages()
        if not any(message is assistant_message for message in context_messages):
            context_messages.append(assistant_message)
        decision = build_threshold_compaction_decision(
            context_messages,
            branch,
            self._get_model(),
            enabled=policy.enabled,
            reserve_tokens=policy.reserve_tokens,
            compact_percent=policy.compact_percent,
            keep_recent_tokens=policy.keep_recent_tokens,
        )
        if decision.usage.tokens is None or decision.action != "threshold":
            return AutoCompactionOutcome()
        result = await self.compact(
            reason="threshold", will_retry=False, raise_on_error=False
        )
        return AutoCompactionOutcome(
            result=result,
            should_continue=result is not None and self._has_queued_messages(),
        )

    async def compact(
        self,
        *,
        reason: CompactionReason,
        will_retry: bool,
        raise_on_error: bool = True,
        custom_instructions: str | None = None,
        execute_compaction: CompactionExecutor | None = None,
        prepare_compaction: PreparationProvider | None = None,
    ) -> CompactionResult | None:
        started_at = monotonic()
        policy = self._get_policy()
        usage_before = _snapshot_payload(self.build_usage_snapshot(policy))
        self._last_started_at = _utc_timestamp()
        self._last_completed_at = None
        self._last_stage = "started"
        self._last_tokens_before = _usage_tokens(usage_before)
        self._last_tokens_after = None
        self._last_summary_mode = _summary_mode(self._get_model())
        self._last_succeeded = None
        self._last_context_window = _usage_integer(usage_before, "context_window")
        self._last_reserve_tokens = policy.reserve_tokens
        await self._dispatch_event(
            ContextCompactionStarted(
                reason=reason,
                usage=usage_before,
                stage="started",
                product_id=self._product_id,
                session_id=self._session_id,
                tokens_before=_usage_tokens(usage_before),
            )
        )
        committed: tuple[CompactionResult, str, bool] | None = None

        async def execute_transaction() -> CompactionResult:
            nonlocal committed
            result, record_id, from_hook = await self._execute(
                reason=reason,
                custom_instructions=custom_instructions,
                prepare_compaction=prepare_compaction or self._prepare_compaction,
                execute_compaction=execute_compaction or self._execute_compaction,
                policy=policy,
            )
            # A successful append is the commit point.  Refresh synchronously
            # before yielding to Product observers so live context cannot lag
            # behind a durable checkpoint.
            self._refresh_context()
            committed = (result, record_id, from_hook)
            return result

        task = asyncio.current_task()
        abort_driver: Callable[[], None] | None = None
        if task is not None:

            def abort_task() -> None:
                task.cancel()

            abort_driver = abort_task
        try:
            result = await self._lifecycle.run(
                execute_transaction,
                reason=reason,
                abort_driver=abort_driver,
            )
        except asyncio.CancelledError:
            await self._dispatch_compaction_completed(
                reason=reason,
                result=None,
                aborted=True,
                will_retry=will_retry,
                policy=policy,
                usage_before=usage_before,
                started_at=started_at,
                stage="aborted",
            )
            if raise_on_error:
                raise
            return None
        except Exception as exc:
            aborted = is_compaction_aborted(exc)
            if not aborted:
                self._record_runtime_exception(code="compaction_failed", exc=exc)
            await self._dispatch_compaction_completed(
                reason=reason,
                result=None,
                aborted=aborted,
                will_retry=will_retry,
                policy=policy,
                usage_before=usage_before,
                started_at=started_at,
                stage="aborted" if aborted else "failed",
                error_message=None if aborted else f"Compaction failed: {exc}",
            )
            if raise_on_error:
                raise
            return None

        post_commit_failed = False
        if committed is not None and self._after_compaction is not None:
            committed_result, record_id, from_hook = committed
            try:
                await self._after_compaction(
                    committed_result,
                    record_id,
                    from_hook,
                )
            except Exception as exc:
                post_commit_failed = True
                self._record_runtime_exception(
                    code="compaction_post_commit_failed",
                    exc=exc,
                )

        if committed is not None and committed[2]:
            self._last_summary_mode = "hook"

        await self._dispatch_compaction_completed(
            reason=reason,
            result=asdict(result),
            aborted=False,
            will_retry=will_retry,
            policy=policy,
            usage_before=usage_before,
            started_at=started_at,
            stage="post_hook_failed" if post_commit_failed else "committed",
            checkpoint_record_id=committed[1] if committed is not None else None,
        )
        return result

    async def _dispatch_compaction_completed(
        self,
        *,
        reason: CompactionReason,
        result: object | None,
        aborted: bool,
        will_retry: bool,
        policy: TranscriptCompactionPolicy,
        usage_before: Mapping[str, object],
        started_at: float,
        stage: Literal["aborted", "failed", "committed", "post_hook_failed"],
        error_message: str | None = None,
        checkpoint_record_id: str | None = None,
    ) -> None:
        usage_after = _snapshot_payload(self.build_usage_snapshot(policy))
        self._last_completed_at = _utc_timestamp()
        self._last_stage = stage
        self._last_tokens_after = _usage_tokens(usage_after)
        self._last_succeeded = stage in {"committed", "post_hook_failed"}
        await self._dispatch_event(
            ContextCompactionCompleted(
                reason=reason,
                result=result,
                aborted=aborted,
                will_retry=will_retry,
                error_message=error_message,
                usage_before=usage_before,
                usage_after=usage_after,
                stage=stage,
                product_id=self._product_id,
                session_id=self._session_id,
                duration_ms=round(max(monotonic() - started_at, 0.0) * 1_000, 3),
                tokens_before=_usage_tokens(usage_before),
                tokens_after=_usage_tokens(usage_after),
                checkpoint_record_id=checkpoint_record_id,
            )
        )

    def build_usage_snapshot(
        self, policy: TranscriptCompactionPolicy | None = None
    ) -> ContextUsageSnapshot:
        active_policy = policy or self._get_policy()
        return build_context_usage_snapshot(
            self._get_context_messages(),
            self._transcript.get_branch(),
            self._get_model(),
            reserve_tokens=active_policy.reserve_tokens,
            compact_percent=active_policy.compact_percent,
            keep_recent_tokens=active_policy.keep_recent_tokens,
        )

    async def _execute(
        self,
        *,
        reason: CompactionReason,
        custom_instructions: str | None,
        prepare_compaction: PreparationProvider,
        execute_compaction: CompactionExecutor,
        policy: TranscriptCompactionPolicy,
    ) -> tuple[CompactionResult, str, bool]:
        preparation = prepare_compaction(
            self._transcript.get_branch(),
            policy.keep_recent_tokens or 0,
        )
        if (
            not preparation.messages_to_summarize
            and not preparation.turn_prefix_messages
        ):
            raise RuntimeError("Nothing to compact (session too small)")

        result: CompactionResult | None = None
        from_hook = False
        if self._before_compaction is not None:
            decision = await self._before_compaction(
                CompactionHookRequest(
                    reason=reason,
                    custom_instructions=custom_instructions,
                )
            )
            if decision is not None and decision.cancel:
                raise CompactionAborted("Compaction cancelled")
            if decision is not None and decision.result is not None:
                result = decision.result
                from_hook = True

        if result is None:
            result = await execute_compaction(preparation, custom_instructions)
        result = _with_preparation_details(result, preparation)
        record_id = await self._transcript.append_compaction(
            result.summary,
            result.first_kept_entry_id,
            result.tokens_before,
            details=result.details,
            from_hook=from_hook,
        )
        return result, record_id, from_hook


def build_threshold_compaction_decision(
    messages: Sequence[AgentMessage],
    branch_entries: Sequence[object],
    model: object | None,
    *,
    enabled: bool,
    reserve_tokens: int,
    compact_percent: float = 100.0,
    keep_recent_tokens: int | None = None,
) -> CompactionDecision:
    snapshot = build_context_usage_snapshot(
        messages,
        branch_entries,
        model,
        reserve_tokens=reserve_tokens,
        compact_percent=compact_percent,
        keep_recent_tokens=keep_recent_tokens,
    )
    if enabled and snapshot.compactable:
        return CompactionDecision(
            action="threshold",
            usage=snapshot,
            will_retry=False,
            reason=snapshot.reason,
        )
    return CompactionDecision(
        action="none",
        usage=snapshot,
        will_retry=False,
        reason=snapshot.reason,
    )


def is_compaction_aborted(exc: Exception) -> bool:
    return (
        isinstance(exc, CompactionAborted) or getattr(exc, "name", None) == "AbortError"
    )


def _message_is_before_or_at_entry(
    message: AssistantMessage, entry: ConversationRecord[object]
) -> bool:
    entry_timestamp = _entry_timestamp_ms(entry.created_at)
    return entry_timestamp is not None and message.timestamp <= entry_timestamp


def _entry_timestamp_ms(timestamp: str) -> float | None:
    try:
        return (
            datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000
        )
    except ValueError:
        return None


def _snapshot_payload(snapshot: ContextUsageSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def _usage_tokens(usage: Mapping[str, object]) -> int | None:
    tokens = usage.get("tokens")
    return tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None


def _usage_integer(usage: Mapping[str, object], key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _summary_mode(
    model: object | None,
) -> Literal["stream", "complete"] | None:
    if model is None:
        return None
    return "stream" if bool(getattr(model, "supports_stream", False)) else "complete"


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _with_preparation_details(
    result: CompactionResult,
    preparation: CompactionPreparation,
) -> CompactionResult:
    details = _merge_preparation_result_details(preparation.details, result.details)
    return result if details == result.details else replace(result, details=details)


def _merge_preparation_result_details(
    preparation_details: object | None,
    result_details: object | None,
) -> object | None:
    if not isinstance(preparation_details, Mapping):
        return result_details if result_details is not None else preparation_details
    merged: dict[object, object] = dict(preparation_details)
    if isinstance(result_details, Mapping):
        merged.update(result_details)
        if "compactionPlan" in preparation_details:
            merged["compactionPlan"] = preparation_details["compactionPlan"]
        return merged
    if result_details is not None:
        merged["resultDetails"] = result_details
    return merged


__all__ = [
    "AutoCompactionOutcome",
    "AgentTranscriptCompactionRuntime",
    "CompactionHookDecision",
    "CompactionHookRequest",
    "CompactionAborted",
    "CompactionDecision",
    "CompactionPlan",
    "CompactionPreparation",
    "CompactionResult",
    "CompactionStatus",
    "ContextUsageSnapshot",
    "TranscriptCompactionStore",
    "TranscriptCompactionPolicy",
    "build_context_usage_snapshot",
    "build_threshold_compaction_decision",
    "calculate_context_tokens",
    "current_context_usage",
    "estimate_context_tokens",
    "estimate_message_tokens",
    "has_post_compaction_usage",
    "is_compaction_aborted",
    "latest_compaction_entry",
    "model_context_window",
]
