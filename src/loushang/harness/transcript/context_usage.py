"""Context accounting for the optional Agent transcript profile.

This module derives context-budget observations from stable Agent messages and
transcript compaction checkpoints. Generic estimates and budget arithmetic
remain in :mod:`loushang.harness.context`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from loushang.agent.types import AgentMessage
from loushang.ai.types import AssistantMessage, ToolResultMessage, UserMessage
from loushang.harness.context.budget import calculate_compaction_budget
from loushang.harness.context.usage import ContextUsageEstimate
from loushang.harness.conversation import ConversationRecord
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
)

ContextUsageSource = Literal[
    "assistant_usage", "estimated_from_last_usage", "estimated", "unknown"
]


@dataclass(frozen=True)
class ContextUsageSnapshot:
    """One context-budget observation over an Agent transcript branch."""

    tokens: int | None
    context_window: int | None
    reserve_tokens: int
    compact_percent: float = 100.0
    keep_recent_tokens: int | None = None
    percent_threshold_tokens: int | None = None
    reserve_threshold_tokens: int | None = None
    threshold_tokens: int | None = None
    threshold_reason: Literal["compact_percent", "reserve_tokens"] | None = None
    percent: float | None = None
    source: ContextUsageSource = "unknown"
    last_usage_index: int | None = None
    stale_after_compaction: bool = False
    compactable: bool = False
    reason: str | None = None


def calculate_context_tokens(usage: object) -> int:
    """Extract total tokens from stable AI usage values or their JSON form."""

    total_tokens = _usage_value(usage, "totalTokens", "total_tokens")
    if isinstance(total_tokens, int) and total_tokens > 0:
        return total_tokens
    return sum(
        _integer_usage_value(_usage_value(usage, *keys))
        for keys in (
            ("input",),
            ("output",),
            ("cacheRead", "cache_read"),
            ("cacheWrite", "cache_write"),
        )
    )


def estimate_context_tokens(messages: Sequence[AgentMessage]) -> ContextUsageEstimate:
    """Estimate current context using the latest completed assistant usage."""

    sequence = list(messages)
    last_usage = _last_assistant_usage_info(sequence)
    if last_usage is None:
        estimated = sum(estimate_message_tokens(message) for message in sequence)
        return ContextUsageEstimate(
            tokens=estimated,
            usage_tokens=0,
            trailing_tokens=estimated,
            last_usage_index=None,
        )

    usage, usage_index = last_usage
    usage_tokens = calculate_context_tokens(usage)
    trailing_tokens = sum(
        estimate_message_tokens(message) for message in sequence[usage_index + 1 :]
    )
    return ContextUsageEstimate(
        tokens=usage_tokens + trailing_tokens,
        usage_tokens=usage_tokens,
        trailing_tokens=trailing_tokens,
        last_usage_index=usage_index,
    )


def current_context_usage(
    messages: Sequence[AgentMessage],
    branch_entries: Sequence[object],
    model: object | None,
) -> tuple[int | None, int | None, float | None]:
    snapshot = build_context_usage_snapshot(
        messages, branch_entries, model, reserve_tokens=0
    )
    return snapshot.tokens, snapshot.context_window, snapshot.percent


def build_context_usage_snapshot(
    messages: Sequence[AgentMessage],
    branch_entries: Sequence[object],
    model: object | None,
    *,
    reserve_tokens: int,
    compact_percent: float = 100.0,
    keep_recent_tokens: int | None = None,
) -> ContextUsageSnapshot:
    context_window = model_context_window(model)
    if context_window is None:
        return ContextUsageSnapshot(
            tokens=None,
            context_window=None,
            reserve_tokens=reserve_tokens,
            compact_percent=compact_percent,
            keep_recent_tokens=keep_recent_tokens,
            threshold_tokens=None,
            threshold_reason=None,
            percent=None,
            source="unknown",
            last_usage_index=None,
            stale_after_compaction=False,
            compactable=False,
            reason="unknown_context_window",
        )

    budget = calculate_compaction_budget(
        context_window=context_window,
        compact_percent=compact_percent,
        reserve_tokens=reserve_tokens,
    )
    latest_compaction = latest_compaction_entry(branch_entries)
    if latest_compaction is not None and not has_post_compaction_usage(
        branch_entries, latest_compaction
    ):
        return ContextUsageSnapshot(
            tokens=None,
            context_window=context_window,
            reserve_tokens=reserve_tokens,
            compact_percent=budget.compact_percent,
            keep_recent_tokens=keep_recent_tokens,
            percent_threshold_tokens=budget.percent_threshold_tokens,
            reserve_threshold_tokens=budget.reserve_threshold_tokens,
            threshold_tokens=budget.threshold_tokens,
            threshold_reason=budget.threshold_reason,
            percent=None,
            source="unknown",
            last_usage_index=None,
            stale_after_compaction=True,
            compactable=False,
            reason="stale_usage_after_compaction",
        )

    estimate = estimate_context_tokens(messages) if messages else None
    tokens = estimate.tokens if estimate is not None else 0
    last_usage_index = estimate.last_usage_index if estimate is not None else None
    if estimate is None or last_usage_index is None:
        source: ContextUsageSource = "estimated"
    elif estimate.trailing_tokens > 0:
        source = "estimated_from_last_usage"
    else:
        source = "assistant_usage"
    compactable = tokens > budget.threshold_tokens
    return ContextUsageSnapshot(
        tokens=tokens,
        context_window=context_window,
        reserve_tokens=reserve_tokens,
        compact_percent=budget.compact_percent,
        keep_recent_tokens=keep_recent_tokens,
        percent_threshold_tokens=budget.percent_threshold_tokens,
        reserve_threshold_tokens=budget.reserve_threshold_tokens,
        threshold_tokens=budget.threshold_tokens,
        threshold_reason=budget.threshold_reason,
        percent=(tokens / context_window) * 100,
        source=source,
        last_usage_index=last_usage_index,
        stale_after_compaction=False,
        compactable=compactable,
        reason="threshold" if compactable else None,
    )


def model_context_window(model: object | None) -> int | None:
    capabilities: object | None = getattr(model, "capabilities", None)
    raw_context_window: object | None = getattr(capabilities, "context_window", None)
    if raw_context_window is None:
        raw_context_window = getattr(model, "context_window", None)
    return _positive_int(raw_context_window)


def latest_compaction_entry(
    entries: Sequence[object],
) -> ConversationRecord[object] | None:
    for entry in reversed(entries):
        if (
            isinstance(entry, ConversationRecord)
            and entry.kind == CONTEXT_COMPACTION_CHECKPOINT_KIND
        ):
            return entry
    return None


def has_post_compaction_usage(
    entries: Sequence[object], compaction: ConversationRecord[object]
) -> bool:
    try:
        compaction_index = list(entries).index(compaction)
    except ValueError:
        return False
    for entry in reversed(entries[compaction_index + 1 :]):
        if (
            not isinstance(entry, ConversationRecord)
            or entry.kind != AGENT_MESSAGE_KIND
        ):
            continue
        message = entry.payload
        if not isinstance(message, AssistantMessage):
            continue
        if message.stop_reason in {"aborted", "error"}:
            return False
        return calculate_context_tokens(message.usage) > 0
    return False


def estimate_message_tokens(message: AgentMessage) -> int:
    chars = 0
    if isinstance(message, UserMessage):
        if isinstance(message.content, str):
            chars = len(message.content)
        else:
            for block in message.content:
                if getattr(block, "type", None) == "text":
                    chars += len(str(getattr(block, "text", "")))
                elif getattr(block, "type", None) == "image":
                    chars += 4_800
        return (chars + 3) // 4
    if isinstance(message, AssistantMessage):
        for assistant_block in message.content:
            block_type = getattr(assistant_block, "type", None)
            if block_type == "text":
                chars += len(str(getattr(assistant_block, "text", "")))
            elif block_type == "thinking":
                chars += len(str(getattr(assistant_block, "thinking", "")))
            elif block_type == "toolCall":
                chars += len(str(getattr(assistant_block, "name", ""))) + len(
                    str(getattr(assistant_block, "arguments", ""))
                )
            elif block_type == "image":
                chars += 4_800
        return (chars + 3) // 4
    if isinstance(message, ToolResultMessage):
        for block in message.content:
            if getattr(block, "type", None) == "text":
                chars += len(str(getattr(block, "text", "")))
            elif getattr(block, "type", None) == "image":
                chars += 4_800
        return (chars + 3) // 4
    return 0


def _usage_value(usage: object, *keys: str) -> object | None:
    if isinstance(usage, Mapping):
        for key in keys:
            value = usage.get(key)
            if value is not None:
                return value
        return None
    for key in keys:
        if hasattr(usage, key):
            value = getattr(usage, key)
            if value is not None:
                return value
    return None


def _integer_usage_value(value: object | None) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _positive_int(value: object | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float | str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _last_assistant_usage_info(
    messages: Sequence[AgentMessage],
) -> tuple[object, int] | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AssistantMessage) and message.stop_reason not in (
            "aborted",
            "error",
        ):
            return message.usage, index
    return None


__all__ = [
    "ContextUsageSnapshot",
    "ContextUsageSource",
    "build_context_usage_snapshot",
    "calculate_context_tokens",
    "current_context_usage",
    "estimate_context_tokens",
    "estimate_message_tokens",
    "has_post_compaction_usage",
    "latest_compaction_entry",
    "model_context_window",
]
