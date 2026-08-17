"""Policy evaluator and matcher protocols, rules, chains, and evaluation.

A policy rule (`PolicyRule`) is evaluation input that matches a subject and
yields allow/deny/ask; it is not a retained approval rule
(`loushang.harness.approval.rules.ApprovalPolicyRule`). See the terminology
conventions in policy-approval-redesign.md section 7.0.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias, TypeVar

from loushang.harness.policy.decisions import (
    PolicyDecision,
    PolicyEvaluationError,
)
from loushang.harness.policy.subjects import PolicySubject

PolicyChainStrategy = Literal[
    "first_non_allow",
    "most_restrictive",
    "first_decision",
]

T = TypeVar("T")
MaybeAwaitable: TypeAlias = T | Awaitable[T]


class PolicyEvaluator(Protocol):
    def evaluate(
        self,
        subject: PolicySubject,
        /,
    ) -> MaybeAwaitable[PolicyDecision | None]: ...


class PolicyMatcher(Protocol):
    def matches(self, subject: PolicySubject, /) -> bool: ...


@dataclass(frozen=True)
class PolicyRule:
    id: str
    matcher: PolicyMatcher
    decision: PolicyDecision

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("PolicyRule id must be a non-empty string")
        if not isinstance(self.decision, PolicyDecision):
            raise TypeError("PolicyRule decision must be a PolicyDecision")


@dataclass(frozen=True)
class RulePolicyEvaluator:
    rules: tuple[PolicyRule, ...]

    def __post_init__(self) -> None:
        normalized = tuple(self.rules)
        ids = [rule.id for rule in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("PolicyRule ids must be unique within an evaluator")
        object.__setattr__(self, "rules", normalized)

    def evaluate(self, subject: PolicySubject, /) -> PolicyDecision | None:
        for rule in self.rules:
            matched = rule.matcher.matches(subject)
            if not isinstance(matched, bool):
                raise TypeError(
                    f"Policy matcher for rule {rule.id!r} returned "
                    f"{type(matched).__name__}, expected bool"
                )
            if matched:
                return rule.decision
        return None


@dataclass(frozen=True)
class PolicyEvaluatorChain:
    evaluators: tuple[PolicyEvaluator, ...]
    strategy: PolicyChainStrategy = "most_restrictive"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluators", tuple(self.evaluators))
        if self.strategy not in {
            "first_non_allow",
            "most_restrictive",
            "first_decision",
        }:
            raise ValueError(f"Unsupported policy chain strategy: {self.strategy}")

    async def evaluate(self, subject: PolicySubject, /) -> PolicyDecision | None:
        if self.strategy == "first_decision":
            for evaluator in self.evaluators:
                decision = await evaluate_policy(evaluator, subject)
                if decision is not None:
                    return decision
            return None

        first_allow: PolicyDecision | None = None
        first_ask: PolicyDecision | None = None
        first_deny: PolicyDecision | None = None
        for evaluator in self.evaluators:
            decision = await evaluate_policy(evaluator, subject)
            if decision is None:
                continue
            if self.strategy == "first_non_allow":
                if decision.disposition != "allow":
                    return decision
                if first_allow is None:
                    first_allow = decision
                continue
            if decision.disposition == "deny" and first_deny is None:
                first_deny = decision
            elif decision.disposition == "ask" and first_ask is None:
                first_ask = decision
            elif decision.disposition == "allow" and first_allow is None:
                first_allow = decision

        if self.strategy == "first_non_allow":
            return first_allow
        return first_deny or first_ask or first_allow


async def evaluate_policy(
    evaluator: PolicyEvaluator,
    subject: PolicySubject,
) -> PolicyDecision | None:
    try:
        evaluate = getattr(evaluator, "evaluate", None)
        if not callable(evaluate):
            raise PolicyEvaluationError(
                f"Policy evaluator {type(evaluator).__name__} has no callable evaluate method"
            )
        result = evaluate(subject)
        if inspect.isawaitable(result):
            result = await result
    except PolicyEvaluationError:
        raise
    except Exception as exc:
        raise PolicyEvaluationError(
            f"Policy evaluator {type(evaluator).__name__} failed: {exc}"
        ) from exc
    if result is not None and not isinstance(result, PolicyDecision):
        raise PolicyEvaluationError(
            f"Policy evaluator {type(evaluator).__name__} returned "
            f"{type(result).__name__}, expected PolicyDecision or None"
        )
    if result is not None:
        try:
            result.__post_init__()
        except (TypeError, ValueError) as exc:
            raise PolicyEvaluationError(
                f"Policy evaluator {type(evaluator).__name__} returned an invalid "
                f"PolicyDecision: {exc}"
            ) from exc
    return result
