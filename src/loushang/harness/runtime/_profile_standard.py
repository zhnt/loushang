"""Canonical capability slots shared by Agent-backed Products."""

from __future__ import annotations

from loushang.harness.runtime._profile_types import (
    RuntimeCapabilitySlot,
)

CONVERSATION_STORE_SLOT = RuntimeCapabilitySlot(
    key="conversation.store",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="sealed",
    allowed_sources=frozenset({"product", "oem"}),
)
AGENT_TRANSCRIPT_PROFILE_SLOT = RuntimeCapabilitySlot(
    key="agent.transcript_profile",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="sealed",
    allowed_sources=frozenset({"product", "oem"}),
)
CONTEXT_COMPACTION_SLOT = RuntimeCapabilitySlot(
    key="context.compaction",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="turn",
    allowed_sources=frozenset({"product", "oem", "extension", "session"}),
)
RESOURCE_RUNTIME_SLOT = RuntimeCapabilitySlot(
    key="resource.runtime",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="workspace",
    refresh_boundary="sealed",
    allowed_sources=frozenset({"product", "oem"}),
)
PROMPT_SECTIONS_SLOT = RuntimeCapabilitySlot(
    key="prompt.sections",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="turn",
    allowed_sources=frozenset({"product", "oem", "extension", "session"}),
)
SKILL_ACTIVATION_SLOT = RuntimeCapabilitySlot(
    key="skill.activation",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="turn",
    allowed_sources=frozenset({"product", "oem", "extension", "session"}),
)
TOOL_PACKS_SLOT = RuntimeCapabilitySlot(
    key="tool.packs",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="turn",
    allowed_sources=frozenset({"product", "oem", "extension"}),
)
COMMAND_PACKS_SLOT = RuntimeCapabilitySlot(
    key="command.packs",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="turn",
    allowed_sources=frozenset({"product", "oem", "extension"}),
)
SIDE_QUESTION_PROVIDER_SLOT = RuntimeCapabilitySlot(
    key="interaction.side_question",
    shape="single",
    variation_semantic="exclusive_replacement",
    scope="session",
    refresh_boundary="sealed",
    allowed_sources=frozenset({"product", "oem", "extension"}),
    required=False,
)
CONTINUITY_PROVIDER_PACKS_SLOT = RuntimeCapabilitySlot(
    key="continuity.provider_packs",
    shape="ordered",
    variation_semantic="aggregate_contribution",
    scope="process",
    refresh_boundary="sealed",
    allowed_sources=frozenset({"product", "oem"}),
    required=False,
)


def standard_agent_session_slots() -> tuple[RuntimeCapabilitySlot, ...]:
    """Return fresh declarations for the first three shared session slots."""

    return (
        CONVERSATION_STORE_SLOT,
        AGENT_TRANSCRIPT_PROFILE_SLOT,
        CONTEXT_COMPACTION_SLOT,
    )


def standard_capability_composition_slots() -> tuple[RuntimeCapabilitySlot, ...]:
    """Return fresh declarations for shared Product capability composition."""

    return (
        RESOURCE_RUNTIME_SLOT,
        PROMPT_SECTIONS_SLOT,
        SKILL_ACTIVATION_SLOT,
        TOOL_PACKS_SLOT,
        COMMAND_PACKS_SLOT,
        SIDE_QUESTION_PROVIDER_SLOT,
        CONTINUITY_PROVIDER_PACKS_SLOT,
    )


def standard_runtime_capability_slots() -> tuple[RuntimeCapabilitySlot, ...]:
    """Return the complete standard Runtime Capability semantic inventory."""

    return standard_agent_session_slots() + standard_capability_composition_slots()
