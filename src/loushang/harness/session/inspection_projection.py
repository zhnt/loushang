"""Product-neutral projections over Harness session inspection values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from loushang.harness.context import serialize_context_usage_payload
from loushang.harness.session.inspection import AgentSessionInspector
from loushang.harness.transcript import (
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    AgentTranscriptRecord,
    ContextCompactionCheckpoint,
)


class _AgentStatePort(Protocol):
    @property
    def messages(self) -> Sequence[object]: ...


class _AgentPort(Protocol):
    @property
    def state(self) -> _AgentStatePort: ...


class _SessionRecordPort(Protocol):
    @property
    def session_id(self) -> str: ...


class _SessionStatsPort(Protocol):
    def get_session_file(self) -> object | None: ...

    def get_session_record(self) -> _SessionRecordPort: ...

    def get_branch(self) -> Sequence[AgentTranscriptRecord]: ...


def project_session_stats(
    *,
    agent: object,
    session_manager: object,
    context_usage: object | None,
) -> dict[str, object]:
    """Project common inspection facts into Coding's Pi-compatible payload."""

    agent_port = cast(_AgentPort, agent)
    session_port = cast(_SessionStatsPort, session_manager)
    user_messages = 0
    assistant_messages = 0
    tool_results = 0
    tool_calls = 0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    total_cost = 0.0
    messages = list(agent_port.state.messages)
    for message in messages:
        role = getattr(message, "role", None)
        if role == "user":
            user_messages += 1
        elif role == "assistant":
            assistant_messages += 1
            content = getattr(message, "content", [])
            if isinstance(content, list):
                tool_calls += sum(
                    1 for block in content if getattr(block, "type", None) == "toolCall"
                )
            usage = getattr(message, "usage", None)
            if usage is not None:
                total_input += int(getattr(usage, "input", 0) or 0)
                total_output += int(getattr(usage, "output", 0) or 0)
                total_cache_read += int(getattr(usage, "cache_read", 0) or 0)
                total_cache_write += int(getattr(usage, "cache_write", 0) or 0)
                cost = getattr(usage, "cost", {})
                if isinstance(cost, dict):
                    total_cost += float(
                        cost.get(
                            "total",
                            sum(
                                value
                                for value in cost.values()
                                if isinstance(value, int | float)
                            ),
                        )
                    )
        elif role == "toolResult":
            tool_results += 1
    session_file = session_port.get_session_file()
    return {
        "session_file": str(session_file) if session_file is not None else None,
        "session_id": session_port.get_session_record().session_id,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "total_messages": len(messages),
        "tokens": {
            "input": total_input,
            "output": total_output,
            "cache_read": total_cache_read,
            "cache_write": total_cache_write,
            "total": total_input + total_output + total_cache_read + total_cache_write,
        },
        "cost": total_cost,
        "context_usage": serialize_context_usage_payload(context_usage),
        "latest_compaction": _latest_compaction_payload(session_port.get_branch()),
    }


def project_fork_candidates(
    inspector: AgentSessionInspector,
) -> list[dict[str, str]]:
    """Project common transcript fork candidates into Coding's wire shape."""

    return [
        {"entry_id": message["entry_id"], "text": message["text"]}
        for message in inspector.get_user_messages_for_forking()
    ]


def _latest_compaction_payload(
    entries: Sequence[AgentTranscriptRecord],
) -> dict[str, object] | None:
    for entry in reversed(entries):
        if entry.kind != CONTEXT_COMPACTION_CHECKPOINT_KIND or not isinstance(
            entry.payload, ContextCompactionCheckpoint
        ):
            continue
        checkpoint = entry.payload
        details = checkpoint.details if isinstance(checkpoint.details, Mapping) else {}
        plan = details.get("compactionPlan")
        return {
            "entry_id": entry.record_id,
            "first_kept_entry_id": checkpoint.first_kept_record_id,
            "tokens_before": checkpoint.tokens_before,
            "from_hook": checkpoint.from_hook,
            "plan": dict(plan) if isinstance(plan, Mapping) else None,
        }
    return None


__all__ = ["project_fork_candidates", "project_session_stats"]
