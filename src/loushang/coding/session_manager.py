from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Self

from loushang.ai.types import UserMessage
from loushang.coding.composition_provenance import (
    composition_header_metadata,
    pinned_composition_plan,
    startup_composition_record,
)
from loushang.coding.composition_sets import (
    CodingCompositionSetPlan,
    resolve_coding_composition_set,
)
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
    SessionSummary,
    TranscriptDeletionOwner,
)
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file,
    load_agent_transcript_header,
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
    async def new_with_composition(
        cls,
        *,
        session_dir: Path,
        cwd: str,
        composition_set: str = "coding-standard",
        persist: bool = True,
        parent_session: str | None = None,
        session_id: str | None = None,
        defer_materialization: bool = True,
    ) -> Self:
        """Pin a canonical Coding choice before transcript materialization."""

        plan = resolve_coding_composition_set(composition_set)
        return await cls.new(
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            parent_session=parent_session,
            session_id=session_id,
            additional_header_metadata=composition_header_metadata(plan),
            defer_materialization=defer_materialization,
        )

    async def append_message(
        self,
        message: object,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> str:
        if (
            self.persist
            and isinstance(message, UserMessage)
            and pinned_composition_plan(self.get_header().metadata) is not None
            and not getattr(self, "_coding_composition_ready", False)
        ):
            raise ValueError(
                "Coding Session composition startup is not prepared; "
                "prepare the Session before committing input"
            )
        return await super().append_message(message, metadata=metadata)

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

    def _fork_header_metadata(self) -> Mapping[str, JSONValue] | None:
        pinned = pinned_composition_plan(self.get_header().metadata)
        if pinned is None:
            if self.persist:
                raise ValueError(
                    "Coding Session has no proven composition choice; create a new Session"
                )
            return None
        return composition_header_metadata(pinned)

    def get_runtime_capability(self, slot: str) -> object | tuple[object, ...]:
        return self._lifecycle_session.product_binding.value(slot)

    def bind_new_composition_plan(
        self, plan: CodingCompositionSetPlan
    ) -> CodingCompositionSetPlan:
        """Seal the canonical creation choice before the first durable record."""

        self._coding_composition_ready = False
        pinned = pinned_composition_plan(self.get_header().metadata)
        if pinned is not None:
            return pinned
        if not self.persist:
            return plan
        try:
            self._transcript.bind_unmaterialized_header_metadata(
                composition_header_metadata(plan)
            )
        except RuntimeError as exc:
            raise ValueError(
                "Coding Session has no proven composition choice; create a new Session"
            ) from exc
        return plan

    def mark_composition_startup_prepared(self) -> None:
        pinned = pinned_composition_plan(self.get_header().metadata)
        if pinned is None:
            raise ValueError("Coding Session has no pinned composition plan")
        startup = startup_composition_record(self.get_entries())
        if startup is None:
            raise ValueError("Coding Session has no startup composition receipt")
        if (
            startup["setId"] != pinned.set_id
            or startup["planFingerprint"] != pinned.fingerprint
        ):
            raise ValueError("Coding Session startup receipt differs from its header")
        self._coding_composition_ready = True


def _create_owned_session_factory(
    *, store_state_root: Path | None = None,
    enroll_legacy_shared_store: bool = False,
) -> AgentTranscriptSessionFactory[
    ResolvedRuntimeProfile, RuntimeProfileBinding,
]:
    """Create an application-owned factory; never replace the legacy singleton."""
    lifecycle = AgentTranscriptLifecycle(
        bind_runtime=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle,
        bind_runtime_owned=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle_owned,
    )
    return AgentTranscriptSessionFactory(
        lifecycle=lifecycle,
        resolve_binding_input=_resolve_coding_binding_input,
        header_metadata=_coding_header_metadata,
        validate_restored_header=_validate_coding_restored_header,
        session_file_factory=lifecycle.default_jsonl_session_file,
        owned_product_id=CODING_PRODUCT_ID,
        store_state_root=store_state_root,
        enroll_legacy_shared_store=enroll_legacy_shared_store,
    )


def _bind_owned_session_manager(
    factory: AgentTranscriptSessionFactory[ResolvedRuntimeProfile, RuntimeProfileBinding],
) -> type[SessionManager]:
    """Reference the runtime's factory, with non-mutating disk preview loaders."""
    transient = AgentTranscriptSessionFactory(
        lifecycle=AgentTranscriptLifecycle(
            bind_runtime=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle,
            header_loader=partial(load_agent_transcript_header, read_only=True),
            snapshot_loader=partial(load_agent_transcript_file, read_only=True),
        ),
        index_writable=False,
        resolve_binding_input=_resolve_coding_binding_input,
        header_metadata=_coding_header_metadata,
        validate_restored_header=_validate_coding_restored_header,
    )

    class ApplicationSessionManager(SessionManager):
        @classmethod
        def _factory_for_persistence(
            cls, persist: bool,
        ) -> AgentTranscriptSessionFactory[ResolvedRuntimeProfile, RuntimeProfileBinding]:
            # The runtime owns admission/cleanup; this class is only a binding.
            factory._accepting()
            return factory if persist else transient

        @classmethod
        async def rename_session(cls, session_file: str | Path, name: str | None) -> SessionSummary:
            factory._accepting()
            context = factory._discover_owned_context(session_file)
            async with factory._owned_source(context) as source:
                manager = cls(lifecycle_session=source)
                await manager.append_session_info(name)
                return manager.get_session_summary()

        @classmethod
        async def delete_session(
            cls, session_file: str | Path, *, current_session_file: str | Path | None = None,
            maintenance_owner: TranscriptDeletionOwner | None = None,
        ) -> bool:
            # Transcript deletion is writer-owned. Attachments remain recoverable
            # for explicit maintenance, never deleted through a pathname fallback.
            if maintenance_owner is not None and maintenance_owner is not factory:
                raise ValueError("application transcript maintenance belongs to its original factory")
            return await factory.delete_transcript(session_file, current_session_file=current_session_file)

        async def create_branched_session(self, leaf_id: str) -> Path | None:
            raise ValueError("owned branching requires the Session-returning fork API")

    return ApplicationSessionManager


__all__ = ["SessionManager"]
