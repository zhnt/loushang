from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.harness.permissions import (
    PermissionProfileCeiling,
    PermissionProfilePolicyEvaluator,
    permission_profile_snapshot,
)
from loushang.harness.policy import (
    PolicyDecision,
    ToolPolicySubject,
)


@dataclass(frozen=True)
class _Policy:
    decision: PolicyDecision

    def evaluate(self, subject: object) -> PolicyDecision:
        del subject
        return self.decision


def _evaluate(
    *,
    profile: str,
    decision: PolicyDecision,
    tool_name: str = "bash",
    ceiling: PermissionProfileCeiling | None = None,
) -> PolicyDecision:
    evaluator = PermissionProfilePolicyEvaluator(
        _Policy(decision),
        profile_provider=lambda: profile,  # type: ignore[arg-type]
        ceiling_provider=lambda: ceiling or PermissionProfileCeiling(),
    )
    return asyncio.run(
        evaluator.evaluate(
            ToolPolicySubject(tool_name=tool_name, arguments={})
        )
    )


def test_permission_profile_snapshot_applies_the_managed_ceiling() -> None:
    snapshot = permission_profile_snapshot(
        "full_access",
        PermissionProfileCeiling(
            maximum_profile="standard",
            reason="Managed environment limits this session.",
        ),
    )

    assert snapshot.requested_profile_id == "full_access"
    assert snapshot.effective_profile.profile_id == "standard"
    full_access = next(
        option
        for option in snapshot.options
        if option.profile.profile_id == "full_access"
    )
    assert full_access.enabled is False
    assert full_access.disabled_reason == "Managed environment limits this session."


def test_standard_profile_preserves_policy_decisions() -> None:
    ask = PolicyDecision.ask("Publish refs", code="git_publish")

    assert _evaluate(profile="standard", decision=ask) == ask


def test_full_access_skips_optional_approval_but_never_managed_deny() -> None:
    assert _evaluate(
        profile="full_access",
        decision=PolicyDecision.ask("Delete files", code="delete"),
    ) == PolicyDecision(disposition="allow", code="delete")

    deny = PolicyDecision.deny("Managed deny", code="managed_deny")
    assert _evaluate(profile="full_access", decision=deny) == deny


def test_managed_ceiling_makes_a_full_access_request_effectively_standard() -> None:
    ask = PolicyDecision.ask("Publish refs", code="git_publish")

    assert _evaluate(
        profile="full_access",
        decision=ask,
        ceiling=PermissionProfileCeiling(maximum_profile="standard"),
    ) == ask


@pytest.mark.parametrize("tool_name", ["write", "edit"])
def test_cautious_profile_asks_before_direct_workspace_mutations(
    tool_name: str,
) -> None:
    decision = _evaluate(
        profile="cautious",
        decision=PolicyDecision.allow(),
        tool_name=tool_name,
    )

    assert decision.disposition == "ask"
    assert decision.code == "cautious_workspace_mutation"


def test_cautious_profile_does_not_add_prompts_to_read_only_tools() -> None:
    assert _evaluate(
        profile="cautious",
        decision=PolicyDecision.allow(),
        tool_name="read",
    ) == PolicyDecision.allow()
