"""Private calculator planning schema, never an execution or acceptance authority."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass

from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import canonical

POLICY_ID = "coding-calculator-model-planning/v1"
TARGETS = frozenset({"subtraction", "clamp"})
REQUIREMENT_IDS = frozenset({"R-SUB", "R-CLAMP", "R-FILES"})
EXPECTED_EVIDENCE = {
    "inspect": frozenset({"goal_inspection_report"}),
    "check": frozenset({"report", "validation"}),
    "repair": frozenset({"method_execution"}),
    "verify_all": frozenset({"report", "validation"}),
    "stop": frozenset(),
}
LIMITS = {
    "work_intents": 20,
    "planning_intents": 10,
    "invalid_proposals": 3,
    "no_progress": 2,
    "planning_calls": 1,
    "repair_calls": 12,
    "provider_attempts": 3,
}
_KEYS = {
    "next_action",
    "targets",
    "requirement_ids",
    "rationale",
    "expected_evidence",
    "remaining_route",
    "change_reason",
    "evidence_refs",
}


class ProposalRejected(GoalError):
    """A model candidate cannot be consumed; its text is still retained evidence."""


def _text(value: object, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise ProposalRejected("expected proposal string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ProposalRejected("invalid proposal Unicode") from error
    if size > 2048 or (not empty and not value.strip()):
        raise ProposalRejected("proposal string empty or too long")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProposalRejected("expected proposal string array")
    result = tuple(_text(item) for item in value)
    if len(result) != len(set(result)):
        raise ProposalRejected("duplicate proposal array entry")
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProposalRejected("duplicate proposal key")
        result[key] = value
    return result


def _constant(value):
    raise ProposalRejected("nonfinite proposal value")


@dataclass(frozen=True)
class Action:
    name: str
    targets: tuple[str, ...]

    @classmethod
    def parse(cls, name: object, targets: object) -> Action:
        name = _text(name)
        if name not in EXPECTED_EVIDENCE:
            raise ProposalRejected("unknown planning action")
        selected = tuple(sorted(_strings(targets)))
        if name in {"inspect", "check"}:
            if not selected or not set(selected) <= TARGETS:
                raise ProposalRejected("unknown or empty inspection/check targets")
        elif name == "repair":
            if selected != ("calculator",):
                raise ProposalRejected("repair requires whole-calculator scope")
        elif selected:
            raise ProposalRejected("verify_all/stop do not take targets")
        return cls(name, selected)

    @property
    def required_requirements(self) -> frozenset[str]:
        if self.name in {"repair", "verify_all"}:
            return REQUIREMENT_IDS
        return frozenset(
            "R-SUB" if target == "subtraction" else "R-CLAMP" for target in self.targets
        )

    @property
    def effect(self) -> tuple[str, tuple[str, ...]]:
        """Comparison only: check focus and verification role aren't new execution."""
        if self.name in {"check", "verify_all"}:
            return "check_all", ()
        return self.name, self.targets

    def data(self) -> dict[str, object]:
        return {"action": self.name, "targets": list(self.targets)}


@dataclass(frozen=True)
class Proposal:
    action: Action
    requirement_ids: tuple[str, ...]
    rationale: str
    expected_evidence: tuple[str, ...]
    remaining_route: tuple[Action, ...]
    change_reason: str
    evidence_refs: tuple[str, ...]

    def data(self) -> dict[str, object]:
        return {
            "next_action": self.action.name,
            "targets": list(self.action.targets),
            "requirement_ids": list(self.requirement_ids),
            "rationale": self.rationale,
            "expected_evidence": list(self.expected_evidence),
            "remaining_route": [item.data() for item in self.remaining_route],
            "change_reason": self.change_reason,
            "evidence_refs": list(self.evidence_refs),
        }


def parse_proposal(raw: bytes, *, known_evidence: Collection[str]) -> Proposal:
    """Decode only model-owned fields. Identity and authority come from the owner."""
    if not raw or len(raw) > 16 * 1024:
        raise ProposalRejected("proposal exceeds response limit or is empty")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProposalRejected("invalid single JSON proposal") from error
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise ProposalRejected("proposal fields do not match v1")
    action = Action.parse(value["next_action"], value["targets"])
    requirements = _strings(value["requirement_ids"])
    if not set(
        requirements
    ) <= REQUIREMENT_IDS or not action.required_requirements <= set(requirements):
        raise ProposalRejected("requirements do not cover action scope")
    expected = _strings(value["expected_evidence"])
    # Templates fix evidence expectations; a model cannot create a new proof kind.
    if set(expected) != EXPECTED_EVIDENCE[action.name]:
        raise ProposalRejected("expected evidence does not match action contract")
    route = value["remaining_route"]
    if not isinstance(route, list) or not 1 <= len(route) <= 6:
        raise ProposalRejected("route must contain one to six actions")
    actions = []
    for entry in route:
        if not isinstance(entry, dict) or set(entry) != {"action", "targets"}:
            raise ProposalRejected("invalid route entry")
        actions.append(Action.parse(entry["action"], entry["targets"]))
    if actions[0] != action:
        raise ProposalRejected("route does not begin with selected action")
    refs = _strings(value["evidence_refs"])
    if not set(refs) <= set(known_evidence):
        raise ProposalRejected("proposal cites unknown evidence")
    return Proposal(
        action,
        requirements,
        _text(value["rationale"]),
        expected,
        tuple(actions),
        _text(value["change_reason"], empty=True),
        refs,
    )


def planning_instructions() -> str:
    """Describe choices, never prescribe the order of implementation actions."""
    return (
        "Choose the next action and a revisable remaining route from current evidence. "
        "Do not change the goal, tests, Method, permissions or limits. "
        "Return exactly one JSON object, no fences or commentary. Keys: next_action, "
        "targets, requirement_ids, rationale, expected_evidence, remaining_route, "
        "change_reason, evidence_refs. remaining_route is 1-6 objects with action and "
        "targets, beginning with the selected action; its tail is not authorized. "
        "rationale and change_reason are strings (each <=2048 UTF-8 bytes); "
        "other fields except next_action are arrays. evidence_refs must use supplied "
        "evidence IDs. Explain route changes using newly observed facts. "
        "inspect/check take nonempty targets from subtraction/clamp. check always "
        "runs all fixed tests and reveals the full result; targets are focus labels. "
        "repair targets must be [calculator], requires a current failing check or "
        "verify_all report, and runs the fixed Method over the whole calculator. "
        "verify_all/stop take []; stop explains its reason in rationale. "
        "repair/verify_all must cover R-SUB,R-CLAMP,R-FILES; inspect/check cover "
        "R-SUB for subtraction and R-CLAMP for clamp. Model claims never complete "
        "the Goal. expected_evidence must match this action table: "
        + canonical({key: sorted(value) for key, value in EXPECTED_EVIDENCE.items()})
        + ". method_execution means the original Work/Method execution facts, "
        "not a new artifact or proof that tests pass. Response limit: 16 KiB."
    )
