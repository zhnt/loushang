"""Product-neutral permission profiles over Policy and execution ceilings.

A permission profile is the Product-selected authority ceiling for a
session; it is not an approval permissions snapshot
(`loushang.harness.approval.grants.ApprovalPermissionsSnapshot`) or an
effective execution profile
(`loushang.harness.authorization.EffectiveExecutionProfile`). See the
terminology conventions in policy-approval-redesign.md section 7.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.policy import (
    PolicyDecision,
    PolicyEvaluator,
    PolicySubject,
    evaluate_policy,
)

PermissionProfileId = Literal["cautious", "standard", "full_access"]
PermissionProfileScope = Literal["session", "project", "user"]
ApprovalBehavior = Literal["cautious", "policy", "allow_optional"]
WorkspaceAccess = Literal["managed_workspace", "managed_ceiling"]
NetworkAccess = Literal["policy", "managed_ceiling"]
SandboxPreference = Literal["configured"]

_PROFILE_ORDER: tuple[PermissionProfileId, ...] = (
    "cautious",
    "standard",
    "full_access",
)


@dataclass(frozen=True, slots=True)
class PermissionProfile:
    """One user-facing mode without weakening managed Policy or execution limits."""

    profile_id: PermissionProfileId
    label: str
    description: str
    approval_behavior: ApprovalBehavior
    workspace_access: WorkspaceAccess
    network_access: NetworkAccess
    sandbox_preference: SandboxPreference = "configured"


@dataclass(frozen=True, slots=True)
class PermissionProfileCeiling:
    """Maximum trust level admitted by a Product or managed environment."""

    maximum_profile: PermissionProfileId = "full_access"
    reason: str | None = None

    def allows(self, profile_id: PermissionProfileId) -> bool:
        return _profile_rank(profile_id) <= _profile_rank(self.maximum_profile)


@dataclass(frozen=True, slots=True)
class PermissionProfileOption:
    profile: PermissionProfile
    current: bool
    enabled: bool
    disabled_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionProfileSnapshot:
    requested_profile_id: PermissionProfileId
    effective_profile: PermissionProfile
    ceiling: PermissionProfileCeiling
    options: tuple[PermissionProfileOption, ...]


BUILTIN_PERMISSION_PROFILES: tuple[PermissionProfile, ...] = (
    PermissionProfile(
        profile_id="standard",
        label="Standard",
        description=(
            "Run normal workspace work without interruption; ask for deletion, "
            "publishing, privilege, secrets, and external side effects."
        ),
        approval_behavior="policy",
        workspace_access="managed_workspace",
        network_access="policy",
    ),
    PermissionProfile(
        profile_id="cautious",
        label="Cautious",
        description=(
            "Also ask before direct workspace writes and edits; managed Policy "
            "and execution limits still apply."
        ),
        approval_behavior="cautious",
        workspace_access="managed_workspace",
        network_access="policy",
    ),
    PermissionProfile(
        profile_id="full_access",
        label="Full Access",
        description=(
            "Skip discretionary approval prompts; managed denies, delegated "
            "ceilings, and configured sandbox limits still apply."
        ),
        approval_behavior="allow_optional",
        workspace_access="managed_ceiling",
        network_access="managed_ceiling",
    ),
)
_PROFILES_BY_ID = {
    profile.profile_id: profile for profile in BUILTIN_PERMISSION_PROFILES
}


def permission_profile(profile_id: PermissionProfileId | str) -> PermissionProfile:
    try:
        return _PROFILES_BY_ID[profile_id]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"unsupported permission profile: {profile_id!r}") from exc


def resolve_permission_profile(
    requested_profile_id: PermissionProfileId,
    ceiling: PermissionProfileCeiling | None = None,
) -> PermissionProfile:
    resolved_ceiling = ceiling or PermissionProfileCeiling()
    if resolved_ceiling.allows(requested_profile_id):
        return permission_profile(requested_profile_id)
    return permission_profile(resolved_ceiling.maximum_profile)


def permission_profile_snapshot(
    requested_profile_id: PermissionProfileId,
    ceiling: PermissionProfileCeiling | None = None,
) -> PermissionProfileSnapshot:
    resolved_ceiling = ceiling or PermissionProfileCeiling()
    effective = resolve_permission_profile(requested_profile_id, resolved_ceiling)
    return PermissionProfileSnapshot(
        requested_profile_id=requested_profile_id,
        effective_profile=effective,
        ceiling=resolved_ceiling,
        options=tuple(
            PermissionProfileOption(
                profile=profile,
                current=profile.profile_id == effective.profile_id,
                enabled=resolved_ceiling.allows(profile.profile_id),
                disabled_reason=(
                    None
                    if resolved_ceiling.allows(profile.profile_id)
                    else resolved_ceiling.reason
                    or (
                        "Disabled by the managed permission ceiling "
                        f"({resolved_ceiling.maximum_profile})."
                    )
                ),
            )
            for profile in BUILTIN_PERMISSION_PROFILES
        ),
    )


class PermissionProfileProvider(Protocol):
    def __call__(self) -> PermissionProfileId: ...


class PermissionCeilingProvider(Protocol):
    def __call__(self) -> PermissionProfileCeiling: ...


@dataclass(frozen=True, slots=True)
class PermissionProfilePolicyEvaluator:
    """Apply a live permission profile after managed Policy has evaluated."""

    policy: PolicyEvaluator
    profile_provider: PermissionProfileProvider
    ceiling_provider: PermissionCeilingProvider = PermissionProfileCeiling

    async def evaluate(self, subject: PolicySubject, /) -> PolicyDecision:
        decision = await evaluate_policy(self.policy, subject)
        managed = decision or PolicyDecision.allow()
        if managed.disposition == "deny":
            return managed
        profile = resolve_permission_profile(
            self.profile_provider(),
            self.ceiling_provider(),
        )
        if profile.approval_behavior == "allow_optional":
            return (
                PolicyDecision(
                    disposition="allow",
                    code=managed.code,
                )
                if managed.disposition == "ask"
                else managed
            )
        if (
            profile.approval_behavior == "cautious"
            and managed.disposition == "allow"
            and getattr(subject, "tool_name", None) in {"write", "edit"}
        ):
            return PolicyDecision.ask(
                "Cautious mode requires approval for workspace mutations",
                code="cautious_workspace_mutation",
            )
        return managed


def _profile_rank(profile_id: PermissionProfileId) -> int:
    try:
        return _PROFILE_ORDER.index(profile_id)
    except ValueError as exc:  # pragma: no cover - protected by Literal callers
        raise ValueError(f"unsupported permission profile: {profile_id!r}") from exc


__all__ = [
    "ApprovalBehavior",
    "BUILTIN_PERMISSION_PROFILES",
    "NetworkAccess",
    "PermissionProfile",
    "PermissionProfileCeiling",
    "PermissionProfileId",
    "PermissionProfileOption",
    "PermissionProfilePolicyEvaluator",
    "PermissionProfileScope",
    "PermissionProfileSnapshot",
    "SandboxPreference",
    "WorkspaceAccess",
    "permission_profile",
    "permission_profile_snapshot",
    "resolve_permission_profile",
]
