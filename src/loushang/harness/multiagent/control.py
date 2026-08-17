"""Pure lifecycle, authority, and fact coordination for an agent tree."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, TypeVar

from .registry import AgentRegistry, Clock
from .types import (
    AgentAuthorityPolicy,
    AgentCompletionNotice,
    AgentFact,
    AgentFactKind,
    AgentInputMessage,
    AgentMessageKind,
    AgentPath,
    AgentProgress,
    AgentRecord,
    AgentRef,
    AgentTransition,
    AgentTypeRegistry,
    AgentTypeSpec,
    AgentUsage,
    ControlCaller,
    ControlLimits,
    DeliveryIntent,
    HostCaller,
    MultiAgentError,
    TerminalPayload,
    TerminalStatus,
    TransitionReason,
)
from .workspace import WorkspaceLeaseSnapshot

FactConsumer = Callable[[AgentFact], None]
NoticeConsumer = Callable[[AgentCompletionNotice], None]
ConsumerT = TypeVar("ConsumerT")


class _KeepSummary:
    pass


_SummaryUpdate = str | None | _KeepSummary
_KEEP_SUMMARY = _KeepSummary()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DefaultAgentAuthorityPolicy:
    """Host controls the tree; agents control self/descendants by default."""

    def allows_control(self, caller: ControlCaller, target: AgentRecord) -> bool:
        if isinstance(caller, HostCaller):
            return True
        return target.path.is_descendant_of(caller.ref.path, include_self=True)

    def allows_message(self, caller: ControlCaller, target: AgentRecord) -> bool:
        if isinstance(caller, HostCaller):
            return True
        sender = caller.ref.path
        if target.path == sender:
            return True
        if target.path.is_descendant_of(sender):
            return True
        return sender.parent == target.path


class MultiAgentControl:
    """Synchronous state core; live task and queue ownership land later."""

    def __init__(
        self,
        *,
        agent_types: AgentTypeRegistry | None = None,
        authority: AgentAuthorityPolicy | None = None,
        limits: ControlLimits | None = None,
        registry: AgentRegistry | None = None,
        fact_consumers: Iterable[FactConsumer] = (),
        notice_consumers: Iterable[NoticeConsumer] = (),
        clock: Clock = _utc_now,
    ) -> None:
        self._clock = clock
        self._registry = registry or AgentRegistry(clock=clock)
        self._agent_types = agent_types or AgentTypeRegistry()
        self._authority = authority or DefaultAgentAuthorityPolicy()
        self._limits = limits or ControlLimits()
        self._fact_consumers = list(fact_consumers)
        self._notice_consumers = list(notice_consumers)
        self._facts: list[AgentFact] = []
        self._notices: list[AgentCompletionNotice] = []
        self._notified_rounds: set[tuple[AgentRef, int]] = set()
        self._fact_sequence = 0
        self._message_sequence = 0

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def root_ref(self) -> AgentRef:
        return self._registry.root_ref

    def facts(self) -> tuple[AgentFact, ...]:
        return tuple(self._facts)

    def notices(self) -> tuple[AgentCompletionNotice, ...]:
        return tuple(self._notices)

    def completion_notice(
        self,
        ref: AgentRef,
        *,
        round_id: int,
    ) -> AgentCompletionNotice | None:
        """Return one exact terminal notice for Host-side orchestration."""

        return next(
            (
                notice
                for notice in reversed(self._notices)
                if notice.sender_ref == ref and notice.round_id == round_id
            ),
            None,
        )

    def agent_type(self, name: str) -> AgentTypeSpec | None:
        return self._agent_types.resolve(name)

    def subscribe_facts(self, consumer: FactConsumer) -> Callable[[], None]:
        """Attach a best-effort live projection consumer."""

        self._fact_consumers.append(consumer)
        return lambda: _remove_consumer(self._fact_consumers, consumer)

    def subscribe_notices(self, consumer: NoticeConsumer) -> Callable[[], None]:
        """Attach a best-effort completion-notice consumer."""

        self._notice_consumers.append(consumer)
        return lambda: _remove_consumer(self._notice_consumers, consumer)

    def spawn(
        self,
        *,
        caller: ControlCaller,
        parent_path: AgentPath,
        name: str,
        agent_type: str,
    ) -> AgentRecord:
        caller_record = self._validate_caller(caller)
        parent = self._require_path(parent_path)
        self._require_control(caller, parent)
        spec = self._agent_types.resolve(agent_type)
        if spec is None:
            raise MultiAgentError(
                "invalid_agent_type",
                f"agent type is not admitted: {agent_type}",
            )
        if caller_record is not None and caller_record.path != AgentPath.root():
            caller_spec = self._agent_types.resolve(caller_record.agent_type)
            if caller_spec is None or not caller_spec.can_spawn:
                raise MultiAgentError(
                    "spawn_not_allowed",
                    f"agent type cannot spawn children: {caller_record.agent_type}",
                )
        if parent.path.depth + 1 > self._limits.max_spawn_depth:
            raise MultiAgentError(
                "agent_depth_exceeded",
                f"spawn would exceed depth {self._limits.max_spawn_depth}",
            )
        if (
            self._registry.open_count + self._registry.reserved_count
            >= self._limits.max_open_agents
        ):
            open_agents = self._registry.records()
            raise MultiAgentError(
                "agent_limit_reached",
                f"agent tree already has {self._limits.max_open_agents} open "
                "agents; completed, failed, and interrupted agents remain open "
                "until close_agent releases them",
                details={
                    "limit": self._limits.max_open_agents,
                    "open_count": self._registry.open_count,
                    "reserved_count": self._registry.reserved_count,
                    "open_agents": tuple(
                        _capacity_occupant(record) for record in open_agents
                    ),
                    "recovery": (
                        "Use list_agents, then reuse an existing child with "
                        "send_message or close an unneeded child before retrying "
                        "spawn_agent."
                    ),
                },
            )
        same_type_children = tuple(
            record
            for record in self._registry.children(parent.ref)
            if record.agent_type == agent_type
        )
        if len(same_type_children) >= spec.maximum_children:
            raise MultiAgentError(
                "agent_type_limit_reached",
                f"agent type {agent_type!r} allows at most "
                f"{spec.maximum_children} open children below {parent.path}; "
                "completed, failed, and interrupted children remain open until "
                "close_agent releases them",
                details={
                    "parent_path": str(parent.path),
                    "agent_type": agent_type,
                    "limit": spec.maximum_children,
                    "open_count": len(same_type_children),
                    "open_children": tuple(
                        _capacity_occupant(record)
                        for record in same_type_children
                    ),
                    "recovery": (
                        "Use list_agents, then reuse an existing child with "
                        "send_message or close an unneeded child before retrying "
                        "spawn_agent."
                    ),
                },
            )

        with self._registry.reserve(
            parent_ref=parent.ref,
            name=name,
            agent_type=agent_type,
        ) as reservation:
            record = reservation.commit()
        self._emit_fact("spawned", record)
        return record

    def begin_round(self, ref: AgentRef) -> AgentTransition:
        current = self._registry.get(ref, include_closed=True)
        if current is None:
            return AgentTransition(False, "stale_ref", None)
        if current.status == "closed":
            return AgentTransition(False, "closed", current)
        if current.status == "running":
            return AgentTransition(False, "invalid_state", current)
        record = self._registry.update(
            ref,
            status="running",
            round_id=current.round_id + 1,
        )
        self._emit_fact("status_changed", record)
        return AgentTransition(True, "applied", record)

    def record_progress(
        self,
        ref: AgentRef,
        *,
        round_id: int,
        latest_input_tokens: int | None = None,
        output_tokens_delta: int = 0,
        tool_uses_delta: int = 0,
        recent_activity: str | None = None,
        summary: _SummaryUpdate = _KEEP_SUMMARY,
    ) -> AgentTransition:
        current, reason = self._active_round(ref, round_id)
        if current is None:
            return AgentTransition(False, reason, self._current_snapshot(ref))
        if latest_input_tokens is not None and latest_input_tokens < 0:
            raise ValueError("latest_input_tokens must be non-negative")
        if output_tokens_delta < 0:
            raise ValueError("output_tokens_delta must be non-negative")
        if tool_uses_delta < 0:
            raise ValueError("tool_uses_delta must be non-negative")

        previous = current.progress
        progress = AgentProgress(
            usage=AgentUsage(
                latest_input_tokens=(
                    previous.usage.latest_input_tokens
                    if latest_input_tokens is None
                    else latest_input_tokens
                ),
                cumulative_output_tokens=(
                    previous.usage.cumulative_output_tokens + output_tokens_delta
                ),
            ),
            tool_uses=previous.tool_uses + tool_uses_delta,
            recent_activity=(
                previous.recent_activity if recent_activity is None else recent_activity
            ),
            summary=(
                previous.summary
                if isinstance(summary, _KeepSummary)
                else summary
            ),
        )
        record = self._registry.update(ref, progress=progress)
        self._emit_fact("progress", record, progress=progress)
        return AgentTransition(True, "applied", record)

    def bind_workspace(
        self,
        ref: AgentRef,
        *,
        workspace_ref: str,
    ) -> AgentRecord:
        """Attach an opaque Product workspace to an admitted child."""

        if not workspace_ref.strip():
            raise ValueError("workspace_ref must be non-empty")
        record = self._registry.update(
            ref,
            workspace_ref=workspace_ref,
            update_workspace=True,
        )
        self._emit_fact("workspace", record)
        return record

    def record_workspace_snapshot(
        self,
        ref: AgentRef,
        snapshot: WorkspaceLeaseSnapshot,
    ) -> AgentRecord:
        """Update opaque workspace state after Product inspection or release."""

        record = self._registry.update(
            ref,
            workspace_ref=snapshot.workspace_ref,
            artifact_refs=snapshot.artifact_refs,
            change_set_ref=snapshot.change_set_ref,
            update_workspace=True,
        )
        self._emit_fact("workspace", record)
        return record

    def finish_round(
        self,
        ref: AgentRef,
        *,
        round_id: int,
        status: TerminalStatus,
        final_message: str,
        duration_ms: int,
        summary: str | None = None,
        workspace_ref: str | None = None,
        artifact_refs: tuple[str, ...] = (),
        change_set_ref: str | None = None,
    ) -> AgentTransition:
        current = self._registry.get(ref, include_closed=True)
        if current is None:
            return AgentTransition(False, "stale_ref", None)
        if current.status == "closed":
            return AgentTransition(False, "closed", current)
        if current.round_id != round_id:
            return AgentTransition(False, "stale_round", current)
        notification_key = (ref, round_id)
        if current.status in {"completed", "failed", "interrupted"}:
            reason: TransitionReason = (
                "duplicate"
                if notification_key in self._notified_rounds
                else "invalid_state"
            )
            return AgentTransition(False, reason, current)
        if current.status != "running":
            return AgentTransition(False, "invalid_state", current)

        progress = (
            current.progress
            if summary is None
            else replace(current.progress, summary=summary)
        )
        record = self._registry.update(
            ref,
            status=status,
            progress=progress,
            workspace_ref=workspace_ref,
            artifact_refs=tuple(artifact_refs),
            change_set_ref=change_set_ref,
            update_workspace=True,
        )
        terminal = TerminalPayload(
            status=status,
            final_message=final_message,
            usage=progress.usage,
            duration_ms=duration_ms,
            tool_uses=progress.tool_uses,
        )
        self._notified_rounds.add(notification_key)
        self._emit_fact("terminal", record, progress=progress, terminal=terminal)

        notice = None
        if record.parent_ref is not None:
            notice = AgentCompletionNotice(
                notice_id=f"{ref}:{round_id}",
                sender_ref=ref,
                recipient_ref=record.parent_ref,
                round_id=round_id,
                terminal=terminal,
                summary=progress.summary,
                workspace_ref=record.workspace_ref,
                artifact_refs=record.artifact_refs,
                change_set_ref=record.change_set_ref,
            )
            self._publish_notice(notice)
        return AgentTransition(True, "applied", record, notice)

    def record_interrupted(
        self,
        ref: AgentRef,
        *,
        round_id: int,
        summary: str | None = None,
    ) -> AgentTransition:
        """Record an observed abort; a future RunHandle performs the abort."""

        return self.finish_round(
            ref,
            round_id=round_id,
            status="interrupted",
            final_message="Agent run interrupted.",
            duration_ms=0,
            summary=summary,
        )

    def route_message(
        self,
        *,
        caller: ControlCaller,
        target: str | AgentPath,
        text: str,
        kind: AgentMessageKind = "follow_up",
        references: tuple[str, ...] = (),
    ) -> DeliveryIntent:
        caller_record = self._validate_caller(caller)
        if isinstance(caller, HostCaller):
            if not isinstance(target, AgentPath) and not target.startswith("/"):
                raise MultiAgentError(
                    "agent_not_found",
                    "host callers must use a canonical target path",
                )
            try:
                path = (
                    target if isinstance(target, AgentPath) else AgentPath.parse(target)
                )
            except ValueError as error:
                raise MultiAgentError(
                    "agent_not_found", f"invalid agent path: {target}"
                ) from error
            recipient = self._require_path(path)
        else:
            assert caller_record is not None
            recipient = self._registry.resolve(
                caller_ref=caller_record.ref,
                target=target,
            )
        if not self._authority.allows_message(caller, recipient):
            raise MultiAgentError(
                "agent_authority_denied",
                f"caller cannot message {recipient.path}",
            )
        if kind not in {"follow_up", "steering"}:
            raise ValueError("agent message kind must be follow_up or steering")
        if not text.strip():
            raise ValueError("agent message text must be non-empty")

        self._message_sequence += 1
        message = AgentInputMessage(
            message_id=f"message-{self._message_sequence}",
            sender=caller,
            recipient_ref=recipient.ref,
            kind=kind,
            text=text,
            references=tuple(references),
        )
        return DeliveryIntent(
            message=message,
            target_status=recipient.status,
            requires_wake=recipient.status != "running",
        )

    def list_agents(
        self,
        *,
        caller: ControlCaller,
    ) -> tuple[AgentRecord, ...]:
        self._validate_caller(caller)
        return tuple(
            record
            for record in self._registry.records()
            if self._authority.allows_control(caller, record)
        )

    def authorize_control(
        self,
        *,
        caller: ControlCaller,
        target: AgentPath,
    ) -> AgentRecord:
        """Resolve one open target and enforce control authority."""

        self._validate_caller(caller)
        record = self._require_path(target)
        self._require_control(caller, record)
        return record

    def plan_close_tree(
        self,
        *,
        caller: ControlCaller,
        target: AgentPath,
    ) -> tuple[AgentRecord, ...]:
        """Authorize and order a subtree for physical close, without mutation."""

        self._validate_caller(caller)
        record = self._require_path(target)
        self._require_control(caller, record)
        return tuple(
            sorted(
                self._registry.subtree(record.ref),
                key=lambda item: item.path.depth,
                reverse=True,
            )
        )

    def commit_closed(self, ref: AgentRef) -> AgentTransition:
        """Commit one physical handle's release after its task is disposed.

        A session/tree owner closes descendants in depth order and calls this
        for each corresponding handle.  The pure control core deliberately
        does not abort or dispose live work itself.
        """

        current = self._registry.get(ref, include_closed=True)
        if current is None:
            return AgentTransition(False, "stale_ref", None)
        if current.status == "closed":
            return AgentTransition(False, "duplicate", current)
        record = self._registry.close(ref)
        self._emit_fact("closed", record)
        return AgentTransition(True, "applied", record)

    def _active_round(
        self,
        ref: AgentRef,
        round_id: int,
    ) -> tuple[
        AgentRecord | None,
        Literal["applied", "stale_ref", "stale_round", "closed", "invalid_state"],
    ]:
        current = self._registry.get(ref, include_closed=True)
        if current is None:
            return None, "stale_ref"
        if current.status == "closed":
            return None, "closed"
        if current.round_id != round_id:
            return None, "stale_round"
        if current.status != "running":
            return None, "invalid_state"
        return current, "applied"

    def _current_snapshot(self, ref: AgentRef) -> AgentRecord | None:
        return self._registry.current(ref.path, include_closed=True)

    def _validate_caller(self, caller: ControlCaller) -> AgentRecord | None:
        if isinstance(caller, HostCaller):
            return None
        record = self._registry.get(caller.ref)
        if record is None:
            raise MultiAgentError(
                "stale_caller",
                f"agent caller is no longer open: {caller.ref}",
            )
        return record

    def _require_path(self, path: AgentPath) -> AgentRecord:
        record = self._registry.current(path)
        if record is None:
            closed = self._registry.current(path, include_closed=True)
            code = "agent_not_addressable" if closed is not None else "agent_not_found"
            raise MultiAgentError(code, f"agent is not addressable: {path}")
        return record

    def _require_control(
        self,
        caller: ControlCaller,
        target: AgentRecord,
    ) -> None:
        if not self._authority.allows_control(caller, target):
            raise MultiAgentError(
                "agent_authority_denied",
                f"caller cannot control {target.path}",
            )

    def _emit_fact(
        self,
        kind: AgentFactKind,
        record: AgentRecord,
        *,
        progress: AgentProgress | None = None,
        terminal: TerminalPayload | None = None,
    ) -> None:
        self._fact_sequence += 1
        fact = AgentFact(
            sequence=self._fact_sequence,
            kind=kind,
            ref=record.ref,
            parent_ref=record.parent_ref,
            agent_type=record.agent_type,
            status=record.status,
            round_id=record.round_id,
            at=self._clock(),
            progress=progress,
            terminal=terminal,
            workspace_ref=record.workspace_ref,
            artifact_refs=record.artifact_refs,
            change_set_ref=record.change_set_ref,
        )
        self._facts.append(fact)
        for consumer in tuple(self._fact_consumers):
            try:
                consumer(fact)
            except Exception:
                continue

    def _publish_notice(self, notice: AgentCompletionNotice) -> None:
        self._notices.append(notice)
        for consumer in tuple(self._notice_consumers):
            try:
                consumer(notice)
            except Exception:
                continue


def _capacity_occupant(record: AgentRecord) -> dict[str, object]:
    return {
        "path": str(record.path),
        "agent_type": record.agent_type,
        "status": record.status,
        "round_id": record.round_id,
    }


def _remove_consumer(
    consumers: list[ConsumerT],
    consumer: ConsumerT,
) -> None:
    with suppress(ValueError):
        consumers.remove(consumer)


__all__ = [
    "DefaultAgentAuthorityPolicy",
    "FactConsumer",
    "MultiAgentControl",
    "NoticeConsumer",
]
