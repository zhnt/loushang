"""Goal's pure record component: immutable model, codec and history reducer.

No execution, storage or Product dependency belongs here. Codec entrypoints are
provided by this component; their implementation has no independent lifetime.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import cast


class GoalError(ValueError):
    """A rejected Goal contract, preserving the reason for the caller."""


class UnsupportedGoalVersion(GoalError):
    pass


def freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise GoalError("record keys must be strings")
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if type(value) is float and math.isfinite(value):
        return value
    if value is None or type(value) in (str, int, bool):
        return value
    raise GoalError("Goal data must contain finite JSON values")


def plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def document(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GoalError("expected an object")
    result = freeze(value)
    assert isinstance(result, Mapping)
    return result


def text(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise GoalError("expected a nonempty string")
    return value


def positive(value: object) -> int:
    if type(value) is not int or value < 1:
        raise GoalError("expected a positive integer")
    return value


def canonical(value: object) -> str:
    return json.dumps(
        plain(freeze(value)),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class GoalHeader:
    scope_id: str
    session_id: str
    policy_id: str
    policy_version: int = 1
    version: int = 1
    extensions: Mapping[str, object] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        for value in (self.scope_id, self.session_id, self.policy_id):
            text(value)
        positive(self.policy_version)
        object.__setattr__(self, "extensions", document(self.extensions))
        if type(self.version) is not int or self.version != 1:
            raise UnsupportedGoalVersion("unsupported Goal header version")


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str

    def __post_init__(self) -> None:
        text(self.id)
        text(self.text)


def requirements(value: object) -> tuple[Requirement, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise GoalError("requirements must be nonempty")
    result = tuple(
        Requirement(text(document(v).get("id")), text(document(v).get("text")))
        for v in value
    )
    if len({r.id for r in result}) != len(result):
        raise GoalError("duplicate requirement id")
    return result


@dataclass(frozen=True)
class GoalRecord:
    sequence: int
    scope_id: str
    goal_id: str
    kind: str
    command_id: str
    data: Mapping[str, object]
    version: int = 1
    extensions: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        positive(self.sequence)
        for value in (self.scope_id, self.goal_id, self.kind, self.command_id):
            text(value)
        if type(self.version) is not int or self.version != 1:
            raise UnsupportedGoalVersion("unsupported Goal record version")
        object.__setattr__(self, "data", document(self.data))
        object.__setattr__(self, "extensions", document(self.extensions))


@dataclass(frozen=True)
class GoalBatch:
    id: str
    goal_id: str
    operation_id: str
    revision: int
    epoch: int
    intent_sequence: int
    command_id: str
    source: Mapping[str, object]
    run_receipt: str | None = None
    not_submitted: bool = False


@dataclass(frozen=True)
class GoalState:
    id: str
    requirements: tuple[Requirement, ...]
    limit: int
    metadata: Mapping[str, object]
    revision: int = 1
    epoch: int = 1
    status: str = "active"
    reason: str = "created"
    acceptance: Mapping[str, object] | None = None


@dataclass(frozen=True)
class CommandReceipt:
    id: str
    goal_id: str
    request: str
    outcome: str = "pending"
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GoalHistory:
    header: GoalHeader
    records: tuple[GoalRecord, ...]
    goals: Mapping[str, GoalState]
    batches: tuple[GoalBatch, ...]
    commands: Mapping[str, CommandReceipt]

    @property
    def sequence(self) -> int:
        return len(self.records)

    def goal(self, goal_id: str) -> GoalState:
        if goal_id not in self.goals:
            raise GoalError("unknown Goal")
        return self.goals[goal_id]


KINDS = frozenset(
    {
        "command_received",
        "command_finished",
        "created",
        "requirements_revised",
        "control_changed",
        "replaced",
        "batch_intent",
        "batch_associated",
        "batch_not_submitted",
        "acceptance_decided",
    }
)
TERMINAL = frozenset({"completed", "abandoned", "failed", "superseded"})


def encode_header(header: GoalHeader) -> Mapping[str, object]:
    return {
        **cast(dict[str, object], plain(header.extensions)),
        "kind": "goal_header",
        "version": header.version,
        "scope_id": header.scope_id,
        "session_id": header.session_id,
        "policy_id": header.policy_id,
        "policy_version": header.policy_version,
    }


def _features(value: Mapping[str, object]) -> None:
    if "required_features" in value:
        features = value["required_features"]
        if not isinstance(features, (tuple, list)):
            raise GoalError("required_features must be a list")
        if features:
            raise UnsupportedGoalVersion("unknown required Goal semantics")


def decode_header(value: Mapping[str, object]) -> GoalHeader:
    _features(value)
    if value.get("kind") != "goal_header" or value.get("required_features", ()):
        raise UnsupportedGoalVersion("unknown Goal header semantics")
    return GoalHeader(
        text(value.get("scope_id")),
        text(value.get("session_id")),
        text(value.get("policy_id")),
        positive(value.get("policy_version")),
        positive(value.get("version")),
        {
            k: v
            for k, v in value.items()
            if k
            not in {
                "kind",
                "version",
                "scope_id",
                "session_id",
                "policy_id",
                "policy_version",
            }
        },
    )


def encode_record(record: GoalRecord) -> Mapping[str, object]:
    return {
        **cast(dict[str, object], plain(record.extensions)),
        "version": record.version,
        "sequence": record.sequence,
        "scope_id": record.scope_id,
        "goal_id": record.goal_id,
        "kind": record.kind,
        "command_id": record.command_id,
        "data": plain(record.data),
    }


def decode_record(value: Mapping[str, object]) -> GoalRecord:
    _features(value)
    if value.get("required_features", ()):
        raise UnsupportedGoalVersion("unsupported Goal required feature")
    if value.get("kind") not in KINDS:
        raise UnsupportedGoalVersion("unsupported Goal record kind")
    keys = {"version", "sequence", "scope_id", "goal_id", "kind", "command_id", "data"}
    return GoalRecord(
        positive(value.get("sequence")),
        text(value.get("scope_id")),
        text(value.get("goal_id")),
        text(value.get("kind")),
        text(value.get("command_id")),
        document(value.get("data")),
        positive(value.get("version")),
        {k: v for k, v in value.items() if k not in keys},
    )


def replay(header: GoalHeader, records: Sequence[GoalRecord]) -> GoalHistory:
    """Validate logical history only; original Work facts remain external."""
    goals: dict[str, GoalState] = {}
    commands: dict[str, CommandReceipt] = {}
    batches: dict[str, GoalBatch] = {}
    operations: set[str] = set()
    effects: dict[str, set[str]] = {}
    for seq, raw in enumerate(records, 1):
        record = decode_record(encode_record(raw))
        if record.sequence != seq or record.scope_id != header.scope_id:
            raise GoalError("record sequence or scope mismatch")
        d, gid, cid = record.data, record.goal_id, record.command_id
        if record.kind == "command_received":
            if cid in commands:
                raise GoalError("duplicate command admission")
            request = text(d.get("request"))
            parsed = json.loads(request)
            if (
                not isinstance(parsed, dict)
                or parsed.get("goal_id") != gid
                or set(parsed) != {"action", "goal_id", "revision", "epoch", "data"}
                or canonical(parsed) != request
                or type(parsed.get("revision")) is not int
                or type(parsed.get("epoch")) is not int
                or parsed.get("action")
                not in {
                    "create",
                    "advance",
                    "revise",
                    "pause",
                    "resume",
                    "abandon",
                    "fail",
                    "replace",
                }
            ):
                raise GoalError("command request identity mismatch")
            if gid in goals:
                g = goals[gid]
                if (parsed.get("revision"), parsed.get("epoch")) != (
                    g.revision,
                    g.epoch,
                ):
                    raise GoalError("command expected version mismatch")
            elif parsed.get("action") != "create":
                raise GoalError("command precedes Goal")
            if parsed["action"] == "create" and (
                parsed["revision"],
                parsed["epoch"],
            ) != (0, 0):
                raise GoalError("create must name the initial Goal version")
            commands[cid] = CommandReceipt(cid, gid, request)
            continue
        command = commands.get(cid)
        if command is None or command.goal_id != gid or command.outcome != "pending":
            raise GoalError("missing, foreign or finished causation command")
        action = json.loads(command.request)["action"]
        allowed = {
            "created": {"create"},
            "requirements_revised": {"revise"},
            "replaced": {"replace"},
            "control_changed": {"pause", "resume", "abandon", "fail", "advance"},
            "batch_intent": {"advance"},
            "batch_associated": {"advance"},
            "batch_not_submitted": {"advance"},
            "acceptance_decided": {"advance"},
            "command_finished": {
                "create",
                "advance",
                "revise",
                "pause",
                "resume",
                "abandon",
                "fail",
                "replace",
            },
        }
        if action not in allowed[record.kind]:
            raise GoalError("record does not match causation command action")
        if record.kind != "command_finished":
            seen = effects.setdefault(cid, set())
            if record.kind in seen:
                raise GoalError("duplicate command effect")
            request_data = json.loads(command.request)["data"]
            if (
                record.kind in {"created", "requirements_revised", "replaced"}
                or (record.kind == "control_changed" and action != "advance")
            ) and canonical(d) != canonical(request_data):
                raise GoalError("effect differs from accepted command data")
            if record.kind == "control_changed":
                expected_status = {
                    "pause": "paused",
                    "resume": "active",
                    "abandon": "abandoned",
                    "fail": "failed",
                }.get(action, "paused")
                if d.get("status") != expected_status:
                    raise GoalError("control effect does not match action")
                if action == "advance" and set(d) != {"status", "reason"}:
                    raise GoalError("advance cannot revise control policy")
            seen.add(record.kind)
        if record.kind == "command_finished":
            if d.get("outcome") == "pending":
                raise GoalError("finished command cannot remain pending")
            commands[cid] = replace(
                command,
                outcome=text(d.get("outcome")),
                details=document(d.get("details", {})),
            )
            continue
        if record.kind == "created":
            if gid in goals:
                raise GoalError("Goal already exists")
            goals[gid] = GoalState(
                gid,
                requirements(d.get("requirements")),
                positive(d.get("limit")),
                document(d.get("metadata", {})),
            )
        else:
            if gid not in goals:
                raise GoalError("record precedes Goal")
            g = goals[gid]
            if record.kind == "requirements_revised":
                if g.status in {"abandoned", "failed", "superseded"}:
                    raise GoalError("cannot revise this terminal Goal")
                goals[gid] = replace(
                    g,
                    requirements=requirements(d.get("requirements")),
                    revision=g.revision + 1,
                    epoch=g.epoch + 1,
                    status="paused" if g.status == "paused" else "active",
                    reason=text(d.get("reason")),
                    acceptance=None,
                )
            elif record.kind == "control_changed":
                status = text(d.get("status"))
                if (
                    status not in {"active", "paused", "abandoned", "failed"}
                    or g.status in TERMINAL
                    or (status == "active" and g.status != "paused")
                ):
                    raise GoalError("invalid Goal control transition")
                goals[gid] = replace(
                    g,
                    status=status,
                    reason=text(d.get("reason")),
                    epoch=g.epoch + 1,
                    limit=positive(d.get("limit", g.limit)),
                )
            elif record.kind == "replaced":
                new_id = text(d.get("new_goal_id"))
                if g.status in TERMINAL or new_id in goals:
                    raise GoalError("invalid Goal replacement")
                goals[gid] = replace(
                    g,
                    status="superseded",
                    epoch=g.epoch + 1,
                    reason=text(d.get("reason")),
                )
                goals[new_id] = GoalState(
                    new_id,
                    requirements(d.get("requirements")),
                    positive(d.get("limit")),
                    document(d.get("metadata", {})),
                )
            elif record.kind == "batch_intent":
                bid, op = text(d.get("batch_id")), text(d.get("operation_id"))
                basis = document(d.get("basis"))
                if (
                    g.status != "active"
                    or bid in batches
                    or op in operations
                    or sum(b.goal_id == gid for b in batches.values()) >= g.limit
                    or any(b.command_id == cid for b in batches.values())
                    or canonical(basis) != canonical(basis_data(header, g, seq - 1))
                ):
                    raise GoalError("invalid batch intent or stale basis")
                if not document(d.get("source")):
                    raise GoalError("batch requires a frozen source snapshot")
                batches[bid] = GoalBatch(
                    bid,
                    gid,
                    op,
                    g.revision,
                    g.epoch,
                    seq,
                    cid,
                    document(d.get("source")),
                )
                operations.add(op)
            elif record.kind in {"batch_associated", "batch_not_submitted"}:
                bid = text(d.get("batch_id"))
                b = batches.get(bid)
                if (
                    b is None
                    or b.goal_id != gid
                    or b.command_id != cid
                    or b.run_receipt is not None
                    or b.not_submitted
                    or d.get("operation_id") != b.operation_id
                ):
                    raise GoalError("invalid or contradictory batch closure")
                if record.kind == "batch_associated":
                    batches[bid] = replace(b, run_receipt=text(d.get("run_id")))
                else:
                    batches[bid] = replace(b, not_submitted=True)
            elif record.kind == "acceptance_decided":
                coverage = d.get("coverage")
                required = d.get("operations")
                if (
                    g.status != "active"
                    or canonical(d.get("basis"))
                    != canonical(basis_data(header, g, seq - 1))
                    or not isinstance(coverage, tuple)
                    or set(coverage) != {r.id for r in g.requirements}
                    or len(coverage) != len(g.requirements)
                    or not document(d.get("proof"))
                    or not isinstance(required, tuple)
                    or not required
                ):
                    raise GoalError("invalid completion basis or proof")
                for op in required:
                    if not any(
                        b.operation_id == op
                        and b.goal_id == gid
                        and b.revision == g.revision
                        and b.epoch == g.epoch
                        and b.run_receipt is not None
                        for b in batches.values()
                    ):
                        raise GoalError("completion cites unknown or old operation")
                goals[gid] = replace(
                    g, status="completed", reason="requirements_satisfied", acceptance=d
                )
            else:
                raise UnsupportedGoalVersion("unknown Goal semantics")
        if sum(g.status not in TERMINAL for g in goals.values()) > 1:
            raise GoalError("scope already has an active Goal")
    return GoalHistory(
        header,
        tuple(records),
        MappingProxyType(goals),
        tuple(batches.values()),
        MappingProxyType(commands),
    )


def basis_data(
    header: GoalHeader, goal: GoalState, sequence: int
) -> Mapping[str, object]:
    return document(
        {
            "scope_id": header.scope_id,
            "session_id": header.session_id,
            "goal_id": goal.id,
            "revision": goal.revision,
            "epoch": goal.epoch,
            "sequence": sequence,
            "policy_id": header.policy_id,
            "policy_version": header.policy_version,
        }
    )
