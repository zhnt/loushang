"""Coding-owned Session choice and immutable history material over Harness forks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from loushang.ai.json_codec import deserialize_message, serialize_message
from loushang.ai.tool.transform import MessagePairingError, transform_messages_result
from loushang.harness.multiagent import (
    AgentRef,
    ControlLimits,
    ForkTier,
)
from loushang.harness.session.multiagent import build_agent_context_plan
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import canonical

from ._goal_driver import digest

TOOLS = ("read", "edit", "write")
MAPPER = "coding-goal-history/v1"
OPERATION_KIND = "coding.goal.delegated_method"
ROLE = "delegated_method_report"


@dataclass(frozen=True)
class SessionChoice:
    mode: str
    target: AgentRef | None = None
    tier: ForkTier = field(default_factory=ForkTier.none)
    allow_empty: bool = False
    reason: str = "host_policy"

    def __post_init__(self):
        if not isinstance(self.mode, str) or self.mode not in {
            "reuse",
            "fresh",
            "inherit",
        }:
            raise GoalError("unsupported Goal Session choice")
        if not isinstance(self.tier, ForkTier) or type(self.allow_empty) is not bool:
            raise GoalError("invalid Goal history selection")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 2048
        ):
            raise GoalError("invalid Goal context selection reason")
        if self.mode == "reuse":
            if not isinstance(self.target, AgentRef):
                raise GoalError("reuse requires an exact AgentRef")
        elif self.target is not None:
            raise GoalError("new Session must not name an existing child")
        if (self.mode == "inherit") != (self.tier.mode != "none"):
            raise GoalError("only inherit selects nonempty history tiers")
        if self.mode != "inherit" and self.allow_empty:
            raise GoalError("empty-history fallback applies only to inherit")


@dataclass(frozen=True)
class SessionExecutionPolicy:
    """None choice: fresh initially, then reuse the last verified live child."""

    choice: SessionChoice | None = None
    limits: ControlLimits = field(default_factory=ControlLimits)

    def __post_init__(self):
        if self.choice is not None and not isinstance(self.choice, SessionChoice):
            raise GoalError("invalid Goal execution policy")
        if not isinstance(self.limits, ControlLimits):
            raise GoalError("invalid child control limits")


def ref_data(ref):
    return {"path": str(ref.path), "incarnation": ref.incarnation}


def message_digest(messages):
    return digest(canonical([serialize_message(m) for m in messages]).encode())


def detach_message(message):
    return deserialize_message(json.loads(canonical(serialize_message(message))))


def build_context(
    *, session, blobs, choice, system_prompt, source_identity, watermark=None
):
    plan, watermark = build_agent_context_plan(
        session=session,
        blobs=blobs,
        choice=choice,
        watermark=watermark,
        system_prompt=system_prompt,
        allowed_tools=TOOLS,
        error_type=GoalError,
        detach_message=detach_message,
    )
    return plan, context_material(
        session_id=session.session_id,
        source_identity=source_identity,
        choice=choice,
        plan=plan,
        watermark=watermark,
    )


def context_material(*, session_id, source_identity, choice, plan, watermark):
    history = plan.history
    if (
        choice.mode == "inherit"
        and history.effective_tier.mode == "none"
        and not choice.allow_empty
    ):
        raise GoalError("inherited history is empty; fallback was not authorized")
    try:
        normalized = transform_messages_result(
            list(history.messages), pairing_mode="strict"
        )
    except MessagePairingError as error:
        raise GoalError("inherited history needs tool/message repair") from error
    if normalized.diagnostics or normalized.messages != list(history.messages):
        raise GoalError("inherited history needs tool/message repair")
    material = {
        "mapper": MAPPER,
        "source_session_id": session_id if watermark else None,
        "source_store_identity": source_identity if watermark else None,
        "watermark": watermark,
        "requested_tier": choice.tier.mode,
        "turns": choice.tier.turns,
        "effective_tier": history.effective_tier.mode,
        "allow_empty": choice.allow_empty,
        "messages_sha256": message_digest(history.messages),
        "diagnostics": [d.code for d in history.diagnostics],
    }
    return material
