from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.approval import ApprovalDecision
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
    constrain_execution_profile,
    execution_profile_expansion_codes,
    resolve_effective_execution_profile,
    select_execution_profile,
)
from loushang.harness.policy import PolicyDecision


def test_live_selection_cannot_widen_or_remove_execution_ceilings(tmp_path: Path) -> None:
    from loushang.harness.workspace.exec import ExecService

    ceiling = EffectiveExecutionProfile(
        readable_roots=(tmp_path,), denied_roots=(tmp_path / "secret",), network="denied",
    )
    requested = EffectiveExecutionProfile(
        readable_roots=(tmp_path.parent,), writable_roots=(tmp_path.parent,),
    )
    assert select_execution_profile(ceiling, lambda: requested) == ceiling
    service = ExecService(execution_profile=ceiling, execution_profile_provider=lambda: requested)
    assert service.execution_profile == ceiling
    with pytest.raises(AttributeError, match="immutable ceiling"):
        service.execution_profile = requested
    with pytest.raises(TypeError, match="provider must return"):
        select_execution_profile(ceiling, lambda: None)  # type: ignore[arg-type,return-value]


@pytest.mark.parametrize("change,expected", [
    ("unknown", ("execution.baseline_unknown",)),
    ("same", ()),
    ("narrow", ()),
    ("read", ("execution.readable_expanded",)),
    ("write", ("execution.writable_expanded",)),
    ("network", ("execution.network_expanded",)),
    ("denial", ("execution.denial_reduced",)),
    ("denial_partial", ("execution.denial_reduced",)),
    ("denial_cover", ()),
    ("denied_current_root", ()),
    ("denial_outside_scope", ()),
])
def test_execution_authority_comparison_uses_effective_scope(tmp_path, change, expected):
    workspace = tmp_path / "workspace"
    secret = workspace / "secret"
    baseline = EffectiveExecutionProfile(
        readable_roots=(workspace,), writable_roots=(workspace / "output",),
        denied_roots=(secret,), network="restricted",
    )
    current = baseline
    if change == "unknown":
        baseline = None
    elif change == "narrow":
        current = EffectiveExecutionProfile(
            readable_roots=(workspace / "output",), writable_roots=(), network="denied",
        )
    elif change == "read":
        current = EffectiveExecutionProfile(
            readable_roots=(tmp_path,), writable_roots=baseline.writable_roots,
            denied_roots=(secret,), network="restricted",
        )
    elif change == "write":
        current = EffectiveExecutionProfile(
            readable_roots=(workspace,), writable_roots=(workspace,),
            denied_roots=(secret,), network="restricted",
        )
    elif change == "network":
        current = EffectiveExecutionProfile(
            readable_roots=(workspace,), writable_roots=baseline.writable_roots,
            denied_roots=(secret,), network="allowed",
        )
    elif change == "denial":
        current = EffectiveExecutionProfile(
            readable_roots=(workspace,), writable_roots=baseline.writable_roots,
            network="restricted",
        )
    elif change in {"denial_partial", "denial_cover"}:
        current = EffectiveExecutionProfile(
            readable_roots=(workspace,), writable_roots=baseline.writable_roots,
            denied_roots=(secret / "child",) if change == "denial_partial" else (workspace,),
            network="restricted",
        )
    elif change == "denied_current_root":
        current = EffectiveExecutionProfile(
            readable_roots=(tmp_path / "outside",), writable_roots=(tmp_path / "outside",),
            denied_roots=(tmp_path / "outside",), network="denied",
        )
    elif change == "denial_outside_scope":
        baseline = EffectiveExecutionProfile(
            readable_roots=(workspace,), denied_roots=(tmp_path / "outside",), network="denied",
        )
        current = EffectiveExecutionProfile(readable_roots=(workspace,), network="denied")
    assert execution_profile_expansion_codes(current, baseline) == expected


def test_execution_scope_comparison_rejects_unbounded_roots(tmp_path):
    profile = EffectiveExecutionProfile(readable_roots=tuple(tmp_path / str(index) for index in range(65)))
    with pytest.raises(ValueError, match="root budget"):
        execution_profile_expansion_codes(profile, None)


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
