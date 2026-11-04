"""Frozen, non-widening effective authority for one execution attempt.

Implements the permission enforcer (§12.4) of
docs/internals/architecture/harness/policy-approval-redesign.md: resolves
the effective execution profile (readable/writable/denied roots, network
access) from policy and approval inputs, and constrains child or delegated
profiles so derived authority can only narrow, never widen. An effective
execution profile is enforcement state, not a permission profile
(`loushang.harness.permissions.PermissionProfile`); see the terminology
conventions in section 7.0.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from loushang.harness.approval import ApprovalDecision
from loushang.harness.policy import PolicyDecision

ExecutionNetworkAccess = Literal["denied", "restricted", "allowed"]

_NETWORK_RANK: dict[ExecutionNetworkAccess, int] = {
    "denied": 0,
    "restricted": 1,
    "allowed": 2,
}


@dataclass(frozen=True, slots=True)
class EffectiveExecutionProfile:
    """Frozen, sandbox-enforceable authority for one execution attempt."""

    readable_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...] = ()
    denied_roots: tuple[Path, ...] = ()
    network: ExecutionNetworkAccess = "allowed"
    policy_code: str | None = None
    approval_action_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("readable_roots", "writable_roots", "denied_roots"):
            object.__setattr__(self, name, _normalize_roots(getattr(self, name), name))
        if self.network not in _NETWORK_RANK:
            raise ValueError(f"unsupported execution network access: {self.network!r}")
        if any(
            not _covered(root, self.readable_roots)
            for root in self.writable_roots
        ):
            raise ValueError("writable roots must be covered by readable roots")


class ExecutionAuthorizationError(PermissionError):
    pass


class ExecutionProfileProvider(Protocol):
    """Trusted owner selection for the next action, before authority is frozen."""

    def __call__(self) -> EffectiveExecutionProfile: ...


def select_execution_profile(
    ceiling: EffectiveExecutionProfile,
    provider: ExecutionProfileProvider | None = None,
) -> EffectiveExecutionProfile:
    """Read live owner selection without exceeding a frozen deployment ceiling."""

    if provider is None:
        return ceiling
    selected = provider()
    if not isinstance(selected, EffectiveExecutionProfile):
        raise TypeError("execution profile provider must return an EffectiveExecutionProfile")
    return constrain_execution_profile(ceiling, selected)


def execution_profile_expansion_codes(
    current: EffectiveExecutionProfile,
    baseline: EffectiveExecutionProfile | None,
) -> tuple[str, ...]:
    """Compare bounded execution scopes without granting authority.

    A baseline may describe historical restrictions. Even an empty result is
    only a scope comparison: it proves neither a current actor, an Approval
    fact, managed Policy nor live filesystem/Sandbox enforcement.
    """

    if type(current) is not EffectiveExecutionProfile or (
        baseline is not None and type(baseline) is not EffectiveExecutionProfile
    ):
        raise TypeError("execution scope comparison requires a native profile")
    for profile in (current, baseline):
        if profile is None:
            continue
        if any(len(roots) > 64 for roots in (
            profile.readable_roots, profile.writable_roots, profile.denied_roots,
        )):
            raise ValueError("execution scope comparison exceeds its root budget")
    if baseline is None:
        return ("execution.baseline_unknown",)
    readable = tuple(root for root in current.readable_roots if not _covered(root, current.denied_roots))
    writable = tuple(root for root in current.writable_roots if not _covered(root, current.denied_roots))
    codes: list[str] = []
    if any(not _covered(root, baseline.readable_roots) for root in readable):
        codes.append("execution.readable_expanded")
    if any(not _covered(root, baseline.writable_roots) for root in writable):
        codes.append("execution.writable_expanded")
    if _NETWORK_RANK[current.network] > _NETWORK_RANK[baseline.network]:
        codes.append("execution.network_expanded")
    if any(
        not _covered(denied, current.denied_roots)
        and any(denied == root or denied.is_relative_to(root) or root.is_relative_to(denied)
                for root in (*readable, *writable))
        for denied in baseline.denied_roots
    ):
        codes.append("execution.denial_reduced")
    return tuple(sorted(codes))


def resolve_effective_execution_profile(
    *,
    ceiling: EffectiveExecutionProfile,
    decision: PolicyDecision,
    requested: EffectiveExecutionProfile | None = None,
    approval: ApprovalDecision | None = None,
    approval_action_id: str | None = None,
) -> EffectiveExecutionProfile:
    """Resolve Policy/Approval into a non-widening execution profile."""

    if decision.disposition == "deny":
        raise ExecutionAuthorizationError(decision.reason or "execution denied by policy")
    if decision.disposition == "ask" and (
        approval is None or approval.disposition != "allow"
    ):
        raise ExecutionAuthorizationError(
            (approval.reason if approval is not None else None)
            or decision.reason
            or "execution requires approval"
        )
    effective = constrain_execution_profile(ceiling, requested or ceiling)
    return replace(
        effective,
        policy_code=decision.code,
        approval_action_id=(
            approval_action_id if decision.disposition == "ask" else None
        ),
    )


def constrain_execution_profile(
    ceiling: EffectiveExecutionProfile,
    requested: EffectiveExecutionProfile,
) -> EffectiveExecutionProfile:
    """Intersect a requested profile with an immutable authority ceiling."""

    readable = _intersect_roots(ceiling.readable_roots, requested.readable_roots)
    writable = tuple(
        root
        for root in _intersect_roots(
            ceiling.writable_roots,
            requested.writable_roots,
        )
        if _covered(root, readable)
    )
    denied = _deduplicate_roots((*ceiling.denied_roots, *requested.denied_roots))
    network = min(
        (ceiling.network, requested.network),
        key=_NETWORK_RANK.__getitem__,
    )
    return EffectiveExecutionProfile(
        readable_roots=readable,
        writable_roots=writable,
        denied_roots=denied,
        network=network,
        policy_code=requested.policy_code,
        approval_action_id=requested.approval_action_id,
    )


def _normalize_roots(values: tuple[Path, ...], name: str) -> tuple[Path, ...]:
    if isinstance(values, (str, bytes, Path)):
        raise TypeError(f"{name} must be a sequence of paths")
    normalized: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{name} must contain absolute paths: {path}")
        path = path.resolve(strict=False)
        if path not in normalized:
            normalized.append(path)
    return tuple(normalized)


def _deduplicate_roots(values: tuple[Path, ...]) -> tuple[Path, ...]:
    result: list[Path] = []
    for value in values:
        path = Path(value).resolve(strict=False)
        if path not in result:
            result.append(path)
    return tuple(result)


def _intersect_roots(
    ceiling: tuple[Path, ...],
    requested: tuple[Path, ...],
) -> tuple[Path, ...]:
    intersections: list[Path] = []
    for ceiling_root in ceiling:
        for requested_root in requested:
            if requested_root == ceiling_root or requested_root.is_relative_to(
                ceiling_root
            ):
                candidate = requested_root
            elif ceiling_root.is_relative_to(requested_root):
                candidate = ceiling_root
            else:
                continue
            if not _covered(candidate, tuple(intersections)):
                intersections.append(candidate)
    return tuple(intersections)


def _covered(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)
