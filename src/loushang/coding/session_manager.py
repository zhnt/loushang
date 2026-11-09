from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Self

from loushang.ai.types import UserMessage
from loushang.coding.composition_provenance import (
    CODING_COMPOSITION_HEADER_KEY,
    composition_header_metadata,
    historical_composition_provenance,
    historical_startup_composition_record,
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
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationRecord,
)
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ResolvedRuntimeProfile,
    RuntimeProfileBinding,
    RuntimeProfileSnapshot,
)
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptLifecycleSession,
    AgentTranscriptRecord,
    AgentTranscriptSessionFactory,
    SessionSummary,
    TranscriptDeletionOwner,
)
from loushang.harness.transcript import (
    ProductTranscriptSession as ProductTranscriptSession,
)
from loushang.harness.transcript._resume_continuation import (
    _AsyncResumeProjector,
    _ResumeContinuationTranscript,
    _ResumePendingInput,
    _ResumeProjector,
)
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file,
    load_agent_transcript_header,
)
from loushang.harness.transcript.types import ExtensionData

from .resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
    validate_coding_activation_attempt_record,
)
from .resume_activation_attempt_v2 import (
    CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE,
    CodingActivationAttemptV2,
    prepare_coding_activation_attempt_v2_record,
    validate_coding_activation_attempt_v2_record,
)
from .resume_activation_plan import (
    ActivationOwnerInputRefV1,
    ResumePlanStaleError,
    SessionActivationPlanV1,
    build_session_activation_plan,
    require_current_resume_plan_inputs,
    require_current_resume_plan_source,
)
from .resume_activation_projection_v2 import (
    project_coding_activation_attempt_path_v2,
    project_coding_activation_attempt_path_v2_async,
)
from .resume_binding import (
    CodingRuntimeBindingV1,
    coding_user_input_digest,
    freeze_coding_user_input,
    inspect_coding_runtime_binding,
    prepare_coding_resume_user_record,
    validate_coding_runtime_binding_record,
)
from .resume_binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY,
    CodingRuntimeBindingV2,
    decode_coding_runtime_binding_v2,
    prepare_coding_resume_v2_user_record,
    validate_coding_resume_v2_user_record,
)
from .resume_history import (
    MAX_CODING_RESUME_HISTORY_BYTES,
    read_coding_resume_snapshot,
)
from .resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
    coding_resume_input_record_digest,
)


@dataclass(slots=True)
class _PendingResumeFirstInput:
    expected_message: UserMessage
    expected_message_digest: str
    prepare_binding: Callable[
        [UserMessage], CodingRuntimeBindingV1 | CodingRuntimeBindingV2
    ]
    created_at: datetime
    original_leaf_id: str | None
    commit_parent_id: str
    attempt_id: str
    attempt: CodingActivationAttemptV1
    revision: int
    ancestry_digest: str
    lock: asyncio.Lock
    expected_metadata: dict[str, JSONValue] | None = None
    prepared_record: AgentTranscriptRecord | None = None
    outcome_unknown: bool = False


_RESUME_WRITER_CAPABILITIES = frozenset({"coding.resume-continuation/v2"})


def _validate_resume_attempt_record(
    record: AgentTranscriptRecord,
) -> CodingActivationAttemptV1:
    payload = record.payload
    if (
        getattr(payload, "extension_type", None)
        == CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE
    ):
        return validate_coding_activation_attempt_v2_record(record)
    return validate_coding_activation_attempt_record(record)


def _prepare_resume_attempt_record(
    attempt: CodingActivationAttemptV1, *, created_at: datetime
) -> AgentTranscriptRecord:
    if type(attempt) is CodingActivationAttemptV2:
        return prepare_coding_activation_attempt_v2_record(
            attempt, created_at=created_at
        )
    if type(attempt) is CodingActivationAttemptV1:
        return prepare_coding_activation_attempt_record(attempt, created_at=created_at)
    raise TypeError("Coding Resume requires an exact supported intent version")


class _CodingResumeMessages:
    @staticmethod
    def freeze_input(message: UserMessage) -> UserMessage:
        return freeze_coding_user_input(message)

    @staticmethod
    def input_digest(message: UserMessage) -> str:
        return coding_user_input_digest(message)

    @staticmethod
    def record_digest(record: AgentTranscriptRecord) -> str:
        return coding_resume_input_record_digest(record)


class _CodingResumeRecords:
    @staticmethod
    def validate_attempt(record: AgentTranscriptRecord) -> CodingActivationAttemptV1:
        return _validate_resume_attempt_record(record)

    @staticmethod
    def prepare_attempt(
        attempt: CodingActivationAttemptV1, *, created_at: datetime
    ) -> AgentTranscriptRecord:
        return _prepare_resume_attempt_record(attempt, created_at=created_at)

    @staticmethod
    def prepare_first_input_record(
        pending: _ResumePendingInput[
            CodingActivationAttemptV1, CodingRuntimeBindingV1 | CodingRuntimeBindingV2
        ],
        persisted: UserMessage,
        *,
        read_session_id: Callable[[], str],
        resource_metadata: dict[str, JSONValue],
    ) -> AgentTranscriptRecord:
        binding = pending.prepare_binding(persisted)
        if type(binding) not in {
            CodingRuntimeBindingV1,
            CodingRuntimeBindingV2,
        }:
            raise TypeError("Coding Resume activation returned an invalid binding")
        if (
            binding.session_id != read_session_id()
            or binding.attempt_id != pending.attempt_id
            or binding.input_id != pending.attempt.request_id
            or binding.original_leaf_id != pending.original_leaf_id
            or binding.ancestry_digest != pending.ancestry_digest
            or binding.planned_fingerprint != pending.attempt.plan_fingerprint
            or binding.actual_fingerprint != pending.attempt.epoch_fingerprint
            or binding.subject_digest != pending.attempt.subject_digest
        ):
            raise ValueError("Coding Resume binding differs from selected history")
        if type(binding) is CodingRuntimeBindingV2:
            if type(pending.attempt) is not CodingActivationAttemptV2:
                raise ValueError("RuntimeBinding v2 requires its v2 intent")
            record = prepare_coding_resume_v2_user_record(
                binding,
                persisted,
                intent=pending.attempt,
                created_at=pending.created_at,
                resource_metadata=resource_metadata,
            )
        else:
            if type(pending.attempt) is not CodingActivationAttemptV1:
                raise ValueError("RuntimeBinding v1 cannot close a v2 intent")
            record = prepare_coding_resume_user_record(
                binding,
                persisted,
                commit_parent_id=pending.commit_parent_id,
                created_at=pending.created_at,
                resource_metadata=resource_metadata,
            )
        return record


class _CodingResumeHistory:
    @property
    def project(self) -> _ResumeProjector[CodingActivationAttemptV1]:
        return project_coding_activation_attempt_path_v2

    @property
    def project_async(self) -> _AsyncResumeProjector[CodingActivationAttemptV1]:
        return project_coding_activation_attempt_path_v2_async


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
    # The Header records the runtime that originally created the transcript.
    # Restoring a readable transcript must not require today's runtime,
    # capability, model, permission, or resource configuration to equal that
    # historical snapshot.  Current execution authority is established by the
    # new runtime after the history has been admitted.
    CODING_TRANSCRIPT_RUNTIME.validate_snapshot(
        header.metadata,
        runtime_profile,
        require_current=False,
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
    _ResumeContinuationTranscript[
        ResolvedRuntimeProfile,
        RuntimeProfileBinding,
        CodingActivationAttemptV1,
        CodingRuntimeBindingV1 | CodingRuntimeBindingV2,
        SessionActivationPlanV1,
    ]
):
    """Coding binding over the Harness-owned Agent transcript session API."""

    _resume_messages = _CodingResumeMessages()
    _resume_records = _CodingResumeRecords()
    _resume_history = _CodingResumeHistory()
    _resume_pending_type = _PendingResumeFirstInput
    _resume_recovery_error = CodingResumeRecoveryRequired
    _resume_label = "Coding Resume"

    def _require_ordinary_input_policy(self, message: object) -> None:
        if (
            self.persist
            and isinstance(message, UserMessage)
            and historical_composition_provenance(self.get_header().metadata)
            is not None
            and not getattr(self, "_coding_composition_ready", False)
        ):
            raise ValueError(
                "Coding Session composition startup is not prepared; "
                "prepare the Session before committing input"
            )

    @classmethod
    def _require_resume_writer_capabilities(
        cls, required_writer_capabilities: frozenset[str]
    ) -> None:
        """Negotiate Transcript wire support without acquiring or reading a source."""

        if type(required_writer_capabilities) is not frozenset or any(
            type(item) is not str for item in required_writer_capabilities
        ):
            raise TypeError("Resume Writer capabilities require exact strings")
        if not required_writer_capabilities <= _RESUME_WRITER_CAPABILITIES:
            raise CodingResumeRecoveryRequired("writer.resume_protocol_unsupported")

    @classmethod
    async def _load_resume_writer(
        cls,
        session_file: str | Path,
        *,
        plan: SessionActivationPlanV1,
        current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
        required_writer_capabilities: frozenset[str] = frozenset(),
        _factory: AgentTranscriptSessionFactory[
            ResolvedRuntimeProfile,
            RuntimeProfileBinding,
        ]
        | None = None,
    ) -> Self:
        """Prepare an isolated current Writer while keeping execution fenced.

        Only an application-owned factory can retain this preparation. Matching
        Plan inputs prove cache freshness, not live execution authorization.
        The activation coordinator must still admit owners and publish Runtime.
        """

        cls._require_resume_writer_capabilities(required_writer_capabilities)
        factory = cls._factory_for_persistence(True) if _factory is None else _factory
        if not isinstance(factory, AgentTranscriptSessionFactory):
            raise TypeError("Coding Resume Writer factory is invalid")
        if not factory.owns_persistent_sessions:
            raise ValueError(
                "Coding Resume Writer requires its application-owned factory"
            )
        if (
            not isinstance(plan, SessionActivationPlanV1)
            or plan.status != "needs_final_validation"
        ):
            raise ValueError(
                "Coding Resume Writer requires an available activation Plan"
            )
        require_current_resume_plan_inputs(plan, current_owner_inputs)
        context = factory._discover_owned_context(session_file)
        history = await settled_io(
            read_coding_resume_snapshot,
            context.session_file,
            max_bytes=MAX_CODING_RESUME_HISTORY_BYTES,
            selected_leaf_id=plan.selected_leaf_id,
            expected_source_fingerprint=plan.source_fingerprint,
        )
        require_current_resume_plan_source(plan, history)
        if (
            context.header != history.header_preview.header
            or context.cwd != plan.workspace_root
            or build_session_activation_plan(
                history,
                resolve_coding_composition_set(
                    plan.composition_comparison.candidate_set_id
                ),
                workspace_root=Path(plan.workspace_root),
                owner_inputs=plan.owner_inputs,
                owner_selections=plan.owner_selections,
            )
            != plan
        ):
            raise ResumePlanStaleError(
                "Coding Resume Writer Plan differs from current history"
            )
        binding = factory._resolve_binding_input(True)
        # Historical schemas and Product identity must remain valid. Current
        # equality belongs to the new epoch, not this immutable original Header.
        _validate_coding_restored_header(context.header, binding, False)
        result: list[Self] = []

        def project(
            session: AgentTranscriptLifecycleSession[RuntimeProfileBinding],
        ) -> None:
            manager = cls(lifecycle_session=session)
            manager._resume_runtime_publication_pending = True
            if tuple(manager.get_entries()) != history.records:
                raise ResumePlanStaleError(
                    "Coding Resume Writer history changed during acquisition"
                )
            if history.selected_leaf_id is not None:
                # Original Transcript branch selection is local read state.
                # Store restore's default last-record leaf is not the user's
                # verified selection and must not replace it during admission.
                manager.branch(history.selected_leaf_id)
            if (
                manager.leaf_id != history.selected_leaf_id
                or tuple(manager.get_active_entries()) != history.selected_records
            ):
                raise ResumePlanStaleError(
                    "Coding Resume Writer history changed during acquisition"
                )
            manager._resume_writer_plan = plan
            manager._creation_factory = factory
            result.append(manager)

        await factory._construct_owned(
            context, binding, restore=True, _projection=project
        )
        return result[0]

    def _require_resume_bootstrap_composition(
        self,
        attempt_id: str,
        composition: CodingCompositionSetPlan,
    ) -> CodingActivationAttemptV1:
        """Match the current candidate to this Writer's definitely committed Plan."""

        attempt = self._require_resume_runtime_preparation(attempt_id)
        plan = self._resume_committed_plan
        if plan is None or plan.plan_id != attempt.plan_fingerprint:
            raise CodingResumeRecoveryRequired("runtime.plan_unverified")
        if (
            not isinstance(composition, CodingCompositionSetPlan)
            or resolve_coding_composition_set(composition.set_id) != composition
            or composition.set_id != plan.composition_comparison.candidate_set_id
            or composition.fingerprint
            != plan.composition_comparison.candidate_fingerprint
        ):
            raise ValueError(
                "Coding Resume bootstrap composition differs from its Writer Plan"
            )
        return attempt

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

    def _publish_resume_runtime(self, attempt_id: str, record_id: str) -> None:
        """Finish the activation owner's synchronous publication after its checks."""

        self._require_committed_resume_input(attempt_id, record_id)
        if not self._resume_runtime_publication_pending or self.leaf_id != record_id:
            raise CodingResumeRecoveryRequired("runtime.publication_target_changed")
        self._coding_composition_ready = True
        self._resume_runtime_publication_pending = False

    async def lookup_resume_input(
        self,
        query: CodingResumeInputLookupQueryV1,
    ) -> CodingResumeInputLookupResultV1:
        """Observe a logical input using the existing Transcript authority owner.

        Selected ancestry includes records outside current model context. A
        missing local match remains unknown, including after service restart;
        only an exact staged record permits the original owner to prove absence.
        The caller must already hold current read authorization. No result
        admits retry, Runtime publication or model execution.
        """

        if not isinstance(query, CodingResumeInputLookupQueryV1):
            raise TypeError("Coding Resume lookup query is invalid")
        unknown = CodingResumeInputLookupResultV1(query.input_id, None, "unknown")
        if not self.persist or len(self._transcript.records) > 65536:
            return unknown
        session_id = self.get_header().conversation_id
        candidates: list[AgentTranscriptRecord] = []
        try:
            path = tuple(self._transcript.active_path())
            projection = project_coding_activation_attempt_path_v2(
                path, current_session_id=session_id
            )
            if projection.status == "unknown_version":
                return unknown
            for record in path:
                reserved = {
                    key
                    for key in record.metadata
                    if key.startswith("coding.runtimeBinding")
                }
                if reserved == {CODING_RUNTIME_BINDING_V2_METADATA_KEY}:
                    binding_v2 = decode_coding_runtime_binding_v2(record.metadata)
                    observed_binding: (
                        CodingRuntimeBindingV1 | CodingRuntimeBindingV2 | None
                    ) = binding_v2
                    if binding_v2.session_id == session_id:
                        intent = next(
                            (
                                _validate_resume_attempt_record(item)
                                for item in path
                                if item.record_id == binding_v2.attempt_id
                            ),
                            None,
                        )
                        if type(intent) is not CodingActivationAttemptV2:
                            raise ValueError("RuntimeBinding v2 intent is unavailable")
                        validate_coding_resume_v2_user_record(record, intent=intent)
                else:
                    observed_binding = inspect_coding_runtime_binding(
                        record.metadata
                    ).binding
                if (
                    observed_binding is None
                    or observed_binding.session_id != session_id
                    or observed_binding.input_id != query.input_id
                ):
                    continue
                if type(observed_binding) is CodingRuntimeBindingV1:
                    validate_coding_runtime_binding_record(
                        record, expected_session_id=session_id
                    )
                candidates.append(record)
        except ValueError:
            return unknown
        pending = self._resume_first_input
        if (
            not candidates
            and isinstance(pending, _PendingResumeFirstInput)
            and pending.attempt.request_id == query.input_id
            and pending.prepared_record is not None
        ):
            candidates.append(pending.prepared_record)
        if not candidates:
            return unknown
        if (
            len(candidates) != 1
            or coding_resume_input_record_digest(candidates[0]) != query.record_digest
        ):
            return CodingResumeInputLookupResultV1(query.input_id, None, "conflict")
        observed = await self.lookup_prebuilt_user_message(candidates[0])
        return CodingResumeInputLookupResultV1(
            query.input_id, observed.record_id, observed.status
        )

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
        provenance = historical_composition_provenance(self.get_header().metadata)
        if provenance is None:
            # A legacy transcript may still be branched as transcript data.
            # Its fork remains unproven and cannot be opened as a Product
            # composition until a new Session is created with a sealed choice.
            return None
        return {
            CODING_COMPOSITION_HEADER_KEY: {
                "version": 1,
                "setId": provenance.set_id,
                "planFingerprint": provenance.plan_fingerprint,
            }
        }

    def get_runtime_capability(self, slot: str) -> object | tuple[object, ...]:
        return self._lifecycle_session.product_binding.value(slot)

    def bind_new_composition_plan(
        self, plan: CodingCompositionSetPlan
    ) -> CodingCompositionSetPlan:
        """Seal the canonical creation choice before the first durable record."""

        self._coding_composition_ready = False
        if self.persist:
            self.require_no_unsettled_resume_activation()
        provenance = historical_composition_provenance(self.get_header().metadata)
        if provenance is not None:
            if provenance.set_id != plan.set_id:
                raise ValueError(
                    "Coding Session is pinned to "
                    f"{provenance.set_id}; requested {plan.set_id}"
                )
            return plan
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
        if self.persist:
            self.require_no_unsettled_resume_activation()
        provenance = historical_composition_provenance(self.get_header().metadata)
        if provenance is None:
            raise ValueError("Coding Session has no pinned composition plan")
        startup = historical_startup_composition_record(self.get_entries())
        if startup is None:
            raise ValueError("Coding Session has no startup composition receipt")
        if (
            startup["setId"] != provenance.set_id
            or startup["planFingerprint"] != provenance.plan_fingerprint
        ):
            raise ValueError("Coding Session startup receipt differs from its header")
        self._coding_composition_ready = True

    @staticmethod
    def _activation_neutral_record(record: AgentTranscriptRecord) -> bool:
        # Only native immutable envelopes can extend a checked prefix. Nested
        # ordinary message/extension data cannot change activation classification;
        # new binding metadata and intent bodies require the full projector.
        if type(record) is not ConversationRecord:
            return False
        payload = record.payload
        if isinstance(payload, ExtensionData) and (
            type(payload) is not ExtensionData
            or payload.extension_type.startswith("coding.activation-attempt/")
        ):
            return False
        return not any(
            key.startswith("coding.runtimeBinding") for key in record.metadata
        )


def _create_owned_session_factory(
    *,
    store_state_root: Path | None = None,
    enroll_legacy_shared_store: bool = False,
) -> AgentTranscriptSessionFactory[
    ResolvedRuntimeProfile,
    RuntimeProfileBinding,
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
    factory: AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile, RuntimeProfileBinding
    ],
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
            cls,
            persist: bool,
        ) -> AgentTranscriptSessionFactory[
            ResolvedRuntimeProfile, RuntimeProfileBinding
        ]:
            # The runtime owns admission/cleanup; this class is only a binding.
            factory._accepting()
            return factory if persist else transient

        @classmethod
        async def rename_session(
            cls, session_file: str | Path, name: str | None
        ) -> SessionSummary:
            factory._accepting()
            context = factory._discover_owned_context(session_file)
            async with factory._owned_source(context) as source:
                manager = cls(lifecycle_session=source)
                await manager.append_session_info(name)
                return manager.get_session_summary()

        @classmethod
        async def delete_session(
            cls,
            session_file: str | Path,
            *,
            current_session_file: str | Path | None = None,
            maintenance_owner: TranscriptDeletionOwner | None = None,
        ) -> bool:
            # Transcript deletion is writer-owned. Attachments remain recoverable
            # for explicit maintenance, never deleted through a pathname fallback.
            if maintenance_owner is not None and maintenance_owner is not factory:
                raise ValueError(
                    "application transcript maintenance belongs to its original factory"
                )
            return await factory.delete_transcript(
                session_file, current_session_file=current_session_file
            )

        async def create_branched_session(self, leaf_id: str) -> Path | None:
            raise ValueError("owned branching requires the Session-returning fork API")

    return ApplicationSessionManager


__all__ = ["SessionManager"]
