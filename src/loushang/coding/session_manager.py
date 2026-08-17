from __future__ import annotations

from dataclasses import replace

from loushang.coding.product_plan import (
    CODING_CAPABILITY_PROFILE,
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
    CODING_PRODUCT_ID,
    CODING_TRANSCRIPT_RUNTIME,
)
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import ConversationHeader
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ResolvedRuntimeProfile,
    RuntimeProfileBinding,
    RuntimeProfileSnapshot,
    RuntimeProfileSnapshotCapability,
)
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptSessionFactory,
    ProductTranscriptSession,
)

_LIFECYCLE = AgentTranscriptLifecycle(
    bind_runtime=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle
)


def _coding_header_metadata(
    runtime_profile: ResolvedRuntimeProfile,
) -> dict[str, JSONValue]:
    capability_snapshot = CODING_CAPABILITY_PROFILE.snapshot()
    return {
        **CODING_TRANSCRIPT_RUNTIME.snapshot_metadata(runtime_profile),
        CODING_CAPABILITY_PROFILE_METADATA_KEY: (
            replace(
                capability_snapshot,
                capabilities=tuple(
                    capability
                    for capability in capability_snapshot.capabilities
                    if capability.slot != SIDE_QUESTION_PROVIDER_SLOT.key
                ),
            ).to_json()
        ),
    }


def _validate_coding_restored_header(
    header: ConversationHeader,
    runtime_profile: ResolvedRuntimeProfile,
    persist: bool,
) -> None:
    CODING_TRANSCRIPT_RUNTIME.validate_snapshot(
        header.metadata,
        runtime_profile,
        require_current=persist,
    )
    raw_capability_snapshot = header.metadata.get(
        CODING_CAPABILITY_PROFILE_METADATA_KEY
    )
    if raw_capability_snapshot is None:
        return
    capability_snapshot = RuntimeProfileSnapshot.from_json(raw_capability_snapshot)
    if capability_snapshot.product_id != CODING_PRODUCT_ID:
        raise ValueError(
            "Coding cannot resume a session with a capability profile for Product "
            f"{capability_snapshot.product_id!r}"
        )
    current_capability_snapshot = CODING_CAPABILITY_PROFILE.snapshot()
    if persist and _selected_capabilities(
        capability_snapshot,
        current=current_capability_snapshot,
    ) != _selected_capabilities(
        current_capability_snapshot,
        current=current_capability_snapshot,
    ):
        raise ValueError(
            "Coding cannot resume a session with an unsupported capability profile"
        )


def _selected_capabilities(
    snapshot: RuntimeProfileSnapshot,
    *,
    current: RuntimeProfileSnapshot,
) -> tuple[RuntimeProfileSnapshotCapability, ...]:
    """Compare continuity-critical slots; auxiliary interaction is additive."""

    current_capabilities = {
        capability.slot: capability for capability in current.capabilities
    }
    return tuple(
        replace(
            capability,
            shape=current_capabilities[capability.slot].shape,
            variation_semantic=current_capabilities[
                capability.slot
            ].variation_semantic,
        )
        if capability.variation_semantic is None
        and capability.slot in current_capabilities
        else capability
        for capability in snapshot.capabilities
        if capability.selections
        and capability.slot != SIDE_QUESTION_PROVIDER_SLOT.key
    )


def _resolve_coding_binding_input(persist: bool) -> ResolvedRuntimeProfile:
    return CODING_TRANSCRIPT_RUNTIME.resolve(persist=persist)


_FACTORY = AgentTranscriptSessionFactory(
    lifecycle=_LIFECYCLE,
    resolve_binding_input=_resolve_coding_binding_input,
    header_metadata=_coding_header_metadata,
    validate_restored_header=_validate_coding_restored_header,
    session_file_factory=_LIFECYCLE.default_jsonl_session_file,
)


class SessionManager(
    ProductTranscriptSession[ResolvedRuntimeProfile, RuntimeProfileBinding]
):
    """Coding binding over the Harness-owned Agent transcript session API."""

    @classmethod
    def _session_factory(
        cls,
    ) -> AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile,
        RuntimeProfileBinding,
    ]:
        return _FACTORY

    @property
    def runtime_profile(self) -> ResolvedRuntimeProfile:
        return self._lifecycle_session.product_binding.profile

    def _fork_binding_input(self) -> ResolvedRuntimeProfile:
        return self.runtime_profile

    def get_runtime_capability(self, slot: str) -> object | tuple[object, ...]:
        return self._lifecycle_session.product_binding.value(slot)


__all__ = ["SessionManager"]
