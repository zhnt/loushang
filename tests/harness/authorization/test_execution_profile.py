from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.approval import ApprovalDecision
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
    constrain_execution_profile,
    resolve_effective_execution_profile,
)
from loushang.harness.policy import PolicyDecision


def test_execution_profile_intersection_cannot_widen_a_ceiling(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    child = workspace / "child"
    outside = tmp_path / "outside"
    ceiling = EffectiveExecutionProfile(
        readable_roots=(workspace,),
        writable_roots=(workspace,),
        denied_roots=(workspace / "secret",),
        network="restricted",
    )
    requested = EffectiveExecutionProfile(
        readable_roots=(child, outside),
        writable_roots=(child, outside),
        denied_roots=(workspace / "generated-secret",),
        network="allowed",
    )

    effective = constrain_execution_profile(ceiling, requested)

    assert effective.readable_roots == (child,)
    assert effective.writable_roots == (child,)
    assert effective.network == "restricted"
    assert effective.denied_roots == (
        workspace / "secret",
        workspace / "generated-secret",
    )


def test_policy_and_approval_resolve_one_frozen_execution_profile(
    tmp_path: Path,
) -> None:
    ceiling = EffectiveExecutionProfile(
        readable_roots=(tmp_path,),
        writable_roots=(tmp_path,),
    )
    decision = PolicyDecision.ask("publish requires approval", code="vcs.publish")

    with pytest.raises(ExecutionAuthorizationError, match="requires approval"):
        resolve_effective_execution_profile(
            ceiling=ceiling,
            decision=decision,
        )

    effective = resolve_effective_execution_profile(
        ceiling=ceiling,
        decision=decision,
        approval=ApprovalDecision.allow(),
        approval_action_id="approval-1",
    )

    assert effective.policy_code == "vcs.publish"
    assert effective.approval_action_id == "approval-1"


def test_broad_request_is_narrowed_to_the_ceiling_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    effective = constrain_execution_profile(
        EffectiveExecutionProfile(
            readable_roots=(workspace,),
            writable_roots=(workspace,),
        ),
        EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            writable_roots=(tmp_path,),
        ),
    )

    assert effective.readable_roots == (workspace,)
    assert effective.writable_roots == (workspace,)


def test_policy_deny_never_produces_an_execution_profile(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAuthorizationError, match="blocked"):
        resolve_effective_execution_profile(
            ceiling=EffectiveExecutionProfile(readable_roots=(tmp_path,)),
            decision=PolicyDecision.deny("blocked"),
            approval=ApprovalDecision.allow(),
        )
