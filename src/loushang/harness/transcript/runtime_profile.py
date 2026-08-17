"""Runtime-profile binding for Conversation JSONL Agent transcripts.

The runtime composes the existing profile resolver, capability binder,
conversation stores, transcript profile, and compaction capability. Products
provide stable implementation identities and defaults without reimplementing
the binding or storage lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import cast

from loushang.foundation.json import JSONValue
from loushang.harness.conversation import (
    CURRENT_CONVERSATION_FORMAT_VERSION,
    ConversationHeader,
    ConversationKey,
    ConversationStore,
    MemoryConversationStore,
)
from loushang.harness.runtime import (
    ProductRuntimePlan,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    RuntimeProfileResolver,
    RuntimeProfileSnapshot,
    standard_agent_session_slots,
)
from loushang.harness.transcript.compaction import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    TURN_AWARE_SUMMARY_VERSION,
    AgentTranscriptCompactionCapability,
    create_agent_transcript_compaction_capability,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
)
from loushang.harness.transcript.lifecycle import (
    AgentTranscriptLifecycleContext,
    AgentTranscriptRuntimeBinding,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.types import AgentTranscriptRecord

_STORE_SLOT = "conversation.store"
_TRANSCRIPT_SLOT = "agent.transcript_profile"
_COMPACTION_SLOT = "context.compaction"


@dataclass(frozen=True)
class AgentTranscriptRuntimeSpec:
    """Product selections for the standard Agent transcript runtime."""

    product_id: str
    product_name: str
    metadata_key: str
    memory_namespace: str
    memory_store_implementation: str
    file_store_implementation: str
    transcript_profile_implementation: str
    compaction_implementation: str = TURN_AWARE_SUMMARY_IMPLEMENTATION
    compaction_implementation_version: int = TURN_AWARE_SUMMARY_VERSION
    compaction_config: Mapping[str, JSONValue] = field(
        default_factory=lambda: {
            "enabled": True,
            "compactPercent": 80.0,
            "reserveTokens": 8_192,
            "keepRecentTokens": 32_768,
        }
    )

    def __post_init__(self) -> None:
        for name in (
            "product_id",
            "product_name",
            "metadata_key",
            "memory_namespace",
            "memory_store_implementation",
            "file_store_implementation",
            "transcript_profile_implementation",
            "compaction_implementation",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.compaction_implementation_version) is not int:
            raise TypeError("compaction_implementation_version must be an integer")
        if self.compaction_implementation_version < 1:
            raise ValueError("compaction_implementation_version must be positive")
        object.__setattr__(self, "compaction_config", dict(self.compaction_config))


class AgentTranscriptProfileRuntime:
    """Resolve and bind one Product's standard Agent transcript profile."""

    def __init__(self, spec: AgentTranscriptRuntimeSpec) -> None:
        self.spec = spec
        self._binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(self._implementations())
        )

    def plan(self, *, persist: bool) -> ProductRuntimePlan:
        slots = tuple(
            replace(
                slot,
                allowed_sources=(
                    frozenset({"product", "oem"})
                    if slot.key == _COMPACTION_SLOT
                    else frozenset({"product"})
                ),
            )
            for slot in standard_agent_session_slots()
        )
        return ProductRuntimePlan(
            product_id=self.spec.product_id,
            slots=slots,
            defaults=(
                RuntimeCapabilitySelection(
                    slot=_STORE_SLOT,
                    implementation=(
                        self.spec.file_store_implementation
                        if persist
                        else self.spec.memory_store_implementation
                    ),
                    implementation_version=1,
                    config={"persistence": "file" if persist else "memory"},
                ),
                RuntimeCapabilitySelection(
                    slot=_TRANSCRIPT_SLOT,
                    implementation=self.spec.transcript_profile_implementation,
                    implementation_version=1,
                    config={
                        "format": "conversation-jsonl",
                        "formatVersion": CURRENT_CONVERSATION_FORMAT_VERSION,
                    },
                ),
                RuntimeCapabilitySelection(
                    slot=_COMPACTION_SLOT,
                    implementation=self.spec.compaction_implementation,
                    implementation_version=self.spec.compaction_implementation_version,
                    config=self.spec.compaction_config,
                ),
            ),
        )

    def resolve(self, *, persist: bool) -> ResolvedRuntimeProfile:
        return RuntimeProfileResolver().resolve(self.plan(persist=persist))

    def snapshot_metadata(
        self,
        profile: ResolvedRuntimeProfile,
    ) -> dict[str, JSONValue]:
        return {self.spec.metadata_key: profile.snapshot().to_json()}

    def read_snapshot(
        self,
        metadata: Mapping[str, JSONValue],
    ) -> RuntimeProfileSnapshot | None:
        raw_snapshot = metadata.get(self.spec.metadata_key)
        if raw_snapshot is None:
            return None
        snapshot = RuntimeProfileSnapshot.from_json(raw_snapshot)
        if snapshot.product_id != self.spec.product_id:
            raise ValueError(
                f"{self.spec.product_name} cannot resume a session with a runtime "
                f"profile for Product {snapshot.product_id!r}"
            )
        return snapshot

    def validate_snapshot(
        self,
        metadata: Mapping[str, JSONValue],
        profile: ResolvedRuntimeProfile,
        *,
        require_current: bool,
    ) -> RuntimeProfileSnapshot | None:
        snapshot = self.read_snapshot(metadata)
        current_snapshot = profile.snapshot()
        if (
            require_current
            and snapshot is not None
            and self._normalize_snapshot(snapshot, current=current_snapshot)
            != self._normalize_snapshot(current_snapshot, current=current_snapshot)
        ):
            raise ValueError(
                f"{self.spec.product_name} cannot resume a session with an "
                "unsupported runtime profile"
            )
        return snapshot

    def _normalize_snapshot(
        self,
        snapshot: RuntimeProfileSnapshot,
        *,
        current: RuntimeProfileSnapshot,
    ) -> RuntimeProfileSnapshot:
        """Canonicalize pre-release aliases without weakening profile checks."""

        current_capabilities = {
            capability.slot: capability for capability in current.capabilities
        }
        capabilities = []
        for capability in snapshot.capabilities:
            current_capability = current_capabilities.get(capability.slot)
            if (
                capability.variation_semantic is None
                and current_capability is not None
            ):
                capability = replace(
                    capability,
                    variation_semantic=current_capability.variation_semantic,
                )
            if capability.slot != _TRANSCRIPT_SLOT:
                capabilities.append(capability)
                continue
            selections = []
            for selection in capability.selections:
                if (
                    selection.implementation
                    == self.spec.transcript_profile_implementation
                    and selection.implementation_version == 1
                    and selection.config == {"format": "current"}
                ):
                    selection = replace(
                        selection,
                        config={
                            "format": "conversation-jsonl",
                            "formatVersion": CURRENT_CONVERSATION_FORMAT_VERSION,
                        },
                    )
                selections.append(selection)
            capabilities.append(
                replace(capability, selections=tuple(selections))
            )
        return replace(snapshot, capabilities=tuple(capabilities))

    async def bind_lifecycle(
        self,
        context: AgentTranscriptLifecycleContext,
        profile: ResolvedRuntimeProfile,
    ) -> AgentTranscriptRuntimeBinding[RuntimeProfileBinding]:
        binding = await self._binder.bind(profile, context=context)
        return AgentTranscriptRuntimeBinding(
            store=self.selected_store(binding),
            key=self.conversation_key(context),
            profile=self.selected_transcript_profile(binding),
            product_binding=binding,
            dispose=lambda: self._binder.dispose(binding),
        )

    def conversation_key(
        self,
        context: AgentTranscriptLifecycleContext,
    ) -> ConversationKey:
        return ConversationKey(
            namespace=(
                str(context.session_dir)
                if context.persist
                else self.spec.memory_namespace
            ),
            conversation_id=context.header.conversation_id,
        )

    def selected_store(
        self,
        binding: RuntimeProfileBinding,
    ) -> ConversationStore[ConversationHeader, AgentTranscriptRecord]:
        value = binding.value(_STORE_SLOT)
        if not isinstance(value, ConversationStore):
            raise TypeError(
                f"selected {self.spec.product_name} conversation store does not "
                "satisfy the port"
            )
        return cast(
            ConversationStore[ConversationHeader, AgentTranscriptRecord],
            value,
        )

    def selected_transcript_profile(
        self,
        binding: RuntimeProfileBinding,
    ) -> AgentTranscriptProfile:
        value = binding.value(_TRANSCRIPT_SLOT)
        if not isinstance(value, AgentTranscriptProfile):
            raise TypeError(
                f"selected {self.spec.product_name} transcript profile is invalid"
            )
        return value

    def _implementations(self) -> tuple[RuntimeCapabilityImplementation, ...]:
        return (
            RuntimeCapabilityImplementation(
                slot=_STORE_SLOT,
                implementation=self.spec.memory_store_implementation,
                implementation_version=1,
                create=self._create_memory_store,
            ),
            RuntimeCapabilityImplementation(
                slot=_STORE_SLOT,
                implementation=self.spec.file_store_implementation,
                implementation_version=1,
                create=self._create_file_store,
            ),
            RuntimeCapabilityImplementation(
                slot=_TRANSCRIPT_SLOT,
                implementation=self.spec.transcript_profile_implementation,
                implementation_version=1,
                create=self._create_transcript_profile,
            ),
            RuntimeCapabilityImplementation(
                slot=_COMPACTION_SLOT,
                implementation=self.spec.compaction_implementation,
                implementation_version=self.spec.compaction_implementation_version,
                create=self._create_compaction_capability,
            ),
        )

    def _create_memory_store(
        self,
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> ConversationStore[ConversationHeader, AgentTranscriptRecord]:
        del selection
        lifecycle_context = self._require_context(context)
        if lifecycle_context.persist:
            raise ValueError(
                f"the {self.spec.product_name} memory store is only valid for "
                "non-persistent runs"
            )
        return MemoryConversationStore(record_id=lambda record: record.record_id)

    def _create_file_store(
        self,
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> ConversationStore[ConversationHeader, AgentTranscriptRecord]:
        del selection
        lifecycle_context = self._require_context(context)
        if not lifecycle_context.persist or lifecycle_context.session_file is None:
            raise ValueError(
                f"the {self.spec.product_name} file store requires a persistent "
                "session context"
            )
        layout = AgentTranscriptFileLayout(lifecycle_context.session_dir)
        layout.bind_create_path(
            self.conversation_key(lifecycle_context),
            lifecycle_context.session_file,
        )
        return create_agent_transcript_file_store(layout)

    @staticmethod
    def _create_transcript_profile(
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> AgentTranscriptProfile:
        del selection, context
        return AgentTranscriptProfile.default()

    @staticmethod
    def _create_compaction_capability(
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> AgentTranscriptCompactionCapability:
        del context
        return create_agent_transcript_compaction_capability(
            implementation=selection.implementation,
            implementation_version=selection.implementation_version,
            config=selection.config,
        )

    @staticmethod
    def _require_context(
        context: object | None,
    ) -> AgentTranscriptLifecycleContext:
        if not isinstance(context, AgentTranscriptLifecycleContext):
            raise TypeError(
                "Agent transcript runtime factories require "
                "AgentTranscriptLifecycleContext"
            )
        return context


__all__ = [
    "AgentTranscriptProfileRuntime",
    "AgentTranscriptRuntimeSpec",
]
