"""Canonical Product profiles for internal Coding agent invocations."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding._resource_catalog_shadow import (
    CODING_READ_ONLY_AGENT_RESOURCE_CATALOG_SOURCE_POLICY,
    CodingResourceCatalogSourcePolicy,
    canonical_coding_resource_catalog_source_policy,
)
from loushang.coding.composition_sets import CodingCompositionSetId


@dataclass(frozen=True, slots=True)
class CodingAgentInvocationProductProfile:
    """One complete Product-owned policy for a delegated Coding process."""

    profile_id: str
    composition_set_id: CodingCompositionSetId
    resource_catalog_source_policy: CodingResourceCatalogSourcePolicy
    include_base_tool_contribution: bool
    include_base_tool_claim_prompt: bool
    include_base_skill_contribution: bool
    include_base_command_contribution: bool
    include_configured_resource_plugins: bool
    include_lsp_provider: bool
    sandbox_workspace_writable: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id.strip()
            or self.profile_id != self.profile_id.strip()
        ):
            raise ValueError("Coding agent invocation profile id is invalid")
        canonical_coding_resource_catalog_source_policy(
            self.resource_catalog_source_policy
        )
        for value in (
            self.include_base_tool_contribution,
            self.include_base_tool_claim_prompt,
            self.include_base_skill_contribution,
            self.include_base_command_contribution,
            self.include_configured_resource_plugins,
            self.include_lsp_provider,
            self.sandbox_workspace_writable,
        ):
            if not isinstance(value, bool):
                raise TypeError("Coding agent invocation profile flags must be bools")


CODING_READ_ONLY_AGENT_INVOCATION_PRODUCT_PROFILE = CodingAgentInvocationProductProfile(
    profile_id="read-only-v1",
    composition_set_id="coding-standard",
    resource_catalog_source_policy=(
        CODING_READ_ONLY_AGENT_RESOURCE_CATALOG_SOURCE_POLICY
    ),
    include_base_tool_contribution=True,
    include_base_tool_claim_prompt=False,
    include_base_skill_contribution=False,
    include_base_command_contribution=False,
    include_configured_resource_plugins=False,
    include_lsp_provider=False,
    sandbox_workspace_writable=False,
)

_CODING_AGENT_INVOCATION_PRODUCT_PROFILES = {
    CODING_READ_ONLY_AGENT_INVOCATION_PRODUCT_PROFILE.profile_id: (
        CODING_READ_ONLY_AGENT_INVOCATION_PRODUCT_PROFILE
    )
}


def resolve_coding_agent_invocation_product_profile(
    profile_id: str,
) -> CodingAgentInvocationProductProfile:
    """Resolve one canonical internal invocation profile by exact id."""

    if not isinstance(profile_id, str) or profile_id != profile_id.strip():
        raise ValueError("Coding agent invocation profile id is invalid")
    try:
        return _CODING_AGENT_INVOCATION_PRODUCT_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Coding agent invocation profile: {profile_id!r}"
        ) from exc


def canonical_coding_agent_invocation_product_profile(
    profile: CodingAgentInvocationProductProfile,
) -> CodingAgentInvocationProductProfile:
    """Reject forged invocation profiles while retaining shared values."""

    if not isinstance(profile, CodingAgentInvocationProductProfile):
        raise TypeError("Coding agent invocation Product profile is invalid")
    canonical = _CODING_AGENT_INVOCATION_PRODUCT_PROFILES.get(profile.profile_id)
    if canonical is None or profile != canonical:
        raise ValueError("Coding agent invocation Product profile must be canonical")
    return canonical


__all__ = [
    "CODING_READ_ONLY_AGENT_INVOCATION_PRODUCT_PROFILE",
    "CodingAgentInvocationProductProfile",
    "canonical_coding_agent_invocation_product_profile",
    "resolve_coding_agent_invocation_product_profile",
]
