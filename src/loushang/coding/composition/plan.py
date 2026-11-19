"""Coding's declarative selections for shared Product runtimes."""

from loushang.harness.capabilities import standard_capability_composition_plan
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    RuntimeProfileResolver,
)
from loushang.harness.transcript import (
    AgentTranscriptProfileRuntime,
    AgentTranscriptRuntimeSpec,
)

CODING_PRODUCT_ID = "coding"
CODING_RUNTIME_PROFILE_METADATA_KEY = "runtimeProfile"
CODING_CAPABILITY_PROFILE_METADATA_KEY = "capabilityProfile"

CODING_TRANSCRIPT_RUNTIME = AgentTranscriptProfileRuntime(
    AgentTranscriptRuntimeSpec(
        product_id=CODING_PRODUCT_ID,
        product_name="Coding",
        metadata_key=CODING_RUNTIME_PROFILE_METADATA_KEY,
        memory_namespace="coding.memory",
        memory_store_implementation="coding.memory",
        file_store_implementation="coding.file",
        transcript_profile_implementation="coding.agent_transcript",
    )
)

CODING_CAPABILITY_PLAN = standard_capability_composition_plan(
    product_id=CODING_PRODUCT_ID,
    slot_allowed_sources={
        SIDE_QUESTION_PROVIDER_SLOT.key: frozenset(
            {"product", "oem", "extension"}
        )
    },
)
CODING_CAPABILITY_PROFILE = RuntimeProfileResolver().resolve(CODING_CAPABILITY_PLAN)

__all__ = [
    "CODING_CAPABILITY_PLAN",
    "CODING_CAPABILITY_PROFILE",
    "CODING_CAPABILITY_PROFILE_METADATA_KEY",
    "CODING_PRODUCT_ID",
    "CODING_RUNTIME_PROFILE_METADATA_KEY",
    "CODING_TRANSCRIPT_RUNTIME",
]
