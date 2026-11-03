"""Coding's initial Resume continuation sequence over existing owner entries.

The Product caller obtains current admission/confirmation before invoking this
entry. Owner callbacks remain mandatory; this coordinator issues no authority,
settles no external effects and supplies no restart or automatic replay grant.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from loushang.agent import ThinkingLevel
from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import ImagePart, UserMessage
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionDecisionJournal,
    PluginExecutionJournalError,
)
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.transcript import AgentTranscriptSessionFactory
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
)
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

from ._capability_plugin_composition import CodingResumePluginParents
from ._product_capability_plugin_composition import (
    prepare_coding_product_approval_state_root,
)
from ._resume_cleanup import (
    CodingResumeContinuationCleanupFailure,
    retain_resume_cleanup_failure,
)
from .bootstrap import (
    BootstrapServices,
    NoToolsMode,
    _coding_capability_plugin_state_root,
    _create_resume_agent_session,
)
from .composition_sets import resolve_coding_composition_set
from .package_product_runtime import CodingFencedProductApplicationSelection
from .resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
)
from .resume_activation_attempt_v2 import (
    CodingActivationAttemptV2,
    prepare_coding_activation_attempt_v2_record,
)
from .resume_activation_plan import ActivationOwnerInputRefV1, SessionActivationPlanV1
from .resume_binding import (
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    inspect_coding_runtime_binding,
)
from .resume_binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY,
    CodingRuntimeBindingV2,
    decode_coding_runtime_binding_v2,
)
from .resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    coding_resume_input_record_digest,
)
from .session.agent_session import AgentSession
from .session_manager import SessionManager

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class CodingResumePreparedContinuation:
    """Original published Session awaiting its Product slot and model dispatch.

    The caller assumes the original Session's disposal responsibility on return.
    Adopting a Product slot still uses its existing lifecycle/Hosted binding owner.
    Input has been committed; callers must not resubmit it through normal prompt.
    """

    session: AgentSession
    attempt_id: str
    input_record_id: str
    input_lookup_query: CodingResumeInputLookupQueryV1


def _prepare_v2_plugin_parents(
    attempt: CodingActivationAttemptV2,
    *, worker_candidate_plugin_id: str | None,
) -> tuple[CodingResumePluginParents | None, ResumeEffectParentContextV1 | None]:
    owners = {owner.owner_id: owner for owner in attempt.effect_owners}
    plugin_ids = {
        "harness.plugin-execution",
        "harness.plugin-activation",
    }
    selected_plugin_ids = plugin_ids & owners.keys()
    if selected_plugin_ids and selected_plugin_ids != plugin_ids:
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    worker_owner_id = "harness.worker-activation"
    supported = plugin_ids | ({worker_owner_id} if worker_candidate_plugin_id else set())
    unsupported = set(owners) - supported
    if unsupported or attempt.effect_classes or any(
        owner.effect_classes for owner in attempt.effect_owners
    ):
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    worker_owner = owners.get(worker_owner_id)
    if (worker_candidate_plugin_id is None) != (worker_owner is None):
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    worker_parent = None
    if worker_owner is not None:
        if worker_owner.phases != ("reservation", "start"):
            raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
        worker_parent = attempt.parent_context(worker_owner)
    if not selected_plugin_ids:
        return None, worker_parent
    if (
        owners["harness.plugin-execution"].phases != ("declaration",)
        or owners["harness.plugin-activation"].phases != ("activation",)
    ):
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    return (
        CodingResumePluginParents(
            definition=attempt.parent_context(owners["harness.plugin-execution"]),
            activation=attempt.parent_context(owners["harness.plugin-activation"]),
        ),
        worker_parent,
    )


def _require_v2_native_writer_protocols(
    manager_type: type[SessionManager],
) -> None:
    """Negotiate all accepted v2 writers without opening any durable source."""

    manager_type._require_resume_writer_capabilities(
        frozenset({"coding.resume-continuation/v2"})
    )
    probe_root = Path.cwd().resolve(strict=False) / ".resume-protocol-probe"
    try:
        PluginExecutionDecisionJournal(
            probe_root / "definition-decisions.jsonl",
            scope_kind="workspace",
            scope_id="session:protocol-probe",
            required_writer_capabilities=frozenset(
                {"harness.plugin-execution.resume-context/v1"}
            ),
        )
        PluginActivationDecisionJournal(
            probe_root / "activation-decisions.jsonl",
            scope_id="session:protocol-probe",
            required_writer_capabilities=frozenset(
                {"harness.plugin-activation.resume-context/v1"}
            ),
        )
        WorkerActivationStateJournal(
            probe_root / "worker-activation-state.jsonl",
            required_writer_capabilities=frozenset(
                {"harness.worker-activation.resume-context/v1"}
            ),
        )
    except (
        PluginExecutionJournalError,
        PluginActivationJournalError,
        WorkerActivationStateJournalError,
    ) as error:
        raise CodingResumeRecoveryRequired(
            "writer.resume_protocol_unsupported"
        ) from error


async def prepare_coding_resume_continuation(
    *, manager_type: type[SessionManager], session_file: str | Path,
    plan: SessionActivationPlanV1,
    current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
    attempt: CodingActivationAttemptV1, input_record_id: str,
    text: str, created_at: datetime,
    require_current_admission: Callable[[CodingActivationAttemptV1], None],
    require_current_epoch_settlement: Callable[[CodingActivationAttemptV1, Mapping[str, object]], None],
    images: list[ImagePart] | None = None,
    services: BootstrapServices | None = None,
    model: Model | ModelSelection | None = None,
    thinking_level: ThinkingLevel | None = None,
    stream_fn: StreamFn | None = None,
    tools: list[ToolDefinition] | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    no_tools: NoToolsMode | bool | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    observe_input_identity: Callable[[CodingResumeInputLookupQueryV1], None] | None = None,
    product_owner_selection: CodingFencedProductApplicationSelection | None = None,
    resume_writer_factory: AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile,
        RuntimeProfileBinding,
    ]
    | None = None,
    worker_candidates: bool = False,
    worker_candidate_plugin_id: str | None = None,
) -> CodingResumePreparedContinuation:
    """Prepare one initial input, commit it once, then publish original owners.

    There is no retry, model dispatch or Product slot replacement here. Failure
    releases the undelivered original candidate/Writer without erasing history.
    Commit uncertainty requires original logical-input lookup, not another input.
    """

    if not isinstance(manager_type, type) or not issubclass(manager_type, SessionManager):
        raise TypeError("Coding Resume requires its original SessionManager type")
    if isinstance(attempt, CodingActivationAttemptV1) and type(attempt) not in {
        CodingActivationAttemptV1,
        CodingActivationAttemptV2,
    }:
        raise CodingResumeRecoveryRequired("writer.resume_protocol_unsupported")
    if product_owner_selection is not None and not isinstance(
        product_owner_selection, CodingFencedProductApplicationSelection,
    ):
        raise TypeError("Coding Resume Product application owner is invalid")
    if (
        type(worker_candidates) is not bool
        or (
            worker_candidate_plugin_id is not None
            and (
                not isinstance(worker_candidate_plugin_id, str)
                or not worker_candidate_plugin_id
                or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
            )
        )
        or ((worker_candidates or worker_candidate_plugin_id is not None) and product_owner_selection is None)
    ):
        raise ValueError("Coding Resume Worker requires its application Product owner")
    resume_plugin_parents: CodingResumePluginParents | None = None
    resume_worker_parent: ResumeEffectParentContextV1 | None = None
    if type(attempt) is CodingActivationAttemptV2:
        if worker_candidates and worker_candidate_plugin_id is None:
            raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
        resume_plugin_parents, resume_worker_parent = _prepare_v2_plugin_parents(
            attempt, worker_candidate_plugin_id=worker_candidate_plugin_id,
        )
        _require_v2_native_writer_protocols(manager_type)
    elif worker_candidate_plugin_id is not None:
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    if (
        not isinstance(plan, SessionActivationPlanV1)
        or not isinstance(attempt, CodingActivationAttemptV1)
        or plan.status != "needs_final_validation"
        or attempt.session_id != plan.session_id
        or attempt.original_leaf_id != plan.selected_leaf_id
        or attempt.ancestry_digest != plan.ancestry_digest
        or attempt.plan_fingerprint != plan.plan_id
    ):
        raise ValueError("Coding Resume attempt differs from its activation Plan")
    if type(input_record_id) is not str or _IDENTIFIER.fullmatch(input_record_id) is None:
        raise ValueError("Coding Resume input record identity is invalid")
    if input_record_id == attempt.attempt_id:
        raise ValueError("Coding Resume intent and input require distinct record identities")
    if not isinstance(text, str) or (not text.strip() and not images):
        raise ValueError("Coding Resume requires nonempty user input")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("Coding Resume timestamp must be timezone-aware")
    if any(not callable(check) or inspect.iscoroutinefunction(check) for check in (
        require_current_admission, require_current_epoch_settlement,
    )):
        raise TypeError("Coding Resume requires synchronous current owner checks")

    def checked(callback: Callable[[], None]) -> None:
        result = cast(Callable[[], object], callback)()
        if result is not None:
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("Coding Resume owner check must return None")

    def current() -> None:
        checked(lambda: require_current_admission(attempt))

    manager: SessionManager | None = None
    session: AgentSession | None = None
    resume_plugin_state_root: Path | None = None
    observed_input = False
    phase = "writer_preparation"
    current()  # Confirmation/current caller admission precedes Writer acquisition.
    try:
        manager = await manager_type._load_resume_writer(
            session_file, plan=plan, current_owner_inputs=current_owner_inputs,
            required_writer_capabilities=(
                frozenset({"coding.resume-continuation/v2"})
                if type(attempt) is CodingActivationAttemptV2
                else frozenset()
            ),
            _factory=resume_writer_factory,
        )
        with manager._lifecycle_session.sync_operation_scope():
            current()
            if any(record.record_id in {input_record_id, attempt.attempt_id} for record in manager.get_entries()):
                raise CodingResumeRecoveryRequired("input.record_identity_conflict")
            for record in manager.get_active_entries():
                existing = inspect_coding_runtime_binding(record.metadata).binding
                if (
                    existing is None
                    and CODING_RUNTIME_BINDING_V2_METADATA_KEY in record.metadata
                ):
                    existing = decode_coding_runtime_binding_v2(record.metadata)
                if (
                    existing is not None and existing.session_id == attempt.session_id
                    and existing.input_id == attempt.request_id
                ):
                    raise CodingResumeRecoveryRequired("input.recovery_required")
        phase = "intent_commit"
        await manager._commit_resume_activation_intent(
            prepare_coding_activation_attempt_v2_record(attempt, created_at=created_at)
            if type(attempt) is CodingActivationAttemptV2
            else prepare_coding_activation_attempt_record(attempt, created_at=created_at),
        )
        if resume_plugin_parents is not None:
            phase = "native_owner_enrollment"
            current()
            resume_plugin_state_root = prepare_coding_product_approval_state_root(
                _coding_capability_plugin_state_root(
                    manager, session_id=attempt.session_id
                )
            )
            resume_plugin_parents.enroll(
                session_id=attempt.session_id,
                state_root=resume_plugin_state_root,
                clock=lambda: int(created_at.timestamp() * 1000),
            )
            current()
        phase = "runtime_preparation"
        session = await _create_resume_agent_session(
            session_manager=manager, attempt_id=attempt.attempt_id,
            composition_set=resolve_coding_composition_set(plan.composition_comparison.candidate_set_id),
            require_current_admission=require_current_admission,
            services=services, model=model, thinking_level=thinking_level,
            stream_fn=stream_fn, tools=tools,
            output_capture_factory=output_capture_factory,
            no_tools=no_tools,
            approval_resolver=approval_resolver, tool_policy_evaluator=tool_policy_evaluator,
            product_owner_selection=product_owner_selection, worker_candidates=worker_candidates,
            worker_candidate_plugin_id=worker_candidate_plugin_id,
            resume_plugin_parents=resume_plugin_parents,
            resume_worker_parent=resume_worker_parent,
            resume_effect_owner_ids=(
                frozenset(owner.owner_id for owner in attempt.effect_owners)
                if type(attempt) is CodingActivationAttemptV2
                else None
            ),
        )
        receipt = await session._prepare_resume_runtime_graph(
            attempt_id=attempt.attempt_id, require_current_admission=require_current_admission,
        )
        if resume_plugin_parents is not None:
            phase = "native_owner_seal"
            current()
            assert resume_plugin_state_root is not None
            resume_plugin_parents.seal(
                session_id=attempt.session_id,
                state_root=resume_plugin_state_root,
                clock=lambda: int(created_at.timestamp() * 1000),
            )
            current()

        def settled() -> None:
            with manager._lifecycle_session.sync_operation_scope():
                current()
                candidate = session._coding_resume_candidate
                if candidate is None:
                    raise RuntimeError("Coding Resume candidate was not delivered")
                session._require_resume_candidate(candidate)
                current()
                session._require_resume_worker_effect_settlement(attempt)
                current()
                checked(lambda: require_current_epoch_settlement(attempt, receipt))
                current()
                session._require_resume_candidate(candidate)
                current()

        settled()  # Unsettled effects cannot proceed to first-input preparation.
        phase = "input_preparation"
        message = await session._prepare_resume_first_user_input(
            text, images=images, attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        settled()

        def binding(
            persisted: UserMessage,
        ) -> CodingRuntimeBindingV1 | CodingRuntimeBindingV2:
            if type(attempt) is CodingActivationAttemptV2:
                return CodingRuntimeBindingV2(
                    attempt_id=attempt.attempt_id, input_id=attempt.request_id,
                    record_id=input_record_id, session_id=attempt.session_id,
                    original_leaf_id=attempt.original_leaf_id,
                    ancestry_digest=attempt.ancestry_digest,
                    subject_digest=attempt.subject_digest,
                    origin_composition=plan.composition_comparison.origin,
                    planned_fingerprint=attempt.plan_fingerprint,
                    actual_fingerprint=attempt.epoch_fingerprint,
                    payload_digest=coding_user_payload_digest(persisted),
                    difference_codes=plan.composition_comparison.difference_codes,
                    intent_digest=attempt.digest,
                )
            return CodingRuntimeBindingV1(
                attempt_id=attempt.attempt_id, input_id=attempt.request_id,
                record_id=input_record_id, session_id=attempt.session_id,
                original_leaf_id=attempt.original_leaf_id,
                ancestry_digest=attempt.ancestry_digest, subject_digest=attempt.subject_digest,
                origin_composition=plan.composition_comparison.origin,
                planned_fingerprint=attempt.plan_fingerprint,
                actual_fingerprint=attempt.epoch_fingerprint,
                payload_digest=coding_user_payload_digest(persisted),
                difference_codes=plan.composition_comparison.difference_codes,
            )

        manager._stage_resume_first_user_input(
            message, prepare_binding=binding, created_at=created_at,
            original_leaf_id=attempt.original_leaf_id, ancestry_digest=attempt.ancestry_digest,
            attempt_id=attempt.attempt_id,
        )
        phase = "input_commit"
        record_id = await session._commit_resume_first_user_input(
            message, attempt_id=attempt.attempt_id, require_current_admission=require_current_admission,
        )
        _, committed_input = manager._require_committed_resume_input(attempt.attempt_id, record_id)
        query = CodingResumeInputLookupQueryV1(
            attempt.request_id, coding_resume_input_record_digest(committed_input),
        )
        observed_input = True  # A failing receiver must not receive this twice.
        if observe_input_identity is not None:
            checked(lambda: observe_input_identity(query))
        phase = "runtime_publication"
        await session._publish_resume_runtime(
            attempt_id=attempt.attempt_id, input_record_id=record_id,
            require_current_admission=require_current_admission,
            require_current_epoch_settlement=require_current_epoch_settlement,
        )
        return CodingResumePreparedContinuation(session, attempt.attempt_id, record_id, query)
    except BaseException as error:
        error.add_note(f"Coding Resume continuation failed during {phase}; no model was dispatched by this entry.")
        if isinstance(error, CodingResumeContinuationCleanupFailure):
            # Bootstrap already retains the complete candidate. Disposing its
            # Manager separately could release its Writer before graph cleanup.
            raise
        if phase in {"input_commit", "runtime_publication"}:
            error.add_note("Input may already be committed; use original input lookup before any explicit recovery.")
            if manager is not None and not observed_input and observe_input_identity is not None:
                proof = manager._resume_committed_input
                pending = manager._resume_first_input
                prepared_record = proof[1] if proof is not None else (
                    pending.prepared_record if pending is not None else None
                )
                if prepared_record is not None:
                    try:
                        recovery_query = CodingResumeInputLookupQueryV1(
                            attempt.request_id, coding_resume_input_record_digest(prepared_record),
                        )
                        checked(lambda: observe_input_identity(recovery_query))
                    except BaseException as observation_error:
                        error.add_note(f"Resume input identity delivery also failed: {observation_error!r}")
        try:
            if session is not None:
                await session.dispose()
            elif manager is not None:
                await manager.dispose_runtime_profile()
        except BaseException as cleanup_error:
            error.add_note(f"Original Coding Resume owner cleanup also failed: {cleanup_error!r}")
            original_owner = session if session is not None else manager
            assert original_owner is not None
            raise retain_resume_cleanup_failure(
                original_owner=original_owner, original_error=error,
                cleanup_error=cleanup_error,
            ) from error
        raise
