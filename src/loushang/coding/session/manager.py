from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from threading import Event
from typing import Self

from loushang.ai.types import UserMessage
from loushang.coding.composition.plan import (
    CODING_CAPABILITY_PROFILE,
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
    CODING_PRODUCT_ID,
    CODING_TRANSCRIPT_RUNTIME,
)
from loushang.coding.composition.provenance import (
    CODING_COMPOSITION_HEADER_KEY,
    composition_header_metadata,
    historical_composition_provenance,
    historical_startup_composition_record,
)
from loushang.coding.composition.sets import (
    CodingCompositionSetPlan,
    resolve_coding_composition_set,
)
from loushang.coding.resume.activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
    validate_coding_activation_attempt_record,
)
from loushang.coding.resume.activation_attempt_v2 import (
    CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE,
    CodingActivationAttemptV2,
    prepare_coding_activation_attempt_v2_record,
    validate_coding_activation_attempt_v2_record,
)
from loushang.coding.resume.activation_plan import (
    ActivationOwnerInputRefV1,
    ResumePlanStaleError,
    SessionActivationPlanV1,
    build_session_activation_plan,
    require_current_resume_plan_inputs,
    require_current_resume_plan_source,
)
from loushang.coding.resume.activation_projection_v2 import (
    find_input_records,
    project_coding_activation_attempt_path_v2,
    project_coding_activation_attempt_path_v2_async,
)
from loushang.coding.resume.binding import (
    CodingRuntimeBindingV1,
    coding_user_input_digest,
    freeze_coding_user_input,
    inspect_coding_runtime_binding,
    prepare_coding_resume_user_record,
)
from loushang.coding.resume.binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY,
    CodingRuntimeBindingV2,
    decode_coding_runtime_binding_v2,
    prepare_coding_resume_v2_user_record,
)
from loushang.coding.resume.history import (
    MAX_CODING_RESUME_HISTORY_BYTES,
    read_coding_resume_snapshot,
)
from loushang.coding.resume.input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
    coding_resume_input_record_digest,
)
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationRecord,
)
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ResolvedRuntimeProfile,
    RuntimeProfileBinding,
    RuntimeProfileSnapshot,
)
from loushang.harness.session.composition_evidence import (
    composition_identity_fields,
    composition_receipt_matches,
)
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptRecord,
    AgentTranscriptSessionFactory,
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
from loushang.harness.transcript.product_session import (
    _ApplicationProductTranscriptSession,
)
from loushang.harness.transcript.session_factory import SessionFileFactory
from loushang.harness.transcript.types import ExtensionData

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
    def input_binding_identity(
        metadata: Mapping[str, JSONValue],
    ) -> tuple[str, str] | None:
        binding = inspect_coding_runtime_binding(metadata).binding
        if binding is None and CODING_RUNTIME_BINDING_V2_METADATA_KEY in metadata:
            binding = decode_coding_runtime_binding_v2(metadata)
        if binding is None:
            return None
        return binding.session_id, binding.input_id

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
    find_input_records = staticmethod(find_input_records)

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
    _resume_recovery_error = CodingResumeRecoveryRequired
    _resume_label = "Coding Resume"
    _resume_writer_capabilities = _RESUME_WRITER_CAPABILITIES

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

        return await cls._load_verified_resume_writer(
            session_file,
            plan=plan,
            plan_type=SessionActivationPlanV1,
            required_writer_capabilities=required_writer_capabilities,
            factory=_factory,
            require_plan_inputs=lambda: require_current_resume_plan_inputs(
                plan, current_owner_inputs
            ),
            read_history=lambda path: read_coding_resume_snapshot(
                path,
                max_bytes=MAX_CODING_RESUME_HISTORY_BYTES,
                selected_leaf_id=plan.selected_leaf_id,
                expected_source_fingerprint=plan.source_fingerprint,
            ),
            require_plan_source=lambda history: require_current_resume_plan_source(
                plan, history
            ),
            rebuild_plan=lambda history: build_session_activation_plan(
                history,
                resolve_coding_composition_set(
                    plan.composition_comparison.candidate_set_id
                ),
                workspace_root=Path(plan.workspace_root),
                owner_inputs=plan.owner_inputs,
                owner_selections=plan.owner_selections,
            ),
            validate_historical_header=_validate_coding_restored_header,
            stale_error=ResumePlanStaleError,
        )

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
        observation = await self._lookup_resume_input_observation(
            input_id=query.input_id, expected_digest=query.record_digest, max_records=65536,
        )
        return CodingResumeInputLookupResultV1(query.input_id, *observation)

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
            CODING_COMPOSITION_HEADER_KEY: composition_identity_fields(
                provenance.set_id, provenance.plan_fingerprint
            )
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
        if not composition_receipt_matches(
            startup, provenance.set_id, provenance.plan_fingerprint
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
    store_root_observed: Event | None = None,
    session_file_factory: SessionFileFactory | None = None,
) -> AgentTranscriptSessionFactory[
    ResolvedRuntimeProfile,
    RuntimeProfileBinding,
]:
    """Create an application-owned factory; never replace the legacy singleton."""
    lifecycle = AgentTranscriptLifecycle(
        bind_runtime=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle,
        bind_runtime_owned=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle_owned,
    )
    if session_file_factory is None:
        session_file_factory = lifecycle.default_jsonl_session_file
    return AgentTranscriptSessionFactory(
        lifecycle=lifecycle,
        resolve_binding_input=_resolve_coding_binding_input,
        header_metadata=_coding_header_metadata,
        validate_restored_header=_validate_coding_restored_header,
        session_file_factory=session_file_factory,
        owned_product_id=CODING_PRODUCT_ID,
        store_state_root=store_state_root,
        store_root_observed=store_root_observed,
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

    class ApplicationSessionManager(
        _ApplicationProductTranscriptSession[
            ResolvedRuntimeProfile, RuntimeProfileBinding
        ],
        SessionManager,
    ):
        _application_factory = factory
        _transient_factory = transient

    return ApplicationSessionManager


__all__ = ["SessionManager"]


# Component entry names borrow the existing operations and retain old identities.
CODING_SESSION_TRANSCRIPT_LIFECYCLE = _LIFECYCLE
coding_session_header_metadata = _coding_header_metadata
resolve_coding_session_binding_input = _resolve_coding_binding_input
validate_coding_session_restored_header = _validate_coding_restored_header
bind_owned_coding_session_manager = _bind_owned_session_manager
create_owned_coding_session_factory = _create_owned_session_factory
