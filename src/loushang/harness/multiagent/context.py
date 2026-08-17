"""Deterministic transcript snapshot planning for technical child agents."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from typing import Generic, Literal, Protocol, TypeVar

from loushang.harness.approval import (
    ApprovalDecision,
    ApprovalRequest,
    ensure_approval_action_id,
)

from .types import AgentRef

RecordT = TypeVar("RecordT")
RecordT_co = TypeVar("RecordT_co", covariant=True)
MessageT = TypeVar("MessageT")

ForkMode = Literal["none", "all", "last"]


@dataclass(frozen=True, slots=True)
class TranscriptWatermark:
    """The exact committed transcript record visible to one spawn."""

    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise ValueError("transcript watermark record_id must be non-empty")


@dataclass(frozen=True, slots=True)
class ForkTier:
    """History selection requested for one child context."""

    mode: ForkMode = "none"
    turns: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"none", "all", "last"}:
            raise ValueError(f"unsupported fork tier: {self.mode}")
        if self.mode == "last":
            if type(self.turns) is not int or self.turns is None or self.turns < 1:
                raise ValueError("last fork tier requires a positive turn count")
        elif self.turns is not None:
            raise ValueError("turns is valid only for the last fork tier")

    @classmethod
    def none(cls) -> ForkTier:
        return cls("none")

    @classmethod
    def all(cls) -> ForkTier:
        return cls("all")

    @classmethod
    def last(cls, turns: int) -> ForkTier:
        return cls("last", turns)


@dataclass(frozen=True, slots=True)
class MappedHistoryMessage(Generic[MessageT]):
    """One Product-mapped message with a stable turn-boundary marker."""

    value: MessageT
    starts_turn: bool = False


class TranscriptHistorySource(Protocol[RecordT_co]):
    """Existing parent-linked transcript read seam used by session forks."""

    def records_to(self, record_id: str) -> tuple[RecordT_co, ...]: ...


HistoryMapper = Callable[[RecordT], Iterable[MappedHistoryMessage[MessageT]]]
HistoryFilter = Callable[[MappedHistoryMessage[MessageT]], bool]


@dataclass(frozen=True, slots=True)
class ForkHistoryDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ForkedHistory(Generic[MessageT]):
    """Immutable child history rebuilt from one committed watermark."""

    requested_tier: ForkTier
    effective_tier: ForkTier
    watermark: TranscriptWatermark | None
    messages: tuple[MessageT, ...]
    rendered_prefix: bytes | None = None
    diagnostics: tuple[ForkHistoryDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentApprovalEnvelope:
    """Preserve the existing approval request while adding agent provenance."""

    request: ApprovalRequest
    caller_ref: AgentRef
    parent_chain: tuple[AgentRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_chain", tuple(self.parent_chain))


class ApprovalExitPort(Protocol):
    def resolve(
        self,
        envelope: AgentApprovalEnvelope,
    ) -> ApprovalDecision | Awaitable[ApprovalDecision]: ...


class SubagentApprovalResolver:
    """Bubble one child's approvals to the root interaction exit."""

    def __init__(
        self,
        *,
        caller_ref: AgentRef,
        parent_chain: tuple[AgentRef, ...],
        exit_port: ApprovalExitPort,
    ) -> None:
        self._caller_ref = caller_ref
        self._parent_chain = tuple(parent_chain)
        self._exit_port = exit_port

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        envelope = AgentApprovalEnvelope(
            request=replace(
                ensure_approval_action_id(request),
                actor_id=str(self._caller_ref),
            ),
            caller_ref=self._caller_ref,
            parent_chain=self._parent_chain,
        )
        decision = self._exit_port.resolve(envelope)
        if inspect.isawaitable(decision):
            decision = await decision
        if not isinstance(decision, ApprovalDecision):
            raise TypeError(
                "approval exit returned "
                f"{type(decision).__name__}, expected ApprovalDecision"
            )
        return decision


@dataclass(frozen=True, slots=True)
class SubagentContextPlan(Generic[MessageT]):
    """Product-neutral context inputs prepared before initial-message delivery."""

    system_prompt: str
    model: str | None
    history: ForkedHistory[MessageT]
    allowed_tools: tuple[str, ...] = ()
    approval_resolver: SubagentApprovalResolver | None = None

    def __post_init__(self) -> None:
        if not self.system_prompt.strip():
            raise ValueError("subagent system_prompt must be non-empty")
        if self.model is not None and not self.model.strip():
            raise ValueError("subagent model must be non-empty when provided")
        tools = tuple(self.allowed_tools)
        if any(not isinstance(tool, str) or not tool for tool in tools):
            raise ValueError("subagent allowed_tools must contain non-empty strings")
        if len(set(tools)) != len(tools):
            raise ValueError("subagent allowed_tools must not contain duplicates")
        object.__setattr__(self, "allowed_tools", tools)


class SubagentContextFactory(Generic[RecordT, MessageT]):
    """Build deterministic fresh/fork plans without Product record knowledge."""

    def __init__(
        self,
        *,
        source: TranscriptHistorySource[RecordT],
        mapper: HistoryMapper[RecordT, MessageT],
        history_filter: HistoryFilter[MessageT] | None = None,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._history_filter = history_filter or (lambda _message: True)

    def build(
        self,
        *,
        tier: ForkTier,
        watermark: TranscriptWatermark | None,
        system_prompt: str,
        inherited_model: str | None = None,
        model_override: str | None = None,
        rendered_prefix: bytes | None = None,
        allowed_tools: tuple[str, ...] = (),
        approval_resolver: SubagentApprovalResolver | None = None,
    ) -> SubagentContextPlan[MessageT]:
        if tier.mode != "none" and watermark is None:
            raise ValueError("forked subagent context requires a transcript watermark")
        if tier.mode != "none" and model_override is not None:
            raise ValueError("forked subagent context cannot override the parent model")
        history = self.fork_history(
            tier=tier,
            watermark=watermark,
            rendered_prefix=rendered_prefix,
        )
        return SubagentContextPlan(
            system_prompt=system_prompt,
            model=inherited_model if model_override is None else model_override,
            history=history,
            allowed_tools=allowed_tools,
            approval_resolver=approval_resolver,
        )

    def fork_history(
        self,
        *,
        tier: ForkTier,
        watermark: TranscriptWatermark | None,
        rendered_prefix: bytes | None = None,
    ) -> ForkedHistory[MessageT]:
        if tier.mode == "none":
            return ForkedHistory(
                requested_tier=tier,
                effective_tier=tier,
                watermark=watermark,
                messages=(),
            )
        if watermark is None:
            raise ValueError("forked subagent history requires a transcript watermark")

        records = self._source.records_to(watermark.record_id)
        mapped = tuple(
            message
            for record in records
            for message in tuple(self._mapper(record))
            if self._history_filter(message)
        )
        diagnostics: list[ForkHistoryDiagnostic] = []
        selected = mapped
        if tier.mode == "last":
            assert tier.turns is not None
            selected = _select_recent_turns(mapped, tier.turns)
        if not selected:
            diagnostics.append(
                ForkHistoryDiagnostic(
                    code="fork_history_empty",
                    message=(
                        "The committed transcript snapshot produced no child-visible "
                        "history; the child will start fresh."
                    ),
                )
            )
            return ForkedHistory(
                requested_tier=tier,
                effective_tier=ForkTier.none(),
                watermark=watermark,
                messages=(),
                diagnostics=tuple(diagnostics),
            )
        if rendered_prefix is None:
            diagnostics.append(
                ForkHistoryDiagnostic(
                    code="rendered_prefix_unavailable",
                    message=(
                        "The fork remains deterministic, but cannot reuse an exact "
                        "rendered request prefix."
                    ),
                )
            )
        return ForkedHistory(
            requested_tier=tier,
            effective_tier=tier,
            watermark=watermark,
            messages=tuple(message.value for message in selected),
            rendered_prefix=(
                None if rendered_prefix is None else bytes(rendered_prefix)
            ),
            diagnostics=tuple(diagnostics),
        )


def _select_recent_turns(
    messages: tuple[MappedHistoryMessage[MessageT], ...],
    count: int,
) -> tuple[MappedHistoryMessage[MessageT], ...]:
    if not messages:
        return ()
    starts = tuple(
        index for index, message in enumerate(messages) if message.starts_turn
    )
    if not starts:
        return messages
    return messages[starts[max(0, len(starts) - count)] :]


__all__ = [
    "AgentApprovalEnvelope",
    "ApprovalExitPort",
    "ForkHistoryDiagnostic",
    "ForkMode",
    "ForkTier",
    "ForkedHistory",
    "HistoryFilter",
    "HistoryMapper",
    "MappedHistoryMessage",
    "SubagentContextFactory",
    "SubagentContextPlan",
    "SubagentApprovalResolver",
    "TranscriptHistorySource",
    "TranscriptWatermark",
]
