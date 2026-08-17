from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.harness.approval import ApprovalDecision, ApprovalRequest
from loushang.harness.conversation import ConversationRepository
from loushang.harness.multiagent import (
    AgentApprovalEnvelope,
    AgentPath,
    AgentRef,
    ForkTier,
    MappedHistoryMessage,
    SubagentApprovalResolver,
    SubagentContextFactory,
    TranscriptWatermark,
)


@dataclass(frozen=True)
class _Record:
    record_id: str
    parent_id: str | None
    role: str
    text: str


def _source() -> ConversationRepository[None, _Record]:
    records = (
        _Record("u1", None, "user", "first question"),
        _Record("t1", "u1", "tool", "hidden tool output"),
        _Record("a1", "t1", "assistant", "first answer"),
        _Record("u2", "a1", "user", "second question"),
        _Record("a2", "u2", "assistant", "second answer"),
        _Record("u3", "a2", "user", "not committed at watermark"),
    )
    return ConversationRepository.create(
        header=None,
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )


def _factory() -> SubagentContextFactory[_Record, str]:
    return SubagentContextFactory(
        source=_source(),
        mapper=lambda record: (
            MappedHistoryMessage(
                f"{record.role}:{record.text}",
                starts_turn=record.role == "user",
            ),
        ),
        history_filter=lambda message: not message.value.startswith("tool:"),
    )


def test_all_history_is_rebuilt_only_to_the_committed_watermark() -> None:
    factory = _factory()

    first = factory.fork_history(
        tier=ForkTier.all(),
        watermark=TranscriptWatermark("a2"),
        rendered_prefix=b"stable-prefix",
    )
    second = factory.fork_history(
        tier=ForkTier.all(),
        watermark=TranscriptWatermark("a2"),
        rendered_prefix=b"stable-prefix",
    )

    assert first == second
    assert first.messages == (
        "user:first question",
        "assistant:first answer",
        "user:second question",
        "assistant:second answer",
    )
    assert first.rendered_prefix == b"stable-prefix"


def test_recent_history_cuts_only_at_a_mapped_turn_boundary() -> None:
    history = _factory().fork_history(
        tier=ForkTier.last(1),
        watermark=TranscriptWatermark("a2"),
    )

    assert history.messages == (
        "user:second question",
        "assistant:second answer",
    )
    assert [diagnostic.code for diagnostic in history.diagnostics] == [
        "rendered_prefix_unavailable"
    ]


def test_empty_filtered_history_degrades_to_fresh_with_a_diagnostic() -> None:
    source = _source()
    factory = SubagentContextFactory(
        source=source,
        mapper=lambda _record: (),
    )

    history = factory.fork_history(
        tier=ForkTier.all(),
        watermark=TranscriptWatermark("a2"),
    )

    assert history.effective_tier == ForkTier.none()
    assert history.messages == ()
    assert history.diagnostics[0].code == "fork_history_empty"


def test_fork_requires_a_watermark_and_cannot_override_the_parent_model() -> None:
    factory = _factory()

    with pytest.raises(ValueError, match="watermark"):
        factory.fork_history(tier=ForkTier.all(), watermark=None)
    with pytest.raises(ValueError, match="cannot override"):
        factory.build(
            tier=ForkTier.all(),
            watermark=TranscriptWatermark("a2"),
            system_prompt="Review independently.",
            inherited_model="provider/parent",
            model_override="provider/other",
        )


def test_fresh_context_does_not_read_or_copy_parent_history() -> None:
    plan = _factory().build(
        tier=ForkTier.none(),
        watermark=None,
        system_prompt="Explore the repository.",
        inherited_model="provider/parent",
        model_override="provider/child",
        allowed_tools=("read", "grep"),
    )

    assert plan.model == "provider/child"
    assert plan.allowed_tools == ("read", "grep")
    assert plan.history.messages == ()
    assert plan.history.rendered_prefix is None


def test_subagent_approval_bubbles_the_original_request_with_agent_provenance() -> None:
    class _Exit:
        def __init__(self) -> None:
            self.envelopes: list[AgentApprovalEnvelope] = []

        def resolve(self, envelope: AgentApprovalEnvelope) -> ApprovalDecision:
            self.envelopes.append(envelope)
            return ApprovalDecision.allow()

    child = AgentRef(AgentPath.root().child("reviewer"), 1)
    root = AgentRef(AgentPath.root(), 1)
    exit_port = _Exit()
    resolver = SubagentApprovalResolver(
        caller_ref=child,
        parent_chain=(root,),
        exit_port=exit_port,
    )

    decision = asyncio.run(
        resolver.resolve(ApprovalRequest(tool_name="bash", arguments={"cmd": "ls"}))
    )

    assert decision.disposition == "allow"
    assert exit_port.envelopes[0].caller_ref == child
    assert exit_port.envelopes[0].parent_chain == (root,)
    assert exit_port.envelopes[0].request.tool_name == "bash"
    assert exit_port.envelopes[0].request.action_id is not None
    assert exit_port.envelopes[0].request.actor_id == str(child)
