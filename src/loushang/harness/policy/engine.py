"""Default Product-injected rule engine over the harness policy primitives.

Implements the policy runtime (§12.1) of
docs/internals/architecture/harness/policy-approval-redesign.md: composes
declarative rule/matcher configuration with heuristic effect detection
(`loushang.harness.policy.effects_detection`) into a `PolicyEvaluator` that Products
configure with their own rules, blocked/ask substrings, and defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loushang.harness.policy.decisions import PolicyDecision
from loushang.harness.policy.effects_detection import detect_policy_effects
from loushang.harness.policy.evaluators import PolicyRule, RulePolicyEvaluator
from loushang.harness.policy.matchers import (
    CapabilityIdMatcher,
    CommandSubstringMatcher,
    ExactToolNameMatcher,
    PathSubstringMatcher,
)
from loushang.harness.policy.subjects import PolicySubject

_DEFAULT_BLOCKED_SUBSTRINGS: tuple[str, ...] = ()
_DEFAULT_ASK_SUBSTRINGS: tuple[str, ...] = ()


def _normalize_substrings(
    values: tuple[str, ...] | list[str],
    field_name: str,
    defaults: tuple[str, ...],
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a sequence of strings, not a string")

    normalized: list[str] = list(defaults)
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a sequence of strings")
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _normalize_strings(
    values: tuple[str, ...] | list[str],
    field_name: str,
) -> tuple[str, ...]:
    return _normalize_substrings(values, field_name, ())


@dataclass(frozen=True)
class PolicyEngine:
    """Reusable workspace policy evaluator assembled from product rules."""

    rule_id_prefix: str = "workspace"
    blocked_substrings: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_BLOCKED_SUBSTRINGS
    )
    ask_substrings: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_ASK_SUBSTRINGS
    )
    blocked_tools: tuple[str, ...] = field(default_factory=tuple)
    ask_tools: tuple[str, ...] = field(default_factory=tuple)
    blocked_path_substrings: tuple[str, ...] = field(default_factory=tuple)
    ask_path_substrings: tuple[str, ...] = field(default_factory=tuple)
    blocked_capabilities: tuple[str, ...] = field(default_factory=tuple)
    ask_capabilities: tuple[str, ...] = field(default_factory=tuple)
    _evaluator: RulePolicyEvaluator = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id_prefix, str) or not self.rule_id_prefix:
            raise ValueError("rule_id_prefix must be a non-empty string")
        object.__setattr__(
            self,
            "blocked_substrings",
            _normalize_substrings(
                self.blocked_substrings,
                "blocked_substrings",
                _DEFAULT_BLOCKED_SUBSTRINGS,
            ),
        )
        object.__setattr__(
            self,
            "ask_substrings",
            _normalize_substrings(
                self.ask_substrings,
                "ask_substrings",
                _DEFAULT_ASK_SUBSTRINGS,
            ),
        )
        object.__setattr__(
            self,
            "blocked_tools",
            _normalize_strings(self.blocked_tools, "blocked_tools"),
        )
        object.__setattr__(
            self,
            "ask_tools",
            _normalize_strings(self.ask_tools, "ask_tools"),
        )
        object.__setattr__(
            self,
            "blocked_capabilities",
            _normalize_strings(
                self.blocked_capabilities,
                "blocked_capabilities",
            ),
        )
        object.__setattr__(
            self,
            "ask_capabilities",
            _normalize_strings(self.ask_capabilities, "ask_capabilities"),
        )
        object.__setattr__(
            self,
            "blocked_path_substrings",
            _normalize_strings(
                self.blocked_path_substrings,
                "blocked_path_substrings",
            ),
        )
        object.__setattr__(
            self,
            "ask_path_substrings",
            _normalize_strings(
                self.ask_path_substrings,
                "ask_path_substrings",
            ),
        )
        object.__setattr__(self, "_evaluator", RulePolicyEvaluator(self._rules()))

    def evaluate(self, subject: PolicySubject, /) -> PolicyDecision:
        configured = self._evaluator.evaluate(subject)
        if configured is not None:
            return configured
        effects = detect_policy_effects(subject)
        if effects:
            effect = effects[0]
            return PolicyDecision.ask(effect.summary, code=effect.code)
        return PolicyDecision.allow()

    def _rules(self) -> tuple[PolicyRule, ...]:
        rules: list[PolicyRule] = []
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.capability.block.{index}",
                matcher=CapabilityIdMatcher(capability_id),
                decision=PolicyDecision.deny(
                    f"Capability {capability_id} is blocked by policy",
                    code="capability_blocked",
                ),
            )
            for index, capability_id in enumerate(self.blocked_capabilities)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.tool.block.{index}",
                matcher=ExactToolNameMatcher(tool_name),
                decision=PolicyDecision.deny(
                    f"Tool {tool_name} is blocked by policy",
                    code="tool_blocked",
                ),
            )
            for index, tool_name in enumerate(self.blocked_tools)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.tool.ask.{index}",
                matcher=ExactToolNameMatcher(tool_name),
                decision=PolicyDecision.ask(
                    f"Tool {tool_name} requires approval",
                    code="tool_requires_approval",
                ),
            )
            for index, tool_name in enumerate(self.ask_tools)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.command.block.{index}",
                matcher=CommandSubstringMatcher(substring),
                decision=PolicyDecision.deny(
                    f"Blocked destructive command substring: {substring}",
                    code="command_blocked",
                ),
            )
            for index, substring in enumerate(self.blocked_substrings)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.command.ask.{index}",
                matcher=CommandSubstringMatcher(substring),
                decision=PolicyDecision.ask(
                    f"Approval recommended for command substring: {substring}",
                    code="command_requires_approval",
                ),
            )
            for index, substring in enumerate(self.ask_substrings)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.path.block.{index}",
                matcher=PathSubstringMatcher(substring),
                decision=PolicyDecision.deny(
                    f"Path is blocked by policy substring: {substring}",
                    code="path_blocked",
                ),
            )
            for index, substring in enumerate(self.blocked_path_substrings)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.path.ask.{index}",
                matcher=PathSubstringMatcher(substring),
                decision=PolicyDecision.ask(
                    f"Approval recommended for path substring: {substring}",
                    code="path_requires_approval",
                ),
            )
            for index, substring in enumerate(self.ask_path_substrings)
        )
        rules.extend(
            PolicyRule(
                id=f"{self.rule_id_prefix}.capability.ask.{index}",
                matcher=CapabilityIdMatcher(capability_id),
                decision=PolicyDecision.ask(
                    f"Capability {capability_id} requires approval",
                    code="capability_requires_approval",
                ),
            )
            for index, capability_id in enumerate(self.ask_capabilities)
        )
        return tuple(rules)
